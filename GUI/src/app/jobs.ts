import { Injectable, signal } from '@angular/core';

/**
 * Talks to the local helper (ao3downloader.server) that actually performs downloads.
 *
 * The browser cannot do this work itself: ao3 sends no CORS headers, a page cannot hold an
 * ao3 login session, and the update scan has to read ebook files on disk. So the helper runs
 * the same python the console menu runs, and this service drives it.
 */

export type JobAction = 'bookmarks' | 'update';

export interface ServerConfig {
  downloadFolder: string;
  username: string;
  filetypes: string[];
  /** always produced, shown ticked and locked in the ui */
  forced: string[];
}

export interface JobEvent {
  type: string;
  text?: string;
  page?: number;
  total?: number;
  works?: number;
  done?: number;
  title?: string;
  phase?: string;
  seconds?: number;
  until?: string;
  error?: string;
  folder?: string;
  action?: string;
}

export interface StartRequest {
  action: JobAction;
  filetypes: string[];
  username: string;
  password: string;
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
