/**
 * Getting a downloads folder into the shape this app expects, the moment it is opened.
 *
 * A library is a folder with five folders in it - the index, collections, images, run
 * history and the works themselves - and everything else assumes they are there. So each
 * time a library is opened, on this computer or in Dropbox, this checks for them and makes
 * whichever are missing. Works in particular live in `works/` and are looked for nowhere
 * else; a library from before that rule still has them in its top level, and this offers to
 * move them rather than leave them unseen - an unseen work is one every run downloads again.
 *
 * The page is covered from the moment a library is opened until it is ready
 * (`setup-overlay`) - while checking, then while creating folders or moving files. A page
 * that still took clicks would let a run start against a library that is half set up. When
 * everything is already in place, which is every time but the first, the cover is up only
 * for as long as the check takes.
 *
 * The move is **asked about every time** it finds works to move, and never done unasked.
 * Declining leaves them exactly where they are; the next opening asks again.
 */

import { Injectable, signal } from '@angular/core';
import { workIdFromFilename } from './bookmarks';

/** every folder a library is expected to have - the helper's `LIBRARY_FOLDER_NAMES` */
export const LIBRARY_FOLDERS = ['indexing', 'collections', 'images', 'runs', 'works'];
export const WORKS_FOLDER = 'works';

/** the formats a run downloads; a file in one of these, named for a work, is a work */
const WORK_FORMAT = /\.(html?|epub|pdf|mobi|azw3)$/i;

/** what a library's top level holds, by name */
export interface TopLevel {
  folders: string[];
  files: string[];
}

export interface MoveResult {
  moved: number;
  /** names left where they were - usually because works/ already has a file by that name */
  notMoved: string[];
}

/** a library, local or in Dropbox, as far as setting it up needs to reach into it */
export interface SetupTarget {
  topLevel(): Promise<TopLevel>;
  makeFolder(name: string): Promise<void>;
  moveToWorks(names: string[], progress: (done: number) => void): Promise<MoveResult>;
}

export type SetupState = 'idle' | 'working' | 'asking';

/** whether a top-level file is a downloaded work that belongs in works/ */
export function isLooseWork(name: string): boolean {
  return WORK_FORMAT.test(name) && !!workIdFromFilename(name);
}

@Injectable({ providedIn: 'root' })
export class LibrarySetup {
  /** anything but idle covers the page */
  readonly state = signal<SetupState>('idle');
  readonly message = signal('');
  readonly detail = signal('');
  readonly progress = signal<{ done: number; total: number } | null>(null);
  /** how many works are waiting in the top level, while the question is up */
  readonly looseWorks = signal(0);
  /** what the last setup could not do, said once it is over; cleared by the next one */
  readonly report = signal('');

  private answer: ((move: boolean) => void) | null = null;

  /**
   * Make whatever `target` is missing, and offer to move its loose works. Resolves once the
   * library is ready to read. Throws if a folder cannot be made - reading a library that
   * cannot be set up would only fail later, less clearly.
   */
  async prepare(target: SetupTarget, where: string): Promise<void> {
    this.report.set('');
    // covered from the first moment, before anything is known: the check itself can take a
    // moment on a large folder or a slow connection, and the page must not take a click that
    // starts a run against a library that turns out to need setting up
    this.state.set('working');
    this.message.set(`Opening ${where}`);
    this.detail.set('Checking the folders this app keeps your library in.');
    try {
      const top = await target.topLevel();
      // folder names are compared the way Dropbox and Windows both compare them
      const have = new Set(top.folders.map((x) => x.toLowerCase()));
      const missing = LIBRARY_FOLDERS.filter((x) => !have.has(x));
      const loose = top.files.filter(isLooseWork);

      if (missing.length) {
        this.state.set('working');
        this.message.set(`Setting up ${where}`);
        this.detail.set(
          `Creating the folders this app keeps your library in: ${missing.join(', ')}.`,
        );
        for (const name of missing) await target.makeFolder(name);
      }

      if (loose.length && (await this.ask(loose.length))) {
        this.state.set('working');
        this.message.set(`Moving your works into ${WORKS_FOLDER}/`);
        this.detail.set('Nothing is downloaded or deleted - the files only change folder.');
        this.progress.set({ done: 0, total: loose.length });
        const result = await target.moveToWorks(loose, (done) =>
          this.progress.set({ done, total: loose.length }),
        );
        if (result.notMoved.length) {
          const shown = result.notMoved.slice(0, 5).join(', ');
          const more = result.notMoved.length > 5 ? ` and ${result.notMoved.length - 5} more` : '';
          this.report.set(
            `Moved ${result.moved} of ${loose.length} works into ${WORKS_FOLDER}/. ` +
              `${result.notMoved.length} were left in the top level - usually because ` +
              `${WORKS_FOLDER}/ already has a file with the same name: ${shown}${more}.`,
          );
        }
      }
    } finally {
      this.state.set('idle');
      this.progress.set(null);
      this.looseWorks.set(0);
      this.answer = null;
    }
  }

  /** The answer to the question the overlay is showing. */
  choose(move: boolean): void {
    const answer = this.answer;
    this.answer = null;
    answer?.(move);
  }

  private ask(count: number): Promise<boolean> {
    this.looseWorks.set(count);
    this.state.set('asking');
    return new Promise((resolve) => (this.answer = resolve));
  }
}
