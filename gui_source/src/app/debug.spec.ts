import { TestBed } from '@angular/core/testing';
import { DEBUG_MODE_KEY, DebugMode, MemoryStore, mockLibrary, mockPaths } from './debug';
import { DebugTab } from './debug-tab';

describe('debug mode', () => {
  beforeEach(() => localStorage.clear());

  it('is off until turned on, and remembered by this browser', () => {
    expect(TestBed.inject(DebugMode).on()).toBe(false);
    TestBed.inject(DebugMode).set(true);
    expect(localStorage.getItem(DEBUG_MODE_KEY)).toBe('on');
    TestBed.inject(DebugMode).set(false);
    expect(localStorage.getItem(DEBUG_MODE_KEY)).toBeNull();
  });
});

describe('a mock library', () => {
  it('has only the issues asked for, as many as asked', () => {
    const all = mockLibrary({ duplicates: true, duplicateCount: 4, index: true, indexCount: 5, dates: true, datesCount: 6 });
    expect(all.works).toHaveLength(5);
    expect(all.duplicates).toHaveLength(4);
    expect(all.undatedElsewhere.length).toBeGreaterThan(0);

    const dupesOnly = mockLibrary({ duplicates: true, duplicateCount: 3, index: false, indexCount: 5, dates: false, datesCount: 6 });
    expect(dupesOnly.works).toEqual([]);
    expect(dupesOnly.duplicates).toHaveLength(3);
    // a duplicate group's undated copy is an indexed work's undated file - offered for dating too
    expect(dupesOnly.undatedElsewhere.every((f) => f.id.startsWith('72'))).toBe(true);

    const indexOnly = mockLibrary({ duplicates: false, duplicateCount: 3, index: true, indexCount: 2, dates: false, datesCount: 6 });
    expect(indexOnly.works).toHaveLength(2);
    expect(indexOnly.duplicates).toEqual([]);
    expect(indexOnly.undatedElsewhere).toEqual([]);
  });

  it('keeps every file in memory, renamed and deleted there alone', async () => {
    const { paths } = mockPaths({ duplicates: true, duplicateCount: 1, index: false, indexCount: 0, dates: false, datesCount: 0 });
    const store = new MemoryStore(paths);
    await store.rename(paths[0], 'works/renamed.html');
    await store.delete(paths[1]);
    expect(await store.list('works')).toEqual(['works/renamed.html']);
    await expect(store.rename('works/renamed.html', 'works/renamed.html')).rejects.toThrow();
  });
});

describe('the DEBUG tab', () => {
  it('opens the window on a mock, and shows the request instead of starting a run', async () => {
    const fixture = TestBed.createComponent(DebugTab);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    element.querySelector<HTMLButtonElement>('button.open-mock')!.click();
    await fixture.whenStable();
    expect(element.querySelector('app-import-dialog')).toBeTruthy();
    expect(element.querySelector('app-import-dialog')!.textContent).toContain('Resolve issues found in your library');
  });

  it('cannot open with no issue chosen', async () => {
    const fixture = TestBed.createComponent(DebugTab);
    await fixture.whenStable();
    const element = fixture.nativeElement as HTMLElement;
    for (const name of ['mockDuplicates', 'mockIndex', 'mockDates']) {
      element.querySelector<HTMLInputElement>(`input[name="${name}"]`)!.click();
    }
    await fixture.whenStable();
    expect(element.querySelector<HTMLButtonElement>('button.open-mock')!.disabled).toBe(true);
  });
});
