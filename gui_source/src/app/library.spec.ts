import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { Library } from './library';
import { DirectoryHandle, FolderStore } from './folder-store';

const SOURCE = 'https://archiveofourown.org/users/Someone/bookmarks';

/** one file per bookmark, as ao3downloader now writes them */
function record(id: string, position: number) {
  return {
    source: SOURCE,
    retrieved: '01/01/2026, 12:00:00',
    position,
    id,
    title: `Work ${id}`,
  };
}

function recordFile(id: string, position: number): File {
  return new File([JSON.stringify(record(id, position))], `${id} Work ${id} - X.json`);
}

function folderFiles(): File[] {
  return [recordFile('111', 1), new File(['<html></html>'], '111 Work 111 - X.html')];
}

/** Stands in for the browser file-system APIs, none of which exist in jsdom. */
class FakeFolderStore extends FolderStore {
  recalled: DirectoryHandle | null = null;
  granted: PermissionState = 'granted';
  requested = 0;
  remembered = 0;
  forgotten = 0;
  files = folderFiles();

  override supported(): boolean {
    return true;
  }
  override async pick(): Promise<DirectoryHandle> {
    return { kind: 'directory', name: 'downloads' } as DirectoryHandle;
  }
  override async recall(): Promise<DirectoryHandle | null> {
    return this.recalled;
  }
  override async remember(): Promise<void> {
    this.remembered += 1;
  }
  override async forget(): Promise<void> {
    this.forgotten += 1;
  }
  override async permission(_handle: DirectoryHandle, request: boolean): Promise<PermissionState> {
    if (request) this.requested += 1;
    return this.granted;
  }
  override async read(): Promise<File[]> {
    return this.files;
  }
}

function handle(name = 'downloads'): DirectoryHandle {
  return { kind: 'directory', name } as DirectoryHandle;
}

describe('Library', () => {
  let store: FakeFolderStore;
  let library: Library;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: FolderStore, useClass: FakeFolderStore }],
    });
    store = TestBed.inject(FolderStore) as FakeFolderStore;
    library = TestBed.inject(Library);
  });

  it('does nothing at startup when no folder was ever picked', async () => {
    await library.restore();

    expect(library.data()).toBeNull();
    expect(library.folderName()).toBe('');
    expect(library.needsReconnect()).toBe(false);
  });

  it('reopens the remembered folder with no clicks when permission still holds', async () => {
    store.recalled = handle();

    await library.restore();

    expect(library.folderName()).toBe('downloads');
    expect(library.needsReconnect()).toBe(false);
    expect(library.data()?.works.length).toBe(1);
    expect(library.htmlFiles().get('111')).toBeTruthy();
    // asking for permission needs a user gesture, so startup must not ask
    expect(store.requested).toBe(0);
  });

  it('asks to reconnect instead of loading when permission lapsed', async () => {
    store.recalled = handle();
    store.granted = 'prompt';

    await library.restore();

    expect(library.folderName()).toBe('downloads');
    expect(library.needsReconnect()).toBe(true);
    expect(library.data()).toBeNull();
    expect(store.requested).toBe(0);
  });

  it('loads once reconnect is confirmed from a click', async () => {
    store.recalled = handle();
    store.granted = 'prompt';
    await library.restore();

    store.granted = 'granted';
    await library.reconnect();

    expect(store.requested).toBe(1);
    expect(library.needsReconnect()).toBe(false);
    expect(library.data()?.works.length).toBe(1);
  });

  it('reports a declined reconnect rather than failing silently', async () => {
    store.recalled = handle();
    store.granted = 'prompt';
    await library.restore();

    await library.reconnect();

    expect(library.error()).toContain('declined');
    expect(library.data()).toBeNull();
  });

  it('remembers a newly picked folder so it comes back next time', async () => {
    await library.pickFolder();

    expect(store.remembered).toBe(1);
    expect(library.folderName()).toBe('downloads');
    expect(library.data()?.works.length).toBe(1);
  });

  it('clears everything when the folder is forgotten', async () => {
    store.recalled = handle();
    await library.restore();

    await library.forget();

    expect(store.forgotten).toBe(1);
    expect(library.folderName()).toBe('');
    expect(library.data()).toBeNull();
    expect(library.htmlFiles().size).toBe(0);
  });

  it('still accepts a plain file list for browsers without a directory picker', async () => {
    await library.load(folderFiles() as unknown as FileList);

    expect(library.data()?.works.length).toBe(1);
    expect(library.htmlFiles().get('111')).toBeTruthy();
  });

  it('explains itself when the folder holds no export', async () => {
    await library.load([new File(['<html></html>'], '111 A Work - X.html')] as unknown as FileList);

    expect(library.error()).toContain('No json files in that folder');
    expect(library.data()).toBeNull();
  });

  it('rejects json that is not an export', async () => {
    await library.load([new File(['{"nope":true}'], 'something.json')] as unknown as FileList);

    expect(library.error()).toContain('none of them look like an ao3downloader export');
    expect(library.data()).toBeNull();
  });

  it('reads one file per bookmark and restores the listing order', async () => {
    // the files come back from the folder in whatever order, but position is the truth
    store.files = [recordFile('333', 3), recordFile('111', 1), recordFile('222', 2)];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111', '222', '333']);
    expect(library.data()?.count).toBe(3);
    expect(library.data()?.source).toBe(SOURCE);
  });

  it('skips json in the folder that has nothing to do with the export', async () => {
    store.files = [recordFile('111', 1), new File(['{"some":"config"}'], 'other.json')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
  });

  it('ignores a json file that is corrupt rather than failing the whole folder', async () => {
    store.files = [recordFile('111', 1), new File(['{not json'], 'broken.json')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111']);
    expect(library.error()).toBe('');
  });

  it('still opens an export from the older single-file version', async () => {
    const legacy = {
      source: SOURCE,
      retrieved: '01/01/2026, 12:00:00',
      count: 2,
      works: [
        { id: '111', title: 'Work 111' },
        { id: '222', title: 'Work 222' },
      ],
    };
    store.files = [new File([JSON.stringify(legacy)], 'bookmarks_09062026.json')];
    store.recalled = handle();

    await library.restore();

    expect(library.data()?.works.map((w) => w.id)).toEqual(['111', '222']);
  });
});
