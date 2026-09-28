import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { History } from './history';
import { ActiveRun, Jobs, RunHistory } from './jobs';
import { Library } from './library';

function aRun(over: Partial<RunHistory> = {}): RunHistory {
  return {
    file: '2026-09-13T120000-abc.json',
    id: 'abc',
    action: 'sync',
    actionName: 'Download new bookmarks and update incomplete fics',
    started: '2026-09-13T12:00:00',
    finished: '2026-09-13T12:30:00',
    status: 'success',
    filetypes: ['JSON', 'HTML'],
    options: { pages: 0, start: 1, series: false, images: false, reindex: true },
    reindexed: [],
    downloaded: [],
    updated: [],
    choices: [],
    failures: [],
    skipped: [],
    error: '',
    ...over,
  };
}

class FakeJobs extends Jobs {
  runs: RunHistory[] | null = [];
  /** the runs the helper says it is not working on - marked interrupted when settled */
  settles = 0;

  override async loadRuns(): Promise<RunHistory[] | null> {
    return this.runs;
  }

  override async refreshActiveRuns(): Promise<ActiveRun[] | null> {
    return this.activeRuns();
  }

  /** set to stand for a helper that does not answer, which settles nothing */
  leaveRunning = false;

  override async settleInterrupted(): Promise<number> {
    this.settles++;
    if (this.leaveRunning) return 0;
    const running = (this.runs ?? []).filter((run) => run.status === 'running');
    for (const run of running) run.status = 'interrupted';
    return running.length;
  }
}

let jobs: FakeJobs;
let fixture: ComponentFixture<History>;
let element: HTMLElement;

async function show(runs: RunHistory[] | null) {
  jobs.runs = runs;
  fixture = TestBed.createComponent(History);
  element = fixture.nativeElement as HTMLElement;
  // the history is read in a few awaited steps; wait for all of them, not just the first
  for (let tries = 0; tries < 10; tries++) {
    await fixture.whenStable();
    if (!element.textContent?.includes('Reading past runs')) break;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

describe('History', () => {
  beforeEach(() => {
    jobs = new FakeJobs();
    TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
  });

  it('says so plainly when nothing has been recorded yet', async () => {
    await show([]);

    expect(element.textContent).toContain('No runs recorded yet');
    expect(element.querySelector('.run')).toBeNull();
  });

  it('tells no library open apart from an empty history', async () => {
    // the history is read out of the library, so without one there is nothing to read -
    // which is not the same as a library nothing has been run in yet
    await show(null);

    expect(element.textContent).toContain('Open a library');
    expect(element.textContent).not.toContain('No runs recorded yet');
  });

  it('names the button that was pressed and how the run ended', async () => {
    await show([aRun()]);

    expect(element.querySelector('.run-name')?.textContent).toContain(
      'Download new bookmarks and update incomplete fics',
    );
    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Finished');
    expect(element.querySelector('.run')?.className).toContain('run-success');
  });

  it('calls a run that never reported finishing interrupted', async () => {
    // the record is written when a run starts, so no ending is the evidence - once the
    // helper confirms it is not still working on it
    await show([aRun({ status: 'running', finished: null })]);
    await fixture.whenStable();
    fixture.detectChanges();

    expect(jobs.settles).toBe(1);
    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Interrupted');
    expect(element.textContent).toContain('never reported finishing');
  });

  it('does not ask the helper about runs when none is left running', async () => {
    await show([aRun()]);
    expect(jobs.settles).toBe(0);
  });

  it('offers to resume an unfinished scan, and says where it got to', async () => {
    const emitted: string[] = [];
    await show([aRun({ action: 'quick', status: 'stopped',
                       progress: { step: 'download', stepLabel: 'Download or update works' } })]);
    fixture.componentInstance.resume.subscribe((id) => emitted.push(id));

    expect(element.textContent).toContain('Got as far as: Download or update works');
    const button = element.querySelector<HTMLButtonElement>('.run-resume button')!;
    expect(button.disabled).toBe(false);
    button.click();
    expect(emitted).toEqual(['abc']);
  });

  it('explains why a custom run over a slice cannot be resumed', async () => {
    await show([aRun({ action: 'custom', status: 'failed', progress: {},
                       options: { pages: 5, start: 1 } })]);

    const button = element.querySelector<HTMLButtonElement>('.run-resume button')!;
    expect(button.disabled).toBe(true);
    expect(button.title).toContain('same page numbers no longer hold the same bookmarks');
  });

  it('offers nothing to resume for a finished run, or one that is not a scan', async () => {
    await show([aRun({ action: 'quick' }), aRun({ id: 'x', file: 'x.json', status: 'failed' })]);
    expect(element.querySelector('.run-resume')).toBeNull();
  });

  it('links a resumed run and the run it picked up, both ways', async () => {
    await show([
      aRun({ id: 'later', file: 'b.json', action: 'quick', started: '2026-09-14T09:00:00',
             resumes: 'abc', baseline: '2026-09-13T12:01:00' }),
      aRun({ action: 'quick', status: 'interrupted', resumedBy: 'later', progress: {} }),
    ]);

    const said = (element.textContent ?? '').replace(/\s+/g, ' ');
    expect(said).toContain('Picks up where the run from');
    expect(said).toContain('Resumed by the run from');
  });

  it('does not call a stopped run a failure', async () => {
    await show([aRun({ status: 'stopped' })]);

    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Stopped');
  });

  it('shows why a failed run failed', async () => {
    await show([aRun({ status: 'failed', error: 'invalid username or password' })]);

    expect(element.querySelector('.run-error')?.textContent).toContain('invalid username');
  });

  it('shows the file types and only the options that were actually set', async () => {
    await show([
      aRun({ options: { pages: 3, start: 5, series: true, images: false, reindex: false } }),
    ]);

    const said = element.querySelector('.run-settings')?.textContent ?? '';
    expect(said).toContain('JSON, HTML');
    expect(said).toContain('no reindexing');
    expect(said).toContain('up to page 3');
    expect(said).toContain('from page 5');
    expect(said).toContain('all works from encountered series');
    // an option left off is not listed at all
    expect(said).not.toContain('save images');
  });

  it('collapses the fic lists and says how many are in each', async () => {
    // a run that touched a thousand works would otherwise bury the next one
    await show([
      aRun({ reindexed: ['111', '222'], downloaded: ['111'], updated: ['333'] }),
    ]);

    const groups = Array.from(element.querySelectorAll('.ids')).map((d) => ({
      open: (d as HTMLDetailsElement).open,
      summary: d.querySelector('summary')?.textContent?.replace(/\s+/g, ' ').trim(),
    }));

    expect(groups.every((g) => !g.open)).toBe(true);
    expect(groups.map((g) => g.summary)).toEqual([
      'Re-indexed 2',
      'Downloaded 1',
      'Updated 1',
    ]);
  });

  it('links each work number to the work on AO3', async () => {
    await show([aRun({ downloaded: ['34816549'] })]);

    expect(element.querySelector('.id-list a')?.getAttribute('href')).toBe(
      'https://archiveofourown.org/works/34816549',
    );
  });

  it('leaves out a fic list that is empty', async () => {
    await show([aRun({ downloaded: ['111'] })]);

    const summaries = Array.from(element.querySelectorAll('.ids summary')).map((s) =>
      s.textContent?.trim().split(/\s+/)[0],
    );
    expect(summaries).toEqual(['Downloaded']);
  });

  it('keeps what could not be fetched apart from what was never a work', async () => {
    await show([
      aRun({
        failures: [{ id: '111', link: 'https://ao3/works/111', error: 'timed out' }],
        skipped: [{ id: null, link: '', title: 'Gone', error: 'the work has been deleted' }],
      }),
    ]);

    expect(element.querySelector('.ids.failed summary')?.textContent).toContain(
      'Could not be fetched',
    );
    expect(element.textContent).toContain('Not works');
    expect(element.textContent).toContain('the work has been deleted');
  });

  it('records what was decided about undated files', async () => {
    // so a library renamed months ago can be explained
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'undated', choice: 'stamp',
            date: '2024-06-01', count: 12 },
        ],
      }),
    ]);

    const said = element.querySelector('.run-choices')?.textContent ?? '';
    expect(said).toContain('12');
    expect(said).toContain('stamp');
    expect(said).toContain('2024-06-01');
  });

  it('names the undated works and every file given a date', async () => {
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'undated', choice: 'stamp',
            date: '2024-06-01', count: 1, files: 2, works: ['111'],
            renamed: [
              { id: '111', from: '111 A - B.html', to: '111 A - B 2024-06-01.html' },
              { id: '111', from: '111 A - B.pdf', to: '111 A - B 2024-06-01.pdf' },
            ] },
        ],
      }),
    ]);

    const said = element.querySelector('.run-choices')?.textContent ?? '';
    // works and files counted apart, so two formats of one work do not read as a miscount
    expect(said).toMatch(/1\s+undated\s+work\s*\(2 files\)/);
    expect(said).toContain('Works without a date');
    expect(element.querySelector('.run-choices a')?.getAttribute('href')).toContain('/works/111');
    expect(said).toContain('Files given a date');
    expect(said).toContain('111 A - B 2024-06-01.pdf');
  });

  it('lists the old copies that could not be deleted, with both file names', async () => {
    await show([
      aRun({
        keptCopies: [
          { id: '123', link: 'https://archiveofourown.org/works/123', error: 'locked',
            file: '123 A - B 2026-09-14.html', old: '123 A - B 2026-01-01.html' },
        ],
      }),
    ]);

    const said = element.querySelector('.run')?.textContent ?? '';
    expect(said).toContain('Downloaded, but needs checking by hand');
    expect(said).toContain('123 A - B 2026-09-14.html');
    expect(said).toContain('123 A - B 2026-01-01.html');
  });

  it('lists the older copies a run removed, and the ones it marked but left', async () => {
    await show([
      aRun({
        choices: [{ at: '2026-09-13T12:05:00', question: 'duplicates', choice: 'newest',
                    count: 2, files: 3 }],
        removals: [
          { id: '111', filetype: 'PDF', file: '111 A 2024-01-01.pdf',
            keeping: '111 A 2025-06-01.pdf', status: 'removed' },
          { id: '222', filetype: 'PDF', file: '222 B.pdf', keeping: '222 B 2025-06-01.pdf',
            status: 'kept', error: 'the file could not be deleted' },
          // a run that died before cleaning up never got to say so
          { id: '333', filetype: 'PDF', file: '333 C.pdf', keeping: '333 C 2025-06-01.pdf',
            status: 'pending' },
        ],
      }),
    ]);

    const said = element.querySelector('.run')?.textContent ?? '';
    expect(said).toContain('keep only the newest');
    expect(said).toContain('Older copies removed');
    expect(said).toContain('111 A 2024-01-01.pdf');
    expect(said).toContain('Marked for removal, still there');
    expect(said).toContain('the file could not be deleted');
    expect(said).toContain('the run ended before its cleanup step');
  });

  it('describes the quick scan question as what it was, not as undated files', async () => {
    await show([
      aRun({
        choices: [
          { at: '2026-09-13T12:05:00', question: 'quick-floor', choice: 'full', count: 40 },
        ],
      }),
    ]);

    const said = element.querySelector('.run-choices')?.textContent ?? '';
    expect(said).not.toContain('undated');
    expect(said).toContain('the whole listing');
  });

  it('lists every run it was given', async () => {
    await show([aRun({ file: 'a.json' }), aRun({ file: 'b.json' })]);

    expect(element.querySelectorAll('.run').length).toBe(2);
  });

  // region the run going now

  const going: ActiveRun = {
    id: 'job-7', action: 'quick', actionName: 'Quick Scan', background: true,
    started: '2026-09-28T10:00:00', paused: false, step: 'Index bookmarks added since your last run',
  };

  it('pins the run going now above the history, saying where it has got to', async () => {
    jobs.activeRuns.set([going]);
    await show([aRun()]);

    const pinned = element.querySelector('[data-active-run]')!;
    expect(element.querySelector('.run')).toBe(pinned);
    expect(pinned.textContent).toContain('Quick Scan');
    expect(pinned.textContent).toContain('In progress - running');
    expect(pinned.textContent).toContain('in the background');
    expect(pinned.textContent).toContain('Index bookmarks added since your last run');
  });

  it('says a paused run is paused', async () => {
    jobs.activeRuns.set([{ ...going, paused: true }]);
    await show([]);

    expect(element.querySelector('[data-active-run]')?.textContent).toContain('In progress - paused');
  });

  it('offers to view a background run\'s progress', async () => {
    jobs.activeRuns.set([going]);
    await show([]);
    const viewed = vi.fn();
    fixture.componentInstance.viewProgress.subscribe(viewed);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.trim() === 'View progress')!.click();

    expect(viewed).toHaveBeenCalledWith(going);
  });

  it('does not offer to view a run that is not in the background', async () => {
    // it needs the page that started it, which is where its progress is
    jobs.activeRuns.set([{ ...going, background: false }]);
    await show([]);

    const pinned = element.querySelector('[data-active-run]')!;
    expect(pinned.textContent).not.toContain('View progress');
    expect(pinned.textContent).toContain('only in the window that started it');
  });

  it('pins nothing when no run is going', async () => {
    await show([aRun()]);
    expect(element.querySelector('[data-active-run]')).toBeNull();
  });

  it('marks a run from the history as having been in the background', async () => {
    await show([aRun({ background: true })]);
    expect(element.querySelector('.run-status')?.textContent).toContain('background');
  });

  // endregion

  // region the issues file, for any run

  it('offers every run with issues its issues as a file, saying how many', async () => {
    await show([
      aRun({ failures: [{ id: '1', link: 'l', error: 'gone' }],
             skipped: [{ id: '2', link: 'm', error: 'a series' }] }),
      aRun({ file: 'b.json', id: 'b' }),
    ]);

    const buttons = Array.from(element.querySelectorAll('button')).filter(
      (b) => b.textContent?.includes('Download issues'),
    );
    expect(buttons).toHaveLength(1);
    expect(buttons[0].textContent).toContain('(2)');
  });

  it('saves the same report the run window used to, headed with the run', async () => {
    // caught where the browser would be handed the file
    let saved: Blob | null = null;
    let name = '';
    const created = vi.fn((blob: Blob) => {
      saved = blob;
      return 'blob:report';
    });
    Object.assign(URL, { createObjectURL: created, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    await show([aRun({ id: 'abcdef123', failures: [{ id: '1', link: 'l', error: 'gone' }] })]);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Download issues'))!.click();

    const text = await saved!.text();
    expect(text).toContain('# Issues from Download new bookmarks and update incomplete fics');
    expect(text).toContain('## 1 work that could not be downloaded');
    expect(text).toContain('1\tl\tgone');
    expect(name).toBe('run-issues-2026-09-13-abcdef12.txt');
    click.mockRestore();
  });

  // endregion

  // region abandoned runs

  it('calls a run the helper ended for being left paused abandoned, and offers to resume it', async () => {
    await show([aRun({ action: 'quick', actionName: 'Quick Scan', status: 'abandoned',
                       progress: { step: 'index', stepLabel: 'Index bookmarks' } })]);

    expect(element.querySelector('.run-status')?.textContent).toContain('Abandoned');
    expect(element.textContent).toContain('left paused, so the helper ended it');
    expect(Array.from(element.querySelectorAll('button')).some(
      (b) => b.textContent?.includes('Resume'))).toBe(true);
  });

  it('says to start again a run that cannot be resumed', async () => {
    await show([aRun({ action: 'sync', status: 'abandoned' })]);
    expect(element.textContent).toContain('Start the same run again');
  });

  it('says when a paused run in progress will be abandoned', async () => {
    jobs.activeRuns.set([{ ...going, paused: true, abandonsAt: '2026-09-28T13:10:00' }]);
    await show([]);

    const expected = new Date('2026-09-28T13:10:00')
      .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    expect(element.querySelector('[data-active-run]')?.textContent).toContain(
      `Abandoned at ${expected} unless resumed`);
  });

  // endregion

  // region the log, and runs the helper has not confirmed

  it('offers the log of any run that kept one', async () => {
    await show([aRun({ logLines: 12 }), aRun({ file: 'b.json', id: 'b', logLines: 0 })]);

    const buttons = Array.from(element.querySelectorAll('button')).filter(
      (b) => b.textContent?.includes('Download log'),
    );
    expect(buttons).toHaveLength(1);
  });

  it('saves the log read back out of the run\'s own file, saying what was dropped', async () => {
    let saved: Blob | null = null;
    let name = '';
    Object.assign(URL, { createObjectURL: vi.fn((blob: Blob) => ((saved = blob), 'blob:x')),
                         revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      name = this.download;
    });
    const read = vi.fn(async () => JSON.stringify({
      log: ['logging in as Someone', 'new download: 1 A.html'], logTrimmed: 3,
    }));
    TestBed.inject(Library).store.set({ read } as never);
    await show([aRun({ id: 'abcdef123', file: 'r.json', logLines: 2 })]);

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Download log'))!.click();
    await fixture.whenStable();

    expect(read).toHaveBeenCalledWith('runs/r.json');
    const text = await saved!.text();
    expect(text).toContain('# Download new bookmarks and update incomplete fics, started');
    expect(text).toContain('the first 3 lines were dropped');
    expect(text.trim().split('\n').slice(-2)).toEqual(['logging in as Someone', 'new download: 1 A.html']);
    expect(name).toBe('run-log-2026-09-13-abcdef12.txt');
    click.mockRestore();
  });

  it('does not call a run running when the helper has not said it is', async () => {
    jobs.leaveRunning = true;
    await show([aRun({ status: 'running', finished: null })]);
    // settleInterrupted is stubbed to leave it, as when the helper does not answer
    expect(element.querySelector('.run-status')?.textContent).toContain('not confirmed');
  });

  it('names a run going on another helper as such', async () => {
    jobs.leaveRunning = true;
    await show([aRun({ status: 'running', finished: null, helper: 'https://elsewhere.example' })]);
    expect(element.querySelector('.run-status')?.textContent).toContain('Running on another helper');
  });

  // endregion

  // region running a collections run again

  function runAgainButton(): HTMLButtonElement | undefined {
    return Array.from(element.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === 'Run again',
    );
  }

  it('offers to run a collections run again, handing over the whole run', async () => {
    const emitted: RunHistory[] = [];
    const run = aRun({ action: 'collection', url: 'https://archiveofourown.org/collections/x',
                       options: { collectionWorks: true } });
    await show([run]);
    fixture.componentInstance.runAgain.subscribe((r) => emitted.push(r));

    runAgainButton()!.click();

    expect(emitted).toEqual([run]);
    // the link it was pointed at is shown on the entry
    expect(element.querySelector('.run-link')?.textContent).toContain('collections/x');
    expect(element.textContent).toContain('indexed and downloaded the works in them');
  });

  it('says a collection run from before links were saved needs its link again', async () => {
    await show([aRun({ action: 'collection' })]);

    expect(runAgainButton()).toBeTruthy();
    expect(element.textContent).toContain('paste it in again');
  });

  it('offers Run again on the collection runs alone, and not while one is going', async () => {
    jobs.leaveRunning = true;
    await show([aRun({ action: 'collections', status: 'running' }), aRun({ file: 'b', id: 'b' })]);
    expect(runAgainButton()).toBeUndefined();

    jobs.activeRuns.set([{ ...going, action: 'quick' }]);
    await show([aRun({ action: 'collections' })]);
    expect(runAgainButton()).toBeUndefined();
  });

  // endregion
});
