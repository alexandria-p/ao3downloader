import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DownloadDialog } from './download-dialog';
import { JobAction, JobEvent, Jobs, ServerConfig, StartRequest } from './jobs';

const CONFIG: ServerConfig = {
  downloadFolder: 'my_downloads',
  username: 'Someone',
  filetypes: ['AZW3', 'EPUB', 'MOBI', 'PDF', 'HTML', 'JSON'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
  settings: {
    file: 'C:\\app\\config\\settings.ini',
    downloadFolder: 'C:\\app\\my_downloads',
    extraWaitTime: 15,
    fileNamePattern: '{worknum} {title} - {author}',
    fileNameLength: 50,
    maxRetries: 0,
    maxTimeouts: 3,
    debugLogging: false,
  },
};

class FakeJobs extends Jobs {
  started: StartRequest[] = [];
  cancelled: string[] = [];
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

  override async cancel(jobId: string): Promise<void> {
    this.cancelled.push(jobId);
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

async function advanceTo(step: 'options' | 'credentials' | 'running') {
  button('Continue')?.click();
  await fixture.whenStable();
  if (step === 'options') return;

  button('Continue')?.click();
  await fixture.whenStable();
  if (step === 'credentials') return;

  const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
  password.value = 'a-password';
  password.dispatchEvent(new Event('input'));
  await fixture.whenStable();

  button('Start download')?.click();
  await fixture.whenStable();
}

describe('DownloadDialog', () => {
  beforeEach(async () => {
    jobs = new FakeJobs();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  // region file types

  it('locks the file types that are always produced', async () => {
    await open();

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

    const html = checkbox('HTML')!;
    expect(html.checked).toBe(true);
    expect(html.disabled).toBe(false);
  });

  it('asks for metadata only when everything else is unticked', async () => {
    await open('bookmarks');
    checkbox('HTML')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].filetypes).toEqual(['JSON']);
  });

  it('says what unticking the rest buys, where the choice is made', async () => {
    await open('bookmarks');

    expect(element.textContent).toContain('rate limit');
  });

  // endregion

  // region options step

  it('asks the listing questions the console asks, for a bookmarks run', async () => {
    await open('bookmarks');
    await advanceTo('options');

    expect(element.querySelector('input[name="pages"]')).toBeTruthy();
    expect(checkbox('series links')).toBeTruthy();
    expect(checkbox('embedded images')).toBeTruthy();
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
    await advanceTo('options');

    // no listing to page through, no series to expand, no metadata to date
    expect(element.querySelector('input[name="pages"]')).toBeNull();
    expect(checkbox('series links')).toBeUndefined();
    expect(checkbox('publication date')).toBeUndefined();
    // images still apply to a re-download
    expect(checkbox('embedded images')).toBeTruthy();
  });

  it('sends the chosen options with the job', async () => {
    await open('bookmarks');
    await advanceTo('options');

    const pages = element.querySelector<HTMLInputElement>('input[name="pages"]')!;
    pages.value = '3';
    pages.dispatchEvent(new Event('input'));
    checkbox('series links')!.click();
    checkbox('embedded images')!.click();
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started).toHaveLength(1);
    expect(jobs.started[0].options).toEqual({
      start: 1,
      pages: 3,
      series: true,
      images: true,
      workdates: false,
    });
  });

  it('sends the page to start on as well as the one to stop after', async () => {
    await open('bookmarks');
    await advanceTo('options');

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

  it('treats a blank or first page as starting at the beginning', async () => {
    await open('bookmarks');
    await advanceTo('options');

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '';
    start.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    await advanceTo('running');

    expect(jobs.started[0].options.start).toBe(1);
  });

  it('says which slice of the listing the run will cover', async () => {
    await open('bookmarks');
    await advanceTo('options');

    const start = element.querySelector<HTMLInputElement>('input[name="start"]')!;
    start.value = '5';
    start.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(element.textContent).toContain('page 5 onwards');
  });

  it('treats a blank or zero page limit as every page', async () => {
    await open('bookmarks');
    await advanceTo('options');

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
    await open('bookmarks');
    await advanceTo('running');

    const chosen = element.querySelector('.chosen')?.textContent ?? '';
    expect(chosen).toContain('JSON');
    expect(chosen).toContain('HTML');
    expect(chosen).toContain('all pages');
    expect(chosen).toContain('my_downloads');
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
