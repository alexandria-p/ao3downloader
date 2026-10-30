import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { Bookmark } from './bookmarks';
import { Library, emptyCopies } from './library';
import { LibraryStore } from './library-store';
import { WorkList } from './work-list';
import { buildTagIndex, highlight, matchesTags, suggestTags, tagsOf } from './tags';

/**
 * Filtering a listing by tag, as ao3's own Sort and Filter panel does: include some, leave
 * others out, by kind - and suggestions from every tag in the library as it is typed.
 */

interface Given {
  id: string;
  fandoms?: string[];
  characters?: string[];
  relationships?: string[];
  additional?: string[];
  rating?: string;
  warnings?: string[];
}

function work(given: Given): Bookmark {
  return {
    id: given.id,
    link: `https://archiveofourown.org/works/${given.id}`,
    title: `Work ${given.id}`,
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
    fandoms: given.fandoms ?? [],
    warnings: given.warnings ?? [],
    tags: {
      rating: given.rating ?? '',
      categories: [],
      relationships: given.relationships ?? [],
      characters: given.characters ?? [],
      additional: given.additional ?? [],
    },
    summary: '',
    words: null,
    chapters_published: 1,
    chapters_total: 1,
    comments: null,
    kudos: null,
    bookmarks: null,
    hits: null,
    date_bookmarked: '02 Feb 2021',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  } as Bookmark;
}

const AVATAR = work({
  id: '1',
  fandoms: ['Avatar: The Last Airbender'],
  characters: ['Aang (Avatar)', 'Zuko (Avatar)'],
  relationships: ['Aang/Katara (Avatar)'],
  additional: ['Fluff'],
  rating: 'General Audiences',
});
const ZUKO = work({
  id: '2',
  fandoms: ['Avatar: The Last Airbender'],
  characters: ['Zuko (Avatar)'],
  relationships: ['Zuko & Iroh (Avatar)'],
  additional: ['Angst', 'fluff'],
  rating: 'Teen And Up Audiences',
});
const POTTER = work({
  id: '3',
  fandoms: ['Harry Potter - J. K. Rowling'],
  characters: ['Harry Potter'],
  additional: ['Angst'],
  rating: 'Teen And Up Audiences',
});

describe('the tags of works, by kind', () => {
  it('reads each kind from where the index keeps it', () => {
    const tags = tagsOf(AVATAR);
    expect(tags.fandom).toEqual(['Avatar: The Last Airbender']);
    expect(tags.character).toEqual(['Aang (Avatar)', 'Zuko (Avatar)']);
    expect(tags.relationship).toEqual(['Aang/Katara (Avatar)']);
    expect(tags.rating).toEqual(['General Audiences']);
  });

  it('counts a tag once per work, whatever its case, most-used first', () => {
    const index = buildTagIndex([AVATAR, ZUKO, POTTER]);
    expect(index.byKind.character.map((t) => [t.name, t.count])).toEqual([
      ['Zuko (Avatar)', 2],
      ['Aang (Avatar)', 1],
      ['Harry Potter', 1],
    ]);
    // 'Fluff' and 'fluff' are one tag
    expect(index.byKind.additional.find((t) => t.name === 'Fluff')?.count).toBe(2);
  });

  it('suggests tags starting with what was typed first, then any containing it, leaving out chosen ones', () => {
    const index = buildTagIndex([AVATAR, ZUKO, POTTER]);
    const names = (typed: string, chosen: string[] = []) =>
      suggestTags(index, typed, new Set(chosen)).map((t) => t.name);

    expect(names('aang')).toEqual(['Aang (Avatar)', 'Aang/Katara (Avatar)']);
    expect(names('zuko')).toEqual(['Zuko (Avatar)', 'Zuko & Iroh (Avatar)']);
    expect(names('avatar').slice(0, 1)).toEqual(['Avatar: The Last Airbender']);
    expect(names('zuko', ['character:zuko (avatar)'])).toEqual(['Zuko & Iroh (Avatar)']);
    expect(names('   ')).toEqual([]);
  });

  it('cuts a name around what was typed, for the match to show in bold', () => {
    expect(highlight('Aang/Katara (Avatar)', 'kat')).toEqual({ before: 'Aang/', match: 'Kat', after: 'ara (Avatar)' });
  });

  it('keeps works with every included tag and none of the excluded ones, within the right kind', () => {
    const include = [{ kind: 'fandom' as const, name: 'avatar: the last airbender' }];
    const exclude = [{ kind: 'additional' as const, name: 'Angst' }];
    const kept = [AVATAR, ZUKO, POTTER].filter((w) => matchesTags(w, include, exclude));
    expect(kept.map((w) => w.id)).toEqual(['1']);
    // a character is not a fandom, even with the same name
    expect(matchesTags(AVATAR, [{ kind: 'fandom', name: 'Zuko (Avatar)' }], [])).toBe(false);
  });
});

describe('the tag filter in the listing', () => {
  let fixture: ComponentFixture<WorkList>;
  let element: HTMLElement;

  async function settle() {
    for (let i = 0; i < 3; i++) {
      await fixture.whenStable();
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    fixture.detectChanges();
  }

  async function listing(works: Bookmark[]) {
    const library = TestBed.inject(Library);
    library.worksById.set(new Map(works.map((w) => [w.id!, w])));
    fixture = TestBed.createComponent(WorkList);
    fixture.componentRef.setInput('works', works);
    await settle();
    element = fixture.nativeElement as HTMLElement;
    const filters = element.querySelector<HTMLDetailsElement>('details.filters')!;
    filters.open = true;
    filters.dispatchEvent(new Event('toggle'));
    await settle();
  }

  function titles(): string[] {
    return [...element.querySelectorAll('.blurb .heading a.title')].map((a) => a.textContent?.trim() ?? '');
  }

  async function type(half: 'include' | 'exclude', text: string) {
    const box = element.querySelector<HTMLInputElement>(`input[name="${half}Tag"]`)!;
    box.value = text;
    box.dispatchEvent(new Event('input'));
    await settle();
    return box;
  }

  function section(half: 'Include' | 'Exclude'): HTMLElement {
    return [...element.querySelectorAll<HTMLElement>('app-tag-filter')].find((s) =>
      s.querySelector('h4')?.textContent?.includes(half),
    )!;
  }

  it('draws nothing of the tag filter until the Filter panel is opened', async () => {
    fixture = TestBed.createComponent(WorkList);
    fixture.componentRef.setInput('works', [AVATAR]);
    await settle();
    expect(fixture.nativeElement.querySelector('app-tag-filter')).toBeNull();
  });

  it('suggests tags from the whole library as you type, by kind, and includes the one picked', async () => {
    await listing([AVATAR, ZUKO, POTTER]);

    await type('include', 'aang');
    const offered = [...element.querySelectorAll('.suggestions li')].map((li) => li.textContent);
    expect(offered[0]).toContain('Aang (Avatar)');
    expect(offered[0]).toContain('Character');
    expect(offered[1]).toContain('Relationship');

    (element.querySelector('.suggestions li') as HTMLElement).click();
    await settle();

    expect(titles()).toEqual(['Work 1']);
    expect(section('Include').querySelector('.chip')?.textContent).toContain('Aang (Avatar)');
    expect(element.textContent).toContain('filtered from 3');
  });

  it('takes a suggestion with the arrow keys and enter', async () => {
    await listing([AVATAR, ZUKO, POTTER]);
    const box = await type('include', 'zuko');

    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
    await settle();

    // the second suggestion: the relationship, which only work 2 carries
    expect(titles()).toEqual(['Work 2']);
  });

  it('leaves out works with an excluded tag', async () => {
    await listing([AVATAR, ZUKO, POTTER]);
    await type('exclude', 'angst');
    (element.querySelector('.suggestions li') as HTMLElement).click();
    await settle();

    expect(titles()).toEqual(['Work 1']);
  });

  it('offers each kind of tag to tick, with this listings counts, as ao3s panel does', async () => {
    await listing([AVATAR, ZUKO, POTTER]);
    const fandoms = [...section('Include').querySelectorAll('details.kind')].find((d) =>
      d.querySelector('summary')?.textContent?.includes('Fandoms'),
    )!;
    expect(fandoms.textContent).toContain('Avatar: The Last Airbender (2)');

    const box = fandoms.querySelector<HTMLInputElement>('input[type="checkbox"]')!;
    box.checked = true;
    box.dispatchEvent(new Event('change'));
    await settle();

    expect(titles().sort()).toEqual(['Work 1', 'Work 2']);
    // a tag included cannot also be ticked to exclude
    const other = [...section('Exclude').querySelectorAll<HTMLInputElement>('details.kind input')].find((i) =>
      i.parentElement?.textContent?.includes('Avatar: The Last Airbender'),
    )!;
    expect(other.disabled).toBe(true);
  });

  it('says so when nothing in the library matches', async () => {
    await listing([AVATAR]);
    await type('include', 'nothing like this');
    expect(element.textContent).toContain('No tag in your library matches that.');
  });

  it('clears the tags with the other filters', async () => {
    await listing([AVATAR, ZUKO, POTTER]);
    await type('include', 'harry');
    (element.querySelector('.suggestions li') as HTMLElement).click();
    await settle();
    expect(titles()).toEqual(['Work 3']);

    [...element.querySelectorAll('button')].find((b) => b.textContent?.includes('Clear filters'))!.click();
    await settle();

    expect(titles()).toHaveLength(3);
  });
});

describe('the listing after a run', () => {
  class MemoryStore implements LibraryStore {
    readonly label = 'memory';
    readonly files = new Map<string, string>();
    async check() {}
    async list() {
      return [...this.files.keys()];
    }
    async read(path: string) {
      return this.files.get(path) ?? null;
    }
    async write() {
      return 0;
    }
    async size() {
      return null;
    }
    async delete() {}
    async rename() {}
    async mkdir() {}
  }

  let library: Library;
  let store: MemoryStore;

  beforeEach(() => {
    library = TestBed.inject(Library);
    store = new MemoryStore();
    library.store.set(store);
    // the library as last read: two works
    (library as unknown as { publish(w: Bookmark[], c: [], k: ReturnType<typeof emptyCopies>): void })
      .publish([AVATAR, POTTER], [], emptyCopies());
  });

  it('takes in the index files the run wrote, and nothing else is read', async () => {
    const changed = { ...ZUKO, id: '1', title: 'Renamed' };
    store.files.set('indexing/1 Renamed - Writer.json', JSON.stringify(changed));
    store.files.set('indexing/2 New - Writer.json', JSON.stringify(ZUKO));
    store.files.set('indexing/3 Not touched.json', JSON.stringify({ ...POTTER, title: 'Should not be read' }));

    await library.refreshAfterRun(['indexing/1 Renamed - Writer.json', 'indexing/2 New - Writer.json', 'runs/x.json']);

    const titles = library.data()!.works.map((w) => w.title).sort();
    expect(titles).toEqual(['Renamed', 'Work 2', 'Work 3']);
    // and the tags the filter suggests from follow
    expect(library.tagIndex().byKind.relationship.map((t) => t.name)).toContain('Zuko & Iroh (Avatar)');
  });

  it('leaves the listing alone for a run in a library no longer shown', async () => {
    store.files.set('indexing/2 New.json', JSON.stringify(ZUKO));
    await library.refreshAfterRun(['indexing/2 New.json'], new MemoryStore());
    expect(library.data()!.works).toHaveLength(2);
  });
});
