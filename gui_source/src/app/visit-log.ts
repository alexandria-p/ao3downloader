/**
 * What someone did on this visit - for a bug report about something that is not a run.
 *
 * A run keeps its own account; nothing else did, so a report about a tab, a library read or a
 * setting arrived with nothing to go on. This keeps a short list of what happened on this
 * visit: tabs opened, the storage switched, library reads and how they ended, windows opened,
 * runs started and ended, settings changed **and the values chosen**, and every page error.
 *
 * **It lives in this page's memory alone**: nothing is written anywhere, it is gone when the
 * tab closes or reloads, and it leaves only as the feedback form's optional *Attach what I did
 * on this visit*, through the same `redactLog` the run log goes through. **Never note what
 * someone typed into the username or password boxes** - a setting's value, yes; a credential,
 * never. Fic titles and folder names are left out too: they say nothing about a bug.
 */

import { ErrorHandler, Injectable, inject } from '@angular/core';

/** how many entries are kept - the oldest go first, since a bug is near the end */
export const VISIT_LOG_LIMIT = 300;
/** no one entry may run longer than this, so an error with a huge message cannot crowd out the rest */
const ENTRY_LIMIT = 4000;

export interface VisitEntry {
  /** UTC, as every time the app keeps */
  at: string;
  text: string;
}

@Injectable({ providedIn: 'root' })
export class VisitLog {
  private readonly entries: VisitEntry[] = [];
  /** how many were dropped off the start for the cap */
  private dropped = 0;

  constructor() {
    // errors nobody caught reach it through Angular: provideBrowserGlobalErrorListeners hands
    // the window's errors and unhandled rejections to the ErrorHandler, which is VisitErrorHandler
    this.note('Page opened');
  }

  /** note something that happened */
  note(text: string): void {
    this.entries.push({ at: new Date().toISOString(), text: String(text).slice(0, ENTRY_LIMIT) });
    if (this.entries.length > VISIT_LOG_LIMIT) {
      this.entries.splice(0, this.entries.length - VISIT_LOG_LIMIT);
      this.dropped++;
    }
  }

  /** note an error, with its message and the first lines of where it came from */
  error(error: unknown, what = 'Error'): void {
    if (error instanceof Error) {
      const where = (error.stack ?? '').split('\n').slice(1, 4).map((line) => line.trim()).join(' | ');
      this.note(`${what}: ${error.name}: ${error.message}${where ? ` (${where})` : ''}`);
    } else {
      this.note(`${what}: ${String(error)}`);
    }
  }

  /** everything noted, one line each, oldest first, stamped in UTC */
  text(): string {
    const lines = this.entries.map((e) => `[${e.at.slice(0, 19).replace('T', ' ')} UTC] ${e.text}`);
    if (this.dropped) lines.unshift(`(earlier entries dropped - only the last ${VISIT_LOG_LIMIT} are kept)`);
    return lines.join('\n');
  }

  get size(): number {
    return this.entries.length;
  }
}

/** Angular's errors go to the console as before, and into the visit log too. */
@Injectable()
export class VisitErrorHandler implements ErrorHandler {
  private readonly visit = inject(VisitLog);

  handleError(error: unknown): void {
    this.visit.error(error);
    console.error(error);
  }
}
