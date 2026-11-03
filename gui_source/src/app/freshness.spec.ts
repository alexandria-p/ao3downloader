import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { beforeEach, describe, expect, it } from 'vitest';
import { LibraryFreshness } from './freshness';
import { ActiveRun, Jobs } from './jobs';
import { Library } from './library';
import { LibraryStore } from './library-store';

/** a library holding run records, by name, each with its status */
function aStore(records: Record<string, string>): LibraryStore {
  const nothing = async () => {
    throw new Error('not used here');
  };
  return {
    label: 'a library',
    check: async () => undefined,
    list: async (path: string) => (path === 'runs' ? Object.keys(records).map((n) => `runs/${n}`) : []),
    read: async (path: string) => {
      const status = records[path.replace(/^runs\//, '')];
      return status === undefined ? null : JSON.stringify({ status });
    },
    write: nothing,
    size: nothing,
    delete: nothing,
    rename: nothing,
    mkdir: nothing,
  };
}

const RUN_A = '2026-11-01T100000-aaaaaaaa.json';
const RUN_B = '2026-11-03T090000-bbbbbbbb.json';

let records: Record<string, string>;
let store: LibraryStore;
let going: ActiveRun[];
let library: { lastRead: ReturnType<typeof signal<{ store: LibraryStore; at: number } | null>>; store: ReturnType<typeof signal<LibraryStore | null>> };
let freshness: LibraryFreshness;

function aRun(id: string): ActiveRun {
  return { id, action: 'bookmarks', actionName: 'Full scan', background: true,
    started: '2026-11-03T09:00:00', paused: false, step: '' };
}

async function read(): Promise<void> {
  library.lastRead.set({ store, at: Date.now() });
  TestBed.tick();
  // the snapshot is taken after a listing and the helper's answer
  await new Promise((done) => setTimeout(done, 0));
}

describe('LibraryFreshness', () => {
  beforeEach(() => {
    records = { [RUN_A]: 'success' };
    store = aStore(records);
    going = [];
    library = { lastRead: signal(null), store: signal(store) };
    const jobs = { activeRuns: signal<ActiveRun[]>([]), refreshActiveRuns: async () => going };
    TestBed.configureTestingModule({
      providers: [{ provide: Library, useValue: library }, { provide: Jobs, useValue: jobs }],
    });
    freshness = TestBed.inject(LibraryFreshness);
  });

  it('is not behind when no run has finished since the library was read', async () => {
    await read();
    await freshness.check();
    expect(freshness.behind()).toBe(false);
  });

  it('is behind once a run that started after the read has finished', async () => {
    await read();
    records[RUN_B] = 'success';
    await freshness.check();
    expect(freshness.behind()).toBe(true);
  });

  it('is behind once a run going at the read has finished, though its record was already there', async () => {
    records[RUN_B] = 'running';
    going = [aRun('bbbbbbbb-1111')];
    await read();

    await freshness.check();
    expect(freshness.behind()).toBe(false);

    records[RUN_B] = 'partial';
    await freshness.check();
    expect(freshness.behind()).toBe(true);
  });

  it('is not behind for a run still going', async () => {
    await read();
    records[RUN_B] = 'running';
    await freshness.check();
    expect(freshness.behind()).toBe(false);
  });

  it('never counts a run whose changes this page took in itself', async () => {
    await read();
    freshness.takenIn('bbbbbbbb-2222');
    records[RUN_B] = 'success';
    await freshness.check();
    expect(freshness.behind()).toBe(false);
  });

  it('is up to date again once the library is read again', async () => {
    await read();
    records[RUN_B] = 'success';
    await freshness.check();
    expect(freshness.behind()).toBe(true);

    await read();
    expect(freshness.behind()).toBe(false);
    await freshness.check();
    expect(freshness.behind()).toBe(false);
  });

  it('says nothing about a library no longer on screen', async () => {
    await read();
    records[RUN_B] = 'success';
    library.store.set(aStore({}));
    await freshness.check();
    expect(freshness.behind()).toBe(false);
  });
});
