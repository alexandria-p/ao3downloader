import { Component, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Jobs, RunHistory } from './jobs';

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

  protected readonly runs = signal<RunHistory[]>([]);
  protected readonly loading = signal(true);
  /** true when the helper could not be reached at all, which is not the same as no runs */
  protected readonly unavailable = signal(false);

  constructor() {
    void this.load();
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    const found = await this.jobs.loadRuns();
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
    if (options['series']) said.push('expand series links');
    if (options['images']) said.push('save images separately');
    return said;
  }

  protected workLink(id: string): string {
    return `https://archiveofourown.org/works/${id}`;
  }
}
