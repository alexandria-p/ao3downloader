import { TestBed } from '@angular/core/testing';
import { Bookmark } from './bookmarks';
import {
  IMPORT_EXCLUDED_FILE,
  LibraryImports,
  dateFiles,
  datedName,
  inferDate,
  renamesFor,
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
  readonly texts = new Map<string, string>();
  async read(path: string) {
    return this.texts.get(path) ?? null;
  }
  async write(path: string, body: Response) {
    this.texts.set(path, await body.text());
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

function found(path: string) {
  const name = path.split('/').pop()!;
  return { id: name.split(' ')[0], path, name, format: 'html' as const, date: '' };
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

    const renames = await renamesFor([
      { file: found('works/1 A - B.html'), date: '2024-01-01' },
      { file: found('works/2 C - D.pdf'), date: '2024-01-02' },
    ]);
    const result = await dateFiles(store, renames, (done) => seen.push(done));

    expect(result.renamed).toEqual([{ from: 'works/1 A - B.html', to: 'works/1 A - B 2024-01-01.html' }]);
    expect(result.failed.map((f) => f.path)).toEqual(['works/2 C - D.pdf']);
    expect([...store.files].sort()).toEqual(['works/1 A - B 2024-01-01.html', 'works/2 C - D.pdf']);
    expect(seen).toEqual([1, 2]);
  });

  it('names a file from the helper where it answers, and adds the date where it does not', async () => {
    const renames = await renamesFor(
      [
        { file: found('works/7 old.html'), date: '2024-02-03', record: { id: '7' } },
        { file: found('works/8 x.pdf'), date: '2024-02-03' },
      ],
      async () => ['7 The Fic - Writer 2024-02-03.html', ''],
    );
    expect(renames.map((r) => r.to)).toEqual(['works/7 The Fic - Writer 2024-02-03.html', 'works/8 x 2024-02-03.pdf']);

    const fallback = await renamesFor([{ file: found('works/7 old.html'), date: '2024-02-03' }], async () => {
      throw new Error('no helper');
    });
    expect(fallback[0].to).toBe('works/7 old 2024-02-03.html');
  });

  it('stops before the next rename once told to', async () => {
    const store = new MemoryStore(['works/1 A.html', 'works/2 B.html']);
    let stop = false;
    const result = await dateFiles(
      store,
      [{ path: 'works/1 A.html', to: 'works/1 A 2024-01-01.html' }, { path: 'works/2 B.html', to: 'works/2 B 2024-01-01.html' }],
      () => (stop = true),
      () => stop,
    );
    expect(result.renamed).toHaveLength(1);
  });
});

describe('inferring a date from a file name', () => {
  const cases: [string, string][] = [
    ['1 Fic - W 2024-03-04.html', '2024-03-04'],
    ['1 Fic 2024_03_04 - W.html', '2024-03-04'],
    ['1 Fic 2024.03.04.html', '2024-03-04'],
    ['1 Fic - W 20240304.pdf', '2024-03-04'],
    ['1 Fic - W 2024/03/04.html', '2024-03-04'],
    ['1 Fic - W 2024 03 04.html', '2024-03-04'],
    ['1 Fic - W 2024-25-04.html', '2024-04-25'],
    ['1 Fic - W 2024_25_04.html', '2024-04-25'],
    ['1 Fic - W 2024.25.04.html', '2024-04-25'],
    ['1 Fic - W 2024/25/04.html', '2024-04-25'],
    ['1 Fic - W 2024 25 04.html', '2024-04-25'],
    ['1 Fic - W 20242504.pdf', '2024-04-25'],
    ['1 Fic - W 2024-25-40.html', ''],
    ['1 Fic - W 03-04-2024.epub', '2024-03-04'],
    ['1 Fic - W 25-04-2024.epub', '2024-04-25'],
    ['1 Fic - W 14 Dec 2024.html', '2024-12-14'],
    ['1 Fic - W 4th December 2024.html', '2024-12-04'],
    ['1 Fic - W Dec 14, 2024.html', '2024-12-14'],
    ['1 Fic - W December 14 2024.html', '2024-12-14'],
    ['1 Fic - W 2024 Dec 14.html', '2024-12-14'],
    ['1 Fic - W.html', ''],
    ['20240304 Fic - W.html', ''],
    ['1 Fic - W 2024-13-40.html', ''],
    ['1 Fic - W 1850-01-01.html', ''],
  ];
  for (const [name, date] of cases) {
    it(`reads "${name}" as ${date || 'no date'}`, () => {
      expect(inferDate(name)).toBe(date);
    });
  }
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

  async function checked(paths: string[], excluded: object[], indexed: string[] = []) {
    const library = TestBed.inject(Library);
    const store = new MemoryStore(paths);
    store.texts.set(IMPORT_EXCLUDED_FILE, JSON.stringify({ excluded }));
    library.store.set(store);
    library.worksById.set(new Map(indexed.map((id) => [id, { id } as Bookmark])));
    const imports = TestBed.inject(LibraryImports);
    await imports.check();
    return imports;
  }

  it('never counts or lists a file on the files list, whatever its work', async () => {
    const imports = await checked(
      ['works/1 A - B.html', 'works/2 C - D.html', 'works/3 E - F.pdf', 'works/3 E - F.epub'],
      [{ id: '2', kind: 'files', files: ['2 C - D.html'] }, { id: '3', kind: 'files', files: ['3 E - F.pdf'] }],
    );
    expect(imports.found().map((w) => [w.id, w.files.map((f) => f.name)])).toEqual([
      ['1', ['1 A - B.html']],
      ['3', ['3 E - F.epub']],
    ]);
  });

  it('offers nothing at all when every file found is on the files list', async () => {
    const imports = await checked(
      ['works/1 A - B.html', 'works/7 G - H.pdf'],
      [{ id: '1', kind: 'files', files: ['1 A - B.html'] }, { id: '7', kind: 'files', files: ['7 G - H.pdf'] }],
      ['7'],
    );
    expect(imports.hasIssues()).toBe(false);
  });

  it('does not ask about a work on the index list while its files are the ones recorded', async () => {
    const imports = await checked(
      ['works/123 no-index 2024-01-01.pdf', 'works/123 no-index 2024-01-01.epub'],
      [{ id: '123', kind: 'index', files: ['123 no-index 2024-01-01.pdf', '123 no-index 2024-01-01.epub'] }],
    );
    expect(imports.found()).toEqual([]);
    expect(imports.hasIssues()).toBe(false);
  });

  it('asks about it again once the library has a file for it that was not recorded', async () => {
    const imports = await checked(
      ['works/123 no-index 2024-01-01.pdf', 'works/123 no-index 2024-01-01.epub', 'works/123 no-index 2024-01-01.html'],
      [{ id: '123', kind: 'index', files: ['123 no-index 2024-01-01.pdf', '123 no-index 2024-01-01.epub'] }],
    );
    expect(imports.found().map((w) => w.files.length)).toEqual([3]);
  });

  it('still offers the undated files of a work on the index list for dating, never for the index', async () => {
    const imports = await checked(
      ['works/123 no-index.pdf', 'works/123 no-index 2024-01-01.epub'],
      [{ id: '123', kind: 'index', files: ['123 no-index.pdf', '123 no-index 2024-01-01.epub'] }],
    );
    expect(imports.found()).toEqual([]);
    expect(imports.undatedIndexed().map((f) => [f.name, f.unindexed])).toEqual([['123 no-index.pdf', true]]);
  });

  it('never offers a file on the dates list for dating, but still asks about its work', async () => {
    const imports = await checked(
      ['works/1 A - B.html', 'works/1 A - B.pdf', 'works/7 G - H.epub'],
      [{ id: '1', kind: 'dates', files: ['1 A - B.html'] }, { id: '7', kind: 'dates', files: ['7 G - H.epub'] }],
      ['7'],
    );
    expect(imports.found().map((w) => w.id)).toEqual(['1']);
    expect(undatedFiles(imports.found()).map((f) => f.name)).toEqual(['1 A - B.pdf']);
    expect(imports.undatedIndexed()).toEqual([]);
  });

  it('offers nothing when the only issue left is files on the dates list', async () => {
    const imports = await checked(
      ['works/7 G - H.epub'],
      [{ id: '7', kind: 'dates', files: ['7 G - H.epub'] }],
      ['7'],
    );
    expect(imports.hasIssues()).toBe(false);
  });

  it('reads the list again once the library is listed again, so a run renaming files is seen', async () => {
    const library = TestBed.inject(Library);
    const store = new MemoryStore(['works/7 New Name - H.epub']);
    store.texts.set(IMPORT_EXCLUDED_FILE, JSON.stringify({ excluded: [{ id: '7', kind: 'dates', files: ['7 old.epub'] }] }));
    library.store.set(store);
    library.worksById.set(new Map([['7', { id: '7' } as Bookmark]]));
    const imports = TestBed.inject(LibraryImports);
    await imports.check();
    expect(imports.undatedIndexed()).toHaveLength(1);

    // the helper renamed the file, and its entry in the list with it
    store.texts.set(IMPORT_EXCLUDED_FILE, JSON.stringify({ excluded: [{ id: '7', kind: 'dates', files: ['7 New Name - H.epub'] }] }));
    library.listedAt.set(new Date());
    await imports.check();
    expect(imports.undatedIndexed()).toEqual([]);
  });

  it('records the files each list was given, and follows a file that dating renames', async () => {
    const library = TestBed.inject(Library);
    const store = new MemoryStore(['works/123 no-index.pdf', 'works/123 no-index.epub', 'works/5 X.html']);
    const written = { get [IMPORT_EXCLUDED_FILE]() { return store.texts.get(IMPORT_EXCLUDED_FILE)!; } };
    library.store.set(store);
    const imports = TestBed.inject(LibraryImports);
    await imports.check();

    await imports.excludeFromIndex(imports.found().filter((w) => w.id === '123'));
    await imports.excludeFiles(imports.found().find((w) => w.id === '5')!.files);
    let entries = JSON.parse(written[IMPORT_EXCLUDED_FILE]).excluded;
    expect(entries.map((e: { id: string; kind: string; files: string[] }) => [e.id, e.kind, e.files])).toEqual([
      ['123', 'index', ['123 no-index.epub', '123 no-index.pdf']],
      ['5', 'files', ['5 X.html']],
    ]);
    expect(imports.hasIssues()).toBe(true); // 123's undated files are still there to date

    await imports.renamed([{ from: 'works/123 no-index.pdf', to: 'works/123 no-index 2024-02-03.pdf' }]);
    entries = JSON.parse(written[IMPORT_EXCLUDED_FILE]).excluded;
    expect(entries[0].files).toEqual(['123 no-index.epub', '123 no-index 2024-02-03.pdf']);
  });

  it('finds nothing with no library open', async () => {
    const imports = TestBed.inject(LibraryImports);
    imports.found.set([{ id: '1', files: [] }]);
    await imports.check();
    expect(imports.found()).toEqual([]);
  });
});
