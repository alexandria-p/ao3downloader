import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { History } from './history';
import { Jobs, RunHistory } from './jobs';

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

  override async loadRuns(): Promise<RunHistory[] | null> {
    return this.runs;
  }
}

let jobs: FakeJobs;
let fixture: ComponentFixture<History>;
let element: HTMLElement;

async function show(runs: RunHistory[] | null) {
  jobs.runs = runs;
  fixture = TestBed.createComponent(History);
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
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
    // the record is written when a run starts, so no ending is the evidence
    await show([aRun({ status: 'running', finished: null })]);

    expect(element.querySelector('.run-status')?.textContent?.trim()).toBe('Interrupted');
    expect(element.textContent).toContain('most likely interrupted');
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
});
