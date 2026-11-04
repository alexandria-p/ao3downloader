import { Component, computed, inject, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  DatingResult,
  FoundFile,
  FoundWork,
  ImportRequest,
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

type Step = 'overview' | 'dates' | 'dating' | 'index' | 'formats';

/** how many rows a page of the dates list holds */
export const DATES_PAGE_SIZE = 25;

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

  readonly works = input.required<FoundWork[]>();
  /** undated files of works the index does have - offered for dating beside the rest */
  readonly undatedElsewhere = input<FoundFile[]>([]);
  readonly store = input<LibraryStore | null>(null);
  /** the formats the helper offers, JSON among them */
  readonly formats = input<string[]>(['HTML', 'EPUB', 'PDF', 'MOBI', 'AZW3', 'JSON']);
  /** a run is going: nothing may be renamed or started */
  readonly busy = input(false);

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
    return [...new Set(this.undated().map((f) => f.id))].filter((id) => !indexed.has(id) || looked.has(id));
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
        this.step.set(this.undated().length ? 'dates' : this.afterDatesStep());
        return;
      case 'exclude':
        try {
          await this.imports.exclude(this.works(), this.undatedElsewhere());
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
    if (step === 'dates') this.step.set('overview');
    else if (step === 'index') this.step.set(this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview');
    else this.step.set(this.works().length ? 'index' : this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview');
  }

  /** no going back to the dates once files are renamed: they would be offered for dating again */
  protected readonly canGoBack = computed(() => !this.dated());

  /**
   * Done: works never to be offered again are written down, and a run - when there is anything
   * for one to do - is handed to the run window. Otherwise the window simply closes.
   */
  protected async finish(): Promise<void> {
    if (this.lookup() === 'never' && this.works().length) {
      try {
        await this.imports.exclude(this.works());
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
      },
      dated: this.dated(),
    });
  }

  /** closing while files are being renamed stops after the one in hand; what was renamed stays */
  protected close(): void {
    this.stopDating = true;
    this.closed.emit(this.dated());
  }

  // endregion
}
