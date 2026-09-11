import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DownloadDialog } from './download-dialog';
import {
  JobAction,
  JobEvent,
  Jobs,
  ServerConfig,
  StartRequest,
  UndatedChoice,
} from './jobs';

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
    fileNamePattern: '{worknum} {title} - {author} {date updated}',
    fileNameLength: 50,
    fileNameExample: '34816549 No Paths Are Bound - Cataclys 2026-08-23.html',
    maxRetries: 0,
    maxTimeouts: 3,
    debugLogging: false,
  },
};

class FakeJobs extends Jobs {
  started: StartRequest[] = [];
  cancelled: string[] = [];
  answers: { jobId: string; choice: UndatedChoice; date: string }[] = [];
  pauses: { jobId: string; paused: boolean }[] = [];
  /** set by a test that needs answering to fail, leaving the run still waiting */
  answerFails: string | null = null;
  /** set by a test that needs pausing to fail, so the run carries on regardless */
  pauseFails: string | null = null;
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

  override async answer(jobId: string, choice: UndatedChoice, date = ''): Promise<void> {
    if (this.answerFails) throw new Error(this.answerFails);
    this.answers.push({ jobId, choice, date });
  }

  override async setPaused(jobId: string, paused: boolean): Promise<void> {
    if (this.pauseFails) throw new Error(this.pauseFails);
    this.pauses.push({ jobId, paused });
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
    expect(said).toContain('Download newly added bookmarks');
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

  it('offers to export the list', async () => {
    await finishWithFailures();

    expect(button('Export the list')).toBeTruthy();
  });

  it('exports the work numbers, links and reasons', async () => {
    await finishWithFailures();

    const report = (fixture.componentInstance as unknown as {
      failureReport(): string;
    }).failureReport();

    const lines = report.trim().split('\n');
    expect(lines[0]).toContain('2 works');
    expect(lines.at(-2)).toBe('111\thttps://archiveofourown.org/works/111\tdeleted');
    expect(lines.at(-1)).toBe('222\thttps://archiveofourown.org/works/222\tlocked');
  });

  it('keeps an error that spans lines on one line of the export', async () => {
    // one work per line is the point: it has to stay feedable back in
    await finishWithFailures([
      { id: '111', link: 'https://archiveofourown.org/works/111', error: 'went\n  wrong' },
    ]);

    const report = (fixture.componentInstance as unknown as {
      failureReport(): string;
    }).failureReport();

    expect(report.trim().split('\n')).toHaveLength(4);
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
