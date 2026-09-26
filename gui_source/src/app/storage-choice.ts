import { Injectable, inject, signal } from '@angular/core';
import { APP_FOLDER_LABEL, DropboxSession, DropboxStorageRequest } from './dropbox';
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
  private readonly dropbox = inject(DropboxSession);

  readonly mode = signal<StorageMode>(safeGet(MODE_KEY) === 'dropbox' ? 'dropbox' : 'local');

  set(mode: StorageMode): void {
    this.mode.set(mode);
    safeSet(MODE_KEY, mode);
  }

  /**
   * The Dropbox library to hand the helper, or null for the folder on this computer.
   *
   * Only when Dropbox is the choice **and** there is a session to hand over - the page
   * offers no run otherwise. Reads signals, so anything computed from it follows a switch.
   */
  dropboxLibrary(): DropboxStorageRequest | null {
    return this.mode() === 'dropbox' ? this.dropbox.runStorage() : null;
  }

  /**
   * Where a run will save, when that is Dropbox - worded the way the helper words it once
   * the run starts, so the dialog does not change its mind halfway through. Null means the
   * folder on this computer, which only the helper can name.
   */
  dropboxFolderLabel(): string | null {
    return this.dropboxLibrary() ? APP_FOLDER_LABEL : null;
  }
}
