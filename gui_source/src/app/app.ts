import {
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { BrowserNotice, browserNoticeSeen } from './browser-notice';
import { CollectionsView } from './collections-view';
import { DownloadDialog } from './download-dialog';
import { Faq } from './faq';
import { History } from './history';
import { FolderWarning, folderWarningDismissed } from './folder-warning';
import { JobAction, Jobs } from './jobs';
import { HelperConnection } from './helper-connection';
import { Library } from './library';
import { LibrarySetup } from './library-setup';
import { PasscodeGate } from './passcode-gate';
import { SetupOverlay } from './setup-overlay';
import { WorkList } from './work-list';
import { Bookmark, ownerFromSource } from './bookmarks';
import { APP_FOLDER_PATH, DropboxSession } from './dropbox';
import { StorageChoice, StorageMode } from './storage-choice';

/** the two things this folder holds, the pages that show them, and the two reading pages */
export type View = 'bookmarks' | 'collections' | 'history' | 'faq';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, BrowserNotice, DownloadDialog, Faq, FolderWarning, History, WorkList,
    CollectionsView, PasscodeGate, SetupOverlay],
  styleUrl: './app.css',
  templateUrl: './app.html',
})
export class App {
  private readonly library = inject(Library);
  private readonly jobs = inject(Jobs);
  private readonly storage = inject(StorageChoice);
  private readonly dropbox = inject(DropboxSession);
  private readonly helper = inject(HelperConnection);

  protected readonly view = signal<View>('bookmarks');
  /**
   * Whether the passcode window is up - on a copy set up with one and not yet given it, or
   * whenever the helper turns the saved one down.
   */
  protected readonly passcodeWanted = this.helper.passcodeWanted;
  /** which download dialog is open, if any */
  protected readonly dialogAction = signal<JobAction | null>(null);
  /** the run a custom run opens set to resume, when opened from the history */
  protected readonly resumeFrom = signal('');
  /** set while the run history is checked for interrupted runs, before a window opens */
  protected readonly checkingRuns = signal(false);
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

  /**
   * Open a run's window, once any run the history still calls 'running' has been checked
   * against the helper. A run left 'running' by a page that closed or a helper that stopped
   * is marked interrupted first, so what the window offers - resuming it - is up to date.
   */
  protected async openRun(action: JobAction): Promise<void> {
    if (this.checkingRuns()) return;
    this.checkingRuns.set(true);
    try {
      await this.jobs.settleInterrupted(this.library.store());
    } finally {
      this.checkingRuns.set(false);
    }
    this.dialogAction.set(action);
  }

  /** from the history: a custom run, set to pick up where that run left off */
  protected resumeRun(runId: string): void {
    this.resumeFrom.set(runId);
    void this.openRun('custom');
  }

  protected readonly data = this.library.data;
  protected readonly collections = this.library.collections;
  protected readonly error = this.library.error;
  protected readonly loading = this.library.loading;
  protected readonly sourceName = this.library.sourceName;
  protected readonly folderName = this.library.folderName;
  protected readonly needsReconnect = this.library.needsReconnect;
  protected readonly canPickFolder = this.library.canPickFolder;

  /** a folder on this computer, or one in Dropbox - both stay remembered either way */
  protected readonly mode = this.storage.mode;
  protected readonly dropboxStatus = this.dropbox.status;
  protected readonly dropboxAccount = this.dropbox.account;
  protected readonly dropboxError = this.dropbox.error;
  /** what setting a library up could not do - files it could not move, say */
  protected readonly setupReport = inject(LibrarySetup).report;
  /** where the library is in Dropbox - always the app folder, so there is nothing to pick */
  protected readonly appFolderPath = APP_FOLDER_PATH;

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
   * Whether the run buttons are offered: once there is a library open that the page can
   * write to. A run reads and writes through the page, so a folder that is only
   * remembered - waiting on a reconnect - is not enough, and neither is a Dropbox sign-in
   * whose folder has not finished opening.
   */
  protected readonly canRun = computed(() => !!this.library.store());

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
    // finishes a sign-in if this load is the way back from dropbox.com
    void this.dropbox.restore();
    // show whichever library is chosen, and show it again whenever that changes. signing in
    // to dropbox is what opens its folder, so the session is tracked - but only while
    // dropbox is the choice: signing in while looking at a local folder must not make the
    // page read that folder again
    effect(() => {
      if (this.mode() === 'dropbox') {
        this.dropboxStatus();
        untracked(() => void this.library.showDropbox());
      } else {
        // reopen the folder picked last time, if the browser still lets us read it
        untracked(() => void this.library.showLocal());
      }
    });
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

  /** the helper took the passcode: ask it again for what it refused to say without one */
  protected unlocked(): void {
    void this.jobs.loadConfig();
  }

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

  protected setMode(mode: StorageMode): void {
    this.storage.set(mode);
  }

  protected signInToDropbox(): void {
    void this.dropbox.signIn();
  }

  protected async signOutOfDropbox(): Promise<void> {
    await this.dropbox.signOut();
  }

  protected async reconnect(): Promise<void> {
    await this.library.reconnect();
  }

  protected async forget(): Promise<void> {
    await this.library.forget();
  }
}
