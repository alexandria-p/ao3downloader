import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { CollectionsView } from './collections-view';
import { DownloadDialog } from './download-dialog';
import { JobAction } from './jobs';
import { Library } from './library';
import { WorkList } from './work-list';
import { Bookmark, ownerFromSource } from './bookmarks';

/** the two things this folder holds, and the two pages that show them */
export type View = 'bookmarks' | 'collections';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, DownloadDialog, WorkList, CollectionsView],
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly library = inject(Library);

  protected readonly view = signal<View>('bookmarks');
  /** which download dialog is open, if any */
  protected readonly dialogAction = signal<JobAction | null>(null);

  protected readonly data = this.library.data;
  protected readonly collections = this.library.collections;
  protected readonly error = this.library.error;
  protected readonly loading = this.library.loading;
  protected readonly sourceName = this.library.sourceName;
  protected readonly folderName = this.library.folderName;
  protected readonly needsReconnect = this.library.needsReconnect;
  protected readonly canPickFolder = this.library.canPickFolder;

  constructor() {
    // reopen the folder picked last time, if the browser still lets us read it
    void this.library.restore();
  }

  protected readonly works = computed<Bookmark[]>(() => this.data()?.works ?? []);
  protected readonly owner = computed(() => ownerFromSource(this.data()?.source ?? ''));

  /** shown above the listing: when the index was last brought up to date */
  protected readonly retrieved = computed(() => this.data()?.retrieved ?? '');

  /** a folder with nothing in it at all is what the getting-started panel is for */
  protected readonly isEmpty = computed(
    () => !this.data() && this.collections().length === 0 && !this.loading(),
  );

  protected setView(view: View): void {
    this.view.set(view);
  }

  protected async choose(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    await this.library.load(input.files);
    // let the same folder be picked again after a re-export
    input.value = '';
  }

  protected async pickFolder(): Promise<void> {
    await this.library.pickFolder();
  }

  protected async reconnect(): Promise<void> {
    await this.library.reconnect();
  }

  protected async forget(): Promise<void> {
    await this.library.forget();
  }
}
