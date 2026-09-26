import { Component, computed, inject, input, linkedSignal, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Library } from './library';
import {
  Bookmark,
  authorLink,
  chapterCount,
  dateStamp,
  isComplete,
  pageItems,
  paragraphs,
  ratingClass,
  warningClass,
} from './bookmarks';

const PER_PAGE = 20;

/** the orderings the filter panel offers; '' is the order the folder was read in */
export type WorkSort = '' | 'created-desc' | 'created-asc' | 'bookmarked-desc' | 'bookmarked-asc';

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

  // What to narrow the listing to. All four are 'no opinion' when empty, so an untouched
  // panel shows everything - the filters are for finding something, not for hiding things
  // by default.
  protected readonly titleQuery = signal('');
  protected readonly authorQuery = signal('');
  protected readonly updatedFrom = signal('');
  protected readonly updatedTo = signal('');
  protected readonly bookmarkedFrom = signal('');
  protected readonly bookmarkedTo = signal('');

  /**
   * How the listing is ordered. Empty keeps the order the folder was read in.
   *
   * A work with no date for the chosen field goes **last in both directions** - it cannot
   * be placed, and putting it first on an ascending sort would bury every dated work under
   * a pile of blanks.
   */
  protected readonly sortBy = signal<WorkSort>('');

  protected readonly filtering = computed(
    () =>
      !!(
        this.titleQuery().trim() ||
        this.authorQuery().trim() ||
        this.updatedFrom() ||
        this.updatedTo() ||
        this.bookmarkedFrom() ||
        this.bookmarkedTo()
      ),
  );

  /** a sort narrows nothing, so it is not 'filtering' - but it is still something to clear */
  protected readonly anythingToClear = computed(() => this.filtering() || !!this.sortBy()
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

    return this.works().filter((work) => {
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
    if (!sort) return false;
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
    return this.filtered().filter((work) => work.id && files.has(work.id)).length;
  });

  protected clearFilters(): void {
    this.titleQuery.set('');
    this.authorQuery.set('');
    this.updatedFrom.set('');
    this.updatedTo.set('');
    this.bookmarkedFrom.set('');
    this.bookmarkedTo.set('');
    this.sortBy.set('');
  }

  // template helpers
  protected readonly authorLink = authorLink;
  protected readonly chapterCount = chapterCount;
  protected readonly isComplete = isComplete;
  protected readonly paragraphs = paragraphs;
  protected readonly ratingClass = ratingClass;
  protected readonly warningClass = warningClass;

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.totalPages()));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected hasLocalCopy(work: Bookmark): boolean {
    return !!work.id && this.htmlFiles().has(work.id);
  }

  /**
   * Opens the downloaded html file in a new tab, falling back to the work on ao3 when
   * this folder has no local copy of it.
   */
  protected openWork(work: Bookmark, event: Event): void {
    event.preventDefault();

    const copy = work.id ? this.htmlFiles().get(work.id) : undefined;
    if (copy instanceof Blob) {
      const url = URL.createObjectURL(copy);
      window.open(url, '_blank');
      // the tab keeps its own copy once loaded, so the handle can be released
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      return;
    }
    if (copy) {
      // a copy in Dropbox has to be fetched first. the tab is opened now, while the click
      // still counts as the user's - opened after the download it would be a popup, and
      // blocked - and pointed at the work once it arrives
      const tab = window.open('', '_blank');
      void this.library.readCopy(copy).then(
        (blob) => {
          const url = URL.createObjectURL(blob);
          if (tab) tab.location.href = url;
          setTimeout(() => URL.revokeObjectURL(url), 60_000);
        },
        () => {
          // could not be fetched - AO3's copy is better than a blank tab
          if (tab && work.link) tab.location.href = work.link;
          else tab?.close();
        },
      );
      return;
    }

    if (work.link) window.open(work.link, '_blank', 'noopener');
  }
}
