/**
 * Debug mode itself: this browser's alone (`DEBUG_MODE_KEY`), turned on and off in User
 * settings. Apart from debug.ts so the library can ask about it without importing the mock.
 */

import { Injectable, signal } from '@angular/core';
import { safeGet, safeRemove, safeSet } from './storage';

export const DEBUG_MODE_KEY = 'ao3.debugMode';

@Injectable({ providedIn: 'root' })
export class DebugMode {
  readonly on = signal(safeGet(DEBUG_MODE_KEY) === 'on');

  set(on: boolean): void {
    this.on.set(on);
    if (on) safeSet(DEBUG_MODE_KEY, 'on');
    else safeRemove(DEBUG_MODE_KEY);
  }
}
