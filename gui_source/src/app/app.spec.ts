import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './app';
import { Jobs } from './jobs';
import { Library } from './library';
import { Bookmark, BookmarksExport } from './bookmarks';
import { Collection } from './collections';
import { DropboxSession } from './dropbox';
import { HelperConnection } from './helper-connection';

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

/** a library open and writable, as the page has once a folder is picked and set up */
function openLibrary(label = 'downloads'): void {
  const library = TestBed.inject(Library);
  library.folderName.set(label);
  const nothing = async () => {
    throw new Error('not used here');
  };
  library.store.set({
    label,
    check: async () => {},
    list: nothing,
    read: nothing,
    write: nothing,
    size: nothing,
    delete: nothing,
    rename: nothing,
    mkdir: nothing,
  });
}

async function render(count: number) {
  const library = TestBed.inject(Library);
  library.data.set(exportOf(count));
  // works only ever load out of a folder that was opened, and the runs are hidden
  // until one is - so a rendered library comes with the folder it came from
  openLibrary();

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

/** the runs only exist once a folder is picked, which these are all about */
async function withFolder() {
  openLibrary();
  const fixture = TestBed.createComponent(App);
  await fixture.whenStable();
  return fixture.nativeElement as HTMLElement;
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
    const element = await withFolder();

    expect(actionLabels(element).slice(0, 2)).toEqual([
      'Quick Scan',
      '(Full scan) Reindex & Update All',
    ]);
  });

  it('keeps the single-purpose runs behind advanced options', async () => {
    // each is right for exactly one job and confusing as a default, so none of them sits
    // in the way of the two that are not
    const element = await withFolder();

    const advanced = element.querySelector('.advanced');
    expect(advanced?.querySelector('summary')?.textContent?.trim()).toBe('Advanced options');
    expect(
      Array.from(advanced!.querySelectorAll('button')).map((b) => b.textContent?.trim()),
    ).toEqual(['Download/update a specific fic', 'Custom run']);
  });

  // they are the passes the two runs above are built from, kept for working on the app
  // rather than for using it
  it('hides the single-pass runs unless settings.ini turns the debug tools on', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const labels = actionLabels(element).join(' ');
    expect(labels).not.toContain('update incomplete fics');
    expect(labels).not.toContain('marked as incomplete');
    expect(labels).not.toContain('newly added bookmarks');
  });

  it('offers the single-pass runs in red, marked as debug, when they are turned on', async () => {
    TestBed.inject(Jobs).config.set({
      username: '',
      filetypes: ['JSON', 'HTML'],
      forced: ['JSON'],
      defaults: ['JSON', 'HTML'],
      settings: {
        file: 'C:\\app\\config\\settings.ini',
        extraWaitTime: 15,
        fileNamePattern: '{worknum} {title} - {author} {date updated}',
        fileNameLength: 50,
        fileNameExample: '34816549 A Fic - Someone 2026-01-01.html',
        maxRetries: 0,
        maxTimeouts: 3,
        debugLogging: false,
        debugTools: true,
      },
    });

    const element = await withFolder();

    const debug = Array.from(element.querySelectorAll('.actions button.debug')).map((b) =>
      b.textContent?.trim(),
    );
    expect(debug).toEqual([
      '[DEBUG] Download new bookmarks and update incomplete fics',
      '[DEBUG] Just update any bookmarks marked as incomplete',
      '[DEBUG] Just download newly added bookmarks',
    ]);
  });

  // writing into a folder you chose needs an API only Chromium has, and the moment it bites
  // is after a folder is picked and a run started - far too late to be told
  it('opens with no passcode window on a copy that needs none', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    expect((fixture.nativeElement as HTMLElement).querySelector('app-passcode-gate')).toBeNull();
  });

  it('puts the passcode window over the page when the helper wants one', async () => {
    TestBed.inject(HelperConnection).passcodeWanted.set(true);
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const gate = (fixture.nativeElement as HTMLElement).querySelector('app-passcode-gate');
    expect(gate?.textContent).toContain('passcode protected');
  });

  it('says once that this needs a Chromium browser', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const notice = element.querySelector('app-browser-notice');
    expect(notice).toBeTruthy();
    expect(notice?.textContent).toContain('Chromium');
  });

  it('does not say it again once it has been dismissed', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    const dismiss = Array.from(
      element.querySelectorAll<HTMLButtonElement>('app-browser-notice button'),
    ).find((b) => b.textContent?.includes('Got it'));
    dismiss!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-browser-notice')).toBeNull();

    // a second visit, with whatever the first one remembered
    const again = TestBed.createComponent(App);
    await again.whenStable();
    expect(
      (again.nativeElement as HTMLElement).querySelector('app-browser-notice'),
    ).toBeNull();
  });

  // every run reads the folder to see what is already there and writes back into it, so
  // there is nothing sensible to offer before one is picked - and the panel below already
  // asks for one, so an empty button bar above it would only repeat the question
  it('offers no run at all before a downloads folder is chosen', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.actions')).toBeNull();
    expect(actionLabels(element)).toEqual([]);
  });

  it('shows the runs once a folder has been chosen and opened', async () => {
    const library = TestBed.inject(Library);
    library.data.set(exportOf(1));
    openLibrary();

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.actions')).toBeTruthy();
    expect(actionLabels(element)).toContain('Quick Scan');
  });

  it('checks the run history for interrupted runs, with a spinner, before a run window opens',
    async () => {
      const library = TestBed.inject(Library);
      library.data.set(exportOf(1));
      openLibrary();
      let finish: (settled: number) => void = () => undefined;
      const settle = vi.spyOn(TestBed.inject(Jobs), 'settleInterrupted').mockImplementation(
        () => new Promise<number>((resolve) => (finish = resolve)),
      );

      const fixture = TestBed.createComponent(App);
      await fixture.whenStable();
      const element = fixture.nativeElement as HTMLElement;
      Array.from(element.querySelectorAll<HTMLButtonElement>('.actions button'))
        .find((b) => b.textContent?.includes('Quick Scan'))!.click();
      fixture.detectChanges();

      expect(settle).toHaveBeenCalledTimes(1);
      expect(element.querySelector('.checking-runs')?.textContent).toContain(
        'Checking your run history',
      );
      expect(element.querySelector('app-download-dialog')).toBeNull();

      finish(0);
      await fixture.whenStable();
      fixture.detectChanges();

      expect(element.querySelector('.checking-runs')).toBeNull();
      expect(element.querySelector('app-download-dialog')).toBeTruthy();
    });

  it('offers no run for a folder that is only remembered, waiting on a reconnect', async () => {
    // a run writes through the page, and the page cannot write there until access is confirmed
    const library = TestBed.inject(Library);
    library.folderName.set('downloads');
    library.needsReconnect.set(true);

    const element = await (async () => {
      const fixture = TestBed.createComponent(App);
      await fixture.whenStable();
      return fixture.nativeElement as HTMLElement;
    })();

    expect(actionLabels(element)).toEqual([]);
  });

  it('hides the collections runs the same way', async () => {
    // no folder: the collections tab is reachable, but there is nothing to start
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    await showCollections(fixture, element);

    expect(element.querySelector('.actions')).toBeNull();
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
    // collections only ever load out of a folder that was opened, so this state comes with
    // one - and without it the buttons are gated and the gate's own notice is what shows
    library.folderName.set('downloads');

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

  // region the history tab

  it('offers a history tab', async () => {
    const { element } = await render(1);

    expect(tab(element, 'History')).toBeTruthy();
  });

  it('shows past runs with no buttons to act on a folder', async () => {
    const { fixture, element } = await render(1);

    tab(element, 'History')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-history')).toBeTruthy();
    expect(element.querySelector('.actions')).toBeNull();
    expect(element.querySelector('app-work-list')).toBeNull();
  });

  it('reads the history without a folder having been chosen', async () => {
    // it describes runs, not the library, so it does not need one
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    tab(element, 'History')!.click();
    await fixture.whenStable();

    expect(element.querySelector('app-history')).toBeTruthy();
    expect(element.querySelector('.empty')).toBeNull();
  });

  // endregion

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
    expect(said).toContain('Export all issues');
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
    // and that the choice covers every undated file at once, with no per-file option
    expect(said).toContain('applied to all of them at once');
  });

  it('says why a login is needed at all', async () => {
    const { fixture, element } = await render(1);
    tab(element, 'FAQ')!.click();
    await fixture.whenStable();

    const said = element.querySelector('app-faq')?.textContent ?? '';
    expect(said).toContain('Your private bookmarks');
    expect(said).toContain('restricted to registered users');
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

  // region where the library lives

  function storageButton(element: HTMLElement, name: string): HTMLButtonElement {
    return Array.from(element.querySelectorAll<HTMLButtonElement>('.storage button')).find((b) =>
      b.textContent?.includes(name),
    )!;
  }

  it('keeps the library on this computer until told otherwise', async () => {
    const element = await withFolder();
    expect(storageButton(element, 'This computer').getAttribute('aria-pressed')).toBe('true');
    expect(actionLabels(element)).toContain('Quick Scan');
  });

  it('offers no run in dropbox until its folder is open', async () => {
    // the local folder is not where a run would write any more, and dropbox is not signed in
    const fixture = TestBed.createComponent(App);
    openLibrary();
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    storageButton(element, 'Dropbox').click();
    await fixture.whenStable();

    expect(actionLabels(element)).toEqual([]);
    expect(localStorage.getItem('ao3.storageMode')).toBe('dropbox');
  });

  it('remembers the local folder underneath a switch to dropbox and back', async () => {
    const fixture = TestBed.createComponent(App);
    openLibrary();
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    storageButton(element, 'Dropbox').click();
    await fixture.whenStable();
    storageButton(element, 'This computer').click();
    await fixture.whenStable();

    // still the folder that reopens - switching never forgets it
    expect(element.querySelector('.topbar .source')?.textContent).toContain('downloads');
  });

  it('says where to put the app key when this copy has no dropbox app', async () => {
    localStorage.setItem('ao3.storageMode', 'dropbox');
    TestBed.inject(DropboxSession).status.set('unconfigured');
    const element = await withFolder();

    expect(element.querySelector('.empty h2')?.textContent).toContain('not set up');
    expect(element.textContent).toContain('dropbox-config.ts');
    expect(element.textContent).not.toContain('Sign in with Dropbox');
  });

  it('opens the dropbox app folder as soon as someone is signed in', async () => {
    // there is nothing to choose: the app folder is all this app can see, so it is the library
    localStorage.setItem('ao3.storageMode', 'dropbox');
    const dropbox = TestBed.inject(DropboxSession);
    dropbox.status.set('signed-in');
    dropbox.account.set({ id: 'dbid:me', name: 'Me', email: 'me@example.com' });

    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    // what opening the app folder leaves behind, once it is set up
    openLibrary('Dropbox app folder');
    fixture.detectChanges();
    const element = fixture.nativeElement as HTMLElement;

    const source = element.querySelector('.topbar .source');
    expect(source?.textContent).toContain('/Apps/ao3-downloader');
    expect(source?.getAttribute('title')).toContain('me@example.com');
    // the library is open, which is everything a run needs
    expect(actionLabels(element)).toContain('Quick Scan');
    const labels = Array.from(element.querySelectorAll('.topbar button')).map((b) =>
      b.textContent?.trim(),
    );
    expect(labels).toContain('Sign out');
    expect(labels.join(' ')).not.toContain('folder');
  });

  it('says where the library will live before anyone signs in', async () => {
    localStorage.setItem('ao3.storageMode', 'dropbox');
    TestBed.inject(DropboxSession).status.set('signed-out');
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;

    expect(element.querySelector('.empty')?.textContent).toContain('/Apps/ao3-downloader');
    expect(actionLabels(element)).toEqual([]);
  });

  // endregion
});
