import { Injectable, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';
import { safeGet, safeSet } from './storage';

/**
 * Whether a newer release of the app is out than the one this page belongs to.
 *
 * A deployment builds every copy of the page - the Windows app's and the GitHub Pages one -
 * with one version, written into `app-config.json` beside it, and publishes the Windows app
 * as a GitHub release tagged `v` and that version. So the page asks GitHub for the latest
 * release and compares. GitHub's api answers a page on any address, which is what lets a
 * page served from `localhost` ask at all.
 *
 * It asks once each time the page opens - never for a page with no version (a bundle built
 * on this computer, which is whatever its builder made it and has nothing to compare) - and
 * anything going wrong - offline, rate-limited, no release yet - is the same as not knowing.
 * A check for updates is never worth an error on the page.
 *
 * Two places say what it found. The banner at the top, which **Dismiss and do not ask me
 * again** hides for good in this browser; and the footer, which always does - `up to date
 * with latest`, or a quiet `update to latest` - so someone who dismissed the banner can
 * still see a newer version is out. That is why dismissing hides the banner and nothing
 * more: the check still runs, for the footer.
 */

export const DISMISSED_KEY = 'ao3.updateCheckDismissed';
/** the last update failure this browser has been shown and said OK to */
export const FAILURE_SEEN_KEY = 'ao3.updateFailureSeen';

/** a newer release, and where to get it */
export interface Release {
  version: string;
  /** the release's page on GitHub, which holds the zip */
  url: string;
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

@Injectable({ providedIn: 'root' })
export class UpdateCheck {
  /**
   * Where this page's version and repository come from. A constructor parameter with a
   * default rather than `inject()`, as `Jobs` does, so a test can say `new UpdateCheck(...)`.
   */
  constructor(private readonly helper: HelperConnection = new HelperConnection()) {}

  /** how GitHub is asked - replaced in tests, which have no network */
  fetcher: Fetch = (input, init) => fetch(input, init);

  /** the newer release, once one has been found */
  readonly newer = signal<Release | null>(null);
  /** whether GitHub has answered - only then can the footer say this is the latest */
  readonly checked = signal(false);
  /** set for good once the person asks for no banner - the footer still says */
  readonly dismissed = signal(safeGet(DISMISSED_KEY) === 'true');

  /** this page's own version, or '' for a build that has none */
  version(): string {
    return this.helper.settings().version;
  }

  /** where the latest release can always be found, whatever it is called */
  latestUrl(): string {
    const repo = this.helper.settings().releasesRepo;
    return repo ? `https://github.com/${repo}/releases/latest` : '';
  }

  async check(): Promise<void> {
    const current = this.version();
    const repo = this.helper.settings().releasesRepo;
    if (!current || !repo) return;
    try {
      const response = await this.fetcher(`https://api.github.com/repos/${repo}/releases/latest`, {
        headers: { Accept: 'application/vnd.github+json' },
      });
      if (!response.ok) return;
      const release = (await response.json()) as Record<string, unknown>;
      const version = String(release['tag_name'] ?? '').replace(/^v/, '');
      if (!versionParts(version)) return;
      const url = typeof release['html_url'] === 'string' ? release['html_url'] : this.latestUrl();
      if (isNewer(version, current)) this.newer.set({ version, url });
      this.checked.set(true);
    } catch {
      // offline, blocked or unreadable: nothing to say
    }
  }

  /** stop showing this browser the banner, for good. the footer still says */
  dismiss(): void {
    safeSet(DISMISSED_KEY, 'true');
    this.dismissed.set(true);
  }

  // region updating the Windows app from here

  /** whether this page's helper is the Windows app, which can update itself */
  readonly canUpdate = signal(false);
  /** how an update asked for from this page is going */
  readonly updating = signal<UpdateProgress>({ state: 'idle' });

  /** how long to keep waiting for the app to come back as the new version */
  waitMs = 180_000;
  /** how often to ask it whether it has */
  pollMs = 2_000;
  /** replaced in tests, which cannot reload */
  reload: () => void = () => location.reload();
  private sleep = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));

  /** what the helper's `/api/config` says about the app it belongs to */
  appStatus(app: AppStatus | undefined): void {
    this.canUpdate.set(!!app?.updatable);
    // the app coming back after an update that did not go through says so here - until it
    // has been seen: the app goes on reporting it until the next update, and a failure
    // already acknowledged is not worth a banner on every opening
    const error = app?.update?.state === 'failed' ? (app.update.error ?? 'the last update did not finish') : '';
    if (error && this.updating().state === 'idle' && safeGet(FAILURE_SEEN_KEY) !== error) {
      this.updating.set({ state: 'failed', error });
    }
  }

  /** the failure has been read: say no more about it, in this browser */
  acknowledgeFailure(): void {
    const progress = this.updating();
    if (progress.state === 'failed') safeSet(FAILURE_SEEN_KEY, progress.error);
    this.updating.set({ state: 'idle' });
  }

  /**
   * Ask the app to update itself, then wait for it to come back as the new version and
   * reload the page from it. The app closes while its files are swapped, so the helper not
   * answering for a while is expected, not a failure. If it comes back as the same version,
   * the swap did not go through - the app put its old files back - and it says why.
   */
  async updateNow(): Promise<void> {
    const from = this.version();
    this.updating.set({ state: 'starting' });
    let target = '';
    try {
      const response = await this.helper.call('/api/update', { method: 'POST' });
      const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
      if (response.status !== 202) {
        this.updating.set({ state: 'failed', error: String(body['error'] ?? `the app answered ${response.status}`) });
        return;
      }
      target = String(body['version'] ?? '');
    } catch {
      this.updating.set({ state: 'failed', error: 'the app on this computer is not answering' });
      return;
    }
    this.updating.set({ state: 'updating', version: target });

    const deadline = Date.now() + this.waitMs;
    let wentAway = false;
    while (Date.now() < deadline) {
      await this.sleep(this.pollMs);
      let app: AppStatus | undefined;
      try {
        const response = await this.helper.call('/api/config');
        if (!response.ok) continue;
        app = ((await response.json()) as { app?: AppStatus }).app;
      } catch {
        // closed, and being swapped: exactly what should happen
        wentAway = true;
        continue;
      }
      if (app?.version === target) {
        this.reload();
        return;
      }
      if (wentAway && app && app.version === from) {
        this.updating.set({
          state: 'failed',
          error: app.update?.error ?? `the app started again as ${from} - the update did not go through`,
        });
        return;
      }
    }
    this.updating.set({
      state: 'failed',
      error: 'the app has not come back yet. If its window is closed, start ao3downloader.exe again.',
    });
  }

  // endregion
}

/** the Windows app, as its helper describes itself */
export interface AppStatus {
  version: string;
  updatable: boolean;
  update?: { state: string; version?: string; error?: string };
}

export type UpdateProgress =
  | { state: 'idle' }
  | { state: 'starting' }
  | { state: 'updating'; version: string }
  | { state: 'failed'; error: string };

/** three whole numbers, or null for anything else */
export function versionParts(version: string): [number, number, number] | null {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version.trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

/**
 * Whether `candidate` is a later version than `current`, number by number - so 1.10.0 is
 * later than 1.9.0, which comparing them as text would get wrong. Anything unreadable is
 * never newer.
 */
export function isNewer(candidate: string, current: string): boolean {
  const a = versionParts(candidate);
  const b = versionParts(current);
  if (!a || !b) return false;
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] > b[i];
  }
  return false;
}
