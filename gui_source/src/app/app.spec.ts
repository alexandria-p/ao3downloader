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
    // the naming note remembers being dismissed, and that would carry between tests
    localStorage.clear();
    await TestBed.configureTestingModule({ imports: [App] }).compileComponents();
    TestBed.inject(Library).data.set(null);
    TestBed.inject(Library).collections.set([]);
    TestBed.inject(Library).htmlFiles.set(new Map());
  });

  it('leads with the everyday run and then the thorough one', async () => {
    // the order is the recommendation: a full scan is hours, and is not what most runs
    // should be
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(actionLabels(element).slice(0, 2)).toEqual([
      '(Recommended) Download new bookmarks and update incomplete fics',
      '(Full scan) Reindex & Update All',
    ]);
  });

  it('keeps the single-purpose runs behind advanced options', async () => {
    // each is right for exactly one job and confusing as a default, so none of them sits
    // in the way of the two that are not
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const advanced = element.querySelector('.advanced');
    expect(advanced?.querySelector('summary')?.textContent?.trim()).toBe('Advanced options');
    expect(
      Array.from(advanced!.querySelectorAll('button')).map((b) => b.textContent?.trim()),
    ).toEqual([
      'Just update any bookmarks marked as incomplete',
      'Just download newly added bookmarks',
      'Download/update a specific fic',
      'Custom run',
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

  // region the faq tab

  it('offers a faq alongside the two listings', async () => {
    const { element } = await render(1);

    expect(tab(element, 'FAQ')).toBeTruthy();
  });

  it('shows the faq with no buttons to act on a folder', async () => {
    // it is something to read, not a folder to do anything with
    const { fixture, element } = await render(1);

    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-faq')).toBeTruthy();
    expect(element.querySelector('.actions')).toBeNull();
    expect(element.querySelector('app-work-list')).toBeNull();
  });

  it('reads the faq without a folder having been chosen', async () => {
    // the likeliest moment to want it is when a download did not come out as expected,
    // which is also a moment nothing may be loaded
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-faq')).toBeTruthy();
    // and the 'choose a folder' panel steps out of the way
    expect(element.querySelector('.empty')).toBeNull();
  });

  it('answers the things that catch people out', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain('Work skins are stripped');
    expect(said).toContain('audio and video');
    expect(said).toContain('very large one');
    expect(said).toContain('has to start with the AO3 work ID');
    expect(said).toContain('date AO3 says the work was last updated');
    // unbookmarking or deleting a fic on AO3 removes nothing here, which surprises people
    expect(said).toContain('Removing a bookmark does not remove anything here');
    expect(said).toContain('Indexing only ever');
  });

  it('explains what happens when a work cannot be downloaded', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain('as a list, not a number');
    // every reason a bookmark can be passed over
    expect(said).toContain('A series');
    expect(said).toContain('An external work');
    expect(said).toContain('A deleted work');
    expect(said).toContain('made private, or hidden');
    // and what the export gives you
    expect(said).toContain('Export the list');
    expect(element.querySelector('app-faq .mock')).toBeTruthy();
  });

  it('explains the choice offered for files with no date', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain('the run stops and asks');
    expect(said).toContain('Give them a date');
    expect(said).toContain('Re-download them');
    expect(said).toContain('Ignore and skip them');
    expect(
      element.querySelector('app-faq a')?.getAttribute('href'),
    ).toBe('https://archiveofourown.org/faq/downloading-fanworks');
  });

  // endregion

  // region the naming note shown before the folder picker

  function folderButton(element: HTMLElement): HTMLButtonElement {
    return Array.from(element.querySelectorAll<HTMLButtonElement>('.picker button')).find((b) =>
      b.textContent?.includes('folder'),
    )!;
  }

  function warningButton(element: HTMLElement, text: string): HTMLButtonElement | undefined {
    return Array.from(
      element.querySelectorAll<HTMLButtonElement>('app-folder-warning button'),
    ).find((b) => b.textContent?.trim() === text);
  }

  /** the picker this browser actually uses - jsdom has no directory picker, so the input */
  function watchPicker(element: HTMLElement) {
    const input = element.querySelector<HTMLInputElement>('input[type="file"]')!;
    const opened = vi.fn();
    input.click = opened;
    return opened;
  }

  async function clickFolder(fixture: ComponentFixture<App>, element: HTMLElement) {
    const opened = watchPicker(element);
    folderButton(element).click();
    await fixture.whenStable();
    return opened;
  }

  it('says how files have to be named before opening the picker', async () => {
    // the rule cannot be discovered afterwards: files named wrongly still load, they just
    // never match the index. so it is said at the one moment it can be acted on
    const { fixture, element } = await render(0);

    const opened = await clickFolder(fixture, element);

    expect(element.querySelector('app-folder-warning')).toBeTruthy();
    expect(element.querySelector('app-folder-warning')?.textContent).toContain('work ID at the start');
    expect(opened).not.toHaveBeenCalled();
  });

  it('opens the picker once the note has been read', async () => {
    const { fixture, element } = await render(0);
    const opened = await clickFolder(fixture, element);

    warningButton(element, 'Choose folder')!.click();
    await fixture.whenStable();

    expect(opened).toHaveBeenCalled();
    expect(element.querySelector('app-folder-warning')).toBeNull();
  });

  it('opens no picker when the note is backed out of', async () => {
    const { fixture, element } = await render(0);
    const opened = await clickFolder(fixture, element);

    warningButton(element, 'Cancel')!.click();
    await fixture.whenStable();

    expect(opened).not.toHaveBeenCalled();
    expect(element.querySelector('app-folder-warning')).toBeNull();
  });

  it('does not show the note again once it has been turned off', async () => {
    const { fixture, element } = await render(0);
    await clickFolder(fixture, element);

    const box = element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!;
    box.click();
    await fixture.whenStable();
    warningButton(element, 'Choose folder')!.click();
    await fixture.whenStable();

    const opened = await clickFolder(fixture, element);

    expect(element.querySelector('app-folder-warning')).toBeNull();
    expect(opened).toHaveBeenCalled();
  });

  it('keeps asking when the note is turned off but then backed out of', async () => {
    // ticking the box is not the decision; going through with it is. otherwise a change of
    // mind at the last moment silences a warning the user never actually accepted
    const { fixture, element } = await render(0);
    await clickFolder(fixture, element);

    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();
    warningButton(element, 'Cancel')!.click();
    await fixture.whenStable();

    await clickFolder(fixture, element);

    expect(element.querySelector('app-folder-warning')).toBeTruthy();
  });

  // endregion
});
