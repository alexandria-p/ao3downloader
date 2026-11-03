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

import type { QuestionName } from './jobs';
import { safeGet, safeRemove, safeSet } from './storage';

export const BROWSER_NOTICE_KEY = 'ao3.browserNoticeSeen';
export const FOLDER_WARNING_KEY = 'ao3.folderWarningDismissed';
export const HIDE_WARNING_KEY = 'ao3.hideWarningOff';
export const SYNC_ACK_KEY = 'ao3.syncAcknowledged';
export const UPDATE_BANNER_KEY = 'ao3.updateCheckDismissed';
export const DEFAULT_FILETYPES_KEY = 'ao3.defaultFiletypes';
export const ANSWER_DEFAULTS_KEY = 'ao3.answerDefaults';
export const QUESTION_TIMEOUT_KEY = 'ao3.questionTimeoutMinutes';
export const AO3_TIME_ZONE_KEY = 'ao3.ao3TimeZone';

export type PromptArea = 'Your library' | 'Runs' | 'Updates';

export interface Prompt {
  key: string;
  area: PromptArea;
  name: string;
  description: string;
  /** what the prompt's own code writes when it is told not to ask again */
  dismissed: string;
  /**
   * What *Ask always* writes, for a prompt that otherwise turns itself off once shown. Unset
   * for the rest: they ask until someone ticks their box, so *Ask always* only removes the key.
   */
  always?: string;
}

/** grouped by `area`, in the order the tab lists them */
export const PROMPTS: Prompt[] = [
  {
    key: BROWSER_NOTICE_KEY,
    area: 'Your library',
    name: 'Saving to Dropbox, or to this device',
    description:
      'What each place to keep a library needs - and, in a browser that is not Chromium on a ' +
      'computer, the warning that it cannot save to a folder here. Shown once unless set to ' +
      'ask always.',
    dismissed: 'true',
    always: 'always',
  },
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
  if (!asks) safeSet(prompt.key, prompt.dismissed);
  else if (prompt.always) safeSet(prompt.key, prompt.always);
  else safeRemove(prompt.key);
}

/** whether *Ask always* was chosen for a prompt that would otherwise turn itself off */
export function askedAlways(prompt: Prompt): boolean {
  return !!prompt.always && safeGet(prompt.key) === prompt.always;
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

/**
 * The questions a run can stop to ask, with the answers each may default to - the same
 * lists as the helper's `strings.INI_ANSWER_CHOICES`, built-in default first. On a helper on
 * this computer they are settings.ini's; on a hosted copy, whose settings.ini the page cannot
 * edit, this browser keeps its own (`savedAnswerDefaults`), sent with every run and used to
 * fill a background run's up-front answers.
 */
export interface QuestionDefault {
  name: QuestionName;
  label: string;
  choices: { value: string; label: string }[];
}

export const QUESTION_DEFAULTS: QuestionDefault[] = [
  { name: 'undated', label: 'Files with no date in their name',
    choices: [{ value: 'skip', label: 'Leave them as they are' }, { value: 'refresh', label: 'Download them again' }] },
  { name: 'quick-floor', label: 'A quick scan with no earlier scan to measure back to',
    choices: [{ value: 'full', label: 'Read the whole listing' }, { value: 'since', label: 'Go back to when the index was last written' }] },
  { name: 'duplicates', label: 'Older copies beside the newest',
    choices: [{ value: 'leave', label: 'Leave them' }, { value: 'newest', label: 'Keep only the newest' }] },
  { name: 'fichub', label: 'Ask FicHub for works AO3 would not give',
    choices: [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }] },
  { name: 'fichub-outdated', label: 'Take an older FicHub copy of a format you have none of',
    choices: [{ value: 'yes', label: 'Yes' }, { value: 'no', label: 'No' }] },
  { name: 'overwrite-older', label: 'Let an overwriting run replace a copy newer than the one it writes',
    choices: [{ value: 'no', label: 'No' }, { value: 'yes', label: 'Yes' }] },
];

/** the built-in default of each question: what it took before any of this was a setting */
export const BUILT_IN_ANSWERS = Object.fromEntries(
  QUESTION_DEFAULTS.map((q) => [q.name, q.choices[0].value]),
) as Record<QuestionName, string>;
export const BUILT_IN_QUESTION_TIMEOUT = 30;

/** this browser's default answers, only those that are real answers to their question */
export function savedAnswerDefaults(): Partial<Record<QuestionName, string>> {
  const raw = safeGet(ANSWER_DEFAULTS_KEY);
  if (!raw) return {};
  try {
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return {};
    const kept: Partial<Record<QuestionName, string>> = {};
    for (const q of QUESTION_DEFAULTS) {
      if (q.choices.some((c) => c.value === saved[q.name])) kept[q.name] = saved[q.name];
    }
    return kept;
  } catch {
    return {};
  }
}

export function saveAnswerDefaults(answers: Partial<Record<QuestionName, string>> | null): void {
  if (answers === null || Object.keys(answers).length === 0) safeRemove(ANSWER_DEFAULTS_KEY);
  else safeSet(ANSWER_DEFAULTS_KEY, JSON.stringify(answers));
}

/** this browser's question timeout in minutes, or null for the helper's */
export function savedQuestionTimeout(): number | null {
  const raw = safeGet(QUESTION_TIMEOUT_KEY);
  if (raw === null || raw === '') return null;
  const minutes = Number(raw);
  return Number.isInteger(minutes) && minutes >= 0 ? minutes : null;
}

export function saveQuestionTimeout(minutes: number | null): void {
  if (minutes === null) safeRemove(QUESTION_TIMEOUT_KEY);
  else safeSet(QUESTION_TIMEOUT_KEY, String(minutes));
}

/** this browser's own time zone, as an IANA name - the default for the AO3 one */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** every zone this browser knows, for the setting's list; just the browser's and UTC without the api */
export function knownTimeZones(): string[] {
  const own = browserTimeZone();
  let zones: string[] = [];
  try {
    zones = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf?.('timeZone') ?? [];
  } catch {
    zones = [];
  }
  return [...new Set(['UTC', own, ...zones])].sort((a, b) => (a === 'UTC' ? -1 : b === 'UTC' ? 1 : a.localeCompare(b)));
}

/**
 * The zone AO3 shows this person's dates in - set in User settings, this browser's own until
 * then (nothing stored). Sent with every run, so the helper dates its floors and ceilings as
 * AO3 dates the fics they are compared with.
 */
export function savedAo3TimeZone(): string | null {
  const raw = safeGet(AO3_TIME_ZONE_KEY);
  return raw && /^[A-Za-z][A-Za-z0-9_+\-]*(\/[A-Za-z0-9_+\-]+)*$/.test(raw) ? raw : null;
}

export function ao3TimeZone(): string {
  return savedAo3TimeZone() ?? browserTimeZone();
}

export function saveAo3TimeZone(zone: string | null): void {
  if (zone === null) safeRemove(AO3_TIME_ZONE_KEY);
  else safeSet(AO3_TIME_ZONE_KEY, zone);
}
