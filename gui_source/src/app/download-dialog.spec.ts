import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DownloadDialog } from './download-dialog';
import { Library } from './library';
import { LibraryStore, StorageRequest } from './library-store';
import {
  AnswerChoice,
  JobAction,
  JobEvent,
  RunHistory,
  Jobs,
  ServerConfig,
  StartRequest,
  UndatedChoice,
} from './jobs';

const CONFIG: ServerConfig = {
  username: 'Someone',
  filetypes: ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML', 'JSON'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
  settings: {
    file: 'C:\\app\\config\\settings.ini',
    extraWaitTime: 15,
    fileNamePattern: '{worknum} {title} - {author} {date updated}',
    fileNameLength: 50,
    fileNameExample: '34816549 No Paths Are Bound - Cataclys 2026-08-23.html',
    maxRetries: 0,
    maxTimeouts: 3,
    debugLogging: false,
  },
};

/** a library that is open, as far as the dialog needs one */
function fakeStore(label: string): LibraryStore {
  const nothing = async () => {
    throw new Error('not used here');
  };
  return {
    label,
    check: async () => {},
    list: nothing,
    read: nothing,
    write: nothing,
    size: nothing,
    delete: nothing,
    rename: nothing,
    mkdir: nothing,
  };
}

class FakeJobs extends Jobs {
  started: StartRequest[] = [];
  /** the scans the helper would offer as floors */
  floorRunsOnRecord: RunHistory[] = [];

  override async loadFloorRuns(): Promise<RunHistory[] | null> {
    return this.floorRunsOnRecord;
  }

  cancelled: string[] = [];
  answers: { jobId: string; choice: AnswerChoice; date: string }[] = [];
  pauses: { jobId: string; paused: boolean }[] = [];
  /** set by a test that needs answering to fail, leaving the run still waiting */
  answerFails: string | null = null;
  /** set by a test that needs pausing to fail, so the run carries on regardless */
  pauseFails: string | null = null;
  /** job ids a debug skip was asked for */
  skipped: string[] = [];
  /** set by a test that needs a skip to be refused */
  skipFails = false;
  push: ((event: JobEvent) => void) | null = null;
  closed = false;
  /** set by a test that needs settings.ini to say something other than the default */
  settingsOverride: ServerConfig['settings'] | null = null;

  override async loadConfig(): Promise<ServerConfig | null> {
    const config = this.settingsOverride
      ? { ...CONFIG, settings: this.settingsOverride }
      : CONFIG;
    this.config.set(config);
    this.available.set(true);
    return config;
  }

  override async start(request: StartRequest): Promise<string> {
    this.started.push(request);
    return 'job-1';
  }

  /** the storage requests the dialog carried out, and the library it used for each */
  storageAnswered: [string, LibraryStore][] = [];
  override async answerStorage(
    _jobId: string,
    request: StorageRequest,
    store: LibraryStore,
  ): Promise<void> {
    this.storageAnswered.push([request.id, store]);
  }

  override async cancel(jobId: string): Promise<void> {
    this.cancelled.push(jobId);
  }

  override async answer(jobId: string, choice: AnswerChoice, date = ''): Promise<void> {
    if (this.answerFails) throw new Error(this.answerFails);
    this.answers.push({ jobId, choice, date });
  }

  override async setPaused(jobId: string, paused: boolean): Promise<void> {
    if (this.pauseFails) throw new Error(this.pauseFails);
    this.pauses.push({ jobId, paused });
  }

  override async skipStep(jobId: string): Promise<void> {
    if (this.skipFails) throw new Error('could not skip the current step');
    this.skipped.push(jobId);
  }

  override stream(_id: string, onEvent: (e: JobEvent) => void): () => void {
    this.push = onEvent;
    return () => {
      this.closed = true;
    };
  }
}

let jobs: FakeJobs;
let fixture: ComponentFixture<DownloadDialog>;
let element: HTMLElement;

async function open(action: JobAction = 'bookmarks') {
  fixture = TestBed.createComponent(DownloadDialog);
  fixture.componentRef.setInput('action', action);
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function button(text: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll('button')).find(
    (b) => b.textContent?.trim() === text,
  );
}

function checkbox(labelText: string): HTMLInputElement | undefined {
  return Array.from(element.querySelectorAll<HTMLLabelElement>('label.check'))
    .find((l) => l.textContent?.includes(labelText))
    ?.querySelector('input') as HTMLInputElement | undefined;
}

function currentStep(): string {
  return element.querySelector('.dialog')?.getAttribute('data-step') ?? '';
}

/**
 * Walk the wizard to a step, by where it actually is rather than by counting clicks.
 *
 * The steps are not in the same order for every run: a custom run asks its options before
 * the file types and everything else asks them after, and several runs put an
 * acknowledgement in between. Counting clicks made every test quietly depend on which.
 */
async function advanceTo(target: 'options' | 'filetypes' | 'credentials' | 'running') {
  for (let guard = 0; guard < 8; guard++) {
    const at = currentStep();
    if (at === target || at === 'running') return;

    if (at === 'acknowledge') {
      element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
      await fixture.whenStable();
    }

    // the two link actions cannot go on without one, so the walker supplies a valid one
    if (at === 'link') {
      const field = element.querySelector<HTMLInputElement>(
        'input[name="work"], input[name="collection"]',
      )!;
      field.value =
        field.name === 'work'
          ? 'https://archiveofourown.org/works/34816549'
          : 'https://archiveofourown.org/collections/yuletide2024';
      field.dispatchEvent(new Event('input'));
      await fixture.whenStable();
    }

    if (at === 'credentials') {
      const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
      password.value = 'a-password';
      password.dispatchEvent(new Event('input'));
      await fixture.whenStable();
      button('Start download')!.click();
      await fixture.whenStable();
      continue;
    }

    button('Continue')?.click();
    await fixture.whenStable();
  }

  throw new Error(`could not reach ${target}; stuck on ${currentStep()}`);
}

/**
 * Open the custom run and choose the page-slice coverage.
 *
 * It is no longer what the run opens on - 'All bookmarks' is the first row now - so a
 * test about the page inputs has to pick that coverage before they exist.
 */
async function toPageOptions() {
  await open('custom');
  await advanceTo('options');
  checkbox('A slice of your bookmarks listing')!.click();
  await fixture.whenStable();
}

describe('DownloadDialog', () => {
  beforeEach(async () => {
    jobs = new FakeJobs();
    // the remembered username and the combined run's note both live here, and either would
    // carry between tests
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  // region file types

  it('locks the file types that are always produced', async () => {
    await open();
    await advanceTo('filetypes');

    for (const forced of CONFIG.forced) {
      const input = checkbox(forced)!;
      expect(input.checked, forced).toBe(true);
      expect(input.disabled, forced).toBe(true);
    }
    expect(checkbox('EPUB')!.disabled).toBe(false);
    expect(checkbox('EPUB')!.checked).toBe(false);
  });

  it('ticks html to begin with but lets it be turned off', async () => {
    // it costs a request per work on top of the indexing, which is the expensive half
    await open();
    await advanceTo('filetypes');

    const html = checkbox('HTML')!;
    expect(html.checked).toBe(true);
    expect(html.disabled).toBe(false);
  });

  it('asks for metadata only when everything else is unticked', async () => {
    await open('bookmarks');
    await advanceTo('filetypes');
    checkbox('HTML')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].filetypes).toEqual(['JSON']);
  });

  it('tells the helper nothing about where the library is', async () => {
    // the page holds the library and does the reading and writing; the helper only asks
    await open('bookmarks');
    await advanceTo('running');
    expect(Object.keys(jobs.started[0]).sort()).toEqual(
      ['action', 'filetypes', 'options', 'password', 'url', 'username'].filter(
        (key) => key in jobs.started[0],
      ),
    );
    expect(JSON.stringify(jobs.started[0])).not.toMatch(/storage|refresh|dropbox/i);
  });

  it('says files go to the library the page has open', async () => {
    TestBed.inject(Library).store.set(fakeStore('Dropbox app folder'));
    await open('bookmarks');
    await advanceTo('running');
    expect(element.querySelector('.chosen')?.textContent).toContain('Dropbox app folder');
  });

  it('carries out what the helper asks, once each, in the library the run started in', async () => {
    const store = fakeStore('My Fics');
    TestBed.inject(Library).store.set(store);
    await open('bookmarks');
    await advanceTo('running');

    const request = { type: 'storage', id: 'r1', op: 'read', path: 'indexing/1.json' };
    jobs.push!(request as unknown as JobEvent);
    // a page that reconnects is sent unanswered requests again
    jobs.push!(request as unknown as JobEvent);
    // switching library mid-run does not move the run
    TestBed.inject(Library).store.set(fakeStore('Somewhere else'));
    jobs.push!({ type: 'storage', id: 'r2', op: 'list', path: 'works' } as unknown as JobEvent);
    await new Promise((r) => setTimeout(r, 0));

    expect(jobs.storageAnswered.map(([id, used]) => [id, used.label])).toEqual([
      ['r1', 'My Fics'],
      ['r2', 'My Fics'],
    ]);
  });

  it('says what unticking the rest buys, where the choice is made', async () => {
    await open('bookmarks');
    await advanceTo('filetypes');

    expect(element.textContent).toContain('rate limit');
  });

  // endregion

  // region options step

  it('offers series expansion on a full scan, which is where it works', async () => {
    // a series is found on a work's own page, and only a full scan goes the long way round
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('series links')).toBeTruthy();
  });

  it('offers saving images separately only on a custom run', async () => {
    await open('custom');
    await advanceTo('options');
    expect(checkbox('images separately')).toBeTruthy();

    for (const action of ['bookmarks', 'sync', 'new', 'update'] as const) {
      await open(action);
      await advanceTo(currentStep() === 'options' ? 'options' : 'filetypes');
      expect(checkbox('images separately'), action).toBeUndefined();
    }
  });

  it('says plainly what saving images costs and what it is not', async () => {
    // most people do not want this: the pictures are already inside the downloaded work
    await open('custom');
    await advanceTo('options');

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('already embedded inside all regular downloaded works');
    expect(said).toContain('their own folder');
    expect(said).toContain('make the download longer');
  });

  it('asks a full scan nothing about pages', async () => {
    // it covers everything by definition; offering to cut it short makes it a custom run
    // under another name
    await open('bookmarks');
    await advanceTo('options');

    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(element.querySelector('input[name="start"]')).toBeNull();
  });

  it('opens a custom run on all bookmarks, with no slice to fill in', async () => {
    await open('custom');
    await advanceTo('options');

    expect(checkbox('All bookmarks')!.checked).toBe(true);
    expect(element.querySelector('input[name="start"]')).toBeNull();
    expect(element.querySelector('input[name="pages"]')).toBeNull();
  });

  // the inputs keep what was typed in them, so a run switched back to the whole listing
  // would otherwise carry a limit it no longer shows
  it('drops a page range once the run is switched back to all bookmarks', async () => {
    await toPageOptions();

    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '9';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    checkbox('All bookmarks')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(1);
    expect(jobs.started[0].options.pages).toBe(0);
  });

  /**
   * Open the quick scan with the debug tools on.
   *
   * Picking your own date is a debug choice on that run - the point of it is the floor
   * it works out for itself - so with the tools off there is nothing to choose and no
   * options step at all.
   */
  async function openQuickDates() {
    jobs.settingsOverride = { ...CONFIG.settings!, debugTools: true };
    await open('quick');
    await advanceTo('options');
  }

  // a quick scan works out its own floor; a slice of the listing means nothing to it
  // with the date range gone there is nothing left for it to ask, and a step with nothing
  // on it reads as one that failed to load
  // it can always be pointed at an earlier scan, so it always has an options step now - but
  // the hand-picked date range stays a debug choice
  it('keeps the date range off a quick scan unless the debug tools are on', async () => {
    await open('quick');
    await advanceTo('options');

    expect(currentStep()).toBe('options');
    expect(checkbox('Choose which earlier scan to measure back to')).toBeTruthy();
    expect(checkbox('Choose my own date range')).toBeUndefined();
  });

  // region choosing which earlier scan a quick scan measures back to

  function scanOnRecord(id: string, started: string, action = 'quick'): RunHistory {
    return {
      file: `${id}.json`, id, action, actionName: action === 'quick' ? 'Quick Scan' : 'Full scan',
      started, finished: started, status: 'success', filetypes: ['JSON'], options: {},
      reindexed: [], downloaded: [], updated: [], choices: [], failures: [], skipped: [], error: '',
    };
  }

  async function toFloorPage() {
    await open('quick');
    await advanceTo('options');
    checkbox('Choose which earlier scan to measure back to')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
  }

  it('lists the scans that can be measured back to on a page of their own', async () => {
    jobs.floorRunsOnRecord = [
      scanOnRecord('b', '2026-09-01T12:00:00'),
      scanOnRecord('a', '2026-03-04T09:30:00', 'bookmarks'),
    ];

    await toFloorPage();

    expect(currentStep()).toBe('floor');
    const said = element.querySelector('.floor-runs')?.textContent ?? '';
    expect(said).toContain('2026-09-01');
    expect(said).toContain('2026-03-04');
    expect(said).toContain('Full scan');
  });

  it('will not go on until a scan has been chosen', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-03-04T09:30:00')];
    await toFloorPage();

    expect(button('Continue')!.disabled).toBe(true);

    element.querySelector<HTMLInputElement>('input[name="floorRun"]')!.click();
    await fixture.whenStable();

    expect(button('Continue')!.disabled).toBe(false);
  });

  it('sends the chosen scan with the job', async () => {
    jobs.floorRunsOnRecord = [
      scanOnRecord('newer', '2026-09-01T12:00:00'),
      scanOnRecord('older', '2026-03-04T09:30:00'),
    ];
    await toFloorPage();

    element.querySelectorAll<HTMLInputElement>('input[name="floorRun"]')[1].click();
    await fixture.whenStable();
    await advanceTo('running');

    expect(jobs.started[0].options.floorRun).toBe('older');
  });

  it('says so when there is no completed scan to choose', async () => {
    jobs.floorRunsOnRecord = [];

    await toFloorPage();

    const text = element.querySelector('.body')?.textContent ?? '';
    expect(text).toContain('Nothing on record can be measured back to');
    // says which runs would count, since a date-range quick scan on record does not
    expect(text).toContain('full scan');
    expect(text).toContain('quick scan with no date range');
    expect(button('Continue')!.disabled).toBe(true);
  });

  it('comes back to the options from the list', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-03-04T09:30:00')];
    await toFloorPage();

    button('Back')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('options');
  });

  it('names the chosen scan in the note, rather than claiming the last run', async () => {
    jobs.floorRunsOnRecord = [scanOnRecord('a', '2026-03-04T09:30:00')];
    await toFloorPage();
    element.querySelector<HTMLInputElement>('input[name="floorRun"]')!.click();
    await fixture.whenStable();

    await walkToNote();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('since the scan you chose, which started on 2026-03-04');
    expect(said).not.toContain('since the last successful');
  });

  it('sends no floor for a quick scan measuring back to its last run as usual', async () => {
    await open('quick');
    await advanceTo('running');

    expect(jobs.started[0].options.floorRun).toBe('');
  });

  // endregion

  it('offers a quick scan no page slice', async () => {
    await openQuickDates();

    expect(checkbox('A slice of your bookmarks listing')).toBeUndefined();
    expect(checkbox('Anything that has changed since my last run')).toBeTruthy();
  });

  it('asks a custom run which pages to cover', async () => {
    await toPageOptions();

    expect(element.querySelector('input[name="pages"]')).toBeTruthy();
    expect(element.querySelector('input[name="start"]')).toBeTruthy();
  });

  it('offers series expansion to no other run', async () => {
    // nothing else goes the long way round, so there would be nothing to expand into
    for (const action of ['custom', 'sync', 'new', 'update'] as const) {
      await open(action);
      await advanceTo(currentStep() === 'options' ? 'options' : 'filetypes');

      expect(checkbox('series links'), action).toBeUndefined();
    }
  });

  it('skips the options step when there is nothing to choose', async () => {
    // a step with nothing on it reads as one that failed to load
    for (const action of ['sync', 'new', 'update'] as const) {
      await open(action);

      expect(currentStep(), action).toBe('filetypes');
    }
  });

  it('steps back past a skipped options step rather than into it', async () => {
    await open('sync');
    await advanceTo('filetypes');

    // nothing before the file types on this run, so there is nowhere back to go
    expect(button('Cancel')).toBeTruthy();
    expect(button('Back')).toBeUndefined();
  });

  it('does not offer the publication date lookup', async () => {
    // hidden from the ui: it costs one request per work and is rarely worth it
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('publication date')).toBeUndefined();
  });

  it('never asks the helper for publication dates', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].options.workdates).toBe(false);
  });

  it('leaves out the questions that mean nothing for an update run', async () => {
    await open('update');

    // no listing to page through, no work page to read anything off, nothing to date - so
    // there is no options step at all, and it opens on the file types
    expect(currentStep()).toBe('filetypes');
    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(checkbox('series links')).toBeUndefined();
    expect(checkbox('publication date')).toBeUndefined();
    expect(checkbox('images separately')).toBeUndefined();
  });

  it('sends the chosen options with the job', async () => {
    await open('bookmarks');
    await advanceTo('options');

    checkbox('series links')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started).toHaveLength(1);
    expect(jobs.started[0].options).toEqual({
      // a full scan covers the whole listing, so these are not its to choose
      start: 1,
      pages: 0,
      series: true,
      // images are a custom run's to ask for; a full scan is not offered them
      images: false,
      workdates: false,
      // only a custom run may turn this off, so every other run always indexes
      reindex: true,
      // offered on a full scan, but off unless it is asked for
      overwrite: false,
      // the date window is a custom run's alternative to pages; nothing else offers it
      dates: false,
      dateFrom: '',
      dateTo: '',
      // only a quick scan pointed at an earlier scan sends one
      floorRun: '',
    });
  });

  it('sends a custom run told to save images separately', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('images separately')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.images).toBe(true);
  });

  it('sends the page to start on as well as the one to stop after', async () => {
    await toPageOptions();

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '5';
    start.dispatchEvent(new Event('input'));
    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '9';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(5);
    expect(jobs.started[0].options.pages).toBe(9);
  });

  /** tick the date range, and fill in the dates the chosen shape of window offers */
  async function chooseWindow(from: string, to = '') {
    checkbox('date range')!.click();
    await fixture.whenStable();

    if (to) {
      checkbox('Between two dates')!.click();
      await fixture.whenStable();
      const upper = element.querySelector<HTMLInputElement>('input[name="dateTo"]')!;
      upper.value = to;
      upper.dispatchEvent(new Event('input'));
    }

    const lower = element.querySelector<HTMLInputElement>('input[name="dateFrom"]')!;
    lower.value = from;
    lower.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('sends a date window instead of pages when the custom run asks for one', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01', '2024-06-30');

    await advanceTo('running');

    expect(jobs.started[0].options.dates).toBe(true);
    expect(jobs.started[0].options.dateFrom).toBe('2024-01-01');
    expect(jobs.started[0].options.dateTo).toBe('2024-06-30');
  });

  // 'since a date' is open at the top, so there is no newer end to send. a date left over
  // from a moment when 'between two dates' was ticked would silently narrow the run
  it('sends no newer end for a window that is open at the top', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01', '2024-06-30');

    checkbox('Everything updated since')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="dateTo"]')).toBeNull();

    await advanceTo('running');

    expect(jobs.started[0].options.dateFrom).toBe('2024-01-01');
    expect(jobs.started[0].options.dateTo).toBe('');
  });

  // the live example, the same thing the page slice offers. read newest first, because
  // that is the direction the run works in
  it('says what a window covers while it is being chosen', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01');

    expect(element.textContent).toContain(
      'any works that were updated between today and 2024-01-01',
    );

    await chooseWindow('2024-01-01', '2024-06-30');

    expect(element.textContent).toContain(
      'any works that were updated between 2024-06-30 and 2024-01-01',
    );
  });

  // the earliest date is what the indexing walk stops at, so without one it reads the lot
  it('warns that a window with no earliest date indexes the whole listing', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('');

    expect(element.textContent).toContain('reads the whole listing');

    await chooseWindow('2024-01-01');

    expect(element.textContent).not.toContain('reads the whole listing');
    expect(element.textContent).toContain('stops at the first fic older than');
  });

  // the two are alternatives, so choosing the window has to take the page inputs away
  // rather than leave a slice showing that the run will not honour
  it('hides the page inputs while the date window is chosen', async () => {
    await toPageOptions();

    expect(element.querySelector('input[name="start"]')).not.toBeNull();

    checkbox('date range')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="start"]')).toBeNull();
    expect(element.querySelector('input[name="pages"]')).toBeNull();

    checkbox('bookmarks listing')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="start"]')).not.toBeNull();
  });

  // an end left empty means no limit there, and the summary has to say so - a blank in a
  // list of what the run will do reads as something that failed to fill in
  it('describes an open-ended window in the summary of what was chosen', async () => {
    await open('custom');
    await advanceTo('options');
    await chooseWindow('2024-01-01');

    await advanceTo('running');

    expect(element.textContent).toContain(
      'any works that were updated between today and 2024-01-01',
    );
  });

  // nothing but a custom run works from a date window, so nothing else may show the choice
  it('offers the date window on the custom run alone', async () => {
    await open('bookmarks');
    await advanceTo('options');

    expect(checkbox('date range')).toBeUndefined();
  });

  it('treats a blank or first page as starting at the beginning', async () => {
    await toPageOptions();

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '';
    start.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(1);
  });

  it('says which slice of the listing the run will cover', async () => {
    await toPageOptions();

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '5';
    start.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(element.textContent).toContain('page 5 onwards');
  });

  it('treats a blank or zero page limit as every page', async () => {
    await toPageOptions();

    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '';
    pages.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.pages).toBe(0);
  });

  // endregion

  // region syncing collections

  async function startCollections() {
    const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
    password.value = 'a-password';
    password.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    button('Start download')?.click();
    await fixture.whenStable();
  }

  // endregion

  // region acknowledging what an update pass cannot see

  async function toAcknowledgement(): Promise<void> {
    await open('update');
    button('Continue')?.click();
    await fixture.whenStable();
    button('Continue')?.click();
    await fixture.whenStable();
  }

  function acknowledgeBox(): HTMLInputElement | null {
    return element.querySelector<HTMLInputElement>('input[name="acknowledge"]');
  }

  it('asks an update run to acknowledge the gap before the login', async () => {
    await toAcknowledgement();

    expect(acknowledgeBox()).toBeTruthy();
    expect(element.querySelector('input[name="password"]')).toBeNull();
  });

  it('says plainly what an update pass will not find', async () => {
    await toAcknowledgement();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('will not find a fic that was already finished');
    // and points at the run that does catch those
    expect(said).toContain('Reindex & Update All');
  });

  // the other half of the same limitation: the first is about fics the index has but calls
  // finished, this about fics the index has never heard of
  it('says it will not see unfinished fics bookmarked since the last scan', async () => {
    await toAcknowledgement();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('will not pick up unfinished fics you have bookmarked since');
    expect(said).toContain('reads no listing');
  });

  it('will not go on until it has actually been acknowledged', async () => {
    await toAcknowledgement();

    expect(button('Continue')?.disabled).toBe(true);

    acknowledgeBox()!.click();
    await fixture.whenStable();

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('reaches the login once acknowledged', async () => {
    await toAcknowledgement();
    acknowledgeBox()!.click();
    await fixture.whenStable();

    button('Continue')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('lets you go back to the note from the login', async () => {
    await toAcknowledgement();
    acknowledgeBox()!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(acknowledgeBox()).toBeTruthy();
  });

  it('asks no such thing of a bookmarks run', async () => {
    await open('bookmarks');
    await advanceTo('credentials');

    expect(acknowledgeBox()).toBeNull();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('asks no such thing of a collections run', async () => {
    await open('collections');

    expect(acknowledgeBox()).toBeNull();
  });

  // endregion

  // region works that would not download

  const FAILURES = [
    { id: '111', link: 'https://archiveofourown.org/works/111', error: 'deleted' },
    { id: '222', link: 'https://archiveofourown.org/works/222', error: 'locked' },
  ];

  async function finishWithFailures(failures = FAILURES): Promise<void> {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'failures', failures });
    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();
  }

  it('says which works could not be downloaded', async () => {
    await finishWithFailures();

    const shown = element.querySelector('.failures')?.textContent ?? '';
    expect(shown).toContain('2');
    expect(shown).toContain('111');
    expect(shown).toContain('222');
    expect(shown).toContain('deleted');
  });

  it('makes clear the rest of the run still succeeded', async () => {
    await finishWithFailures();

    expect(element.querySelector('.failures')?.textContent).toContain(
      'Everything else was saved',
    );
  });

  it('links a failed work so it can be looked up', async () => {
    await finishWithFailures();

    const link = element.querySelector<HTMLAnchorElement>('.failed-list a')!;
    expect(link.getAttribute('href')).toBe('https://archiveofourown.org/works/111');
  });

  it('says nothing about failures when every work came down', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();

    expect(element.querySelector('.failures')).toBeNull();
  });

  it('does not list every one of a long list, but says how many there are', async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      id: String(i), link: `https://archiveofourown.org/works/${i}`, error: 'gone',
    }));

    await finishWithFailures(many);

    expect(element.querySelectorAll('.failed-list li')).toHaveLength(5);
    expect(element.querySelector('.failures')?.textContent).toContain('7 more');
  });

  it('offers one export for every issue', async () => {
    await finishWithFailures();

    expect(button('Export all issues')).toBeTruthy();
  });

  it('exports the work numbers, links and reasons', async () => {
    await finishWithFailures();

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();

    const lines = report.trim().split('\n');
    expect(report).toContain('## 2 works that could not be downloaded');
    expect(lines.at(-2)).toBe('111\thttps://archiveofourown.org/works/111\tdeleted');
    expect(lines.at(-1)).toBe('222\thttps://archiveofourown.org/works/222\tlocked');
  });

  it('keeps an error that spans lines on one line of the export', async () => {
    // one work per line is the point: it has to stay feedable back in
    await finishWithFailures([
      { id: '111', link: 'https://archiveofourown.org/works/111', error: 'went\n  wrong' },
    ]);

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();

    expect(report.trim().split('\n').at(-1)).toBe(
      '111\thttps://archiveofourown.org/works/111\twent wrong');
    expect(report).toContain('111\thttps://archiveofourown.org/works/111\twent wrong');
  });

  // endregion

  // region copies already on disk

  it('decides nothing about undated files up front', async () => {
    // what to do with them is asked during the run, once the count is known
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].options).not.toHaveProperty('refreshUndated');
    expect(jobs.started[0].options).not.toHaveProperty('stampUndated');
  });

  it('adds nothing to the running view about the copies already downloaded', async () => {
    // there used to be a standing panel here. the log says all of this as it happens, a
    // line at a time, so the panel only repeated what was already on screen
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 3, undated: 12, stamped: 40 });
    await fixture.whenStable();

    expect(element.querySelector('.refresh')).toBeNull();
  });

  it('counts the out-of-date copies in the summary once the run is over', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 3, undated: 12 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('3');
    expect(said).toContain('out of date');
  });

  it('counts the files it dated in the summary once the run is over', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 0, undated: 0, stamped: 40 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('40');
    expect(said).toContain('given a date');
  });

  it('says nothing about copies on disk when there is nothing to say', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'refresh', stale: 0, undated: 0 });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).not.toContain('out of date');
    expect(said).not.toContain('given a date');
  });

  // endregion

  // region being asked what to do about undated files

  async function askedAboutUndated(count = 12): Promise<void> {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'question',
      name: 'undated',
      count,
      choices: ['stamp', 'refresh', 'skip'],
    });
    await fixture.whenStable();
  }

  /** the quick scan's question: no run to measure from, but an index already here */
  async function askedAboutTheFloor(count = 240, date = '2026-09-10'): Promise<void> {
    await open('quick');
    await advanceTo('running');
    jobs.push!({
      type: 'question',
      name: 'quick-floor',
      count,
      date,
      choices: ['since', 'full'],
    });
    await fixture.whenStable();
  }

  // more than one question can stop a run, and they go back through the same endpoint -
  // so the panel has to be keyed on which one is being asked, not on the count
  it('asks how far back a quick scan should go, in its own words', async () => {
    await askedAboutTheFloor();

    const said = element.querySelector('.question')?.textContent ?? '';
    expect(said).toContain('no record of a completed scan');
    expect(said).toContain('240');
    expect(said).toContain('2026-09-10');
    // and not the undated question's wording
    expect(said).not.toContain('before file names carried a date');
  });

  it('measures back to the index date when that is what was chosen', async () => {
    await askedAboutTheFloor();

    button('Find what has changed since 2026-09-10')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'since', date: '' }]);
    expect(element.querySelector('.question')).toBeNull();
  });

  it('reads the whole listing when that is what was chosen', async () => {
    await askedAboutTheFloor();

    button('Read my whole listing')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'full', date: '' }]);
  });

  it('still shows the undated question its own panel', async () => {
    await askedAboutUndated();

    const said = element.querySelector('.question')?.textContent ?? '';
    expect(said).toContain('before file names carried a date');
    expect(said).not.toContain('no record of a completed scan');
    expect(button('Ignore and skip them')).toBeTruthy();
  });

  it('asks during the run, not after it', async () => {
    // the answer decides what counts as out of date, so asking afterwards is too late
    await askedAboutUndated();

    expect(element.querySelector('.question')).toBeTruthy();
    expect(element.querySelector('.offer')).toBeNull();
  });

  it('offers all three ways out', async () => {
    await askedAboutUndated();

    expect(button('Give them a date')).toBeTruthy();
    expect(button('Re-download them')).toBeTruthy();
    expect(button('Ignore and skip them')).toBeTruthy();
  });

  it('says what each of them costs', async () => {
    await askedAboutUndated();

    const said = element.querySelector('.question')?.textContent ?? '';
    expect(said).toContain('12');
    expect(said).toContain('no downloads');
    expect(said).toContain('removes the old copies');
  });

  it('says nothing when the run has not asked anything', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.question')).toBeNull();
  });

  it('sends the choice to skip them', async () => {
    await askedAboutUndated();

    button('Ignore and skip them')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'skip', date: '' }]);
  });

  it('sends the choice to fetch them all again', async () => {
    await askedAboutUndated();

    button('Re-download them')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'refresh', date: '' }]);
  });

  it('defaults the date to today, meaning what I have is current', async () => {
    await askedAboutUndated();

    button('Give them a date')!.click();
    await fixture.whenStable();

    const box = element.querySelector<HTMLInputElement>('input[name="stampDate"]')!;
    expect(box.value).toBe(new Date().toISOString().slice(0, 10));
  });

  it('will not answer with something that is not a real date', async () => {
    await askedAboutUndated();
    button('Give them a date')!.click();
    await fixture.whenStable();

    const box = element.querySelector<HTMLInputElement>('input[name="stampDate"]')!;
    box.value = '2024-02-31';
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(button('Date them and continue')?.disabled).toBe(true);
    expect(jobs.answers).toEqual([]);
  });

  it('sends the chosen date', async () => {
    await askedAboutUndated();
    button('Give them a date')!.click();
    await fixture.whenStable();

    const box = element.querySelector<HTMLInputElement>('input[name="stampDate"]')!;
    box.value = '2024-06-01';
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    button('Date them and continue')!.click();
    await fixture.whenStable();

    expect(jobs.answers).toEqual([{ jobId: 'job-1', choice: 'stamp', date: '2024-06-01' }]);
  });

  it('can back out of choosing a date', async () => {
    await askedAboutUndated();
    button('Give them a date')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(element.querySelector('input[name="stampDate"]')).toBeNull();
    expect(button('Re-download them')).toBeTruthy();
  });

  it('does not ask the same question twice over', async () => {
    await askedAboutUndated();

    button('Ignore and skip them')!.click();
    button('Ignore and skip them')?.click();
    await fixture.whenStable();

    expect(jobs.answers).toHaveLength(1);
  });

  it('puts the question away once it has been answered', async () => {
    await askedAboutUndated();

    button('Ignore and skip them')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.question')).toBeNull();
  });

  it('says so when the answer could not be delivered, since the run is still waiting', async () => {
    await askedAboutUndated();
    jobs.answerFails = 'helper went away';

    button('Ignore and skip them')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.log')?.textContent).toContain('helper went away');
    // still asking, so it can be tried again
    expect(element.querySelector('.question')).toBeTruthy();
  });

  it('does not carry an answer over from a previous run', async () => {
    await askedAboutUndated();
    button('Ignore and skip them')!.click();
    await fixture.whenStable();

    jobs.push!({ type: 'question', name: 'undated', count: 3, choices: [] });
    await fixture.whenStable();

    expect(element.querySelector('.question')?.textContent).toContain('3');
    // the buttons are live again, rather than still locked from the last answer
    expect(button('Ignore and skip them')?.disabled).toBe(false);
  });

  // endregion

  // region indexing one collection by link

  const LINK = 'https://archiveofourown.org/collections/yuletide2024';

  function linkBox(): HTMLInputElement {
    return element.querySelector<HTMLInputElement>('input[name="collection"]')!;
  }

  async function typeLink(url: string): Promise<void> {
    const box = linkBox();
    box.value = url;
    box.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('asks for the link first, before anything else', async () => {
    await open('collection');

    expect(linkBox()).toBeTruthy();
    expect(element.querySelector('input[name="password"]')).toBeNull();
    expect(element.querySelector('.dialog fieldset')).toBeNull();
  });

  it('will not go on until the link is one it can use', async () => {
    await open('collection');
    expect(button('Continue')?.disabled).toBe(true);

    await typeLink(LINK);

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('says what is wrong with a link that is not a collection', async () => {
    await open('collection');

    await typeLink('https://archiveofourown.org/works/123');

    expect(button('Continue')?.disabled).toBe(true);
    expect(element.querySelector('.error')?.textContent).toContain('not a link to a collection');
  });

  it('accepts a link to any page of the collection', async () => {
    await open('collection');

    await typeLink(LINK + '/works?page=2');

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('sends the link with the job', async () => {
    await open('collection');
    await typeLink(LINK);
    button('Continue')!.click();
    await fixture.whenStable();
    await startCollections();

    expect(jobs.started[0].action).toBe('collection');
    expect(jobs.started[0].url).toBe(LINK);
  });

  it('lets you go back to correct the link', async () => {
    await open('collection');
    await typeLink(LINK);
    button('Continue')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(linkBox().value).toBe(LINK);
  });

  it('never sends a link on a job that does not take one', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(jobs.started[0].url).toBeUndefined();
  });

  // endregion

  // region the settings a run is using

  it('shows what settings.ini says, so the run can be taken at its word', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('15');
    expect(shown).toContain('{worknum} {title} - {author}');
    expect(shown).toContain('50');
  });

  // the wizard pages are gone by the time the run is working, so this panel is the only
  // place the answers given on them still exist
  it('reads back the file types chosen on the way in', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.settings')?.textContent).toContain('File types');
    expect(element.querySelector('.settings')?.textContent).toContain('JSON, HTML');
  });

  it('reads back the options chosen on the way in', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Overwrite existing downloads')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('overwritten, current or not');
    expect(shown).toContain("reading AO3's listing");
    expect(shown).toContain('all bookmarks');
  });

  it('leaves out settings the run never asked about', async () => {
    // a setting shown for a run that does not offer it reads as one decided behind you
    await open('update');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('File types');
    expect(shown).not.toContain('Series links');
    expect(shown).not.toContain('Existing files');
    expect(shown).not.toContain('Covers');
  });

  it('spells out how files are named, including the date', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('{worknum} {title} - {author} {date updated}');
    expect(shown).toContain('cut to 50 characters');
  });

  it('shows the naming as a real example, and says it cannot be changed', async () => {
    await open('bookmarks');
    await advanceTo('running');

    const shown = element.querySelector('.settings')?.textContent ?? '';
    expect(shown).toContain('34816549 No Paths Are Bound - Cataclys 2026-08-23.html');
    expect(shown).toContain('may be shortened to fit');
  });

  it('names the settings file it read, since which one is in force is not obvious', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.settings')?.textContent).toContain(
      'C:\\app\\config\\settings.ini',
    );
  });

  it('flags a zero wait, which is what trips the rate limit', async () => {
    jobs.settingsOverride = { ...CONFIG.settings!, extraWaitTime: 0 };
    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.settings .warn')?.textContent).toContain('rate limit');
  });

  // endregion

  // region syncing your own collections

  it('names itself after the job it is doing', async () => {
    await open('collections');

    expect(element.querySelector('.dialog h2')?.textContent?.trim()).toBe('Index my collections');
  });

  it('goes straight to the login, since there is nothing to choose', async () => {
    // collections write metadata only: no file types, no download options
    await open('collections');

    expect(element.querySelector('input[name="password"]')).toBeTruthy();
    expect(element.querySelector('.dialog fieldset')).toBeNull();
    expect(element.querySelector('.dialog input[type="number"]')).toBeNull();
  });

  it('offers no way back past the login', async () => {
    await open('collections');

    expect(button('Back')).toBeUndefined();
    expect(button('Cancel')).toBeTruthy();
  });

  it('sends the collections action', async () => {
    await open('collections');
    await startCollections();

    expect(jobs.started).toHaveLength(1);
    expect(jobs.started[0].action).toBe('collections');
  });

  it('still shows progress and a stop button while it runs', async () => {
    await open('collections');
    await startCollections();

    jobs.push!({ type: 'phase', name: 'collections' });
    jobs.push!({ type: 'work', title: 'Best of DCMK', phase: 'collections', done: 1 });
    await fixture.whenStable();

    expect(element.querySelector('.current')?.textContent).toContain('Best of DCMK');
    expect(button('Stop')).toBeTruthy();
  });

  // endregion

  // region running

  it('shows what the run was asked to do', async () => {
    TestBed.inject(Library).store.set(fakeStore('my_downloads'));
    await open('bookmarks');
    await advanceTo('running');

    const chosen = element.querySelector('.chosen')?.textContent ?? '';
    expect(chosen).toContain('JSON');
    expect(chosen).toContain('HTML');
    // the library the page has open - the helper has none of its own to name
    expect(chosen).toContain('my_downloads');
  });

  it('shows back only the settings the run was actually offered', async () => {
    // a full scan is not asked which pages to cover, so showing a page range back at it
    // reads as a setting that was chosen rather than one that does not exist
    await open('bookmarks');
    await advanceTo('running');
    expect(element.querySelector('.chosen')?.textContent).not.toContain('pages');

    // and a custom run says so only once it has actually been asked for a slice
    await toPageOptions();
    await advanceTo('running');
    expect(element.querySelector('.chosen')?.textContent).toContain('all pages');
  });

  it('names the fic and the format currently being fetched', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'work', title: '123 A Fic - Author', filetype: 'EPUB' });
    await fixture.whenStable();

    const current = element.querySelector('.current')?.textContent ?? '';
    expect(current).toContain('123 A Fic - Author');
    expect(current).toContain('EPUB');
  });

  it('keeps the fic name when a work event carries no format', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'work', title: '123 A Fic - Author' });
    await fixture.whenStable();

    const current = element.querySelector('.current')?.textContent ?? '';
    expect(current).toContain('123 A Fic - Author');
  });

  it('names the stage the run is in', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'indexing' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain('Indexing');

    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain('Downloading works');
  });

  it('shows what is being fetched only while something is being fetched', async () => {
    // this line used to stand there permanently reading 'Reading the bookmarks listing',
    // which was a plain lie during the login and during every stage of an update run
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
    expect(element.querySelector('.current')).toBeNull();

    jobs.push!({ type: 'work', title: 'A Fic', filetype: 'EPUB', done: 1, total: 3 });
    await fixture.whenStable();
    expect(element.querySelector('.current')?.textContent).toContain('A Fic');
    expect(element.querySelector('.current')?.textContent).toContain('Downloading');
  });

  it('stops naming a fic once that stage is over', async () => {
    // otherwise the panel sits there still naming whatever it happened to finish on
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'phase', name: 'downloading' });
    jobs.push!({ type: 'work', title: 'A Fic', done: 1, total: 3 });
    await fixture.whenStable();
    expect(element.querySelector('.current')).toBeTruthy();

    jobs.push!({ type: 'phase', name: 'collections' });
    await fixture.whenStable();

    expect(element.querySelector('.current')).toBeNull();
  });

  it('puts what is being fetched between the step and the bar', async () => {
    // it qualifies the step - that says which part of the run, this says which fic - so it
    // belongs with it rather than stranded below the progress bar
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'downloading' });
    jobs.push!({ type: 'work', title: 'A Fic', done: 1, total: 3 });
    await fixture.whenStable();

    const order = Array.from(element.querySelectorAll('.phase, .current, .bar'));
    expect(order.map((e) => e.className.split(' ')[0])).toEqual(['phase', 'current', 'bar']);
  });

  it('says Updating rather than Downloading during an update run', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'phase', name: 'updating' });
    jobs.push!({ type: 'work', title: 'A Fic', done: 1, total: 3 });
    await fixture.whenStable();

    expect(element.querySelector('.current')?.textContent).toContain('Updating');
  });

  // region the runs and what each says it cannot do

  /**
   * Walk on to the acknowledgement from wherever the dialog is, or to the login if this
   * run has no note to show.
   *
   * By where it has got to rather than by counting clicks: which steps come before the
   * note varies per run, and a count quietly depends on that. It stops at the login as
   * well, because a note that has been turned off leaves no step to stop at - and whether
   * that happened is what several of these tests are checking.
   */
  async function walkToNote() {
    for (let guard = 0; guard < 6; guard++) {
      const at = currentStep();
      if (at === 'acknowledge' || at === 'credentials') return;
      button('Continue')?.click();
      await fixture.whenStable();
    }
  }

  async function toNote(action: 'bookmarks' | 'sync' | 'update' | 'quick') {
    await open(action);
    await walkToNote();
  }

  it('warns that a full scan is a long job and names the lighter run', async () => {
    await toNote('bookmarks');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('take a really long time');
    expect(said).toContain('Download new bookmarks and update incomplete fics');
    expect(button('Continue')?.disabled).toBe(true);
  });

  it('says what the combined run trusts and what it will miss', async () => {
    await toNote('sync');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('trusts the index you already have');
    expect(said).toContain('already marked complete');
    expect(said).toContain('Reindex & Update All');
  });

  it('lets the combined run’s note be turned off, once it is accepted', async () => {
    await toNote('sync');
    element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();

    await toNote('sync');

    // straight past it to the login this time
    expect(element.querySelector('input[name="acknowledge"]')).toBeNull();
    expect(element.querySelector('input[name="password"]')).toBeTruthy();
  });

  it('keeps asking when the note is turned off but then backed out of', async () => {
    // ticking the box is not the decision; going through with it is
    await toNote('sync');
    element.querySelector<HTMLInputElement>('input[name="dontAskAgain"]')!.click();
    await fixture.whenStable();

    await toNote('sync');

    expect(element.querySelector('input[name="acknowledge"]')).toBeTruthy();
  });

  it('warns that a quick scan does a full index the first time', async () => {
    // there is nothing to measure back to until a run has completed, so the first one
    // walks the whole listing - which on a large library is hours, not minutes
    await toNote('quick');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('this will perform a full index');
    expect(said).toContain('may take several hours');
  });

  it('gives a quick scan its own caveat rather than the combined run’s', async () => {
    // a quick scan does re-read completed fics that changed, so the combined run's warning
    // about those would be untrue here
    await toNote('quick');

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('will not be restored by this Quick Scan');
    expect(said).toContain('(Full scan) Reindex & Update All');
    expect(said).not.toContain('not notice changes to fics already marked complete');
    expect(said).not.toContain('three passes');
  });

  // the answer to a damaged or truncated file, which no version check can see: the name
  // and the date are both right and only the bytes are wrong
  it.each(['bookmarks', 'custom'] as const)(
    'lets a %s run overwrite files nothing says are out of date',
    async (action) => {
      await open(action);
      await advanceTo('options');

      checkbox('Overwrite existing downloads')!.click();
      await fixture.whenStable();

      await advanceTo('running');

      expect(jobs.started[0].options.overwrite).toBe(true);
    },
  );

  // they exist to be cheap, and a run that re-fetches everything it holds is the opposite
  it.each(['sync', 'quick', 'update', 'work'] as const)(
    'does not offer %s the option to overwrite',
    async (action) => {
      await open(action);
      await advanceTo('filetypes');

      expect(checkbox('Overwrite existing downloads')).toBeUndefined();
    },
  );

  it('leaves overwriting off unless it is asked for', async () => {
    await open('custom');
    await advanceTo('running');

    expect(jobs.started[0].options.overwrite).toBe(false);
  });

  // a quick scan's two shapes, in its own words: the floor it works out for itself, or one
  // the user gives it
  it('offers a quick scan its own pair of coverage choices', async () => {
    await openQuickDates();

    expect(checkbox('Anything that has changed since my last run')).toBeTruthy();
    expect(checkbox('[DEBUG] Choose my own date range')).toBeTruthy();
    // that is the custom run's wording, and it walks no slice of the listing
    expect(checkbox('A slice of your bookmarks listing')).toBeUndefined();
    expect(element.querySelector('input[name="start"]')).toBeNull();
  });

  it('sends a quick scan the date range it was given', async () => {
    await openQuickDates();

    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();
    const from = element.querySelector<HTMLInputElement>('input[name="dateFrom"]')!;
    from.value = '2026-01-01';
    from.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.dates).toBe(true);
    expect(jobs.started[0].options.dateFrom).toBe('2026-01-01');
  });

  it('leaves a quick scan measuring back to the last run unless told otherwise', async () => {
    await open('quick');
    await advanceTo('running');

    expect(jobs.started[0].options.dates).toBe(false);
  });

  // the caveats differ: measuring back to the last run and measuring back to a date you
  // picked fail in different ways, so one note cannot cover both
  // the same method as the ordinary quick scan, given two dates instead of an earlier scan
  it('explains that a quick scan date range reads by date bookmarked, then by date updated', async () => {
    await openQuickDates();
    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();
    const from = element.querySelector<HTMLInputElement>('input[name="dateFrom"]')!;
    from.value = '2026-01-01';
    from.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('by date bookmarked');
    expect(said).toContain('by date updated');
    expect(said).toContain('any works that were bookmarked or updated between today and 2026-01-01');
    // the custom run's single-walk wording does not belong here
    expect(said).not.toContain('re-read one at a time');
  });

  it('keeps the custom run date range worded as a single walk by date updated', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('sorted by when AO3 last updated each work');
    expect(said).not.toContain('by date bookmarked');
  });

  it('gives a quick scan over a date range its own caveats', async () => {
    await openQuickDates();

    checkbox('Choose my own date range')!.click();
    await fixture.whenStable();
    await walkToNote();

    const said = element.querySelector('.dialog .body')?.textContent ?? '';
    expect(said).toContain('bookmarked');
    expect(said).toContain('in this date range');
    expect(said).toContain('once by date bookmarked and once by date updated');
    expect(said).not.toContain('since the last successful run');
    expect(said).not.toContain('will not be restored by this Quick Scan');
  });

  it('never lets the full scan note be turned off', async () => {
    // it is the run that costs hours; it says so every time
    await toNote('bookmarks');

    expect(element.querySelector('input[name="dontAskAgain"]')).toBeNull();
  });

  it('asks a single-fic run for a work, by link or by number', async () => {
    await open('work');

    const input = element.querySelector<HTMLInputElement>('input[name="work"]')!;
    expect(input).toBeTruthy();
    expect(button('Continue')?.disabled).toBe(true);

    input.value = '34816549';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(button('Continue')?.disabled).toBe(false);
  });

  it('refuses a single-fic run anything that is not one work', async () => {
    await open('work');
    const input = element.querySelector<HTMLInputElement>('input[name="work"]')!;

    input.value = 'https://archiveofourown.org/collections/yuletide';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(button('Continue')?.disabled).toBe(true);
    expect(element.querySelector('.error')?.textContent).toContain('not an AO3 work');
  });

  it('takes a chapter link as the work it belongs to', async () => {
    await open('work');
    const input = element.querySelector<HTMLInputElement>('input[name="work"]')!;

    input.value = 'https://archiveofourown.org/works/34816549/chapters/86677150';
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(button('Continue')?.disabled).toBe(false);
  });

  it('offers skipping the indexing only on a custom run', async () => {
    await open('custom');
    await advanceTo('options');
    expect(checkbox('Skip indexing')).toBeTruthy();

    await open('bookmarks');
    await advanceTo('options');
    expect(checkbox('Skip indexing')).toBeUndefined();
  });

  it('asks a custom run its options before its file types', async () => {
    // one of its options decides a file type, so asking which types you want and then
    // changing one behind you would read as the dialog overruling you
    await open('custom');
    expect(currentStep()).toBe('options');

    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('filetypes');
  });

  it('asks every run its options before its file types', async () => {
    // two orders is one more than anybody needs to learn
    await open('bookmarks');
    expect(currentStep()).toBe('options');

    button('Continue')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('filetypes');
  });

  it('lets a custom run step back from the file types to its options', async () => {
    await open('custom');
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    button('Back')!.click();
    await fixture.whenStable();

    expect(currentStep()).toBe('options');
  });

  it('ties a custom run’s JSON to whether it is indexing', async () => {
    // json *is* the index, so a run that indexes writes it and a run that does not cannot
    await open('custom');
    await advanceTo('options');
    button('Continue')!.click();
    await fixture.whenStable();

    const json = checkbox('JSON')!;
    expect(json.checked).toBe(true);
    expect(json.disabled).toBe(true);
  });

  it('unticks and locks a custom run’s JSON when it is not indexing', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Skip indexing')!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();

    const json = checkbox('JSON')!;
    expect(json.checked).toBe(false);
    expect(json.disabled).toBe(true);
    expect(element.querySelector('.body')?.textContent).toContain('no JSON is written');
  });

  it('does not ask the helper for JSON it will not write', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Skip indexing')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].filetypes).not.toContain('JSON');
    expect(jobs.started[0].filetypes).toContain('HTML');
  });

  it('asks the helper for JSON when the custom run is indexing', async () => {
    await open('custom');
    await advanceTo('running');

    expect(jobs.started[0].filetypes).toContain('JSON');
  });

  it('leaves JSON locked on for every other run', async () => {
    await open('bookmarks');
    await advanceTo('filetypes');

    const json = checkbox('JSON')!;
    expect(json.checked).toBe(true);
    expect(json.disabled).toBe(true);
  });

  it('sends a custom run told to skip indexing', async () => {
    await open('custom');
    await advanceTo('options');
    checkbox('Skip indexing')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.reindex).toBe(false);
  });

  it('asks the lighter runs nothing about pages', async () => {
    // they start at the first page by definition; there is nothing to choose
    await open('sync');
    await advanceTo('options');

    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(element.querySelector('input[name="start"]')).toBeNull();
  });

  it('says a long run is expected to be left running', async () => {
    await open('sync');
    await advanceTo('running');

    expect(element.querySelector('.warning')?.textContent).toContain('may take a long time');
    expect(element.querySelector('.warning')?.textContent).toContain('Leave this tab open');
  });

  // endregion

  // region the debug panel

  async function runningWithDebug(on: boolean) {
    jobs.settingsOverride = { ...CONFIG.settings!, debugTools: on };
    await open('sync');
    await advanceTo('running');
  }

  it('hides the debug panel unless settings.ini asks for it', async () => {
    // skipping a step really skips it, so this is not something to leave lying about
    await runningWithDebug(false);

    expect(element.querySelector('.settings.debug')).toBeNull();
  });

  it('shows the debug panel when settings.ini asks for it', async () => {
    await runningWithDebug(true);

    const panel = element.querySelector('.settings.debug');
    expect(panel).toBeTruthy();
    expect(button('Skip this step')).toBeTruthy();
    expect(button('Show a made-up report')).toBeTruthy();
  });

  it('asks the helper to skip the current step', async () => {
    await runningWithDebug(true);

    button('Skip this step')!.click();
    await fixture.whenStable();

    expect(jobs.skipped).toEqual(['job-1']);
    expect(element.querySelector('.log')?.textContent).toContain('skipping the rest');
  });

  it('says so when a skip is refused rather than pretending it worked', async () => {
    jobs.skipFails = true;
    await runningWithDebug(true);

    button('Skip this step')!.click();
    await fixture.whenStable();

    expect(element.querySelector('.log')?.textContent).toContain('could not skip');
  });

  it('fills both report lists with one of every kind, and says they are made up', async () => {
    await runningWithDebug(true);

    button('Show a made-up report')!.click();
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('a series, not a single work');
    expect(said).toContain('an external work');
    expect(said).toContain('the work has been deleted');
    expect(said).toContain('unrevealed collection');
    expect(said).toContain('made private, or hidden');
    // and the failures list, which is the other half of the report
    expect(element.querySelector('.failures:not(.skipped)')?.textContent).toContain(
      'timed out',
    );
  });

  it('sends nothing to the helper for a made-up report', async () => {
    // it is a picture of the layout, not a result - no run is affected
    await runningWithDebug(true);

    button('Show a made-up report')!.click();
    await fixture.whenStable();

    expect(jobs.skipped).toEqual([]);
    expect(jobs.cancelled).toEqual([]);
  });

  // endregion

  // region a login that lapses mid-run

  it('explains an expired login rather than showing a bare error', async () => {
    await open('sync');
    await advanceTo('running');

    jobs.push!({ type: 'failed', error: 'AO3 has stopped recognising your login',
                 sessionExpired: true });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('login expired while this was running');
    expect(said).toContain('Nothing was lost');
    // and says what to do, because re-running really does continue from what is missing
    expect(said).toContain('carries on from what is still missing');
  });

  it('shows an ordinary failure as itself', async () => {
    await open('sync');
    await advanceTo('running');

    jobs.push!({ type: 'failed', error: 'something else went wrong' });
    await fixture.whenStable();

    const said = element.querySelector('.body')?.textContent ?? '';
    expect(said).toContain('something else went wrong');
    expect(said).not.toContain('login expired');
  });

  // endregion

  // region the checklist of steps

  async function runningWithSteps(steps: { id: string; label: string }[]) {
    await open('sync');
    await advanceTo('running');
    jobs.push!({ type: 'steps', steps });
    await fixture.whenStable();
  }

  function stepRows() {
    return Array.from(element.querySelectorAll('.step-list li')).map((li) => ({
      label: li.querySelector('.step-label')?.textContent?.trim(),
      state: li.querySelector('.step-state')?.textContent?.trim(),
      status: li.className,
    }));
  }

  it('shows what the run intends to do before it has done any of it', async () => {
    // the point of the panel: what is still to come, not only what has happened
    await runningWithSteps([
      { id: 'login', label: 'Log in to AO3' },
      { id: 'index', label: 'Index bookmarks added since last time' },
    ]);

    expect(stepRows().map((r) => r.label)).toEqual([
      'Log in to AO3',
      'Index bookmarks added since last time',
    ]);
    expect(stepRows().every((r) => r.state === 'waiting')).toBe(true);
  });

  it('moves a step to in progress and then to done', async () => {
    await runningWithSteps([{ id: 'index', label: 'Index' }]);

    jobs.push!({ type: 'step', id: 'index', status: 'running' });
    await fixture.whenStable();
    expect(stepRows()[0].state).toBe('in progress');
    expect(stepRows()[0].status).toContain('step-running');

    jobs.push!({ type: 'step', id: 'index', status: 'done' });
    await fixture.whenStable();
    expect(stepRows()[0].state).toBe('done');
  });

  it('does not make a skipped step look like a failed one', async () => {
    // a run with no unfinished fics skips that step and nothing has gone wrong
    await runningWithSteps([
      { id: 'update', label: 'Update' },
      { id: 'gaps', label: 'Gaps' },
    ]);

    jobs.push!({ type: 'step', id: 'update', status: 'skipped' });
    jobs.push!({ type: 'step', id: 'gaps', status: 'failed' });
    await fixture.whenStable();

    expect(stepRows()[0].state).toBe('skipped');
    expect(stepRows()[0].status).not.toContain('step-failed');
    expect(stepRows()[0].status).toContain('step-skipped');
    expect(stepRows()[1].state).toBe('failed');

    // tagged on the line itself, so it reads as skipped without reading the column
    expect(stepRows()[0].label).toContain('[SKIP]');
    expect(stepRows()[1].label).not.toContain('[SKIP]');
  });

  it('counts how far through the run is', async () => {
    await runningWithSteps([
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
      { id: 'c', label: 'C' },
    ]);

    jobs.push!({ type: 'step', id: 'a', status: 'done' });
    jobs.push!({ type: 'step', id: 'b', status: 'skipped' });
    await fixture.whenStable();

    // a skipped step is behind the run just as much as a finished one
    expect(element.querySelector('.step-count')?.textContent).toContain('2 of 3');
  });

  it('leaves the other steps alone when one changes', async () => {
    await runningWithSteps([
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
    ]);

    jobs.push!({ type: 'step', id: 'b', status: 'running' });
    await fixture.whenStable();

    expect(stepRows()[0].state).toBe('waiting');
    expect(stepRows()[1].state).toBe('in progress');
  });

  it('shows no panel at all before a run has published a plan', async () => {
    await open('sync');
    await advanceTo('running');

    expect(element.querySelector('.run-steps')).toBeNull();
  });

  it('does not carry a checklist over into the next run', async () => {
    await runningWithSteps([{ id: 'a', label: 'A' }]);

    await open('sync');
    await advanceTo('running');

    expect(element.querySelector('.run-steps')).toBeNull();
  });

  // endregion

  // region bookmarks that were never works

  async function finishedWithSkipped(rows: unknown[]) {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'skipped', skipped: rows as never });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();
  }

  it('names each bookmark it could not download, and why', async () => {
    await finishedWithSkipped([
      { id: '12345', link: 'https://ao3/series/12345', title: 'A Series',
        error: 'a series, not a single work' },
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
    ]);

    const said = element.querySelector('.failures.skipped')?.textContent ?? '';
    expect(said).toContain('2');
    expect(said).toContain('a series, not a single work');
    expect(said).toContain('the work has been deleted');
  });

  it('still identifies a skipped bookmark that has no link at all', async () => {
    // a deleted work has no number and no link, so the title is all there is to show
    await finishedWithSkipped([
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
    ]);

    expect(element.querySelector('.failures.skipped')?.textContent).toContain('Gone');
  });

  it('does not call a skipped bookmark a failure', async () => {
    // nothing went wrong: there was no work there to fetch
    await finishedWithSkipped([
      { id: '1', link: 'https://ao3/series/1', title: 'S', error: 'a series' },
    ]);

    const said = element.querySelector('.failures.skipped')?.textContent ?? '';
    expect(said).toContain('Nothing has gone wrong');
    // and the red failures panel is not showing, because there were none
    expect(element.querySelector('.failures:not(.skipped)')).toBeNull();
  });

  it('offers the skipped list as a file, with a reason on every row', async () => {
    await finishedWithSkipped([
      { id: '12345', link: 'https://ao3/series/12345', title: 'S',
        error: 'a series, not a single work' },
      { id: null, link: '', title: 'Gone', error: 'the work has been deleted' },
    ]);

    const exportButtons = Array.from(element.querySelectorAll('button')).filter(
      (b) => b.textContent?.trim() === 'Export all issues',
    );
    expect(exportButtons).toHaveLength(1);

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();
    expect(report).toContain('## 2 bookmarks that are not works');
    expect(report).toContain('12345\thttps://ao3/series/12345\ta series, not a single work');
    expect(report).toContain('\t\tthe work has been deleted');
  });

  it('lists old copies that could not be deleted, and puts every issue in one file', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'skipped',
      skipped: [{ id: '1', link: 'a', title: 'S', error: 'a series' }] as never,
    });
    jobs.push!({ type: 'failures', failures: [{ id: '2', link: 'b', error: 'timed out' }] });
    jobs.push!({
      type: 'keptCopies',
      keptCopies: [{ id: '3', link: 'c', file: '3 New 2026-09-14.html',
                     old: '3 New 2026-01-01.html', error: 'locked' }],
    });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    const kept = element.querySelector('.failures.kept')?.textContent ?? '';
    expect(kept).toContain('checking by hand');
    expect(kept).toContain('3 New 2026-09-14.html');

    const exportButtons = Array.from(element.querySelectorAll('button')).filter(
      (b) => b.textContent?.trim() === 'Export all issues',
    );
    expect(exportButtons).toHaveLength(1);

    const report = (fixture.componentInstance as unknown as {
      issuesReport(): string;
    }).issuesReport();
    const headings = report.split('\n').filter((x) => x.startsWith('## '));
    expect(headings).toEqual([
      '## 1 work that could not be downloaded',
      '## 1 new copy downloaded that needs checking by hand',
      '## 1 bookmark that is not a work',
    ]);
    // the ids sit under their own heading
    const lines = report.split('\n');
    expect(lines[lines.indexOf(headings[1]) + 2]).toBe(
      '3\tc\t3 New 2026-09-14.html\t3 New 2026-01-01.html\tlocked');
  });

  it('keeps the two lists apart when a run has both', async () => {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({
      type: 'skipped',
      skipped: [{ id: '1', link: 'a', title: 'S', error: 'a series' }] as never,
    });
    jobs.push!({ type: 'failures', failures: [{ id: '2', link: 'b', error: 'timed out' }] });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    expect(element.querySelector('.failures.skipped')).toBeTruthy();
    expect(element.querySelector('.failures:not(.skipped)')).toBeTruthy();
  });

  it('does not carry a skipped list into the next run', async () => {
    await finishedWithSkipped([{ id: '1', link: 'a', title: 'S', error: 'a series' }]);

    await open('bookmarks');
    await advanceTo('running');

    expect(element.querySelector('.failures.skipped')).toBeNull();
  });

  // endregion

  // region pausing a run

  async function running() {
    await open('bookmarks');
    await advanceTo('running');
    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
  }

  async function press(text: string) {
    button(text)!.click();
    await fixture.whenStable();
  }

  it('offers pausing alongside stopping while a run is going', async () => {
    await running();

    expect(button('Pause')).toBeTruthy();
    expect(button('Stop')).toBeTruthy();
  });

  it('does not say it is paused until the run says it has stopped', async () => {
    // the helper only sets a flag; the run acts on it at its next safe point, which can be
    // a whole file later. saying 'Paused' on the button press would claim it had stopped
    // while it was still downloading
    await running();

    await press('Pause');

    expect(jobs.pauses).toEqual([{ jobId: 'job-1', paused: true }]);
    expect(button('Pausing...')).toBeTruthy();
    expect(element.querySelector('.warning.held')).toBeNull();

    jobs.push!({ type: 'held' });
    await fixture.whenStable();

    expect(button('Resume')).toBeTruthy();
    expect(element.querySelector('.warning.held')?.textContent).toContain('Paused');
  });

  it('lets a paused run go again', async () => {
    await running();
    await press('Pause');
    jobs.push!({ type: 'held' });
    await fixture.whenStable();

    await press('Resume');
    expect(jobs.pauses.at(-1)).toEqual({ jobId: 'job-1', paused: false });

    jobs.push!({ type: 'released' });
    await fixture.whenStable();

    expect(button('Pause')).toBeTruthy();
    expect(element.querySelector('.warning.held')).toBeNull();
  });

  it('can still be stopped while it is paused', async () => {
    // a pause must never be able to trap a run, so stopping is never blocked behind it
    await running();
    await press('Pause');
    jobs.push!({ type: 'held' });
    await fixture.whenStable();

    expect(button('Stop')?.disabled).toBe(false);
    await press('Stop');

    expect(jobs.cancelled).toEqual(['job-1']);
  });

  it('does not claim a pause that the helper refused', async () => {
    // saying 'Paused' over a run that is still downloading is the worst of both
    jobs.pauseFails = 'could not pause the run';
    await running();

    await press('Pause');

    expect(button('Pause')).toBeTruthy();
    expect(element.querySelector('.warning.held')).toBeNull();
    expect(element.querySelector('.log')?.textContent).toContain('could not pause');
  });

  it('passes on why the pause was refused rather than a generic line', async () => {
    // a pause refused because the helper is older than the page is fixed by restarting the
    // app, and a flat 'could not pause' gives nobody a way to work that out
    jobs.pauseFails =
      'could not pause the run - the helper may be an older version that does not ' +
      'support pausing. Restart the app to update it.';
    await running();

    await press('Pause');

    expect(element.querySelector('.log')?.textContent).toContain('Restart the app');
  });

  it('offers no pause while the run is stopped waiting on a question', async () => {
    // it is already stopped dead waiting for the answer; a pause there would claim to do
    // something it cannot
    await running();
    jobs.push!({ type: 'question', name: 'undated', count: 2 });
    await fixture.whenStable();

    expect(button('Pause')).toBeUndefined();
    expect(button('Stop')).toBeTruthy();
  });

  it('does not carry a pause over into the next run', async () => {
    await running();
    await press('Pause');
    jobs.push!({ type: 'held' });
    jobs.push!({ type: 'finished' });
    await fixture.whenStable();

    expect(element.querySelector('.warning.held')).toBeNull();
  });

  // endregion

  it('names the stages an update run goes through', async () => {
    // an update run has no separate download stage: it re-reads and fetches one fic at a
    // time, so the last stage it reports covers both
    await toAcknowledgement();
    acknowledgeBox()!.click();
    await fixture.whenStable();
    button('Continue')!.click();
    await fixture.whenStable();

    const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
    password.value = 'a-password';
    password.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    button('Start download')!.click();
    await fixture.whenStable();

    jobs.push!({ type: 'phase', name: 'scanning' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain('Reading your index');

    jobs.push!({ type: 'phase', name: 'checking_files' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain(
      'already downloaded',
    );

    jobs.push!({ type: 'phase', name: 'updating' });
    await fixture.whenStable();
    expect(element.querySelector('.phase')?.textContent).toContain(
      'Re-reading each unfinished fic',
    );
  });

  it('restarts the bar when the stage changes', async () => {
    // each stage has its own scale, so carrying a percentage across would be a lie
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 20, total: 20 });
    await fixture.whenStable();
    expect(element.querySelector('.percent')?.textContent).toContain('100');

    jobs.push!({ type: 'phase', name: 'downloading' });
    await fixture.whenStable();
    expect(element.querySelector('.percent')).toBeNull();
  });

  it('tracks progress from page events', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 20, total: 80, works: 400 });
    await fixture.whenStable();

    expect(element.querySelector('.percent')?.textContent).toContain('25');
  });

  // the fetch is the slow part of indexing, so naming the page that just finished names
  // the wrong page for as long as the next one takes to arrive
  it('names the page being fetched, not the last one that finished', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({
      type: 'page',
      page: 3,
      total: 80,
      listingPage: 3,
      listingTotal: 80,
      works: 57,
    });
    await fixture.whenStable();
    expect(element.querySelector('.status')?.textContent).toContain('page 3 of 80');

    jobs.push!({
      type: 'page',
      page: 4,
      total: 80,
      listingPage: 4,
      listingTotal: 80,
      fetching: true,
    });
    await fixture.whenStable();

    expect(element.querySelector('.status')?.textContent).toContain('fetching page 4 of 80');
  });

  it('does not count a page as done while it is still being fetched', async () => {
    // the caption names what is in flight; the bar still measures what has arrived
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 21, total: 80, fetching: true });
    await fixture.whenStable();

    expect(element.querySelector('.percent')?.textContent).toContain('25');
  });

  // a walk stopped by a date floor, or by the first fic already indexed, cannot know how
  // many pages it will read - so a finished page has no 'of', and certainly not 'of ?'
  it('gives no total for a page on a walk that can stop anywhere', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 3, listingPage: 3, works: 57 });
    await fixture.whenStable();

    const said = element.querySelector('.status')?.textContent ?? '';
    expect(said).toContain('page 3 - 57 works so far');
    expect(said).not.toContain(' of ');
  });

  it('names the first page before anything knows how many there are', async () => {
    // the total comes off the page itself, so the first fetch has no total to report
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'page', page: 1, listingPage: 1, fetching: true });
    await fixture.whenStable();

    const said = element.querySelector('.status')?.textContent ?? '';
    expect(said).toContain('fetching page 1');
    expect(said).not.toContain('of ?');
  });

  it('warns when ao3 asks the run to slow down', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'paused', seconds: 300, until: '12:05:00' });
    await fixture.whenStable();

    const pause = element.querySelector('.pause')?.textContent ?? '';
    expect(pause).toContain('300');
    expect(pause).toContain('12:05:00');

    jobs.push!({ type: 'resumed' });
    await fixture.whenStable();
    expect(element.querySelector('.pause')).toBeNull();
  });

  // endregion

  // region stopping

  it('offers a stop button while the run is working', async () => {
    await open('bookmarks');
    await advanceTo('running');

    expect(button('Stop')).toBeTruthy();
  });

  it('asks the helper to stop when it is pressed', async () => {
    await open('bookmarks');
    await advanceTo('running');

    button('Stop')!.click();
    await fixture.whenStable();

    expect(jobs.cancelled).toEqual(['job-1']);
    // and does not let it be pressed twice
    expect(button('Stopping...')?.disabled).toBe(true);
  });

  it('reports a stop as kept work rather than a failure', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'finished', cancelled: true });
    await fixture.whenStable();

    expect(element.querySelector('.error')).toBeNull();
    const warning = element.querySelector('.warning')?.textContent ?? '';
    expect(warning).toContain('Stopped');
    expect(warning).toContain('kept');
  });

  it('offers a way out of the modal once the stop has taken effect', async () => {
    await open('bookmarks');
    await advanceTo('running');

    button('Stop')!.click();
    await fixture.whenStable();
    jobs.push!({ type: 'finished', cancelled: true });
    await fixture.whenStable();

    expect(button('Stopping...')).toBeUndefined();
    expect(button('Close modal')).toBeTruthy();
  });

  it('reports a clean finish as success', async () => {
    await open('bookmarks');
    await advanceTo('running');

    jobs.push!({ type: 'finished', cancelled: false });
    await fixture.whenStable();

    expect(element.querySelector('.success')?.textContent).toContain('Finished');
  });

  // endregion
});
