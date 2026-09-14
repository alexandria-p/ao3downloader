import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { WorkList } from './work-list';
import { Bookmark } from './bookmarks';

/**
 * Narrowing a listing that is already on disk.
 *
 * Every filter here reads what the folder holds, so it costs no requests and works with the
 * helper stopped. What it must never do is quietly show less than it says it is showing.
 */

interface Partial {
  id: string;
  title?: string;
  authors?: string[];
  updated?: string;
  bookmarked?: string;
}

function work(given: Partial): Bookmark {
  return {
    id: given.id,
    link: `https://archiveofourown.org/works/${given.id}`,
    title: given.title ?? `Work ${given.id}`,
    authors: given.authors ?? ['Writer'],
    date_created: null,
    date_updated: given.updated ?? '01 Jan 2020',
    fandoms: ['A Fandom'],
    warnings: ['No Archive Warnings Apply'],
    tags: {
      rating: 'General Audiences',
      categories: [],
      relationships: [],
      characters: [],
      additional: [],
    },
    summary: '',
    words: 100,
    chapters_published: 1,
    chapters_total: 1,
    comments: null,
    kudos: null,
    bookmarks: null,
    hits: null,
    date_bookmarked: given.bookmarked ?? '02 Feb 2021',
    bookmark_notes: '',
    bookmark_tags: [],
    bookmark_collections: [],
    bookmark_private: false,
    bookmark_rec: false,
  } as Bookmark;
}

let fixture: ComponentFixture<WorkList>;
let element: HTMLElement;

async function listing(works: Bookmark[]) {
  fixture = TestBed.createComponent(WorkList);
  fixture.componentRef.setInput('works', works);
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function shownTitles(): string[] {
  // `a.title` only: the heading also links every author, and those are not titles
  return Array.from(element.querySelectorAll('.blurb .heading a.title')).map(
    (a) => a.textContent?.trim() ?? '',
  );
}

function shownCount(): number {
  return element.querySelectorAll('.blurb').length;
}

async function type(name: string, value: string) {
  const input = element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!;
  input.value = value;
  input.dispatchEvent(new Event('input'));
  await fixture.whenStable();
}

const LIBRARY = [
  work({ id: '1', title: 'No Paths Are Bound', authors: ['Cataclysmic_Cal'],
         updated: '14 Dec 2024', bookmarked: '01 Mar 2025' }),
  work({ id: '2', title: 'Catch and Release', authors: ['Like_a_Hurricane'],
         updated: '02 Aug 2026', bookmarked: '10 Sep 2026' }),
  work({ id: '3', title: 'The Dating Game', authors: ['inukagome15', 'Cataclysmic_Cal'],
         updated: '2026-01-15', bookmarked: '05 Jan 2026' }),
];

describe('WorkList filtering', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [WorkList] }).compileComponents();
  });

  it('shows everything when nothing has been filled in', async () => {
    await listing(LIBRARY);

    expect(shownCount()).toBe(3);
    expect(element.querySelector('.filtered-note')).toBeNull();
  });

  it('matches part of a title, whatever the case', async () => {
    await listing(LIBRARY);

    await type('titleQuery', 'dating');

    expect(shownTitles()).toEqual(['The Dating Game']);
  });

  it('matches part of an author name, including a second author', async () => {
    await listing(LIBRARY);

    await type('authorQuery', 'cataclysmic');

    // work 3 lists two authors, and the second one is the match
    expect(shownTitles().sort()).toEqual(['No Paths Are Bound', 'The Dating Game']);
  });

  it('narrows by when AO3 last updated the work, counting both ends', async () => {
    await listing(LIBRARY);

    await type('updatedFrom', '2024-12-14');
    await type('updatedTo', '2026-01-15');

    // the two on the boundaries are kept; the 2026-08 one is outside
    expect(shownTitles().sort()).toEqual(['No Paths Are Bound', 'The Dating Game']);
  });

  it('narrows by when the work was bookmarked', async () => {
    await listing(LIBRARY);

    await type('bookmarkedFrom', '2026-01-01');

    expect(shownTitles().sort()).toEqual(['Catch and Release', 'The Dating Game']);
  });

  it('reads both of the date forms AO3 writes', async () => {
    // work 3's updated date is stored as 2026-01-15, the others as '14 Dec 2024' style
    await listing(LIBRARY);

    await type('updatedFrom', '2026-01-01');
    await type('updatedTo', '2026-01-31');

    expect(shownTitles()).toEqual(['The Dating Game']);
  });

  it('makes every filter that was filled in have to match', async () => {
    await listing(LIBRARY);

    await type('authorQuery', 'cataclysmic');
    await type('updatedFrom', '2026-01-01');

    // both authored by Cal, but only one updated this year
    expect(shownTitles()).toEqual(['The Dating Game']);
  });

  // it cannot be placed in the range, and including it would make the range a lie
  it('leaves a work with no readable date out of a date range', async () => {
    const undated = work({ id: '4', title: 'Undated', updated: '', bookmarked: '' });
    await listing([...LIBRARY, undated]);

    expect(shownCount()).toBe(4);

    await type('updatedFrom', '2000-01-01');

    expect(shownTitles()).not.toContain('Undated');
  });

  it('says the listing is filtered, so a short one is not read as a small library', async () => {
    await listing(LIBRARY);

    await type('titleQuery', 'dating');

    expect(element.querySelector('.filtered-note')?.textContent).toContain('3');
    expect(element.querySelector('.listing-heading')?.textContent).toContain('of 1');
  });

  it('clears back to the whole listing', async () => {
    await listing(LIBRARY);
    await type('titleQuery', 'dating');
    expect(shownCount()).toBe(1);

    const clear = Array.from(element.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('Clear filters'),
    )!;
    clear.click();
    await fixture.whenStable();

    expect(shownCount()).toBe(3);
    expect(element.querySelector('.filtered-note')).toBeNull();
  });

  // staying on page 9 of a result that now has one page would show an empty listing and
  // look like the filter had found nothing
  it('goes back to the first page when the filter changes', async () => {
    const many = Array.from({ length: 45 }, (_, i) =>
      work({ id: String(i + 1), title: i === 44 ? 'Findable' : `Filler ${i + 1}` }),
    );
    await listing(many);

    const second = Array.from(element.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === '2',
    )!;
    second.click();
    await fixture.whenStable();
    expect(element.querySelector('.listing-heading')?.textContent).toContain('21 - 40');

    await type('titleQuery', 'findable');

    expect(shownTitles()).toEqual(['Findable']);
    expect(element.querySelector('.listing-heading')?.textContent).toContain('1 - 1');
  });
});
