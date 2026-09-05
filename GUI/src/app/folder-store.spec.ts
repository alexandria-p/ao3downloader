import { describe, expect, it } from 'vitest';
import { DirectoryHandle, FileHandle, readFolder } from './folder-store';

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
