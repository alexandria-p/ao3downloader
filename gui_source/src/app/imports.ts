/**
 * Works whose files are in the library with no index entry - downloaded some other way, or
 * kept from before the index existed - found so they can be imported.
 *
 * A file counts when it is in `works/`, is one of the formats a run downloads, and its name
 * starts with a work number (`workIdFromFilename`, the rule every file is paired to the index
 * by). Its work is unindexed when the index holds no entry with that number.
 *
 * Importing one is two things, both asked about first (`ImportDialog`):
 * - **dating** an undated file - giving its name the ` YYYY-MM-DD` it should end in, the
 *   version it holds - which the page does itself, by renaming it. A run can only judge a
 *   dated copy against AO3's version, and leaves an undated one alone;
 * - **the import run** (`import`), which indexes each work from AO3, marks it imported, and
 *   fetches the formats asked for.
 */

import { Injectable, computed, inject, signal } from '@angular/core';
import { dateFromFilename, workIdFromFilename } from './bookmarks';
import { WORKS_FOLDER } from './library-setup';
import { LibraryStore } from './library-store';
import { Library, OpenableFormat, OPENABLE_FORMATS } from './library';

/** one file in `works/` named for a work */
export interface FoundFile {
  /** the work number its name starts with */
  id: string;
  /** its path in the library, `works/<name>` */
  path: string;
  name: string;
  format: OpenableFormat;
  /** the `YYYY-MM-DD` its name ends in, or '' when it has none */
  date: string;
  /**
   * a file of a work with no index entry that is not offered for the index question - its
   * work was excluded from it - so it is offered for dating only, never looked up
   */
  unindexed?: boolean;
  /** on the dates list: never offered for dating, though its work may still be asked about */
  noDating?: boolean;
}

/** a work in the library with no index entry, and its files */
export interface FoundWork {
  id: string;
  files: FoundFile[];
}

/** which of the downloaded formats a file name is, if any */
export function formatOf(name: string): OpenableFormat | null {
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase();
  if (ext === 'htm') return 'html';
  return (OPENABLE_FORMATS as string[]).includes(ext ?? '') ? (ext as OpenableFormat) : null;
}

/**
 * The works among `paths` (library paths, as `LibraryStore.list` gives them) with no entry in
 * `indexed`, each with its files - by work number, smallest first, so a list reads in order.
 * Only files directly in `works/`, which is the one place a run looks for them.
 */
export function unindexedWorks(paths: Iterable<string>, indexed: ReadonlySet<string>): FoundWork[] {
  return byWork(workFiles(paths).filter((f) => !indexed.has(f.id)));
}

/**
 * The files of works the index **does** have whose names carry no date. A run cannot tell
 * whether AO3 has a newer version of one, and stops to ask about it - so they are offered for
 * dating up front too, beside the unindexed works.
 */
export function undatedIndexedFiles(paths: Iterable<string>, indexed: ReadonlySet<string>): FoundFile[] {
  return byWork(workFiles(paths).filter((f) => indexed.has(f.id) && !f.date)).flatMap((w) => w.files);
}

/** every file directly in works/ that is one of the formats a run downloads, named for a work */
function workFiles(paths: Iterable<string>): FoundFile[] {
  const found: FoundFile[] = [];
  for (const raw of paths) {
    const path = raw.replace(/^\/+/, '');
    const parts = path.split('/');
    if (parts.length !== 2 || parts[0].toLowerCase() !== WORKS_FOLDER) continue;
    const name = parts[1];
    const format = formatOf(name);
    const id = workIdFromFilename(name);
    if (!format || !id) continue;
    found.push({ id, path, name, format, date: dateFromFilename(name) });
  }
  return found;
}

/** files grouped by work - by work number, smallest first, so a list reads in order */
function byWork(files: FoundFile[]): FoundWork[] {
  const works = new Map<string, FoundFile[]>();
  for (const file of files) works.set(file.id, [...(works.get(file.id) ?? []), file]);
  return [...works.entries()]
    .sort(([a], [b]) => a.length - b.length || a.localeCompare(b))
    .map(([id, list]) => ({ id, files: list.sort((a, b) => a.name.localeCompare(b.name)) }));
}

/** the files among these works with no date in their name */
export function undatedFiles(works: FoundWork[]): FoundFile[] {
  return works.flatMap((w) => w.files.filter((f) => !f.date && !f.noDating));
}

/** whether a typed date is one a file can be named with: a real `YYYY-MM-DD` */
export function isFileDate(date: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
  const at = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(at.getTime()) && at.toISOString().slice(0, 10) === date;
}

/**
 * The name a file takes once given `date`: the date added at the end, before the extension,
 * as every download is named (`{work} {title} - {author} YYYY-MM-DD.ext`). Whatever else the
 * name holds - a date written another way included - is kept as it was.
 */
export function datedName(name: string, date: string): string {
  const dot = name.lastIndexOf('.');
  const stem = (dot > 0 ? name.slice(0, dot) : name).trimEnd();
  const ext = dot > 0 ? name.slice(dot) : '';
  return `${stem} ${date}${ext}`;
}

/** what dating some files did: the renames made, and the ones that could not be */
export interface DatingResult {
  renamed: { from: string; to: string }[];
  failed: { path: string; error: string }[];
}

/** one file to rename: where it is now, and the name it takes */
export interface Rename {
  path: string;
  to: string;
}

/**
 * Rename each file to its new name, in place. One that will not rename - a file already there
 * by the new name, or the library out of reach - is noted and the rest carry on; a rename never
 * writes over another file (`LibraryStore.rename` refuses to). `stopped` is asked before each
 * one, so closing the window part way through stops there: what was renamed stays renamed.
 */
export async function dateFiles(
  store: LibraryStore,
  renames: readonly Rename[],
  progress: (done: number, total: number) => void = () => undefined,
  stopped: () => boolean = () => false,
  result: DatingResult = { renamed: [], failed: [] },
): Promise<DatingResult> {
  for (const [index, { path, to }] of renames.entries()) {
    if (stopped()) break;
    if (to === path) {
      progress(index + 1, renames.length);
      continue;
    }
    try {
      await store.rename(path, to);
      result.renamed.push({ from: path, to });
    } catch (error) {
      result.failed.push({ path, error: error instanceof Error ? error.message : String(error) });
    }
    progress(index + 1, renames.length);
  }
  return result;
}

/** a file to be given a date, with the index entry of its work when there is one */
export interface ToDate {
  file: FoundFile;
  date: string;
  record?: object;
}

/**
 * The new name of each file given a date. A file whose work is indexed is named from that entry,
 * as a download names it, carrying the date given (`ask`: the helper's `POST /api/file-names`,
 * which builds names with the very code a download uses); one with no entry - or when the
 * helper cannot be asked - keeps its name with the date added at the end (`datedName`).
 */
export async function renamesFor(
  files: readonly ToDate[],
  ask: (files: readonly ToDate[]) => Promise<string[] | null> = async () => null,
): Promise<Rename[]> {
  let names: string[] | null = null;
  try {
    names = await ask(files);
  } catch {
    names = null;
  }
  return files.map((item, index) => {
    const named = names?.[index];
    const name = named || datedName(item.file.name, item.date);
    const folder = item.file.path.slice(0, item.file.path.length - item.file.name.length);
    return { path: item.file.path, to: folder + name };
  });
}

const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

/** the years a date in a file name can plausibly be: AO3 opened in 2008, fanfic predates it */
function plausible(year: number): boolean {
  return year >= 1990 && year <= new Date().getUTCFullYear() + 1;
}

function stamp(year: number, month: number, day: number): string {
  const date = `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
  return plausible(year) && isFileDate(date) ? date : '';
}

/**
 * The ways a date is written in file names, tried in this order - the first that gives a real
 * day wins. Day-first and month-first both write `03-04-2024` (and `2024-03-04`), so
 * month-first (the US way, and what most tools write) is tried first; a first number over 12
 * can only be a day, so that date is read day-first.
 */
const DATE_PATTERNS: { pattern: RegExp; read: (m: RegExpExecArray) => string }[] = [
  // 2024-03-04, 2024_03_04, 2024.03.04, 2024/03/04, 2024 03 04 - month-first, then day-first
  { pattern: /(?<!\d)(\d{4})[-_. /](\d{1,2})[-_. /](\d{1,2})(?!\d)/, read: (m) => stamp(+m[1], +m[2], +m[3]) || stamp(+m[1], +m[3], +m[2]) },
  // 20240304 - month-first, then day-first
  { pattern: /(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)/, read: (m) => stamp(+m[1], +m[2], +m[3]) || stamp(+m[1], +m[3], +m[2]) },
  // 03-04-2024 as month-first, then day-first
  { pattern: /(?<!\d)(\d{1,2})[-_. /](\d{1,2})[-_. /](\d{4})(?!\d)/, read: (m) => stamp(+m[3], +m[1], +m[2]) || stamp(+m[3], +m[2], +m[1]) },
  // 14 Dec 2024, 14 December 2024, 14-Dec-2024
  { pattern: /(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[-_. ]+([a-z]{3,9})\.?[-_., ]+(\d{4})(?!\d)/i, read: (m) => monthDate(m[3], m[2], m[1]) },
  // Dec 14 2024, December 14, 2024
  { pattern: /(?<![a-z])([a-z]{3,9})\.?[-_. ]+(\d{1,2})(?:st|nd|rd|th)?,?[-_. ]+(\d{4})(?!\d)/i, read: (m) => monthDate(m[3], m[1], m[2]) },
  // 2024 Dec 14
  { pattern: /(?<!\d)(\d{4})[-_. ]+([a-z]{3,9})\.?[-_. ]+(\d{1,2})(?!\d)/i, read: (m) => monthDate(m[1], m[2], m[3]) },
];

function monthDate(year: string, month: string, day: string): string {
  const index = MONTHS.indexOf(month.slice(0, 3).toLowerCase());
  return index < 0 ? '' : stamp(+year, index + 1, +day);
}

/**
 * A date read out of a file's name, written any of the ways in `DATE_PATTERNS` and anywhere in
 * the name - or '' when there is none. The work number the name starts with is left out, so a
 * work numbered 20240304 is not read as a date.
 */
export function inferDate(name: string): string {
  const base = name.replace(/\.[^.]*$/, '');
  const id = workIdFromFilename(base);
  const rest = id ? base.slice(id.length) : base;
  for (const { pattern, read } of DATE_PATTERNS) {
    const global = new RegExp(pattern.source, pattern.flags.includes('g') ? pattern.flags : pattern.flags + 'g');
    for (let m = global.exec(rest); m; m = global.exec(rest)) {
      const date = read(m);
      if (date) return date;
    }
  }
  return '';
}

function baseName(path: string): string {
  return path.split('/').pop() ?? path;
}

/** the links an import run is started with, one to a line, as the helper keeps them */
export function importLinks(works: FoundWork[]): string {
  return works.map((w) => `https://archiveofourown.org/works/${w.id}`).join('\n');
}

/**
 * Which of the works found are updated - given the formats picked, and their outdated copies
 * replaced: every one with an issue, only those with undated files, only those with no index
 * entry, or none (`skip`).
 */
export type UpdateScope = 'all' | 'dates' | 'index' | 'skip';

/** what the import window hands the run window to start */
export interface ImportRequest {
  /** the works' links, one to a line */
  links: string;
  count: number;
  /** JSON, and whichever formats to fetch for works without them */
  filetypes: string[];
  replaceOutdated: boolean;
  /** the works among `links` only looked up for their index entry - nothing downloaded */
  indexOnly: string[];
  /** how many of the works are looked up for a missing index entry */
  lookups: number;
  /** which works the formats and replacing are for */
  scope: UpdateScope;
}

/**
 * What never to offer again, at the top of the library, so a library in Dropbox leaves the
 * same out on every device. The page reads and writes it; the helper only renames names in it. Three lists:
 *
 * - **files** (`kind: 'files'`, *No, do not ask me again for these files*): left out of
 *   everything - never counted, never listed, never a reason to offer the window;
 * - **index** (`kind: 'index'`, *No, and do not ask again for these works*): a work with no
 *   index entry, and the files it had then. It is not asked about again **while its files are
 *   still exactly those**; a file added since asks again. Its undated files are still offered
 *   for dating, and renaming one renames it here too (`LibraryImports.renamed`);
 * - **dates** (`kind: 'dates'`, *Don't ask this again for skipped files*): undated files never
 *   offered for dating again, by name. Each still counts for its work's index question.
 *
 * A file renamed - by dating here, or by an import naming files from their new entries (the
 * helper's `follow_renames_in_exclusions`) - is renamed on every list it is on.
 */
export const IMPORT_EXCLUDED_FILE = 'import-excluded.json';

export interface Excluded {
  /** file names left out of everything */
  files: Set<string>;
  /** by work number: the file names it had when it was left out of the index question */
  index: Map<string, Set<string>>;
  /** file names never offered for dating */
  dates: Set<string>;
}

/** one line of the excluded file */
interface ExcludedEntry {
  id: string;
  kind?: 'files' | 'index' | 'dates';
  files?: string[];
  excluded_on?: string;
}

function excludedEntries(text: string | null): ExcludedEntry[] {
  try {
    const parsed = JSON.parse(text ?? '') as { excluded?: unknown };
    return Array.isArray(parsed?.excluded)
      ? (parsed.excluded as ExcludedEntry[]).filter((x) => x && /^\d+$/.test(String(x.id ?? '')))
      : [];
  } catch {
    return [];
  }
}

function excludedOf(entries: ExcludedEntry[]): Excluded {
  const excluded: Excluded = { files: new Set(), index: new Map(), dates: new Set() };
  for (const entry of entries) {
    const names = (entry.files ?? []).map(String);
    if (entry.kind === 'files') for (const name of names) excluded.files.add(name);
    else if (entry.kind === 'dates') for (const name of names) excluded.dates.add(name);
    else {
      const id = String(entry.id);
      excluded.index.set(id, new Set([...(excluded.index.get(id) ?? []), ...names]));
    }
  }
  return excluded;
}

/** what the excluded file leaves out; anything unreadable is nothing */
export function readExcludedFile(text: string | null): Excluded {
  return excludedOf(excludedEntries(text));
}

/** whether a work is still left out of the index question: every file it has now was recorded */
export function indexExcluded(work: FoundWork, excluded: Excluded): boolean {
  const recorded = excluded.index.get(work.id);
  return !!recorded && work.files.every((f) => recorded.has(f.name));
}

/** the most works one import takes - the helper's `MAX_IMPORT_LINKS` */
export const MAX_IMPORT_WORKS = 5000;

/**
 * The library's unindexed works, kept current: worked out again whenever the index changes
 * (a read, a refresh, a run's changes taken in) - one listing of `works/`, nothing read.
 */
@Injectable({ providedIn: 'root' })
export class LibraryImports {
  private readonly library = inject(Library);
  readonly found = signal<FoundWork[]>([]);
  /** files of indexed works with no date in their name */
  readonly undatedIndexed = signal<FoundFile[]>([]);
  /** whether anything was found to resolve: works with no index entry, or undated files */
  readonly hasIssues = computed(() => this.found().length > 0 || this.undatedIndexed().length > 0);
  /** the store the last check was of, so a check of a library since closed is dropped */
  readonly checkedStore = signal<LibraryStore | null>(null);
  /**
   * the excluded file's lines, as each library has them - read once per listing, so a run that
   * renamed files (and so changed the file) is read again once the page takes its changes in
   */
  private readonly entriesBy = new WeakMap<LibraryStore, { entries: ExcludedEntry[]; listedAt: Date | null }>();
  private generation = 0;

  private async entries(store: LibraryStore): Promise<ExcludedEntry[]> {
    const listedAt = this.library.listedAt();
    const cached = this.entriesBy.get(store);
    if (cached && cached.listedAt === listedAt) return cached.entries;
    let entries: ExcludedEntry[];
    try {
      entries = excludedEntries(await store.read(IMPORT_EXCLUDED_FILE));
    } catch {
      entries = cached?.entries ?? [];
    }
    this.entriesBy.set(store, { entries, listedAt });
    return entries;
  }

  private async save(store: LibraryStore, entries: ExcludedEntry[]): Promise<void> {
    await store.write(IMPORT_EXCLUDED_FILE, new Response(JSON.stringify({ excluded: entries }, null, 2) + '\n'));
    this.entriesBy.set(store, { entries, listedAt: this.library.listedAt() });
  }

  /**
   * Never count or offer these files again (*No, do not ask me again for these files*). The
   * files themselves are left as they are.
   */
  async excludeFiles(files: FoundFile[]): Promise<void> {
    await this.addFiles('files', files);
  }

  /**
   * Never offer these undated files for dating again (*Don't ask this again for skipped
   * files*). Their works are still asked about; the files are left as they are.
   */
  async excludeDating(files: FoundFile[]): Promise<void> {
    await this.addFiles('dates', files);
  }

  private async addFiles(kind: 'files' | 'dates', files: FoundFile[]): Promise<void> {
    const store = this.library.store();
    if (!store || !files.length) return;
    const entries = await this.entries(store);
    const before = excludedOf(entries)[kind];
    const today = new Date().toISOString().slice(0, 10);
    const byWork = new Map<string, string[]>();
    for (const file of files) {
      if (before.has(file.name)) continue;
      byWork.set(file.id, [...(byWork.get(file.id) ?? []), file.name]);
    }
    const added: ExcludedEntry[] = [...byWork].map(([id, names]) => ({ id, kind, files: names, excluded_on: today }));
    if (added.length) await this.save(store, [...entries, ...added]);
    await this.check();
  }

  /**
   * Do not ask about these works' index entries again while their files stay as they are
   * (*No, and do not ask again for these works*) - each recorded with the files it has now.
   */
  async excludeFromIndex(works: FoundWork[]): Promise<void> {
    const store = this.library.store();
    if (!store || !works.length) return;
    const ids = new Set(works.map((w) => w.id));
    const today = new Date().toISOString().slice(0, 10);
    // a work asked about again (it gained a file) is recorded afresh, with every file it has
    const kept = (await this.entries(store)).filter((e) => e.kind === 'files' || !ids.has(String(e.id)));
    const added: ExcludedEntry[] = works.map((w) => ({
      id: w.id,
      kind: 'index',
      files: w.files.map((f) => f.name),
      excluded_on: today,
    }));
    await this.save(store, [...kept, ...added]);
    await this.check();
  }

  /** files renamed by dating: the exclusion list follows them, so a dated file is not a new one */
  async renamed(renames: readonly { from: string; to: string }[]): Promise<void> {
    const store = this.library.store();
    if (!store || !renames.length) return;
    const names = new Map(renames.map((r) => [baseName(r.from), baseName(r.to)]));
    const entries = await this.entries(store);
    let changed = false;
    const next = entries.map((entry) => {
      const files = (entry.files ?? []).map((name) => {
        const to = names.get(name);
        if (to) changed = true;
        return to ?? name;
      });
      return { ...entry, files };
    });
    if (changed) await this.save(store, next).catch(() => undefined);
  }

  async check(): Promise<void> {
    const store = this.library.store();
    const generation = ++this.generation;
    if (!store) {
      this.found.set([]);
      this.undatedIndexed.set([]);
      this.checkedStore.set(null);
      return;
    }
    const indexed = new Set(this.library.worksById().keys());
    try {
      const listed = await store.list(WORKS_FOLDER, false);
      const excluded = excludedOf(await this.entries(store));
      if (generation !== this.generation || store !== this.library.store()) return;
      // files left out of everything are gone before anything is counted
      const paths = listed.filter((p) => !excluded.files.has(baseName(p)));
      // files on the dates list are never offered for dating, but still count for their work
      const unindexed = unindexedWorks(paths, indexed).map((w) => ({
        ...w,
        files: w.files.map((f) => (excluded.dates.has(f.name) ? { ...f, noDating: true } : f)),
      }));
      const asked = unindexed.filter((w) => !indexExcluded(w, excluded));
      // a work left out of the index question still has its undated files to date
      const notAsked = unindexed
        .filter((w) => indexExcluded(w, excluded))
        .flatMap((w) => w.files.filter((f) => !f.date).map((f) => ({ ...f, unindexed: true })));
      this.found.set(asked);
      this.undatedIndexed.set(
        [...undatedIndexedFiles(paths, indexed), ...notAsked].filter((f) => !excluded.dates.has(f.name)),
      );
      this.checkedStore.set(store);
    } catch {
      // the library could not be listed: whatever was found before is kept until it can
    }
  }
}
