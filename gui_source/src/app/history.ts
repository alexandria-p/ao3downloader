import { Component, effect, inject, signal, untracked, output } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActiveRun, Jobs, RunHistory, RunRemoval } from './jobs';
import { issueCount, issuesOf, issuesReport, saveText } from './issues';
import { Library } from './library';

/** the workflows History offers Resume on - the helper's RESUME_ACTIONS */
const RESUMABLE = ['bookmarks', 'quick', 'custom', 'collections', 'collection'];

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
  /** a background run to open the progress window onto */
  readonly viewProgress = output<ActiveRun>();

  /**
   * The runs the helper is working on right now, pinned above the history.
   *
   * From the helper rather than from the history files: a file saying `running` might be a
   * run that was interrupted, and only the helper knows which ones really are going.
   */
  protected readonly activeRuns = this.jobs.activeRuns;

  /** how many issues a run reported, across every kind */
  protected issuesIn(run: RunHistory): number {
    return issueCount(issuesOf(run));
  }

  /**
   * Save every issue a run reported as one text file - available for every run, for as
   * long as its history file is there, not only in the window of a run just finished.
   */
  protected downloadIssues(run: RunHistory): void {
    saveText(
      issuesReport(issuesOf(run), `Issues from ${run.actionName} started ${this.when(run.started)}`),
      `run-issues-${this.stampOf(run)}`,
    );
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    // what is going now, for the pinned panel - not waited on: the history is read out of
    // the library, and is worth showing whether or not the helper answers
    void this.jobs.refreshActiveRuns();
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
        // only the helper can say a run is really going; a record can only say it started
        if (!this.jobs.isThisHelpers(run)) return 'Running on another helper';
        return this.activeRuns().some((active) => active.id === run.id)
          ? 'Running'
          : 'Running - not confirmed by the helper';
      case 'abandoned':
        return 'Abandoned';
      default:
        return 'Interrupted';
    }
  }

  /** set while a run's log is being read to be saved, so it cannot be asked for twice */
  protected readonly readingLog = signal('');

  /**
   * Save the account a run gave in its window - every line it printed - as a text file.
   *
   * Read from the run's history file when asked for, not with the history: a log can run to
   * thousands of lines, and a hundred of them would be a lot to read to draw a list.
   */
  protected async downloadLog(run: RunHistory): Promise<void> {
    const store = this.library.store();
    if (!store || this.readingLog()) return;
    this.readingLog.set(run.id);
    try {
      const record = JSON.parse((await store.read(`runs/${run.file}`)) ?? '{}') as {
        log?: string[];
        logTrimmed?: number;
      };
      const lines = Array.isArray(record.log) ? record.log : [];
      const head = [
        `# ${run.actionName}, started ${this.when(run.started)}`,
        `# ${this.outcome(run)}${run.finished ? `, ${this.when(run.finished)}` : ''}`,
      ];
      if (record.logTrimmed) {
        head.push(`# the first ${record.logTrimmed} lines were dropped to keep the file small`);
      }
      saveText([...head, '', ...lines].join('\n') + '\n', `run-log-${this.stampOf(run)}`);
    } catch {
      // the file is gone or unreadable; the button stays, and the list says what there was
    } finally {
      this.readingLog.set('');
    }
  }

  /** a run's start and id, for naming the files saved from it */
  private stampOf(run: RunHistory): string {
    const started = run.started ? new Date(run.started) : new Date();
    const day = Number.isNaN(started.getTime()) ? '' : started.toISOString().slice(0, 10);
    return `${day}-${run.id.slice(0, 8)}`;
  }

  /** a time of day, for when a paused run will be abandoned */
  protected timeOf(stamp: string | undefined): string {
    const parsed = stamp ? new Date(stamp) : null;
    return parsed && !Number.isNaN(parsed.getTime())
      ? parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : '';
  }

  /** whether starting the same run again is how to carry on, rather than Resume */
  protected startAgainInstead(run: RunHistory): boolean {
    return !RESUMABLE.includes(run.action);
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
    if (options['collectionWorks']) said.push('indexed and downloaded the works in them');
    if (options['subcollections']) said.push('with subcollections');
    if (options['parentCollections']) said.push('with parent collections');
    if (options['series']) said.push('all works from encountered series');
    if (options['images']) said.push('save images separately');
    return said;
  }

  /**
   * Whether a run can be picked up where it left off, or why not - the page's quick answer
   * for the button. The helper checks again, properly, when the run starts.
   */
  protected resumeProblem(run: RunHistory): string | null {
    if (!RESUMABLE.includes(run.action)) return null;
    if (run.status === 'success' || run.status === 'running') return null;
    if (run.action === 'collection' && !run.url) {
      return 'This run is from before collection runs saved their link - start it again from its button.';
    }
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
