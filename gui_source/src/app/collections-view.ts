import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Library } from './library';
import { WorkList } from './work-list';
import { Bookmark, pageItems, paragraphs, placeholderWork } from './bookmarks';
import {
  Collection,
  collectionBadges,
  collectionLink,
  collectionNameFromLink,
  historyLength,
} from './collections';

const PER_PAGE = 20;

/** which set of a collection's works is being shown */
type Tab = 'works' | 'bookmarks';

/**
 * The collections page: a paginated listing of the collections that have been indexed,
 * and everything known about one when it is opened.
 *
 * A collection file records the works it holds by work number only, so the works shown
 * inside one are the matching entries from the bookmarks index - the same works, in the
 * same listing, which is why the works table here is the bookmarks table.
 */
@Component({
  selector: 'app-collections-view',
  imports: [DecimalPipe, WorkList],
  styleUrl: './collections-view.css',
  templateUrl: './collections-view.html',
})
export class CollectionsView {
  private readonly library = inject(Library);

  protected readonly collections = this.library.collections;

  /** the open collection, by ao3 name; null while the listing is showing */
  protected readonly openName = signal<string | null>(null);
  protected readonly tab = signal<Tab>('works');
  protected readonly page = signal(1);

  protected readonly total = computed(() => this.collections().length);
  protected readonly totalPages = computed(() => Math.max(1, Math.ceil(this.total() / PER_PAGE)));
  protected readonly pages = computed(() => pageItems(this.page(), this.totalPages()));

  protected readonly visible = computed(() => {
    const start = (this.page() - 1) * PER_PAGE;
    return this.collections().slice(start, start + PER_PAGE);
  });

  protected readonly rangeStart = computed(() =>
    this.total() === 0 ? 0 : (this.page() - 1) * PER_PAGE + 1,
  );
  protected readonly rangeEnd = computed(() => Math.min(this.page() * PER_PAGE, this.total()));

  protected readonly open = computed<Collection | null>(() => {
    const name = this.openName();
    return name === null ? null : (this.collections().find((c) => c.name === name) ?? null);
  });

  /** every indexed work, by work number, which is what a collection records */
  private readonly worksById = this.library.worksById;

  /** the work numbers the open tab is showing */
  private readonly openIds = computed<string[]>(() => {
    const collection = this.open();
    if (!collection) return [];
    return this.tab() === 'works' ? collection.work_ids : collection.bookmark_ids;
  });

  /**
   * Every work the collection lists, in its listed order.
   *
   * A collection records what it holds by work number alone, and can hold works you have
   * never bookmarked. Those have no index entry to show, so they appear as a placeholder
   * carrying the one thing that is known - the number - and a link to the work on ao3.
   */
  protected readonly openWorks = computed<Bookmark[]>(() => {
    const byId = this.worksById();
    return this.openIds().map((id) => byId.get(id) ?? placeholderWork(id));
  });

  protected readonly missingCount = computed(
    () => this.openWorks().filter((work) => work.placeholder).length,
  );

  protected readonly note = computed(() => {
    const missing = this.missingCount();
    if (missing === 0) return '';
    return (
      `${missing.toLocaleString()} of ${this.openIds().length.toLocaleString()} works in this ` +
      'collection are not in your bookmarks index. They are listed by work number, and open ' +
      'on AO3 rather than as a local copy.'
    );
  });

  protected readonly emptyMessage = computed(() =>
    this.tab() === 'works'
      ? 'No works were recorded for this collection.'
      : 'No bookmarked items were recorded for this collection.',
  );

  // template helpers
  protected readonly paragraphs = paragraphs;
  protected readonly badges = collectionBadges;
  protected readonly link = collectionLink;
  protected readonly nameFromLink = collectionNameFromLink;
  protected readonly historyLength = historyLength;

  protected show(collection: Collection): void {
    this.openName.set(collection.name);
    this.tab.set('works');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected back(): void {
    this.openName.set(null);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /** open a subcollection or parent from its link, if it has been indexed too */
  protected follow(url: string, event: Event): void {
    const name = collectionNameFromLink(url);
    const known = this.collections().find((c) => c.name === name);
    if (!known) return; // not indexed: let the link go to ao3
    event.preventDefault();
    this.show(known);
  }

  protected isIndexed(url: string): boolean {
    const name = collectionNameFromLink(url);
    return this.collections().some((c) => c.name === name);
  }

  protected goTo(page: number): void {
    this.page.set(Math.min(Math.max(page, 1), this.totalPages()));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  protected count(value: number | null | undefined): string {
    return value === null || value === undefined ? 'not recorded' : value.toLocaleString();
  }
}
