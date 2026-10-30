import { Bookmark } from './bookmarks';

/**
 * The tags on works in the index, kind by kind, for filtering a listing by them - including
 * some and leaving others out, as ao3's own Sort and Filter panel does.
 *
 * **Nothing is fetched and nothing is stored.** Every tag is already in the index the page has
 * read, so the index of tags is built from the works in memory - once per library read, and
 * again only when the works change (a run's refresh, a different library). Building it is a
 * single pass over every work, milliseconds for thousands; looking one up as someone types is a
 * scan of the distinct tags, which is far fewer. A cache kept in the browser would only be a
 * second copy of the index that could fall behind it.
 */

/** the kinds of tag ao3 shows in its filter panel, in its order */
export type TagKind =
  | 'rating'
  | 'warning'
  | 'category'
  | 'fandom'
  | 'character'
  | 'relationship'
  | 'additional';

export const TAG_KINDS: { kind: TagKind; label: string; one: string }[] = [
  { kind: 'rating', label: 'Ratings', one: 'Rating' },
  { kind: 'warning', label: 'Warnings', one: 'Warning' },
  { kind: 'category', label: 'Categories', one: 'Category' },
  { kind: 'fandom', label: 'Fandoms', one: 'Fandom' },
  { kind: 'character', label: 'Characters', one: 'Character' },
  { kind: 'relationship', label: 'Relationships', one: 'Relationship' },
  { kind: 'additional', label: 'Additional Tags', one: 'Additional tag' },
];

/** one tag, as chosen or as offered: which kind it is, and its name as ao3 writes it */
export interface TagChoice {
  kind: TagKind;
  name: string;
}

/** a tag in the index, with how many works carry it */
export interface TagCount extends TagChoice {
  count: number;
  /** its name in lower case, worked out once rather than on every keystroke */
  lower: string;
}

/** every distinct tag, by kind, most-used first - and all of them together, for typing */
export interface TagIndex {
  byKind: Record<TagKind, TagCount[]>;
  all: TagCount[];
}

/** the same tag whatever its case - ao3 treats 'Fluff' and 'fluff' as one */
export function tagKey(tag: TagChoice): string {
  return `${tag.kind}:${tag.name.trim().toLowerCase()}`;
}

/** a work's tags, by kind. A series or an external work carries what its blurb showed */
export function tagsOf(work: Bookmark): Record<TagKind, string[]> {
  const tags = work.tags ?? ({} as Bookmark['tags']);
  const list = (value: unknown) =>
    (Array.isArray(value) ? value : []).filter((x): x is string => typeof x === 'string' && !!x.trim());
  return {
    rating: tags.rating ? [tags.rating] : [],
    warning: list(work.warnings),
    category: list(tags.categories),
    fandom: list(work.fandoms),
    character: list(tags.characters),
    relationship: list(tags.relationships),
    additional: list(tags.additional),
  };
}

/** Count every distinct tag across `works`, by kind, most-used first. */
export function buildTagIndex(works: Bookmark[]): TagIndex {
  const counts = new Map<string, TagCount>();
  for (const work of works) {
    const tags = tagsOf(work);
    for (const { kind } of TAG_KINDS) {
      // a work counts once per tag, however its index happens to repeat one
      const seen = new Set<string>();
      for (const name of tags[kind]) {
        const key = tagKey({ kind, name });
        if (seen.has(key)) continue;
        seen.add(key);
        const found = counts.get(key);
        if (found) found.count++;
        else counts.set(key, { kind, name: name.trim(), count: 1, lower: name.trim().toLowerCase() });
      }
    }
  }
  const order = (a: TagCount, b: TagCount) => b.count - a.count || a.name.localeCompare(b.name);
  const all = [...counts.values()].sort(order);
  const byKind = Object.fromEntries(TAG_KINDS.map(({ kind }) => [kind, [] as TagCount[]])) as Record<
    TagKind,
    TagCount[]
  >;
  for (const tag of all) byKind[tag.kind].push(tag);
  return { byKind, all };
}

/**
 * The tags matching what has been typed, for the box under the filter: any tag containing it,
 * those starting with it first, then the most used - as ao3's own suggestions do. Tags already
 * chosen are left out.
 */
export function suggestTags(
  index: TagIndex,
  typed: string,
  chosen: ReadonlySet<string>,
  limit = 15,
): TagCount[] {
  const query = typed.trim().toLowerCase();
  if (!query) return [];
  const starts: TagCount[] = [];
  const contains: TagCount[] = [];
  for (const tag of index.all) {
    const at = tag.lower.indexOf(query);
    if (at < 0 || chosen.has(tagKey(tag))) continue;
    if (at === 0) starts.push(tag);
    else if (contains.length < limit) contains.push(tag);
    // most-used first already, so the first that start with it are the ones to offer
    if (starts.length >= limit) break;
  }
  return [...starts, ...contains].slice(0, limit);
}

/** `name` cut around what was typed, so the match can be shown in bold, as ao3 does */
export function highlight(name: string, typed: string): { before: string; match: string; after: string } {
  const at = name.toLowerCase().indexOf(typed.trim().toLowerCase());
  if (at < 0 || !typed.trim()) return { before: name, match: '', after: '' };
  const end = at + typed.trim().length;
  return { before: name.slice(0, at), match: name.slice(at, end), after: name.slice(end) };
}

/**
 * Whether a work passes the tag filters: **every** included tag, and **none** of the excluded
 * ones - as ao3 narrows. A tag is matched within its own kind, so a character named the same
 * as a fandom is not mistaken for it.
 */
export function matchesTags(work: Bookmark, include: TagChoice[], exclude: TagChoice[]): boolean {
  if (!include.length && !exclude.length) return true;
  const keys = keysOf(work);
  const has = (tag: TagChoice) => keys.has(tagKey(tag));
  return include.every(has) && !exclude.some(has);
}

/**
 * A work's tags as keys, worked out once per work and remembered for as long as the work is -
 * so changing a filter is one lookup per chosen tag per work, not a pass over all its tags.
 * A refreshed entry is a new object, so it is never answered from an old one's tags.
 */
const keysByWork = new WeakMap<Bookmark, Set<string>>();

function keysOf(work: Bookmark): Set<string> {
  let keys = keysByWork.get(work);
  if (!keys) {
    const tags = tagsOf(work);
    keys = new Set(TAG_KINDS.flatMap(({ kind }) => tags[kind].map((name) => tagKey({ kind, name }))));
    keysByWork.set(work, keys);
  }
  return keys;
}
