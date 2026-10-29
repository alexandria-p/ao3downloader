import { Component, computed, inject, input, linkedSignal, signal } from '@angular/core';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { Library, LocalCopy, OPENABLE_FORMATS, OpenableFormat, copyName, viewableInBrowser } from './library';
import { Collection, isCustomCollection } from './collections';
import { CollectionItems, CustomCollections, canCollect, itemsOf } from './custom-collections';
import { CollectionEditor } from './collection-editor';
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
export type WorkSort =
  | ''
  | 'created-desc'
  | 'created-asc'
  | 'bookmarked-desc'
  | 'bookmarked-asc'
  | 'updated-desc'
  | 'updated-asc';

/** the date each sort orders by */
function sortField(sort: WorkSort): 'date_created' | 'date_bookmarked' | 'date_updated' {
  if (sort.startsWith('created')) return 'date_created';
  if (sort.startsWith('updated')) return 'date_updated';
  return 'date_bookmarked';
}

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
  imports: [DecimalPipe, NgTemplateOutlet, CollectionEditor],
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
  /** whether works can be ticked and put in a custom collection */
  readonly selectable = input(false);
  /** the collection being shown, when it is one: a custom one can have works taken out */
  readonly collection = input<Collection | null>(null);

  private readonly custom = inject(CustomCollections);

  protected readonly htmlFiles = this.library.htmlFiles;
  private readonly copies = this.library.copies;

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

    const field = sortField(sort);
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
    const field = sortField(sort);
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

  // region picking works for a custom collection

  /** ticking only means something where it can be saved: a library that can be written to */
  protected readonly canSelect = computed(() => this.selectable() && this.custom.writable());
  /** a different listing is a different set of works, so it starts with nothing ticked */
  protected readonly selected = linkedSignal<Bookmark[], ReadonlySet<string>>({
    source: this.works,
    computation: () => new Set(),
  });
  /** what can be ticked among what the filters leave showing */
  private readonly selectableShown = computed(() => this.filtered().filter(canCollect));
  /**
   * The ticked works the filters still show. Narrowing the listing narrows what an action
   * acts on, so nothing hidden is added or taken out unseen.
   */
  protected readonly selectedShown = computed(() => {
    const picked = this.selected();
    return this.selectableShown().filter((work) => picked.has(keyOf(work)));
  });
  protected readonly allShownSelected = computed(
    () => this.selectableShown().length > 0 && this.selectedShown().length === this.selectableShown().length,
  );
  /** the open collection, when it is one of the person's own and so can be taken from */
  protected readonly removableFrom = computed(() => {
    const collection = this.collection();
    return collection && isCustomCollection(collection) ? collection : null;
  });
  /** where ticked works can go: every custom collection but the one being shown */
  protected readonly targets = computed(() =>
    this.custom.all().filter((c) => c.name !== this.collection()?.name),
  );

  protected readonly adding = signal(false);
  /** the custom collection to add to, by name - '' until one is chosen */
  protected readonly target = signal('');
  /**
   * The works a new collection is being made for, while its window is open. Taken when the
   * window opens, so what it starts with is what was ticked then; null when it is shut.
   */
  protected readonly creatingWith = signal<CollectionItems | null>(null);
  protected readonly busy = signal(false);
  protected readonly outcome = signal('');
  protected readonly problem = signal('');

  protected readonly canAdd = computed(
    () => !this.busy() && this.selectedShown().length > 0 && !!this.target(),
  );

  protected canCollect(work: Bookmark): boolean {
    return canCollect(work);
  }

  protected isSelected(work: Bookmark): boolean {
    return this.selected().has(keyOf(work));
  }

  protected toggleSelected(work: Bookmark): void {
    const picked = new Set(this.selected());
    const key = keyOf(work);
    if (picked.has(key)) picked.delete(key);
    else picked.add(key);
    this.selected.set(picked);
  }

  /** every work the filters show, across every page - or none, when they all are already */
  protected toggleAllShown(): void {
    if (this.allShownSelected()) {
      this.selected.set(new Set());
      return;
    }
    this.selected.set(new Set([...this.selected(), ...this.selectableShown().map(keyOf)]));
  }

  protected clearSelection(): void {
    this.selected.set(new Set());
  }

  protected openAdd(): void {
    this.outcome.set('');
    this.problem.set('');
    // the last one added to stays chosen; otherwise the first, so Add is never waiting on a click
    if (!this.targets().some((c) => c.name === this.target())) this.target.set(this.targets()[0]?.name ?? '');
    // with none of your own to add to, the only answer is a new one - so ask that straight away
    if (this.targets().length === 0) {
      this.newCollection();
      return;
    }
    this.adding.set(true);
  }

  /** open the new-collection window, to start with what is ticked */
  protected newCollection(): void {
    this.outcome.set('');
    this.problem.set('');
    this.creatingWith.set(itemsOf(this.selectedShown()));
  }

  /** the new collection was made, with the ticked works already in it */
  protected collectionCreated(collection: Collection): void {
    const items = this.creatingWith() ?? { works: [], externals: [] };
    this.creatingWith.set(null);
    this.adding.set(false);
    this.target.set(collection.name ?? '');
    this.selected.set(new Set());
    this.outcome.set(`Made ${collection.title}, with ${countOf(items)} in it.`);
  }

  /**
   * Closed without saving: no collection was made, and nothing else changes - the works stay
   * ticked and the add panel stays as it was, so the person can pick another way.
   */
  protected collectionCancelled(): void {
    this.creatingWith.set(null);
  }

  protected async addSelected(): Promise<void> {
    if (!this.canAdd()) return;
    const items = itemsOf(this.selectedShown());
    await this.act(async () => {
      const { collection, added, already } = await this.custom.add(this.target(), items);
      this.adding.set(false);
      const count = added.works.length + added.externals.length;
      // a work is in a collection once: those already there are said, not added again
      const skipped = already ? ` ${already.toLocaleString()} ${already === 1 ? 'was' : 'were'} already in it.` : '';
      return count
        ? `Added ${countOf(added)} to ${collection.title}.${skipped}`
        : `Everything ticked was already in ${collection.title}.`;
    });
  }

  protected async removeSelected(): Promise<void> {
    const collection = this.removableFrom();
    if (!collection?.name || this.busy() || this.selectedShown().length === 0) return;
    const items = itemsOf(this.selectedShown());
    await this.act(async () => {
      await this.custom.remove(collection.name!, items);
      return `Took ${countOf(items)} out of ${collection.title}.`;
    });
  }

  private async act(change: () => Promise<string>): Promise<void> {
    this.busy.set(true);
    this.problem.set('');
    this.outcome.set('');
    try {
      this.outcome.set(await change());
      this.selected.set(new Set());
    } catch (error) {
      this.problem.set(error instanceof Error ? error.message : String(error));
    } finally {
      this.busy.set(false);
    }
  }

  // endregion

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

  /**
   * The formats this folder holds a downloaded copy of the work in, besides the html its title
   * opens - each one a button beside the title. A series' or an external work's id is not a
   * work number, so they never get one.
   */
  protected formatsOf(work: Bookmark): OpenableFormat[] {
    if (!isWorkEntry(work) || !work.id) return [];
    const copies = this.copies();
    return OPENABLE_FORMATS.filter((format) => format !== 'html' && copies[format].has(work.id!));
  }

  protected readonly viewable = viewableInBrowser;

  /**
   * Open the work's newest copy in that format: in a new tab where a browser can show it (a
   * pdf), and otherwise saved under its own name, for an e-reader - no browser shows an epub,
   * mobi or azw3, and a tab handed one only saves it under a made-up name.
   */
  protected openFormat(work: Bookmark, format: OpenableFormat, event: Event): void {
    event.preventDefault();
    const copy = isWorkEntry(work) && work.id ? this.copies()[format].get(work.id) : undefined;
    if (!copy) return;
    if (viewableInBrowser(format)) this.openCopy(copy, format, null);
    else this.saveCopy(copy, format);
  }

  private saveCopy(copy: LocalCopy, format: OpenableFormat): void {
    void this.library.readCopy(copy, format).then(
      (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = copyName(copy);
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      },
      () => {
        // the file has gone since the folder was read; the button stays, nothing is saved
      },
    );
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

/** a work and an external work can share a number, so the kind is part of the key */
function keyOf(work: Bookmark): string {
  return `${bookmarkTypeOf(work)}:${work.id}`;
}

/** '1 work', '3 works', '2 works and 1 external work' */
function countOf(items: { works: string[]; externals: string[] }): string {
  const say = (n: number, one: string) => `${n.toLocaleString()} ${one}${n === 1 ? '' : 's'}`;
  if (!items.externals.length) return say(items.works.length, 'work');
  if (!items.works.length) return say(items.externals.length, 'external work');
  return `${say(items.works.length, 'work')} and ${say(items.externals.length, 'external work')}`;
}
