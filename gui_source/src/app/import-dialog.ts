import { Component, computed, inject, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  DatingResult,
  FoundFile,
  FoundWork,
  ImportRequest,
  MAX_IMPORT_WORKS,
  ToDate,
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

  readonly works = input.required<FoundWork[]>();
  /** undated files of works the index does have - offered for dating beside the rest */
  readonly undatedElsewhere = input<FoundFile[]>([]);
  readonly store = input<LibraryStore | null>(null);
  /** the formats the helper offers, JSON among them */
  readonly formats = input<string[]>(['HTML', 'EPUB', 'PDF', 'MOBI', 'AZW3', 'JSON']);
  /** a run is going: nothing may be renamed or started */
  readonly busy = input(false);
  /** offered on the first page: stop opening this by itself when a library opens */
  readonly askAgain = input(true);

  /** closed without starting anything; `dated` is what was renamed, if anything */
  readonly closed = output<DatingResult | null>();
  /** start the import run with these */
  readonly start = output<{ request: ImportRequest; dated: DatingResult | null }>();
  /** ticked or unticked 'do not offer this when a library opens' */
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

  protected readonly fetchNow = signal(true);
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

  /**
   * The works a run would be over: the unindexed ones, if they are to be fetched, and the
   * indexed works with undated files - their formats and outdated copies are this window's to
   * settle too.
   */
  protected readonly scope = computed(() => {
    const ids = new Set<string>();
    if (this.fetchNow()) for (const work of this.works()) ids.add(work.id);
    for (const file of this.undatedElsewhere()) ids.add(file.id);
    return [...ids].map((id) => ({ id, files: [] }));
  });
  /** whether there is anything left for a run to do */
  protected readonly runs = computed(
    () =>
      this.scope().length > 0 &&
      ((this.fetchNow() && this.works().length > 0) || this.picked().length > 0 || this.replaceOutdated()),
  );
  protected readonly tooMany = computed(() => this.scope().length > MAX_IMPORT_WORKS);

  protected toggleFormat(format: string, on: boolean): void {
    this.picked.update((p) => (on ? [...new Set([...p, format])] : p.filter((x) => x !== format)));
  }

  // endregion

  // region moving between pages

  protected fromOverview(): void {
    this.step.set(this.undated().length ? 'dates' : this.afterDatesStep());
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

  protected backFrom(step: 'dates' | 'index' | 'formats'): void {
    if (step === 'dates') this.step.set('overview');
    else if (step === 'index') this.step.set(this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview');
    else this.step.set(this.works().length ? 'index' : this.dated() ? 'overview' : this.undated().length ? 'dates' : 'overview');
  }

  /** no going back to the dates once files are renamed: they would be offered for dating again */
  protected readonly canGoBack = computed(() => !this.dated());

  protected finish(): void {
    if (!this.runs() || this.busy()) {
      this.closed.emit(this.dated());
      return;
    }
    const works = this.scope().slice(0, MAX_IMPORT_WORKS);
    this.start.emit({
      request: {
        links: importLinks(works),
        count: works.length,
        filetypes: ['JSON', ...this.picked()],
        replaceOutdated: this.replaceOutdated(),
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
