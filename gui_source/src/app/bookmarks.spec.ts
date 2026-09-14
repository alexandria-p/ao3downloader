import { describe, expect, it } from 'vitest';
import {
  Bookmark,
  chapterCount,
  dateStamp,
  isComplete,
  ownerFromSource,
  pageItems,
  paragraphs,
  ratingClass,
  warningClass,
  workIdFromFilename,
} from './bookmarks';

function work(overrides: Partial<Bookmark> = {}): Bookmark {
  return {
    id: '111',
    link: 'https://archiveofourown.org/works/111',
    title: 'A Work',
    authors: ['Writer'],
    date_created: null,
    date_updated: '01 Jan 2020',
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
    ...overrides,
  };
}

describe('pageItems', () => {
  it('lists every page when they all fit', () => {
    expect(pageItems(1, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it('collapses the tail on the first page', () => {
    expect(pageItems(1, 79)).toEqual([1, 2, 3, 4, 5, 6, 7, 'gap', 79]);
  });

  it('collapses both ends in the middle of a long list', () => {
    expect(pageItems(40, 79)).toEqual([1, 'gap', 37, 38, 39, 40, 41, 42, 43, 'gap', 79]);
  });

  it('keeps the window inside the list at the end', () => {
    expect(pageItems(79, 79)).toEqual([1, 'gap', 73, 74, 75, 76, 77, 78, 79]);
  });

  it('handles an empty export', () => {
    expect(pageItems(1, 0)).toEqual([]);
  });
});

describe('workIdFromFilename', () => {
  it("reads the work number off ao3downloader's default file name", () => {
    expect(workIdFromFilename('34816549 No Paths Are Bound - Author.html')).toBe('34816549');
  });

  it('reads it out of a nested path', () => {
    expect(workIdFromFilename('downloads/sub folder/218676 Some Work - A.html')).toBe('218676');
  });

  it('returns null when the name does not start with a work number', () => {
    expect(workIdFromFilename('Some Work - Author.html')).toBeNull();
  });

  it('does not match a number that runs into the title', () => {
    // '99Red Balloons' is a title, not a work number followed by one
    expect(workIdFromFilename('99Red Balloons.html')).toBeNull();
  });
});

describe('ownerFromSource', () => {
  it('reads the username out of a bookmarks url', () => {
    expect(ownerFromSource('https://archiveofourown.org/users/Someone/bookmarks')).toBe('Someone');
  });

  it('returns empty for a listing that is not a user page', () => {
    expect(ownerFromSource('https://archiveofourown.org/tags/Some%20Tag/works')).toBe('');
  });

  it('tolerates a missing source', () => {
    expect(ownerFromSource('')).toBe('');
  });
});

describe('chapter helpers', () => {
  it('treats a work in progress as incomplete', () => {
    const wip = work({ chapters_published: 3, chapters_total: null });
    expect(isComplete(wip)).toBe(false);
    expect(chapterCount(wip)).toBe('3/?');
  });

  it('treats a finished work as complete', () => {
    const done = work({ chapters_published: 152, chapters_total: 152 });
    expect(isComplete(done)).toBe(true);
    expect(chapterCount(done)).toBe('152/152');
  });

  it('does not call a partially posted work complete', () => {
    expect(isComplete(work({ chapters_published: 23, chapters_total: 35 }))).toBe(false);
  });
});

describe('paragraphs', () => {
  it('splits stored text back into paragraphs', () => {
    expect(paragraphs('one\ntwo')).toEqual(['one', 'two']);
  });

  it('drops blank lines', () => {
    expect(paragraphs('one\n\n  \ntwo')).toEqual(['one', 'two']);
  });

  it('returns nothing for an empty summary', () => {
    expect(paragraphs('')).toEqual([]);
  });
});

describe('symbol classes', () => {
  it('maps ao3 ratings onto colour bands', () => {
    expect(ratingClass('Explicit')).toBe('rating-explicit');
    expect(ratingClass('Teen And Up Audiences')).toBe('rating-teen');
    expect(ratingClass('Not Rated')).toBe('rating-none');
    expect(ratingClass('')).toBe('rating-none');
  });

  it('distinguishes real warnings from the two placeholder ones', () => {
    expect(warningClass(['No Archive Warnings Apply'])).toBe('warning-none');
    expect(warningClass(['Choose Not To Use Archive Warnings'])).toBe('warning-maybe');
    expect(warningClass(['Graphic Depictions Of Violence'])).toBe('warning-yes');
    expect(warningClass([])).toBe('warning-none');
  });
});

describe('dateStamp', () => {
  // ao3 writes the same date two ways and an index holds whichever the run that wrote it
  // saw, so both have to end up comparable
  it('reads the form a listing blurb uses', () => {
    expect(dateStamp('14 Dec 2024')).toBe('2024-12-14');
    expect(dateStamp('1 Jan 2020')).toBe('2020-01-01');
  });

  it('leaves the form a work page uses alone', () => {
    expect(dateStamp('2024-12-14')).toBe('2024-12-14');
  });

  it('sorts correctly once normalised, which is the whole point', () => {
    const dates = ['14 Dec 2024', '01 Feb 2025', '2024-01-30'].map(dateStamp).sort();
    expect(dates).toEqual(['2024-01-30', '2024-12-14', '2025-02-01']);
  });

  it('gives back nothing for anything it cannot read', () => {
    // a filter must never be the reason a listing fails to render
    for (const junk of ['', '   ', 'sometime', '14 Xxx 2024', '2024', 'yesterday']) {
      expect(dateStamp(junk)).toBe('');
    }
    expect(dateStamp(undefined as unknown as string)).toBe('');
  });
});
