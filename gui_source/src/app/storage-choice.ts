import { Injectable, signal } from '@angular/core';
import { safeGet, safeSet } from './storage';

/** where the library lives: a folder on this computer, or a folder in Dropbox */
export type StorageMode = 'local' | 'dropbox';

const MODE_KEY = 'ao3.storageMode';

/**
 * Which of the two the page is working with.
 *
 * Kept in localStorage because it is a per-browser convenience: losing it only means the
 * page opens on the local folder, and both choices stay remembered underneath - switching
 * back and forth never forgets a folder or signs anybody out.
 */
@Injectable({ providedIn: 'root' })
export class StorageChoice {
  readonly mode = signal<StorageMode>(safeGet(MODE_KEY) === 'dropbox' ? 'dropbox' : 'local');

  set(mode: StorageMode): void {
    this.mode.set(mode);
    safeSet(MODE_KEY, mode);
  }
}
