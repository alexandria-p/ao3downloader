import { Component, effect, inject, signal, untracked, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Jobs, RunHistory, RunRemoval } from './jobs';
import { Library } from './library';

/** why a custom run over a slice of the listing is never offered for resuming */
export const SLICE_CANNOT_RESUME =
  'A custom run over a slice of your bookmarks listing cannot be resumed: bookmarks added or ' +
  'removed since move every page, so the same page numbers no longer hold the same bookmarks.';

/**
 * What past runs did, read back from the helper's run files.
 *
 * The fic lists are collapsed by default and the rest of the card is not: a run that
 * touched a thousand works would otherwise bury the next one, and the number is usually
 * all anybody wants from it.
 */
@Component({
  selector: 'app-history',
  imports: [DecimalPipe],
  templateUrl: './history.html',
  styleUrl: './history.css',
})
export class History {
  private readonly jobs = inject(Jobs);
  private readonly library = inject(Library);

  protected readonly runs = signal<RunHistory[]>([]);
  protected readonly loading = signal(true);
  /** true when the helper could not be reached at all, which is not the same as no runs */
  protected readonly unavailable = signal(false);

  constructor() {
    // the history lives in the library, so it is read again whenever the library changes -
    // switching to Dropbox while looking at this page shows Dropbox's runs
    effect(() => {
      this.library.store();
      untracked(() => void this.load());
    });
  }

  /** the older copies a run removed in its cleanup step */
  protected removedOf(run: RunHistory): RunRemoval[] {
    return (run.removals ?? []).filter((x) => x.status === 'removed');
  }

  /**
   * The older copies a run marked for removal and did not remove. A record still saying
   * `pending` is a run that never reached its cleanup step - interrupted before it could
   * say so itself.
   */
  protected notRemovedOf(run: RunHistory): RunRemoval[] {
    return (run.removals ?? []).filter((x) => x.status !== 'removed');
  }

  /** a run to pick up where it left off, in a custom run */
  readonly resume = output<string>();

  protected async load(): Promise<void> {
    this.loading.set(true);
    let found = await this.jobs.loadRuns(this.library.store());
    // a run the history calls 'running' that the helper is not working on was interrupted:
    // marked so, and read again. only asked when there is one, which is seldom
    if (found?.some((run) => run.status === 'running') &&
        (await this.jobs.settleInterrupted(this.library.store()))) {
      found = await this.jobs.loadRuns(this.library.store());
    }
    this.unavailable.set(found === null);
    this.runs.set(found ?? []);
    this.loading.set(false);
  }

  /**
   * What to call a run's outcome.
   *
   * A record still saying 'running' is one that never finished - the file is written when
   * a run starts, so the absence of an ending is the evidence that it was interrupted.
   */
  protected outcome(run: RunHistory): string {
    switch (run.status) {
      case 'success':
        return 'Finished';
      case 'stopped':
        return 'Stopped';
      case 'failed':
        return 'Failed';
      case 'running':
        return 'Running';
      default:
        return 'Interrupted';
    }
  }

  /** when it ran, in the reader's own locale rather than as an iso stamp */
  protected when(stamp: string | null): string {
    if (!stamp) return '';
    const parsed = new Date(stamp);
    return Number.isNaN(parsed.getTime()) ? stamp : parsed.toLocaleString();
  }

  /** the settings worth showing back, as words rather than as a json dump */
  protected settingsOf(run: RunHistory): string[] {
    const options = run.options ?? {};
    const said: string[] = [];
    if (options['reindex'] === false) said.push('no reindexing');
    if (options['pages']) said.push(`up to page ${options['pages']}`);
    if (Number(options['start'] ?? 1) > 1) said.push(`from page ${options['start']}`);
    if (options['series']) said.push('all works from encountered series');
    if (options['images']) said.push('save images separately');
    return said;
  }

  /**
   * Whether a run can be picked up where it left off, or why not - the page's quick answer
   * for the button. The helper checks again, properly, when the run starts.
   */
  protected resumeProblem(run: RunHistory): string | null {
    if (!['bookmarks', 'quick', 'custom'].includes(run.action)) return null;
    if (run.status === 'success' || run.status === 'running') return null;
    const options = run.options ?? {};
    if (run.action === 'custom' && !options['dates'] &&
        (Number(options['pages'] ?? 0) || Number(options['start'] ?? 1) > 1)) {
      return SLICE_CANNOT_RESUME;
    }
    if (!run.progress) return 'This run is from before runs saved their progress.';
    return '';
  }

  /** the other run of a resume, by id, for the link either way */
  protected runById(id: string | null | undefined): RunHistory | undefined {
    return id ? this.runs().find((run) => run.id === id) : undefined;
  }

  protected workLink(id: string): string {
    return `https://archiveofourown.org/works/${id}`;
  }
}
