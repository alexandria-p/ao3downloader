import { Component, computed, inject, input, linkedSignal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Library } from './library';
import {
  Bookmark,
  authorLink,
  chapterCount,
  isComplete,
  pageItems,
  paragraphs,
  ratingClass,
  warningClass,
} from './bookmarks';

const PER_PAGE = 20;

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

  /** a different set of works is a different listing, so it starts at its first page */
  protected readonly page = linkedSignal<Bookmark[], number>({
    source: this.works,
    computation: () => 1,
  });

  protected readonly total = computed(() => this.works().length);
  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PER_PAGE)));
  protected readonly pages = computed(() => pageItems(this.page(), this.totalPages()));

  protected readonly pageWorks = computed(() => {
    const start = (this.page() - 1) * PER_PAGE;
    return this.works().slice(start, start + PER_PAGE);
  });

  protected readonly rangeStart = computed(() =>
    this.total() === 0 ? 0 : (this.page() - 1) * PER_PAGE + 1,
  );
  protected readonly rangeEnd = computed(() => Math.min(this.page() * PER_PAGE, this.total()));

  /** how many of the listed works actually have a downloaded html file alongside them */
  readonly linkedCount = computed(() => {
    const files = this.htmlFiles();
    return this.works().filter((work) => work.id && files.has(work.id)).length;
  });

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

    const file = work.id ? this.htmlFiles().get(work.id) : undefined;
    if (file) {
      const url = URL.createObjectURL(file);
      window.open(url, '_blank');
      // the tab keeps its own copy once loaded, so the handle can be released
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
      return;
    }

    if (work.link) window.open(work.link, '_blank', 'noopener');
  }
}
