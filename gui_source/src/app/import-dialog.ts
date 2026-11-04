import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  DatingResult,
  DuplicateGroup,
  ModifiedTimes,
  RemovingResult,
  bestGuessOf,
  byRecency,
  modifiedTimes,
  newestOf,
  removeFiles,
  FoundFile,
  FoundWork,
  ImportRequest,
  LONG_IMPORT_FILES,
  LibraryImports,
  MAX_IMPORT_WORKS,
  ToDate,
  UpdateScope,
  dateFiles,
  importLinks,
  inferDate,
  isFileDate,
  renamesFor,
  undatedFiles,
} from './imports';
import { Jobs } from './jobs';
import { Library } from './library';
import { LibraryStore } from './library-store';
import { inAo3Zone } from './preferences';

type Step = 'overview' | 'duplicates' | 'choose' | 'removing' | 'dates' | 'dating' | 'index' | 'formats';

/** what sifting by hand decided for one group: a file to keep, skipped, or its most recent */
/** what *Sort any remaining in bulk* can do with the rest */
export type BulkChoice = 'skip' | 'skip-remember' | 'recent';
export type SiftOutcome = { kind: 'pick'; path: string } | { kind: 'skip'; remember?: boolean } | { kind: 'recent' };

/** what to do with one group of duplicates */
export type DuplicateChoice = 'skip' | 'recent' | 'choose';

/** how many groups a page of the duplicates list holds */
export const DUPLICATES_PAGE_SIZE = 7;

/** how many rows a page of the dates list holds */
export const DATES_PAGE_SIZE = 7;

/** what to do with a set marked Keep most recent whose most recent cannot be told */
export type UndecidedHow = 'choose' | 'guess' | 'keep';

/** how long the removing page waits on that question before keeping every file of the set */
export const UNDECIDED_WAIT_MS = 5 * 60_000;

/** one set of duplicates as the removing page works through it */
type RemovalStep = { group: DuplicateGroup; remove: string[] } | { group: DuplicateGroup; undecided: true };

/**
 * Resolving what reading a library found: works with files but no index entry, and files with
 * no date in their name. One page per question, each passed over when it has nothing to ask:
 *
 * 1. **overview** - what was found, in a sentence each; nothing listed yet;
 * 2. **dates** - only with undated files: a date for each, one for all (*Use for all*), skips,
 *    or *Infer date*, which reads a date out of each name however it is written. Rows are by
 *    name, a page at a time or as one scrolling list;
 * 3. **dating** - the renames, with a bar; no going back from here, and closing stops it;
 * 4. **index** - only with unindexed works: fetch their entries from AO3 now?
 * 5. **formats** - other formats to download, and whether to replace a copy AO3 has a newer
 *    version of. Anything to do hands over to the run window (`start`), which asks the rest -
 *    background (a hosted copy), the login - as for any run.
 *
 * **Never while a run is going** (`busy`): the run reads and writes the library, and renaming
 * files under it - or a second run, which the helper refuses anyway - is not safe.
 */
@Component({
  selector: 'app-import-dialog',
  imports: [DecimalPipe],
  templateUrl: './import-dialog.html',
  styleUrl: './import-dialog.css',
})
export class ImportDialog {
  private readonly jobs = inject(Jobs);
  private readonly library = inject(Library);
  private readonly imports = inject(LibraryImports);

  readonly worksFound = input.required<FoundWork[]>({ alias: 'works' });
  /** undated files of works the index does have - offered for dating beside the rest */
  readonly undatedFound = input<FoundFile[]>([], { alias: 'undatedElsewhere' });
  /** works with more than one file in one format, offered before anything else */
  readonly duplicates = input<DuplicateGroup[]>([]);
  /** the files removed as duplicates here: gone from every page after */
  private readonly removedPaths = signal<ReadonlySet<string>>(new Set());
  /** what was found, less anything removed as a duplicate */
  protected readonly works = computed(() => {
    const removed = this.removedPaths();
    if (!removed.size) return this.worksFound();
    return this.worksFound()
      .map((w) => ({ ...w, files: w.files.filter((f) => !removed.has(f.path)) }))
      .filter((w) => w.files.length);
  });
  protected readonly undatedElsewhere = computed(() => {
    const removed = this.removedPaths();
    return this.undatedFound().filter((f) => !removed.has(f.path));
  });
  readonly store = input<LibraryStore | null>(null);
  /** the formats the helper offers, JSON among them */
  readonly formats = input<string[]>(['HTML', 'EPUB', 'PDF', 'MOBI', 'AZW3', 'JSON']);
  /**
   * A mock, from the DEBUG tab: the store is one in memory, and nothing reaches the real
   * library - exclusion lists are noted (`sandboxNotes`) instead of written, and no listing is
   * refreshed. Starting hands back the request, which the DEBUG tab shows rather than runs.
   */
  readonly sandbox = input(false);
  /** what a mock would have written to the exclusion lists, in words */
  readonly sandboxNoted = output<string>();
  /** a run is going: nothing may be renamed or started */
  readonly busy = input(false);
  /** how long the removing page waits for an answer about a set it cannot tell, before keeping it all */
  readonly answerWaitMs = input(UNDECIDED_WAIT_MS);

  /** closed without starting anything; `dated` is what was renamed, if anything */
  readonly closed = output<DatingResult | null>();
  /** start the import run with these */
  readonly start = output<{ request: ImportRequest; dated: DatingResult | null }>();
  /** 'No, never ask me again' chosen: neither this window nor the reminder, from now on */
  readonly askAgainChanged = output<boolean>();

  protected readonly step = signal<Step>('overview');

  /** every undated file, by name */
  protected readonly undated = computed(() =>
    [...undatedFiles(this.works()), ...this.undatedElsewhere()].sort((a, b) =>
      a.name.localeCompare(b.name),
    ),
  );
  protected readonly maxWorks = MAX_IMPORT_WORKS;
  /** how many files belong to works with no index entry, for the first page */
  protected readonly unindexedFiles = computed(() => this.works().reduce((n, w) => n + w.files.length, 0));

  // region duplicates

  /** each group's choice, by key; a group not here is skipped */
  protected readonly dupChoices = signal<Record<string, DuplicateChoice>>({});
  protected readonly dupPaged = signal(true);
  protected readonly dupPage = signal(0);
  protected readonly dupPageSize = DUPLICATES_PAGE_SIZE;
  protected readonly dupPages = computed(() => Math.max(1, Math.ceil(this.duplicates().length / this.dupPageSize)));
  protected readonly shownGroups = computed(() =>
    this.dupPaged()
      ? this.duplicates().slice(this.dupPage() * this.dupPageSize, (this.dupPage() + 1) * this.dupPageSize)
      : this.duplicates(),
  );
  protected readonly duplicateFiles = computed(() => this.duplicates().reduce((n, g) => n + g.files.length, 0));

  protected choiceOf(group: DuplicateGroup): DuplicateChoice {
    return this.dupChoices()[group.key] ?? 'skip';
  }

  protected setChoice(group: DuplicateGroup, choice: DuplicateChoice): void {
    this.dupChoices.update((c) => ({ ...c, [group.key]: choice }));
  }

  /** the buttons at the top: the same choice in every row, each still changeable after */
  protected chooseForAll(choice: DuplicateChoice): void {
    this.dupChoices.set(Object.fromEntries(this.duplicates().map((g) => [g.key, choice])));
  }

  protected setDupPaged(paged: boolean): void {
    this.dupPaged.set(paged);
    this.dupPage.set(Math.min(this.dupPage(), this.dupPages() - 1));
  }

  /**
   * When each duplicate file was last changed, by path - asked of the library once the window
   * has the duplicates, to tell apart two sharing the newest date. Unknown until it answers.
   */
  protected readonly modifiedAt = signal<ModifiedTimes>({});

  private readonly loadModified = effect(() => {
    const store = this.store();
    const paths = this.duplicates().flatMap((g) => g.files.map((f) => f.path));
    const known = untracked(this.modifiedAt);
    const wanted = paths.filter((p) => known[p] === undefined);
    if (!store || !wanted.length) return;
    void modifiedTimes(store, wanted).then((times) => {
      if (Object.keys(times).length) this.modifiedAt.update((m) => ({ ...m, ...times }));
    });
  });

  /** the newest file of a group, worked out once per group */
  protected readonly newest = computed(() => {
    const modified = this.modifiedAt();
    return new Map(this.duplicates().map((g) => [g.key, newestOf(g, modified)]));
  });

  protected newestIn(group: DuplicateGroup): FoundFile | null {
    return this.newest().get(group.key) ?? null;
  }

  protected dateIn(file: FoundFile): string {
    return inferDate(file.name);
  }

  /** the groups marked I'll choose on the list */
  protected readonly toChoose = computed(() => this.duplicates().filter((g) => this.choiceOf(g) === 'choose'));

  /**
   * Every group ever marked I'll choose, in the order it first was. Never shortened: a group
   * changed to something else on the list and back again returns to its own place, with what
   * was decided for it while sifting.
   */
  private readonly siftOrder = signal<string[]>([]);
  /** what was decided for each group while sifting, by key - kept apart from the list's choice */
  protected readonly siftOutcome = signal<Record<string, SiftOutcome>>({});
  /** the groups to sort through by hand: those marked I'll choose, in sifting order */
  protected readonly siftList = computed(() => {
    const byKey = new Map(this.toChoose().map((g) => [g.key, g]));
    return this.siftOrder().map((key) => byKey.get(key)).filter((g): g is DuplicateGroup => !!g);
  });
  protected readonly chooseAt = signal(0);
  protected readonly choosing = computed(() => this.siftList()[this.chooseAt()] ?? null);
  protected readonly undecidedCount = computed(
    () => this.siftList().filter((g) => !this.siftOutcome()[g.key]).length,
  );
  /** every group sorted through: the done note shows, and Continue is offered */
  protected readonly siftDone = computed(() => this.siftList().length > 0 && this.undecidedCount() === 0);
  /** the list's skipped groups go on the duplicates list, all their files kept - sifting says so per group */
  protected readonly rememberSkipped = signal(false);
  /** every row marked Skip: the step is skipped as a whole */
  protected readonly allSkipped = computed(() => this.duplicates().every((g) => this.choiceOf(g) === 'skip'));

  private note(said: string): void {
    this.sandboxNoted.emit(said);
  }

  /**
   * A group's files to choose from, the likeliest most recent first: by the date in each name
   * (undated last), then by when each file was last changed, then by name.
   */
  protected byRecency(group: DuplicateGroup): FoundFile[] {
    return byRecency(group, this.modifiedAt());
  }

  /**
   * Said above the top radio: *Most recent* when the dates (and change times) settle it,
   * otherwise that the top one is only our best guess.
   */
  protected topLabel(group: DuplicateGroup): string {
    return this.newestIn(group) ? 'Most recent' : "This is our best guess for 'most recent'";
  }

  /** what is known of one file, under its radio: the date in its name, and when it last changed */
  protected fileNotes(file: FoundFile): string[] {
    const date = this.dateIn(file);
    const at = this.modifiedAt()[file.path];
    const notes = [
      date ? `Filename dated ${date}` : 'No date included in the filename',
      at
        ? `File metadata updated at ${new Date(at).toLocaleString([], inAo3Zone({ dateStyle: 'medium', timeStyle: 'short' }))}`
        : 'File metadata updated at: unknown',
    ];
    return notes;
  }

  protected outcomeOf(group: DuplicateGroup): SiftOutcome | undefined {
    return this.siftOutcome()[group.key];
  }

  /**
   * The file picked to keep in a group: the one picked by hand, or - until anything is decided -
   * the top of the list, the most recent where that can be told. Skipped picks none.
   */
  protected pickedIn(group: DuplicateGroup): string {
    const outcome = this.outcomeOf(group);
    if (outcome?.kind === 'pick') return outcome.path;
    if (outcome) return '';
    return this.byRecency(group)[0]?.path ?? '';
  }

  private decide(group: DuplicateGroup, outcome: SiftOutcome): void {
    this.siftOutcome.update((o) => ({ ...o, [group.key]: outcome }));
  }

  /** a file picked to keep: this group is sorted */
  protected setPicked(group: DuplicateGroup, file: FoundFile): void {
    this.decide(group, { kind: 'pick', path: file.path });
  }

  /** on to the sifting: newly marked groups join the end, and it opens on the first undecided */
  protected fromDuplicates(): void {
    if (this.busy()) return;
    if (!this.toChoose().length) {
      void this.applyDuplicates();
      return;
    }
    const known = new Set(this.siftOrder());
    this.siftOrder.update((order) => [...order, ...this.toChoose().filter((g) => !known.has(g.key)).map((g) => g.key)]);
    const first = this.siftList().findIndex((g) => !this.outcomeOf(g));
    this.chooseAt.set(first < 0 ? 0 : first);
    this.step.set('choose');
  }

  protected previousEntry(): void {
    if (this.chooseAt() > 0) this.chooseAt.set(this.chooseAt() - 1);
  }

  /**
   * On to the next entry, keeping the file selected here - the top one, until another is picked.
   * From the last entry it goes to the first one still to sort, or the done note.
   */
  protected nextEntry(): void {
    const group = this.choosing();
    if (group && !this.outcomeOf(group)) {
      const top = this.pickedIn(group);
      if (top) this.decide(group, { kind: 'pick', path: top });
    }
    if (this.chooseAt() < this.siftList().length - 1) this.chooseAt.set(this.chooseAt() + 1);
    else this.toNextUndecided();
  }

  /**
   * This group skipped: every file kept - for now, or put on the duplicates list so it is not
   * asked about again. Like picking a file, it stays here until Next entry.
   */
  protected skipThis(group: DuplicateGroup, remember: boolean): void {
    this.decide(group, { kind: 'skip', remember });
  }

  protected skipRemembered(group: DuplicateGroup): boolean {
    const outcome = this.outcomeOf(group);
    return outcome?.kind === 'skip' && !!outcome.remember;
  }

  private toNextUndecided(): void {
    const list = this.siftList();
    const at = this.chooseAt();
    const after = [...list.keys()].slice(at + 1).concat([...list.keys()].slice(0, at));
    const next = after.find((i) => !this.outcomeOf(list[i]));
    if (next !== undefined) this.chooseAt.set(next);
  }

  /** what *Sort any remaining in bulk* offers, worded as the radios for one entry are */
  protected readonly bulkOptions: { value: BulkChoice; label: string }[] = [
    { value: 'skip', label: 'Skip for now' },
    { value: 'skip-remember', label: "Skip, don't ask again" },
    { value: 'recent', label: 'Keep most recent' },
  ];
  protected readonly bulkChoice = signal<BulkChoice | null>(null);

  /**
   * Every group not yet sorted: skipped (for now, or not to be asked about again), or its most
   * recent kept. Nothing is removed yet - the done note shows, and Continue goes on.
   */
  protected applyToRest(): void {
    const choice = this.bulkChoice();
    if (!choice) return;
    for (const group of this.siftList()) {
      if (this.outcomeOf(group)) continue;
      this.decide(group, choice === 'recent' ? { kind: 'recent' } : { kind: 'skip', remember: choice === 'skip-remember' });
    }
  }

  protected continueFromChoosing(): void {
    if (this.siftDone()) void this.applyDuplicates();
  }

  protected readonly removeProgress = signal<{ done: number; total: number }>({ done: 0, total: 0 });
  protected readonly removing = signal(false);
  protected readonly removed = signal<RemovingResult | null>(null);
  /**
   * Sets marked Keep most recent whose most recent could not be told, and kept whole - by the
   * answer, or because none came in time (`timedOut`). Offered again next time.
   */
  protected readonly undecided = signal<DuplicateGroup[]>([]);
  protected readonly timedOut = signal<ReadonlySet<string>>(new Set());
  /** sets settled by a best guess, and the file kept for each */
  protected readonly guessed = signal<{ group: DuplicateGroup; kept: FoundFile }[]>([]);
  private stopRemoving = false;

  // the question the removing page stops on, for a set it cannot tell
  protected readonly asking = signal<DuplicateGroup | null>(null);
  protected readonly askHow = signal<UndecidedHow | null>(null);
  protected readonly askPick = signal('');
  protected readonly askForOthers = signal<boolean | null>(null);
  /** how many more such sets come after this one */
  protected readonly askMore = signal(0);
  /** the answer given for all the others like it - asked once, then followed */
  protected readonly standing = signal<UndecidedHow | null>(null);
  private answered: ((how: UndecidedHow, path?: string) => void) | null = null;
  private answerTimer: ReturnType<typeof setTimeout> | null = null;
  protected readonly waitMinutes = computed(() => Math.max(1, Math.round(this.answerWaitMs() / 60_000)));
  protected readonly askReady = computed(() => {
    const how = this.askHow();
    if (!how) return false;
    if (how === 'choose' && !this.askPick()) return false;
    return this.standing() !== null || !this.askMore() || this.askForOthers() !== null;
  });

  /** what the best guess would keep for the set being asked about */
  protected guessFor(group: DuplicateGroup): FoundFile {
    return bestGuessOf(group, this.modifiedAt());
  }

  /**
   * What the choices come to, set by set in the list's order: the files to delete - never every
   * file of a set - or a set to ask about, one marked Keep most recent whose newest cannot be
   * told; and the sets kept as they are that go on the duplicates list (skipped, and told not
   * to ask again). Nothing is deleted before the removing page - sifting only decides.
   */
  private duplicatePlan(): { steps: RemovalStep[]; keep: { group: DuplicateGroup; kept: FoundFile[] }[] } {
    const steps: RemovalStep[] = [];
    const keep: { group: DuplicateGroup; kept: FoundFile[] }[] = [];
    const keepNewest = (group: DuplicateGroup) => {
      const newest = this.newestIn(group);
      steps.push(
        newest
          ? { group, remove: group.files.filter((f) => f !== newest).map((f) => f.path) }
          : { group, undecided: true },
      );
    };
    for (const group of this.duplicates()) {
      const choice = this.choiceOf(group);
      if (choice === 'skip') {
        if (this.rememberSkipped()) keep.push({ group, kept: group.files });
      } else if (choice === 'recent') {
        keepNewest(group);
      } else if (choice === 'choose') {
        const outcome = this.outcomeOf(group);
        if (outcome?.kind === 'recent') keepNewest(group);
        else if (outcome?.kind === 'pick' && group.files.some((f) => f.path === outcome.path)) {
          steps.push({ group, remove: group.files.filter((f) => f.path !== outcome.path).map((f) => f.path) });
        }
        // skipped while sorting by hand: kept, and on the duplicates list only when told so there
        else if (outcome?.kind === 'skip' && outcome.remember) keep.push({ group, kept: group.files });
        // never sorted: left as it is
      }
    }
    return { steps, keep };
  }

  /**
   * Remove what was chosen, on a page of its own, set by set; nothing to remove or ask about
   * goes straight on. A set it cannot tell stops the bar and asks (`askAbout`).
   */
  protected async applyDuplicates(): Promise<void> {
    const store = this.store();
    if (this.busy()) return;
    const plan = this.duplicatePlan();
    if (plan.keep.length) {
      try {
        if (this.sandbox()) this.note(`duplicates list: ${plan.keep.map((k) => k.group.key).join(', ')}`);
        else await this.imports.excludeDuplicates(plan.keep);
      } catch {
        // not written: they are offered again next time, which loses nothing
      }
    }
    if (!store || !plan.steps.length) {
      this.step.set(this.afterDuplicatesStep());
      return;
    }
    this.step.set('removing');
    const result: RemovingResult = { removed: [], failed: [] };
    this.removed.set(result);
    this.undecided.set([]);
    this.guessed.set([]);
    this.timedOut.set(new Set());
    this.standing.set(null);
    this.removing.set(true);
    this.stopRemoving = false;
    // a set still to ask about counts as all but one of its files, until the answer says
    let total = plan.steps.reduce((n, x) => n + ('remove' in x ? x.remove.length : x.group.files.length - 1), 0);
    let done = 0;
    this.removeProgress.set({ done, total });
    for (const [index, item] of plan.steps.entries()) {
      if (this.stopRemoving) break;
      let paths: string[];
      if ('remove' in item) {
        paths = item.remove;
      } else {
        const more = plan.steps.slice(index + 1).filter((x) => !('remove' in x)).length;
        const answer = await this.askAbout(item.group, more);
        if (this.stopRemoving) break;
        if (answer.how === 'keep') {
          this.undecided.update((u) => [...u, item.group]);
          total -= item.group.files.length - 1;
          this.removeProgress.set({ done, total });
          continue;
        }
        const kept =
          answer.how === 'guess'
            ? this.guessFor(item.group)
            : (item.group.files.find((f) => f.path === answer.path) ?? this.guessFor(item.group));
        if (answer.how === 'guess') this.guessed.update((g) => [...g, { group: item.group, kept }]);
        paths = item.group.files.filter((f) => f !== kept).map((f) => f.path);
      }
      const before = done;
      await removeFiles(
        store,
        paths,
        (d) => this.removeProgress.set({ done: before + d, total }),
        () => this.stopRemoving,
        result,
      );
      done = before + paths.length;
    }
    this.removedPaths.set(new Set(result.removed));
    this.removed.set({ ...result });
    this.removing.set(false);
    // the listing and what was found are brought up to date, so no removed file is offered again
    if (result.removed.length && !this.sandbox()) {
      try {
        await this.library.refreshAfterRun(result.removed, store);
      } catch {
        // the next read catches up
      }
      void this.imports.check();
    }
  }

  /**
   * Stop on a set whose most recent cannot be told and ask what to do: choose the file here, a
   * best guess (`bestGuessOf`), or keep them all - and, with more like it to come, whether to
   * do the same for those. An answer given for the others is followed without asking (a
   * remembered *choose* still shows the files). No answer within `answerWaitMs` keeps every
   * file of this set, which deletes nothing, and the next is asked again.
   */
  private askAbout(group: DuplicateGroup, more: number): Promise<{ how: UndecidedHow; path?: string }> {
    const standing = this.standing();
    if (standing === 'keep' || standing === 'guess') return Promise.resolve({ how: standing });
    return new Promise((resolve) => {
      this.asking.set(group);
      // a best guess is picked to begin with; a standing choose shows the files straight away
      this.askHow.set(standing === 'choose' ? 'choose' : 'guess');
      this.askPick.set('');
      this.askForOthers.set(null);
      this.askMore.set(more);
      this.answered = (how, path) => {
        if (this.answerTimer) clearTimeout(this.answerTimer);
        this.answerTimer = null;
        this.answered = null;
        this.asking.set(null);
        resolve({ how, path });
      };
      this.answerTimer = setTimeout(() => {
        this.timedOut.update((t) => new Set([...t, group.key]));
        this.answered?.('keep');
      }, this.answerWaitMs());
    });
  }

  protected answerAsked(): void {
    const how = this.askHow();
    if (!this.askReady() || !how || !this.answered) return;
    if (this.standing() === null && this.askForOthers()) this.standing.set(how);
    this.answered(how, how === 'choose' ? this.askPick() : undefined);
  }

  /** after the duplicates: the dates, when anything is undated, then the index question */
  private afterDuplicatesStep(): Step {
    return this.undated().length ? 'dates' : this.afterDatesStep();
  }

  protected fromRemoving(): void {
    this.step.set(this.afterDuplicatesStep());
  }

  // endregion

  // region dates

  /** the date typed or inferred for each undated file, by path; '' is none */
  protected readonly dates = signal<Record<string, string>>({});
  /** the files to leave undated, by path */
  protected readonly skipped = signal<Record<string, boolean>>({});
  /** the files whose date `Infer date` set, and has not been changed by hand since */
  protected readonly inferred = signal<Record<string, boolean>>({});
  /** the rows' order, by path - by name, until `Infer date` moves what it dated to the top */
  protected readonly order = signal<string[] | null>(null);
  protected readonly bulkDate = signal('');
  /** the skipped files go on the dates list, never to be offered for dating again */
  protected readonly rememberSkips = signal(false);
  protected readonly inferring = signal(false);
  /** what the last `Infer date` found: how many it dated, or null before it has run */
  protected readonly inferredCount = signal<number | null>(null);
  protected readonly paged = signal(true);
  protected readonly page = signal(0);
  protected readonly pageSize = DATES_PAGE_SIZE;

  protected readonly rows = computed(() => {
    const byPath = new Map(this.undated().map((f) => [f.path, f]));
    const order = this.order() ?? this.undated().map((f) => f.path);
    return order.map((path) => byPath.get(path)).filter((f): f is FoundFile => !!f);
  });
  protected readonly pages = computed(() => Math.max(1, Math.ceil(this.rows().length / this.pageSize)));
  protected readonly shownRows = computed(() =>
    this.paged()
      ? this.rows().slice(this.page() * this.pageSize, (this.page() + 1) * this.pageSize)
      : this.rows(),
  );

  protected dateOf(file: FoundFile): string {
    return this.dates()[file.path] ?? '';
  }

  protected isSkipped(file: FoundFile): boolean {
    return !!this.skipped()[file.path];
  }

  protected isInferred(file: FoundFile): boolean {
    return !!this.inferred()[file.path];
  }

  /** a date set by hand: no longer one `Infer date` worked out, though the row stays put */
  protected setDate(file: FoundFile, date: string): void {
    this.dates.update((d) => ({ ...d, [file.path]: date }));
    this.inferred.update((x) => ({ ...x, [file.path]: false }));
  }

  protected setSkipped(file: FoundFile, skip: boolean): void {
    this.skipped.update((s) => ({ ...s, [file.path]: skip }));
  }

  /** the one date put in every row - skips stay as they are, and can still be changed */
  protected applyToAll(): void {
    const date = this.bulkDate();
    if (!isFileDate(date)) return;
    this.dates.set(Object.fromEntries(this.undated().map((f) => [f.path, date])));
    this.inferred.set({});
  }

  protected skipAll(): void {
    this.skipped.set(Object.fromEntries(this.undated().map((f) => [f.path, true])));
  }

  /**
   * Read a date out of each file's name (`inferDate`), skipped files included - their date is
   * filled in, though skipped they stay. What it dated goes to the top: those not skipped, then
   * those skipped before it ran, each by name, then the rest by name.
   */
  protected async inferDates(): Promise<void> {
    if (this.inferring()) return;
    this.inferring.set(true);
    try {
      // a breath for the spinner, and another every so often over a long list
      await new Promise((resolve) => setTimeout(resolve, 0));
      const found: Record<string, string> = {};
      const files = this.undated();
      for (const [index, file] of files.entries()) {
        const date = inferDate(file.name);
        if (date) found[file.path] = date;
        if (index % 200 === 199) await new Promise((resolve) => setTimeout(resolve, 0));
      }
      this.dates.update((d) => ({ ...d, ...found }));
      this.inferred.set(Object.fromEntries(Object.keys(found).map((path) => [path, true])));
      const skipped = this.skipped();
      const byName = (a: FoundFile, b: FoundFile) => a.name.localeCompare(b.name);
      const dated = files.filter((f) => found[f.path]);
      this.order.set([
        ...dated.filter((f) => !skipped[f.path]).sort(byName),
        ...dated.filter((f) => skipped[f.path]).sort(byName),
        ...files.filter((f) => !found[f.path]).sort(byName),
      ].map((f) => f.path));
      this.inferredCount.set(dated.length);
      this.page.set(0);
    } catch {
      this.inferredCount.set(0);
    } finally {
      this.inferring.set(false);
    }
  }

  /** the files that will be renamed: given a real date, and not skipped */
  protected readonly toDate = computed(() =>
    this.undated().filter((f) => !this.skipped()[f.path] && isFileDate(this.dates()[f.path] ?? '')),
  );
  protected readonly bulkValid = computed(() => isFileDate(this.bulkDate()));

  protected setPaged(paged: boolean): void {
    this.paged.set(paged);
    this.page.set(Math.min(this.page(), this.pages() - 1));
  }

  // endregion

  // region dating

  protected readonly datingProgress = signal<{ done: number; total: number }>({ done: 0, total: 0 });
  protected readonly dating = signal(false);
  protected readonly dated = signal<DatingResult | null>(null);
  private stopDating = false;

  // endregion

  // region index and formats

  /** the works with no index entry: look them up now, later, or never offer them again */
  protected readonly lookup = signal<'yes' | 'later' | 'never'>('yes');
  /** which works the formats and replacing are for; `skip` does neither */
  protected readonly updateScope = signal<UpdateScope>('all');
  /** the formats to fetch for works without them - none ticked to begin with */
  protected readonly picked = signal<string[]>([]);
  protected readonly replaceOutdated = signal(false);
  /** every downloadable format the helper offers, JSON aside (always written: it is the index) */
  protected readonly offered = computed(() => this.formats().filter((x) => x !== 'JSON'));
  /** the formats the found files are already in, so the page can say so */
  protected readonly held = computed(() => {
    const held = new Set<string>();
    for (const file of [...this.works().flatMap((w) => w.files), ...this.undatedElsewhere()]) {
      held.add(file.format.toUpperCase());
    }
    return held;
  });

  /** the works with no index entry that are looked up now */
  protected readonly lookups = computed(() => (this.lookup() === 'yes' ? this.works().map((w) => w.id) : []));
  /**
   * The works with date issues that can be updated: an undated file, of an indexed work or of
   * one looked up now - a work left unindexed is left alone altogether.
   */
  protected readonly dateIssues = computed(() => {
    const looked = new Set(this.lookups());
    const indexed = new Set(this.works().map((w) => w.id));
    // a file of a work left out of the index question is dated, never looked up for an update
    const files = this.undated().filter((f) => !f.unindexed && (!indexed.has(f.id) || looked.has(f.id)));
    return [...new Set(files.map((f) => f.id))];
  });
  /** the works with an index issue that can be updated: those looked up now */
  protected readonly indexIssues = computed(() => this.lookups());
  /** every work with an issue that can be updated */
  protected readonly allIssues = computed(() => [...new Set([...this.indexIssues(), ...this.dateIssues()])]);
  /** the scope chosen, or every work when the one chosen is no longer offered */
  protected readonly scopeChosen = computed<UpdateScope>(() => {
    const scope = this.updateScope();
    if (scope === 'dates' && !this.dateIssues().length) return 'all';
    if (scope === 'index' && !this.indexIssues().length) return 'all';
    return scope;
  });
  /** the works the formats and replacing are for */
  protected readonly updating = computed(() => {
    switch (this.scopeChosen()) {
      case 'dates':
        return this.dateIssues();
      case 'index':
        return this.indexIssues();
      case 'skip':
        return [];
      default:
        return this.allIssues();
    }
  });
  /** whether anything is downloaded or replaced: an update chosen, and something to do */
  protected readonly updates = computed(
    () => this.updating().length > 0 && (this.picked().length > 0 || this.replaceOutdated()),
  );
  /** the works a run is over: those looked up, and those updated */
  protected readonly scope = computed(() => {
    const ids = new Set<string>(this.lookups());
    if (this.updates()) for (const id of this.updating()) ids.add(id);
    return [...ids].map((id) => ({ id, files: [] }));
  });
  /** how many files the window knows of for these works: their own unindexed files, and undated ones */
  private filesOf(ids: Iterable<string>): number {
    const wanted = new Set(ids);
    const paths = new Set<string>();
    for (const w of this.works()) if (wanted.has(w.id)) for (const f of w.files) paths.add(f.path);
    for (const f of this.undatedElsewhere()) if (wanted.has(f.id)) paths.add(f.path);
    return paths.size;
  }
  /** files of the works the index page asks about */
  protected readonly indexFiles = computed(() => this.filesOf(this.works().map((w) => w.id)));
  /** files of the works a run would go over */
  protected readonly scopeFiles = computed(() => this.filesOf(this.scope().map((w) => w.id)));
  protected readonly longImport = LONG_IMPORT_FILES;

  /** whether there is anything for a run to do: a lookup, or an update */
  protected readonly runs = computed(() => this.scope().length > 0);
  protected readonly tooMany = computed(() => this.scope().length > MAX_IMPORT_WORKS);

  protected toggleFormat(format: string, on: boolean): void {
    this.picked.update((p) => (on ? [...new Set([...p, format])] : p.filter((x) => x !== format)));
  }

  // endregion

  // region moving between pages

  /** the first page's answer: repair now, later, never for these files, or never at all */
  protected readonly firstChoice = signal<'repair' | 'later' | 'exclude' | 'never' | null>(null);

  protected async fromOverview(): Promise<void> {
    switch (this.firstChoice()) {
      case 'repair':
        if (this.busy()) return;
        this.step.set(this.duplicates().length ? 'duplicates' : this.afterDuplicatesStep());
        return;
      case 'exclude':
        try {
          const files = new Map<string, FoundFile>();
          for (const file of [
            ...this.works().flatMap((w) => w.files),
            ...this.undatedElsewhere(),
            ...this.duplicates().flatMap((g) => g.files),
          ]) files.set(file.path, file);
          if (this.sandbox()) this.note(`files list: ${[...files.values()].map((f) => f.name).join(', ')}`);
          else await this.imports.excludeFiles([...files.values()]);
        } catch {
          // not written: offered again next time, which loses nothing
        }
        this.closed.emit(null);
        return;
      case 'never':
        this.askAgainChanged.emit(false);
        this.closed.emit(null);
        return;
      case 'later':
        this.closed.emit(null);
        return;
    }
  }

  /** after the dates: the index question, when there are works without an entry */
  private afterDatesStep(): Step {
    return this.works().length ? 'index' : 'formats';
  }

  /** rename the files given a date, on a page of its own; none to rename goes straight on */
  protected async fromDates(): Promise<void> {
    const store = this.store();
    const chosen = this.toDate();
    const skipped = this.undated().filter((f) => this.skipped()[f.path]);
    if (this.rememberSkips() && skipped.length && !this.busy()) {
      try {
        if (this.sandbox()) this.note(`dates list: ${skipped.map((f) => f.name).join(', ')}`);
        else await this.imports.excludeDating(skipped);
      } catch {
        // not written: they are offered for dating again next time, which loses nothing
      }
    }
    if (!chosen.length || !store || this.busy()) {
      this.step.set(this.afterDatesStep());
      return;
    }
    this.step.set('dating');
    this.dating.set(true);
    this.stopDating = false;
    const result: DatingResult = { renamed: [], failed: [] };
    this.dated.set(result);
    this.datingProgress.set({ done: 0, total: chosen.length });
    const entries = this.library.worksById();
    const items: ToDate[] = chosen.map((file) => ({
      file,
      date: this.dates()[file.path],
      record: entries.get(file.id) as object | undefined,
    }));
    const renames = await renamesFor(items, (files) =>
      files.some((x) => x.record) ? this.jobs.fileNames(files) : Promise.resolve(null),
    );
    await dateFiles(
      store,
      renames,
      (done, total) => this.datingProgress.set({ done, total }),
      () => this.stopDating,
      result,
    );
    // a renamed file keeps its place on the exclusion lists - on the index list above all, where
    // a name no longer recorded would ask about its work again - written at once, not on close
    if (result.renamed.length) {
      try {
        if (this.sandbox()) this.note(`renamed in the lists: ${result.renamed.length} files`);
        else await this.imports.renamed(result.renamed);
      } catch {
        // not written: that work's index question may be asked again, which loses nothing
      }
    }
    this.dated.set({ ...result });
    this.dating.set(false);
  }

  protected fromDating(): void {
    this.step.set(this.afterDatesStep());
  }

  /** the formats page only when some work could be updated; with none, the window is done */
  protected fromIndex(): void {
    if (this.allIssues().length) this.step.set('formats');
    else this.finish();
  }

  protected backFrom(step: 'dates' | 'index' | 'formats'): void {
    if (step === 'dates') this.step.set(this.duplicates().length && !this.removed() ? 'duplicates' : 'overview');
    else if (step === 'index') this.step.set(this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview');
    else this.step.set(this.works().length ? 'index' : this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview');
  }

  /** no going back to the dates once files are renamed: they would be offered for dating again */
  protected readonly canGoBack = computed(() => !this.dated() && !this.removed()?.removed.length);

  /**
   * Done: works never to be offered again are written down, and a run - when there is anything
   * for one to do - is handed to the run window. Otherwise the window simply closes.
   */
  protected async finish(): Promise<void> {
    if (this.lookup() === 'never' && this.works().length) {
      try {
        if (this.sandbox()) this.note(`index list: ${this.works().map((w) => w.id).join(', ')}`);
        else await this.imports.excludeFromIndex(this.works());
      } catch {
        // not written: they are offered again next time, which loses nothing
      }
    }
    if (!this.runs() || this.busy()) {
      this.closed.emit(this.dated());
      return;
    }
    const works = this.scope().slice(0, MAX_IMPORT_WORKS);
    const taken = new Set(works.map((w) => w.id));
    const updating = new Set(this.updates() ? this.updating() : []);
    const updates = this.updates();
    this.start.emit({
      request: {
        links: importLinks(works),
        count: works.length,
        filetypes: ['JSON', ...(updates ? this.picked() : [])],
        replaceOutdated: updates && this.replaceOutdated(),
        indexOnly: this.lookups().filter((id) => taken.has(id) && !updating.has(id)),
        lookups: this.lookups().filter((id) => taken.has(id)).length,
        scope: updates ? this.scopeChosen() : 'skip',
        files: this.filesOf(taken),
      },
      dated: this.dated(),
    });
  }

  /** closing while files are being renamed stops after the one in hand; what was renamed stays */
  protected close(): void {
    this.stopDating = true;
    this.stopRemoving = true;
    // a question waiting on the removing page is answered as the one that deletes nothing
    this.answered?.('keep');
    this.closed.emit(this.dated());
  }

  // endregion
}
