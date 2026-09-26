import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CollectionsView } from './collections-view';
import { Library } from './library';
import { Bookmark, BookmarksExport } from './bookmarks';
import { Collection, flattenCollection } from './collections';

function work(id: string): Bookmark {
  return {
    id,
    link: `https://archiveofourown.org/works/${id}`,
    title: `Work ${id}`,
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
    fandoms: [],
    warnings: [],
    tags: { rating: '', categories: [], relationships: [], characters: [], additional: [] },
    summary: '',
    words: null,
    chapters_published: 1,
    chapters_total: 1,
    comments: null,
    kudos: null,
    bookmarks: null,
    hits: null,
    date_bookmarked: '',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  };
}

function index(ids: string[]): BookmarksExport {
  return {
    source: 'https://archiveofourown.org/users/Someone/bookmarks',
    retrieved: '01/01/2026, 12:00:00',
    count: ids.length,
    works: ids.map(work),
  };
}

function collection(fields: Record<string, unknown>): Collection {
  return flattenCollection({ name: 'a-collection', work_ids: [], bookmark_ids: [], ...fields })!;
}

let fixture: ComponentFixture<CollectionsView>;
let element: HTMLElement;
let library: Library;

async function render(collections: Collection[], indexed: string[] = []) {
  library = TestBed.inject(Library);
  library.collections.set(collections);
  library.data.set(indexed.length ? index(indexed) : null);
  // a collection looks its works up by number, among every work in the index
  library.worksById.set(new Map(indexed.map((id) => [id, work(id)])));

  fixture = TestBed.createComponent(CollectionsView);
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function titles(): string[] {
  return Array.from(element.querySelectorAll('.collection .title')).map(
    (t) => t.textContent?.trim() ?? '',
  );
}

async function openFirst(): Promise<void> {
  element.querySelector<HTMLButtonElement>('.collection .title')!.click();
  await fixture.whenStable();
}

function tab(name: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll<HTMLButtonElement>('.tabs button')).find((b) =>
    b.textContent?.includes(name),
  );
}

describe('CollectionsView', () => {
  beforeEach(async () => {
    vi.stubGlobal('scrollTo', vi.fn());
    await TestBed.configureTestingModule({ imports: [CollectionsView] }).compileComponents();
    TestBed.inject(Library).htmlFiles.set(new Map());
  });

  // region the listing

  it('says so when no collections have been indexed', async () => {
    await render([]);

    const notice = element.querySelector('.notice')?.textContent ?? '';
    expect(notice).toContain('Index my collections');
    expect(notice).toContain('Index collection by URL');
    expect(titles()).toEqual([]);
  });

  it('lists the collections it was given', async () => {
    await render([
      collection({ name: 'one', title: 'First' }),
      collection({ name: 'two', title: 'Second' }),
    ]);

    expect(titles()).toEqual(['First', 'Second']);
    expect(element.querySelector('.listing-heading')?.textContent).toContain('1 - 2 of 2');
  });

  it('shows 20 collections to a page, like the bookmarks listing', async () => {
    await render(
      Array.from({ length: 25 }, (_, i) => collection({ name: `c${i}`, title: `Collection ${i}` })),
    );

    expect(titles()).toHaveLength(20);

    const pages = Array.from(element.querySelectorAll<HTMLButtonElement>('.pagination .page'));
    pages.find((b) => b.textContent?.trim() === '2')!.click();
    await fixture.whenStable();

    expect(titles()).toHaveLength(5);
  });

  it('counts what each collection holds without needing the works themselves', async () => {
    await render([collection({ work_ids: ['1', '2', '3'], bookmark_ids: ['9'] })]);

    const stats = element.querySelector('.collection .stats')?.textContent ?? '';
    expect(stats).toContain('3');
    expect(stats).toContain('1');
  });

  // endregion

  // region one collection

  it('opens a collection and shows what was recorded about it', async () => {
    await render([
      collection({
        name: 'yuletide',
        title: 'Yuletide',
        description: 'A gift exchange.',
        maintainers: ['someone'],
        tags: ['Yuletide'],
        active_since: '01 Sep 2024',
        challenge_type: 'Gift Exchange Challenge',
        closed: true,
        moderated: true,
        multifandom: true,
        fandom_count: 1193,
      }),
    ]);

    await openFirst();

    expect(element.querySelector('.collection-head h2')?.textContent).toContain('Yuletide');
    expect(element.querySelector('.summary')?.textContent).toContain('A gift exchange.');

    const flags = element.querySelector('.flags')?.textContent ?? '';
    expect(flags).toContain('Closed');
    expect(flags).toContain('Moderated');
    expect(flags).toContain('Multifandom');
    expect(flags).toContain('Gift Exchange Challenge');

    const facts = element.querySelector('.facts')?.textContent ?? '';
    expect(facts).toContain('someone');
    expect(facts).toContain('01 Sep 2024');
    expect(facts).toContain('1,193');
  });

  it('says a count was not recorded rather than showing it as zero', async () => {
    await render([collection({ fandom_count: null })]);
    await openFirst();

    expect(element.querySelector('.facts')?.textContent).toContain('not recorded');
  });

  it('goes back to the listing', async () => {
    await render([collection({ title: 'One' })]);
    await openFirst();
    expect(element.querySelector('.collection-head')).toBeTruthy();

    element.querySelector<HTMLButtonElement>('.crumb button')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.collection-head')).toBeNull();
    expect(titles()).toEqual(['One']);
  });

  // endregion

  // region the works inside one

  it('shows the works in a collection as the same listing the bookmarks page uses', async () => {
    await render([collection({ work_ids: ['1', '2'] })], ['1', '2', '3']);
    await openFirst();

    const listed = Array.from(element.querySelectorAll('.blurb .heading a.title')).map((a) =>
      a.textContent?.trim(),
    );
    expect(listed).toEqual(['Work 1', 'Work 2']);
  });

  it('lists works that are not indexed by number, rather than dropping them', async () => {
    // a collection holds works that are not in your bookmarks; only their number is known,
    // which is still worth showing
    await render([collection({ work_ids: ['1', '2', '3'] })], ['1']);
    await openFirst();

    expect(element.querySelectorAll('.blurb')).toHaveLength(3);
    const titles = Array.from(element.querySelectorAll('.blurb .heading a.title')).map((a) =>
      a.textContent?.trim(),
    );
    expect(titles).toEqual(['Work 1', 'Work 2', 'Work 3']);
  });

  it('sends an unindexed work to ao3, since there is no local copy to open', async () => {
    await render([collection({ work_ids: ['404'] })], []);
    await openFirst();

    const link = element.querySelector<HTMLAnchorElement>('.blurb .heading a.title')!;
    expect(link.getAttribute('href')).toBe('https://archiveofourown.org/works/404');
    expect(element.querySelector('.not-indexed')?.textContent).toContain(
      'only its work number is known',
    );
  });

  it('keeps the collection order, indexed or not', async () => {
    await render([collection({ work_ids: ['9', '1', '7'] })], ['1']);
    await openFirst();

    const titles = Array.from(element.querySelectorAll('.blurb .heading a.title')).map((a) =>
      a.textContent?.trim(),
    );
    expect(titles).toEqual(['Work 9', 'Work 1', 'Work 7']);
  });

  it('still says how many of them it knows nothing about', async () => {
    await render([collection({ work_ids: ['1', '2', '3'] })], ['1']);
    await openFirst();

    const note = element.querySelector('.meta-line.note')?.textContent ?? '';
    expect(note).toContain('2 of 3');
    expect(note).toContain('not in your bookmarks index');
  });

  it('says nothing about missing works when every one of them is indexed', async () => {
    await render([collection({ work_ids: ['1'] })], ['1']);
    await openFirst();

    expect(element.querySelector('.meta-line.note')).toBeNull();
  });

  it('switches between the works and the bookmarked items', async () => {
    await render([collection({ work_ids: ['1'], bookmark_ids: ['2'] })], ['1', '2']);
    await openFirst();

    expect(element.querySelector('.blurb .heading a.title')?.textContent?.trim()).toBe('Work 1');

    tab('Bookmarked items')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.blurb .heading a.title')?.textContent?.trim()).toBe('Work 2');
  });

  it('explains an empty listing instead of showing a bare table', async () => {
    // nothing was recorded for it at all - not the same as nothing being indexed
    await render([collection({ work_ids: [] })], ['1']);
    await openFirst();

    expect(element.querySelectorAll('.blurb')).toHaveLength(0);
    expect(element.querySelector('.notice')?.textContent).toContain(
      'No works were recorded for this collection',
    );
  });

  // endregion

  // region related collections

  it('opens a subcollection here when it has been indexed too', async () => {
    await render([
      collection({
        name: 'parent',
        title: 'Parent',
        subcollections: ['https://archiveofourown.org/collections/child'],
      }),
      collection({ name: 'child', title: 'Child' }),
    ]);
    await openFirst();

    const link = element.querySelector<HTMLAnchorElement>('.related a.known')!;
    expect(link.textContent?.trim()).toBe('child');

    link.click();
    await fixture.whenStable();

    expect(element.querySelector('.collection-head h2')?.textContent).toContain('Child');
  });

  it('leaves a subcollection that was never indexed pointing at ao3', async () => {
    await render([
      collection({
        name: 'parent',
        subcollections: ['https://archiveofourown.org/collections/stranger'],
      }),
    ]);
    await openFirst();

    const link = element.querySelector<HTMLAnchorElement>('.related a')!;
    expect(link.classList.contains('known')).toBe(false);
    expect(link.getAttribute('href')).toBe('https://archiveofourown.org/collections/stranger');
  });

  it('shows the parent collection a collection belongs to', async () => {
    await render([
      collection({
        name: 'yuletide2024',
        parent_collection: 'https://archiveofourown.org/collections/yuletide',
      }),
    ]);
    await openFirst();

    const related = element.querySelector('.related')?.textContent ?? '';
    expect(related).toContain('Part of');
    expect(related).toContain('yuletide');
  });

  // endregion
});
