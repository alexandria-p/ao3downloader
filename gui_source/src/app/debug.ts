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
import { MemoryStore } from './memory-store';
import { safeGet, safeRemove, safeSet } from './storage';

// kept importable from here, where the mock first needed it
export { MemoryStore };

export { DEBUG_MODE_KEY, DebugMode } from './debug-mode';

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
  duplicateCount: 5,
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
 * newest, three copies, an undated copy, two sharing a date told apart by when each file was
 * last changed, and two sharing a date with nothing to tell them apart.
 */
export function mockPaths(setup: MockSetup): { paths: string[]; indexed: Set<string>; changed: Record<string, number> } {
  const paths: string[] = [];
  const indexed = new Set<string>();
  const changed: Record<string, number> = {};
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
      switch (i % 5) {
        case 0:
          paths.push(`${base} 2025-03-01.html`, `${base} (old copy) 2024-11-02.htm`);
          break;
        case 1:
          paths.push(`${base} 2021-05-01.epub`, `${base} (backup) 2020-01-30.epub`, `${base}_2022-07-19.epub`);
          break;
        case 2:
          paths.push(`${base} 2019-08-14.pdf`, `${base}.pdf`);
          break;
        case 3:
          paths.push(`${base} 2023-03-03.mobi`, `${base} copy 2023-03-03.mobi`);
          changed[`${base} 2023-03-03.mobi`] = Date.UTC(2023, 2, 4, 9, 30);
          changed[`${base} copy 2023-03-03.mobi`] = Date.UTC(2023, 5, 1, 18, 5);
          break;
        default:
          // the same date in both names, and no change time for either: cannot be told
          paths.push(`${base} 2022-02-02.azw3`, `${base} (2) 2022-02-02.azw3`);
      }
    }
  }
  return { paths, indexed, changed };
}

export function mockLibrary(setup: MockSetup): MockLibrary {
  const { paths, indexed, changed } = mockPaths(setup);
  return {
    store: new MemoryStore(paths, changed),
    works: unindexedWorks(paths, indexed),
    undatedElsewhere: undatedIndexedFiles(paths, indexed),
    duplicates: duplicateGroups(paths),
  };
}
