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

  it('tells a missing helper apart from an empty history', async () => {
    // one means start the app again, the other means go and run something
    await show(null);

    expect(element.textContent).toContain("helper isn't running");
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
    expect(said).toContain('expand series links');
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

  it('lists every run it was given', async () => {
    await show([aRun({ file: 'a.json' }), aRun({ file: 'b.json' })]);

    expect(element.querySelectorAll('.run').length).toBe(2);
  });
});
