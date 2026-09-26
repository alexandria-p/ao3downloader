import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { WorkList } from './work-list';
import { Library } from './library';
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
  created?: string;
}

function work(given: Partial): Bookmark {
  return {
    id: given.id,
    link: `https://archiveofourown.org/works/${given.id}`,
    title: given.title ?? `Work ${given.id}`,
    authors: given.authors ?? ['Writer'],
    date_created: given.created ?? null,
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

  // region sorting

  async function sortBy(value: string) {
    const select = element.querySelector<HTMLSelectElement>('select[name="sortBy"]')!;
    select.value = value;
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  it('sorts by date bookmarked, newest first', async () => {
    await listing(LIBRARY);

    await sortBy('bookmarked-desc');

    // 10 Sep 2026, 05 Jan 2026, 01 Mar 2025
    expect(shownTitles()).toEqual(['Catch and Release', 'The Dating Game', 'No Paths Are Bound']);
  });

  it('sorts by date bookmarked, oldest first', async () => {
    await listing(LIBRARY);

    await sortBy('bookmarked-asc');

    expect(shownTitles()).toEqual(['No Paths Are Bound', 'The Dating Game', 'Catch and Release']);
  });

  it('sorts by date created when works have one', async () => {
    await listing([
      work({ id: '1', title: 'Middle', created: '10 Jun 2020' }),
      work({ id: '2', title: 'Newest', created: '2024-01-01' }),
      work({ id: '3', title: 'Oldest', created: '01 Jan 2010' }),
    ]);

    await sortBy('created-desc');
    expect(shownTitles()).toEqual(['Newest', 'Middle', 'Oldest']);

    await sortBy('created-asc');
    expect(shownTitles()).toEqual(['Oldest', 'Middle', 'Newest']);
  });

  // putting blanks first on an ascending sort would bury every dated work under them
  it('puts works without the date last, whichever way it sorts', async () => {
    await listing([
      work({ id: '1', title: 'Blank', bookmarked: '' }),
      work({ id: '2', title: 'Old', bookmarked: '01 Jan 2020' }),
      work({ id: '3', title: 'New', bookmarked: '01 Jan 2025' }),
    ]);

    await sortBy('bookmarked-asc');
    expect(shownTitles()).toEqual(['Old', 'New', 'Blank']);

    await sortBy('bookmarked-desc');
    expect(shownTitles()).toEqual(['New', 'Old', 'Blank']);
  });

  // publication dates are only recorded by a lookup this app does not run, so on most
  // libraries this sort has nothing to work with - and should say so
  it('says when there is nothing to sort by, instead of doing nothing silently', async () => {
    await listing(LIBRARY);

    await sortBy('created-desc');

    expect(element.querySelector('.sort-empty')?.textContent).toContain('leaves the order unchanged');
    expect(shownTitles()).toEqual(['No Paths Are Bound', 'Catch and Release', 'The Dating Game']);

    await sortBy('bookmarked-desc');
    expect(element.querySelector('.sort-empty')).toBeNull();
  });

  it('does not call a sorted listing a filtered one', async () => {
    await listing(LIBRARY);

    await sortBy('bookmarked-desc');

    expect(element.querySelector('.filtered-note')).toBeNull();
    expect(shownCount()).toBe(3);
  });

  it('clears the sort along with the filters', async () => {
    await listing(LIBRARY);
    await sortBy('bookmarked-asc');

    Array.from(element.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('Clear filters'))!
      .click();
    await fixture.whenStable();

    // back to the default: most recently bookmarked first
    expect(shownTitles()).toEqual(['Catch and Release', 'The Dating Game', 'No Paths Are Bound']);
    expect(element.querySelector<HTMLSelectElement>('select[name="sortBy"]')!.value).toBe(
      'bookmarked-desc',
    );
  });

  it('lists the most recently bookmarked first, before anything is chosen', async () => {
    // the index keeps no listing order of its own any more
    await listing(LIBRARY);

    expect(shownTitles()).toEqual(['Catch and Release', 'The Dating Game', 'No Paths Are Bound']);
    expect(element.querySelector('.sort-empty')).toBeNull();
    // a default is not something to clear
    const clear = Array.from(element.querySelectorAll<HTMLButtonElement>('button')).find((b) =>
      b.textContent?.includes('Clear filters'),
    )!;
    expect(clear.disabled).toBe(true);
  });

  // endregion
});

describe('WorkList, bookmarks of every kind', () => {
  const series = {
    ...work({ id: '15213', title: "Watches 'Verse", bookmarked: '18 May 2026' }),
    link: 'https://archiveofourown.org/series/15213',
    bookmark_type: 'series bookmark',
    works: 3,
    complete: false,
    work_ids: ['111', '222', '999'],
  } as Bookmark;
  const external = {
    ...work({ id: '1', title: 'drift', bookmarked: '01 Jan 2026' }),
    link: 'https://example.com/drift',
    bookmark_type: 'external work',
  } as Bookmark;
  const single = {
    ...work({ id: '555', title: 'On Its Own', bookmarked: '10 Sep 2026' }),
    bookmark_type: 'individual work',
  } as Bookmark;
  // in the index because of the series; one of them bookmarked in its own right as well
  const partOne = { ...work({ id: '111', title: 'Part One' }), bookmarked: false } as Bookmark;
  const partTwo = { ...work({ id: '222', title: 'Part Two' }), bookmarked: true } as Bookmark;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [WorkList] }).compileComponents();
    const library = TestBed.inject(Library);
    library.worksById.set(new Map([['111', partOne], ['222', partTwo], ['555', single]]));
    // a downloaded copy of part one - and a file whose number happens to be the external
    // work's id, which must not be taken for its copy
    library.htmlFiles.set(new Map([
      ['111', new File(['<p>one</p>'], '111 Part One.html')],
      ['1', new File(['<p>work 1</p>'], '1 Some Other Work.html')],
    ]));
  });

  async function showTypes(value: string) {
    const select = element.querySelector<HTMLSelectElement>('select[name="typeFilter"]')!;
    select.value = value;
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  it('lists works, series and external works together, newest bookmark first', async () => {
    await listing([series, external, single]);
    expect(shownTitles()).toEqual(['On Its Own', "Watches 'Verse", 'drift']);
    expect(Array.from(element.querySelectorAll('.kind')).map((x) => x.textContent?.trim()))
      .toEqual(['Series', 'External work']);
  });

  it('narrows to one kind of bookmark', async () => {
    await listing([series, external, single]);

    await showTypes('series bookmark');
    expect(shownTitles()).toEqual(["Watches 'Verse"]);
    await showTypes('external work');
    expect(shownTitles()).toEqual(['drift']);
    await showTypes('individual work');
    expect(shownTitles()).toEqual(['On Its Own']);
    expect(element.querySelector('.filtered-note')?.textContent).toContain('3');
  });

  it('opens a series on ao3 and an external work where it is hosted', async () => {
    await listing([series, external]);
    const links = Array.from(element.querySelectorAll<HTMLAnchorElement>('.blurb .heading a.title'));
    expect(links.map((a) => [a.getAttribute('href'), a.target])).toEqual([
      ['https://archiveofourown.org/series/15213', '_blank'],
      ['https://example.com/drift', '_blank'],
    ]);
    // an external work's id is not a work number, whatever file shares it
    expect(links[1].classList.contains('local')).toBe(false);
  });

  it('keeps a series card closed until asked, then lists its works in order', async () => {
    await listing([series]);
    expect(element.querySelector('.series-list')).toBeNull();

    const toggle = element.querySelector<HTMLButtonElement>('.series-toggle')!;
    expect(toggle.textContent).toContain('Show the 3 works in this series');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    toggle.click();
    await fixture.whenStable();

    const parts = Array.from(element.querySelectorAll('.series-list li'));
    expect(parts.map((li) => li.querySelector('a.title')?.textContent?.trim())).toEqual([
      'Part One',
      'Part Two',
      // grown since the series was last read: known only by its number
      'Work 999',
    ]);
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    // a part with a downloaded copy opens it, as any work does
    expect(parts[0].querySelector('a.title')!.classList.contains('local')).toBe(true);
    // and one bookmarked in its own right says so
    expect(parts[1].querySelector('.badge')?.textContent).toContain('Also bookmarked');
    expect(parts[0].querySelector('.badge')).toBeNull();

    toggle.click();
    await fixture.whenStable();
    expect(element.querySelector('.series-list')).toBeNull();
  });

  it('says so when a series has not been read for its works yet', async () => {
    await listing([{ ...series, work_ids: [] } as Bookmark]);
    element.querySelector<HTMLButtonElement>('.series-toggle')!.click();
    await fixture.whenStable();
    expect(element.querySelector('.series-works')?.textContent).toContain('not been read for its works yet');
  });

  it('shows a series its own stats rather than chapters', async () => {
    await listing([series]);
    const stats = element.querySelector('.stats')?.textContent ?? '';
    expect(stats).toContain('Works:');
    expect(stats).toContain('Complete:');
    expect(stats).not.toContain('Chapters:');
  });
});
