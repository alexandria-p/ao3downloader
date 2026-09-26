import { describe, expect, it } from 'vitest';
import {
  DirectoryHandle,
  FileHandle,
  moveIntoSubfolder,
  readFolder,
  readSubfolder,
  removeFile,
  streamFile,
  topLevel,
  writeFile,
} from './folder-store';

function file(name: string, body = ''): FileHandle {
  return {
    kind: 'file',
    name,
    getFile: async () => new File([body], name),
  };
}

function directory(name: string, entries: (DirectoryHandle | FileHandle)[]): DirectoryHandle {
  return {
    kind: 'directory',
    name,
    async *values() {
      for (const entry of entries) yield entry;
    },
  };
}

describe('readFolder', () => {
  it('returns every file in the folder', async () => {
    const handle = directory('downloads', [file('bookmarks_1.json'), file('111 A Work - X.html')]);

    const files = await readFolder(handle);

    expect(files.map((f) => f.name)).toEqual(['bookmarks_1.json', '111 A Work - X.html']);
  });

  it('descends into subfolders, which the file name pattern can create', async () => {
    const handle = directory('downloads', [
      file('bookmarks_1.json'),
      directory('A Fandom', [file('222 Nested - Y.html'), directory('deeper', [file('333 Deep - Z.html')])]),
    ]);

    const files = await readFolder(handle);

    expect(files.map((f) => f.name).sort()).toEqual([
      '222 Nested - Y.html',
      '333 Deep - Z.html',
      'bookmarks_1.json',
    ]);
  });

  it('handles an empty folder', async () => {
    expect(await readFolder(directory('downloads', []))).toEqual([]);
  });
});

/**
 * A folder that can be written to, kept in memory.
 *
 * Nothing in jsdom implements the File System Access API, so the fake has to stand in for
 * the parts the page relies on: creating a subfolder, creating a file in it, and only
 * landing the bytes on close.
 */
function writable(written: Map<string, string>, prefix = ''): DirectoryHandle {
  const here = prefix;
  return {
    kind: 'directory',
    name: prefix || 'downloads',
    async *values() {
      // nothing reads a written folder back in these tests
    },
    async getDirectoryHandle(name: string, options?: { create?: boolean }) {
      if (!options?.create) throw new Error('not found: ' + name);
      return writable(written, here + name + '/');
    },
    async getFileHandle(name: string, options?: { create?: boolean }) {
      if (!options?.create) throw new Error('not found: ' + name);
      const path = here + name;
      let pending = '';
      return {
        kind: 'file' as const,
        name,
        getFile: async () => new File([written.get(path) ?? ''], name),
        createWritable: async () => ({
          async write(data: BufferSource | Blob | string) {
            pending += String(data);
          },
          async close() {
            written.set(path, pending);
          },
        }),
      };
    },
    async removeEntry(name: string) {
      const path = here + name;
      if (!written.has(path)) throw new Error('not found: ' + path);
      written.delete(path);
    },
  };
}

describe('writing into the picked folder', () => {
  it('writes a file at the top of the folder', async () => {
    const written = new Map<string, string>();

    await writeFile(writable(written), '111 A Work - X 2026-01-01.html', '<html>');

    expect(written.get('111 A Work - X 2026-01-01.html')).toBe('<html>');
  });

  // indexing, collections, images and runs all live under the picked folder, and none of
  // them exists the first time something is saved into it
  it('creates the subfolders on the way', async () => {
    const written = new Map<string, string>();

    await writeFile(writable(written), 'indexing/111 A Work.json', '{"id":"111"}');
    await writeFile(written.size ? writable(written) : writable(written), 'runs/a-run.json', '{}');

    expect(written.get('indexing/111 A Work.json')).toBe('{"id":"111"}');
    expect(written.get('runs/a-run.json')).toBe('{}');
  });

  it('lands nothing until the stream is closed', async () => {
    const written = new Map<string, string>();
    const handle = writable(written);
    const folder = await handle.getFileHandle!('half.html', { create: true });
    const stream = await folder.createWritable!();

    await stream.write('partial');
    expect(written.has('half.html')).toBe(false);

    await stream.close();
    expect(written.get('half.html')).toBe('partial');
  });

  it('removes a file, and treats one that is not there as already gone', async () => {
    const written = new Map<string, string>([['indexing/111.json', '{}']]);

    expect(await removeFile(writable(written), 'indexing/111.json')).toBe(true);
    expect(written.has('indexing/111.json')).toBe(false);
    expect(await removeFile(writable(written), 'indexing/nope.json')).toBe(false);
  });

  it('will not write into a browser that cannot create files', async () => {
    // the fallback folder input gives no handle worth writing through
    await expect(writeFile(directory('downloads', []), 'a.html', 'x')).rejects.toThrow();
  });
});

/**
 * A folder whose files are real `WritableStream`s, which is what `pipeTo` needs.
 *
 * The browser's own `createWritable` returns one, so faking anything less would test a
 * different code path than the one that runs.
 */
function streamable(written: Map<string, string>, landed = new Set<string>()): DirectoryHandle {
  return {
    kind: 'directory',
    name: 'downloads',
    async *values() {
      // nothing reads it back here
    },
    async getDirectoryHandle() {
      return streamable(written, landed);
    },
    async getFileHandle(name: string) {
      let buffer = '';
      return {
        kind: 'file' as const,
        name,
        getFile: async () => new File([written.get(name) ?? ''], name),
        createWritable: async () =>
          new WritableStream<Uint8Array>({
            write(chunk) {
              buffer += new TextDecoder().decode(chunk);
            },
            close() {
              written.set(name, buffer);
              landed.add(name);
            },
            abort() {
              // an aborted writable discards what it had - no truncated file is left
            },
          }) as unknown as never,
      };
    },
  };
}

function bodyOf(chunks: string[], failOn = -1): ReadableStream<Uint8Array> {
  let at = 0;
  return new ReadableStream<Uint8Array>({
    pull(controller) {
      if (at === failOn) {
        controller.error(new Error('connection lost'));
        return;
      }
      if (at >= chunks.length) {
        controller.close();
        return;
      }
      controller.enqueue(new TextEncoder().encode(chunks[at++]));
    },
  });
}

describe('streaming a download into the picked folder', () => {
  it('writes the whole body without ever holding it', async () => {
    const written = new Map<string, string>();

    await streamFile(streamable(written), '111 A Work.epub', bodyOf(['one', 'two', 'three']));

    expect(written.get('111 A Work.epub')).toBe('onetwothree');
  });

  // the same guarantee the helper's own writes were built around: a transfer that dies
  // partway leaves no file rather than one that looks complete and is not
  it('leaves no file behind when the transfer fails partway', async () => {
    const written = new Map<string, string>();
    const landed = new Set<string>();

    await expect(
      streamFile(streamable(written, landed), '111 A Work.epub', bodyOf(['one', 'two'], 1)),
    ).rejects.toThrow('connection lost');

    expect(landed.has('111 A Work.epub')).toBe(false);
    expect(written.has('111 A Work.epub')).toBe(false);
  });

  it('creates the subfolder on the way, as a plain write does', async () => {
    const written = new Map<string, string>();

    await streamFile(streamable(written), 'images/111 img000.png', bodyOf(['bytes']));

    expect(written.get('111 img000.png')).toBe('bytes');
  });
});

/**
 * A whole folder tree in memory - reads what it holds as well as taking writes - for the
 * parts of setting a library up that move files between folders.
 */
class MemoryFolder implements DirectoryHandle {
  readonly kind = 'directory' as const;
  readonly folders = new Map<string, MemoryFolder>();
  readonly files = new Map<string, string>();
  /** a write that lands short, as a full disk would leave it */
  shortWrites = false;

  constructor(readonly name: string) {}

  async *values() {
    for (const folder of this.folders.values()) yield folder;
    for (const name of this.files.keys()) yield this.fileHandle(name);
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

  private fileHandle(name: string): FileHandle {
    return {
      kind: 'file',
      name,
      getFile: async () => new File([this.files.get(name) ?? ''], name),
      createWritable: async () => {
        let pending = '';
        return {
          write: async (data: BufferSource | Blob | string) => {
            pending +=
              typeof data === 'string'
                ? data
                : data instanceof Blob
                  ? await data.text()
                  : new TextDecoder().decode(data as ArrayBuffer);
          },
          close: async () => {
            this.files.set(name, this.shortWrites ? pending.slice(0, 1) : pending);
          },
        };
      },
    };
  }
}

describe('setting a library up', () => {
  it('names what is in the top level, folders apart from files', async () => {
    const library = new MemoryFolder('downloads');
    await library.getDirectoryHandle('indexing', { create: true });
    library.files.set('111 A.html', 'fic');

    expect(await topLevel(library)).toEqual({ folders: ['indexing'], files: ['111 A.html'] });
  });

  it('reads a subfolder that is not there as empty, without making it', async () => {
    const library = new MemoryFolder('downloads');
    expect(await readSubfolder(library, 'works')).toEqual([]);
    expect(library.folders.has('works')).toBe(false);
  });

  it('moves a work into works/, all of it, and only then removes the original', async () => {
    const library = new MemoryFolder('downloads');
    library.files.set('111 A.html', 'the whole fic');

    expect(await moveIntoSubfolder(library, '111 A.html', 'works')).toBe(true);

    expect(library.files.has('111 A.html')).toBe(false);
    expect(library.folders.get('works')!.files.get('111 A.html')).toBe('the whole fic');
  });

  it('never writes over a file already in works/', async () => {
    const library = new MemoryFolder('downloads');
    library.files.set('111 A.html', 'top level copy');
    const works = await library.getDirectoryHandle('works', { create: true });
    works.files.set('111 A.html', 'the one already moved');

    expect(await moveIntoSubfolder(library, '111 A.html', 'works')).toBe(false);

    expect(library.files.get('111 A.html')).toBe('top level copy');
    expect(works.files.get('111 A.html')).toBe('the one already moved');
  });

  it('keeps the original when the copy does not arrive whole', async () => {
    const library = new MemoryFolder('downloads');
    library.files.set('111 A.html', 'the whole fic');
    const works = await library.getDirectoryHandle('works', { create: true });
    works.shortWrites = true;

    expect(await moveIntoSubfolder(library, '111 A.html', 'works')).toBe(false);

    expect(library.files.get('111 A.html')).toBe('the whole fic');
    expect(works.files.has('111 A.html')).toBe(false);
  });
});
