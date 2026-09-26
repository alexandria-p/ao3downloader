/**
 * The library the page has open - a folder on this computer, or the Dropbox app folder -
 * as the one thing that reads and writes it.
 *
 * **The page owns the library; the helper only asks.** The helper cannot reach either kind:
 * a local folder is a File System Access handle, which never tells anyone its path, and
 * Dropbox needs the session the page signed in for. So during a run the helper sends each
 * read and write it needs as a `storage` event, and the page carries it out here and
 * answers (`answerStorage`). All the rules about what is outdated, what may be replaced and
 * what counts as saved stay in the helper; only the bytes pass through the page.
 *
 * Paths are always relative to the library and joined with '/': `works/123 A.html`,
 * `indexing/123.json`, `''` for the library itself. Neither kind can step outside it.
 */

import { DropboxError, DropboxSession } from './dropbox';
import type { RunHistory } from './jobs';
import {
  DirectoryHandle,
  FileHandle,
  folderAt,
  folderPermission,
  streamFile,
  writeFile,
} from './folder-store';

export interface LibraryStore {
  /** a name for the library, for the run dialog to say where files are going */
  readonly label: string;
  /** whether the page can still reach it - permission kept, session alive */
  check(): Promise<void>;
  /** every file below `path`, as library paths; nothing when the folder is not there */
  list(path: string, recursive: boolean): Promise<string[]>;
  /** a text file's contents, or null when there is no such file */
  read(path: string): Promise<string | null>;
  /** put a file in place, making the folders above it; answers the size now stored */
  write(path: string, body: Response): Promise<number>;
  size(path: string): Promise<number | null>;
  /** remove a file. One already gone is not an error */
  delete(path: string): Promise<void>;
  /** rename a file; refuses, with an error, to write over one already at the new name */
  rename(from: string, to: string): Promise<void>;
  mkdir(path: string): Promise<void>;
}

/** one request from the helper, as it arrives on the event stream */
export interface StorageRequest {
  id: string;
  op: string;
  path?: string;
  to?: string;
  recursive?: boolean;
  blob?: boolean;
}

/**
 * Carry out one request and say how it went, in the shape the helper reads.
 *
 * Every failure becomes `{error}` rather than a thrown error: the helper turns that into an
 * `OSError`, which is exactly what every path there already expects a folder to raise - a
 * damaged index file skipped, a download recorded as failed.
 */
export async function answerStorage(
  store: LibraryStore,
  request: StorageRequest,
  collect: () => Promise<Response>,
): Promise<Record<string, unknown>> {
  const path = request.path ?? '';
  try {
    switch (request.op) {
      case 'check':
        await store.check();
        return {};
      case 'mkdir':
        await store.mkdir(path);
        return {};
      case 'list':
        return { files: await store.list(path, !!request.recursive) };
      case 'read': {
        const text = await store.read(path);
        return text === null ? { missing: true } : { text };
      }
      case 'write':
        return { size: await store.write(path, await collect()) };
      case 'size':
        return { size: await store.size(path) };
      case 'delete':
        await store.delete(path);
        return {};
      case 'rename':
        await store.rename(path, request.to ?? '');
        return {};
      default:
        return { error: `the page does not know how to ${request.op}` };
    }
  } catch (error) {
    return { error: error instanceof Error ? error.message : String(error) };
  }
}

/** how many runs the history page shows */
const HISTORY_LIMIT = 100;

/**
 * Every run on record in the library, newest first - what the helper's `read_runs` did,
 * done here now that the page holds the library.
 *
 * A record that cannot be read is skipped rather than ending the listing.
 */
export async function readRunHistory(store: LibraryStore): Promise<RunHistory[]> {
  // named for when they started, so newest first is simply by name
  const files = (await store.list('runs', false))
    .filter((path) => /\.json$/i.test(path))
    .sort()
    .reverse();

  const found: RunHistory[] = [];
  for (const path of files) {
    if (found.length >= HISTORY_LIMIT) break;
    try {
      const record = JSON.parse((await store.read(path)) ?? '') as RunHistory & { log?: string[] };
      if (!record || typeof record !== 'object') continue;
      // the console log is not shown here, and can run to thousands of lines
      const { log: _log, ...rest } = record;
      found.push({ ...rest, file: path.split('/').pop() ?? path });
    } catch {
      continue;
    }
  }
  return found;
}

function split(path: string): { folders: string[]; name: string } {
  const parts = path.split('/').filter(Boolean);
  return { folders: parts, name: parts.pop() ?? '' };
}

// region a folder on this computer

export class LocalLibraryStore implements LibraryStore {
  constructor(private readonly handle: DirectoryHandle) {}

  get label(): string {
    return this.handle.name;
  }

  async check(): Promise<void> {
    if ((await folderPermission(this.handle, false)) !== 'granted') {
      throw new Error(
        `This page no longer has permission to use ${this.handle.name}. Reconnect it and ` +
          'start the run again.',
      );
    }
  }

  /** the folder at a path, or null - never made just by asking */
  private async existing(folders: string[]): Promise<DirectoryHandle | null> {
    let at = this.handle;
    for (const name of folders) {
      if (!at.getDirectoryHandle) return null;
      try {
        at = await at.getDirectoryHandle(name);
      } catch {
        return null;
      }
    }
    return at;
  }

  private async file(path: string): Promise<FileHandle | null> {
    const { folders, name } = split(path);
    const folder = await this.existing(folders);
    if (!folder?.getFileHandle) return null;
    try {
      return await folder.getFileHandle(name);
    } catch {
      return null;
    }
  }

  async list(path: string, recursive: boolean): Promise<string[]> {
    const start = await this.existing(path.split('/').filter(Boolean));
    if (!start) return [];
    const found: string[] = [];
    const walk = async (folder: DirectoryHandle, prefix: string) => {
      for await (const entry of folder.values()) {
        if (entry.kind === 'file') found.push(prefix + entry.name);
        else if (recursive) await walk(entry, `${prefix}${entry.name}/`);
      }
    };
    await walk(start, path ? `${path.replace(/\/+$/, '')}/` : '');
    return found;
  }

  async read(path: string): Promise<string | null> {
    const file = await this.file(path);
    return file ? (await file.getFile()).text() : null;
  }

  async write(path: string, body: Response): Promise<number> {
    // straight from the helper to disk, never held whole; an aborted stream leaves no file
    if (body.body) await streamFile(this.handle, path, body.body);
    else await writeFile(this.handle, path, '');
    return (await this.size(path)) ?? 0;
  }

  async size(path: string): Promise<number | null> {
    const file = await this.file(path);
    return file ? (await file.getFile()).size : null;
  }

  async delete(path: string): Promise<void> {
    const { folders, name } = split(path);
    const folder = await this.existing(folders);
    if (!folder?.removeEntry || !(await this.file(path))) return; // already gone
    await folder.removeEntry(name);
  }

  /**
   * Copy, check, then delete: a browser folder has no rename a page can rely on, and doing
   * it this way round means a rename that fails partway leaves the original where it was.
   */
  async rename(from: string, to: string): Promise<void> {
    const original = await this.file(from);
    if (!original) throw new Error(`${from} is not there to rename`);
    if (await this.file(to)) throw new Error(`${to} is already there`);

    const content = await original.getFile();
    await writeFile(this.handle, to, content);
    if ((await this.size(to)) !== content.size) {
      await this.delete(to);
      throw new Error(`${to} did not arrive whole, so ${from} was left as it was`);
    }
    await this.delete(from);
  }

  async mkdir(path: string): Promise<void> {
    await folderAt(this.handle, path.split('/').filter(Boolean));
  }
}

// endregion

// region the Dropbox app folder

export class DropboxLibraryStore implements LibraryStore {
  readonly label = 'Dropbox app folder';

  constructor(private readonly dropbox: DropboxSession) {}

  async check(): Promise<void> {
    if (this.dropbox.status() !== 'signed-in') {
      throw new Error('The page is not signed in to Dropbox any more. Sign in and start the run again.');
    }
  }

  async list(path: string, recursive: boolean): Promise<string[]> {
    const files = await this.dropbox.listFiles(remote(path), recursive);
    return files.map((file) => file.path.replace(/^\//, ''));
  }

  async read(path: string): Promise<string | null> {
    try {
      return await (await this.dropbox.download(remote(path))).text();
    } catch (error) {
      if (notFound(error)) return null;
      throw error;
    }
  }

  async write(path: string, body: Response): Promise<number> {
    return this.dropbox.upload(remote(path), await body.blob());
  }

  async size(path: string): Promise<number | null> {
    return this.dropbox.fileSize(remote(path));
  }

  async delete(path: string): Promise<void> {
    await this.dropbox.deleteFile(remote(path));
  }

  async rename(from: string, to: string): Promise<void> {
    await this.dropbox.moveFile(remote(from), remote(to));
  }

  async mkdir(path: string): Promise<void> {
    await this.dropbox.makeFolder(path.replace(/^\/+/, ''));
  }
}

/** a library path as the Dropbox api names it: `''` for the app folder, `/works/x` below it */
function remote(path: string): string {
  const clean = path.split('/').filter(Boolean).join('/');
  return clean ? `/${clean}` : '';
}

function notFound(error: unknown): boolean {
  return error instanceof DropboxError && /not_found/.test(error.summary);
}

// endregion
