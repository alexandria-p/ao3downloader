import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ImportDialog } from './import-dialog';
import { DatingResult, FoundFile, FoundWork, ImportRequest, unindexedWorks } from './imports';
import { Jobs } from './jobs';
import { Library } from './library';
import { IMPORT_EXCLUDED_FILE, LibraryImports } from './imports';
import { Bookmark } from './bookmarks';
import { LibraryStore } from './library-store';

class MemoryStore implements LibraryStore {
  readonly label = 'memory';
  readonly renamed: [string, string][] = [];
  /** renames that fail, by the path they come from */
  readonly refuse = new Set<string>();
  /** renames held until let go, to look at the page while they run */
  hold: Promise<void> | null = null;
  async check() {}
  async list() {
    return [];
  }
  readonly written = new Map<string, string>();
  async read(path: string) {
    return this.written.get(path) ?? null;
  }
  async write(path: string, body: Response) {
    const text = await body.text();
    this.written.set(path, text);
    return text.length;
  }
  async size() {
    return null;
  }
  async delete() {}
  async rename(from: string, to: string) {
    if (this.hold) await this.hold;
    if (this.refuse.has(from)) throw new Error(`${to} is already there`);
    this.renamed.push([from, to]);
  }
  async mkdir() {}
}

/** the helper's naming, standing in: a file of an indexed work gets that entry's name */
class FakeJobs extends Jobs {
  asked: unknown[] = [];
  override async fileNames(files: readonly { file: { name: string }; date: string; record?: object }[]) {
    this.asked.push(files);
    return files.map((x) => {
      const record = x.record as Bookmark | undefined;
      const ext = x.file.name.slice(x.file.name.lastIndexOf('.'));
      return record ? `${record.id} ${record.title} - ${record.authors?.[0]} ${x.date}${ext}` : '';
    });
  }
}

let fixture: ComponentFixture<ImportDialog>;
let element: HTMLElement;
let store: MemoryStore;
let jobs: FakeJobs;
let closed: (DatingResult | null)[];
let started: { request: ImportRequest; dated: DatingResult | null }[];

const SOME = unindexedWorks(
  ['works/1 A - B 2024-01-01.html', 'works/2 C - D.html', 'works/2 C - D.pdf', 'works/3 E - F.epub'],
  new Set(),
);
const ALL_DATED = unindexedWorks(['works/1 A - B 2024-01-01.html'], new Set());
const INDEXED_UNDATED: FoundFile[] = [
  { id: '7', path: 'works/7 old name.html', name: '7 old name.html', format: 'html', date: '' },
];

beforeEach(() => {
  jobs = new FakeJobs();
  TestBed.configureTestingModule({ providers: [{ provide: Jobs, useValue: jobs }] });
});

async function open(works: FoundWork[] = SOME, busy = false, elsewhere: FoundFile[] = []) {
  fixture = TestBed.createComponent(ImportDialog);
  store = new MemoryStore();
  fixture.componentRef.setInput('works', works);
  fixture.componentRef.setInput('undatedElsewhere', elsewhere);
  fixture.componentRef.setInput('store', store);
  fixture.componentRef.setInput('busy', busy);
  closed = [];
  started = [];
  fixture.componentInstance.closed.subscribe((x) => closed.push(x));
  fixture.componentInstance.start.subscribe((x) => started.push(x));
  await fixture.whenStable();
  element = fixture.nativeElement as HTMLElement;
}

function button(text: string): HTMLButtonElement | undefined {
  return Array.from(element.querySelectorAll('button')).find((b) => b.textContent?.trim() === text);
}

function primary(): HTMLButtonElement {
  return element.querySelector<HTMLButtonElement>('footer .button.primary')!;
}

function step(): string {
  return element.querySelector('.dialog')?.getAttribute('data-step') ?? '';
}

async function click(text: string) {
  // the first page's Continue waits for a choice: these walks repair
  if (step() === 'overview' && text === 'Continue') await pick('repair');
  button(text)!.click();
  await settle();
}

async function pick(choice: string) {
  element.querySelector<HTMLInputElement>(`input[name="firstChoice"][value="${choice}"]`)!.click();
  await fixture.whenStable();
}

async function settle() {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await fixture.whenStable();
  }
}

async function type(input: HTMLInputElement, value: string) {
  input.value = value;
  input.dispatchEvent(new Event('input'));
  await fixture.whenStable();
}

function row(path: string): HTMLTableRowElement {
  return element.querySelector<HTMLTableRowElement>(`tr[data-file="${path}"]`)!;
}

function dateBox(path: string): HTMLInputElement {
  return row(path).querySelector<HTMLInputElement>('input[type="date"]')!;
}

function skipBox(path: string): HTMLInputElement {
  return row(path).querySelector<HTMLInputElement>('input[type="checkbox"]')!;
}

function rowOrder(): string[] {
  return Array.from(element.querySelectorAll('tr[data-file]')).map((r) => r.getAttribute('data-file')!);
}

describe('ImportDialog', () => {
  // region the overview

  it('opens on an overview that says what was found, and lists nothing yet', async () => {
    await open();
    expect(step()).toBe('overview');
    expect(element.querySelector('.overview-undated')?.textContent).toContain(
      '3 files imported from your library have no date in their names. You can give them a date next.',
    );
    expect(element.querySelector('.overview-unindexed')?.textContent).toContain(
      'Your library has 3 works that were imported with no index entry.',
    );
    expect(element.querySelector('tr[data-file]')).toBeNull();
    expect(element.textContent).not.toContain('1 A - B');
  });

  it('says only what applies', async () => {
    await open(ALL_DATED);
    expect(element.querySelector('.overview-undated')).toBeNull();
    expect(element.querySelector('.overview-unindexed')?.textContent).toContain('1 work that was imported');
  });

  it('goes straight to the index question when no file needs a date', async () => {
    await open(ALL_DATED);
    await click('Continue');
    expect(step()).toBe('index');
  });

  it('goes from the dates to the formats when no work needs an index entry', async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    expect(step()).toBe('dates');
    await click('Skip this step');
    expect(step()).toBe('formats');
  });

  it('renames and starts nothing while a run is going, and says why', async () => {
    await open(SOME, true);
    expect(element.querySelector('.busy-note')?.textContent).toContain('A run is in progress');
    expect(button('Continue')!.disabled).toBe(true);
  });

  it('asks what to do first, holding Continue until something is chosen', async () => {
    await open();
    expect(button('Not now')).toBeUndefined();
    expect(element.querySelector('.dont-ask')).toBeNull();
    expect(primary().disabled).toBe(true);
    const labels = [...element.querySelectorAll('input[name="firstChoice"]')].map(
      (x) => x.closest('label')!.querySelector('span')!.childNodes[0].textContent!.trim(),
    );
    expect(labels).toEqual([
      'Repair now (recommended)',
      'Not now, remind me again next time I open my library',
      'No, do not ask me again for these files',
      'No, never ask me again',
    ]);

    for (const [choice, text] of [['repair', 'Continue'], ['later', 'Remind me later'], ['exclude', 'Done'], ['never', 'Done']]) {
      await pick(choice);
      expect(primary().disabled).toBe(false);
      expect(primary().textContent?.trim()).toBe(text);
    }
  });

  it('closes on Remind me later, having changed nothing', async () => {
    await open();
    await pick('later');
    await click('Remind me later');
    expect(closed).toEqual([null]);
    expect(store.renamed).toEqual([]);
    expect(store.written.size).toBe(0);
  });

  it('puts every file found on the files list on No, do not ask me again', async () => {
    await open(SOME, false, INDEXED_UNDATED);
    TestBed.inject(Library).store.set(store);
    const imports = TestBed.inject(LibraryImports);
    await pick('exclude');
    await click('Done');

    expect(closed).toEqual([null]);
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    expect(written.excluded.map((x: { id: string; kind: string; files: string[] }) => [x.id, x.kind, x.files])).toEqual([
      ['1', 'files', ['1 A - B 2024-01-01.html']],
      ['2', 'files', ['2 C - D.html', '2 C - D.pdf']],
      ['3', 'files', ['3 E - F.epub']],
      ['7', 'files', ['7 old name.html']],
    ]);
    expect(imports.hasIssues()).toBe(false);
  });

  it('turns itself off for good on No, never ask me again', async () => {
    await open();
    const changed: boolean[] = [];
    fixture.componentInstance.askAgainChanged.subscribe((x) => changed.push(x));
    await pick('never');
    await click('Done');
    expect(changed).toEqual([false]);
    expect(closed).toEqual([null]);
  });

  it('cannot start repairing while a run is going, but can still be put off', async () => {
    await open(SOME, true);
    await pick('repair');
    expect(primary().disabled).toBe(true);
    await pick('later');
    expect(primary().disabled).toBe(false);
  });

  it('never says what comes after the formats page', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    expect(element.textContent).not.toContain('Next you log in to AO3');
  });

  // endregion

  // region the dates

  it('lists the undated files by name, and offers to skip the step while none has a date', async () => {
    await open();
    await click('Continue');
    expect(rowOrder()).toEqual(['works/2 C - D.html', 'works/2 C - D.pdf', 'works/3 E - F.epub']);
    expect(primary().textContent?.trim()).toBe('Skip this step');
    expect(row('works/2 C - D.html').querySelector('td.file-name')!.getAttribute('title')).toBe('2 C - D.html');

    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    expect(primary().textContent?.trim()).toBe('Date 1 file and continue');
  });

  it('greys a skipped row and its date, without striking it through', async () => {
    await open();
    await click('Continue');
    skipBox('works/2 C - D.pdf').click();
    await fixture.whenStable();
    expect(row('works/2 C - D.pdf').classList).toContain('skipped');
    expect(dateBox('works/2 C - D.pdf').disabled).toBe(true);
    expect(getComputedStyle(row('works/2 C - D.pdf').querySelector('td')!).textDecoration).not.toContain('line-through');
  });

  it('fills every date with Use for all, leaving skips as they are and changeable', async () => {
    await open();
    await click('Continue');
    skipBox('works/2 C - D.pdf').click();
    await type(element.querySelector<HTMLInputElement>('input[name="bulkDate"]')!, '2024-01-31');
    await click('Use for all');

    expect(rowOrder().map((p) => dateBox(p).value)).toEqual(['2024-01-31', '2024-01-31', '2024-01-31']);
    expect(skipBox('works/2 C - D.pdf').checked).toBe(true);
    expect(primary().textContent).toContain('Date 2 files');
    skipBox('works/2 C - D.pdf').click();
    await fixture.whenStable();
    expect(primary().textContent).toContain('Date 3 files');
  });

  it('ticks every skip with Skip all', async () => {
    await open();
    await click('Continue');
    await click('Skip all');
    expect(rowOrder().every((p) => skipBox(p).checked)).toBe(true);
    expect(primary().textContent?.trim()).toBe('Skip this step');
    await click('Skip this step');
    expect(store.renamed).toEqual([]);
    expect(step()).toBe('index');
  });

  it('shows the files a page at a time or as one scrolling list, keeping what was set', async () => {
    const many = unindexedWorks(
      Array.from({ length: 30 }, (_, i) => `works/${100 + i} Fic ${String(i).padStart(2, '0')} - W.html`),
      new Set(),
    );
    await open(many);
    await click('Continue');
    expect(rowOrder()).toHaveLength(25);
    await type(dateBox('works/100 Fic 00 - W.html'), '2024-02-02');
    await click('Next');
    expect(rowOrder()).toHaveLength(5);

    await click('One scrolling list');
    expect(rowOrder()).toHaveLength(30);
    expect(dateBox('works/100 Fic 00 - W.html').value).toBe('2024-02-02');
    // back to pages, on the page it was on
    await click('Pages');
    expect(rowOrder()).toHaveLength(5);
    await click('Previous');
    expect(dateBox('works/100 Fic 00 - W.html').value).toBe('2024-02-02');
  });

  // endregion

  // region inferring dates

  const MESSY = unindexedWorks(
    [
      'works/10 Zeta 20230115 - W.html',
      'works/11 Alpha - W (posted 03-04-2022).epub',
      'works/12 Beta - W.pdf',
      'works/13 Gamma 14 Dec 2021 - W.html',
      'works/20240304 Delta - W.html',
    ],
    new Set(),
  );

  it('reads dates out of the names, whatever their form, and moves what it dated to the top in yellow', async () => {
    await open(MESSY);
    await click('Continue');
    skipBox('works/13 Gamma 14 Dec 2021 - W.html').click();
    await fixture.whenStable();
    await click('Infer date');

    // dated and not skipped, by name; then dated and skipped, by name; then the rest, by name
    expect(rowOrder()).toEqual([
      'works/10 Zeta 20230115 - W.html',
      'works/11 Alpha - W (posted 03-04-2022).epub',
      'works/13 Gamma 14 Dec 2021 - W.html',
      'works/12 Beta - W.pdf',
      'works/20240304 Delta - W.html',
    ]);
    expect(dateBox('works/10 Zeta 20230115 - W.html').value).toBe('2023-01-15');
    expect(dateBox('works/11 Alpha - W (posted 03-04-2022).epub').value).toBe('2022-03-04');
    // a skipped file is dated too, and stays skipped
    expect(dateBox('works/13 Gamma 14 Dec 2021 - W.html').value).toBe('2021-12-14');
    expect(skipBox('works/13 Gamma 14 Dec 2021 - W.html').checked).toBe(true);
    expect(row('works/13 Gamma 14 Dec 2021 - W.html').classList).toContain('inferred');
    // a work number is not a date
    expect(dateBox('works/20240304 Delta - W.html').value).toBe('');
    expect(row('works/10 Zeta 20230115 - W.html').classList).toContain('inferred');
    expect(element.querySelector('.infer-said')?.textContent).toContain('3 files were auto-dated');
    expect(primary().textContent).toContain('Date 2 files');
  });

  it('takes the yellow off a row changed by hand, which stays where it is', async () => {
    await open(MESSY);
    await click('Continue');
    await click('Infer date');
    await type(dateBox('works/10 Zeta 20230115 - W.html'), '2023-01-20');
    expect(row('works/10 Zeta 20230115 - W.html').classList).not.toContain('inferred');
    expect(rowOrder()[0]).toBe('works/10 Zeta 20230115 - W.html');
  });

  it('says when it could date nothing', async () => {
    await open(unindexedWorks(['works/1 No Date Here - W.html'], new Set()));
    await click('Continue');
    await click('Infer date');
    expect(element.querySelector('.infer-said')?.textContent).toContain('Unable to auto-date any works');
  });

  it('holds Continue and its own button while it runs', async () => {
    await open(MESSY);
    await click('Continue');
    button('Infer date')!.click();
    fixture.detectChanges();
    expect(element.querySelector<HTMLButtonElement>('.button.infer')!.disabled).toBe(true);
    expect(element.querySelector('.button.infer .spinner')).not.toBeNull();
    expect(primary().disabled).toBe(true);
    await settle();
    expect(primary().disabled).toBe(false);
  });

  // endregion

  // region dating

  it('renames on a page of its own, then says how many, with failures folded away', async () => {
    await open();
    await click('Continue');
    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    await type(dateBox('works/3 E - F.epub'), '2024-07-08');
    store.refuse.add('works/3 E - F.epub');
    let letGo!: () => void;
    store.hold = new Promise<void>((resolve) => (letGo = resolve));
    primary().click();
    await settle();

    expect(step()).toBe('dating');
    expect(element.querySelector('.dating-progress')?.textContent).toContain('Dating files');
    expect(primary().disabled).toBe(true);
    expect(button('Back')).toBeUndefined();

    letGo();
    await settle();
    expect(element.querySelector('.dated-said')?.textContent).toContain('Dated 1 file');
    const failures = element.querySelector<HTMLDetailsElement>('details.dating-failures')!;
    expect(failures.open).toBe(false);
    expect(failures.textContent).toContain('works/3 E - F.epub');
    expect(store.renamed).toEqual([['works/2 C - D.html', 'works/2 C - D 2024-05-06.html']]);
    expect(primary().disabled).toBe(false);
    await click('Continue');
    expect(step()).toBe('index');
  });

  it('names a file of an indexed work from its entry, with the date given', async () => {
    TestBed.inject(Library).worksById.set(new Map([['7', { id: '7', title: 'The Fic', authors: ['Writer'] } as Bookmark]]));
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    await type(dateBox('works/7 old name.html'), '2024-02-03');
    primary().click();
    await settle();

    expect(store.renamed).toEqual([['works/7 old name.html', 'works/7 The Fic - Writer 2024-02-03.html']]);
  });

  it('stops renaming when closed part way, keeping what was renamed', async () => {
    await open();
    await click('Continue');
    await click('Skip all');
    for (const path of ['works/2 C - D.html', 'works/2 C - D.pdf']) {
      skipBox(path).click();
      await type(dateBox(path), '2024-05-06');
    }
    let letGo!: () => void;
    store.hold = new Promise<void>((resolve) => (letGo = resolve));
    primary().click();
    await settle();
    element.querySelector<HTMLButtonElement>('header .icon')!.click();
    letGo();
    await settle();

    expect(closed).toHaveLength(1);
    expect(store.renamed.length).toBeLessThanOrEqual(1);
  });

  // endregion

  // region the index and the formats

  it('asks about the index on a page of its own, then the formats on the next', async () => {
    await open(ALL_DATED);
    await click('Continue');
    expect(element.textContent).toContain('Fetch their index entries from AO3 now?');
    expect(element.textContent).not.toContain('Also download them in other formats?');
    await click('Continue');
    expect(step()).toBe('formats');
    expect(element.textContent).toContain('Also download them in other formats?');
    expect(element.textContent).toContain('Replace a copy you have when AO3 has a newer version');
  });

  function radio(name: string, value: string): HTMLInputElement | null {
    return element.querySelector<HTMLInputElement>(`input[name="${name}"][value="${value}"]`);
  }

  async function choose(name: string, value: string) {
    radio(name, value)!.click();
    await fixture.whenStable();
  }

  async function tick(name: string) {
    element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!.click();
    await fixture.whenStable();
  }

  it('starts an import of every work found, with the formats ticked and whether to replace', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    expect(radio('updateScope', 'all')!.checked).toBe(true);
    await tick('format-EPUB');
    await tick('replaceOutdated');
    await click('Continue');

    expect(started[0].request).toEqual({
      links: 'https://archiveofourown.org/works/1',
      count: 1,
      filetypes: ['JSON', 'EPUB'],
      replaceOutdated: true,
      indexOnly: [],
      lookups: 1,
      scope: 'all',
    });
  });

  it('takes in the indexed works whose files were undated, for their formats and outdated copies', async () => {
    await open(ALL_DATED, false, INDEXED_UNDATED);
    await click('Continue');
    await click('Skip this step');
    await click('Continue');
    await tick('replaceOutdated');
    await click('Continue');
    expect(started[0].request.links).toBe(
      'https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/7',
    );
  });

  it('never shows the index page when every work has an index entry: dating goes straight to the formats', async () => {
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    expect(step()).toBe('dates');
    await type(row('works/7 old name.html').querySelector<HTMLInputElement>('input[type="date"]')!, '2024-02-03');
    await click('Date 1 file and continue');
    expect(step()).toBe('dating');
    await click('Continue');
    expect(step()).toBe('formats');
    expect(element.textContent).not.toContain('Fetch their index entries');
    // and only the scopes that have works: no index issues to pick
    expect(radio('updateScope', 'index')).toBeNull();
    expect(radio('updateScope', 'dates')).toBeTruthy();

    // skipping the dates goes straight there too
    await open([], false, INDEXED_UNDATED);
    await click('Continue');
    await click('Skip this step');
    expect(step()).toBe('formats');
  });

  it('never offers an update for the undated file of a work left out of the index question', async () => {
    const left: FoundFile = { ...INDEXED_UNDATED[0], id: '9', path: 'works/9 x.html', name: '9 x.html', unindexed: true };
    await open([], false, [left, ...INDEXED_UNDATED]);
    await click('Continue');
    await click('Skip this step');
    expect(step()).toBe('formats');
    // work 7 only: work 9 has no index entry and is never looked up
    expect(element.querySelector('input[name="updateScope"][value="all"]')!.closest('label')!.textContent).toContain('(1)');
  });

  it('offers updating just the date issues or just the index issues only where there are some', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    expect(radio('updateScope', 'all')).toBeTruthy();
    expect(radio('updateScope', 'dates')).toBeNull();
    expect(radio('updateScope', 'index')).toBeTruthy();
    expect(radio('updateScope', 'skip')).toBeTruthy();

    await open(SOME);
    await click('Continue');
    await click('Skip this step');
    await click('Continue');
    expect(radio('updateScope', 'dates')).toBeTruthy();
    expect(radio('updateScope', 'index')).toBeTruthy();
  });

  it('downloads only for the works with date issues when told, still looking up the rest', async () => {
    await open(SOME);
    await click('Continue');
    await click('Skip this step');
    await click('Continue');
    await choose('updateScope', 'dates');
    await tick('format-EPUB');
    await click('Continue');

    const request = started[0].request;
    expect(request.links.split('\n').map((l) => l.split('/').pop())).toEqual(['1', '2', '3']);
    expect(request.indexOnly).toEqual(['1']);
    expect(request.scope).toBe('dates');
    expect(request.filetypes).toEqual(['JSON', 'EPUB']);
  });

  it('hides the formats and replacing when the step is skipped, and does neither', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue');
    await tick('format-EPUB');
    await tick('replaceOutdated');
    await choose('updateScope', 'skip');
    expect(element.querySelector('input[name="format-EPUB"]')).toBeNull();
    expect(element.querySelector('input[name="replaceOutdated"]')).toBeNull();
    await click('Continue');

    expect(started[0].request).toMatchObject({
      filetypes: ['JSON'],
      replaceOutdated: false,
      indexOnly: ['1'],
      lookups: 1,
      scope: 'skip',
    });
  });

  it('is done without a run when there is nothing for one to do', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await choose('lookup', 'later');
    // nothing left that could be updated, so the window ends here
    await click('Done');
    expect(started).toEqual([]);
    expect(closed).toEqual([null]);
  });

  it('is done without a run when an update is chosen with nothing to download or replace', async () => {
    await open(ALL_DATED, false, INDEXED_UNDATED);
    await click('Continue');
    await click('Skip this step');
    await choose('lookup', 'later');
    await click('Continue');
    expect(primary().textContent?.trim()).toBe('Done');
    await click('Done');
    expect(started).toEqual([]);
  });

  it('never offers works again once told not to, writing them to the library', async () => {
    await open(ALL_DATED);
    TestBed.inject(Library).store.set(store);
    const imports = TestBed.inject(LibraryImports);
    imports.found.set(ALL_DATED);
    await click('Continue');
    await choose('lookup', 'never');
    await click('Done');
    await settle();

    expect(started).toEqual([]);
    expect(closed).toHaveLength(1);
    const written = JSON.parse(store.written.get(IMPORT_EXCLUDED_FILE)!);
    // the work, and the files that brought it here
    expect(written.excluded).toMatchObject([{ id: '1', kind: 'index', files: ['1 A - B 2024-01-01.html'] }]);
    expect(imports.found()).toEqual([]);
  });

  // endregion
});
