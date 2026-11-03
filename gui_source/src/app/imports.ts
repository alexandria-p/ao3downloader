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
  return works.flatMap((w) => w.files.filter((f) => !f.date));
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

/**
 * Give each file its date, by renaming it in place. One that will not rename - a file already
 * there by the new name, or the library out of reach - is noted and the rest carry on; a
 * rename never writes over another file (`LibraryStore.rename` refuses to).
 */
export async function dateFiles(
  store: LibraryStore,
  dates: ReadonlyMap<string, string>,
  progress: (done: number, total: number) => void = () => undefined,
): Promise<DatingResult> {
  const result: DatingResult = { renamed: [], failed: [] };
  const all = [...dates.entries()];
  for (const [index, [path, date]] of all.entries()) {
    const name = path.split('/').pop() ?? path;
    const to = `${path.slice(0, path.length - name.length)}${datedName(name, date)}`;
    try {
      await store.rename(path, to);
      result.renamed.push({ from: path, to });
    } catch (error) {
      result.failed.push({ path, error: error instanceof Error ? error.message : String(error) });
    }
    progress(index + 1, all.length);
  }
  return result;
}

/** the links an import run is started with, one to a line, as the helper keeps them */
export function importLinks(works: FoundWork[]): string {
  return works.map((w) => `https://archiveofourown.org/works/${w.id}`).join('\n');
}

/** what the import window hands the run window to start */
export interface ImportRequest {
  /** the works' links, one to a line */
  links: string;
  count: number;
  /** JSON, and whichever formats to fetch for works without them */
  filetypes: string[];
  replaceOutdated: boolean;
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
  private generation = 0;

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
      const paths = await store.list(WORKS_FOLDER, false);
      if (generation !== this.generation || store !== this.library.store()) return;
      this.found.set(unindexedWorks(paths, indexed));
      this.undatedIndexed.set(undatedIndexedFiles(paths, indexed));
      this.checkedStore.set(store);
    } catch {
      // the library could not be listed: whatever was found before is kept until it can
    }
  }
}
