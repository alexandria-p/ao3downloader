import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { DropboxFile, DropboxFolder, DropboxSession, DropboxStatus } from './dropbox';
import { FolderStore } from './folder-store';
import { DropboxCopy, Library } from './library';
import { LibrarySetup } from './library-setup';
import { unzip } from './unzip';

// region building zips the way dropbox sends them

const encoder = new TextEncoder();

async function deflate(data: Uint8Array): Promise<Uint8Array> {
  const stream = new Response(data as BodyInit).body!.pipeThrough(new CompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** a zip of `files`, deflated unless told to store, with a folder entry as dropbox adds */
async function zipOf(files: Record<string, string>, stored = false): Promise<ArrayBuffer> {
  const locals: Uint8Array[] = [];
  const directory: Uint8Array[] = [];
  let offset = 0;
  const entries: [string, Uint8Array, number, Uint8Array][] = [['indexing/', new Uint8Array(), 0, new Uint8Array()]];
  for (const [path, text] of Object.entries(files)) {
    const raw = encoder.encode(text);
    entries.push([path, stored ? raw : await deflate(raw), stored ? 0 : 8, raw]);
  }

  for (const [path, data, method, raw] of entries) {
    const name = encoder.encode(path);
    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(8, method, true);
    local.setUint32(18, data.length, true);
    local.setUint32(22, raw.length, true);
    local.setUint16(26, name.length, true);
    locals.push(new Uint8Array(local.buffer), name, data);

    const central = new DataView(new ArrayBuffer(46));
    central.setUint32(0, 0x02014b50, true);
    central.setUint16(8, 0x0800, true); // utf-8 names
    central.setUint16(10, method, true);
    central.setUint32(20, data.length, true);
    central.setUint32(24, raw.length, true);
    central.setUint16(28, name.length, true);
    central.setUint32(42, offset, true);
    directory.push(new Uint8Array(central.buffer), name);
    offset += 30 + name.length + data.length;
  }

  const size = directory.reduce((n, part) => n + part.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, entries.length, true);
  end.setUint16(10, entries.length, true);
  end.setUint32(12, size, true);
  end.setUint32(16, offset, true);
  const parts = [...locals, ...directory, new Uint8Array(end.buffer)];
  const zip = new Uint8Array(parts.reduce((n, part) => n + part.length, 0));
  let at = 0;
  for (const part of parts) {
    zip.set(part, at);
    at += part.length;
  }
  return zip.buffer;
}

// endregion

describe('unzip', () => {
  it('reads deflated entries, names and all, and leaves folders out', async () => {
    const entries = await unzip(await zipOf({ 'indexing/111 Café.json': '{"id":"111"}' }));
    expect(entries.map((e) => e.path)).toEqual(['indexing/111 Café.json']);
    expect(new TextDecoder().decode(entries[0].data)).toBe('{"id":"111"}');
  });

  it('reads stored entries too', async () => {
    const entries = await unzip(await zipOf({ 'a.json': 'plain' }, true));
    expect(new TextDecoder().decode(entries[0].data)).toBe('plain');
  });

  it('refuses something that is not a zip, so the caller can fall back', async () => {
    await expect(unzip(encoder.encode('not a zip at all, just text').buffer)).rejects.toThrow();
  });
});

const SOURCE = 'https://archiveofourown.org/users/Someone/bookmarks';

function record(id: string, position: number): string {
  return JSON.stringify({ source: SOURCE, position, id, title: `Work ${id}` });
}

function collection(name: string): string {
  return JSON.stringify({
    name,
    link: `https://archiveofourown.org/collections/${name}`,
    last_indexed: '2026-09-10T12:00:00+00:00',
    indexes: [{ indexed_on: '2026-09-10T12:00:00+00:00', title: name, work_ids: ['111'] }],
  });
}

/** a dropbox folder in memory, reached through the session's own methods */
class FakeDropbox {
  readonly status = signal<DropboxStatus>('signed-in');
  // the app folder, as the real session hands it out; paths below it are rooted at ''
  readonly folder = signal<DropboxFolder | null>({ id: '', path: '', name: 'ao3-downloader' });
  files: Record<string, string> = {};
  zips: string[] = [];
  downloads: string[] = [];
  zipFails = false;

  async listFiles(path: string): Promise<DropboxFile[]> {
    return Object.keys(this.files)
      .filter((p) => p.toLowerCase().startsWith(path.toLowerCase() + '/'))
      .map((p, i) => ({ name: p.split('/').pop()!, path: p, modified: i }));
  }

  async downloadZip(path: string): Promise<ArrayBuffer> {
    this.zips.push(path);
    if (this.zipFails) throw new Error('too_many_files');
    const inside: Record<string, string> = {};
    const folder = path.split('/').pop()!;
    for (const [p, text] of Object.entries(this.files)) {
      if (p.startsWith(path + '/')) inside[`${folder}/${p.slice(path.length + 1)}`] = text;
    }
    return zipOf(inside);
  }

  async download(path: string): Promise<Blob> {
    this.downloads.push(path);
    return new Blob([this.files[path]]);
  }

  /** a library already set up, unless a test says otherwise */
  folders = new Set(['indexing', 'collections', 'images', 'runs', 'works']);
  made: string[] = [];

  async topLevel(): Promise<{ folders: string[]; files: string[] }> {
    const files = Object.keys(this.files)
      .filter((p) => p.split('/').length === 2)
      .map((p) => p.slice(1));
    return { folders: [...this.folders], files };
  }

  async makeFolder(name: string): Promise<void> {
    this.made.push(name);
    this.folders.add(name);
  }

  async moveInto(folder: string, names: string[], progress: (done: number) => void) {
    let moved = 0;
    const notMoved: string[] = [];
    for (const name of names) {
      if (this.files[`/${folder}/${name}`] !== undefined) {
        notMoved.push(name); // dropbox refuses to write over it
        continue;
      }
      this.files[`/${folder}/${name}`] = this.files[`/${name}`];
      delete this.files[`/${name}`];
      moved++;
    }
    progress(names.length);
    return { moved, notMoved };
  }
}

describe('Library, reading a Dropbox folder', () => {
  let dropbox: FakeDropbox;
  let library: Library;

  beforeEach(() => {
    dropbox = new FakeDropbox();
    TestBed.configureTestingModule({
      providers: [
        { provide: DropboxSession, useValue: dropbox },
        // no local folder in any of these
        { provide: FolderStore, useValue: { supported: () => true, recall: async () => null } },
      ],
    });
    library = TestBed.inject(Library);
  });

  it('reads the index in one zip per folder rather than a request per fic', async () => {
    dropbox.files = {
      '/indexing/222 Two.json': record('222', 2),
      '/indexing/111 One.json': record('111', 1),
      '/collections/yuletide.json': collection('yuletide'),
      '/works/111 One - A 2024-01-01.html': '<p>one</p>',
    };

    await library.showDropbox();

    expect(library.error()).toBe('');
    expect(library.data()?.works.map((w) => w.id)).toEqual(['111', '222']);
    expect(library.collections().map((c) => c.name)).toEqual(['yuletide']);
    expect(dropbox.zips).toEqual(['/indexing', '/collections']);
    expect(dropbox.downloads).toEqual([]);
  });

  it('knows which works have a copy without downloading any of them', async () => {
    dropbox.files = {
      '/indexing/111 One.json': record('111', 1),
      '/works/111 One - A 2024-01-01.html': '<p>new</p>',
      '/works/old/111 One - A.html': '<p>old</p>',
      '/images/111 picture.html': 'not a work',
    };

    await library.showDropbox();

    const copy = library.htmlFiles().get('111') as DropboxCopy;
    // the one dropbox saw change last, as a local folder picks the newest file
    expect(copy.dropboxPath).toBe('/works/old/111 One - A.html');
    expect(dropbox.downloads).toEqual([]);
  });

  it('looks for works in works/ and nowhere else', async () => {
    dropbox.files = {
      '/indexing/111 One.json': record('111', 1),
      '/elsewhere/111 One - A.html': '<p>not here</p>',
    };
    await library.showDropbox();
    expect(library.htmlFiles().has('111')).toBe(false);
  });

  it('fetches a work only when it is opened, as html so a tab shows it', async () => {
    dropbox.files = {
      '/indexing/111 One.json': record('111', 1),
      '/works/111 One - A.html': '<p>the fic</p>',
    };
    await library.showDropbox();

    const blob = await library.readCopy(library.htmlFiles().get('111')!);

    expect(blob.type).toBe('text/html');
    expect(await blob.text()).toBe('<p>the fic</p>');
    expect(dropbox.downloads).toEqual(['/works/111 One - A.html']);
  });

  it('reads the files one at a time when dropbox will not zip the folder', async () => {
    dropbox.zipFails = true;
    dropbox.files = {
      '/indexing/111 One.json': record('111', 1),
      '/indexing/222 Two.json': record('222', 2),
    };

    await library.showDropbox();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111', '222']);
    expect(dropbox.downloads.sort()).toEqual(['/indexing/111 One.json', '/indexing/222 Two.json']);
  });

  it('shows a folder with nothing in it yet as empty, not as a mistake', async () => {
    await library.showDropbox();
    expect(library.error()).toBe('');
    expect(library.data()).toBeNull();
    expect(library.loading()).toBe(false);
  });

  it('reads nothing without a session', async () => {
    dropbox.status.set('signed-out');
    dropbox.folder.set(null);
    dropbox.files = { '/indexing/111 One.json': record('111', 1) };
    await library.showDropbox();
    expect(library.data()).toBeNull();
    expect(dropbox.zips).toEqual([]);
  });

  it('says which folder could not be read', async () => {
    dropbox.listFiles = async () => {
      throw new Error('Dropbox asked us to slow down.');
    };
    await library.showDropbox();
    expect(library.error()).toContain('/Apps/ao3-downloader');
    expect(library.error()).toContain('slow down');
  });

  it('does not leave dropbox works on screen after switching back to this computer', async () => {
    dropbox.files = { '/indexing/111 One.json': record('111', 1) };
    await library.showDropbox();
    library.folderName.set('downloads');

    await library.showLocal();

    expect(library.data()).toBeNull();
    // the local folder is still the one remembered
    expect(library.folderName()).toBe('downloads');
  });

  it('throws away a read that finishes after the library was switched', async () => {
    dropbox.files = { '/indexing/111 One.json': record('111', 1) };
    const reading = library.showDropbox();
    await library.showLocal();
    await reading;
    expect(library.data()).toBeNull();
  });

  // region setting the library up

  it('makes the folders a library needs when some are missing, before reading it', async () => {
    dropbox.folders = new Set(['indexing']);
    const setup = TestBed.inject(LibrarySetup);
    const seen: string[] = [];
    const makeFolder = dropbox.makeFolder.bind(dropbox);
    // what the overlay would be showing while each folder is made
    dropbox.makeFolder = async (name) => {
      seen.push(setup.state());
      await makeFolder(name);
    };

    await library.showDropbox();

    expect(dropbox.made).toEqual(['collections', 'images', 'runs', 'works']);
    expect(seen.every((state) => state === 'working')).toBe(true);
    expect(setup.state()).toBe('idle');
  });

  it('covers the page while it checks, and uncovers it when nothing needs doing', async () => {
    const setup = TestBed.inject(LibrarySetup);
    let whileChecking = '';
    const topLevel = dropbox.topLevel.bind(dropbox);
    dropbox.topLevel = async () => {
      // the cover is up before the first question is even asked of the folder
      whileChecking = setup.state();
      return topLevel();
    };

    await library.showDropbox();

    expect(whileChecking).toBe('working');
    expect(dropbox.made).toEqual([]);
    expect(setup.state()).toBe('idle');
  });

  it('asks before moving works out of the top level, and moves them when told to', async () => {
    dropbox.files = {
      '/indexing/111 One.json': record('111', 1),
      '/111 One - A 2024-01-01.html': '<p>one</p>',
      '/222 Two - B.epub': 'two',
      '/notes.txt': 'not a work',
    };
    const setup = TestBed.inject(LibrarySetup);
    const showing = library.showDropbox();
    await until(() => setup.state() === 'asking');

    expect(setup.looseWorks()).toBe(2);
    setup.choose(true);
    await showing;

    expect(Object.keys(dropbox.files).sort()).toEqual([
      '/indexing/111 One.json',
      '/notes.txt',
      '/works/111 One - A 2024-01-01.html',
      '/works/222 Two - B.epub',
    ]);
    expect(library.htmlFiles().has('111')).toBe(true);
    expect(setup.state()).toBe('idle');
  });

  it('leaves the works where they are when told to, and asks again next time', async () => {
    dropbox.files = {
      '/indexing/111 One.json': record('111', 1),
      '/111 One - A.html': '<p>one</p>',
    };
    const setup = TestBed.inject(LibrarySetup);

    for (let visit = 0; visit < 2; visit++) {
      const showing = library.showDropbox();
      await until(() => setup.state() === 'asking');
      setup.choose(false);
      await showing;
    }

    expect(dropbox.files['/111 One - A.html']).toBe('<p>one</p>');
    // not looked for outside works/, so not paired with the fic
    expect(library.htmlFiles().has('111')).toBe(false);
  });

  it('says which works it could not move, and why that usually is', async () => {
    dropbox.files = {
      '/111 One - A.html': 'top level',
      '/works/111 One - A.html': 'already moved once',
      '/222 Two - B.html': 'two',
    };
    const setup = TestBed.inject(LibrarySetup);
    const showing = library.showDropbox();
    await until(() => setup.state() === 'asking');
    setup.choose(true);
    await showing;

    expect(setup.report()).toContain('Moved 1 of 2');
    expect(setup.report()).toContain('111 One - A.html');
    // the copy already in works/ is untouched
    expect(dropbox.files['/works/111 One - A.html']).toBe('already moved once');
  });

  // endregion
});

/** wait for something the page does across a few awaits */
async function until(condition: () => boolean): Promise<void> {
  for (let i = 0; i < 50 && !condition(); i++) await new Promise((r) => setTimeout(r, 0));
  expect(condition()).toBe(true);
}
