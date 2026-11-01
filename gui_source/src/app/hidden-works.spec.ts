import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { Bookmark, isListedEntry, originOf } from './bookmarks';
import { HIDDEN_FILE, Library, emptyCopies } from './library';
import { LibraryStore } from './library-store';
import { WorkList } from './work-list';

/**
 * Where a work in the listing came from - your bookmarks, a collection, anywhere else - and
 * hiding works from the listing without touching their files.
 */

function work(id: string, extra: Partial<Bookmark> = {}): Bookmark {
  return {
    id,
    link: `https://archiveofourown.org/works/${id}`,
    title: `Work ${id}`,
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
    fandoms: [],
    warnings: [],
    tags: { rating: '', categories: [], relationships: [], characters: [], additional: [] },
    summary: '',
    words: null,
    chapters_published: 1,
    chapters_total: 1,
    comments: null,
    kudos: null,
    bookmarks: null,
    hits: null,
    date_bookmarked: '',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
    ...extra,
  } as Bookmark;
}

const MINE = work('1', { bookmarked: true });
const OLD = work('2'); // from before `bookmarked` was recorded: off your bookmarks
const BY_LINK = work('3', { bookmarked: false });
const IN_COLLECTION = work('4', { bookmarked: false, from_collections: ['yuletide2024'] });
const ONLY_IN_SERIES = work('5', { bookmarked: false, from_series: ['77'] });
const FETCHED = work('6', { bookmarked: false, from_link: true });
const FROM_FICHUB = work('7', { bookmarked: false, from_link: true,
                                retrieved_from: { site: 'fichub', downloaded: ['EPUB'] } });
const NOTED = work('8', { bookmarked: true, bookmark_notes: 'loved the ending' });
const RECCED = work('9', { bookmarked: true, bookmark_rec: true });

class MemoryStore implements LibraryStore {
  readonly label = 'memory';
  readonly files = new Map<string, string>();
  failWrites = false;
  async check() {}
  async list() {
    return [...this.files.keys()];
  }
  async read(path: string) {
    return this.files.get(path) ?? null;
  }
  async write(path: string, body: Response) {
    if (this.failWrites) throw new Error('the disk is full');
    const text = await body.text();
    this.files.set(path, text);
    return text.length;
  }
  async size() {
    return null;
  }
  async delete() {}
  async rename() {}
  async mkdir() {}
}

describe('where a work came from', () => {
  it('says bookmarks, a collection, by ID or URL, or unknown', () => {
    expect([MINE, OLD, BY_LINK, IN_COLLECTION, FETCHED, FROM_FICHUB].map(originOf)).toEqual([
      'bookmarks',
      'bookmarks',
      'other',
      'collection',
      'link',
      // a fic run's fic that FicHub supplied is still one fetched by ID or URL
      'link',
    ]);
    // your bookmark stays your bookmark, however it was fetched
    expect(originOf(work('10', { bookmarked: true, from_link: true }))).toBe('bookmarks');
    // and one first found another way, later found on your bookmarks, is yours from then on
    expect(originOf(work('11', { bookmarked: true, from_link: true, from_collections: ['c'],
      retrieved_from: { site: 'fichub', downloaded: ['EPUB'] } }))).toBe('bookmarks');
  });

  it('lists everything in the index but a work only a series brought in, and a series you did not bookmark', () => {
    expect([MINE, OLD, BY_LINK, IN_COLLECTION, ONLY_IN_SERIES].map((w) => isListedEntry(w))).toEqual([
      true, true, true, true, false,
    ]);
    expect(isListedEntry(work('6', { bookmarked: false, bookmark_type: 'series bookmark' }))).toBe(false);
    // a bookmarked series listing it is as good as its own from_series
    expect(isListedEntry(work('7', { bookmarked: false }), new Set(['7']))).toBe(false);
  });
});

describe('the listing, with works from elsewhere and works hidden', () => {
  let library: Library;
  let store: MemoryStore;
  let fixture: ComponentFixture<WorkList>;
  let element: HTMLElement;

  async function settle() {
    for (let i = 0; i < 3; i++) {
      await fixture.whenStable();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    fixture.detectChanges();
  }

  async function listing(works: Bookmark[], selectable = false) {
    fixture = TestBed.createComponent(WorkList);
    fixture.componentRef.setInput('works', works);
    fixture.componentRef.setInput('selectable', selectable);
    await settle();
    element = fixture.nativeElement as HTMLElement;
  }

  function titles(): string[] {
    return [...element.querySelectorAll('.blurb .heading a.title')].map((a) => a.textContent?.trim() ?? '');
  }

  function blurb(title: string): HTMLElement {
    return [...element.querySelectorAll<HTMLElement>('li.blurb')].find((li) =>
      li.querySelector('a.title')?.textContent?.trim() === title,
    )!;
  }

  function button(text: string): HTMLButtonElement {
    return [...element.querySelectorAll('button')].find((b) => b.textContent?.trim().includes(text))!;
  }

  function writtenHidden(): string[] {
    return JSON.parse(store.files.get(HIDDEN_FILE) ?? '{"hidden":[]}').hidden.map((h: { key: string }) => h.key);
  }

  beforeEach(() => {
    localStorage.clear();
    library = TestBed.inject(Library);
    store = new MemoryStore();
    library.store.set(store);
  });

  it('gives every entry the eye and the menu, on a row of their own after the bookmark box', async () => {
    const yours = work('6', { bookmarked: true, date_bookmarked: '02 Feb 2021', bookmark_notes: 'loved it' });
    const external = work('7', {
      bookmark_type: 'external work',
      link: 'https://elsewhere.example/story',
      date_bookmarked: '03 Mar 2022',
    });
    const stub = { ...work('8'), placeholder: true } as Bookmark;
    await listing([yours, external, stub], true);

    for (const entry of element.querySelectorAll<HTMLElement>('li.blurb')) {
      const actions = entry.querySelector('.entry-actions');
      expect(actions?.querySelector('button.hide-toggle')).toBeTruthy();
      expect(actions?.querySelector('button.entry-menu-toggle')).toBeTruthy();
      // last in the entry, so the 'Bookmarked by' box can never be drawn over them
      expect(entry.lastElementChild).toBe(actions);
    }
    expect(blurb('Work 6').querySelector('.user')).toBeTruthy();
  });

  it('marks a work that is not one of your bookmarks, and says where it came from', async () => {
    await listing([MINE, BY_LINK, IN_COLLECTION]);

    expect(blurb('Work 1').querySelector('.badge.origin')).toBeNull();
    expect(blurb('Work 3').querySelector('.badge.origin')?.textContent).toContain('Not in your AO3 bookmarks');
    expect(blurb('Work 4').querySelector('.badge.origin')?.textContent).toContain('From the collection yuletide2024');
  });

  it('filters by where works came from', async () => {
    await listing([MINE, OLD, BY_LINK, IN_COLLECTION]);
    const select = element.querySelector<HTMLSelectElement>('select[name="originFilter"]')!;

    select.value = 'other';
    select.dispatchEvent(new Event('change'));
    await settle();
    expect(titles()).toEqual(['Work 3']);

    select.value = 'bookmarks';
    select.dispatchEvent(new Event('change'));
    await settle();
    expect(titles().sort()).toEqual(['Work 1', 'Work 2']);
  });

  it('offers the five places a work can come from, and filters by each new one', async () => {
    await listing([MINE, BY_LINK, FETCHED]);
    const select = element.querySelector<HTMLSelectElement>('select[name="originFilter"]')!;
    expect(Array.from(select.options).map((o) => o.textContent?.trim())).toEqual([
      'Anywhere', 'Your AO3 bookmarks', 'An AO3 collection',
      'Imported from external source (coming soon)', 'Downloaded by ID or URL', 'Unknown',
    ]);
    // an upcoming feature: there, but not yet choosable
    expect(Array.from(select.options).find((o) => o.value === 'external')?.disabled).toBe(true);

    select.value = 'link';
    select.dispatchEvent(new Event('change'));
    await settle();
    expect(titles()).toEqual(['Work 6']);
    expect(blurb('Work 6').querySelector('.badge.origin')?.textContent).toContain('Downloaded by ID or URL');
  });

  it('narrows to bookmarks with a note, or ones you recommended', async () => {
    await listing([MINE, NOTED, RECCED]);
    const notes = element.querySelector<HTMLInputElement>('input[name="withNotes"]')!;
    notes.click();
    await settle();
    expect(titles()).toEqual(['Work 8']);

    notes.click();
    element.querySelector<HTMLInputElement>('input[name="recommended"]')!.click();
    await settle();
    expect(titles()).toEqual(['Work 9']);
  });

  it('warns before hiding, then hides it from the list and keeps the choice in the library', async () => {
    await listing([MINE, BY_LINK]);

    blurb('Work 3').querySelector<HTMLButtonElement>('button.hide-toggle')!.click();
    await settle();
    const warning = element.querySelector('.hide-modal')!;
    expect(warning.textContent).toContain('Nothing is deleted');
    expect(warning.textContent).toContain('Show hidden works');
    expect(writtenHidden()).toEqual([]);

    button('Hide it').click();
    await settle();

    expect(titles()).toEqual(['Work 1']);
    expect(writtenHidden()).toEqual(['individual work:3']);
    expect(element.querySelector('.listing-heading')?.textContent).toContain('1 hidden');
  });

  it('hides nothing when the warning is cancelled', async () => {
    await listing([MINE, BY_LINK]);
    blurb('Work 3').querySelector<HTMLButtonElement>('button.hide-toggle')!.click();
    await settle();

    button('Cancel').click();
    await settle();

    expect(titles()).toHaveLength(2);
    expect(store.files.has(HIDDEN_FILE)).toBe(false);
  });

  it('does not warn again once told not to', async () => {
    await listing([MINE, BY_LINK, IN_COLLECTION]);
    blurb('Work 3').querySelector<HTMLButtonElement>('button.hide-toggle')!.click();
    await settle();
    const dontWarn = element.querySelector<HTMLInputElement>('.dont-warn input')!;
    dontWarn.checked = true;
    dontWarn.dispatchEvent(new Event('change'));
    button('Hide it').click();
    await settle();

    blurb('Work 4').querySelector<HTMLButtonElement>('button.hide-toggle')!.click();
    await settle();

    expect(element.querySelector('.hide-modal')).toBeNull();
    expect(titles()).toEqual(['Work 1']);
  });

  it('shows hidden works marked as such when asked, and unhides one', async () => {
    await library.hide(BY_LINK);
    await listing([MINE, BY_LINK]);
    expect(titles()).toEqual(['Work 1']);

    const show = element.querySelector<HTMLInputElement>('input[name="showHidden"]')!;
    show.checked = true;
    show.dispatchEvent(new Event('change'));
    await settle();

    expect(titles()).toHaveLength(2);
    expect(blurb('Work 3').classList).toContain('hidden-work');
    expect(blurb('Work 3').textContent).toContain('Hidden');

    blurb('Work 3').querySelector<HTMLButtonElement>('button.unhide')!.click();
    await settle();

    expect(writtenHidden()).toEqual([]);
    expect(blurb('Work 3').classList).not.toContain('hidden-work');
  });

  it('puts a hide back when it could not be saved, and says why', async () => {
    store.failWrites = true;
    localStorage.setItem('ao3.hideWarningOff', 'off');
    await listing([MINE, BY_LINK]);

    blurb('Work 3').querySelector<HTMLButtonElement>('button.hide-toggle')!.click();
    await settle();

    expect(titles()).toHaveLength(2);
    expect(element.textContent).toContain('the disk is full');
  });

  it('offers no hiding in a library that can only be read', async () => {
    library.store.set(null);
    await listing([MINE]);
    expect(element.querySelector('button.hide-toggle')).toBeNull();
  });

  // region hiding and unhiding ticked works

  async function showHidden() {
    const show = element.querySelector<HTMLInputElement>('input[name="showHidden"]')!;
    show.checked = true;
    show.dispatchEvent(new Event('change'));
    await settle();
  }

  async function tick(...titlesToTick: string[]) {
    for (const title of titlesToTick) {
      blurb(title).querySelector<HTMLInputElement>('input.pick')!.dispatchEvent(new Event('change'));
    }
    await settle();
  }

  /** what the ticked-works bar offers for hiding, by label */
  function offered(): string[] {
    return [...element.querySelectorAll('.selection-bar button')]
      .map((b) => b.textContent?.trim() ?? '')
      .filter((label) => /hide/i.test(label));
  }

  it('offers Hide for one showing work, and Unhide for one hidden work', async () => {
    await library.hide(BY_LINK);
    await listing([MINE, BY_LINK], true);
    await showHidden();

    await tick('Work 1');
    expect(offered()).toEqual(['Hide']);

    await tick('Work 1', 'Work 3');
    expect(offered()).toEqual(['Unhide']);
  });

  it('offers Hide all when every ticked work is showing, Unhide all when every one is hidden', async () => {
    await library.hide([BY_LINK, IN_COLLECTION]);
    await listing([MINE, OLD, BY_LINK, IN_COLLECTION], true);
    await showHidden();

    await tick('Work 1', 'Work 2');
    expect(offered()).toEqual(['Hide all']);

    await tick('Work 1', 'Work 2', 'Work 3', 'Work 4');
    expect(offered()).toEqual(['Unhide all']);
  });

  it('offers both Hide all and Unhide all when the ticked works are a mix', async () => {
    await library.hide(BY_LINK);
    await listing([MINE, OLD, BY_LINK], true);
    await showHidden();

    await tick('Work 1', 'Work 3');

    expect(offered()).toEqual(['Hide all', 'Unhide all']);
  });

  it('hides every ticked work after one warning, in a single write', async () => {
    await listing([MINE, OLD, BY_LINK], true);
    let writes = 0;
    const write = store.write.bind(store);
    store.write = async (path, body) => {
      writes++;
      return write(path, body);
    };
    await tick('Work 1', 'Work 2');

    [...element.querySelectorAll<HTMLButtonElement>('.selection-bar button')].find((b) => b.textContent?.trim() === 'Hide all')!.click();
    await settle();
    expect(element.querySelector('.hide-modal h2')?.textContent).toContain('Hide these 2 works');
    button('Hide them').click();
    await settle();

    expect(writtenHidden().sort()).toEqual(['individual work:1', 'individual work:2']);
    expect(writes).toBe(1);
    expect(titles()).toEqual(['Work 3']);
    expect(element.textContent).toContain('Hid 2 works.');
  });

  it('keeps the works ticked and hides nothing when the warning is cancelled', async () => {
    await listing([MINE, OLD], true);
    await tick('Work 1', 'Work 2');

    [...element.querySelectorAll<HTMLButtonElement>('.selection-bar button')].find((b) => b.textContent?.trim() === 'Hide all')!.click();
    await settle();
    button('Cancel').click();
    await settle();

    expect(store.files.has(HIDDEN_FILE)).toBe(false);
    expect(element.querySelectorAll('input.pick:checked')).toHaveLength(2);
  });

  it('unhides only the ticked works that were hidden, with no warning', async () => {
    await library.hide([BY_LINK, IN_COLLECTION]);
    await listing([MINE, BY_LINK, IN_COLLECTION], true);
    await showHidden();
    await tick('Work 1', 'Work 3');

    [...element.querySelectorAll<HTMLButtonElement>('.selection-bar button')].find((b) => b.textContent?.trim() === 'Unhide all')!.click();
    await settle();

    expect(element.querySelector('.hide-modal')).toBeNull();
    expect(writtenHidden()).toEqual(['individual work:4']);
    expect(element.textContent).toContain('Unhid 1 work.');
  });

  // endregion

  it('reads back what was hidden when the library is opened again', async () => {
    await library.hide(BY_LINK);
    library.hidden.set(new Map());

    await (library as unknown as { readHidden(g: number): Promise<void> }).readHidden(
      (library as unknown as { generation: number }).generation,
    );

    expect([...library.hidden().keys()]).toEqual(['individual work:3']);
  });

  it('lists works from elsewhere in the library, but not one only a series brought in', () => {
    (library as unknown as { publish(w: Bookmark[], c: [], k: ReturnType<typeof emptyCopies>): void })
      .publish([MINE, BY_LINK, IN_COLLECTION, ONLY_IN_SERIES], [], emptyCopies());
    expect(library.data()!.works.map((w) => w.id)).toEqual(['1', '3', '4']);
  });
});
