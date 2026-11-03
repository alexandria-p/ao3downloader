import { Component, computed, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  DatingResult,
  FoundFile,
  FoundWork,
  ImportRequest,
  MAX_IMPORT_WORKS,
  dateFiles,
  importLinks,
  isFileDate,
  undatedFiles,
} from './imports';
import { LibraryStore } from './library-store';

/**
 * Bringing in the works whose files are in the library with no index entry.
 *
 * Three pages, each skippable:
 * 1. **found** - what was found, by work and file;
 * 2. **dates** - only when some files have no date in their name: a date for each, or one for
 *    all, or none. A run can only judge a dated copy against AO3's version, and leaves an
 *    undated one alone, so this is offered before anything else. Dating renames the files,
 *    here and now, through the library;
 * 3. **fetch** - whether to look the works up on AO3 now and index them, which other formats
 *    to download for works without them, and whether a copy AO3 has a newer version of is
 *    replaced. Yes hands over to the run window (`start`), which asks the rest - background
 *    (a hosted copy), the login - as for any run.
 *
 * **Never while a run is going** (`busy`): the run reads and writes the library, and renaming
 * files under it - or a second run, which the helper refuses anyway - is not safe. The window
 * says so and offers nothing but closing; the offer is made again once the run has ended.
 */
@Component({
  selector: 'app-import-dialog',
  imports: [DecimalPipe],
  templateUrl: './import-dialog.html',
  styleUrl: './import-dialog.css',
})
export class ImportDialog {
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

  protected readonly step = signal<'found' | 'dates' | 'dating' | 'fetch'>('found');

  protected readonly fileCount = computed(() =>
    this.works().reduce((n, w) => n + w.files.length, 0),
  );
  protected readonly undated = computed(() => [...undatedFiles(this.works()), ...this.undatedElsewhere()]);
  /** whether there is anything to import, or only files to date */
  protected readonly importable = computed(() => this.works().length > 0);
  /** how many works are named on the first page before 'and N more' */
  protected readonly shownWorks = 30;
  protected readonly tooMany = computed(() => this.works().length > MAX_IMPORT_WORKS);
  protected readonly maxWorks = MAX_IMPORT_WORKS;

  // region dates

  /** the date typed for each undated file, by path; '' is none yet */
  protected readonly dates = signal<Record<string, string>>({});
  /** the files to leave undated, by path */
  protected readonly skipped = signal<Record<string, boolean>>({});
  protected readonly bulkDate = signal('');
  protected readonly datingProgress = signal<{ done: number; total: number } | null>(null);
  protected readonly dated = signal<DatingResult | null>(null);

  protected dateOf(file: FoundFile): string {
    return this.dates()[file.path] ?? '';
  }

  protected isSkipped(file: FoundFile): boolean {
    return !!this.skipped()[file.path];
  }

  protected setDate(file: FoundFile, date: string): void {
    this.dates.update((d) => ({ ...d, [file.path]: date }));
    if (date) this.skipped.update((s) => ({ ...s, [file.path]: false }));
  }

  protected setSkipped(file: FoundFile, skip: boolean): void {
    this.skipped.update((s) => ({ ...s, [file.path]: skip }));
  }

  /** the one date given to every undated file not skipped */
  protected applyToAll(): void {
    const date = this.bulkDate();
    if (!isFileDate(date)) return;
    const all: Record<string, string> = {};
    for (const file of this.undated()) all[file.path] = date;
    this.dates.set(all);
    this.skipped.set({});
  }

  protected skipAll(): void {
    this.skipped.set(Object.fromEntries(this.undated().map((f) => [f.path, true])));
  }

  /** a file neither dated nor skipped yet, or dated with something that is not a date */
  protected readonly unsettled = computed(() =>
    this.undated().filter((f) => !this.skipped()[f.path] && !isFileDate(this.dates()[f.path] ?? '')),
  );
  protected readonly toDate = computed(() =>
    this.undated().filter((f) => !this.skipped()[f.path] && isFileDate(this.dates()[f.path] ?? '')),
  );
  protected readonly bulkValid = computed(() => isFileDate(this.bulkDate()));
  protected readonly isFileDate = isFileDate;

  // endregion

  // region fetch

  protected readonly fetchNow = signal(true);
  /** the formats to fetch for works without them - none ticked to begin with */
  protected readonly picked = signal<string[]>([]);
  protected readonly replaceOutdated = signal(false);
  /** every downloadable format the helper offers, JSON aside (always written: it is the index) */
  protected readonly offered = computed(() => this.formats().filter((x) => x !== 'JSON'));
  /** the formats the found files are already in, so the page can say so */
  protected readonly held = computed(() => {
    const held = new Set<string>();
    for (const work of this.works()) for (const file of work.files) held.add(file.format.toUpperCase());
    return held;
  });

  protected toggleFormat(format: string, on: boolean): void {
    this.picked.update((p) => (on ? [...new Set([...p, format])] : p.filter((x) => x !== format)));
  }

  // endregion

  protected fromFound(): void {
    this.step.set(this.undated().length ? 'dates' : 'fetch');
  }

  /** rename the files given a date, then go on */
  protected async fromDates(): Promise<void> {
    const store = this.store();
    const chosen = new Map(this.toDate().map((f) => [f.path, this.dates()[f.path]]));
    if (!chosen.size || !store || this.busy()) {
      this.afterDating();
      return;
    }
    this.step.set('dating');
    this.datingProgress.set({ done: 0, total: chosen.size });
    const result = await dateFiles(store, chosen, (done, total) =>
      this.datingProgress.set({ done, total }),
    );
    this.dated.set(result);
    this.datingProgress.set(null);
    this.afterDating();
  }

  /** on to the import - or, with nothing to import, done */
  private afterDating(): void {
    if (this.importable()) this.step.set('fetch');
    else this.closed.emit(this.dated());
  }

  protected backFrom(step: 'dates' | 'fetch'): void {
    if (step === 'dates') this.step.set('found');
    // dating is done once renamed: going back to it would offer to date them again
    else this.step.set(this.undated().length && !this.dated() ? 'dates' : 'found');
  }

  protected finish(): void {
    if (!this.fetchNow() || this.busy()) {
      this.closed.emit(this.dated());
      return;
    }
    const works = this.works().slice(0, MAX_IMPORT_WORKS);
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

  protected close(): void {
    if (this.step() === 'dating') return;
    this.closed.emit(this.dated());
  }
}
