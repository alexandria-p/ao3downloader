import { Injectable, inject, signal } from '@angular/core';
import {
  Bookmark,
  BookmarksExport,
  flattenRecord,
  isBookmarkEntry,
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

/** the folders whose json is the index, read in one zip each */
const INDEX_FOLDERS = ['indexing', 'collections'];
/** how many files to fetch at once when a folder is too big to come as one zip */
const PARALLEL_DOWNLOADS = 6;

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
  readonly htmlFiles = signal<Map<string, LocalCopy>>(new Map());
  /**
   * Every work in the index by work number - including works that are there only because a
   * series you bookmarked holds them, which the bookmarks listing leaves out. A series' card
   * and a collection both list works by number and look them up here.
   */
  readonly worksById = signal<Map<string, Bookmark>>(new Map());
  readonly error = signal('');
  readonly loading = signal(false);
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
    try {
      await this.setup.prepare(this.dropboxTarget(), APP_FOLDER_PATH);
      if (generation !== this.generation) return;
      this.store.set(new DropboxLibraryStore(this.dropbox));
      const files = await this.dropbox.listFiles(folder.path);
      if (generation !== this.generation) return;

      const inside = (file: DropboxFile) =>
        file.path.slice(folder.path.length).split('/').filter(Boolean);
      const indexFiles = files.filter(
        (f) => /\.json$/i.test(f.name) && INDEX_FOLDERS.includes(inside(f)[0]?.toLowerCase()),
      );
      const copies = new Map<string, LocalCopy>();
      for (const file of files) {
        if (!/\.html?$/i.test(file.name)) continue;
        // works/ and nowhere else - the same place a run looks
        if (inside(file)[0]?.toLowerCase() !== WORKS_FOLDER) continue;
        const id = workIdFromFilename(file.name);
        if (!id) continue;
        const existing = copies.get(id) as DropboxCopy | undefined;
        if (!existing || existing.modified < file.modified) {
          copies.set(id, { dropboxPath: file.path, modified: file.modified });
        }
      }

      const jsonFiles = await this.readDropboxIndex(folder.path, indexFiles);
      if (generation !== this.generation) return;
      await this.ingestRecords(jsonFiles, copies, false);
    } catch (error) {
      if (generation !== this.generation) return;
      this.error.set(
        `Could not read ${APP_FOLDER_PATH} from Dropbox. ` +
          (error instanceof Error ? error.message : ''),
      );
    } finally {
      if (generation === this.generation) this.loading.set(false);
    }
  }

  /** The contents of a downloaded work, to open it. */
  async readCopy(copy: LocalCopy): Promise<Blob> {
    if (copy instanceof Blob) return copy;
    // dropbox sends a file as octet-stream, which a tab would offer to save rather than show
    return new Blob([await this.dropbox.download(copy.dropboxPath)], { type: 'text/html' });
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
    this.htmlFiles.set(new Map());
    this.worksById.set(new Map());
  }

  /**
   * The index's json, read a folder at a time as a zip. A folder Dropbox will not zip -
   * more than 10,000 files, or a zip this page cannot read - is fetched file by file
   * instead, a few at a time.
   */
  private async readDropboxIndex(root: string, indexFiles: DropboxFile[]): Promise<File[]> {
    const read: File[] = [];
    for (const name of INDEX_FOLDERS) {
      const prefix = `${root}/${name}/`.toLowerCase();
      const wanted = indexFiles.filter((f) => f.path.toLowerCase().startsWith(prefix));
      if (wanted.length === 0) continue;
      try {
        const entries = await unzip(await this.dropbox.downloadZip(`${root}/${name}`));
        for (const entry of entries) {
          const file = entry.path.split('/').pop() ?? '';
          if (/\.json$/i.test(file)) read.push(new File([entry.data as BlobPart], file));
        }
      } catch {
        read.push(...(await this.downloadEach(wanted)));
      }
    }
    return read;
  }

  private async downloadEach(files: DropboxFile[]): Promise<File[]> {
    const read: File[] = [];
    let next = 0;
    const worker = async () => {
      while (next < files.length) {
        const file = files[next++];
        try {
          read.push(new File([await this.dropbox.download(file.path)], file.name));
        } catch {
          // one unreadable file should not hide the rest of the library
        }
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
      // the index can be anywhere it has ever been written, so all of it is read for json;
      // works only ever come from works/
      const everything = await this.folders.read(handle);
      const works = await this.folders.readSubfolder(handle, WORKS_FOLDER);
      if (!current()) return;
      // not strict: this folder has just been set up as a library, so an empty one is new,
      // not the wrong folder
      await this.ingestRecords(jsonOf(everything), this.mapHtmlFiles(works), false);
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
    await this.ingestRecords(jsonOf(files), this.mapHtmlFiles(works), true);
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
    copies: Map<string, LocalCopy>,
    strict: boolean,
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

      const { works, collections } = await this.readRecords(jsonFiles);
      if (works.length === 0 && collections.length === 0) {
        if (!strict) return;
        this.error.set(
          `Found ${jsonFiles.length} json file(s) in there, but none of them look like an ` +
            'ao3downloader export.',
        );
        return;
      }

      // no listing order is kept: the works list sorts by when each was bookmarked
      collections.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
      this.collections.set(collections);
      this.htmlFiles.set(copies);
      const byId = new Map<string, Bookmark>();
      for (const work of works) if (work.id && isWorkEntry(work)) byId.set(work.id, work);
      this.worksById.set(byId);

      // the listing is your bookmarks: works, series and external works you bookmarked,
      // but not a work that is only here because a series holds it - that is in its card
      const bookmarks = works.filter(isBookmarkEntry);
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
    } finally {
      this.loading.set(false);
    }
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
  ): Promise<{ works: Bookmark[]; collections: Collection[] }> {
    const parsed = await Promise.all(
      jsonFiles.map(async (file) => {
        try {
          return JSON.parse(await file.text()) as unknown;
        } catch {
          return null; // a folder can hold json that has nothing to do with us
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

  private mapHtmlFiles(files: File[]): Map<string, LocalCopy> {
    const map = new Map<string, File>();
    for (const file of files) {
      if (!/\.html?$/i.test(baseName(file))) continue;
      const id = workIdFromFilename(baseName(file));
      if (!id) continue;
      const existing = map.get(id);
      if (!existing || existing.lastModified < file.lastModified) map.set(id, file);
    }
    return map;
  }
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
