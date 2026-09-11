import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { CollectionsView } from './collections-view';
import { DownloadDialog } from './download-dialog';
import { FolderWarning, folderWarningDismissed } from './folder-warning';
import { JobAction } from './jobs';
import { Library } from './library';
import { WorkList } from './work-list';
import { Bookmark, ownerFromSource } from './bookmarks';

/** the two things this folder holds, and the two pages that show them */
export type View = 'bookmarks' | 'collections';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, DownloadDialog, FolderWarning, WorkList, CollectionsView],
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly library = inject(Library);

  protected readonly view = signal<View>('bookmarks');
  /** which download dialog is open, if any */
  protected readonly dialogAction = signal<JobAction | null>(null);
  /** whether the naming note is up, waiting to be read before the picker opens */
  protected readonly warning = signal(false);

  /** the fallback picker, for browsers with no directory picker of their own */
  private readonly folderInput = viewChild<ElementRef<HTMLInputElement>>('folderInput');

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

  /**
   * The naming rule, said once before the folder is chosen.
   *
   * Both ways of choosing go through here - the directory picker where the browser has one,
   * and the hidden file input where it does not - because the rule applies to the folder,
   * not to how it was opened. Dismissing the note is remembered, so a return visit goes
   * straight to the picker.
   */
  protected askBeforePicking(): void {
    if (folderWarningDismissed()) {
      this.openPicker();
      return;
    }
    this.warning.set(true);
  }

  protected warningAccepted(): void {
    this.warning.set(false);
    this.openPicker();
  }

  protected warningCancelled(): void {
    this.warning.set(false);
  }

  private openPicker(): void {
    if (this.canPickFolder) {
      void this.library.pickFolder();
      return;
    }
    // no directory picker here, so the folder comes from a file input. clicking it from
    // inside the confirm handler keeps this within the user gesture the browser requires
    this.folderInput()?.nativeElement.click();
  }

  protected async reconnect(): Promise<void> {
    await this.library.reconnect();
  }

  protected async forget(): Promise<void> {
    await this.library.forget();
  }
}
