/**
 * localStorage, for the small per-browser conveniences that are allowed to go missing.
 *
 * Every access is wrapped, because reading or writing it *throws* in a private window or
 * with site data blocked - it does not merely come back empty. A remembered username or a
 * dismissed warning is never worth taking the page down for, so a failure here reads as
 * "nothing stored" and the caller carries on.
 *
 * What lives here stays in one browser and never reaches the helper. Anything that has to
 * survive being read back later belongs somewhere else - a directory handle, for one, is
 * structured data that localStorage cannot hold at all, which is what `folder-store.ts` is.
 */

export function safeGet(key: string): string {
  try {
    return localStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}

export function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private window or blocked site data
  }
}

export function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // nothing to clean up
  }
}
