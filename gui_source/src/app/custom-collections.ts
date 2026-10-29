import { Injectable, computed, inject } from '@angular/core';
import { Library } from './library';
import { Bookmark, bookmarkTypeOf } from './bookmarks';
import { Collection, flattenCollection, isCustomCollection } from './collections';

/**
 * Collections made in this app: works picked from the listing and grouped under a name of the
 * person's own choosing, beside the collections indexed from ao3.
 *
 * **They live in `collections/custom/`, and the helper never sees them.** Every helper read
 * of `collections/` lists that folder's own files only, never a folder inside it - so a
 * custom collection is not linked into works' `from_collections`, not counted by the
 * new-bookmarks walk, and cannot be overwritten by a collection run of the same name. The
 * page reads the whole folder and tells collections from works by shape, so it finds them.
 *
 * **A name that can never be an ao3 one.** ao3 collection names are letters, digits and
 * underscores, so a custom collection's `custom-` prefix keeps the two apart for good. The
 * name is the file's name too, so renaming the title later moves nothing.
 *
 * Works from ao3 collections are never changed here: what ao3 says a collection holds is
 * ao3's to say, and the next collection run would only put it back.
 */

/** where custom collections are kept, inside the library */
export const CUSTOM_COLLECTIONS_FOLDER = 'collections/custom';
export const CUSTOM_PREFIX = 'custom-';
/** the longest title a custom collection takes */
export const TITLE_LIMIT = 120;

/**
 * What can go into a custom collection: works, and external works - each by the number ao3
 * gives it, kept apart because the two are numbered separately. Series are left out: a
 * collection holds works, and a series is already a group of its own.
 */
export interface CollectionItems {
  works: string[];
  externals: string[];
}

/** the works and external works among `entries`, by number, in the order given */
export function itemsOf(entries: Bookmark[]): CollectionItems {
  const works: string[] = [];
  const externals: string[] = [];
  for (const entry of entries) {
    if (!entry.id || entry.error) continue;
    const type = bookmarkTypeOf(entry);
    if (type === 'individual work') works.push(entry.id);
    else if (type === 'external work') externals.push(entry.id);
  }
  return { works, externals };
}

/** whether an entry can be put in a custom collection at all */
export function canCollect(entry: Bookmark): boolean {
  return !!entry.id && !entry.error && bookmarkTypeOf(entry) !== 'series bookmark';
}

@Injectable({ providedIn: 'root' })
export class CustomCollections {
  private readonly library = inject(Library);

  /** the custom collections, by title - the targets an add can go to */
  readonly all = computed(() => this.library.collections().filter(isCustomCollection));

  /**
   * Whether this library can be written to. A folder handed over as a list of files, by a
   * browser with no folder picker, can only be read - so nothing can be collected there.
   */
  readonly writable = computed(() => !!this.library.store());

  /** Make a collection holding `items`, and answer it. */
  async create(title: string, items: CollectionItems): Promise<Collection> {
    const name = title.trim().slice(0, TITLE_LIMIT);
    if (!name) throw new Error('give the collection a name');
    return this.save({
      name: this.newName(),
      custom: true,
      link: null,
      title: name,
      description: '',
      created: new Date().toISOString().slice(0, 10),
      work_ids: unique(items.works),
      bookmark_ids: [],
      external_ids: unique(items.externals),
    });
  }

  /** Add `items` to a custom collection, keeping what it holds and its order. */
  async add(name: string, items: CollectionItems): Promise<Collection> {
    const collection = this.customNamed(name);
    return this.save({
      ...this.documentOf(collection),
      work_ids: unique([...collection.work_ids, ...items.works]),
      external_ids: unique([...collection.external_ids, ...items.externals]),
    });
  }

  /** Take `items` out of a custom collection. */
  async remove(name: string, items: CollectionItems): Promise<Collection> {
    const collection = this.customNamed(name);
    const works = new Set(items.works);
    const externals = new Set(items.externals);
    return this.save({
      ...this.documentOf(collection),
      work_ids: collection.work_ids.filter((id) => !works.has(id)),
      external_ids: collection.external_ids.filter((id) => !externals.has(id)),
    });
  }

  /** an ao3 collection is refused here, whatever asked: it is not the app's to change */
  private customNamed(name: string): Collection {
    const collection = this.library.collections().find((c) => c.name === name);
    if (!collection) throw new Error('that collection is not in this library any more');
    if (!isCustomCollection(collection)) {
      throw new Error('a collection from AO3 cannot be changed here - only your own collections can');
    }
    return collection;
  }

  /** what is written for a custom collection: its own fields, not everything flattening added */
  private documentOf(collection: Collection): Record<string, unknown> {
    return {
      name: collection.name,
      custom: true,
      link: null,
      title: collection.title,
      description: collection.description,
      created: collection.created,
      work_ids: collection.work_ids,
      bookmark_ids: [],
      external_ids: collection.external_ids,
    };
  }

  private async save(document: Record<string, unknown>): Promise<Collection> {
    const store = this.library.store();
    if (!store) throw new Error('this library can only be read, so nothing can be saved to it');
    const written: Record<string, unknown> = { ...document, last_modified: new Date().toISOString() };
    await store.write(
      `${CUSTOM_COLLECTIONS_FOLDER}/${written['name']}.json`,
      new Response(JSON.stringify(written, null, 2) + '\n'),
    );
    const collection = flattenCollection(written);
    if (!collection) throw new Error('the collection could not be read back');
    // shown at once, as the library would read it back, rather than rereading the library
    const others = this.library.collections().filter((c) => c.name !== collection.name);
    this.library.collections.set(
      [...others, collection].sort((a, b) => (a.title || '').localeCompare(b.title || '')),
    );
    return collection;
  }

  private newName(): string {
    const taken = new Set(this.library.collections().map((c) => c.name));
    for (;;) {
      const bytes = crypto.getRandomValues(new Uint8Array(5));
      const name = CUSTOM_PREFIX + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
      if (!taken.has(name)) return name;
    }
  }
}

function unique(ids: string[]): string[] {
  return [...new Set(ids.map(String))];
}
