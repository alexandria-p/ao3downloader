import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DownloadDialog } from './download-dialog';
import { DropboxSession } from './dropbox';
import { Library } from './library';
import { DropboxLibraryStore, LibraryStore } from './library-store';
import {
  ActiveRun,
  JobAction,
  JobEvent,
  Jobs,
  RunInProgressError,
  ServerConfig,
  StartRequest,
} from './jobs';

const CONFIG: ServerConfig = {
  username: 'Someone',
  filetypes: ['EPUB', 'PDF', 'HTML', 'JSON'],
  forced: ['JSON'],
  defaults: ['JSON', 'HTML'],
  settings: {
    file: 'settings.ini',
    extraWaitTime: 15,
    fileNamePattern: '{worknum} {title} - {author} {date updated}',
    fileNameLength: 50,
    fileNameExample: '1 A - B 2026-01-01.html',
    maxRetries: 0,
    maxTimeouts: 3,
    debugLogging: false,
  },
};

const HANDOVER = { refreshToken: 'refresh-me', appKey: 'app-key' };

class FakeJobs extends Jobs {
  started: StartRequest[] = [];
  cancelled: string[] = [];
  streamed: string[] = [];
  push: ((event: JobEvent) => void) | null = null;
  closedStream = false;
  refuseWith: Error | null = null;

  override async loadConfig(): Promise<ServerConfig | null> {
    this.config.set(CONFIG);
    this.available.set(true);
    return CONFIG;
  }

  override async refreshActiveRuns(): Promise<ActiveRun[] | null> {
    return this.activeRuns();
  }

  override async start(request: StartRequest): Promise<string> {
    if (this.refuseWith) throw this.refuseWith;
    this.started.push(request);
    return 'job-1';
  }

  override async cancel(jobId: string): Promise<void> {
    this.cancelled.push(jobId);
  }

  override stream(id: string, onEvent: (e: JobEvent) => void): () => void {
    this.streamed.push(id);
    this.push = onEvent;
    return () => {
      this.closedStream = true;
    };
  }
}

/** a folder on this computer, as far as the dialog can tell */
function localFolder(): LibraryStore {
  const nothing = async () => {
    throw new Error('not used here');
  };
  return {
    label: 'My Fics', check: async () => {}, list: nothing, read: nothing, write: nothing,
    size: nothing, delete: nothing, rename: nothing, mkdir: nothing,
  };
}

let jobs: FakeJobs;
let fixture: ComponentFixture<DownloadDialog>;
let element: HTMLElement;

/** a library open in Dropbox, and signed in */
function inDropbox(): void {
  const session = TestBed.inject(DropboxSession);
  session.status.set('signed-in');
  vi.spyOn(session, 'handover').mockReturnValue(HANDOVER);
  TestBed.inject(Library).store.set(new DropboxLibraryStore(session));
}

async function open(action: JobAction = 'bookmarks', attachTo: ActiveRun | null = null) {
  fixture = TestBed.createComponent(DownloadDialog);
  fixture.componentRef.setInput('action', action);
  fixture.componentRef.setInput('attachTo', attachTo);
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

/** walk to the login step, by where the dialog is rather than by counting clicks */
async function toCredentials(): Promise<void> {
  for (let guard = 0; guard < 8 && currentStep() !== 'credentials'; guard++) {
    if (currentStep() === 'acknowledge') {
      element.querySelector<HTMLInputElement>('input[name="acknowledge"]')!.click();
      await fixture.whenStable();
    }
    if (currentStep() === 'link') {
      const field = element.querySelector<HTMLInputElement>('input[name="work"], input[name="collection"]')!;
      field.value = field.name === 'work'
        ? 'https://archiveofourown.org/works/34816549'
        : 'https://archiveofourown.org/collections/yuletide2024';
      field.dispatchEvent(new Event('input'));
      await fixture.whenStable();
    }
    button('Continue')?.click();
    await fixture.whenStable();
  }
}

async function tickBackground(): Promise<void> {
  checkbox('Run as background task')!.click();
  await fixture.whenStable();
}

function questionsOffered(): string[] {
  return Array.from(element.querySelectorAll('[data-question]')).map(
    (x) => x.getAttribute('data-question') ?? '',
  );
}

async function startIt(label = 'Start in the background'): Promise<void> {
  const password = element.querySelector<HTMLInputElement>('input[name="password"]')!;
  password.value = 'a-password';
  password.dispatchEvent(new Event('input'));
  await fixture.whenStable();
  button(label)!.click();
  await fixture.whenStable();
}

describe('Running in the background', () => {
  beforeEach(() => {
    jobs = new FakeJobs();
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  // region the choice

  it('is not offered for a folder on this computer, and says why', async () => {
    // the helper reaches a local folder only through the page, so the page has to stay
    TestBed.inject(Library).store.set(localFolder());
    await open();
    await toCredentials();

    const box = checkbox('Run as background task')!;
    expect(box.disabled).toBe(true);
    expect(element.querySelector('.background-choice')?.textContent).toContain(
      'Only for a library in Dropbox',
    );
  });

  it('is not offered in Dropbox until the page is signed in', async () => {
    const session = TestBed.inject(DropboxSession);
    TestBed.inject(Library).store.set(new DropboxLibraryStore(session));
    session.status.set('signed-out');
    await open();
    await toCredentials();

    expect(checkbox('Run as background task')!.disabled).toBe(true);
    expect(element.querySelector('.background-choice')?.textContent).toContain('Sign in to Dropbox');
  });

  it('is offered for a library in Dropbox, with the warnings up front', async () => {
    inDropbox();
    await open();
    await toCredentials();

    expect(checkbox('Run as background task')!.disabled).toBe(false);
    await tickBackground();

    const said = element.querySelector('.background-warning')?.textContent ?? '';
    expect(said).toContain('No other run can start until it has finished');
    expect(said).toContain('Restarting the helper ends the run');
    expect(button('Start in the background')).toBeTruthy();
  });

  // endregion

  // region asked up front

  it('asks a full scan what to do about undated files and older copies', async () => {
    inDropbox();
    await open('bookmarks');
    await toCredentials();
    await tickBackground();

    expect(questionsOffered()).toEqual(['undated', 'duplicates']);
  });

  it('also asks a quick scan how far back to go with nothing to measure to', async () => {
    inDropbox();
    await open('quick');
    await toCredentials();
    await tickBackground();

    expect(questionsOffered()).toEqual(['quick-floor', 'undated', 'duplicates']);
  });

  it('does not ask about undated files on a run that fetches every copy again anyway', async () => {
    inDropbox();
    await open('work');
    await toCredentials();
    await tickBackground();

    expect(questionsOffered()).toEqual(['duplicates']);
  });

  it('asks nothing of a run that downloads no works', async () => {
    inDropbox();
    await open('collections');
    await toCredentials();
    await tickBackground();

    expect(questionsOffered()).toEqual([]);
  });

  it('starts with the answers that change nothing', async () => {
    inDropbox();
    await open('quick');
    await toCredentials();
    await tickBackground();
    await startIt();

    expect(jobs.started[0].answers).toEqual({
      'quick-floor': { choice: 'full' },
      undated: { choice: 'skip' },
      duplicates: { choice: 'leave' },
    });
  });

  it('sends the answers given, and the date undated files are to be given', async () => {
    inDropbox();
    await open('bookmarks');
    await toCredentials();
    await tickBackground();
    checkbox('Give them a date')!.click();
    await fixture.whenStable();
    const date = element.querySelector<HTMLInputElement>('input[name="bg-undated-date"]')!;
    date.value = '2024-05-06';
    date.dispatchEvent(new Event('input'));
    checkbox('Keep the newest')!.click();
    await fixture.whenStable();
    await startIt();

    expect(jobs.started[0].answers).toEqual({
      undated: { choice: 'stamp', date: '2024-05-06' },
      duplicates: { choice: 'newest' },
    });
  });

  it('will not start with a date that is not one', async () => {
    inDropbox();
    await open('bookmarks');
    await toCredentials();
    await tickBackground();
    checkbox('Give them a date')!.click();
    await fixture.whenStable();
    const date = element.querySelector<HTMLInputElement>('input[name="bg-undated-date"]')!;
    date.value = '';
    date.dispatchEvent(new Event('input'));
    await fixture.whenStable();

    expect(button('Start in the background')!.disabled).toBe(true);
  });

  // endregion

  // region starting and leaving it

  it('hands the helper the Dropbox sign-in, and says it is a background run', async () => {
    inDropbox();
    await open();
    await toCredentials();
    await tickBackground();
    await startIt();

    expect(jobs.started[0].background).toBe(true);
    expect(jobs.started[0].dropbox).toEqual(HANDOVER);
  });

  it('sends nothing about the background on an ordinary run in Dropbox', async () => {
    inDropbox();
    await open();
    await toCredentials();
    await startIt('Start download');

    expect(Object.keys(jobs.started[0])).not.toContain('background');
    expect(JSON.stringify(jobs.started[0])).not.toContain('refresh-me');
  });

  it('can be left to carry on, without stopping it', async () => {
    inDropbox();
    await open();
    await toCredentials();
    await tickBackground();
    await startIt();
    const closed = vi.fn();
    fixture.componentInstance.closed.subscribe(closed);

    expect(element.textContent).toContain('This run is going in the background');
    button('Continue in background')!.click();

    expect(closed).toHaveBeenCalledOnce();
    expect(jobs.cancelled).toEqual([]);
    expect(jobs.closedStream).toBe(true);
  });

  it('does not ask to be kept open, since it does not need the page', async () => {
    const guard = vi.spyOn(window, 'addEventListener');
    inDropbox();
    await open();
    await toCredentials();
    await tickBackground();
    await startIt();

    expect(guard.mock.calls.map((x) => x[0])).not.toContain('beforeunload');
  });

  it('offers no way to leave an ordinary run that needs the page', async () => {
    inDropbox();
    await open();
    await toCredentials();
    await startIt('Start download');

    expect(button('Continue in background')).toBeUndefined();
    expect(element.querySelector('[aria-label="Close"]')).toBeNull();
  });

  it('says so when another run is already going, rather than starting a second', async () => {
    jobs.refuseWith = new RunInProgressError('A run is already in progress.', 'job-0');
    inDropbox();
    await open();
    await toCredentials();
    await tickBackground();
    await startIt();

    expect(currentStep()).toBe('failed');
    expect(element.textContent).toContain('A run is already in progress');
  });

  // endregion

  // region coming back to it

  it('opens straight onto a run already going, and follows it', async () => {
    const run: ActiveRun = {
      id: 'job-7', action: 'quick', actionName: 'Quick Scan', background: true,
      started: '2026-09-28T10:00:00', paused: false, step: 'Index bookmarks',
    };
    await open('quick', run);

    expect(currentStep()).toBe('running');
    expect(jobs.streamed).toEqual(['job-7']);
    expect(jobs.started).toEqual([]);

    // what the run said before the page came back is replayed through the same stream
    jobs.push!({ type: 'started', filetypes: ['JSON', 'EPUB'] });
    jobs.push!({ type: 'steps', steps: [{ id: 'login', label: 'Log in to AO3' }] });
    jobs.push!({ type: 'step', id: 'login', status: 'done' });
    jobs.push!({ type: 'message', text: 'new download: 1 A.html' });
    await fixture.whenStable();

    expect(element.textContent).toContain('Log in to AO3');
    // what it is saving is what the run said, not what this window happens to have ticked
    expect(element.querySelector('.chosen')?.textContent).toContain('JSON, EPUB');
    expect(element.textContent).toContain('new download: 1 A.html');
    expect(button('Continue in background')).toBeTruthy();
    expect(button('Pause')).toBeTruthy();
  });

  it('shows a paused run as paused when it comes back to it', async () => {
    await open('quick', {
      id: 'job-7', action: 'quick', actionName: 'Quick Scan', background: true,
      started: '2026-09-28T10:00:00', paused: true, step: '',
    });

    expect(button('Resume')).toBeTruthy();
  });

  // endregion
});
