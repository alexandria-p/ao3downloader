import { TestBed } from '@angular/core/testing';
import { Bookmark } from './bookmarks';
import {
  LibraryImports,
  dateFiles,
  datedName,
  importLinks,
  isFileDate,
  undatedFiles,
  undatedIndexedFiles,
  unindexedWorks,
} from './imports';
import { Library } from './library';
import { LibraryStore } from './library-store';

/** a library in memory, by path: what is renamed moves */
class MemoryStore implements LibraryStore {
  readonly label = 'memory';
  readonly files = new Set<string>();
  /** renames that fail, by the path they come from */
  readonly refuse = new Set<string>();
  constructor(paths: string[] = []) {
    for (const path of paths) this.files.add(path);
  }
  async check() {}
  async list(path: string) {
    return [...this.files].filter((p) => p.startsWith(`${path}/`));
  }
  async read() {
    return null;
  }
  async write() {
    return 0;
  }
  async size() {
    return null;
  }
  async delete(path: string) {
    this.files.delete(path);
  }
  async rename(from: string, to: string) {
    if (this.refuse.has(from)) throw new Error(`${to} is already there`);
    this.files.delete(from);
    this.files.add(to);
  }
  async mkdir() {}
}

describe('finding works with files and no index entry', () => {
  it('finds the works in works/ named for a work number that the index has no entry for', () => {
    const found = unindexedWorks(
      [
        'works/12 A Fic - Someone 2024-01-02.html',
        'works/12 A Fic - Someone.epub',
        'works/7 Indexed - Someone 2024-01-01.html',
        'works/notes.txt',
        'works/No Number Here.html',
        'works/99Red Balloons.html',
        'indexing/5 Elsewhere - Someone.html',
        'works/sub/6 Deeper - Someone.html',
        'works/100 Another - Someone.pdf',
      ],
      new Set(['7']),
    );

    expect(found.map((w) => w.id)).toEqual(['12', '100']);
    expect(found[0].files.map((f) => [f.format, f.date]).sort()).toEqual([
      ['epub', ''],
      ['html', '2024-01-02'],
    ]);
  });

  it('finds the undated files of works the index does have', () => {
    const found = undatedIndexedFiles(
      ['works/7 A - B.html', 'works/7 A - B 2024-01-01.pdf', 'works/8 C - D.epub'],
      new Set(['7']),
    );
    expect(found.map((f) => f.name)).toEqual(['7 A - B.html']);
  });

  it('reads an .htm file as html', () => {
    expect(unindexedWorks(['works/3 X - Y.htm'], new Set())[0].files[0].format).toBe('html');
  });

  it('lists the files with no date in their name', () => {
    const found = unindexedWorks(
      ['works/1 A - B 2024-01-01.html', 'works/1 A - B.pdf', 'works/2 C - D 14 Dec 2024.epub'],
      new Set(),
    );
    expect(undatedFiles(found).map((f) => f.name)).toEqual(['1 A - B.pdf', '2 C - D 14 Dec 2024.epub']);
  });

  it('starts the import with one link to a line', () => {
    const found = unindexedWorks(['works/1 A - B.html', 'works/2 C - D.html'], new Set());
    expect(importLinks(found)).toBe(
      'https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/2',
    );
  });
});

describe('dating a file', () => {
  it('puts the date at the end of the name, before the extension', () => {
    expect(datedName('12 A Fic - Someone.html', '2024-03-04')).toBe('12 A Fic - Someone 2024-03-04.html');
    expect(datedName('12 A Fic - Someone .epub', '2024-03-04')).toBe('12 A Fic - Someone 2024-03-04.epub');
  });

  it('takes only a real day as a date', () => {
    expect(isFileDate('2024-02-29')).toBe(true);
    expect(isFileDate('2023-02-29')).toBe(false);
    expect(isFileDate('14 Dec 2024')).toBe(false);
    expect(isFileDate('')).toBe(false);
  });

  it('renames each file given a date, and carries on past one that will not rename', async () => {
    const store = new MemoryStore(['works/1 A - B.html', 'works/2 C - D.pdf']);
    store.refuse.add('works/2 C - D.pdf');
    const seen: number[] = [];

    const result = await dateFiles(
      store,
      new Map([
        ['works/1 A - B.html', '2024-01-01'],
        ['works/2 C - D.pdf', '2024-01-02'],
      ]),
      (done) => seen.push(done),
    );

    expect(result.renamed).toEqual([{ from: 'works/1 A - B.html', to: 'works/1 A - B 2024-01-01.html' }]);
    expect(result.failed.map((f) => f.path)).toEqual(['works/2 C - D.pdf']);
    expect([...store.files].sort()).toEqual(['works/1 A - B 2024-01-01.html', 'works/2 C - D.pdf']);
    expect(seen).toEqual([1, 2]);
  });
});

describe('LibraryImports', () => {
  it('works out the unindexed works from works/ and the index the page has read', async () => {
    const library = TestBed.inject(Library);
    const store = new MemoryStore(['works/1 A - B.html', 'works/2 C - D.html']);
    library.store.set(store);
    library.worksById.set(new Map([['1', { id: '1' } as Bookmark]]));
    const imports = TestBed.inject(LibraryImports);

    await imports.check();

    expect(imports.found().map((w) => w.id)).toEqual(['2']);
    expect(imports.checkedStore()).toBe(store);
  });

  it('finds nothing with no library open', async () => {
    const imports = TestBed.inject(LibraryImports);
    imports.found.set([{ id: '1', files: [] }]);
    await imports.check();
    expect(imports.found()).toEqual([]);
  });
});
