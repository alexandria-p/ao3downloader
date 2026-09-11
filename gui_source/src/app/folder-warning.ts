import { Component, output, signal } from '@angular/core';
import { safeGet, safeSet } from './storage';

const DISMISSED_KEY = 'ao3.folderWarningDismissed';

/** whether the note has been turned off for this browser */
export function folderWarningDismissed(): boolean {
  return safeGet(DISMISSED_KEY) === 'true';
}

/**
 * Shown before the folder picker opens, because the one rule about file names cannot be
 * discovered from the page afterwards.
 *
 * A file is paired with its index entry by the work id at the *start* of its name. Get that
 * wrong and nothing breaks loudly - the folder loads, the works list fills in, and every
 * title quietly opens on AO3 instead of the local copy. Someone who brings files in from
 * elsewhere, or renames them, has no way to know that until they notice it, so this is said
 * once at the only moment it is actionable: before the folder is chosen.
 *
 * It can be turned off, which is why it is worth showing at all - a warning nobody can
 * silence is one people learn to click through.
 */
@Component({
  selector: 'app-folder-warning',
  templateUrl: './folder-warning.html',
  styleUrl: './folder-warning.css',
})
export class FolderWarning {
  /** the picker should open now */
  readonly confirmed = output<void>();
  /** backed out; nothing is remembered either way */
  readonly cancelled = output<void>();

  protected readonly dontAskAgain = signal(false);

  protected proceed(): void {
    // only written when they go through with it, so backing out never silences the note
    if (this.dontAskAgain()) safeSet(DISMISSED_KEY, 'true');
    this.confirmed.emit();
  }

  protected cancel(): void {
    this.cancelled.emit();
  }
}
