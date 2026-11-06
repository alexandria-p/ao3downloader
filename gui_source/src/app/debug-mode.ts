/**
 * Debug mode itself: this browser's alone (`DEBUG_MODE_KEY`), turned on and off in User
 * settings. Apart from debug.ts so the library can ask about it without importing the mock.
 *
 * **On a downloaded app it is only offered when settings.ini allows it** (`EnableDebugTools`,
 * which the helper reports as `settings.debugTools`): someone using the app never meets it,
 * and whoever works on it turns it on in the file. The hosted copy is its owner's alone, so it
 * is always offered there. Where it is not allowed it is off, whatever this browser saved.
 */

import { Injectable, computed, inject, signal } from '@angular/core';
import { HelperConnection } from './helper-connection';
import { Jobs } from './jobs';
import { safeGet, safeRemove, safeSet } from './storage';

export const DEBUG_MODE_KEY = 'ao3.debugMode';

@Injectable({ providedIn: 'root' })
export class DebugMode {
  private readonly helper = inject(HelperConnection);
  private readonly jobs = inject(Jobs);
  /** what this browser chose */
  readonly chosen = signal(safeGet(DEBUG_MODE_KEY) === 'on');
  /** whether it may be offered here: always on the hosted copy, on an app only by settings.ini */
  readonly allowed = computed(() => !this.helper.isLocal() || !!this.jobs.config()?.settings?.debugTools);
  /** in force: chosen, and allowed */
  readonly on = computed(() => this.chosen() && this.allowed());

  set(on: boolean): void {
    this.chosen.set(on);
    if (on) safeSet(DEBUG_MODE_KEY, 'on');
    else safeRemove(DEBUG_MODE_KEY);
  }
}
