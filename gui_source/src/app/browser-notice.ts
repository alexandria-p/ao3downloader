import { Component, output } from '@angular/core';
import { safeGet, safeSet } from './storage';
import { supportsDirectoryPicker } from './folder-store';

const SEEN_KEY = 'ao3.browserNoticeSeen';

/** whether this browser has already been told, once, what it needs */
export function browserNoticeSeen(): boolean {
  return safeGet(SEEN_KEY) === 'true';
}

/**
 * Said once, on the first visit: this needs a Chromium browser.
 *
 * Everything is written straight into the folder you pick - the works, the index, the
 * images, the run history - and the only way a page can write to a folder you chose is the
 * File System Access API, which Chromium has and Firefox and Safari do not. There is no
 * fallback that writes: a page without it can be handed files to read, but cannot put one
 * back.
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

  /** whether this browser can actually do it, which changes the note from a caveat to a wall */
  protected readonly supported = supportsDirectoryPicker();

  protected dismiss(): void {
    safeSet(SEEN_KEY, 'true');
    this.dismissed.emit();
  }
}
