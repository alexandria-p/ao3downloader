import { Injectable, inject, signal } from '@angular/core';
import { Bookmark, BookmarksExport, flattenRecord, workIdFromFilename } from './bookmarks';
import { Collection, flattenCollection, isCollectionRecord } from './collections';
import { DirectoryHandle, FolderStore } from './folder-store';

/**
 * Reads a downloads folder that ao3downloader wrote into.
 *
 * Everything stays in the browser - the files are read in the page, never uploaded. The
 * folder is picked once and the handle is kept, so later visits load it with no clicks.
 */
@Injectable({ providedIn: 'root' })
export class Library {
  readonly data = signal<BookmarksExport | null>(null);
  readonly collections = signal<Collection[]>([]);
  readonly sourceName = signal('');
  readonly folderName = signal('');
  readonly htmlFiles = signal<Map<string, File>>(new Map());
  readonly error = signal('');
  readonly loading = signal(false);
  /** a folder is remembered but the browser wants the permission confirmed again */
  readonly needsReconnect = signal(false);

  private readonly store = inject(FolderStore);

  readonly canPickFolder = this.store.supported();

  private handle: DirectoryHandle | null = null;

  /** Called at startup: reopen the remembered folder if it can still be read. */
  async restore(): Promise<void> {
    const handle = await this.store.recall();
    if (!handle) return;

    this.handle = handle;
    this.folderName.set(handle.name);

    if ((await this.store.permission(handle, false)) !== 'granted') {
      // asking needs a click behind it, so surface a button instead
      this.needsReconnect.set(true);
      return;
    }
    await this.readHandle(handle);
  }

  /** Pick a folder and remember it. */
  async pickFolder(): Promise<void> {
    let handle: DirectoryHandle;
    try {
      handle = await this.store.pick();
    } catch {
      return; // the picker was dismissed
    }
    this.handle = handle;
    this.folderName.set(handle.name);
    this.needsReconnect.set(false);
    await this.store.remember(handle);
    await this.readHandle(handle);
  }

  /** Confirm permission for the remembered folder, from a click. */
  async reconnect(): Promise<void> {
    if (!this.handle) return;
    if ((await this.store.permission(this.handle, true)) !== 'granted') {
      this.error.set('Permission to read that folder was declined.');
      return;
    }
    this.needsReconnect.set(false);
    await this.readHandle(this.handle);
  }

  async forget(): Promise<void> {
    await this.store.forget();
    this.handle = null;
    this.folderName.set('');
    this.needsReconnect.set(false);
    this.data.set(null);
    this.collections.set([]);
    this.sourceName.set('');
    this.htmlFiles.set(new Map());
  }

  /** Fallback for browsers without a directory picker, and for loading a single json. */
  async load(fileList: FileList | null): Promise<void> {
    const files = Array.from(fileList ?? []);
    if (files.length === 0) return;
    await this.ingest(files);
  }

  private async readHandle(handle: DirectoryHandle): Promise<void> {
    this.loading.set(true);
    try {
      await this.ingest(await this.store.read(handle));
    } catch {
      this.error.set(`Could not read ${handle.name}.`);
    } finally {
      this.loading.set(false);
    }
  }

  private async ingest(files: File[]): Promise<void> {
    this.error.set('');
    this.loading.set(true);
    try {
      const jsonFiles = files.filter((f) => /\.json$/i.test(baseName(f)));
      if (jsonFiles.length === 0) {
        this.error.set(
          'No json files in that folder. Pick the folder ao3downloader saves into - the ' +
            'DownloadFolder from settings.ini - which should hold your .json metadata files ' +
            'alongside your downloaded works.',
        );
        return;
      }

      const { works, collections } = await this.readRecords(jsonFiles);
      if (works.length === 0 && collections.length === 0) {
        this.error.set(
          `Found ${jsonFiles.length} json file(s) in there, but none of them look like an ` +
            'ao3downloader export.',
        );
        return;
      }

      // one file per bookmark, so the listing order has to be restored from the records
      works.sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
      collections.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
      this.collections.set(collections);
      this.htmlFiles.set(this.mapHtmlFiles(files));

      if (works.length === 0) {
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
        count: works.length,
        works,
      });
      this.sourceName.set(`${works.length} works`);
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

  private mapHtmlFiles(files: File[]): Map<string, File> {
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

function baseName(file: File): string {
  const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
  return path.split(/[\\/]/).pop() ?? file.name;
}
