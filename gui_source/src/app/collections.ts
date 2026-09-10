/**
 * Shapes and pure helpers for the json files written by the 'index collections' action.
 * Keep these in step with parse_soup.get_collection_metadata / get_collection_profile
 * and ao3.save_collection.
 */

import { AO3_BASE_URL } from './bookmarks';

/** one reading of a collection, as stored in the file's history */
export interface CollectionIndex {
  indexed_on: string;
  [field: string]: unknown;
}

export interface Collection {
  /** the ao3 name - the part of the url after /collections/ - and the file's identity */
  name: string | null;
  link: string | null;
  source?: string;
  last_indexed?: string;
  indexes?: CollectionIndex[];

  title: string;
  description: string;
  maintainers: string[];
  tags: string[];
  active_since: string;
  created: string;
  flags: string[];
  challenge_type: string;
  multifandom: boolean | null;
  closed: boolean;
  moderated: boolean;
  unrevealed: boolean;
  anonymous: boolean;
  fandom_count: number | null;
  work_count: number | null;
  bookmark_count: number | null;
  subcollection_count: number | null;
  parent_collection: string | null;
  subcollections_link: string | null;
  subcollections: string[];
  /** the work numbers in the collection, which is all that is recorded of them */
  work_ids: string[];
  bookmark_ids: string[];
  /** present when the crawl could not read part of the collection */
  error?: string;
}

/**
 * Whether a parsed json file is a collection rather than a bookmark.
 *
 * The two live in different folders, but a folder read through the file system access api
 * arrives flat - the paths are gone by the time we see the files - so this goes on shape.
 * A collection is identified by ao3 name and records what it contains; a bookmark has a
 * work id and records the work itself.
 */
export function isCollectionRecord(parsed: unknown): boolean {
  if (!parsed || typeof parsed !== 'object') return false;
  const record = merged(parsed as Record<string, unknown>);
  if (typeof record['name'] !== 'string') return false;
  return (
    Array.isArray(record['work_ids']) ||
    Array.isArray(record['bookmark_ids']) ||
    typeof record['challenge_type'] === 'string'
  );
}

/**
 * Turn one collection file into the collection to display: the newest reading, with the
 * identity at the root laid over it, exactly as bookmarks are flattened.
 */
export function flattenCollection(parsed: unknown): Collection | null {
  if (!isCollectionRecord(parsed)) return null;
  const record = merged(parsed as Record<string, unknown>);
  return {
    ...record,
    title: (record['title'] as string) || (record['name'] as string) || '',
    description: (record['description'] as string) ?? '',
    maintainers: asArray(record['maintainers']),
    tags: asArray(record['tags']),
    active_since: (record['active_since'] as string) ?? '',
    created: (record['created'] as string) ?? '',
    flags: asArray(record['flags']),
    challenge_type: (record['challenge_type'] as string) || 'No Challenge',
    multifandom: (record['multifandom'] as boolean | null) ?? null,
    subcollections: asArray(record['subcollections']),
    work_ids: asArray(record['work_ids']),
    bookmark_ids: asArray(record['bookmark_ids']),
  } as unknown as Collection;
}

/** the newest reading with the unversioned identity at the root laid over it */
function merged(record: Record<string, unknown>): Record<string, unknown> {
  const history = record['indexes'];
  if (!Array.isArray(history) || history.length === 0) return record;
  const latest = history[history.length - 1];
  if (!latest || typeof latest !== 'object') return record;
  return { ...(latest as Record<string, unknown>), ...record };
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function collectionLink(collection: Collection): string {
  return collection.link || `${AO3_BASE_URL}/collections/${collection.name ?? ''}`;
}

/** 'yuletide2024' from a parent or subcollection url, for showing a link by name */
export function collectionNameFromLink(link: string): string {
  return /\/collections\/([^/?#]+)/.exec(link ?? '')?.[1] ?? link;
}

/**
 * How many readings this collection has, which is what the history is worth showing for.
 * A file written before versioning existed has none.
 */
export function historyLength(collection: Collection): number {
  return collection.indexes?.length ?? 0;
}

/** 'Closed', 'Moderated' and so on - what ao3 shows in brackets after the name */
export function collectionBadges(collection: Collection): string[] {
  const badges: string[] = [];
  if (collection.closed) badges.push('Closed');
  if (collection.moderated) badges.push('Moderated');
  if (collection.unrevealed) badges.push('Unrevealed');
  if (collection.anonymous) badges.push('Anonymous');
  if (collection.multifandom) badges.push('Multifandom');
  return badges;
}
