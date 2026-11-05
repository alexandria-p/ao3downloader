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

import { Injectable, computed, signal } from '@angular/core';
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

/** a location inside the library, said as a path: `Dropbox/Apps/FicFairy/works`, or `works` for a folder with no name */
function inside(where: string, name: string): string {
  return where ? `${where}/${name}` : name;
}

/** whether a top-level file is a downloaded work that belongs in works/ */
export function isLooseWork(name: string): boolean {
  return WORK_FORMAT.test(name) && !!workIdFromFilename(name);
}

@Injectable({ providedIn: 'root' })
export class LibrarySetup {
  /**
   * 'working' is said in the library's loading bar, step by step (`caption`, `progress`), and
   * holds the run buttons; only 'asking' - a question for the reader - covers the page
   */
  readonly state = signal<SetupState>('idle');
  /** what is happening now, as it happens: one line for the loading bar, locations in backticks */
  readonly caption = signal('');
  readonly progress = signal<{ done: number; total: number } | null>(null);
  /** the bar's percentage, when the step has a count */
  readonly percent = computed(() => {
    const progress = this.progress();
    return progress && progress.total ? Math.round((progress.done / progress.total) * 100) : null;
  });
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
    // working from the first moment, before anything is known: the check itself can take a
    // moment on a large folder or a slow connection, and the run buttons wait on it
    // (`App.libraryPreparing`) rather than start a run against a library that needs setting up
    this.state.set('working');
    this.caption.set(where ? `Checking the folders in \`${where}\`...` : 'Checking the folders in your library...');
    try {
      const top = await target.topLevel();
      // folder names are compared the way Dropbox and Windows both compare them
      const have = new Set(top.folders.map((x) => x.toLowerCase()));
      const missing = LIBRARY_FOLDERS.filter((x) => !have.has(x));
      const loose = top.files.filter(isLooseWork);

      // each folder said as it is made - no percentage: a folder or two is no measure
      for (const [done, name] of missing.entries()) {
        const count = missing.length > 1 ? ` (${done + 1} of ${missing.length})` : '';
        this.caption.set(`Creating folder \`${inside(where, name)}\`${count}`);
        await target.makeFolder(name);
      }

      if (loose.length && (await this.ask(loose.length))) {
        this.state.set('working');
        this.caption.set(`Moving your works into \`${inside(where, WORKS_FOLDER)}/\``);
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
      this.caption.set('');
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
