import { Component, OnDestroy, computed, inject, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { JobAction, JobEvent, Jobs, WorkFailure } from './jobs';

type Step = 'link' | 'filetypes' | 'options' | 'credentials' | 'running' | 'done' | 'failed';

/** any page of a collection will do, so this only asks that a name follows /collections/ */
const COLLECTION_URL = /^https?:\/\/(www\.)?archiveofourown\.org\/collections\/([^/?#]+)/i;

const USERNAME_KEY = 'ao3.username';
const REMEMBER_KEY = 'ao3.remember';
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

  /** works ao3 has updated since they were saved, which this run is fetching again */
  protected readonly staleCount = signal(0);
  /** works saved before file names carried a date, which cannot be judged either way */
  protected readonly undatedCount = signal(0);
  /** set when this run was started to refresh those undated works */
  protected readonly refreshUndated = signal(false);
  /** existing files this run gave a date to, by renaming them */
  protected readonly stampedCount = signal(0);
  /** works this run could not download */
  protected readonly failures = signal<WorkFailure[]>([]);
  /** the date to write onto undated files, when that is what was chosen */
  protected readonly stampUndated = signal('');
  /** whether the 'give them a date' half of the offer is showing */
  protected readonly choosingDate = signal(false);
  protected readonly stampDate = signal(today());

  private jobId: string | null = null;
  private stop: (() => void) | null = null;
  private unloadGuard: ((event: BeforeUnloadEvent) => void) | null = null;

  protected readonly title = computed(() => {
    switch (this.action()) {
      case 'bookmarks':
        return 'Download newly added bookmarks';
      case 'collections':
        return 'Index my collections';
      case 'collection':
        return 'Index collection by URL';
      default:
        return 'Update incomplete fics';
    }
  });

  protected readonly blurb = computed(() => {
    switch (this.action()) {
      case 'bookmarks':
        return 'Reads your AO3 bookmarks and downloads anything not already in your downloads folder.';
      case 'collections':
        return 'Saves a json file describing each of your collections, including the work IDs it contains. The works themselves are not downloaded - they come from your index.';
      case 'collection':
        return 'Indexes any one collection on AO3, whether or not it is yours. Saved alongside your own collections, in the same shape.';
      default:
        return 'Scans your downloads folder for works that were incomplete, and re-downloads any that have new chapters.';
    }
  });

  /** JSON is metadata rather than a work, so the update run cannot produce it */
  protected readonly metadataNotApplicable = computed(() => this.action() === 'update');

  /** page limits, series expansion and publication dates only mean something for a listing */
  protected readonly listingOptions = computed(() => this.action() === 'bookmarks');

  /**
   * Indexing collections writes metadata only, so there is nothing to pick: no file types
   * and no download options. Indexing one by link asks for the link first; indexing your
   * own goes straight to the login.
   */
  protected readonly picksFiletypes = computed(
    () => this.action() !== 'collections' && this.action() !== 'collection',
  );
  protected readonly needsLink = computed(() => this.action() === 'collection');
  protected readonly firstStep = computed<Step>(() => {
    if (this.needsLink()) return 'link';
    return this.picksFiletypes() ? 'filetypes' : 'credentials';
  });

  /** whether what has been typed is a link to one collection */
  protected readonly linkIsValid = computed(() =>
    COLLECTION_URL.test(this.collectionUrl().trim()),
  );

  /** what the current stage is doing, in words */
  protected readonly phaseLabel = computed(() => {
    switch (this.phase()) {
      case 'authenticating':
        return 'Verifying your AO3 login';
      case 'indexing':
        return 'Indexing - saving a json file for every bookmark';
      case 'scanning':
        return 'Scanning your downloads folder for incomplete works';
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
    if (this.listingOptions()) {
      chosen.push(this.pageRange());
      if (this.series()) chosen.push('expand series links');
      if (this.workdates()) chosen.push('look up publication dates');
    }
    if (this.images()) chosen.push('embedded images');
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

  protected isSelected(filetype: string): boolean {
    return this.selected().includes(filetype);
  }

  protected toggle(filetype: string): void {
    if (this.isForced(filetype)) return;
    const current = this.selected();
    this.selected.set(
      current.includes(filetype) ? current.filter((x) => x !== filetype) : [...current, filetype],
    );
  }

  protected toOptions(): void {
    this.step.set('options');
  }

  protected toCredentials(): void {
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
    this.step.set('credentials');
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
    this.undatedCount.set(0);
    this.stampedCount.set(0);
    this.choosingDate.set(false);
    this.failures.set([]);

    let jobId: string;
    try {
      jobId = await this.jobs.start({
        action: this.action(),
        filetypes: this.selected(),
        options: {
          start: this.start(),
          pages: this.pages(),
          series: this.series(),
          images: this.images(),
          workdates: this.workdates(),
          refreshUndated: this.refreshUndated(),
          stampUndated: this.stampUndated(),
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
      case 'authenticated':
        this.loginVerified.set(true);
        this.signedInAs.set(event.username ?? '');
        break;
      case 'refresh':
        this.staleCount.set(event.stale ?? 0);
        this.undatedCount.set(event.undated ?? 0);
        this.stampedCount.set(event.stamped ?? 0);
        break;
      case 'failures':
        this.failures.set(event.failures ?? []);
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

  private finishUp(): void {
    this.paused.set(null);
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
   * Run again, this time fetching the works whose files carry no date.
   *
   * Back to the login rather than straight into it: the password was handed to the helper
   * and deliberately not kept, so it has to be given again.
   */
  protected refreshUndatedWorks(): void {
    this.refreshUndated.set(true);
    this.step.set('credentials');
  }

  protected setStampDate(value: string): void {
    this.stampDate.set(value);
  }

  /** whether what has been typed is a date this can actually be run with */
  protected readonly stampDateIsValid = computed(() => isDate(this.stampDate()));

  /**
   * Write the chosen date onto the undated files instead of fetching them again.
   *
   * Nothing is downloaded to do this - the files are renamed where they sit - but it runs
   * as part of a bookmarks run so that the ordinary rule can take over immediately: any
   * work ao3 has updated since that date is fetched on the same pass.
   */
  protected dateUndatedWorks(): void {
    if (!this.stampDateIsValid()) return;
    this.stampUndated.set(this.stampDate());
    this.step.set('credentials');
  }

  /** the failed works as the text that gets saved - kept apart from the saving itself */
  protected failureReport(): string {
    const rows = this.failures();
    const lines = [
      `# ${rows.length} work${rows.length === 1 ? '' : 's'} that could not be downloaded`,
      `# ${new Date().toISOString()}`,
      '# work id, link, reason - tab separated',
      ...rows.map((row) =>
        [row.id ?? '', row.link ?? '', (row.error ?? '').replace(/\s+/g, ' ')].join('\t'),
      ),
    ];
    return lines.join('\n') + '\n';
  }

  /**
   * Hand the list of failed works over as a text file.
   *
   * Done in the page rather than by the helper: it is a few lines the browser can save
   * directly, so it does not need a round trip or a second thing that writes to disk.
   */
  protected exportFailures(): void {
    if (!this.failures().length) return;

    const blob = new Blob([this.failureReport()], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `failed-downloads-${new Date().toISOString().slice(0, 10)}.txt`;
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

function safeGet(key: string): string {
  try {
    return localStorage.getItem(key) ?? '';
  } catch {
    return '';
  }
}

function safeSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private window or blocked site data
  }
}

function safeRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // nothing to clean up
  }
}
