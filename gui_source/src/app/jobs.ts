import { Injectable, signal } from '@angular/core';
import { LibraryStore, StorageRequest, answerStorage, readRunHistory } from './library-store';

/**
 * Talks to the local helper (ao3downloader.server) that actually performs downloads.
 *
 * The browser cannot do this work itself: ao3 sends no CORS headers, a page cannot hold an
 * ao3 login session, and the update scan has to read ebook files on disk. So the helper runs
 * the same python the console menu runs, and this service drives it.
 */

export type JobAction =
  | 'bookmarks'
  | 'update'
  | 'collections'
  | 'collection'
  /** newest bookmarks only, stopping at the first one already indexed */
  | 'new'
  /** new bookmarks, then the unfinished ones, then the formats still missing */
  | 'sync'
  /** one fic, by link or work number */
  | 'work'
  /** the full scan with its parts made optional */
  | 'custom'
  /** a full scan that stops at the works ao3 has not touched since the last run */
  | 'quick';

/** what settings.ini says, so a run can show what it is working from */
export interface ServerSettings {
  /** which settings.ini is in force - not obvious, and worth being able to check */
  file: string;
  extraWaitTime: number;
  /** how every downloaded file is named. fixed, not a setting - shown so it can be read */
  fileNamePattern: string;
  fileNameLength: number;
  /** the naming rule as an actual name, built through the same truncation */
  fileNameExample: string;
  maxRetries: number;
  maxTimeouts: number;
  debugLogging: boolean;
  /**
   * Whether settings.ini turns on the debug panel in the download window.
   *
   * For working on the app rather than for using it: skipping a step really does skip it,
   * so this stays off unless somebody has deliberately asked for it.
   */
  debugTools?: boolean;
}

export interface ServerConfig {
  username: string;
  filetypes: string[];
  /** ticked and locked: produced whatever the request says */
  forced: string[];
  /** ticked when the dialog opens, but free to untick */
  defaults: string[];
  settings?: ServerSettings;
}

/** the questions the console menu asks after the file types */
export interface JobOptions {
  /** page to begin on; 1 is the start of the listing */
  start: number;
  /** page to stop on; 0 means every page */
  pages: number;
  series: boolean;
  images: boolean;
  workdates: boolean;
  /**
   * Fetch every requested format again, whether or not the copy held is behind.
   *
   * The answer to a file that is damaged or truncated - something no version check can
   * see, because the name and the date are both right and only the bytes are wrong.
   */
  overwrite: boolean;
  /**
   * Whether to read AO3's listing at all, or work from what the index already holds.
   *
   * Only a custom run offers this. It defaults to true everywhere else: a run that quietly
   * skipped indexing would judge everything against however stale the index happened to be.
   */
  reindex: boolean;
  /**
   * Whether to cover a date window instead of a slice of the listing.
   *
   * The two are alternatives rather than settings that combine, so `dates` decides which of
   * `start`/`pages` and `dateFrom`/`dateTo` the helper reads at all.
   */
  dates: boolean;
  /** inclusive ends of that window, YYYY-MM-DD; empty means no limit at that end */
  dateFrom: string;
  dateTo: string;
  /**
   * A quick scan's chosen floor: the id of an earlier completed scan to measure back to.
   *
   * Only the id is sent. The helper reads the date off that run's own record and refuses
   * one that is not a valid floor, so a request can never invent a date.
   */
  floorRun: string;
}

/** what to do about downloaded files that carry no date, asked part way through a run */
export type UndatedChoice = 'stamp' | 'refresh' | 'skip';

/**
 * How far back a quick scan should reach when no run qualifies as a floor.
 *
 * 'since' measures back to the day the index was last written; 'full' reads the whole
 * listing, which is what it does when there is nothing to go on at all.
 */
export type QuickFloorChoice = 'since' | 'full';

/** anything a run may be answered with; the run only reads its own question's replies */
export type AnswerChoice = UndatedChoice | QuickFloorChoice;

/**
 * Where a step has got to.
 *
 * 'skipped' is not 'failed'. A run with no unfinished fics skips that step and nothing has
 * gone wrong, so the two must not look alike.
 */
export type StepStatus = 'waiting' | 'running' | 'done' | 'skipped' | 'failed';

/** one step of the checklist a run publishes before it starts */
export interface RunStep {
  id: string;
  label: string;
  status: StepStatus;
}

/**
 * How a past run ended.
 *
 * `running` is also what an **interrupted** run is left as: the record is written when a
 * run starts, and a run killed mid-flight never gets to write its ending.
 */
export type RunStatus = 'running' | 'success' | 'failed' | 'stopped';

/** something a run stopped to ask, what was answered, and what came of it */
export interface RunChoice {
  at: string;
  question: string;
  choice: string;
  date?: string;
  /** how many works the question was about */
  count?: number;
  /** how many files those works held between them - a work in two formats is two files */
  files?: number;
  /** the work numbers the question was about */
  works?: string[];
  /** the files given a date, when that was the answer */
  renamed?: { id: string; from: string; to: string }[];
}

/** one past run, as the helper wrote it down */
export interface RunHistory {
  file: string;
  id: string;
  action: string;
  actionName: string;
  started: string;
  finished: string | null;
  status: RunStatus;
  filetypes: string[];
  options: Record<string, unknown>;
  reindexed: string[];
  downloaded: string[];
  updated: string[];
  choices: RunChoice[];
  failures: WorkFailure[];
  skipped: WorkFailure[];
  /** new copies downloaded while the old copy could not be deleted - absent on older runs */
  keptCopies?: WorkFailure[];
  error: string;
}

/**
 * Whether a json file read out of the downloads folder is one of these run records.
 *
 * They live in a `runs` subfolder, but a folder read through the File System Access API
 * arrives **flat** - the paths are gone - so the only thing left to tell them apart by is
 * their shape. Without this a run record is rendered as a bookmark: `flattenRecord` hands
 * back anything carrying an `id`, and a run record has one.
 *
 * Three fields rather than one, because `id` alone is what caused the problem and `action`
 * alone is a word a fic could plausibly use. No work or collection record carries all of
 * `action`, `status` and `started`.
 */
export function isRunRecord(parsed: unknown): boolean {
  if (!parsed || typeof parsed !== 'object') return false;
  const record = parsed as Record<string, unknown>;
  return (
    typeof record['action'] === 'string' &&
    typeof record['status'] === 'string' &&
    typeof record['started'] === 'string'
  );
}

/** a work the run could not download */
export interface WorkFailure {
  /** the ao3 work number, when the link had one in it */
  id: string | null;
  link: string;
  error: string;
  /**
   * What the listing called it, when there is anything to call it.
   *
   * Only skipped bookmarks carry this. A bookmark of a deleted work has no number and no
   * link to identify it by, so without the title there would be nothing on the row at all.
   */
  title?: string;
  /** a kept copy only: the name of the file that was just downloaded */
  file?: string;
  /** a kept copy only: the name of the older copy still on disk */
  old?: string;
}

export interface JobEvent {
  type: string;
  text?: string;
  /** on a `page` event: position within the slice being fetched, which drives the bar */
  page?: number;
  total?: number;
  /** on a `page` event: the same page's actual number in the listing, for the wording */
  listingPage?: number;
  listingTotal?: number;
  /**
   * On a `page` event: this page is about to be fetched rather than finished.
   *
   * The fetch is the slow part of indexing, so the run says what it is asking for before
   * it asks - a caption written only once a page is in describes the wrong page for as
   * long as the next one takes to arrive.
   */
  fetching?: boolean;
  works?: number;
  done?: number;
  title?: string;
  /** which format is being fetched for the work named in `title` */
  filetype?: string;
  phase?: string;
  /** which stage of the run has just started, on a `phase` event */
  name?: string;
  /** who the helper signed in as, on an `authenticated` event */
  username?: string;
  /** on a `refresh` event: works ao3 has updated since they were saved */
  stale?: number;
  /** on a `refresh` event: works saved before file names carried a date */
  undated?: number;
  /** on a `refresh` event: existing files this run gave a date to, by renaming them */
  stamped?: number;
  /** on a `failures` event: the works that would not download */
  failures?: WorkFailure[];
  /** on a `skipped` event: bookmarks that were never works, and why each one was not */
  skipped?: WorkFailure[];
  /** on a `keptCopies` event: new copies downloaded while the old copy could not be deleted */
  keptCopies?: WorkFailure[];
  /** on a `steps` event: the checklist this run intends to work through */
  steps?: { id: string; label: string }[];
  /** on a `step` event: which step changed, and to what */
  id?: string;
  status?: StepStatus;
  /** on a `question` event: which question is being asked, and how many works it concerns */
  count?: number;
  choices?: string[];
  /** on a `question` event: the date the question is offering, where it has one */
  date?: string;
  seconds?: number;
  until?: string;
  error?: string;
  /**
   * On a `failed` event: whether AO3 stopped recognising the login mid-run.
   *
   * Flagged by the helper rather than left to be guessed from the error text - it is not a
   * crash, and there is a specific thing to do about it.
   */
  sessionExpired?: boolean;
  folder?: string;
  action?: string;
  filetypes?: string[];
  options?: JobOptions;
  cancelled?: boolean;
}

export interface StartRequest {
  action: JobAction;
  filetypes: string[];
  options: JobOptions;
  username: string;
  password: string;
  /** the collection to index, for the one action that works from a link */
  url?: string;
}

const API_BASE = 'http://127.0.0.1:4400';

@Injectable({ providedIn: 'root' })
export class Jobs {
  /** null until checked; false means the helper is not running */
  readonly available = signal<boolean | null>(null);
  readonly config = signal<ServerConfig | null>(null);

  async loadConfig(): Promise<ServerConfig | null> {
    try {
      const response = await fetch(`${API_BASE}/api/config`);
      if (!response.ok) throw new Error(String(response.status));
      const config = (await response.json()) as ServerConfig;
      this.config.set(config);
      this.available.set(true);
      return config;
    } catch {
      this.available.set(false);
      return null;
    }
  }

  /**
   * Every run the helper has written down, newest first.
   *
   * Returns null rather than throwing when the helper is not there: the history page is
   * something to read, and a page that shows an error where a list should be is less
   * useful than one that says the helper is not running.
   */
  /**
   * The earlier runs a quick scan may be told to measure back to, newest first.
   *
   * Asked of the helper rather than filtered here, so the rule for what counts as a floor
   * lives in one place - the same place that enforces it when the run starts.
   */
  async loadFloorRuns(store: LibraryStore | null): Promise<RunHistory[] | null> {
    if (!store) return null;
    try {
      // the history is read out of the library here; which of it qualifies is the helper's
      // rule, so it is asked rather than decided twice
      const response = await fetch(`${API_BASE}/api/runs/floors`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ runs: await readRunHistory(store) }),
      });
      if (!response.ok) throw new Error(String(response.status));
      return ((await response.json()) as { runs: RunHistory[] }).runs ?? [];
    } catch {
      return null;
    }
  }

  /**
   * Every run written down in the library, newest first - read straight out of it, so the
   * history is there with the helper stopped. Null when no library is open.
   */
  async loadRuns(store: LibraryStore | null): Promise<RunHistory[] | null> {
    if (!store) return null;
    try {
      return await readRunHistory(store);
    } catch {
      return null;
    }
  }

  /**
   * Do one thing the helper asked of the library, and tell it how that went.
   *
   * A write's bytes are collected from the helper only now, as a stream, so a large epub
   * goes from the helper to the folder without being held whole. An answer that cannot be
   * delivered is left for the helper to notice - it gives up on a page it cannot hear from.
   */
  async answerStorage(jobId: string, request: StorageRequest, store: LibraryStore): Promise<void> {
    const answer = await answerStorage(store, request, async () => {
      const response = await fetch(`${API_BASE}/api/jobs/${jobId}/blobs/${request.id}`);
      if (!response.ok) throw new Error(`could not collect the file (${response.status})`);
      return response;
    });
    try {
      await fetch(`${API_BASE}/api/jobs/${jobId}/storage/${request.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(answer),
      });
    } catch {
      // the helper has gone; the stream closing says so
    }
  }

  /**
   * Ask a run to abandon the step it is on.
   *
   * A debug tool. Throws on refusal for the same reason pausing does: a skip that silently
   * did not happen would leave the page believing the run had moved on when it had not.
   */
  async skipStep(jobId: string): Promise<void> {
    const response = await fetch(`${API_BASE}/api/jobs/${jobId}/skip`, { method: 'POST' });
    if (!response.ok) throw new Error('could not skip the current step');
  }

  async start(request: StartRequest): Promise<string> {
    const response = await fetch(`${API_BASE}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    const answer = await response.json();
    if (!response.ok) throw new Error(answer?.error ?? `request failed (${response.status})`);
    return answer.jobId as string;
  }

  /**
   * Answer a question the run has stopped to ask.
   *
   * The run is blocked waiting for this, so a failure here matters: it is surfaced rather
   * than swallowed, and the helper gives up on its own after a while so nothing hangs for
   * ever if this never arrives.
   */
  async answer(jobId: string, choice: AnswerChoice, date = ''): Promise<void> {
    const response = await fetch(`${API_BASE}/api/jobs/${jobId}/answer`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ choice, date }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.error ?? `could not answer (${response.status})`);
    }
  }

  /**
   * Ask the helper to stop. The run unwinds at its next checkpoint, keeping whatever it
   * has already written, so this is safe rather than destructive.
   */
  async cancel(jobId: string): Promise<void> {
    try {
      await fetch(`${API_BASE}/api/jobs/${jobId}/cancel`, { method: 'POST' });
    } catch {
      // the helper may already have stopped; the stream closing will tell us
    }
  }

  /**
   * Pause or resume a run.
   *
   * The helper only sets a flag, so this returns straight away - the run acts on it at its
   * next safe point, which is before its next request. Throwing on a failure matters here:
   * a pause that silently did not happen would leave the page saying the run is paused
   * while it carries on downloading.
   */
  async setPaused(jobId: string, paused: boolean): Promise<void> {
    const what = paused ? 'pause' : 'resume';
    const response = await fetch(`${API_BASE}/api/jobs/${jobId}/${what}`, { method: 'POST' });
    if (response.ok) return;

    // a 404 here is nearly always a helper older than this page rather than a missing job.
    // the page is reloaded from disk on every refresh; the helper is a long-running process
    // that keeps whatever code it started with, so an app left running across an update
    // serves the new page from the old helper - which has no pause route at all
    if (response.status === 404) {
      throw new Error(
        `could not ${what} the run - the helper may be an older version that does not ` +
          'support pausing. Restart the app to update it.',
      );
    }
    throw new Error(`could not ${what} the run`);
  }

  /**
   * Subscribe to a job's progress. Returns a function that closes the stream.
   * The password is never part of this - it went out with the start request and is not stored.
   */
  stream(jobId: string, onEvent: (event: JobEvent) => void, onError: () => void): () => void {
    const source = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);

    source.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data) as JobEvent);
      } catch {
        // a malformed frame is not worth tearing the run down for
      }
    };
    source.onerror = () => {
      // the helper closes the stream when the job ends, which surfaces here too
      source.close();
      onError();
    };

    return () => source.close();
  }
}
