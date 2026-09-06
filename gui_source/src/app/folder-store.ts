/**
 * Remembers which folder was picked, so it only has to be chosen once.
 *
 * A page cannot read a path off disk - it cannot read settings.ini and go to the folder
 * named there. What it can do is keep the handle the user granted, in IndexedDB, and reuse
 * it on later visits. localStorage is no good for this: a directory handle is a structured
 * object, not a string.
 */

import { Injectable } from '@angular/core';

const DB_NAME = 'ao3-bookmarks';
const STORE = 'handles';
const KEY = 'downloads-folder';

/** Chromium exposes these; other browsers fall back to the folder input. */
export interface DirectoryHandle {
  readonly name: string;
  values(): AsyncIterableIterator<DirectoryHandle | FileHandle>;
  readonly kind: 'directory';
  queryPermission?(options: { mode: 'read' }): Promise<PermissionState>;
  requestPermission?(options: { mode: 'read' }): Promise<PermissionState>;
}

export interface FileHandle {
  readonly kind: 'file';
  readonly name: string;
  getFile(): Promise<File>;
}

export function supportsDirectoryPicker(): boolean {
  return typeof (globalThis as { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function';
}

export function showDirectoryPicker(): Promise<DirectoryHandle> {
  const picker = (globalThis as unknown as {
    showDirectoryPicker(options?: { mode?: 'read'; id?: string }): Promise<DirectoryHandle>;
  }).showDirectoryPicker;
  // `id` makes the browser reopen at the same place next time
  return picker({ mode: 'read', id: 'ao3downloads' });
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

export async function rememberFolder(handle: DirectoryHandle): Promise<void> {
  try {
    await withStore('readwrite', (store) => store.put(handle, KEY) as IDBRequest<IDBValidKey>);
  } catch {
    // a private window or blocked site data just means it has to be picked again
  }
}

export async function recallFolder(): Promise<DirectoryHandle | null> {
  try {
    return (await withStore<DirectoryHandle | undefined>('readonly', (store) => store.get(KEY))) ?? null;
  } catch {
    return null;
  }
}

export async function forgetFolder(): Promise<void> {
  try {
    await withStore('readwrite', (store) => store.delete(KEY) as IDBRequest<undefined>);
  } catch {
    // nothing to clean up
  }
}

/**
 * Whether the stored handle can be read right now. `request` needs a user gesture behind
 * it, so startup only ever queries - reconnecting is done from a button.
 */
export async function folderPermission(
  handle: DirectoryHandle,
  request: boolean,
): Promise<PermissionState> {
  const granted = await handle.queryPermission?.({ mode: 'read' });
  if (granted === 'granted' || !request) return granted ?? 'prompt';
  return (await handle.requestPermission?.({ mode: 'read' })) ?? 'prompt';
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
}
