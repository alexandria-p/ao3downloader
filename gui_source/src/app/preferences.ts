/**
 * What this browser remembers about how the page should behave: every prompt that offers
 * "don't ask again", and the file types a run starts with ticked.
 *
 * One list, so the User settings tab can offer every prompt - including those this browser
 * has never been shown - and each prompt's own code reads the same key the tab writes. A
 * prompt added with a "don't ask again" box belongs in `PROMPTS`, or the tab cannot undo it.
 *
 * Kept in localStorage through `storage.ts`, like every per-browser convenience: losing it
 * only means a prompt is shown again, or the helper's own default file types are ticked.
 */

import { safeGet, safeRemove, safeSet } from './storage';

export const FOLDER_WARNING_KEY = 'ao3.folderWarningDismissed';
export const HIDE_WARNING_KEY = 'ao3.hideWarningOff';
export const SYNC_ACK_KEY = 'ao3.syncAcknowledged';
export const UPDATE_BANNER_KEY = 'ao3.updateCheckDismissed';
export const DEFAULT_FILETYPES_KEY = 'ao3.defaultFiletypes';

export type PromptArea = 'Your library' | 'Runs' | 'Updates';

export interface Prompt {
  key: string;
  area: PromptArea;
  name: string;
  description: string;
  /** what the prompt's own code writes when it is told not to ask again */
  dismissed: string;
}

/** grouped by `area`, in the order the tab lists them */
export const PROMPTS: Prompt[] = [
  {
    key: FOLDER_WARNING_KEY,
    area: 'Your library',
    name: 'Before you choose a folder',
    description:
      'How downloaded files are matched to your index by their file names, shown before the ' +
      'folder picker opens.',
    dismissed: 'true',
  },
  {
    key: HIDE_WARNING_KEY,
    area: 'Your library',
    name: 'Before hiding a work',
    description: 'What hiding does, and how to bring a hidden work back.',
    dismissed: 'off',
  },
  {
    key: SYNC_ACK_KEY,
    area: 'Runs',
    name: 'What a quick scan will not pick up',
    description:
      'The note you tick before a quick scan (and the combined run) starts, saying what it ' +
      'does not check.',
    dismissed: 'true',
  },
  {
    key: UPDATE_BANNER_KEY,
    area: 'Updates',
    name: 'Banner when a newer version is out',
    description:
      'The banner at the top of the page. With it off, the footer still says when there is ' +
      'a newer version.',
    dismissed: 'true',
  },
];

export const PROMPT_AREAS: PromptArea[] = ['Your library', 'Runs', 'Updates'];

/** whether the prompt is still shown - true until someone said not to ask again */
export function promptAsks(prompt: Prompt): boolean {
  return safeGet(prompt.key) !== prompt.dismissed;
}

export function setPromptAsks(prompt: Prompt, asks: boolean): void {
  if (asks) safeRemove(prompt.key);
  else safeSet(prompt.key, prompt.dismissed);
}

/** the file types this browser starts every run with ticked, or null for the helper's own */
export function savedDefaultFiletypes(): string[] | null {
  const raw = safeGet(DEFAULT_FILETYPES_KEY);
  if (!raw) return null;
  try {
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list.filter((x): x is string => typeof x === 'string') : null;
  } catch {
    return null;
  }
}

export function saveDefaultFiletypes(filetypes: string[] | null): void {
  if (filetypes === null) safeRemove(DEFAULT_FILETYPES_KEY);
  else safeSet(DEFAULT_FILETYPES_KEY, JSON.stringify(filetypes));
}

/**
 * What a run starts with ticked: this browser's choice when there is one, otherwise the
 * helper's defaults - always with the forced types, and never one the helper does not offer.
 */
export function startingFiletypes(config: { filetypes: string[]; forced: string[]; defaults?: string[] }): string[] {
  const saved = savedDefaultFiletypes();
  const chosen = saved ?? config.defaults ?? config.forced;
  const offered = chosen.filter((x) => config.filetypes.includes(x));
  return [...config.forced, ...offered.filter((x) => !config.forced.includes(x))];
}
