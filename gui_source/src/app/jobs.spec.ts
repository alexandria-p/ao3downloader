import { afterEach, describe, expect, it, vi } from 'vitest';
import { Jobs } from './jobs';
import { LibraryStore } from './library-store';

/** a library that is only its runs folder, in memory */
function runsFolder(records: Record<string, object>): LibraryStore & { files: Map<string, string> } {
  const files = new Map(Object.entries(records).map(([name, record]) =>
    [`runs/${name}`, JSON.stringify(record)]));
  return {
    label: 'memory',
    files,
    check: async () => undefined,
    list: async (path: string) => [...files.keys()].filter((key) => key.startsWith(path + '/')),
    read: async (path: string) => files.get(path) ?? null,
    write: async (path: string, body: Response) => {
      const text = await body.text();
      files.set(path, text);
      return text.length;
    },
    size: async () => null,
    delete: async () => undefined,
    rename: async () => undefined,
    mkdir: async () => undefined,
  };
}

function run(id: string, status: string) {
  return { id, action: 'quick', status, started: '2026-09-20T21:15:00' };
}

function helperWorkingOn(...active: string[]) {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ active }))));
}

function statusOf(store: { files: Map<string, string> }, name: string): string {
  return JSON.parse(store.files.get(`runs/${name}`)!).status;
}

describe('Jobs.settleInterrupted', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('marks a run still saying running that the helper is not working on', async () => {
    const store = runsFolder({ 'a.json': run('a', 'running'), 'b.json': run('b', 'running') });
    helperWorkingOn('b');

    expect(await new Jobs().settleInterrupted(store)).toBe(1);

    expect(statusOf(store, 'a.json')).toBe('interrupted');
    // still going - another tab's run, say - and left alone
    expect(statusOf(store, 'b.json')).toBe('running');
  });

  it('leaves them alone when the helper does not answer', async () => {
    // a hosted helper waking up, or a dropped connection, looks just like one that is gone -
    // and a background run may be going on it perfectly well. settled next time it answers
    const store = runsFolder({ 'a.json': run('a', 'running') });
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));

    expect(await new Jobs().settleInterrupted(store)).toBe(0);
    expect(statusOf(store, 'a.json')).toBe('running');
  });

  it('goes by the run\'s own id, so another run going cannot stand in for it', async () => {
    const store = runsFolder({ 'a.json': run('a', 'running') });
    helperWorkingOn('someone-elses-run');

    expect(await new Jobs().settleInterrupted(store)).toBe(1);
    expect(statusOf(store, 'a.json')).toBe('interrupted');
  });

  it('leaves alone a run started on a different helper', async () => {
    // the helper on this computer knows nothing of what the hosted one is doing in the same
    // Dropbox library, and must not end it on paper
    const store = runsFolder({
      'a.json': { ...run('a', 'running'), helper: 'https://helper.example.com' },
      'b.json': { ...run('b', 'running'), helper: 'http://127.0.0.1:4400/' },
    });
    helperWorkingOn();

    expect(await new Jobs().settleInterrupted(store)).toBe(1);
    expect(statusOf(store, 'a.json')).toBe('running');
    // the same helper, written a little differently
    expect(statusOf(store, 'b.json')).toBe('interrupted');
  });

  it('leaves runs that ended alone, and does not ask the helper when none is running', async () => {
    const store = runsFolder({ 'a.json': run('a', 'success'), 'b.json': run('b', 'stopped') });
    const fetching = vi.fn();
    vi.stubGlobal('fetch', fetching);

    expect(await new Jobs().settleInterrupted(store)).toBe(0);
    expect(fetching).not.toHaveBeenCalled();
    expect(statusOf(store, 'b.json')).toBe('stopped');
  });

  it('does nothing without a library', async () => {
    expect(await new Jobs().settleInterrupted(null)).toBe(0);
  });
});
