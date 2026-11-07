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

import type { DefaultName, Scenario } from './jobs';
import { safeGet, safeRemove, safeSet } from './storage';

export const BROWSER_NOTICE_KEY = 'ao3.browserNoticeSeen';
export const FOLDER_WARNING_KEY = 'ao3.folderWarningDismissed';
export const HIDE_WARNING_KEY = 'ao3.hideWarningOff';
export const SYNC_ACK_KEY = 'ao3.syncAcknowledged';
/** 'off': the import window no longer opens by itself when a library has unindexed works */
export const IMPORT_OFFER_KEY = 'ao3.importOfferOff';
export const UPDATE_BANNER_KEY = 'ao3.updateCheckDismissed';
export const DEFAULT_FILETYPES_KEY = 'ao3.defaultFiletypes';
export const ANSWER_DEFAULTS_KEY = 'ao3.answerDefaults';
export const QUESTION_TIMEOUT_KEY = 'ao3.questionTimeoutMinutes';
export const GUESSED_DATE_TIMEOUT_KEY = 'ao3.guessedDateTimeoutMinutes';
export const BUILT_IN_GUESSED_DATE_TIMEOUT = 1;
/** answers you chose to always use for a case of a file without the app's own date */
export const ALWAYS_ANSWERS_KEY = 'ao3.alwaysAnswers';
export const AO3_TIME_ZONE_KEY = 'ao3.ao3TimeZone';

export type PromptArea = 'File imports' | 'Your library' | 'Runs' | 'Updates';

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
  /**
   * false keeps it off the User settings tab - still tracked, saved, and put back by Reset to
   * defaults, just not offered as a choice there
   */
  listed?: boolean;
  /** what its two choices are called on the tab, when 'Ask always' / 'Do not ask again' do not fit */
  labels?: { ask: string; skip: string };
}

/** the words for a prompt's two choices on the User settings tab */
export function promptLabels(prompt: Prompt): { ask: string; skip: string } {
  return prompt.labels ?? { ask: 'Ask always', skip: 'Do not ask again' };
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
    listed: false,
  },
  {
    key: FOLDER_WARNING_KEY,
    area: 'File imports',
    name: 'When loading local files on your machine',
    description: 'Tell the user how the application finds and identifies files.',
    dismissed: 'true',
  },
  {
    key: IMPORT_OFFER_KEY,
    area: 'File imports',
    name: "Show 'resolve issues' window if a problem was found with your file import",
    description:
      'If works are missing an index, files with no date in their name or there are duplicates.',
    dismissed: 'off',
  },
  {
    key: HIDE_WARNING_KEY,
    area: 'Your library',
    name: 'Hide a work',
    description: 'Tell me what hiding does, and how to undo it for a work.',
    dismissed: 'off',
  },
  {
    key: SYNC_ACK_KEY,
    area: 'Runs',
    name: 'Quick Scan acknowledgement',
    description:
      'A warning that a Quick Scan will not restore any files missing from earlier runs due ' +
      'to an incomplete or damaged index - for example, if an earlier run was interrupted, or ' +
      'files were deleted.',
    dismissed: 'true',
  },
  {
    key: UPDATE_BANNER_KEY,
    area: 'Updates',
    name: 'New app version alert banner',
    description:
      'The banner at the top of the page. With it off, the footer still says when there is ' +
      'a newer version.',
    dismissed: 'true',
    labels: { ask: 'Show always', skip: "Don't show" },
  },
];

export const PROMPT_AREAS: PromptArea[] = ['File imports', 'Your library', 'Runs', 'Updates'];

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
  name: DefaultName;
  label: string;
  choices: { value: string; label: string }[];
}

/** the six cases of a file without the app's own date, as User settings words them */
export const SCENARIO_LABELS: { name: Scenario; label: string }[] = [
  { name: 'ao3-older', label: "From AO3: your file's date is guessed, and looks older than AO3's version" },
  { name: 'ao3-newer', label: "From AO3: your file's date is guessed, and looks the same as AO3's version or newer" },
  { name: 'ao3-unknown', label: "From AO3: no date can be read from your file's name" },
  { name: 'fichub-older', label: "From FicHub: your file's date is guessed, and looks older than FicHub's copy" },
  { name: 'fichub-newer', label: "From FicHub: your file's date is guessed, and looks the same as FicHub's copy or newer" },
  { name: 'fichub-unknown', label: "From FicHub: no date can be read from your file's name" },
];

const KEEP_OR_REPLACE = [{ value: 'no', label: 'Keep my file' }, { value: 'yes', label: 'Replace it' }];

export const QUESTION_DEFAULTS: QuestionDefault[] = [
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
  ...SCENARIO_LABELS.map(({ name, label }) => ({ name, label, choices: KEEP_OR_REPLACE })),
];

/** the built-in default of each question: what it took before any of this was a setting */
export const BUILT_IN_ANSWERS = Object.fromEntries(
  QUESTION_DEFAULTS.map((q) => [q.name, q.choices[0].value]),
) as Record<DefaultName, string>;
export const BUILT_IN_QUESTION_TIMEOUT = 30;

/** this browser's default answers, only those that are real answers to their question */
export function savedAnswerDefaults(): Partial<Record<DefaultName, string>> {
  const raw = safeGet(ANSWER_DEFAULTS_KEY);
  if (!raw) return {};
  try {
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return {};
    const kept: Partial<Record<DefaultName, string>> = {};
    for (const q of QUESTION_DEFAULTS) {
      if (q.choices.some((c) => c.value === saved[q.name])) kept[q.name] = saved[q.name];
    }
    return kept;
  } catch {
    return {};
  }
}

export function saveAnswerDefaults(answers: Partial<Record<DefaultName, string>> | null): void {
  if (answers === null || Object.keys(answers).length === 0) safeRemove(ANSWER_DEFAULTS_KEY);
  else safeSet(ANSWER_DEFAULTS_KEY, JSON.stringify(answers));
}

/** the answers this browser always uses, by case - only real ones */
export function savedAlwaysAnswers(): Partial<Record<Scenario, 'yes' | 'no'>> {
  const raw = safeGet(ALWAYS_ANSWERS_KEY);
  if (!raw) return {};
  try {
    const saved = JSON.parse(raw);
    if (!saved || typeof saved !== 'object') return {};
    const kept: Partial<Record<Scenario, 'yes' | 'no'>> = {};
    for (const { name } of SCENARIO_LABELS) {
      if (saved[name] === 'yes' || saved[name] === 'no') kept[name] = saved[name];
    }
    return kept;
  } catch {
    return {};
  }
}

/** always use `choice` for a case from now on, or (null) ask again every time */
export function saveAlwaysAnswer(scenario: Scenario, choice: 'yes' | 'no' | null): void {
  const answers = savedAlwaysAnswers();
  if (choice === null) delete answers[scenario];
  else answers[scenario] = choice;
  if (Object.keys(answers).length === 0) safeRemove(ALWAYS_ANSWERS_KEY);
  else safeSet(ALWAYS_ANSWERS_KEY, JSON.stringify(answers));
}

/** this browser's question timeout in minutes, or null for the helper's */
export function savedQuestionTimeout(): number | null {
  const raw = safeGet(QUESTION_TIMEOUT_KEY);
  if (raw === null || raw === '') return null;
  const minutes = Number(raw);
  return Number.isInteger(minutes) && minutes >= 0 ? minutes : null;
}

/** this browser's wait for a question about a file without the app's own date, or null */
export function savedGuessedDateTimeout(): number | null {
  const raw = safeGet(GUESSED_DATE_TIMEOUT_KEY);
  if (raw === null || raw === '') return null;
  const minutes = Number(raw);
  return Number.isInteger(minutes) && minutes >= 0 ? minutes : null;
}

export function saveGuessedDateTimeout(minutes: number | null): void {
  if (minutes === null) safeRemove(GUESSED_DATE_TIMEOUT_KEY);
  else safeSet(GUESSED_DATE_TIMEOUT_KEY, String(minutes));
}

/** a YYYY-MM-DD date as a reader writes it - 13 May 2026 - or as it was if it is not one */
export function writtenDate(stamp: string | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(stamp ?? '');
  if (!m) return stamp ?? '';
  const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
    'September', 'October', 'November', 'December'];
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}`;
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

/**
 * Formatting options that show a time in the person's AO3 zone - every time the page shows
 * is in it, as the dates AO3's are compared against are. A zone this browser cannot name
 * (a hand-edited value) leaves the browser's own rather than throwing.
 */
export function inAo3Zone(options: Intl.DateTimeFormatOptions = {}): Intl.DateTimeFormatOptions {
  const timeZone = ao3TimeZone();
  try {
    new Intl.DateTimeFormat([], { timeZone });
    return { ...options, timeZone };
  } catch {
    return options;
  }
}

/** how far `zone` is ahead of UTC at the moment `utcMs`, in milliseconds */
function zoneOffsetMs(utcMs: number, zone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  }).formatToParts(new Date(utcMs));
  const v = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return Date.UTC(+v['year'], +v['month'] - 1, +v['day'], +v['hour'] % 24, +v['minute'], +v['second']) - utcMs;
}

/** the zone to use: the AO3 one when this browser can name it, else UTC */
function usableZone(): string {
  const zone = ao3TimeZone();
  try {
    new Intl.DateTimeFormat([], { timeZone: zone });
    return zone;
  } catch {
    return 'UTC';
  }
}

/**
 * A day typed in the person's AO3 zone, as the UTC moment it begins - or, for the newer end
 * of a range (`end`), the last second of it - written `YYYY-MM-DDTHH:MM:SS+00:00`, which is how
 * the helper keeps it. '' for anything that is not a `YYYY-MM-DD` day.
 */
export function zonedDayToUtc(day: string, end = false): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day.trim());
  if (!m) return '';
  const zone = usableZone();
  const local = Date.UTC(+m[1], +m[2] - 1, +m[3], end ? 23 : 0, end ? 59 : 0, end ? 59 : 0);
  // the offset at the guess, then again at the answer, which settles a daylight-saving change
  let at = local - zoneOffsetMs(local, zone);
  at = local - zoneOffsetMs(at, zone);
  return new Date(at).toISOString().replace(/\.\d{3}Z$/, '+00:00');
}

/** a kept moment as the day it is in the person's AO3 zone; a bare day is itself */
export function utcToZonedDay(stamp: unknown): string {
  const text = String(stamp ?? '').trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text;
  const at = new Date(text);
  if (!text || Number.isNaN(at.getTime())) return text.slice(0, 10);
  // en-CA writes YYYY-MM-DD
  return at.toLocaleDateString('en-CA', { timeZone: usableZone() });
}

/**
 * A time as a listing shows it, in 'List refreshed': the reader's AO3 time zone, date and time
 * to the minute. A value that will not parse (an old file's free-text time) is shown as written.
 */
export function shownTime(value: string | Date): string {
  const at = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(at.getTime())) return String(value);
  return at.toLocaleString([], inAo3Zone({ dateStyle: 'medium', timeStyle: 'short' }));
}
