/**
 * Debug mode, and the mock library the DEBUG tab tries the Resolve issues window on.
 *
 * Debug mode is this browser's alone (`DEBUG_MODE_KEY`), turned on and off in User settings.
 * It shows a banner above everything else and a DEBUG tab - nothing else changes.
 *
 * **A mock never touches the real library.** Its files live in a `MemoryStore`, so dating
 * renames and duplicate removals happen in memory; the window runs in `sandbox` mode, so its
 * exclusion lists are noted rather than written, no listing is refreshed, and starting hands back
 * the request instead of starting a run. Only the helper's file-naming answer is asked for, which
 * changes nothing.
 */

import { Injectable, signal } from '@angular/core';
import { DuplicateGroup, FoundFile, FoundWork, duplicateGroups, undatedIndexedFiles, unindexedWorks } from './imports';
import { LibraryStore } from './library-store';
import { safeGet, safeRemove, safeSet } from './storage';

export const DEBUG_MODE_KEY = 'ao3.debugMode';

@Injectable({ providedIn: 'root' })
export class DebugMode {
  readonly on = signal(safeGet(DEBUG_MODE_KEY) === 'on');

  set(on: boolean): void {
    this.on.set(on);
    if (on) safeSet(DEBUG_MODE_KEY, 'on');
    else safeRemove(DEBUG_MODE_KEY);
  }
}

/** a library held in memory, by path - what a mock renames and deletes, and nothing else */
export class MemoryStore implements LibraryStore {
  readonly label = 'mock library (in memory)';
  readonly files = new Map<string, string>();

  constructor(paths: Iterable<string> = []) {
    for (const path of paths) this.files.set(path, '');
  }

  async check(): Promise<void> {}

  async list(path: string): Promise<string[]> {
    const prefix = path ? `${path.replace(/\/+$/, '')}/` : '';
    return [...this.files.keys()].filter((p) => p.startsWith(prefix)).sort();
  }

  async read(path: string): Promise<string | null> {
    return this.files.get(path) ?? null;
  }

  async write(path: string, body: Response): Promise<number> {
    const text = await body.text();
    this.files.set(path, text);
    return text.length;
  }

  async size(path: string): Promise<number | null> {
    return this.files.has(path) ? (this.files.get(path) ?? '').length : null;
  }

  async delete(path: string): Promise<void> {
    this.files.delete(path);
  }

  async rename(from: string, to: string): Promise<void> {
    if (this.files.has(to)) throw new Error(`${to} is already there`);
    if (!this.files.has(from)) throw new Error(`${from} is not there`);
    this.files.set(to, this.files.get(from) ?? '');
    this.files.delete(from);
  }

  async mkdir(): Promise<void> {}
}

/** what a mock library has issues with, and how many of each */
export interface MockSetup {
  duplicates: boolean;
  duplicateCount: number;
  index: boolean;
  indexCount: number;
  dates: boolean;
  datesCount: number;
}

export const DEFAULT_MOCK: MockSetup = {
  duplicates: true,
  duplicateCount: 4,
  index: true,
  indexCount: 5,
  dates: true,
  datesCount: 6,
};

/** what the window is opened with, worked out from the mock's files by the same rules as a real library */
export interface MockLibrary {
  store: MemoryStore;
  works: FoundWork[];
  undatedElsewhere: FoundFile[];
  duplicates: DuplicateGroup[];
}

const TITLES = ['The Long Way Home', 'Ink and Salt', 'Small Hours', 'A Map of Rivers', 'Glass Gardens', 'North of Nowhere'];
const FORMATS = ['html', 'epub', 'pdf', 'mobi'];

function title(n: number): string {
  return `${TITLES[n % TITLES.length]} - Mock Writer`;
}

/**
 * The files of a mock library. Works with index issues are numbered from 7000001, works with
 * date issues from 7100001 and duplicates from 7200001; only the last two are treated as
 * indexed. Duplicate groups cycle through the cases the page tells apart: dated with one
 * newest, three copies, an undated copy, and two sharing a date.
 */
export function mockPaths(setup: MockSetup): { paths: string[]; indexed: Set<string> } {
  const paths: string[] = [];
  const indexed = new Set<string>();
  if (setup.index) {
    for (let i = 0; i < setup.indexCount; i++) {
      const id = String(7000001 + i);
      paths.push(`works/${id} ${title(i)} 2024-0${(i % 9) + 1}-15.html`);
      // some have an undated copy in another format, so they are in the dates too
      if (setup.dates && i % 2 === 0) paths.push(`works/${id} ${title(i)}.${FORMATS[(i % 3) + 1]}`);
    }
  }
  if (setup.dates) {
    for (let i = 0; i < setup.datesCount; i++) {
      const id = String(7100001 + i);
      indexed.add(id);
      const name = i % 3 === 0 ? `${title(i)} (saved 03-1${i % 9}-2021)` : i % 3 === 1 ? `${title(i)} 14 Dec 2020` : title(i);
      paths.push(`works/${id} ${name}.${FORMATS[i % FORMATS.length]}`);
    }
  }
  if (setup.duplicates) {
    for (let i = 0; i < setup.duplicateCount; i++) {
      const id = String(7200001 + i);
      indexed.add(id);
      const base = `works/${id} ${title(i)}`;
      switch (i % 4) {
        case 0:
          paths.push(`${base} 2025-03-01.html`, `${base} (old copy) 2024-11-02.htm`);
          break;
        case 1:
          paths.push(`${base} 2021-05-01.epub`, `${base} (backup) 2020-01-30.epub`, `${base}_2022-07-19.epub`);
          break;
        case 2:
          paths.push(`${base} 2019-08-14.pdf`, `${base}.pdf`);
          break;
        default:
          paths.push(`${base} 2023-03-03.mobi`, `${base} copy 2023-03-03.mobi`);
      }
    }
  }
  return { paths, indexed };
}

export function mockLibrary(setup: MockSetup): MockLibrary {
  const { paths, indexed } = mockPaths(setup);
  return {
    store: new MemoryStore(paths),
    works: unindexedWorks(paths, indexed),
    undatedElsewhere: undatedIndexedFiles(paths, indexed),
    duplicates: duplicateGroups(paths),
  };
}
