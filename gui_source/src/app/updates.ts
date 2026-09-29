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
 * It asks once each time the page opens, and never when:
 * - the page has no version - a bundle built on this computer, which is whatever its
 *   builder made it and has nothing to compare;
 * - the person has said not to ask again (kept in this browser);
 *
 * and anything going wrong - offline, rate-limited, no release yet - is the same as there
 * being nothing newer. A check for updates is never worth an error on the page.
 */

export const DISMISSED_KEY = 'ao3.updateCheckDismissed';

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
  /** set for good once the person asks not to be told again */
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
    if (!current || !repo || this.dismissed()) return;
    try {
      const response = await this.fetcher(`https://api.github.com/repos/${repo}/releases/latest`, {
        headers: { Accept: 'application/vnd.github+json' },
      });
      if (!response.ok) return;
      const release = (await response.json()) as Record<string, unknown>;
      const version = String(release['tag_name'] ?? '').replace(/^v/, '');
      const url = typeof release['html_url'] === 'string' ? release['html_url'] : this.latestUrl();
      if (isNewer(version, current)) this.newer.set({ version, url });
    } catch {
      // offline, blocked or unreadable: nothing to say
    }
  }

  /** stop telling this browser about new releases, for good */
  dismiss(): void {
    safeSet(DISMISSED_KEY, 'true');
    this.dismissed.set(true);
    this.newer.set(null);
  }
}

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
