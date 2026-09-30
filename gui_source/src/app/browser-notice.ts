import { Component, output } from '@angular/core';
import { safeGet, safeSet } from './storage';
import { supportsDirectoryPicker } from './folder-store';

const SEEN_KEY = 'ao3.browserNoticeSeen';

/** whether this browser has already been told, once, what it needs */
export function browserNoticeSeen(): boolean {
  return safeGet(SEEN_KEY) === 'true';
}

/**
 * Said once, on the first visit: where a library can be kept, and what each way needs.
 *
 * A library in Dropbox needs nothing special - the page reaches it over Dropbox's own api,
 * in any browser on any device, and a background run can carry on with the page closed. A
 * folder on this device is the demanding one: the page writes into it itself, which takes the
 * File System Access API (Chromium on a computer - Firefox, Safari and mobile browsers do not
 * have it), and the page has to stay open for the whole run, because it is the page that does
 * the writing. A large library can take hours, and that is worth knowing before starting.
 *
 * Shown on the first visit rather than at the moment it bites, because the moment it bites
 * is after someone has picked a folder and started a run - too late to be useful. Dismissing
 * it is the whole interaction; there is no checkbox, because being told twice about a thing
 * that cannot change is worse than being told once.
 */
@Component({
  selector: 'app-browser-notice',
  templateUrl: './browser-notice.html',
  styleUrl: './browser-notice.css',
})
export class BrowserNotice {
  readonly dismissed = output<void>();

  /** whether this browser can save to a folder here, which turns the last line into a warning */
  protected readonly supported = supportsDirectoryPicker();

  protected dismiss(): void {
    safeSet(SEEN_KEY, 'true');
    this.dismissed.emit();
  }
}
