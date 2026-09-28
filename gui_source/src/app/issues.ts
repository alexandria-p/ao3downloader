import { RunHistory, WorkFailure } from './jobs';

/** everything a run reported that needs a person's attention, by kind */
export interface RunIssues {
  /** works that should have downloaded and did not */
  failures: WorkFailure[];
  /** new copies downloaded where the older copy could not be deleted, or was not confirmed */
  keptCopies: WorkFailure[];
  /** older copies marked for removal that are still there */
  notRemoved: WorkFailure[];
  /** bookmarks that were never works */
  skipped: WorkFailure[];
}

/** how many entries there are across every kind */
export function issueCount(issues: RunIssues): number {
  return (
    issues.failures.length +
    issues.keptCopies.length +
    issues.notRemoved.length +
    issues.skipped.length
  );
}

/**
 * A run's issues as its history file records them.
 *
 * The history file is written as the run goes, so this works for any run the History tab
 * lists - one that finished with the page shut, one from months ago, one that was
 * interrupted. An older copy still `pending` belongs to a run that never reached its cleanup
 * step, which is itself the reason it is still there.
 */
export function issuesOf(run: RunHistory): RunIssues {
  return {
    failures: run.failures ?? [],
    keptCopies: run.keptCopies ?? [],
    notRemoved: (run.removals ?? [])
      .filter((x) => x.status !== 'removed')
      .map((x) => ({
        id: x.id,
        link: '',
        file: x.file,
        old: x.keeping,
        error:
          x.error ?? (x.status === 'pending' ? 'the run ended before its cleanup step' : ''),
      })),
    skipped: run.skipped ?? [],
  };
}

/**
 * Every issue, as the one text file that gets saved.
 *
 * One file with a heading per kind rather than a file per list: the lists answer different
 * questions and stay apart on screen, but somebody saving them wants the whole account of
 * the run in one place. A kind with nothing in it gets no heading at all.
 */
export function issuesReport(issues: RunIssues, heading = 'Issues from this run', when = new Date()): string {
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const clean = (text: string | undefined) => (text ?? '').replace(/\s+/g, ' ');
  const lines = [`# ${heading}`, `# ${when.toISOString()}`, '# rows are tab separated'];
  const section = (title: string, columns: string, rows: string[]) => {
    if (!rows.length) return;
    lines.push('', `## ${title}`, `# ${columns}`, ...rows);
  };

  section(
    plural(issues.failures.length, 'work that could not be downloaded',
      'works that could not be downloaded'),
    'work id, link, reason',
    issues.failures.map((row) => [row.id ?? '', row.link ?? '', clean(row.error)].join('\t')),
  );
  section(
    plural(issues.keptCopies.length,
      'new copy downloaded that needs checking by hand',
      'new copies downloaded that need checking by hand'),
    'work id, link, new file, older copy still on disk (if any), reason',
    issues.keptCopies.map((row) =>
      [row.id ?? '', row.link ?? '', row.file ?? '', row.old ?? '', clean(row.error)].join('\t'),
    ),
  );
  section(
    plural(issues.notRemoved.length,
      'older copy marked for removal that is still there',
      'older copies marked for removal that are still there'),
    'work id, older copy, newest copy (kept), reason',
    issues.notRemoved.map((row) =>
      [row.id ?? '', row.file ?? '', row.old ?? '', clean(row.error)].join('\t'),
    ),
  );
  section(
    plural(issues.skipped.length, 'bookmark that is not a work', 'bookmarks that are not works'),
    'work or series id, link, reason',
    issues.skipped.map((row) => [row.id ?? '', row.link ?? '', clean(row.error)].join('\t')),
  );
  return lines.join('\n') + '\n';
}

/**
 * Hand the text over as a file the browser saves.
 *
 * Done in the page rather than by the helper: it is a few lines the browser can save
 * directly, so it needs neither a round trip nor a second thing that writes to disk.
 */
export function saveText(text: string, name: string): void {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name}.txt`;
  link.click();
  // the save has its own copy once started, so the handle can go
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
