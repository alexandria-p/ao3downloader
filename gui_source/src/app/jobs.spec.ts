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

  it('reads a run it already found ended only once, however many windows open', async () => {
    const store = runsFolder({ 'a.json': run('a', 'success'), 'b.json': run('b', 'running') });
    const reads: string[] = [];
    const read = store.read;
    store.read = async (path: string) => {
      reads.push(path);
      return read(path);
    };
    helperWorkingOn('b');

    await new Jobs().settleInterrupted(store);
    await new Jobs().settleInterrupted(store);

    expect(reads.filter((path) => path === 'runs/a.json')).toHaveLength(1);
    // still going, so it might yet be interrupted: read every time
    expect(reads.filter((path) => path === 'runs/b.json')).toHaveLength(2);
  });

  it('does not read again a run it marked interrupted itself', async () => {
    const store = runsFolder({ 'a.json': run('a', 'running') });
    helperWorkingOn();
    await new Jobs().settleInterrupted(store);

    const reads: string[] = [];
    const read = store.read;
    store.read = async (path: string) => {
      reads.push(path);
      return read(path);
    };
    await new Jobs().settleInterrupted(store);
    expect(reads).toEqual([]);
  });

  it('does nothing without a library', async () => {
    expect(await new Jobs().settleInterrupted(null)).toBe(0);
  });
});

describe('Jobs.forceStop', () => {
  afterEach(() => vi.unstubAllGlobals());

  function helperForceStops(record: object | null, status = 200) {
    const fetching = vi.fn(async (url: string) =>
      String(url).endsWith('/force-stop')
        ? new Response(JSON.stringify({ stopped: true, record }), { status })
        : new Response(JSON.stringify({ jobs: [] })));
    vi.stubGlobal('fetch', fetching);
    return fetching;
  }

  it('writes the record the helper hands back over the one in the library', async () => {
    const store = runsFolder({ 'a.json': run('a', 'running') });
    const fetching = helperForceStops({
      file: 'a.json',
      data: { ...run('a', 'stopped'), error: 'Force stopped from the History tab', log: ['bye'] },
    });

    await new Jobs().forceStop('a', store);

    expect(String(fetching.mock.calls[0][0])).toContain('/api/jobs/a/force-stop');
    expect(statusOf(store, 'a.json')).toBe('stopped');
    expect(JSON.parse(store.files.get('runs/a.json')!).log).toEqual(['bye']);
  });

  it('never writes a run that is not in this library', async () => {
    const store = runsFolder({});
    helperForceStops({ file: 'elsewhere.json', data: run('x', 'stopped') });

    await new Jobs().forceStop('x', store);

    expect(store.files.size).toBe(0);
  });

  it('says so when the helper will not', async () => {
    helperForceStops(null, 404);
    await expect(new Jobs().forceStop('gone', runsFolder({}))).rejects.toThrow();
  });
});

describe('Jobs.loadNewestFloor', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('stops reading at the first batch holding a scan to measure back to', async () => {
    const records: Record<string, object> = {};
    for (let n = 10; n < 40; n++) records[`2026${n}.json`] = run(`r${n}`, 'success');
    const store = runsFolder(records);
    const reads: string[] = [];
    const read = store.read;
    store.read = async (path: string) => {
      reads.push(path);
      return read(path);
    };
    // the helper says every run it is shown qualifies
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) =>
      new Response(JSON.stringify({ runs: JSON.parse(String(init?.body)).runs }))));

    const floor = await new Jobs().loadNewestFloor(store);

    expect(floor?.id).toBe('r39');
    // one batch of the thirty, not the whole history
    expect(reads.length).toBeLessThan(10);
  });
});
