import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { Jobs } from './jobs';
import { Library } from './library';
import type { LibraryStore } from './library-store';

/** the least time between two checks a page makes on its own (a tab coming back into view) */
export const CHECK_EVERY_MS = 20_000;

/**
 * Whether a run has finished since the library on screen was read, with changes this page
 * did not take in - a background run (the helper writes to Dropbox itself), or a run from
 * another tab or device on the same library.
 *
 * **No clocks are compared.** A hosted helper's clock and the browser's need not agree, and a
 * local and a hosted helper can share one Dropbox library. So a read notes which run records
 * the library held (`runs/`, one listing) and which runs the helper said were going. A check
 * lists `runs/` again and reads only the records that are new since, or were going then -
 * usually none - and the library is behind once one of them has finished. A run whose
 * changes this page took in itself (`takenIn`, from the run window's `refreshAfterRun`) never
 * counts: those are already on screen.
 */
@Injectable({ providedIn: 'root' })
export class LibraryFreshness {
  private readonly library = inject(Library);
  private readonly jobs = inject(Jobs);

  /** a run has finished since the library was read, and the listing does not show it */
  readonly behind = signal(false);

  private snapshot: { store: LibraryStore; names: Set<string>; going: Set<string> } | null = null;
  private readonly taken = new Set<string>();
  private checking = false;
  private lastCheck = 0;

  constructor() {
    effect(() => {
      const read = this.library.lastRead();
      untracked(() => void this.noteRead(read?.store ?? null));
    });
  }

  /** a run whose every change went through this page and is on screen already */
  takenIn(jobId: string | null | undefined): void {
    if (jobId) this.taken.add(shortId(jobId));
  }

  /**
   * Look again. `soon` is a check the page made on its own (a tab coming back), at most one
   * per CHECK_EVERY_MS; a run just seen to end always looks.
   */
  async check(soon = false): Promise<void> {
    const snapshot = this.snapshot;
    if (!snapshot || this.checking || this.behind()) return;
    if (soon && Date.now() - this.lastCheck < CHECK_EVERY_MS) return;
    if (snapshot.store !== this.library.store()) return;
    this.checking = true;
    this.lastCheck = Date.now();
    try {
      const names = await runNames(snapshot.store);
      const candidates = names
        .filter((name) => !snapshot.names.has(name) || snapshot.going.has(idOf(name)))
        .filter((name) => !this.taken.has(idOf(name)))
        .sort()
        .reverse();
      for (const name of candidates) {
        if (snapshot !== this.snapshot) return;
        const status = await statusOf(snapshot.store, `runs/${name}`);
        if (status && status !== 'running') {
          if (snapshot === this.snapshot) this.behind.set(true);
          return;
        }
      }
    } catch {
      // a library that will not list says nothing about whether it is behind
    } finally {
      this.checking = false;
    }
  }

  private async noteRead(store: LibraryStore | null): Promise<void> {
    this.behind.set(false);
    this.snapshot = null;
    if (!store) return;
    try {
      const [names, going] = await Promise.all([
        runNames(store),
        this.jobs.refreshActiveRuns(),
      ]);
      // a later read, or another library, has taken over meanwhile
      if (this.library.lastRead()?.store !== store) return;
      this.snapshot = {
        store,
        names: new Set(names),
        going: new Set((going ?? this.jobs.activeRuns()).map((run) => shortId(run.id))),
      };
    } catch {
      this.snapshot = null;
    }
  }
}

/** the record files in runs/, by name alone - named `<started>-<first 8 of the run id>.json` */
async function runNames(store: LibraryStore): Promise<string[]> {
  return (await store.list('runs', false))
    .map((path) => path.split('/').pop() ?? path)
    .filter((name) => /\.json$/i.test(name));
}

function idOf(name: string): string {
  return name.replace(/\.json$/i, '').split('-').pop() ?? '';
}

function shortId(id: string): string {
  return id.slice(0, 8);
}

async function statusOf(store: LibraryStore, path: string): Promise<string> {
  try {
    const record = JSON.parse((await store.read(path)) ?? '');
    return typeof record?.status === 'string' ? record.status : '';
  } catch {
    return '';
  }
}
