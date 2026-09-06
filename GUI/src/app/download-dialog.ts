import { Component, OnDestroy, computed, inject, input, output, signal } from '@angular/core';
import { JobAction, JobEvent, Jobs } from './jobs';

type Step = 'filetypes' | 'options' | 'credentials' | 'running' | 'done' | 'failed';

const USERNAME_KEY = 'ao3.username';
const REMEMBER_KEY = 'ao3.remember';
const MAX_LOG = 200;

@Component({
  selector: 'app-download-dialog',
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
  protected readonly pages = signal(0);
  protected readonly series = signal(false);
  protected readonly images = signal(false);
  protected readonly workdates = signal(false);

  protected readonly log = signal<string[]>([]);
  protected readonly percent = signal<number | null>(null);
  protected readonly paused = signal<{ seconds: number; until: string } | null>(null);
  protected readonly summary = signal('');
  protected readonly error = signal('');
  protected readonly folder = signal('');

  /** what is being fetched right now */
  protected readonly currentTitle = signal('');
  protected readonly currentFiletype = signal('');

  protected readonly cancelling = signal(false);
  protected readonly wasCancelled = signal(false);

  private jobId: string | null = null;
  private stop: (() => void) | null = null;
  private unloadGuard: ((event: BeforeUnloadEvent) => void) | null = null;

  protected readonly title = computed(() =>
    this.action() === 'bookmarks' ? 'Download newly added bookmarks' : 'Update incomplete fics',
  );

  protected readonly blurb = computed(() =>
    this.action() === 'bookmarks'
      ? 'Reads your AO3 bookmarks and downloads anything not already in your downloads folder.'
      : 'Scans your downloads folder for works that were incomplete, and re-downloads any that have new chapters.',
  );

  /** JSON is metadata rather than a work, so the update run cannot produce it */
  protected readonly metadataNotApplicable = computed(() => this.action() === 'update');

  /** page limits, series expansion and publication dates only mean something for a listing */
  protected readonly listingOptions = computed(() => this.action() === 'bookmarks');

  /** what the run was asked to do, shown back while it works */
  protected readonly chosenOptions = computed(() => {
    const chosen: string[] = [];
    if (this.listingOptions()) {
      chosen.push(this.pages() === 0 ? 'all pages' : `stop after page ${this.pages()}`);
      if (this.series()) chosen.push('expand series links');
      if (this.workdates()) chosen.push('look up publication dates');
    }
    if (this.images()) chosen.push('embedded images');
    return chosen;
  });

  constructor() {
    void this.init();
  }

  private async init(): Promise<void> {
    const config = await this.jobs.loadConfig();
    if (!config) return;

    this.folder.set(config.downloadFolder);
    this.selected.set([...config.forced]);

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
    this.cancelling.set(false);
    this.wasCancelled.set(false);

    let jobId: string;
    try {
      jobId = await this.jobs.start({
        action: this.action(),
        filetypes: this.selected(),
        options: {
          pages: this.pages(),
          series: this.series(),
          images: this.images(),
          workdates: this.workdates(),
        },
        username: this.username().trim(),
        password: this.password(),
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
      case 'page':
        if (event.total) this.percent.set(Math.round(((event.page ?? 0) / event.total) * 100));
        this.summary.set(
          `page ${event.page ?? '?'} of ${event.total}` +
            (event.works !== undefined ? ` - ${event.works} works so far` : ''),
        );
        break;
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

  protected close(): void {
    if (this.step() === 'running') return; // the guard message explains why
    this.closed.emit();
  }
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
