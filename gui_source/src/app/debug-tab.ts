import { Component, computed, inject, input, signal } from '@angular/core';
import { DecimalPipe, JsonPipe } from '@angular/common';
import { ImportDialog } from './import-dialog';
import { DatingResult, ImportRequest } from './imports';
import { DEFAULT_MOCK, MockLibrary, MockSetup, mockLibrary } from './debug';
import { DummyData } from './dummy-data';

/**
 * The DEBUG tab, shown only in debug mode: tries the Resolve issues window on a mock library
 * in memory, set up with whichever issues are wanted. See `debug.ts` for why nothing real is
 * touched.
 */
@Component({
  selector: 'app-debug-tab',
  imports: [ImportDialog, DecimalPipe, JsonPipe],
  templateUrl: './debug-tab.html',
  styleUrl: './debug-tab.css',
})
export class DebugTab {
  /** debug mode's made-up library, in place of the real one - this tab is where it is switched */
  protected readonly dummyData = inject(DummyData);
  /** the formats the window offers - the helper's, as the real window has them */
  readonly formats = input<string[]>(['HTML', 'EPUB', 'PDF', 'MOBI', 'AZW3', 'JSON']);

  protected readonly setup = signal<MockSetup>({ ...DEFAULT_MOCK });
  protected readonly mock = signal<MockLibrary | null>(null);
  protected readonly notes = signal<string[]>([]);
  protected readonly request = signal<ImportRequest | null>(null);
  protected readonly ended = signal<string>('');
  /** the mock library's files once the window closed, to see what was renamed or removed */
  protected readonly filesAfter = signal<string[]>([]);

  protected readonly nothingChosen = computed(() => {
    const s = this.setup();
    return !s.duplicates && !s.index && !s.dates;
  });

  protected set<K extends keyof MockSetup>(key: K, value: MockSetup[K]): void {
    this.setup.update((s) => ({ ...s, [key]: value }));
  }

  protected count(value: string): number {
    const n = Math.floor(Number(value));
    return Number.isFinite(n) ? Math.min(Math.max(n, 1), 60) : 1;
  }

  protected open(): void {
    if (this.nothingChosen()) return;
    this.notes.set([]);
    this.request.set(null);
    this.ended.set('');
    this.filesAfter.set([]);
    this.mock.set(mockLibrary(this.setup()));
  }

  protected noted(said: string): void {
    this.notes.update((n) => [...n, said]);
  }

  protected async closed(dated: DatingResult | null): Promise<void> {
    this.ended.set(dated?.renamed.length ? `Closed, having dated ${dated.renamed.length} files.` : 'Closed.');
    await this.finish();
  }

  protected async started(chosen: { request: ImportRequest }): Promise<void> {
    this.request.set(chosen.request);
    this.ended.set('Would have opened the run window with this request - nothing was started.');
    await this.finish();
  }

  private async finish(): Promise<void> {
    const mock = this.mock();
    if (mock) this.filesAfter.set(await mock.store.list('works'));
    this.mock.set(null);
  }
}
