import { Injectable, signal } from '@angular/core';

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
  | 'custom';

/** what settings.ini says, so a run can show what it is working from */
export interface ServerSettings {
  /** which settings.ini is in force - not obvious, and worth being able to check */
  file: string;
  downloadFolder: string;
  extraWaitTime: number;
  /** how every downloaded file is named. fixed, not a setting - shown so it can be read */
  fileNamePattern: string;
  fileNameLength: number;
  /** the naming rule as an actual name, built through the same truncation */
  fileNameExample: string;
  maxRetries: number;
  maxTimeouts: number;
  debugLogging: boolean;
}

export interface ServerConfig {
  downloadFolder: string;
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
   * Whether to read AO3's listing at all, or work from what the index already holds.
   *
   * Only a custom run offers this. It defaults to true everywhere else: a run that quietly
   * skipped indexing would judge everything against however stale the index happened to be.
   */
  reindex: boolean;
}

/** what to do about downloaded files that carry no date, asked part way through a run */
export type UndatedChoice = 'stamp' | 'refresh' | 'skip';

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
  /** on a `question` event: which question is being asked, and how many works it concerns */
  count?: number;
  choices?: string[];
  seconds?: number;
  until?: string;
  error?: string;
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

  async start(request: StartRequest): Promise<string> {
    const response = await fetch(`${API_BASE}/api/jobs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error ?? `request failed (${response.status})`);
    return body.jobId as string;
  }

  /**
   * Answer a question the run has stopped to ask.
   *
   * The run is blocked waiting for this, so a failure here matters: it is surfaced rather
   * than swallowed, and the helper gives up on its own after a while so nothing hangs for
   * ever if this never arrives.
   */
  async answer(jobId: string, choice: UndatedChoice, date = ''): Promise<void> {
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
