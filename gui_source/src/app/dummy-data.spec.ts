import { TestBed } from '@angular/core/testing';
import { DebugMode } from './debug-mode';
import { DUMMY_DATA_KEY, DummyData, dummyLibrary } from './dummy-data';
import { readRunHistory } from './library-store';
import { workIdFromFilename } from './bookmarks';

describe('dummyLibrary', () => {
  it('builds a different library for each storage choice, each saying which it is', async () => {
    const local = dummyLibrary('local');
    const dropbox = dummyLibrary('dropbox');
    const localIndex = await local.list('indexing');
    const dropboxIndex = await dropbox.list('indexing');
    expect(localIndex.length).not.toBe(dropboxIndex.length);
    expect(local.label).toContain('this computer');
    expect(dropbox.label).toContain('Dropbox');
    expect(await local.read(localIndex[0])).toContain('Dummy data (This computer)');
    expect(await dropbox.read(dropboxIndex[0])).toContain('Dummy data (Dropbox)');
  });

  it('holds works, collections and a run history that reads as a real one does', async () => {
    for (const kind of ['local', 'dropbox'] as const) {
      const store = dummyLibrary(kind);
      expect((await store.list('collections')).length).toBeGreaterThan(1);
      const runs = await readRunHistory(store);
      expect(runs.length).toBeGreaterThan(2);
      expect(runs.every((run) => run.status !== 'running')).toBe(true);
    }
  });

  it('gives every work file an index entry, so nothing offers to repair it', async () => {
    const store = dummyLibrary('dropbox');
    const indexed = new Set((await store.list('indexing')).map((p) => workIdFromFilename(p.split('/').pop()!)));
    for (const path of await store.list('works')) {
      expect(indexed.has(workIdFromFilename(path.split('/').pop()!))).toBe(true);
    }
  });
});

describe('DummyData', () => {
  beforeEach(() => localStorage.clear());

  it('is only in force while debug mode is on', () => {
    const dummy = TestBed.inject(DummyData);
    const debug = TestBed.inject(DebugMode);
    dummy.set(true);
    expect(localStorage.getItem(DUMMY_DATA_KEY)).toBe('on');
    expect(dummy.active()).toBe(false);
    debug.set(true);
    expect(dummy.active()).toBe(true);
    debug.set(false);
  });

  it('keeps one library per choice while on, and a fresh one after being turned off', () => {
    const dummy = TestBed.inject(DummyData);
    dummy.set(true);
    const first = dummy.library('local');
    expect(dummy.library('local')).toBe(first);
    dummy.set(false);
    expect(dummy.library('local')).not.toBe(first);
    expect(localStorage.getItem(DUMMY_DATA_KEY)).toBeNull();
  });
});
