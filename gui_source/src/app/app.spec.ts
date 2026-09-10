import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './app';
import { Library } from './library';
import { Bookmark, BookmarksExport } from './bookmarks';
import { Collection } from './collections';

function work(id: number): Bookmark {
  return {
    id: String(id),
    link: `https://archiveofourown.org/works/${id}`,
    title: `Work ${id}`,
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
    fandoms: ['A Fandom'],
    warnings: ['No Archive Warnings Apply'],
    tags: {
      rating: 'Teen And Up Audiences',
      categories: ['M/M'],
      relationships: [],
      characters: [],
      additional: ['a tag'],
    },
    summary: 'first line\nsecond line',
    words: 1234,
    chapters_published: 3,
    chapters_total: null,
    comments: null,
    kudos: 7,
    bookmarks: null,
    hits: null,
    date_bookmarked: '02 Feb 2021',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  };
}

function exportOf(count: number): BookmarksExport {
  const works = Array.from({ length: count }, (_, i) => work(i + 1));
  return {
    source: 'https://archiveofourown.org/users/Someone/bookmarks',
    retrieved: '01/01/2026, 12:00:00',
    count,
    works,
  };
}

function collection(name: string): Collection {
  return {
    name,
    link: `https://archiveofourown.org/collections/${name}`,
    title: `The ${name} Collection`,
    description: '',
    maintainers: [],
    tags: [],
    active_since: '',
    created: '',
    flags: [],
    challenge_type: 'No Challenge',
    multifandom: null,
    closed: false,
    moderated: false,
    unrevealed: false,
    anonymous: false,
    fandom_count: null,
    work_count: null,
    bookmark_count: null,
    subcollection_count: null,
    parent_collection: null,
    subcollections_link: null,
    subcollections: [],
    work_ids: [],
    bookmark_ids: [],
  };
}

async function render(count: number) {
  const library = TestBed.inject(Library);
  library.data.set(exportOf(count));

  const fixture = TestBed.createComponent(App);
  await fixture.whenStable();
  return { fixture, element: fixture.nativeElement as HTMLElement, library };
}

function actionLabels(element: HTMLElement): (string | undefined)[] {
  return Array.from(element.querySelectorAll('.actions button')).map((b) => b.textContent?.trim());
}

function tab(element: HTMLElement, name: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll<HTMLButtonElement>('.views button')).find((b) =>
    b.textContent?.includes(name),
  );
}

async function showCollections(
  fixture: ComponentFixture<App>,
  element: HTMLElement,
): Promise<void> {
  tab(element, 'Collections')!.click();
  await fixture.whenStable();
}

describe('App', () => {
  beforeEach(async () => {
    vi.stubGlobal('scrollTo', vi.fn());
    await TestBed.configureTestingModule({ imports: [App] }).compileComponents();
    TestBed.inject(Library).data.set(null);
    TestBed.inject(Library).collections.set([]);
    TestBed.inject(Library).htmlFiles.set(new Map());
  });

  it('offers the two bookmark jobs on the bookmarks page', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(actionLabels(element)).toEqual([
      'Download newly added bookmarks',
      'Update any bookmarks marked as incomplete',
    ]);
  });

  it('offers only the collections jobs on the collections page', async () => {
    // each page carries the buttons that fill it, so neither offers the other's job
    const { fixture, element } = await render(1);
    await showCollections(fixture, element);

    expect(actionLabels(element)).toEqual([
      'Index my collections',
      'Index collection by URL',
    ]);
  });

  it('switches between the two listings', async () => {
    const { fixture, element } = await render(3);
    expect(element.querySelectorAll('.blurb').length).toBe(3);

    await showCollections(fixture, element);
    expect(element.querySelector('app-collections-view')).toBeTruthy();
    expect(element.querySelectorAll('.blurb').length).toBe(0);

    tab(element, 'Bookmarks')!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-collections-view')).toBeNull();
    expect(element.querySelectorAll('.blurb').length).toBe(3);
  });

  it('counts what each page holds on its tab', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(3));
    library.collections.set([collection('a'), collection('b')]);

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(tab(element, 'Bookmarks')?.textContent).toContain('3');
    expect(tab(element, 'Collections')?.textContent).toContain('2');
  });

  it('opens a folder whose collections are synced but whose bookmarks are not', async () => {
    // collections can be indexed first, and that folder is not an empty one
    const library = TestBed.inject(Library);
    library.collections.set([collection('a')]);

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.empty')).toBeNull();
    expect(element.querySelector('.notice')?.textContent).toContain('No bookmarks indexed');

    await showCollections(fixture, element);
    expect(element.querySelectorAll('.collection').length).toBe(1);
  });

  it('asks for a folder before anything is loaded', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.empty')).toBeTruthy();
    expect(element.querySelectorAll('.blurb').length).toBe(0);
  });

  it('shows 20 works on a page', async () => {
    const { element } = await render(25);

    expect(element.querySelectorAll('.blurb').length).toBe(20);
  });

  it('reports the range and the owner of the listing', async () => {
    const { element } = await render(25);

    const heading = element.querySelector('.listing-heading')?.textContent ?? '';
    expect(heading).toContain('1 - 20 of 25 Bookmarks');
    expect(heading).toContain('Someone');
  });

  it('shows the remainder on the last page', async () => {
    const { fixture, element } = await render(25);

    const pages = Array.from(element.querySelectorAll<HTMLButtonElement>('.pagination .page'));
    pages.find((button) => button.textContent?.trim() === '2')?.click();
    await fixture.whenStable();

    expect(element.querySelectorAll('.blurb').length).toBe(5);
    expect(element.querySelector('.listing-heading')?.textContent).toContain('21 - 25 of 25');
  });

  it('does not paginate when everything fits on one page', async () => {
    const { element } = await render(20);

    expect(element.querySelectorAll('.blurb').length).toBe(20);
    expect(element.querySelector('.pagination')).toBeNull();
  });

  it('renders the summary as separate paragraphs', async () => {
    const { element } = await render(1);

    expect(element.querySelectorAll('.blurb .summary p').length).toBe(2);
  });

  it('marks titles without a downloaded copy so they are not mistaken for local files', async () => {
    const { element } = await render(1);

    const title = element.querySelector('.heading a.title');
    expect(title?.classList.contains('local')).toBe(false);
    expect(element.querySelector('.meta-line.linked')?.textContent).toContain('No downloaded work files');
  });

  it('links a title to its downloaded copy when the folder has one', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(1));
    library.htmlFiles.set(new Map([['1', new File(['<html></html>'], '1 Work 1 - Writer.html')]]));

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.heading a.title')?.classList.contains('local')).toBe(true);
    expect(element.querySelector('.meta-line.linked')?.textContent).toContain('1 of 1 works');
  });
});
