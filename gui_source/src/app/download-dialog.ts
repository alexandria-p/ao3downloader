import { Component, OnDestroy, computed, inject, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { JobAction, JobEvent, Jobs, UndatedChoice, WorkFailure } from './jobs';
import { safeGet, safeRemove, safeSet } from './storage';

type Step =
  | 'link'
  | 'filetypes'
  | 'options'
  | 'acknowledge'
  | 'credentials'
  | 'running'
  | 'done'
  | 'failed';

/** any page of a collection will do, so this only asks that a name follows /collections/ */
const COLLECTION_URL = /^https?:\/\/(www\.)?archiveofourown\.org\/collections\/([^/?#]+)/i;

/** any chapter or page of a work will do, so this only asks that digits follow /works/ */
const WORK_URL = /^https?:\/\/(www\.)?archiveofourown\.org\/works\/(\d+)/i;

/**
 * The index's own file type, which is not a copy of a work like the others.
 *
 * Matches `strings.AO3_DOWNLOAD_TYPE_METADATA` on the helper. Named here rather than read
 * out of `config.forced`, because what makes it special is what it *is* - the index - and
 * not that it happens to be on a list of locked types.
 */
const METADATA = 'JSON';

const USERNAME_KEY = 'ao3.username';
const REMEMBER_KEY = 'ao3.remember';
/** set once the combined run's note has been read and turned off */
const SYNC_ACK_KEY = 'ao3.syncAcknowledged';
const MAX_LOG = 200;

@Component({
  selector: 'app-download-dialog',
  imports: [DecimalPipe],
  templateUrl: './download-dialog.html',
  styleUrl: './download-dialog.css',
})
export class DownloadDialog implements OnDestroy {
  private readonly jobs = inject(Jobs);

  readonly action = input.required<JobAction>();
  readonly closed = output<void>();

  protected readonly step = signal<Step>('filetypes');
  protected readonly config = this.jobs.config;
  protected readonly available = this.jobs.available;

  protected readonly selected = signal<string[]>([]);
  protected readonly username = signal('');
  protected readonly password = signal('');
  /** opt-in: only true once the user has asked to be remembered */
  protected readonly remember = signal(false);

  // the questions the console menu asks after the file types
  protected readonly start = signal(1);
  protected readonly pages = signal(0);
  protected readonly series = signal(false);
  protected readonly images = signal(false);
  protected readonly workdates = signal(false);

  /** the collection to index, for the action that works from a link */
  protected readonly collectionUrl = signal('');

  /** ticked once the limitation of this run has been read and accepted */
  protected readonly acknowledged = signal(false);
  /** the combined run's note only: turns it off for next time, once accepted */
  protected readonly dontAskAgain = signal(false);

  /** a custom run may work from the index rather than reading AO3's listing again */
  protected readonly reindex = signal(true);

  protected readonly log = signal<string[]>([]);
  protected readonly percent = signal<number | null>(null);
  protected readonly paused = signal<{ seconds: number; until: string } | null>(null);
  protected readonly summary = signal('');
  protected readonly error = signal('');
  protected readonly folder = signal('');

  /** which stage of the run is in progress */
  protected readonly phase = signal('');

  /** null while the login is being checked, then whether it worked */
  protected readonly loginVerified = signal<boolean | null>(null);
  protected readonly signedInAs = signal('');

  /** what is being fetched right now */
  protected readonly currentTitle = signal('');
  protected readonly currentFiletype = signal('');

  protected readonly cancelling = signal(false);
  protected readonly wasCancelled = signal(false);

  /**
   * Whether the run is paused, and whether a pause has been asked for but not taken effect.
   *
   * These are two different things on purpose. The helper sets a flag and answers straight
   * away; the run itself only stops at its next safe point, which can be a whole file
   * later. Showing 'Paused' the instant the button is pressed would claim the run had
   * stopped while it was still downloading, so the button says 'Pausing...' until the run
   * itself confirms it by sending a `held` event.
   */
  protected readonly held = signal(false);
  protected readonly holdPending = signal(false);

  // these two are for the summary shown once the run has finished. while it is running the
  // log says all of this as it happens, a line at a time, so there is nothing for a
  // standing panel to add. the `refresh` event still carries an undated count and nothing
  // reads it - the log covers that too.
  /** works ao3 has updated since they were saved, which this run is fetching again */
  protected readonly staleCount = signal(0);
  /** existing files this run gave a date to, by renaming them */
  protected readonly stampedCount = signal(0);
  /** works this run could not download */
  protected readonly failures = signal<WorkFailure[]>([]);
  /**
   * Bookmarks that were never works: a series, something hosted elsewhere, one deleted.
   *
   * Kept apart from `failures` because nothing went wrong with these - there was no work
   * there to fetch, and no amount of retrying would change that. Listing them together
   * would make a real failure look routine.
   */
  protected readonly skipped = signal<WorkFailure[]>([]);

  /**
   * How many undated files the run has stopped to ask about, or 0 when it is not asking.
   *
   * The run is genuinely blocked while this is set - it cannot decide what counts as out
   * of date until it knows the answer - so the dialog shows the question in place of the
   * usual progress.
   */
  protected readonly asking = signal(0);
  /** whether the 'give them a date' half of the question is showing */
  protected readonly choosingDate = signal(false);
  protected readonly stampDate = signal(today());
  /** set once an answer has gone back, so it cannot be sent twice */
  protected readonly answering = signal(false);

  private jobId: string | null = null;
  private stop: (() => void) | null = null;
  private unloadGuard: ((event: BeforeUnloadEvent) => void) | null = null;

  protected readonly title = computed(() => {
    switch (this.action()) {
      case 'bookmarks':
        return '(Full scan) Reindex & Update All';
      case 'collections':
        return 'Index my collections';
      case 'collection':
        return 'Index collection by URL';
      case 'new':
        return 'Just download newly added bookmarks';
      case 'sync':
        return 'Download new bookmarks and update incomplete fics';
      case 'work':
        return 'Download/update a specific fic';
      case 'custom':
        return 'Custom run';
      default:
        return 'Update incomplete fics';
    }
  });

  protected readonly blurb = computed(() => {
    switch (this.action()) {
      case 'bookmarks':
        return 'Walks every page of your AO3 bookmarks, reindexes all of them, and downloads anything missing or out of date. Thorough, and slow.';
      case 'collections':
        return 'Saves a json file describing each of your collections, including the work IDs it contains. The works themselves are not downloaded - they come from your index.';
      case 'collection':
        return 'Indexes any one collection on AO3, whether or not it is yours. Saved alongside your own collections, in the same shape.';
      case 'new':
        return 'Indexes your newest bookmarks and stops at the first one you already have, then downloads what it found. Usually a request or two.';
      case 'sync':
        return 'Three passes: your new bookmarks, then the fics your index last saw unfinished, then any finished fic missing a format you asked for.';
      case 'work':
        return 'Indexes one fic and downloads it, in whichever formats you pick. Use it for a single work you want now, or to repair one copy.';
      case 'custom':
        return 'A full scan with its parts made optional - choose the pages to cover, or skip reading AO3 entirely and work from what is already indexed.';
      default:
        return 'Reads your index for fics it last saw unfinished, checks each one on AO3, brings its index entry up to date, and re-downloads any that have grown.';
    }
  });

  /** JSON is metadata rather than a work, so the update run cannot produce it */
  protected readonly metadataNotApplicable = computed(() => this.action() === 'update');

  /**
   * Which page of the listing to begin and end on. Only a custom run asks.
   *
   * A full scan covers everything by definition - that is what makes it a full scan, and
   * offering to cut it short there only makes it a custom run under another name.
   */
  protected readonly picksPages = computed(() => this.action() === 'custom');

  /**
   * Series expansion: the full scan only.
   *
   * A series is discovered on a work's own page, and following one means downloading works
   * that were never in the listing. Only a full scan goes the long way round (see
   * `server.can_use_index`); every other run downloads a known set straight from the work
   * numbers, and there is nothing in that path to expand a series into.
   */
  protected readonly picksSeries = computed(() => this.action() === 'bookmarks');

  /**
   * Embedded images: the custom run only.
   *
   * Image links are `<img>` tags in the work's rendered html, so they need the work page.
   * The custom run fetches it separately, after the files themselves have come down the
   * cheap way - which costs an extra request per work and is why it is opt-in, on the one
   * run that exists for asking about things like this.
   */
  protected readonly picksImages = computed(() => this.action() === 'custom');

  /** only a custom run may work from the index instead of reading the listing */
  protected readonly picksReindex = computed(() => this.action() === 'custom');

  /**
   * Indexing collections writes metadata only, so there is nothing to pick: no file types
   * and no download options. The two link actions ask for their link first; indexing your
   * own collections goes straight to the login.
   */
  protected readonly picksFiletypes = computed(
    () => this.action() !== 'collections' && this.action() !== 'collection',
  );
  protected readonly needsLink = computed(
    () => this.action() === 'collection' || this.action() === 'work',
  );
  /** the link step asks for a fic rather than a collection */
  protected readonly wantsWork = computed(() => this.action() === 'work');

  /**
   * Which runs say what they cannot do before anyone logs in for them.
   *
   * All three have a real limitation and none of them is obvious from the button: an update
   * pass never sees a fic that had finished, a full scan takes hours, and a combined run
   * trusts the index it already has. Better read before a long run than worked out after.
   */
  protected readonly needsAcknowledgement = computed(() => {
    const action = this.action();
    if (action === 'update' || action === 'bookmarks') return true;
    // this one can be turned off - it is the run people are meant to use routinely, and a
    // note that cannot be silenced is one they learn to click past
    return action === 'sync' && !safeGet(SYNC_ACK_KEY);
  });

  /**
   * Whether this run has anything to ask on the options step.
   *
   * A step with nothing on it is worse than no step: it reads as something that failed to
   * load. When there is nothing to choose the run goes straight past it, in both
   * directions, rather than showing a page that says so.
   */
  protected readonly hasOptions = computed(
    () => this.picksPages() || this.picksSeries() || this.picksImages() || this.picksReindex(),
  );

  /**
   * The options come before the file types, for every run.
   *
   * They have to for a custom run, where one of the options decides a file type - skipping
   * the indexing means no json, since json *is* the index - and asking which types you
   * want and then changing one behind you reads as the dialog overruling you. The rest
   * follow the same order because two orders is one more than anybody needs to learn.
   */
  protected readonly firstStep = computed<Step>(() => {
    if (this.needsLink()) return 'link';
    if (this.hasOptions()) return 'options';
    return this.picksFiletypes() ? 'filetypes' : 'credentials';
  });

  /** whether what has been typed is something this run can act on */
  protected readonly linkIsValid = computed(() => {
    const typed = this.collectionUrl().trim();
    if (!this.wantsWork()) return COLLECTION_URL.test(typed);
    // a bare work number says the same thing as the whole url, and is what you get from
    // the address bar most easily
    return /^\d+$/.test(typed) || WORK_URL.test(typed);
  });

  /** what the current stage is doing, in words */
  protected readonly phaseLabel = computed(() => {
    switch (this.phase()) {
      case 'authenticating':
        return 'Verifying your AO3 login';
      case 'indexing':
        return 'Indexing - saving a json file for every bookmark';
      case 'scanning':
        return 'Reading your index for fics it last saw unfinished';
      case 'checking_files':
        return 'Checking which of these you have already downloaded';
      case 'checking_versions':
        return 'Checking which of your downloads AO3 has a newer version of';
      case 'updating':
        // an update run does one fic at a time: re-read it, then fetch it if the copy is
        // behind. so there is no separate 'downloading' stage to move on to
        return 'Re-reading each unfinished fic and replacing the copies that are behind';
      case 'downloading':
        return 'Downloading works';
      case 'collections':
        return 'Reading collections';
      default:
        return '';
    }
  });

  /** what the run was asked to do, shown back while it works */
  protected readonly chosenOptions = computed(() => {
    const chosen: string[] = [];
    // only what this run was actually offered: showing back a setting it cannot act on
    // would read as a promise it is not going to keep
    if (this.picksPages()) chosen.push(this.pageRange());
    if (this.workdates()) chosen.push('look up publication dates');
    if (this.picksSeries() && this.series()) chosen.push('expand series links');
    if (this.picksImages() && this.images()) chosen.push('save images separately');
    if (this.picksReindex() && !this.reindex()) chosen.push('no reindexing');
    return chosen;
  });

  /** the slice of the listing this run covers, in words */
  protected readonly pageRange = computed(() => {
    const start = this.start();
    const stop = this.pages();
    if (start <= 1) return stop === 0 ? 'all pages' : `pages 1 to ${stop}`;
    return stop === 0 ? `page ${start} onwards` : `pages ${start} to ${stop}`;
  });

  /** what settings.ini says this run will work from */
  protected readonly settings = computed(() => this.config()?.settings ?? null);

  constructor() {
    void this.init();
  }

  private async init(): Promise<void> {
    const config = await this.jobs.loadConfig();
    if (!config) return;

    this.folder.set(config.downloadFolder);
    // the defaults are a starting point, not a rule: only `forced` cannot be unticked
    this.selected.set([...(config.defaults ?? config.forced)]);
    this.step.set(this.firstStep());

    const remembered = safeGet(REMEMBER_KEY) === 'true';
    this.remember.set(remembered);
    // the saved username can come from the browser or from ao3downloader's own data.json
    this.username.set((remembered ? safeGet(USERNAME_KEY) : '') || config.username || '');
  }

  ngOnDestroy(): void {
    this.stop?.();
    this.releaseUnloadGuard();
  }

  // region filetypes

  protected isForced(filetype: string): boolean {
    return (this.config()?.forced ?? []).includes(filetype);
  }

  /**
   * Whether this type is decided for you rather than chosen.
   *
   * On a custom run json is settled by the indexing switch in both directions - on when it
   * indexes, off when it does not - so it is locked either way rather than only when on.
   */
  protected isLocked(filetype: string): boolean {
    if (this.picksReindex() && filetype === METADATA) return true;
    return this.isForced(filetype);
  }

  protected isSelected(filetype: string): boolean {
    if (this.picksReindex() && filetype === METADATA) return this.reindex();
    return this.selected().includes(filetype);
  }

  /** why this type is locked, in a word, or '' when it is not */
  protected lockedBecause(filetype: string): string {
    if (!this.isLocked(filetype)) return '';
    if (this.picksReindex() && filetype === METADATA) {
      return this.reindex() ? 'with indexing' : 'not indexing';
    }
    return 'always on';
  }

  protected toggle(filetype: string): void {
    if (this.isLocked(filetype)) return;
    const current = this.selected();
    this.selected.set(
      current.includes(filetype) ? current.filter((x) => x !== filetype) : [...current, filetype],
    );
  }

  /**
   * The file types the run is actually asked for.
   *
   * `selected` holds what was ticked; on a custom run json is not ticked at all but
   * follows the indexing switch, so the two have to be reconciled before anything is sent
   * rather than the helper being left to guess which of them meant it.
   */
  protected readonly chosenFiletypes = computed(() => {
    if (!this.picksReindex()) return this.selected();
    const rest = this.selected().filter((x) => x !== METADATA);
    return this.reindex() ? [METADATA, ...rest] : rest;
  });

  protected afterFiletypes(): void {
    this.toCredentials();
  }

  protected afterOptions(): void {
    this.step.set(this.picksFiletypes() ? 'filetypes' : 'credentials');
  }

  /**
   * The step before this one, or null when this one is the first.
   *
   * Worked out rather than written down, because which steps a run has varies: a run with
   * nothing to choose has no options step at all, and only two ask for a link.
   */
  private stepBefore(step: Step): Step | null {
    const earlier: Step[] = [];
    if (this.needsLink()) earlier.push('link');
    if (this.hasOptions()) earlier.push('options');
    if (this.picksFiletypes()) earlier.push('filetypes');
    if (this.needsAcknowledgement()) earlier.push('acknowledge');
    earlier.push('credentials');

    const at = earlier.indexOf(step);
    return at > 0 ? earlier[at - 1] : null;
  }

  protected backFrom(step: Step): void {
    const previous = this.stepBefore(step);
    if (previous) {
      this.step.set(previous);
      return;
    }
    this.close();
  }

  /** whether stepping back from here goes anywhere other than out of the dialog */
  protected hasStepBefore(step: Step): boolean {
    return this.stepBefore(step) !== null;
  }

  protected toCredentials(): void {
    // an update pass has a limitation worth reading before anyone logs in for it
    this.step.set(this.needsAcknowledgement() ? 'acknowledge' : 'credentials');
  }

  /** from the acknowledgement: only on once it has actually been accepted */
  protected fromAcknowledgement(): void {
    if (!this.acknowledged()) return;
    // written only when they go through with it, so backing out never silences the note
    if (this.action() === 'sync' && this.dontAskAgain()) safeSet(SYNC_ACK_KEY, 'true');
    this.step.set('credentials');
  }

  protected setPages(value: string): void {
    const parsed = Number.parseInt(value, 10);
    this.pages.set(Number.isFinite(parsed) && parsed > 0 ? parsed : 0);
  }

  protected setStart(value: string): void {
    const parsed = Number.parseInt(value, 10);
    this.start.set(Number.isFinite(parsed) && parsed > 1 ? parsed : 1);
  }

  protected setCollectionUrl(value: string): void {
    this.collectionUrl.set(value);
  }

  /** from the link step: only worth going on once the link is one we can use */
  protected fromLink(): void {
    if (!this.linkIsValid()) return;
    if (this.hasOptions()) {
      this.step.set('options');
      return;
    }
    this.step.set(this.picksFiletypes() ? 'filetypes' : 'credentials');
  }

  // endregion

  // region credentials

  protected setUsername(value: string): void {
    this.username.set(value);
  }

  protected setPassword(value: string): void {
    this.password.set(value);
  }

  protected toggleRemember(value: boolean): void {
    this.remember.set(value);
  }

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    if (!this.username().trim() || !this.password()) return;

    // only the username is ours to keep. the password is left to the browser's own
    // password manager, which stores it in the OS keychain rather than in page storage.
    if (this.remember()) {
      safeSet(REMEMBER_KEY, 'true');
      safeSet(USERNAME_KEY, this.username().trim());
    } else {
      safeRemove(REMEMBER_KEY);
      safeRemove(USERNAME_KEY);
    }

    await this.run();
  }

  // endregion

  // region running

  private async run(): Promise<void> {
    this.step.set('running');
    this.log.set([]);
    this.percent.set(null);
    this.error.set('');
    this.currentTitle.set('');
    this.currentFiletype.set('');
    this.phase.set('');
    this.loginVerified.set(null);
    this.signedInAs.set('');
    this.cancelling.set(false);
    this.wasCancelled.set(false);
    this.staleCount.set(0);
    this.stampedCount.set(0);
    this.choosingDate.set(false);
    this.asking.set(0);
    this.answering.set(false);
    this.failures.set([]);
    this.skipped.set([]);

    let jobId: string;
    try {
      jobId = await this.jobs.start({
        action: this.action(),
        filetypes: this.chosenFiletypes(),
        options: {
          start: this.start(),
          pages: this.pages(),
          series: this.series(),
          images: this.images(),
          workdates: this.workdates(),
          // only a custom run can turn this off; everything else always indexes
          reindex: this.picksReindex() ? this.reindex() : true,
        },
        username: this.username().trim(),
        password: this.password(),
        url: this.needsLink() ? this.collectionUrl().trim() : undefined,
      });
    } catch (e) {
      this.error.set(e instanceof Error ? e.message : String(e));
      this.step.set('failed');
      return;
    } finally {
      // the password has been handed over; don't keep it in component state
      this.password.set('');
    }

    this.jobId = jobId;
    this.holdUnloadGuard();
    this.stop = this.jobs.stream(
      jobId,
      (event) => this.onEvent(event),
      () => this.onStreamEnd(),
    );
  }

  private onEvent(event: JobEvent): void {
    switch (event.type) {
      case 'started':
        if (event.folder) this.folder.set(event.folder);
        this.append('starting');
        break;
      case 'phase':
        this.phase.set(event.name ?? '');
        // the login is being checked; nothing is known about it yet
        if (event.name === 'authenticating') this.loginVerified.set(null);
        // each stage has its own scale, so the bar restarts rather than jumping back
        this.percent.set(null);
        this.summary.set('');
        this.currentTitle.set('');
        this.currentFiletype.set('');
        break;
      case 'page': {
        // the bar measures the slice being fetched, so it runs 1..n and ends full
        if (event.total) this.percent.set(Math.round(((event.page ?? 0) / event.total) * 100));
        // the words say where that is in the listing itself - the page you would go and look at
        const where = event.listingPage ?? event.page;
        const outOf = event.listingTotal ?? event.total;
        this.summary.set(
          `page ${where ?? '?'} of ${outOf ?? '?'}` +
            (event.works !== undefined ? ` - ${event.works} works so far` : ''),
        );
        break;
      }
      case 'work':
        if (event.total) this.percent.set(Math.round(((event.done ?? 0) / event.total) * 100));
        if (event.title) {
          this.currentTitle.set(event.title);
          // a work event without a filetype means the work page itself, not a format
          this.currentFiletype.set(event.filetype ?? '');
        }
        if (event.done !== undefined && event.total) {
          this.summary.set(
            event.phase === 'scanning'
              ? `checking file ${event.done} of ${event.total}`
              : `work ${event.done} of ${event.total}`,
          );
        }
        break;
      case 'paused':
        this.paused.set({ seconds: event.seconds ?? 0, until: event.until ?? '' });
        break;
      case 'resumed':
        this.paused.set(null);
        break;
      // the run itself confirming it has reached a safe point and stopped there. this is
      // what turns 'Pausing...' into 'Paused' - not the button press, which only asked
      case 'held':
        this.held.set(true);
        this.holdPending.set(false);
        break;
      case 'released':
        this.held.set(false);
        this.holdPending.set(false);
        break;
      case 'authenticated':
        this.loginVerified.set(true);
        this.signedInAs.set(event.username ?? '');
        break;
      case 'refresh':
        this.staleCount.set(event.stale ?? 0);
        this.stampedCount.set(event.stamped ?? 0);
        break;
      case 'failures':
        this.failures.set(event.failures ?? []);
        break;
      case 'skipped':
        this.skipped.set(event.skipped ?? []);
        break;
      case 'question':
        // the run is blocked until this is answered, so it takes over from the progress
        this.asking.set(event.count ?? 0);
        this.choosingDate.set(false);
        this.answering.set(false);
        break;
      case 'message':
        if (event.text) this.append(event.text);
        break;
      case 'finished':
        this.wasCancelled.set(!!event.cancelled);
        if (!event.cancelled) this.percent.set(100);
        this.summary.set('');
        this.currentTitle.set('');
        this.currentFiletype.set('');
        this.step.set('done');
        this.finishUp();
        break;
      case 'failed':
        // a failure while the login was still being checked is a login failure, and
        // saying so is more use than a bare error message
        if (this.loginVerified() === null && this.phase() === 'authenticating') {
          this.loginVerified.set(false);
        }
        this.error.set(event.error ?? 'the download failed');
        this.step.set('failed');
        this.finishUp();
        break;
    }
  }

  private onStreamEnd(): void {
    // the stream also drops when the helper stops; only treat that as a failure
    // if the job never reported an outcome
    if (this.step() === 'running') {
      this.error.set('Lost contact with the local helper. Check the window it is running in.');
      this.step.set('failed');
      this.finishUp();
    }
  }

  /** Ask the helper to stop. It keeps everything already written. */
  protected async requestStop(): Promise<void> {
    if (!this.jobId || this.cancelling()) return;
    this.cancelling.set(true);
    this.append('stopping at your request...');
    await this.jobs.cancel(this.jobId);
  }

  /**
   * Pause the run, or let it go again.
   *
   * Stopping is deliberately not blocked while paused, so this never has to be undone
   * first. If the helper refuses, the page says so rather than showing a pause that is
   * not really in force.
   */
  protected async togglePause(): Promise<void> {
    if (!this.jobId || this.holdPending() || this.cancelling()) return;

    const wanted = !this.held();
    this.holdPending.set(true);
    try {
      await this.jobs.setPaused(this.jobId, wanted);
      this.append(wanted ? 'pausing after the work in progress...' : 'resuming...');
    } catch (error) {
      this.holdPending.set(false);
      // the helper's own words - it can tell a missing job from a helper too old to know
      // what a pause is, and which one it was is the whole of what to do about it
      this.append(
        error instanceof Error ? error.message : `could not ${wanted ? 'pause' : 'resume'} the run`,
      );
    }
  }

  private finishUp(): void {
    this.paused.set(null);
    // a finished run is not a paused one, whatever it was when it reached the end
    this.held.set(false);
    this.holdPending.set(false);
    this.cancelling.set(false);
    this.jobId = null;
    this.stop?.();
    this.stop = null;
    this.releaseUnloadGuard();
  }

  private append(text: string): void {
    const lines = [...this.log(), text];
    this.log.set(lines.length > MAX_LOG ? lines.slice(-MAX_LOG) : lines);
  }

  /** stop a reload or a tab close from silently killing a run in progress */
  private holdUnloadGuard(): void {
    this.unloadGuard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', this.unloadGuard);
  }

  private releaseUnloadGuard(): void {
    if (!this.unloadGuard) return;
    window.removeEventListener('beforeunload', this.unloadGuard);
    this.unloadGuard = null;
  }

  // endregion

  /**
   * Answer the question the run has stopped on, and let it carry on.
   *
   * The run is waiting on this, so the answer goes straight back rather than being kept
   * for a second run: everything after this point - which works count as out of date, and
   * therefore what gets downloaded - depends on it.
   */
  private async answerUndated(choice: UndatedChoice, date = ''): Promise<void> {
    if (!this.jobId || this.answering()) return;
    this.answering.set(true);
    try {
      await this.jobs.answer(this.jobId, choice, date);
      this.asking.set(0);
    } catch (e) {
      // the run is still blocked, so this has to be said rather than swallowed
      this.answering.set(false);
      this.append(e instanceof Error ? e.message : String(e));
    }
  }

  /** fetch them all again, replacing whatever is there */
  protected refreshUndatedWorks(): void {
    void this.answerUndated('refresh');
  }

  /** leave them exactly as they are */
  protected skipUndatedWorks(): void {
    void this.answerUndated('skip');
  }

  protected setStampDate(value: string): void {
    this.stampDate.set(value);
  }

  /** whether what has been typed is a date this can actually be run with */
  protected readonly stampDateIsValid = computed(() => isDate(this.stampDate()));

  /**
   * Write the chosen date onto them instead of fetching them again.
   *
   * Nothing is downloaded to do this - the files are renamed where they sit - and the run
   * carries straight on, so anything ao3 has updated since that date is fetched on this
   * same pass rather than a later one.
   */
  protected dateUndatedWorks(): void {
    if (!this.stampDateIsValid()) return;
    void this.answerUndated('stamp', this.stampDate());
  }

  /** the failed works as the text that gets saved - kept apart from the saving itself */
  protected failureReport(): string {
    return this.listReport(
      this.failures(),
      `${this.failures().length} work${this.failures().length === 1 ? '' : 's'} that could not be downloaded`,
    );
  }

  protected skippedReport(): string {
    return this.listReport(
      this.skipped(),
      `${this.skipped().length} bookmark${this.skipped().length === 1 ? '' : 's'} that are not works`,
    );
  }

  /** one row per entry, tab separated, so it can be read or fed back in as it is */
  private listReport(rows: WorkFailure[], heading: string): string {
    return (
      [
        `# ${heading}`,
        `# ${new Date().toISOString()}`,
        '# work id, link, reason - tab separated',
        ...rows.map((row) =>
          [row.id ?? '', row.link ?? '', (row.error ?? '').replace(/\s+/g, ' ')].join('\t'),
        ),
      ].join('\n') + '\n'
    );
  }

  /**
   * Hand the list of failed works over as a text file.
   *
   * Done in the page rather than by the helper: it is a few lines the browser can save
   * directly, so it does not need a round trip or a second thing that writes to disk.
   */
  protected exportFailures(): void {
    this.saveText(this.failureReport(), 'failed-downloads', this.failures().length);
  }

  protected exportSkipped(): void {
    this.saveText(this.skippedReport(), 'skipped-bookmarks', this.skipped().length);
  }

  private saveText(text: string, name: string, rows: number): void {
    if (!rows) return;

    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${name}-${new Date().toISOString().slice(0, 10)}.txt`;
    link.click();
    // the save has its own copy once started, so the handle can go
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  protected close(): void {
    if (this.step() === 'running') return; // the guard message explains why
    this.closed.emit();
  }
}

/**
 * Today in UTC, as YYYY-MM-DD - the default answer to "which version are these?".
 *
 * UTC rather than local time so the default does not depend on which side of midnight the
 * machine's timezone happens to be, and so it matches the stamps written elsewhere. Being
 * a day out either way only moves the staleness boundary by a day, which is harmless.
 */
function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** a real calendar date written as YYYY-MM-DD, not merely something shaped like one */
function isDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value ?? '')) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
