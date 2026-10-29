import { Injectable, computed, inject, signal } from '@angular/core';
import {
  Bookmark,
  BookmarksExport,
  bookmarkTypeOf,
  flattenRecord,
  isBookmarkEntry,
  isListedEntry,
  isNewerCopy,
  isWorkEntry,
  workIdFromFilename,
} from './bookmarks';
import { Collection, flattenCollection, isCollectionRecord } from './collections';
import { APP_FOLDER_PATH, DropboxFile, DropboxSession } from './dropbox';
import { DirectoryHandle, FolderStore } from './folder-store';
import { isRunRecord } from './jobs';
import { LibrarySetup, SetupTarget, WORKS_FOLDER } from './library-setup';
import { DropboxLibraryStore, LibraryStore, LocalLibraryStore } from './library-store';
import { unzip } from './unzip';
import { buildTagIndex } from './tags';

/**
 * A downloaded work that can be opened from the listing: a file already in hand for a
 * local folder, or where to fetch it from for Dropbox - fetched only when clicked, since
 * reading every work up front would mean downloading the whole library to show a list.
 */
export type LocalCopy = File | DropboxCopy;

export interface DropboxCopy {
  dropboxPath: string;
  modified: number;
}

/**
 * Every format ao3 offers a download in, as the listing knows its files - in the order the
 * listing shows their buttons. The title opens the html, so html has no button of its own.
 */
const OPENABLE = {
  html: /\.html?$/i,
  pdf: /\.pdf$/i,
  epub: /\.epub$/i,
  mobi: /\.mobi$/i,
  azw3: /\.azw3$/i,
} as const;
export type OpenableFormat = keyof typeof OPENABLE;
export const OPENABLE_FORMATS = Object.keys(OPENABLE) as OpenableFormat[];

/** the downloaded copies the listing can open, by work number, for each format */
export type Copies = Record<OpenableFormat, Map<string, LocalCopy>>;

export function emptyCopies(): Copies {
  return Object.fromEntries(OPENABLE_FORMATS.map((f) => [f, new Map()])) as Copies;
}

/** how a tab is told to show each format, or a saved file to be typed */
const SHOWN_AS: Record<OpenableFormat, string> = {
  html: 'text/html',
  pdf: 'application/pdf',
  epub: 'application/epub+zip',
  mobi: 'application/x-mobipocket-ebook',
  azw3: 'application/vnd.amazon.ebook',
};

/**
 * Whether a browser can show the format itself. Html and pdf open in a tab; an e-book has no
 * viewer in any browser - a tab handed one only saves it under a made-up name - so those are
 * saved, under the file's own name, for an e-reader to open.
 */
export function viewableInBrowser(format: OpenableFormat): boolean {
  return format === 'html' || format === 'pdf';
}

/** a downloaded copy's own file name, to save it under */
export function copyName(copy: LocalCopy): string {
  if (copy instanceof Blob) return (copy as File).name ?? 'work';
  return copy.dropboxPath.split('/').pop() ?? 'work';
}

/** the folders whose json is the index, read in one zip each */
const INDEX_FOLDERS = ['indexing', 'collections'];
/** how many files to fetch at once when a folder is too big to come as one zip */
const PARALLEL_DOWNLOADS = 6;

/**
 * How far reading a Dropbox library has got, for the bar shown while it loads.
 *
 * Each stage says only what is known at that point. A listing comes a page at a time with no
 * total, so it counts what it has found. A folder's zip is built by Dropbox as it sends it, so
 * its size is usually unknown (`total` null) and the bar can only say how much has arrived;
 * which folder of how many is known. Entries fetched one at a time (a folder too big for one
 * zip) and entries read once downloaded both have a real total.
 */
export type ReadProgress =
  | { stage: 'listing'; found: number }
  | { stage: 'downloading'; folder: number; folders: number; bytes: number; total: number | null }
  | { stage: 'fetching'; done: number; total: number }
  | { stage: 'reading'; done: number; total: number };

type NoteProgress = (progress: ReadProgress) => void;

const count = new Intl.NumberFormat('en');

/** a size people can read: bytes, KB or MB */
export function readableSize(bytes: number): string {
  if (bytes < 1024) return `${count.format(bytes)} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * What the bar shows for a stage: a percentage only where there is a real total to divide
 * by, otherwise null - the bar then moves without claiming a number - and a caption saying
 * what is happening.
 */
export function describeReadProgress(progress: ReadProgress): {
  percent: number | null;
  caption: string;
} {
  const share = (done: number, total: number) =>
    total > 0 ? Math.min(100, Math.floor((done / total) * 100)) : 0;
  switch (progress.stage) {
    case 'listing':
      return {
        percent: null,
        caption: progress.found
          ? `Listing your library in Dropbox - ${count.format(progress.found)} files so far`
          : 'Listing your library in Dropbox...',
      };
    case 'downloading': {
      const folder = progress.folders > 1 ? ` (folder ${progress.folder} of ${progress.folders})` : '';
      const size = progress.total
        ? `${readableSize(progress.bytes)} of ${readableSize(progress.total)}`
        : `${readableSize(progress.bytes)} so far`;
      return {
        percent: progress.total ? share(progress.bytes, progress.total) : null,
        caption: `Downloading the index from Dropbox${folder} - ${size}`,
      };
    }
    case 'fetching':
      return {
        percent: share(progress.done, progress.total),
        caption: `Downloading the index from Dropbox one entry at a time - ` +
          `${count.format(progress.done)} of ${count.format(progress.total)}`,
      };
    case 'reading':
      return {
        percent: share(progress.done, progress.total),
        caption: `Reading the index - ${count.format(progress.done)} of ` +
          `${count.format(progress.total)} entries`,
      };
  }
}

/**
 * Reads a downloads folder that ao3downloader wrote into - on this computer, or in Dropbox.
 *
 * Every time a library is opened it is set up first (`LibrarySetup`): the folders it should
 * have are made, and works left in its top level are offered a move into `works/`. Works
 * are only ever looked for in `works/`, so the listing pairs a fic with the same copy a run
 * would find.
 *
 * A local folder stays in the browser - the files are read in the page, never uploaded. The
 * folder is picked once and the handle is kept, so later visits load it with no clicks. A
 * Dropbox folder is read straight from Dropbox by the page, with the session it signed in
 * for; the helper is not needed just to look.
 */
@Injectable({ providedIn: 'root' })
export class Library {
  readonly data = signal<BookmarksExport | null>(null);
  readonly collections = signal<Collection[]>([]);
  readonly sourceName = signal('');
  readonly folderName = signal('');
  /** each work's newest downloaded copy in every format, by work number */
  readonly copies = signal<Copies>(emptyCopies());
  readonly htmlFiles = computed(() => this.copies().html);
  /** each work's newest downloaded PDF, by work number - what the listing's PDF button opens */
  readonly pdfFiles = computed(() => this.copies().pdf);
  /**
   * Every work in the index by work number - including works that are there only because a
   * series you bookmarked holds them, which the bookmarks listing leaves out. A series' card
   * and a collection both list works by number and look them up here.
   */
  readonly worksById = signal<Map<string, Bookmark>>(new Map());
  /**
   * Every series entry by series id - one you bookmarked, or one reached through a work of
   * yours - so a work's 'Part N of' line can list the rest of its series.
   */
  readonly seriesById = signal<Map<string, Bookmark>>(new Map());
  /**
   * Every external work entry by ao3's number for it - kept apart from works because the two
   * are numbered separately, so a collection's external works are never matched to a work.
   */
  readonly externalsById = signal<Map<string, Bookmark>>(new Map());
  /**
   * Every tag in the library, by kind and most-used first - what the tag filter suggests from.
   * Built from the works already in memory: once per read, and again only when the works change
   * (a run's refresh, another library), never on a keystroke.
   */
  readonly tagIndex = computed(() =>
    buildTagIndex([...this.worksById().values(), ...this.seriesById().values(), ...this.externalsById().values()]),
  );
  readonly error = signal('');
  readonly loading = signal(false);
  /** while a Dropbox library is being read, how far it has got; null otherwise */
  readonly readProgress = signal<ReadProgress | null>(null);
  /** a folder is remembered but the browser wants the permission confirmed again */
  readonly needsReconnect = signal(false);
  /**
   * The library that is open and can be written to, or null. A run reads and writes
   * through this and nothing else - the helper asks, the page does it - and the history
   * page reads the run records out of it.
   */
  readonly store = signal<LibraryStore | null>(null);

  private readonly folders = inject(FolderStore);
  private readonly dropbox = inject(DropboxSession);
  private readonly setup = inject(LibrarySetup);

  /** which library is on screen, so switching back to a local folder clears Dropbox's */
  private showing: 'local' | 'dropbox' | null = null;
  /**
   * Bumped every time the page switches library, local or Dropbox. Every read notes the
   * number it started under and throws its result away if it has changed by the time it
   * finishes - a large folder takes seconds to read, and a switch made meanwhile must not
   * have the old library land on top of the new one.
   */
  private generation = 0;
  /**
   * Every entry the index holds, as last read - bookmarks and the works a series or a
   * collection brought in alike. Kept so a refresh after a run can swap in only what the run
   * rewrote, rather than reading the whole library again.
   */
  private entries: Bookmark[] = [];
  /**
   * The works hidden from the listing, by `hiddenKey` - kept in the library itself
   * (`HIDDEN_FILE`), so a library in Dropbox hides the same works on every device. Hiding
   * touches nothing else: the files and the index entry stay exactly as they were.
   */
  readonly hidden = signal<Map<string, HiddenWork>>(new Map());

  /** the folder on this computer being shown, to list its works/ again after a run */
  private localHandle: DirectoryHandle | null = null;

  readonly canPickFolder = this.folders.supported();

  private handle: DirectoryHandle | null = null;

  /** Show the folder on this computer: reopen the remembered one if it can still be read. */
  async showLocal(): Promise<void> {
    if (this.showing === 'dropbox') {
      // Dropbox's library, and the means of writing to it, go with it
      this.clearLibrary();
      this.store.set(null);
    }
    this.showing = 'local';
    await this.restore(++this.generation);
  }

  /**
   * Show the Dropbox folder the page is signed in to.
   *
   * One recursive listing says what is there; the index then comes down as a zip per
   * folder. Works are not read at all until one is opened. A folder with nothing in it yet
   * is an empty library, not an error - a folder chosen a minute ago is exactly that.
   */
  async showDropbox(): Promise<void> {
    this.showing = 'dropbox';
    const generation = ++this.generation;
    this.clearLibrary();
    // the local folder is not what a run would write to now; Dropbox's replaces it once open
    this.store.set(null);
    this.error.set('');

    const folder = this.dropbox.folder();
    if (!folder || this.dropbox.status() !== 'signed-in') {
      this.store.set(null);
      return;
    }

    this.loading.set(true);
    // a switch of library meanwhile must not have this read's progress land on the new one
    const note: NoteProgress = (progress) => {
      if (generation === this.generation) this.readProgress.set(progress);
    };
    try {
      await this.setup.prepare(this.dropboxTarget(), APP_FOLDER_PATH);
      if (generation !== this.generation) return;
      this.store.set(new DropboxLibraryStore(this.dropbox));
      note({ stage: 'listing', found: 0 });
      const files = await this.dropbox.listFiles(folder.path, true, (found) =>
        note({ stage: 'listing', found }),
      );
      if (generation !== this.generation) return;

      const inside = (file: DropboxFile) =>
        file.path.slice(folder.path.length).split('/').filter(Boolean);
      const indexFiles = files.filter(
        (f) => /\.json$/i.test(f.name) && INDEX_FOLDERS.includes(inside(f)[0]?.toLowerCase()),
      );
      const copies = dropboxCopies(files, folder.path);

      const jsonFiles = await this.readDropboxIndex(folder.path, indexFiles, note);
      if (generation !== this.generation) return;
      await this.ingestRecords(jsonFiles, copies, false, note);
      // the listing says whether there is one, so a library with nothing hidden costs no download
      const hiddenPath = `${folder.path}/${HIDDEN_FILE}`.toLowerCase();
      await this.readHidden(generation, files.some((f) => f.path.toLowerCase() === hiddenPath));
    } catch (error) {
      if (generation !== this.generation) return;
      this.error.set(
        `Could not read ${APP_FOLDER_PATH} from Dropbox. ` +
          (error instanceof Error ? error.message : ''),
      );
    } finally {
      if (generation === this.generation) {
        this.loading.set(false);
        this.readProgress.set(null);
      }
    }
  }

  /**
   * The contents of a downloaded work, to open it - typed as the format it is, so a tab
   * shows it rather than offering to save it. Dropbox sends every file as octet-stream.
   */
  async readCopy(copy: LocalCopy, format: OpenableFormat = 'html'): Promise<Blob> {
    const type = SHOWN_AS[format];
    if (copy instanceof Blob) return copy.type === type ? copy : new Blob([copy], { type });
    return new Blob([await this.dropbox.download(copy.dropboxPath)], { type });
  }

  /** Called at startup: reopen the remembered folder if it can still be read. */
  async restore(generation = this.generation): Promise<void> {
    const handle = await this.folders.recall();
    if (!handle || generation !== this.generation) return;

    this.handle = handle;
    this.folderName.set(handle.name);

    if ((await this.folders.permission(handle, false)) !== 'granted') {
      if (generation !== this.generation) return;
      // asking needs a click behind it, so surface a button instead - and until then this
      // folder cannot be written to, so it is no library for a run
      this.needsReconnect.set(true);
      this.store.set(null);
      return;
    }
    await this.readHandle(handle, generation);
  }

  /** Pick a folder and remember it. */
  async pickFolder(): Promise<void> {
    let handle: DirectoryHandle;
    try {
      handle = await this.folders.pick();
    } catch {
      return; // the picker was dismissed
    }
    this.handle = handle;
    this.folderName.set(handle.name);
    this.needsReconnect.set(false);
    await this.folders.remember(handle);
    await this.readHandle(handle, this.generation);
  }

  /** Confirm permission for the remembered folder, from a click. */
  async reconnect(): Promise<void> {
    if (!this.handle) return;
    if ((await this.folders.permission(this.handle, true)) !== 'granted') {
      this.error.set('Permission to read that folder was declined.');
      return;
    }
    this.needsReconnect.set(false);
    await this.readHandle(this.handle, this.generation);
  }

  async forget(): Promise<void> {
    await this.folders.forget();
    this.handle = null;
    this.folderName.set('');
    this.needsReconnect.set(false);
    this.store.set(null);
    this.clearLibrary();
  }

  /** What is on screen, without touching which local folder is remembered. */
  private clearLibrary(): void {
    this.data.set(null);
    this.collections.set([]);
    this.sourceName.set('');
    this.copies.set(emptyCopies());
    this.hidden.set(new Map());
    this.entries = [];
    this.worksById.set(new Map());
    this.seriesById.set(new Map());
    this.externalsById.set(new Map());
  }

  /**
   * The index's json, read a folder at a time as a zip. A folder Dropbox will not zip -
   * more than 10,000 files, or a zip this page cannot read - is fetched file by file
   * instead, a few at a time.
   */
  private async readDropboxIndex(
    root: string,
    indexFiles: DropboxFile[],
    note: NoteProgress = () => {},
  ): Promise<File[]> {
    const read: File[] = [];
    const folders = INDEX_FOLDERS.map((name) => {
      const prefix = `${root}/${name}/`.toLowerCase();
      return { name, wanted: indexFiles.filter((f) => f.path.toLowerCase().startsWith(prefix)) };
    }).filter((f) => f.wanted.length > 0);
    for (const [at, { name, wanted }] of folders.entries()) {
      try {
        const zip = await this.dropbox.downloadZip(`${root}/${name}`, (bytes, total) =>
          note({ stage: 'downloading', folder: at + 1, folders: folders.length, bytes, total }),
        );
        const entries = await unzip(zip);
        for (const entry of entries) {
          const file = entry.path.split('/').pop() ?? '';
          if (/\.json$/i.test(file)) read.push(new File([entry.data as BlobPart], file));
        }
      } catch {
        read.push(...(await this.downloadEach(wanted, note)));
      }
    }
    return read;
  }

  private async downloadEach(files: DropboxFile[], note: NoteProgress = () => {}): Promise<File[]> {
    const read: File[] = [];
    let next = 0;
    let done = 0;
    note({ stage: 'fetching', done, total: files.length });
    const worker = async () => {
      while (next < files.length) {
        const file = files[next++];
        try {
          read.push(new File([await this.dropbox.download(file.path)], file.name));
        } catch {
          // one unreadable file should not hide the rest of the library
        }
        // counted either way: the bar is how many have been tried, not how many arrived
        note({ stage: 'fetching', done: ++done, total: files.length });
      }
    };
    await Promise.all(Array.from({ length: PARALLEL_DOWNLOADS }, worker));
    return read;
  }

  /** Fallback for browsers without a directory picker, and for loading a single json. */
  async load(fileList: FileList | null): Promise<void> {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    await this.ingest(files);
  }

  /**
   * Set a local folder up and read it - unless the page has switched library by the time
   * any step of that finishes, in which case nothing of it is kept.
   */
  private async readHandle(handle: DirectoryHandle, generation: number): Promise<void> {
    const current = () => generation === this.generation;
    this.loading.set(true);
    try {
      try {
        await this.setup.prepare(this.localTarget(handle), handle.name);
      } catch (error) {
        if (!current()) return;
        this.error.set(
          `Could not set up ${handle.name}. ` + (error instanceof Error ? error.message : ''),
        );
        return;
      }
      if (!current()) return;
      this.store.set(new LocalLibraryStore(handle));
      this.localHandle = handle;
      // the index can be anywhere it has ever been written, so all of it is read for json;
      // works only ever come from works/
      const everything = await this.folders.read(handle);
      const works = await this.folders.readSubfolder(handle, WORKS_FOLDER);
      if (!current()) return;
      // not strict: this folder has just been set up as a library, so an empty one is new,
      // not the wrong folder
      await this.ingestRecords(jsonOf(everything), this.mapCopies(works), false);
      await this.readHidden(generation);
    } catch {
      if (current()) this.error.set(`Could not read ${handle.name}.`);
    } finally {
      if (current()) this.loading.set(false);
    }
  }

  /**
   * A folder handed over as a list of files, by a browser with no directory picker. It
   * cannot be set up - nothing can be written back - so it is read as it is, works taken
   * from works/ where the list says where each file sat.
   */
  private async ingest(files: File[]): Promise<void> {
    const works = files.filter((f) => {
      const parts = relativePath(f).split(/[\\/]/);
      // [picked folder, works, name] - or a bare file with no path to go on
      return parts.length === 1 || parts[1]?.toLowerCase() === WORKS_FOLDER;
    });
    await this.ingestRecords(jsonOf(files), this.mapCopies(works), true);
    // nothing can be written to a folder handed over this way, but what was hidden still is
    const hidden = files.find((f) => {
      const parts = relativePath(f).split(/[\\/]/);
      return parts.length <= 2 && baseName(f).toLowerCase() === HIDDEN_FILE;
    });
    this.hidden.set(hidden ? readHiddenFile(await hidden.text()) : new Map());
  }

  private localTarget(handle: DirectoryHandle): SetupTarget {
    return {
      topLevel: () => this.folders.topLevel(handle),
      makeFolder: (name) => this.folders.makeFolder(handle, name),
      moveToWorks: async (names, progress) => {
        let moved = 0;
        const notMoved: string[] = [];
        for (const [i, name] of names.entries()) {
          try {
            if (await this.folders.moveIntoSubfolder(handle, name, WORKS_FOLDER)) moved++;
            else notMoved.push(name);
          } catch {
            notMoved.push(name);
          }
          progress(i + 1);
        }
        return { moved, notMoved };
      },
    };
  }

  private dropboxTarget(): SetupTarget {
    return {
      topLevel: () => this.dropbox.topLevel(),
      makeFolder: (name) => this.dropbox.makeFolder(name),
      moveToWorks: (names, progress) => this.dropbox.moveInto(WORKS_FOLDER, names, progress),
    };
  }

  /**
   * Turn the index's json into the listing. `strict` is for a folder the user pointed at
   * by hand, where finding no index at all most likely means the wrong folder was picked;
   * a Dropbox folder chosen for this app and not yet run into is simply empty.
   */
  private async ingestRecords(
    jsonFiles: File[],
    copies: Copies,
    strict: boolean,
    note?: NoteProgress,
  ): Promise<void> {
    this.error.set('');
    this.loading.set(true);
    try {
      if (jsonFiles.length === 0 && !strict) return;
      if (jsonFiles.length === 0) {
        this.error.set(
          'No json files in that folder. Pick the folder your library lives in - the one ' +
            'holding the indexing and works folders.',
        );
        return;
      }

      const { works, collections } = await this.readRecords(jsonFiles, note);
      if (works.length === 0 && collections.length === 0) {
        if (!strict) return;
        this.error.set(
          `Found ${jsonFiles.length} json file(s) in there, but none of them look like an ` +
            'ao3downloader export.',
        );
        return;
      }

      this.publish(works, collections, copies);
    } finally {
      this.loading.set(false);
    }
  }

  /**
   * Bring the listing up to date with what a run just wrote, without reading the whole
   * library again - which, for a large library in Dropbox, is minutes.
   *
   * `changed` is every path the run wrote, deleted or renamed (the page made each of those
   * changes for it, so it knows them all). The index files among them are read again and
   * swapped in for the entries and collections they hold; works/ is listed again if anything
   * in it changed, since a download can replace or rename an older copy. Everything else is
   * kept as it was. An index file the run deleted leaves its entry until the library is next
   * opened - runs do not delete index entries, so that is only ever a file removed by hand.
   */
  async refreshAfterRun(changed: Iterable<string>, store: LibraryStore | null = this.store()): Promise<void> {
    // the run's library is not the one on screen any more: nothing here to bring up to date
    if (!store || store !== this.store()) return;
    const generation = this.generation;
    const paths = [...new Set(changed)].map((p) => p.replace(/^\/+/, ''));
    const top = (path: string) => path.split('/')[0]?.toLowerCase() ?? '';
    const indexPaths = paths.filter((p) => /\.json$/i.test(p) && INDEX_FOLDERS.includes(top(p)));
    const worksChanged = paths.some((p) => top(p) === WORKS_FOLDER);
    if (!indexPaths.length && !worksChanged) return;

    try {
      const read = await Promise.all(
        indexPaths.map(async (path) => {
          const text = await store.read(path).catch(() => null);
          return text === null ? null : new File([text], path.split('/').pop() ?? path);
        }),
      );
      const { works, collections } = await this.readRecords(read.filter((f): f is File => !!f));
      const copies = worksChanged ? await this.listCopies() : this.copies();
      if (generation !== this.generation || store !== this.store()) return;

      const key = (entry: Bookmark) => `${bookmarkTypeOf(entry)}:${entry.id}`;
      const fresh = new Map(works.filter((w) => w.id).map((w) => [key(w), w]));
      const merged = this.entries.map((entry) => (entry.id && fresh.get(key(entry))) || entry);
      const known = new Set(this.entries.filter((e) => e.id).map(key));
      merged.push(...works.filter((w) => !w.id || !known.has(key(w))));

      const freshCollections = new Map(collections.map((c) => [c.name, c]));
      const keptCollections = this.collections().filter((c) => !freshCollections.has(c.name));
      this.publish(merged, [...keptCollections, ...collections], copies ?? this.copies());
    } catch {
      // the listing stays as it was: still right about everything but what the run changed,
      // and the next time the library is opened reads it all again
    }
  }

  /** Hide a work from the listing. Its files and its index entry are left as they are. */
  async hide(work: Bookmark): Promise<void> {
    if (!work.id) return;
    const next = new Map(this.hidden());
    next.set(hiddenKey(work), {
      key: hiddenKey(work),
      id: work.id,
      kind: bookmarkTypeOf(work),
      title: work.title ?? '',
      authors: work.authors ?? [],
      hidden_on: new Date().toISOString(),
    });
    await this.saveHidden(next);
  }

  async unhide(work: Bookmark): Promise<void> {
    const next = new Map(this.hidden());
    next.delete(hiddenKey(work));
    await this.saveHidden(next);
  }

  /** shown at once and written to the library; if the write fails the change is undone */
  private async saveHidden(next: Map<string, HiddenWork>): Promise<void> {
    const store = this.store();
    if (!store) throw new Error('this library can only be read, so nothing can be hidden in it');
    const before = this.hidden();
    this.hidden.set(next);
    try {
      const document = { hidden: [...next.values()] };
      await store.write(HIDDEN_FILE, new Response(JSON.stringify(document, null, 2) + '\n'));
    } catch (error) {
      this.hidden.set(before);
      throw error;
    }
  }

  private async readHidden(generation: number, exists = true): Promise<void> {
    const store = this.store();
    if (!store || !exists) {
      this.hidden.set(new Map());
      return;
    }
    try {
      const text = await store.read(HIDDEN_FILE);
      if (generation === this.generation) this.hidden.set(readHiddenFile(text ?? ''));
    } catch {
      // unreadable: nothing is hidden, and the next hide writes a good file
      if (generation === this.generation) this.hidden.set(new Map());
    }
  }

  /** works/ listed again, for the copies a run downloaded, replaced or renamed */
  private async listCopies(): Promise<Copies | null> {
    if (this.showing === 'dropbox') {
      const folder = this.dropbox.folder();
      if (!folder) return null;
      return dropboxCopies(await this.dropbox.listFiles(`${folder.path}/${WORKS_FOLDER}`, true), folder.path);
    }
    if (!this.localHandle) return null;
    return this.mapCopies(await this.folders.readSubfolder(this.localHandle, WORKS_FOLDER));
  }

  /** Show `works` and `collections` as the library, with `copies` as its downloaded files. */
  private publish(works: Bookmark[], collections: Collection[], copies: Copies): void {
    this.entries = works;
    // no listing order is kept: the works list sorts by when each was bookmarked
    collections.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
    this.collections.set(collections);
    this.copies.set(copies);
    const byId = new Map<string, Bookmark>();
    const seriesById = new Map<string, Bookmark>();
    const externalsById = new Map<string, Bookmark>();
    for (const entry of works) {
      if (!entry.id) continue;
      if (isWorkEntry(entry)) byId.set(entry.id, entry);
      else if (entry.bookmark_type === 'series bookmark') seriesById.set(entry.id, entry);
      else if (entry.bookmark_type === 'external work') externalsById.set(entry.id, entry);
    }
    this.worksById.set(byId);
    this.seriesById.set(seriesById);
    this.externalsById.set(externalsById);

    // the listing is your bookmarks, and every other work in the index marked with where it
    // came from - but not a work that is only here because a series holds it (that is in its
    // card), nor a series you did not bookmark
    const inBookmarkedSeries = new Set(
      [...seriesById.values()].filter(isBookmarkEntry).flatMap((series) => series.work_ids ?? []),
    );
    const bookmarks = works.filter((entry) => isListedEntry(entry, inBookmarkedSeries));
    if (bookmarks.length === 0) {
      // collections synced but nothing indexed yet: the collections page still works
      this.data.set(null);
      this.sourceName.set(`${collections.length} collections`);
      return;
    }

    this.data.set({
      source: works.find((w) => w.source)?.source ?? '',
      // newer files record when they were last checked; older ones a single retrieval
      retrieved:
        works.find((w) => w.last_indexed)?.last_indexed ??
        works.find((w) => w.retrieved)?.retrieved ??
        '',
      count: bookmarks.length,
      works: bookmarks,
    });
    this.sourceName.set(`${bookmarks.length} bookmarks`);
  }

  /**
   * Each json file is one bookmark or one collection. A file holding a `works` array is
   * read as well, so an export from the older single-file version of this still opens.
   *
   * The two kinds are told apart by shape rather than by which folder they came from: a
   * folder read through the file system access api arrives flat, with the paths gone.
   */
  private async readRecords(
    jsonFiles: File[],
    note?: NoteProgress,
  ): Promise<{ works: Bookmark[]; collections: Collection[] }> {
    let done = 0;
    note?.({ stage: 'reading', done, total: jsonFiles.length });
    const parsed = await Promise.all(
      jsonFiles.map(async (file) => {
        try {
          return JSON.parse(await file.text()) as unknown;
        } catch {
          return null; // a folder can hold json that has nothing to do with us
        } finally {
          note?.({ stage: 'reading', done: ++done, total: jsonFiles.length });
        }
      }),
    );

    const works: Bookmark[] = [];
    const collections: Collection[] = [];
    for (const entry of parsed) {
      if (!entry || typeof entry !== 'object') continue;

      // the run history lives in a subfolder of the downloads folder, and a folder read
      // here arrives flat - so a run record has to be recognised by shape and passed over,
      // or it is rendered as a bookmark on the strength of carrying an id
      if (isRunRecord(entry)) continue;

      // checked before the works array, since a collection also holds a list of works
      if (isCollectionRecord(entry)) {
        const collection = flattenCollection(entry);
        if (collection) collections.push(collection);
        continue;
      }

      const aggregate = entry as BookmarksExport;
      if (Array.isArray(aggregate.works)) {
        works.push(...aggregate.works);
        continue;
      }
      const record = flattenRecord(entry);
      if (record) works.push(record);
    }
    return { works, collections };
  }

  /** each work's newest copy in every format, from the files in works/ */
  private mapCopies(files: File[]): Copies {
    const copies = emptyCopies();
    for (const file of files) {
      const format = openableFormat(baseName(file));
      if (!format) continue;
      const id = workIdFromFilename(baseName(file));
      if (!id) continue;
      const map = copies[format];
      const existing = map.get(id) as File | undefined;
      // the newest version by the date in its name, as a run would judge it - not whichever
      // file was touched last, which a copy or a sync tool can change
      if (!existing || isNewerCopy(baseName(file), file.lastModified,
          { name: baseName(existing), modified: existing.lastModified })) {
        map.set(id, file);
      }
    }
    return copies;
  }
}

/** which of the formats the listing opens a file is, if any */
function openableFormat(name: string): OpenableFormat | null {
  for (const format of Object.keys(OPENABLE) as OpenableFormat[]) {
    if (OPENABLE[format].test(name)) return format;
  }
  return null;
}

function relativePath(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

function baseName(file: File): string {
  return relativePath(file).split(/[\\/]/).pop() ?? file.name;
}

function jsonOf(files: File[]): File[] {
  return files.filter((f) => /\.json$/i.test(baseName(f)));
}

/**
 * Each work's newest copy in every format, from a Dropbox listing - works/ and nowhere else,
 * the same place a run looks, and newest by the date in its name, as a run would judge it.
 */
function dropboxCopies(files: DropboxFile[], root: string): Copies {
  const copies = emptyCopies();
  for (const file of files) {
    const format = openableFormat(file.name);
    if (!format) continue;
    const inside = file.path.slice(root.length).split('/').filter(Boolean);
    if (inside[0]?.toLowerCase() !== WORKS_FOLDER) continue;
    const id = workIdFromFilename(file.name);
    if (!id) continue;
    const map = copies[format];
    const existing = map.get(id) as DropboxCopy | undefined;
    if (!existing || isNewerCopy(file.name, file.modified,
        { name: existing.dropboxPath, modified: existing.modified })) {
      map.set(id, { dropboxPath: file.path, modified: file.modified });
    }
  }
  return copies;
}

/**
 * The page's list of hidden works, at the top of the library. The helper never reads it - a run
 * only looks for files named for a work - and setting up a library only moves loose works, so
 * nothing else touches it.
 */
export const HIDDEN_FILE = 'hidden-works.json';

/** one hidden work, with enough said about it to recognise it in the file by hand */
export interface HiddenWork {
  key: string;
  id: string;
  kind: string;
  title: string;
  authors: string[];
  hidden_on: string;
}

/** a work and an external work can share a number, so the kind is part of the key */
export function hiddenKey(work: Bookmark): string {
  return `${bookmarkTypeOf(work)}:${work.id}`;
}

function readHiddenFile(text: string): Map<string, HiddenWork> {
  try {
    const parsed = JSON.parse(text) as { hidden?: unknown };
    const list = Array.isArray(parsed?.hidden) ? (parsed.hidden as HiddenWork[]) : [];
    return new Map(list.filter((h) => h && typeof h.key === 'string').map((h) => [h.key, h]));
  } catch {
    return new Map();
  }
}
