import { inAo3Zone } from './preferences';
import {
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
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
import { Feedback } from './feedback';
import { History } from './history';
import { FolderWarning, folderWarningDismissed } from './folder-warning';
import { ActiveRun, JobAction, Jobs, RunHistory } from './jobs';
import { HelperConnection } from './helper-connection';
import { Library, describeReadProgress } from './library';
import { LibraryFreshness } from './freshness';
import { LibrarySetup } from './library-setup';
import { PasscodeGate } from './passcode-gate';
import { SetupOverlay } from './setup-overlay';
import { WorkList } from './work-list';
import { Bookmark, ownerFromSource } from './bookmarks';
import { APP_FOLDER_PATH, DropboxSession } from './dropbox';
import { StorageChoice, StorageMode } from './storage-choice';
import { UpdateCheck } from './updates';
import { UserSettings } from './user-settings';

/** how often the page asks whether a run in progress has finished, while one is */
const ACTIVE_RUN_POLL_MS = 30_000;

/** the two things this folder holds, the pages that show them, and the two reading pages */
export type View = 'bookmarks' | 'collections' | 'history' | 'faq' | 'bug' | 'settings';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, BrowserNotice, DownloadDialog, Faq, FolderWarning, History, WorkList,
    CollectionsView, Feedback, PasscodeGate, SetupOverlay, UserSettings],
  styleUrl: './app.css',
  templateUrl: './app.html',
  // a tab coming back into view is when a run elsewhere is most likely to have finished
  host: { '(document:visibilitychange)': 'lookAgain()' },
})
export class App {
  private readonly library = inject(Library);
  protected readonly freshness = inject(LibraryFreshness);
  protected readonly refreshing = this.library.refreshing;
  private readonly jobs = inject(Jobs);
  private readonly storage = inject(StorageChoice);
  private readonly dropbox = inject(DropboxSession);
  private readonly helper = inject(HelperConnection);
  private readonly updates = inject(UpdateCheck);

  /** a newer release than this page's own, once GitHub has said so - the footer says it always */
  protected readonly newerRelease = this.updates.newer;
  /** ...and the banner until it is dismissed */
  protected readonly bannerRelease = computed(() => (this.updates.dismissed() ? null : this.updates.newer()));
  /** only once GitHub has answered: not knowing is not the same as being the latest */
  protected readonly upToDate = computed(() => this.updates.checked() && !this.updates.newer());
  protected readonly latestReleaseUrl = computed(() => {
    this.helper.settings();
    return this.updates.latestUrl();
  });
  protected readonly currentVersion = computed(() => this.helper.settings().version);
  protected readonly repositoryName = computed(() => this.helper.settings().releasesRepo);
  protected readonly repositoryUrl = computed(() => `https://github.com/${this.repositoryName()}`);
  protected readonly issuesUrl = computed(() => `${this.repositoryUrl()}/issues`);
  /** whether the feedback tab is there to point at - only on a copy built with its Worker */
  protected readonly feedbackOffered = computed(() => !!this.helper.settings().feedbackUrl);
  /** the Report a bug page's button opens the same window the Feedback tab does */
  protected openFeedback(): void {
    this.feedback()?.show();
  }
  /** only the Windows, Mac or Linux app can install an update itself; anywhere else the banner links it */
  protected readonly canUpdate = this.updates.canUpdate;
  protected readonly updateProgress = this.updates.updating;
  protected readonly updateTarget = computed(() => {
    const progress = this.updateProgress();
    return progress.state === 'updating' ? progress.version : '';
  });
  protected readonly updateError = computed(() => {
    const progress = this.updateProgress();
    return progress.state === 'failed' ? progress.error : '';
  });

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
  /** a background run the window opens onto, from the history's View progress */
  protected readonly attachTo = signal<ActiveRun | null>(null);

  /**
   * The run the helper is working on, if any.
   *
   * The helper runs one at a time, so while there is one nothing else can start: the page
   * says so at the top and the run buttons wait, rather than letting someone fill in a
   * whole run window only to be refused at the end of it.
   */
  protected readonly activeRun = computed(() => this.jobs.activeRuns()[0] ?? null);
  /**
   * What is still being done before a run window opens, all of it at once: the run history
   * checked for interrupted runs, the helper woken and asked for its config, and - for a quick
   * scan - the newest scan it would measure back to. The notice names the first still going
   */
  protected readonly preparing = signal<readonly Preparation[]>([]);
  protected readonly checkingRuns = computed(() => this.preparing().length > 0);
  /** the newest scan a quick scan would measure back to, found before its window opened */
  protected readonly newestFloor = signal<RunHistory | null | undefined>(undefined);
  protected readonly preparingNote = computed(() => {
    const left = this.preparing();
    return PREPARATIONS.find((step) => left.includes(step.id))?.note ?? '';
  });

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
  private readonly feedback = viewChild(Feedback);
  private readonly destroyRef = inject(DestroyRef);
  private readonly folderInput = viewChild<ElementRef<HTMLInputElement>>('folderInput');
  /** the version bar, measured so what is pinned to the bottom sits just above it */
  private readonly footer = viewChild<ElementRef<HTMLElement>>('appFooter');

  /**
   * Open a run's window, once any run the history still calls 'running' has been checked
   * against the helper. A run left 'running' by a page that closed or a helper that stopped
   * is marked interrupted first, so what the window offers - resuming it - is up to date.
   */
  protected async openRun(action: JobAction): Promise<void> {
    if (this.checkingRuns() || this.activeRun()) return;
    const store = this.library.store();
    const quick = action === 'quick';
    this.newestFloor.set(undefined);
    this.preparing.set(quick ? ['history', 'helper', 'floor'] : ['history', 'helper']);
    const finished = (id: Preparation) => () =>
      this.preparing.update((left) => left.filter((step) => step !== id));

    // all at once. the helper's config is the run window's first request, and a hosted
    // helper asleep since its last run (Render's free tier) takes most of a minute to wake -
    // so that starts now rather than after the history. a quick scan also finds the newest
    // scan it would measure back to - a handful of records, newest first - so 'since my last
    // run' needs nothing more once its window is open. the whole list waits for 'choose which
    // earlier scan', in the window
    const settle = this.jobs.settleInterrupted(store).finally(finished('history'));
    const config = this.jobs.loadConfig().finally(finished('helper'));
    const floor = quick
      ? this.jobs.loadNewestFloor(store).finally(finished('floor'))
      : Promise.resolve(undefined);
    try {
      const [, , newest] = await Promise.all([settle, config, floor]);
      this.newestFloor.set(newest);
    } finally {
      this.preparing.set([]);
    }
    this.dialogAction.set(action);
  }

  /** a time of day, for when a paused background run will be abandoned */
  protected timeOf(stamp: string): string {
    const parsed = new Date(stamp);
    return Number.isNaN(parsed.getTime())
      ? ''
      : parsed.toLocaleTimeString([], inAo3Zone({ hour: '2-digit', minute: '2-digit' }));
  }

  /** from the banner: the history, where the run in progress is pinned to the top */
  protected goToRun(): void {
    this.view.set('history');
  }

  /** from the history: open the progress window onto a background run already going */
  protected viewProgress(run: ActiveRun): void {
    this.attachTo.set(run);
    this.dialogAction.set(run.action);
  }

  /** the run window closed - whatever it was, what is running may have changed */
  protected dialogClosed(): void {
    this.dialogAction.set(null);
    this.resumeFrom.set('');
    this.attachTo.set(null);
    void this.jobs.refreshActiveRuns();
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
  /** the bar while a Dropbox library is read: what stage, and how far when that is known */
  protected readonly reading = computed(() => {
    const progress = this.library.readProgress();
    return progress ? describeReadProgress(progress) : null;
  });
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
    // the selection bar is pinned above the version bar, which wraps onto more lines on a
    // narrow window - so its height is measured rather than guessed (--app-footer-height)
    afterNextRender(() => {
      const footer = this.footer()?.nativeElement;
      if (!footer || typeof ResizeObserver === 'undefined') return;
      const note = () =>
        document.documentElement.style.setProperty('--app-footer-height', `${footer.offsetHeight}px`);
      const watching = new ResizeObserver(note);
      watching.observe(footer);
      note();
      this.destroyRef.onDestroy(() => watching.disconnect());
    });
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
    // a run left going in the background, from this page or another, is said at once
    void this.jobs.refreshActiveRuns();
    // once per opening, and never for a page that has no version or was told not to
    void this.updates.check();
    // whether the helper is the Windows, Mac or Linux app, which can update itself - and whether its last
    // update went through. untracked, or clearing a failure would bring it straight back
    effect(() => {
      const app = this.jobs.config()?.app;
      untracked(() => this.updates.appStatus(app));
    });
    // and asked about again while one is going, so the banner goes when it finishes. only
    // then: with nothing running there is nothing to watch for, and a hosted helper is left
    // to sleep
    // a run that finished since the library was read, with changes this page did not take
    // in: the list brings itself up to date - only while it is in view, and never while a run
    // is going, which may be writing to the library still
    effect(() => {
      const view = this.view();
      if (!this.freshness.behind() || this.activeRun() || this.library.refreshing()) return;
      if (view !== 'bookmarks' && view !== 'collections') return;
      untracked(() => {
        if (this.freshness.claimRefresh()) void this.library.refresh();
      });
    });
    // a run the helper stops listing has ended - whatever it changed may not be on screen
    let going = new Set<string>();
    effect(() => {
      const now = new Set(this.jobs.activeRuns().map((run) => run.id));
      const ended = [...going].some((id) => !now.has(id));
      going = now;
      if (ended) untracked(() => void this.freshness.check());
    });
    this.watch = setInterval(() => {
      if (this.activeRun()) void this.jobs.refreshActiveRuns();
    }, ACTIVE_RUN_POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(this.watch));
  }

  private watch: ReturnType<typeof setInterval> | undefined;

  /** stop saying there is a newer release, in this browser, for good */
  protected dismissUpdates(): void {
    this.updates.dismiss();
  }

  /** the Windows, Mac or Linux app: download the newer release, restart as it, and reload this page */
  protected updateNow(): void {
    void this.updates.updateNow();
  }

  protected clearUpdateError(): void {
    this.updates.acknowledgeFailure();
  }

  protected readonly works = computed<Bookmark[]>(() => this.data()?.works ?? []);
  protected readonly owner = computed(() => ownerFromSource(this.data()?.source ?? ''));

  /**
   * Above the listing: when this list was last brought up to date from the library - a read,
   * a refresh, or a run's changes taken in
   */
  protected readonly listingNote = computed(() => {
    const listed = this.library.listedAt();
    return listed ? `List refreshed ${shownTime(listed)}.` : '';
  });

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
    if (view === 'bookmarks' || view === 'collections') void this.freshness.check(true);
  }

  /** a works list in view is when it is worth knowing it is behind */
  protected lookAgain(): void {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    const view = this.view();
    if (view === 'bookmarks' || view === 'collections') void this.freshness.check(true);
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
    if (this.libraryLocked()) return;
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

  /**
   * A run reads and writes through the library open now, so while one is going the library
   * cannot be changed - not switched between this computer and Dropbox, not signed out of,
   * not pointed at another folder. Checked here as well as on the buttons.
   */
  protected readonly libraryLocked = computed(() => !!this.activeRun());
  protected readonly lockedTitle = 'Cannot be changed while an active run is in progress';
  protected readonly store = this.library.store;

  protected setMode(mode: StorageMode): void {
    if (this.libraryLocked()) return;
    this.storage.set(mode);
  }

  protected signInToDropbox(): void {
    if (this.libraryLocked()) return;
    void this.dropbox.signIn();
  }

  protected async signOutOfDropbox(): Promise<void> {
    if (this.libraryLocked()) return;
    await this.dropbox.signOut();
  }

  /** read the library again now, as the list does by itself after a run finished elsewhere */
  protected refreshLibrary(): void {
    if (this.libraryLocked() || this.refreshing()) return;
    void this.library.refresh();
  }

  protected async reconnect(): Promise<void> {
    await this.library.reconnect();
  }

  protected async forget(): Promise<void> {
    if (this.libraryLocked()) return;
    await this.library.forget();
  }
}

/**
 * A time as the listing shows it: the reader's own time zone, date and time to the minute. A
 * value that will not parse (an old file's free-text retrieval time) is shown as it was written.
 */
/** what openRun does before a window opens, in the order its notice names them */
type Preparation = 'history' | 'helper' | 'floor';
const PREPARATIONS: { id: Preparation; note: string }[] = [
  { id: 'history', note: 'Checking your run history...' },
  { id: 'helper', note: 'Connecting to the helper...' },
  { id: 'floor', note: 'Reading your scan history...' },
];

export function shownTime(value: string | Date): string {
  const at = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(at.getTime())) return String(value);
  return at.toLocaleString([], inAo3Zone({ dateStyle: 'medium', timeStyle: 'short' }));
}
