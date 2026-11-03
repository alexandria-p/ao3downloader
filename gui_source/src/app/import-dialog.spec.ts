import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ImportDialog } from './import-dialog';
import { DatingResult, FoundWork, ImportRequest, unindexedWorks } from './imports';
import { LibraryStore } from './library-store';

class MemoryStore implements LibraryStore {
  readonly label = 'memory';
  readonly renamed: [string, string][] = [];
  async check() {}
  async list() {
    return [];
  }
  async read() {
    return null;
  }
  async write() {
    return 0;
  }
  async size() {
    return null;
  }
  async delete() {}
  async rename(from: string, to: string) {
    this.renamed.push([from, to]);
  }
  async mkdir() {}
}

let fixture: ComponentFixture<ImportDialog>;
let element: HTMLElement;
let store: MemoryStore;
let closed: (DatingResult | null)[];
let started: { request: ImportRequest; dated: DatingResult | null }[];

const SOME = unindexedWorks(
  ['works/1 A - B 2024-01-01.html', 'works/2 C - D.html', 'works/2 C - D.pdf', 'works/3 E - F.epub'],
  new Set(),
);
const ALL_DATED = unindexedWorks(['works/1 A - B 2024-01-01.html'], new Set());

async function open(works: FoundWork[] = SOME, busy = false) {
  fixture = TestBed.createComponent(ImportDialog);
  store = new MemoryStore();
  fixture.componentRef.setInput('works', works);
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

function step(): string {
  return element.querySelector('.dialog')?.getAttribute('data-step') ?? '';
}

async function click(text: string) {
  button(text)!.click();
  await fixture.whenStable();
}

async function type(input: HTMLInputElement, value: string) {
  input.value = value;
  input.dispatchEvent(new Event('input'));
  await fixture.whenStable();
}

function dateBox(path: string): HTMLInputElement {
  return element.querySelector<HTMLInputElement>(`tr[data-file="${path}"] input[type="date"]`)!;
}

function skipBox(path: string): HTMLInputElement {
  return element.querySelector<HTMLInputElement>(`tr[data-file="${path}"] input[type="checkbox"]`)!;
}

describe('ImportDialog', () => {
  it('says what it found, by work and file, and how many have no date', async () => {
    await open();
    const said = element.textContent ?? '';
    expect(said).toContain('3 works');
    expect(said).toContain('4 files');
    expect(said).toContain('3 files have no date');
    expect(element.querySelectorAll('.found-list .file-name.undated').length).toBe(3);
  });

  it('goes straight to fetching when every file is dated', async () => {
    await open(ALL_DATED);
    await click('Continue');
    expect(step()).toBe('fetch');
  });

  it('cannot leave the dates until every undated file has a date or a skip', async () => {
    await open();
    await click('Continue');
    expect(step()).toBe('dates');
    const go = () => element.querySelector<HTMLButtonElement>('footer .button.primary')!;
    expect(go().disabled).toBe(true);
    expect(element.querySelector('.unsettled')?.textContent).toContain('3 still need');

    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    skipBox('works/2 C - D.pdf').click();
    await fixture.whenStable();
    expect(go().disabled).toBe(true);
    await type(dateBox('works/3 E - F.epub'), '2024-07-08');
    expect(go().disabled).toBe(false);
    expect(go().textContent).toContain('Date 2 files and continue');
  });

  it('dates each file it was given a date for, leaves a skipped one, and says so', async () => {
    await open();
    await click('Continue');
    await type(dateBox('works/2 C - D.html'), '2024-05-06');
    skipBox('works/2 C - D.pdf').click();
    await type(dateBox('works/3 E - F.epub'), '2024-07-08');
    element.querySelector<HTMLButtonElement>('footer .button.primary')!.click();
    await fixture.whenStable();

    expect(store.renamed).toEqual([
      ['works/2 C - D.html', 'works/2 C - D 2024-05-06.html'],
      ['works/3 E - F.epub', 'works/3 E - F 2024-07-08.epub'],
    ]);
    expect(step()).toBe('fetch');
    expect(element.querySelector('.dated-said')?.textContent).toContain('Dated 2 files');
  });

  it('gives every undated file one date at once', async () => {
    await open();
    await click('Continue');
    await type(element.querySelector<HTMLInputElement>('input[name="bulkDate"]')!, '2024-01-31');
    await click('Use for all');
    element.querySelector<HTMLButtonElement>('footer .button.primary')!.click();
    await fixture.whenStable();

    expect(store.renamed.map(([, to]) => to)).toEqual([
      'works/2 C - D 2024-01-31.html',
      'works/2 C - D 2024-01-31.pdf',
      'works/3 E - F 2024-01-31.epub',
    ]);
  });

  it('skips them all without renaming anything', async () => {
    await open();
    await click('Continue');
    await click('Skip all');
    await click('Continue');

    expect(store.renamed).toEqual([]);
    expect(step()).toBe('fetch');
  });

  it('starts an import of every work found, with the formats ticked and whether to replace', async () => {
    await open(ALL_DATED);
    await click('Continue');
    element.querySelector<HTMLInputElement>('input[name="format-EPUB"]')!.click();
    element.querySelector<HTMLInputElement>('input[name="replaceOutdated"]')!.click();
    await fixture.whenStable();
    await click('Continue to the run');

    expect(started).toHaveLength(1);
    expect(started[0].request).toEqual({
      links: 'https://archiveofourown.org/works/1',
      count: 1,
      filetypes: ['JSON', 'EPUB'],
      replaceOutdated: true,
    });
  });

  it('indexes only, keeping every copy, unless told otherwise', async () => {
    await open(ALL_DATED);
    await click('Continue');
    await click('Continue to the run');
    expect(started[0].request.filetypes).toEqual(['JSON']);
    expect(started[0].request.replaceOutdated).toBe(false);
  });

  it('can be finished without fetching anything, keeping the dates given', async () => {
    await open();
    await click('Continue');
    await type(element.querySelector<HTMLInputElement>('input[name="bulkDate"]')!, '2024-01-31');
    await click('Use for all');
    element.querySelector<HTMLButtonElement>('footer .button.primary')!.click();
    await fixture.whenStable();
    element.querySelectorAll<HTMLInputElement>('input[name="fetchNow"]')[1].click();
    await fixture.whenStable();
    await click('Done');

    expect(started).toEqual([]);
    expect(closed).toHaveLength(1);
    expect(closed[0]?.renamed).toHaveLength(3);
  });

  it('is closed by Not now, having changed nothing', async () => {
    await open();
    await click('Not now');
    expect(closed).toEqual([null]);
    expect(store.renamed).toEqual([]);
  });

  it('renames and starts nothing while a run is going, and says why', async () => {
    await open(SOME, true);
    expect(element.querySelector('.busy-note')?.textContent).toContain('A run is in progress');
    expect(button('Continue')!.disabled).toBe(true);
  });
});
