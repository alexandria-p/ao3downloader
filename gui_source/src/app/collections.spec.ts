import { describe, expect, it } from 'vitest';
import {
  collectionBadges,
  collectionNameFromLink,
  flattenCollection,
  historyLength,
  isCollectionRecord,
} from './collections';

const COLLECTION = {
  name: 'yuletide',
  link: 'https://archiveofourown.org/collections/yuletide',
  source: 'https://archiveofourown.org/users/Someone/collections',
  last_indexed: '2026-09-10T12:00:00+00:00',
  indexes: [
    {
      indexed_on: '2026-09-10T12:00:00+00:00',
      title: 'Yuletide',
      challenge_type: 'Gift Exchange Challenge',
      work_ids: ['1', '2'],
      bookmark_ids: [],
    },
  ],
};

const BOOKMARK = {
  id: '34816549',
  link: 'https://archiveofourown.org/works/34816549',
  source: 'https://archiveofourown.org/users/Someone/bookmarks',
  position: 4,
  indexes: [{ indexed_on: '2026-09-10T12:00:00+00:00', title: 'A Fic', kudos: 12 }],
};

describe('isCollectionRecord', () => {
  it('recognises a collection file', () => {
    expect(isCollectionRecord(COLLECTION)).toBe(true);
  });

  it('does not mistake a bookmark for one', () => {
    // both kinds carry a versioned history, so shape is what separates them
    expect(isCollectionRecord(BOOKMARK)).toBe(false);
  });

  it('does not mistake a work whose title happens to be under a name field', () => {
    expect(isCollectionRecord({ name: 'not a collection', title: 'A Fic' })).toBe(false);
  });

  it('recognises a flat collection file written without a history', () => {
    expect(isCollectionRecord({ name: 'yuletide', work_ids: [] })).toBe(true);
  });

  it('says no to anything that is not a record at all', () => {
    expect(isCollectionRecord(null)).toBe(false);
    expect(isCollectionRecord('yuletide')).toBe(false);
    expect(isCollectionRecord([])).toBe(false);
  });
});

describe('flattenCollection', () => {
  it('reads the newest reading with the identity laid over it', () => {
    const flat = flattenCollection({
      ...COLLECTION,
      indexes: [
        { indexed_on: '2026-09-01T10:00:00+00:00', title: 'Old', work_ids: ['1'] },
        { indexed_on: '2026-09-10T12:00:00+00:00', title: 'New', work_ids: ['1', '2'] },
      ],
    })!;

    expect(flat.title).toBe('New');
    expect(flat.work_ids).toEqual(['1', '2']);
    // identity is not versioned, so the root wins
    expect(flat.name).toBe('yuletide');
    expect(flat.link).toBe('https://archiveofourown.org/collections/yuletide');
  });

  it('falls back to the ao3 name when a collection has no display title', () => {
    const flat = flattenCollection({ name: 'yuletide', work_ids: [] })!;

    expect(flat.title).toBe('yuletide');
  });

  it('fills in the lists that are missing, so the page never has to guard them', () => {
    const flat = flattenCollection({ name: 'yuletide', challenge_type: 'No Challenge' })!;

    expect(flat.work_ids).toEqual([]);
    expect(flat.bookmark_ids).toEqual([]);
    expect(flat.tags).toEqual([]);
    expect(flat.maintainers).toEqual([]);
    expect(flat.subcollections).toEqual([]);
  });

  it('returns nothing for a bookmark', () => {
    expect(flattenCollection(BOOKMARK)).toBeNull();
  });

  it('counts the readings kept', () => {
    expect(historyLength(flattenCollection(COLLECTION)!)).toBe(1);
    expect(historyLength(flattenCollection({ name: 'x', work_ids: [] })!)).toBe(0);
  });
});

describe('collectionBadges', () => {
  it('names only the flags that are set', () => {
    const flat = flattenCollection({
      name: 'yuletide',
      work_ids: [],
      closed: true,
      moderated: true,
      unrevealed: false,
      anonymous: false,
      multifandom: true,
    })!;

    expect(collectionBadges(flat)).toEqual(['Closed', 'Moderated', 'Multifandom']);
  });

  it('says nothing about multifandom when the fandom count was never read', () => {
    const flat = flattenCollection({ name: 'yuletide', work_ids: [] })!;

    expect(collectionBadges(flat)).toEqual([]);
  });
});

describe('collectionNameFromLink', () => {
  it('takes the ao3 name out of a collection url', () => {
    expect(collectionNameFromLink('https://archiveofourown.org/collections/yuletide')).toBe(
      'yuletide',
    );
    expect(collectionNameFromLink('https://archiveofourown.org/collections/yuletide/works')).toBe(
      'yuletide',
    );
  });

  it('gives the link back when there is no name in it to take', () => {
    expect(collectionNameFromLink('not a url')).toBe('not a url');
  });
});
