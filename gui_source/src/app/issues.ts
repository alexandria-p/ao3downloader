import { IndexGap, RunHistory, WorkFailure } from './jobs';

/** everything a run reported that needs a person's attention, by kind */
export interface RunIssues {
  /** where indexing broke off - a listing, a collection, or a fic's own page */
  indexGaps?: IndexGap[];
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
    (issues.indexGaps?.length ?? 0) +
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
    indexGaps: run.indexFailures ?? [],
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
    plural(issues.indexGaps?.length ?? 0, 'place indexing did not finish',
      'places indexing did not finish'),
    'what, where it stopped, how far it got',
    (issues.indexGaps ?? []).map((gap) => clean(describeGap(gap))),
  );
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
 * Exactly where indexing broke off, in words: which listing or collection, the pages read, the
 * page that failed, and how far back in date the listing got - the helper's
 * `describe_listing_gap`, said the same way so the History card and the issues file agree with
 * the run's own window.
 */
/** why something failed, in words: the recorded reason, then the error itself */
export function failureWords(failed: { reason?: string; status?: number; error?: string }): string {
  const error = failed.error ?? '';
  const words =
    failed.reason === 'maintenance' ? 'AO3 was down for maintenance'
    : failed.reason === 'status' && failed.status ? `AO3 answered with status ${failed.status}`
    : failed.reason === 'connection' ? 'AO3 could not be reached'
    : failed.reason === 'no-data' ? 'the page AO3 served had nothing on it that could be read'
    : '';
  if (!words) return error;
  return error && error !== words ? `${words} (${error})` : words;
}

export function describeGap(gap: IndexGap): string {
  if (gap.kind === 'work') {
    return `Work ${gap.id}: its page on AO3 could not be read, so it was not indexed - ${failureWords(gap)}.`;
  }
  const walk = gap.walk === 'bookmarked' ? ' sorted by date bookmarked'
    : gap.walk === 'updated' ? ' sorted by date updated' : '';
  const where = gap.kind === 'collection'
    ? `The ${gap.items ?? 'works'} of collection ${gap.collection}`
    : `Your bookmarks${walk}`;
  const total = gap.totalPages ? ` of ${gap.totalPages}` : '';
  const read = gap.lastPage
    ? `Pages ${gap.firstPage ?? 1} to ${gap.lastPage} were indexed (${gap.works ?? 0} works).`
    : 'No page was indexed before it.';
  const date = gap.sort === 'updated' ? gap.reachedUpdated : gap.reachedBookmarked;
  const kind = gap.sort === 'updated' ? 'updated' : 'bookmarked';
  const reached = gap.lastPage && date
    ? ` The last page read reached works ${kind} on ${date}; anything ${kind} before that was not reached.`
    : '';
  return `${where} stopped at page ${gap.failedPage}${total}: ${failureWords(gap)}. ${read}${reached}`;
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
