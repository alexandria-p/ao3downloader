/**
 * The folder the user picked, and everything done to it.
 *
 * **A page never learns a path.** `showDirectoryPicker` hands back a handle, not
 * `D:\Fics`, and there is no way to ask it for one - so nothing here can tell the helper
 * where the folder is, and nothing should try. What a handle *can* do is far more than
 * read: granted `readwrite`, it creates subfolders and writes files, which is what lets the
 * page own the library outright instead of asking a helper to write on its behalf.
 *
 * The handle itself is kept in IndexedDB so the folder only has to be chosen once.
 * localStorage is no good for it: a directory handle is a structured object, not a string.
 */

import { Injectable } from '@angular/core';

const DB_NAME = 'ao3-bookmarks';
const STORE = 'handles';
const KEY = 'downloads-folder';

/** what the page needs granted to own the folder rather than only look at it */
export type FolderAccess = 'read' | 'readwrite';

/** Chromium exposes these; other browsers fall back to the folder input. */
export interface DirectoryHandle {
  readonly name: string;
  values(): AsyncIterableIterator<DirectoryHandle | FileHandle>;
  readonly kind: 'directory';
  queryPermission?(options: { mode: FolderAccess }): Promise<PermissionState>;
  requestPermission?(options: { mode: FolderAccess }): Promise<PermissionState>;
  getDirectoryHandle?(name: string, options?: { create?: boolean }): Promise<DirectoryHandle>;
  getFileHandle?(name: string, options?: { create?: boolean }): Promise<FileHandle>;
  removeEntry?(name: string, options?: { recursive?: boolean }): Promise<void>;
}

export interface FileHandle {
  readonly kind: 'file';
  readonly name: string;
  getFile(): Promise<File>;
  createWritable?(): Promise<WritableFile>;
}

/** the stream a file handle opens; nothing lands on disk until `close` */
export interface WritableFile {
  write(data: BufferSource | Blob | string): Promise<void>;
  close(): Promise<void>;
}

export function supportsDirectoryPicker(): boolean {
  return typeof (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function';
}

export function showDirectoryPicker(): Promise<DirectoryHandle> {
  const picker = (globalThis as unknown as {
    showDirectoryPicker(options?: { mode?: FolderAccess; id?: string }): Promise<DirectoryHandle>;
  }).showDirectoryPicker;
  // readwrite, because this folder is where everything is written as well as read - the
  // index, the works, the images, the run history. asking for read alone would mean asking
  // again the first time anything had to be saved.
  // `id` makes the browser reopen at the same place next time
  return picker({ mode: 'readwrite', id: 'ao3downloads' });
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function withStore<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const request = run(db.transaction(STORE, mode).objectStore(STORE));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      }),
  );
}

/**
 * One value in this page's IndexedDB store, by key. Shared with the Dropbox session, which
 * keeps its refresh token and chosen folder here beside the local folder's handle.
 *
 * All three swallow failure: a private window or blocked site data just means the thing
 * has to be chosen, or signed into, again.
 */
export async function putValue(key: string, value: unknown): Promise<void> {
  try {
    await withStore('readwrite', (store) => store.put(value, key) as IDBRequest<IDBValidKey>);
  } catch {
    // remembered for this visit only
  }
}

export async function getValue<T>(key: string): Promise<T | null> {
  try {
    return (await withStore<T | undefined>('readonly', (store) => store.get(key))) ?? null;
  } catch {
    return null;
  }
}

export async function deleteValue(key: string): Promise<void> {
  try {
    await withStore('readwrite', (store) => store.delete(key) as IDBRequest<undefined>);
  } catch {
    // nothing to clean up
  }
}

export function rememberFolder(handle: DirectoryHandle): Promise<void> {
  return putValue(KEY, handle);
}

export function recallFolder(): Promise<DirectoryHandle | null> {
  return getValue<DirectoryHandle>(KEY);
}

export function forgetFolder(): Promise<void> {
  return deleteValue(KEY);
}

/**
 * Whether the stored handle can be read right now. `request` needs a user gesture behind
 * it, so startup only ever queries - reconnecting is done from a button.
 */
export async function folderPermission(
  handle: DirectoryHandle,
  request: boolean,
): Promise<PermissionState> {
  const granted = await handle.queryPermission?.({ mode: 'readwrite' });
  if (granted === 'granted' || !request) return granted ?? 'prompt';
  return (await handle.requestPermission?.({ mode: 'readwrite' })) ?? 'prompt';
}

/**
 * The folder a relative path names, creating the steps along the way.
 *
 * Paths are joined with '/' and are always relative to the picked folder - `indexing`,
 * `images`, `runs`. There is no way to step outside it, which is the whole point of the
 * handle: the grant is that folder and nothing above it.
 */
export async function folderAt(
  handle: DirectoryHandle,
  segments: string[],
): Promise<DirectoryHandle> {
  let at = handle;
  for (const segment of segments) {
    if (!segment || segment === '.') continue;
    if (!at.getDirectoryHandle) throw new Error('this browser cannot create folders');
    at = await at.getDirectoryHandle(segment, { create: true });
  }
  return at;
}

/**
 * Write one file into the folder, at a path relative to it.
 *
 * Nothing reaches disk until `close`, so a write that fails partway leaves no half-file
 * behind - the same guarantee the helper's own writes were built around.
 */
export async function writeFile(
  handle: DirectoryHandle,
  path: string,
  contents: BufferSource | Blob | string,
): Promise<void> {
  const parts = path.split('/').filter(Boolean);
  const name = parts.pop();
  if (!name) throw new Error('no file name in ' + path);

  const folder = await folderAt(handle, parts);
  if (!folder.getFileHandle) throw new Error('this browser cannot write files');
  const file = await folder.getFileHandle(name, { create: true });
  if (!file.createWritable) throw new Error('this browser cannot write files');

  const stream = await file.createWritable();
  try {
    await stream.write(contents);
  } finally {
    await stream.close();
  }
}

/**
 * Write a response body straight into the folder, without ever holding it whole.
 *
 * `createWritable` returns a real `WritableStream`, so the bytes go from the socket to disk
 * in chunks and the browser never has the file in memory. That matters because the other
 * end of this is the helper handing over a work it has already downloaded: without
 * streaming, a large epub would sit in python's memory and the page's at the same time.
 *
 * **`pipeTo` closes the file on success and aborts it on failure**, and an aborted
 * `FileSystemWritableFileStream` discards what it had - so a transfer that dies partway
 * leaves no file rather than a truncated one. That is the same guarantee the helper's own
 * writes were built around, and it is why this does not close the stream by hand.
 */
export async function streamFile(
  handle: DirectoryHandle,
  path: string,
  body: ReadableStream<Uint8Array>,
): Promise<void> {
  const parts = path.split('/').filter(Boolean);
  const name = parts.pop();
  if (!name) throw new Error('no file name in ' + path);

  const folder = await folderAt(handle, parts);
  if (!folder.getFileHandle) throw new Error('this browser cannot write files');
  const file = await folder.getFileHandle(name, { create: true });
  if (!file.createWritable) throw new Error('this browser cannot write files');

  const destination = (await file.createWritable()) as unknown as WritableStream<Uint8Array>;
  await body.pipeTo(destination);
}

/** Remove one file, by a path relative to the picked folder. Missing is not an error. */
export async function removeFile(handle: DirectoryHandle, path: string): Promise<boolean> {
  const parts = path.split('/').filter(Boolean);
  const name = parts.pop();
  if (!name) return false;
  try {
    const folder = await folderAt(handle, parts);
    if (!folder.removeEntry) return false;
    await folder.removeEntry(name);
    return true;
  } catch {
    // already gone, or never there
    return false;
  }
}

/** The names of the folders and files directly inside a folder. */
export async function topLevel(
  handle: DirectoryHandle,
): Promise<{ folders: string[]; files: string[] }> {
  const folders: string[] = [];
  const files: string[] = [];
  for await (const entry of handle.values()) {
    (entry.kind === 'directory' ? folders : files).push(entry.name);
  }
  return { folders, files };
}

/** Every file below one subfolder - none when it is not there, rather than making it. */
export async function readSubfolder(handle: DirectoryHandle, name: string): Promise<File[]> {
  if (!handle.getDirectoryHandle) return [];
  let folder: DirectoryHandle;
  try {
    folder = await handle.getDirectoryHandle(name);
  } catch {
    return [];
  }
  return readFolder(folder);
}

/**
 * Move a file from a folder into one of its subfolders, reporting whether it moved.
 *
 * Copy, check, then delete: the copy has to be all there before the original goes, so a
 * move that fails partway leaves the file where it was rather than nowhere. A file already
 * in the subfolder under that name is never written over - the move is refused and both are
 * left alone.
 */
export async function moveIntoSubfolder(
  handle: DirectoryHandle,
  name: string,
  subfolder: string,
): Promise<boolean> {
  if (!handle.getDirectoryHandle || !handle.getFileHandle || !handle.removeEntry) return false;
  const destination = await handle.getDirectoryHandle(subfolder, { create: true });
  if (!destination.getFileHandle) return false;
  try {
    await destination.getFileHandle(name);
    return false; // something is already called that there
  } catch {
    // nothing there, which is what a move needs
  }

  const original = await (await handle.getFileHandle(name)).getFile();
  await writeFile(destination, name, original);
  const copy = await (await destination.getFileHandle(name)).getFile();
  if (copy.size !== original.size) {
    await removeFile(destination, name);
    return false;
  }
  await handle.removeEntry(name);
  return true;
}

/** Every file in the folder, including subfolders. */
export async function readFolder(handle: DirectoryHandle): Promise<File[]> {
  const files: File[] = [];
  for await (const entry of handle.values()) {
    if (entry.kind === 'file') files.push(await entry.getFile());
    else files.push(...(await readFolder(entry)));
  }
  return files;
}

/**
 * The browser APIs above, behind an injectable seam. None of them exist in jsdom, and
 * Angular's test runner does not allow module mocking for relative imports, so this is
 * what lets the tests stand in for the file system.
 */
@Injectable({ providedIn: 'root' })
export class FolderStore {
  supported(): boolean {
    return supportsDirectoryPicker();
  }

  pick(): Promise<DirectoryHandle> {
    return showDirectoryPicker();
  }

  remember(handle: DirectoryHandle): Promise<void> {
    return rememberFolder(handle);
  }

  recall(): Promise<DirectoryHandle | null> {
    return recallFolder();
  }

  forget(): Promise<void> {
    return forgetFolder();
  }

  permission(handle: DirectoryHandle, request: boolean): Promise<PermissionState> {
    return folderPermission(handle, request);
  }

  read(handle: DirectoryHandle): Promise<File[]> {
    return readFolder(handle);
  }

  readSubfolder(handle: DirectoryHandle, name: string): Promise<File[]> {
    return readSubfolder(handle, name);
  }

  topLevel(handle: DirectoryHandle): Promise<{ folders: string[]; files: string[] }> {
    return topLevel(handle);
  }

  async makeFolder(handle: DirectoryHandle, name: string): Promise<void> {
    await folderAt(handle, [name]);
  }

  moveIntoSubfolder(handle: DirectoryHandle, name: string, subfolder: string): Promise<boolean> {
    return moveIntoSubfolder(handle, name, subfolder);
  }

  write(
    handle: DirectoryHandle,
    path: string,
    contents: BufferSource | Blob | string,
  ): Promise<void> {
    return writeFile(handle, path, contents);
  }

  remove(handle: DirectoryHandle, path: string): Promise<boolean> {
    return removeFile(handle, path);
  }

  /** for a downloaded work: from the socket to disk, never held whole in memory */
  stream(
    handle: DirectoryHandle,
    path: string,
    body: ReadableStream<Uint8Array>,
  ): Promise<void> {
    return streamFile(handle, path, body);
  }
}
