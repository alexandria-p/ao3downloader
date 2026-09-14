import { Component, ElementRef, computed, inject, signal, viewChild } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { BrowserNotice, browserNoticeSeen } from './browser-notice';
import { CollectionsView } from './collections-view';
import { DownloadDialog } from './download-dialog';
import { Faq } from './faq';
import { History } from './history';
import { FolderWarning, folderWarningDismissed } from './folder-warning';
import { JobAction, Jobs } from './jobs';
import { Library } from './library';
import { WorkList } from './work-list';
import { Bookmark, ownerFromSource } from './bookmarks';

/** the two things this folder holds, the pages that show them, and the two reading pages */
export type View = 'bookmarks' | 'collections' | 'history' | 'faq';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, BrowserNotice, DownloadDialog, Faq, FolderWarning, History,
    WorkList, CollectionsView],
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly library = inject(Library);
  private readonly jobs = inject(Jobs);

  protected readonly view = signal<View>('bookmarks');
  /** which download dialog is open, if any */
  protected readonly dialogAction = signal<JobAction | null>(null);
  /**
   * Whether the one-off browser note is up.
   *
   * Said on the first visit and never again: writing into a folder you chose needs the
   * File System Access API, which only Chromium browsers have. Waiting until it bites
   * would mean saying it after a folder is picked and a run started.
   */
  protected readonly browserNotice = signal(!browserNoticeSeen());

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

  /**
   * Whether a downloads folder has been chosen yet.
   *
   * Every run reads that folder to work out what it already has and writes everything back
   * into it, so starting one before a folder is picked is starting a run with no idea what
   * it is looking at. The buttons stay disabled until then rather than being hidden: a
   * button you can see and cannot press says what is missing, where an absent one does not.
   */
  protected readonly folderChosen = computed(() => !!this.folderName());

  /**
   * Whether settings.ini has turned the debug tools on.
   *
   * Gates the runs that are kept for working on the app rather than for using it.
   * They still work, and they are still the passes the recommended run is built
   * from - but offering them beside it invites picking one of the parts when the
   * whole is what was wanted.
   */
  protected readonly debugTools = computed(
    () => !!this.jobs.config()?.settings?.debugTools,
  );

  constructor() {
    // reopen the folder picked last time, if the browser still lets us read it
    void this.library.restore();
    // the buttons on offer depend on settings.ini, so it is read as the page opens
    // rather than when a dialog first needs it
    void this.jobs.loadConfig();
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
