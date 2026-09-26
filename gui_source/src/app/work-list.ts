import { Component, computed, inject, input, linkedSignal, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Library, LocalCopy, OpenableFormat } from './library';
import {
  Bookmark,
  BookmarkType,
  authorLink,
  bookmarkTypeOf,
  chapterCount,
  dateStamp,
  isEntryComplete,
  isWorkEntry,
  pageItems,
  paragraphs,
  placeholderWork,
  ratingClass,
  warningClass,
} from './bookmarks';

const PER_PAGE = 20;

/** the orderings the filter panel offers; '' is the order the folder was read in */
export type WorkSort = '' | 'created-desc' | 'created-asc' | 'bookmarked-desc' | 'bookmarked-asc';

/**
 * How the works are listed until someone asks otherwise: most recently bookmarked first,
 * which is how ao3 shows your bookmarks. The index no longer keeps a listing position of
 * its own, so this is what puts the list in that order.
 */
export const DEFAULT_SORT: WorkSort = 'bookmarked-desc';

/**
 * A paginated listing of works, in ao3's own blurb style.
 *
 * This is the whole of the bookmarks page's table, and is reused as-is for the works
 * inside a collection - the two are the same listing over a different set of works.
 */
@Component({
  selector: 'app-work-list',
  imports: [DecimalPipe, NgTemplateOutlet],
  styleUrl: './work-list.css',
  templateUrl: './work-list.html',
})
export class WorkList {
  private readonly library = inject(Library);

  readonly works = input.required<Bookmark[]>();
  /** whose listing this is, shown in the heading and on the bookmarker's section */
  readonly owner = input('');
  /** what the things being counted are called: '1 - 20 of 25 Bookmarks' */
  readonly label = input('Bookmarks');
  readonly emptyMessage = input('This export has no works in it.');
  /** shown under the heading, above the listing */
  readonly note = input('');

  protected readonly htmlFiles = this.library.htmlFiles;
  protected readonly pdfFiles = this.library.pdfFiles;

  // What to narrow the listing to. All four are 'no opinion' when empty, so an untouched
  // panel shows everything - the filters are for finding something, not for hiding things
  // by default.
  protected readonly titleQuery = signal('');
  protected readonly authorQuery = signal('');
  protected readonly updatedFrom = signal('');
  protected readonly updatedTo = signal('');
  protected readonly bookmarkedFrom = signal('');
  protected readonly bookmarkedTo = signal('');
  /** one kind of bookmark only - works, series or external works - or '' for all of them */
  protected readonly typeFilter = signal<'' | BookmarkType>('');

  /**
   * The parts lists that are open. A series card is keyed by the series id; a work's
   * 'Part N of' line by the work and the series, so opening it on one card does not open it
   * on every other work of the same series.
   */
  protected readonly openSeries = signal<ReadonlySet<string>>(new Set());
  private readonly worksById = this.library.worksById;
  private readonly seriesById = this.library.seriesById;

  /**
   * How the listing is ordered. Empty keeps the order the folder was read in.
   *
   * A work with no date for the chosen field goes **last in both directions** - it cannot
   * be placed, and putting it first on an ascending sort would bury every dated work under
   * a pile of blanks.
   */
  protected readonly sortBy = signal<WorkSort>(DEFAULT_SORT);

  protected readonly filtering = computed(
    () =>
      !!(
        this.titleQuery().trim() ||
        this.authorQuery().trim() ||
        this.updatedFrom() ||
        this.updatedTo() ||
        this.bookmarkedFrom() ||
        this.bookmarkedTo() ||
        this.typeFilter()
      ),
  );

  /** a sort narrows nothing, so it is not 'filtering' - but it is still something to clear */
  protected readonly anythingToClear = computed(() => this.filtering() || this.sortBy() !== DEFAULT_SORT
  );

  /**
   * The works this listing is actually showing.
   *
   * Every filter that has been filled in has to match - they narrow together rather than
   * widening, which is what someone hunting for one fic expects.
   *
   * **A work with no readable date is excluded by a date filter, not kept.** It cannot be
   * placed in the range, and including it would make the range a lie. With no date filter
   * set it is shown like anything else.
   */
  protected readonly filtered = computed(() => {
    const title = this.titleQuery().trim().toLowerCase();
    const author = this.authorQuery().trim().toLowerCase();
    const updatedFrom = this.updatedFrom();
    const updatedTo = this.updatedTo();
    const bookmarkedFrom = this.bookmarkedFrom();
    const bookmarkedTo = this.bookmarkedTo();
    const type = this.typeFilter();

    return this.works().filter((work) => {
      if (type && bookmarkTypeOf(work) !== type) return false;
      if (title && !(work.title ?? '').toLowerCase().includes(title)) return false;
      if (author && !(work.authors ?? []).some((name) =>
        name.toLowerCase().includes(author))) return false;

      if (updatedFrom || updatedTo) {
        const updated = dateStamp(work.date_updated);
        if (!updated) return false;
        if (updatedFrom && updated < updatedFrom) return false;
        if (updatedTo && updated > updatedTo) return false;
      }

      if (bookmarkedFrom || bookmarkedTo) {
        const bookmarked = dateStamp(work.date_bookmarked);
        if (!bookmarked) return false;
        if (bookmarkedFrom && bookmarked < bookmarkedFrom) return false;
        if (bookmarkedTo && bookmarked > bookmarkedTo) return false;
      }

      return true;
    });
  });

  /**
   * A different set of works is a different listing, so it starts at its first page.
   *
   * Sourced on the filtered set rather than the input, so narrowing the listing also
   * goes back to page 1 - staying on page 9 of a result that now has two pages would
   * show an empty listing and look like the filter had found nothing.
   */
  /** the filtered works, in the order asked for */
  protected readonly sorted = computed(() => {
    const sort = this.sortBy();
    const works = this.filtered();
    if (!sort) return works;

    const field = sort.startsWith('created') ? 'date_created' : 'date_bookmarked';
    const ascending = sort.endsWith('asc');
    return works
      .map((work, at) => ({ work, at, stamp: dateStamp(work[field] ?? '') }))
      .sort((a, b) => {
        if (!a.stamp !== !b.stamp) return a.stamp ? -1 : 1;
        if (a.stamp !== b.stamp) {
          const order = a.stamp < b.stamp ? -1 : 1;
          return ascending ? order : -order;
        }
        // equal dates keep the order they were read in, so the sort is stable to look at
        return a.at - b.at;
      })
      .map((x) => x.work);
  });

  /**
   * Whether the chosen sort has nothing to sort on.
   *
   * Publication dates are only recorded by a per-work lookup this app does not run, so on
   * most libraries no work has one and a date-created sort changes nothing. Saying so beats
   * a control that silently does nothing.
   */
  protected readonly sortHasNoDates = computed(() => {
    const sort = this.sortBy();
    // the default is not something anyone chose, so it is not worth a note that it does
    // nothing - a collection of works you never bookmarked has no bookmark dates at all
    if (!sort || sort === DEFAULT_SORT) return false;
    const field = sort.startsWith('created') ? 'date_created' : 'date_bookmarked';
    return this.filtered().length > 0 &&
      !this.filtered().some((work) => dateStamp(work[field] ?? ''));
  });

  protected readonly page = linkedSignal<Bookmark[], number>({
    source: this.sorted,
    computation: () => 1,
  });

  protected readonly total = computed(() => this.filtered().length);
  /** how many there were before any filter, so the listing can say what it is hiding */
  protected readonly totalUnfiltered = computed(() => this.works().length);
  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PER_PAGE)));
  protected readonly pages = computed(() => pageItems(this.page(), this.totalPages()));

  protected readonly pageWorks = computed(() => {
    const start = (this.page() - 1) * PER_PAGE;
    return this.sorted().slice(start, start + PER_PAGE);
  });

  protected readonly rangeStart = computed(() =>
    this.total() === 0 ? 0 : (this.page() - 1) * PER_PAGE + 1,
  );
  protected readonly rangeEnd = computed(() => Math.min(this.page() * PER_PAGE, this.total()));

  /** how many of the listed works actually have a downloaded html file alongside them */
  readonly linkedCount = computed(() => {
    const files = this.htmlFiles();
    return this.filtered().filter((work) => isWorkEntry(work) && work.id && files.has(work.id)).length;
  });

  protected clearFilters(): void {
    this.titleQuery.set('');
    this.authorQuery.set('');
    this.updatedFrom.set('');
    this.updatedTo.set('');
    this.bookmarkedFrom.set('');
    this.bookmarkedTo.set('');
    this.typeFilter.set('');
    this.sortBy.set(DEFAULT_SORT);
  }

  // template helpers
  protected readonly authorLink = authorLink;
  protected readonly chapterCount = chapterCount;
  protected readonly isComplete = isEntryComplete;
  protected readonly typeOf = bookmarkTypeOf;
  protected readonly paragraphs = paragraphs;
  protected readonly ratingClass = ratingClass;
  protected readonly warningClass = warningClass;

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.totalPages()));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected hasLocalCopy(work: Bookmark): boolean {
    // a series' or an external work's id is not a work number, and could be one by chance
    return isWorkEntry(work) && !!work.id && this.htmlFiles().has(work.id);
  }

  protected isOpen(key: string): boolean {
    return this.openSeries().has(key);
  }

  protected toggle(key: string): void {
    const open = new Set(this.openSeries());
    if (open.has(key)) open.delete(key);
    else open.add(key);
    this.openSeries.set(open);
  }

  /**
   * The works a series holds, in the series' own order, as the index describes them. A work
   * the index has no entry for - the series grew since it was last walked - is shown by its
   * number, with a link to ao3, as a collection shows one.
   */
  protected partsOf(ids: string[] | undefined): Bookmark[] {
    const byId = this.worksById();
    return (ids ?? []).map((id) => byId.get(id) ?? placeholderWork(id));
  }

  /** the works in one of the series a work belongs to, when that series has been walked */
  protected seriesParts(seriesId: string): string[] | undefined {
    return this.seriesById().get(seriesId)?.work_ids;
  }

  /**
   * Opens the downloaded html file in a new tab, falling back to the work on ao3 when
   * this folder has no local copy of it.
   */
  protected openWork(work: Bookmark, event: Event): void {
    event.preventDefault();

    const copy = isWorkEntry(work) && work.id ? this.htmlFiles().get(work.id) : undefined;
    if (copy) {
      this.openCopy(copy, 'html', work.link);
      return;
    }
    if (work.link) window.open(work.link, '_blank', 'noopener');
  }

  /** whether this folder holds a downloaded PDF of the work */
  protected hasPdf(work: Bookmark): boolean {
    return isWorkEntry(work) && !!work.id && this.pdfFiles().has(work.id);
  }

  /** Open the work's newest downloaded PDF in a new tab. */
  protected openPdf(work: Bookmark, event: Event): void {
    event.preventDefault();
    const copy = isWorkEntry(work) && work.id ? this.pdfFiles().get(work.id) : undefined;
    if (copy) this.openCopy(copy, 'pdf', null);
  }

  /**
   * Show a downloaded copy in a new tab.
   *
   * A copy in Dropbox has to be fetched first. The tab is opened straight away, while the
   * click still counts as the user's - opened after the download it would be a popup, and
   * blocked - and pointed at the file once it arrives. If it cannot be fetched, the tab goes
   * to `fallback` (the work on AO3) rather than staying blank.
   */
  private openCopy(copy: LocalCopy, format: OpenableFormat, fallback: string | null): void {
    const tab = window.open('', '_blank');
    void this.library.readCopy(copy, format).then(
      (blob) => {
        const url = URL.createObjectURL(blob);
        if (tab) tab.location.href = url;
        else window.open(url, '_blank');
        // the tab keeps its own copy once loaded, so the handle can be released
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      },
      () => {
        if (tab && fallback) tab.location.href = fallback;
        else tab?.close();
      },
    );
  }
}
