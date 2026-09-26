import { signal } from '@angular/core';
import { describe, expect, it } from 'vitest';
import { DropboxError, DropboxSession, DropboxStatus } from './dropbox';
import { DirectoryHandle, FileHandle } from './folder-store';
import {
  DropboxLibraryStore,
  LibraryStore,
  LocalLibraryStore,
  StorageRequest,
  answerStorage,
  readRunHistory,
} from './library-store';

/**
 * A folder tree in memory that can be read, written - including by piping a stream into
 * it, as a download from the helper is - and asked for permission.
 */
class MemoryFolder implements DirectoryHandle {
  readonly kind = 'directory' as const;
  readonly folders = new Map<string, MemoryFolder>();
  readonly files = new Map<string, string>();
  permission: PermissionState = 'granted';

  constructor(readonly name: string) {}

  async *values() {
    for (const folder of this.folders.values()) yield folder;
    for (const name of this.files.keys()) yield this.fileHandle(name);
  }

  async queryPermission() {
    return this.permission;
  }

  async getDirectoryHandle(name: string, options?: { create?: boolean }) {
    let folder = this.folders.get(name);
    if (!folder) {
      if (!options?.create) throw new Error('not found: ' + name);
      folder = new MemoryFolder(name);
      this.folders.set(name, folder);
    }
    return folder;
  }

  async getFileHandle(name: string, options?: { create?: boolean }) {
    if (!this.files.has(name)) {
      if (!options?.create) throw new Error('not found: ' + name);
      this.files.set(name, '');
    }
    return this.fileHandle(name);
  }

  async removeEntry(name: string) {
    if (!this.files.delete(name)) throw new Error('not found: ' + name);
  }

  /** what is at a path below here, for the tests to look at */
  at(path: string): string | undefined {
    const parts = path.split('/');
    const name = parts.pop()!;
    let folder: MemoryFolder | undefined = this;
    for (const part of parts) folder = folder?.folders.get(part);
    return folder?.files.get(name);
  }

  private fileHandle(name: string): FileHandle {
    return {
      kind: 'file',
      name,
      getFile: async () => new File([this.files.get(name) ?? ''], name),
      createWritable: async () => {
        let pending = '';
        const decoder = new TextDecoder();
        const land = () => {
          this.files.set(name, pending);
        };
        // a real stream, so a body can be piped in; and the two calls a plain write makes
        const stream = new WritableStream<Uint8Array>({
          write: (chunk) => {
            pending += decoder.decode(chunk, { stream: true });
          },
          close: land,
        });
        return Object.assign(stream, {
          write: async (data: BufferSource | Blob | string) => {
            pending += typeof data === 'string' ? data : data instanceof Blob ? await data.text() : '';
          },
          close: async () => land(),
        });
      },
    };
  }
}

const body = (text: string) => new Response(text);

/** an answer as the helper reads it */
interface Answer {
  text?: string;
  missing?: boolean;
  files?: string[];
  size?: number | null;
  error?: string;
}

async function ask(store: LibraryStore, request: Partial<StorageRequest>, content = ''): Promise<Answer> {
  return (await answerStorage(store, { id: 'r', op: 'check', ...request } as StorageRequest, async () =>
    body(content),
  )) as Answer;
}

describe('answering the helper, in a folder on this computer', () => {
  it('writes what the helper sends into the folder, making folders on the way', async () => {
    const folder = new MemoryFolder('Fics');
    const store = new LocalLibraryStore(folder);

    expect(await ask(store, { op: 'write', path: 'works/1 A.html' }, '<p>fic</p>')).toEqual({
      size: 10,
    });
    expect(folder.at('works/1 A.html')).toBe('<p>fic</p>');
  });

  it('reads a file back, and says plainly when there is none', async () => {
    const folder = new MemoryFolder('Fics');
    const store = new LocalLibraryStore(folder);
    await ask(store, { op: 'write', path: 'indexing/1.json' }, '{"id":"1"}');

    expect(await ask(store, { op: 'read', path: 'indexing/1.json' })).toEqual({ text: '{"id":"1"}' });
    expect(await ask(store, { op: 'read', path: 'indexing/2.json' })).toEqual({ missing: true });
    // asking about a folder does not make it
    expect(await ask(store, { op: 'read', path: 'nowhere/2.json' })).toEqual({ missing: true });
    expect(folder.folders.has('nowhere')).toBe(false);
  });

  it('lists files as library paths, all the way down or one level', async () => {
    const folder = new MemoryFolder('Fics');
    const store = new LocalLibraryStore(folder);
    await ask(store, { op: 'write', path: 'works/1 A.html' });
    await ask(store, { op: 'write', path: 'works/old/2 B.epub' });
    await ask(store, { op: 'write', path: 'runs/a.json' });

    expect((await ask(store, { op: 'list', path: 'works', recursive: true })).files).toEqual([
      'works/old/2 B.epub',
      'works/1 A.html',
    ]);
    expect((await ask(store, { op: 'list', path: 'works', recursive: false })).files).toEqual([
      'works/1 A.html',
    ]);
    expect((await ask(store, { op: 'list', path: '', recursive: true })).files).toHaveLength(3);
    expect((await ask(store, { op: 'list', path: 'images', recursive: true })).files).toEqual([]);
  });

  it('answers sizes, deletes, and treats a file already gone as deleted', async () => {
    const folder = new MemoryFolder('Fics');
    const store = new LocalLibraryStore(folder);
    await ask(store, { op: 'write', path: 'works/1 A.html' }, 'twelve bytes');

    expect(await ask(store, { op: 'size', path: 'works/1 A.html' })).toEqual({ size: 12 });
    expect(await ask(store, { op: 'delete', path: 'works/1 A.html' })).toEqual({});
    expect(await ask(store, { op: 'size', path: 'works/1 A.html' })).toEqual({ size: null });
    expect(await ask(store, { op: 'delete', path: 'works/1 A.html' })).toEqual({});
  });

  it('renames by copying, checking, then removing - and never writes over a file', async () => {
    const folder = new MemoryFolder('Fics');
    const store = new LocalLibraryStore(folder);
    await ask(store, { op: 'write', path: 'works/1 A.html' }, 'old');
    await ask(store, { op: 'write', path: 'works/2 B.html' }, 'other');

    expect(await ask(store, { op: 'rename', path: 'works/1 A.html', to: 'works/1 A 2024-06-01.html' })).toEqual({});
    expect(folder.at('works/1 A 2024-06-01.html')).toBe('old');
    expect(folder.at('works/1 A.html')).toBeUndefined();

    const refused = await ask(store, { op: 'rename', path: 'works/2 B.html', to: 'works/1 A 2024-06-01.html' });
    expect(refused.error).toContain('already there');
    expect(folder.at('works/1 A 2024-06-01.html')).toBe('old');
  });

  it('makes folders when asked', async () => {
    const folder = new MemoryFolder('Fics');
    await ask(new LocalLibraryStore(folder), { op: 'mkdir', path: 'runs' });
    expect(folder.folders.has('runs')).toBe(true);
  });

  it('says so when the page has lost permission to use the folder', async () => {
    const folder = new MemoryFolder('Fics');
    folder.permission = 'prompt';
    const answer = await ask(new LocalLibraryStore(folder), { op: 'check' });
    expect(answer.error).toContain('no longer has permission to use Fics');
  });

  it('turns anything that goes wrong into an answer rather than leaving the helper waiting', async () => {
    const store = new LocalLibraryStore(new MemoryFolder('Fics'));
    const answer = await answerStorage(
      store,
      { id: 'r', op: 'write', path: 'works/1.html' },
      async () => {
        throw new Error('could not collect the file (404)');
      },
    );
    expect(answer).toEqual({ error: 'could not collect the file (404)' });
    expect((await ask(store, { op: 'fly' })).error).toContain('does not know how to fly');
  });
});

/** the parts of the session a Dropbox library uses, in memory */
class FakeSession {
  readonly status = signal<DropboxStatus>('signed-in');
  files = new Map<string, string>();
  made: string[] = [];

  async listFiles(path: string, recursive = true) {
    return [...this.files.keys()]
      .filter((p) => p.startsWith(path + '/') && (recursive || !p.slice(path.length + 1).includes('/')))
      .map((p) => ({ name: p.split('/').pop()!, path: p, modified: 0 }));
  }
  async download(path: string) {
    if (!this.files.has(path)) throw new DropboxError('not found', 409, 'path/not_found/.');
    return new Blob([this.files.get(path)!]);
  }
  async upload(path: string, content: Blob) {
    this.files.set(path, await content.text());
    return content.size;
  }
  async fileSize(path: string) {
    return this.files.has(path) ? this.files.get(path)!.length : null;
  }
  async deleteFile(path: string) {
    this.files.delete(path);
  }
  async moveFile(from: string, to: string) {
    if (this.files.has(to)) throw new DropboxError('to/conflict', 409, 'to/conflict/file/.');
    this.files.set(to, this.files.get(from)!);
    this.files.delete(from);
  }
  async makeFolder(name: string) {
    this.made.push(name);
  }
}

describe('answering the helper, in the Dropbox app folder', () => {
  function dropbox() {
    const session = new FakeSession();
    return { session, store: new DropboxLibraryStore(session as unknown as DropboxSession) };
  }

  it('writes, reads and lists with library paths, as a local folder does', async () => {
    const { session, store } = dropbox();

    expect(await ask(store, { op: 'write', path: 'works/1 A.html' }, 'fic')).toEqual({ size: 3 });
    expect(session.files.get('/works/1 A.html')).toBe('fic');
    expect(await ask(store, { op: 'read', path: 'works/1 A.html' })).toEqual({ text: 'fic' });
    expect(await ask(store, { op: 'read', path: 'works/2.html' })).toEqual({ missing: true });
    expect((await ask(store, { op: 'list', path: 'works', recursive: true })).files).toEqual([
      'works/1 A.html',
    ]);
  });

  it('refuses a rename onto a name already taken, as a local folder does', async () => {
    const { session, store } = dropbox();
    session.files.set('/works/1.html', 'a');
    session.files.set('/works/2.html', 'b');

    const answer = await ask(store, { op: 'rename', path: 'works/1.html', to: 'works/2.html' });

    expect(answer.error).toBeTruthy();
    expect(session.files.get('/works/2.html')).toBe('b');
  });

  it('says so when the page is not signed in any more', async () => {
    const { session, store } = dropbox();
    session.status.set('signed-out');
    expect((await ask(store, { op: 'check' })).error).toContain('not signed in');
  });
});

describe('the run history, read out of the library', () => {
  it('lists runs newest first, leaving out the console log and anything unreadable', async () => {
    const folder = new MemoryFolder('Fics');
    const store = new LocalLibraryStore(folder);
    const record = (id: string) =>
      JSON.stringify({ id, action: 'quick', status: 'success', log: ['a', 'b'] });
    await ask(store, { op: 'write', path: 'runs/2026-01-01T000000-a.json' }, record('a'));
    await ask(store, { op: 'write', path: 'runs/2026-02-01T000000-b.json' }, record('b'));
    await ask(store, { op: 'write', path: 'runs/2026-03-01T000000-c.json' }, 'not json');

    const history = await readRunHistory(store);

    expect(history.map((x) => x.id)).toEqual(['b', 'a']);
    expect(history[0].file).toBe('2026-02-01T000000-b.json');
    expect('log' in history[0]).toBe(false);
  });

  it('is empty for a library nothing has been run in', async () => {
    expect(await readRunHistory(new LocalLibraryStore(new MemoryFolder('Fics')))).toEqual([]);
  });
});
