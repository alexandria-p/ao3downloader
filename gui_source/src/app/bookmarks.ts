/**
 * Shapes and pure helpers for the json file written by ao3downloader's JSON download type.
 * Keep these in step with parse_soup.get_blurb_metadata and actions/ao3download.metadata_file.
 */

export interface WorkTags {
  rating: string;
  categories: string[];
  relationships: string[];
  characters: string[];
  additional: string[];
}

/** one reading of a bookmark, as stored in the file's history */
export interface BookmarkIndex {
  indexed_on: string;
  [field: string]: unknown;
}

/** the helper's `BOOKMARK_TYPE_*` */
export type BookmarkType = 'individual work' | 'external work' | 'series bookmark';

/** what an entry is, reading an entry from before types were recorded as a work */
export function bookmarkTypeOf(record: Bookmark): BookmarkType {
  return record.bookmark_type ?? 'individual work';
}

/**
 * Whether an index entry is a work - something with a work number and a file to open.
 *
 * A bookmarked series and an external work have entries of their own, in folders inside
 * indexing/. A folder read through the File System Access API arrives flat, so this goes by
 * what the entry says, not where it was.
 */
export function isWorkEntry(record: Bookmark): boolean {
  return bookmarkTypeOf(record) === 'individual work';
}

/**
 * Whether an entry belongs in the bookmarks listing - that is, whether it is one of your
 * bookmarks.
 *
 * Everything is, except a work that is in the index only because a series you bookmarked
 * holds it: that is shown inside its series' card, not a second time on its own. An entry
 * from before `bookmarked` was recorded came off your bookmarks, so it counts.
 */
export function isBookmarkEntry(record: Bookmark): boolean {
  return !(isWorkEntry(record) && record.bookmarked === false);
}

/** whether a work, or a series, is finished - which the two record differently */
export function isEntryComplete(record: Bookmark): boolean {
  return bookmarkTypeOf(record) === 'series bookmark' ? !!record.complete : isComplete(record);
}

export interface Bookmark {
  /** provenance, written into every per-work file */
  source?: string;
  retrieved?: string;
  /** when the fic was last checked, whether or not anything had changed */
  last_indexed?: string;
  /** every reading kept for this fic, oldest first */
  indexes?: BookmarkIndex[];
  /**
   * What the bookmark is of. Entries from before this was recorded have none, and are
   * individual works.
   */
  bookmark_type?: BookmarkType;
  /** false for a work in the index only because a series you bookmarked holds it */
  bookmarked?: boolean;
  /** the bookmarked series, by id, a work was found through */
  from_series?: string[];
  /** on a series: how many works it holds, whether it is finished, and which works */
  works?: number | null;
  complete?: boolean;
  work_ids?: string[];
  id: string | null;
  link: string | null;
  title: string;
  authors: string[];
  date_created: string | null;
  date_updated: string;
  fandoms: string[];
  warnings: string[];
  tags: WorkTags;
  summary: string;
  words: number | null;
  chapters_published: number | null;
  chapters_total: number | null;
  comments: number | null;
  kudos: number | null;
  bookmarks: number | null;
  hits: number | null;
  date_bookmarked: string;
  bookmark_notes: string;
  bookmark_tags: string[];
  bookmark_collections: string[];
  bookmark_private: boolean;
  bookmark_rec: boolean;
  /** present instead of the rest when a blurb could not be parsed */
  error?: string;
  /**
   * Set when this stands in for a work that is listed somewhere - a collection - but has
   * no entry in the index. Its number and link are all that is known about it.
   */
  placeholder?: boolean;
}

export interface BookmarksExport {
  source: string;
  retrieved: string;
  count: number;
  works: Bookmark[];
}

export const AO3_BASE_URL = 'https://archiveofourown.org';

/**
 * Turn one file's contents into a bookmark to display.
 *
 * A file keeps a history of readings, so the newest one is what to show, with the
 * identity at the root laid over it. Files written before that history existed are flat,
 * and are used as they are.
 */
export function flattenRecord(parsed: unknown): Bookmark | null {
  if (!parsed || typeof parsed !== 'object') return null;
  const record = parsed as Record<string, unknown>;

  const history = record['indexes'];
  if (Array.isArray(history)) {
    const latest = history[history.length - 1];
    if (!latest || typeof latest !== 'object') return null;
    // root last so identity wins: id, link, source and bookmark type are not versioned
    return { ...(latest as object), ...record } as unknown as Bookmark;
  }

  return record['id'] || record['title'] ? (record as unknown as Bookmark) : null;
}

/**
 * A stand-in for a work that something lists but the index has no entry for.
 *
 * A collection records the works it holds by work number alone, and a collection can hold
 * works you have never bookmarked. Rather than dropping those, they are shown with the one
 * thing that is known about them - the number - and a link to the work on ao3.
 */
export function placeholderWork(id: string): Bookmark {
  return {
    placeholder: true,
    id,
    link: `${AO3_BASE_URL}/works/${id}`,
    title: `Work ${id}`,
    authors: [],
    date_created: null,
    date_updated: '',
    fandoms: [],
    warnings: [],
    tags: { rating: '', categories: [], relationships: [], characters: [], additional: [] },
    summary: '',
    words: null,
    chapters_published: null,
    chapters_total: null,
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
  };
}

export type PageItem = number | 'gap';

/**
 * Page numbers to show, with gaps collapsed - 1 2 3 4 5 6 7 ... 79.
 * Keeps a window of `span` pages around the current one, always showing the first and last.
 */
export function pageItems(current: number, total: number, span = 7): PageItem[] {
  if (total < 1) return [];
  if (total <= span + 1) return range(1, total);

  const start = Math.max(1, Math.min(current - Math.floor(span / 2), total - span + 1));
  const end = Math.min(total, start + span - 1);

  const items: PageItem[] = [];
  if (start > 1) {
    items.push(1);
    if (start > 2) items.push('gap');
  }
  items.push(...range(start, end));
  if (end < total) {
    if (end < total - 1) items.push('gap');
    items.push(total);
  }
  return items;
}

function range(from: number, to: number): number[] {
  return Array.from({ length: to - from + 1 }, (_, i) => from + i);
}

/**
 * ao3downloader's default file name pattern is '{worknum} {title} - {author}', so a
 * downloaded work can be matched back to its metadata by the number it starts with.
 * Returns null for a file named some other way, which just means no local copy is linked.
 */
export function workIdFromFilename(name: string): string | null {
  const base = name.split(/[\\/]/).pop() ?? '';
  // the number has to be followed by a separator, so a title that merely starts with
  // digits ('99 Red Balloons' is a work number, '99Red Balloons' is not) isn't mistaken for one
  const match = /^(\d+)(?:[\s_.\-]|$)/.exec(base);
  return match ? match[1] : null;
}

const MONTHS = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
];

/**
 * An AO3 date turned into `YYYY-MM-DD`, or '' when it is not one.
 *
 * AO3 writes the same date two ways - `14 Dec 2024` on a listing blurb, `2024-12-14` on a
 * work's own page - and an index holds whichever the run that wrote it saw. Comparing them
 * as plain strings would order a listing date by its day number, so both are normalised to
 * the form that sorts correctly.
 *
 * This is the browser's half of `parse_text.get_date_stamp`. Anything unrecognised comes
 * back empty rather than throwing: a filter must never be the reason a listing fails to
 * render, and a work with no readable date simply cannot be placed in a range.
 */
export function dateStamp(text: string): string {
  const value = (text ?? '').trim();
  if (!value) return '';

  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;

  const listing = /^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})$/.exec(value);
  if (!listing) return '';

  const month = MONTHS.indexOf(listing[2].toLowerCase());
  if (month < 0) return '';
  return `${listing[3]}-${String(month + 1).padStart(2, '0')}-${listing[1].padStart(2, '0')}`;
}

/** 'https://archiveofourown.org/users/Someone/bookmarks' -> 'Someone' */
export function ownerFromSource(source: string): string {
  return /\/users\/([^/?#]+)/.exec(source ?? '')?.[1] ?? '';
}

export function authorLink(author: string): string {
  return `${AO3_BASE_URL}/users/${encodeURIComponent(author)}`;
}

/** ao3 shows '?' as the total for a work in progress, which the export stores as null. */
export function isComplete(work: Bookmark): boolean {
  return work.chapters_total !== null && work.chapters_published === work.chapters_total;
}

export function chapterCount(work: Bookmark): string {
  return `${work.chapters_published ?? '?'}/${work.chapters_total ?? '?'}`;
}

/** The export stores summaries and notes as plain text with blank lines between paragraphs. */
export function paragraphs(text: string): string[] {
  return (text ?? '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

/**
 * Colour band for the rating tile, mirroring ao3's own symbol colours.
 */
export function ratingClass(rating: string): string {
  const value = (rating ?? '').toLowerCase();
  if (value.includes('general')) return 'rating-general';
  if (value.includes('teen')) return 'rating-teen';
  if (value.includes('mature')) return 'rating-mature';
  if (value.includes('explicit')) return 'rating-explicit';
  return 'rating-none';
}

export function warningClass(warnings: string[]): string {
  const list = warnings ?? [];
  if (list.some((w) => w.toLowerCase().startsWith('no archive warnings'))) return 'warning-none';
  if (list.some((w) => w.toLowerCase().startsWith('choose not to use'))) return 'warning-maybe';
  return list.length > 0 ? 'warning-yes' : 'warning-none';
}
