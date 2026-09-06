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

export interface Bookmark {
  /** provenance, written into every per-work file */
  source?: string;
  retrieved?: string;
  /** place in the listing, which is the order ao3 shows the bookmarks in */
  position?: number;
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
}

export interface BookmarksExport {
  source: string;
  retrieved: string;
  count: number;
  works: Bookmark[];
}

export const AO3_BASE_URL = 'https://archiveofourown.org';

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
