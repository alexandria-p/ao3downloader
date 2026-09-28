import { describe, expect, it } from 'vitest';
import { issueCount, issuesOf, issuesReport } from './issues';
import { RunHistory } from './jobs';

function aRun(over: Partial<RunHistory> = {}): RunHistory {
  return {
    file: 'a.json', id: 'a', action: 'sync', actionName: 'Sync', started: '', finished: null,
    status: 'success', filetypes: [], options: {}, reindexed: [], downloaded: [], updated: [],
    choices: [], failures: [], skipped: [], error: '', ...over,
  };
}

describe('issuesOf', () => {
  it('reads every kind of issue out of a run\'s history file', () => {
    const found = issuesOf(aRun({
      failures: [{ id: '1', link: 'l', error: 'gone' }],
      skipped: [{ id: '2', link: 'm', error: 'a series' }],
      keptCopies: [{ id: '3', link: 'n', error: 'locked', file: 'new', old: 'old' }],
      removals: [
        { id: '4', filetype: 'HTML', file: '4 old.html', keeping: '4 new.html', status: 'removed' },
        { id: '5', filetype: 'HTML', file: '5 old.html', keeping: '5 new.html', status: 'kept',
          error: 'in use' },
      ],
    }));

    expect(issueCount(found)).toBe(4);
    // only the ones still there are issues
    expect(found.notRemoved).toEqual([
      { id: '5', link: '', file: '5 old.html', old: '5 new.html', error: 'in use' },
    ]);
  });

  it('says why an older copy a run never got round to is still there', () => {
    // a record still saying pending is a run that ended before its cleanup step
    const found = issuesOf(aRun({ removals: [
      { id: '6', filetype: 'HTML', file: '6 old.html', keeping: '6 new.html', status: 'pending' },
    ] }));

    expect(found.notRemoved[0].error).toContain('before its cleanup step');
  });

  it('copes with a history file from before any of these were recorded', () => {
    const old = aRun();
    delete (old as Partial<RunHistory>).keptCopies;
    expect(issueCount(issuesOf(old))).toBe(0);
  });
});

describe('issuesReport', () => {
  it('leaves out a kind with nothing in it', () => {
    const report = issuesReport(issuesOf(aRun({ failures: [{ id: '1', link: 'l', error: 'x' }] })));
    expect(report.split('\n').filter((x) => x.startsWith('## '))).toEqual([
      '## 1 work that could not be downloaded',
    ]);
  });
});
