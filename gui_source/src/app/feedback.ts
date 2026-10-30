import {
  Component,
  ElementRef,
  Injectable,
  OnDestroy,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { HelperConnection } from './helper-connection';
import { Jobs } from './jobs';
import { Library } from './library';
import { saveText } from './issues';
import { DropboxLibraryStore, LibraryStore, LocalLibraryStore } from './library-store';
import { safeGet } from './storage';

/**
 * The feedback tab on the right edge of every page, and the form it opens.
 *
 * A submission goes to the feedback Worker on Cloudflare (`feedback_worker/`, FEEDBACK.md),
 * never to the helper: the Worker holds the GitHub token and opens an issue labelled
 * `feedback` and `positive` or `negative`. So nobody leaves the page or signs up for anything,
 * and a hosted copy's Render helper is never asked to do it. Turnstile, Cloudflare's bot
 * check, stands in front of it - the page shows the widget, the Worker checks its token.
 *
 * The tab is only there when the build was given the Worker's address and the widget's site
 * key (`feedbackUrl`, `turnstileSiteKey` in app-config.json) - a copy built on this computer
 * has neither, and a form that could never be sent is not offered.
 */

export type Sentiment = 'positive' | 'negative';

/** what is said in place of the AO3 username in an attached log */
export const USERNAME_REMOVED = '[your AO3 username]';

const TURNSTILE_SCRIPT = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
/** the same remembered username the run window fills in */
const USERNAME_KEY = 'ao3.username';
/** the Worker's own limits - anything longer it refuses (message, name) or trims (the log) */
export const MESSAGE_LIMIT = 5000;
export const NAME_LIMIT = 100;
/** how long a send may take before it counts as failed, rather than 'Sending...' for ever */
export const SEND_TIMEOUT_MS = 30_000;
/** GitHub's new-issue page takes the text in its address, which browsers cap; the log never goes */
const PREFILL_LIMIT = 4000;

/**
 * Cloudflare's widget, behind a seam: the tests stand in for it, since there is no Cloudflare
 * in jsdom. `render` resolves to the widget's id once it is on the page.
 */
@Injectable({ providedIn: 'root' })
export class Turnstile {
  private loading: Promise<TurnstileApi> | null = null;

  async render(element: HTMLElement, siteKey: string, token: (value: string) => void): Promise<string> {
    const api = await this.load();
    return api.render(element, {
      sitekey: siteKey,
      theme: 'dark',
      callback: (value: string) => token(value),
      'expired-callback': () => token(''),
      'error-callback': () => token(''),
    });
  }

  /** a token works once, so a refused submission needs a fresh check */
  reset(id: string): void {
    window.turnstile?.reset(id);
  }

  remove(id: string): void {
    window.turnstile?.remove(id);
  }

  private load(): Promise<TurnstileApi> {
    if (window.turnstile) return Promise.resolve(window.turnstile);
    // a failed load is not kept, so opening the form again tries again
    this.loading ??= new Promise<TurnstileApi>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = TURNSTILE_SCRIPT;
      script.async = true;
      script.onload = () => (window.turnstile ? resolve(window.turnstile) : reject(new Error('no turnstile')));
      script.onerror = () => {
        script.remove();
        reject(new Error('could not load the bot check'));
      };
      document.head.appendChild(script);
    }).catch((error) => {
      this.loading = null;
      throw error;
    });
    return this.loading;
  }
}

interface TurnstileApi {
  render(element: HTMLElement, options: Record<string, unknown>): string;
  reset(id: string): void;
  remove(id: string): void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

/** the newest run's log, with what it needs to be read */
export interface LatestLog {
  actionName: string;
  started: string;
  username: string;
  lines: string[];
}

/** The newest run record in the library, or null when there is none or it will not read. */
export async function readLatestLog(store: LibraryStore): Promise<LatestLog | null> {
  try {
    // named for when they started, so the newest is last by name
    const newest = (await store.list('runs', false)).filter((path) => /\.json$/i.test(path)).sort().pop();
    if (!newest) return null;
    const record = JSON.parse((await store.read(newest)) ?? '') as Record<string, unknown>;
    if (!record || typeof record !== 'object') return null;
    const text = (value: unknown) => (typeof value === 'string' ? value : '');
    return {
      actionName: text(record['actionName']) || text(record['action']),
      started: text(record['started']),
      username: text(record['username']),
      lines: Array.isArray(record['log']) ? record['log'].map(String) : [],
    };
  } catch {
    return null;
  }
}

/**
 * The log as it will be sent: every AO3 username named, in any case, replaced, and anything
 * that looks like a password taken out. No run prints a password - the Worker scrubs the same
 * pattern again - but this is what the person sees before sending, so it is done here too.
 */
export function redactLog(text: string, usernames: string[]): string {
  let redacted = text;
  const names = [...new Set(usernames.map((name) => name.trim()).filter(Boolean))]
    // longest first, so a name containing another is replaced whole
    .sort((a, b) => b.length - a.length);
  for (const name of names) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    redacted = redacted.replace(new RegExp(escaped, 'gi'), USERNAME_REMOVED);
  }
  return redacted.replace(/(password["']?\s*[:=]\s*)("[^"]*"|'[^']*'|\S+)/gi, '$1[removed]');
}

type Stage = 'form' | 'sending' | 'sent';

@Component({
  selector: 'app-feedback',
  templateUrl: './feedback.html',
  styleUrl: './feedback.css',
  host: { '(document:keydown.escape)': 'escape()' },
})
export class Feedback implements OnDestroy {
  private readonly helper = inject(HelperConnection);
  private readonly library = inject(Library);
  private readonly jobs = inject(Jobs);
  private readonly turnstile = inject(Turnstile);

  /** whether this copy can send feedback at all */
  protected readonly offered = computed(() => !!this.helper.settings().feedbackUrl);
  protected readonly open = signal(false);
  protected readonly stage = signal<Stage>('form');

  protected readonly sentiment = signal<Sentiment | ''>('');
  protected readonly message = signal('');
  protected readonly name = signal('');
  protected readonly attachLog = signal(false);
  /** the log exactly as it would be sent, once read; '' while reading or when there is none */
  protected readonly logPreview = signal('');
  protected readonly logNote = signal('');
  protected readonly canAttach = computed(() => !!this.library.store());

  protected readonly token = signal('');
  protected readonly checkProblem = signal('');
  protected readonly problem = signal('');
  protected readonly sent = signal<{ number: number; url: string } | null>(null);

  protected readonly messageLimit = MESSAGE_LIMIT;
  protected readonly nameLimit = NAME_LIMIT;
  private readonly repository = computed(() => `https://github.com/${this.helper.settings().releasesRepo}`);
  protected readonly feedbackList = computed(() => `${this.repository()}/issues?q=label%3Afeedback`);
  /** where to go when the form cannot be sent - it needs a GitHub account, so it is the fallback */
  protected readonly newIssue = computed(() => `${this.repository()}/issues/new`);
  /** the same, with what was written filled in - so sending it by hand loses nothing either */
  protected readonly newIssueFilled = computed(() => {
    const message = this.message().trim();
    const title = `Feedback (${this.sentiment() || 'feedback'}): ${message.split('\n')[0].slice(0, 60)}`;
    const body = message.length > PREFILL_LIMIT ? `${message.slice(0, PREFILL_LIMIT)}...` : message;
    const query = new URLSearchParams({ title, body });
    return `${this.newIssue()}?${query}`;
  });
  /** the form could not be sent, either way - the window then offers the text and GitHub */
  protected readonly failed = computed(() => !!this.problem() || !!this.checkProblem());
  protected readonly canSend = computed(
    () =>
      this.stage() === 'form' &&
      !!this.sentiment() &&
      !!this.message().trim() &&
      this.message().length <= MESSAGE_LIMIT &&
      this.name().length <= NAME_LIMIT &&
      !!this.token() &&
      (!this.attachLog() || !!this.logPreview()),
  );

  private readonly widget = viewChild<ElementRef<HTMLElement>>('check');
  private widgetId = '';

  constructor() {
    // the widget goes in when its place appears - the form opening - and nowhere else
    effect(() => {
      const element = this.widget()?.nativeElement;
      if (element) untracked(() => void this.mountCheck(element));
    });
  }

  ngOnDestroy(): void {
    this.unmountCheck();
  }

  protected show(): void {
    if (this.stage() === 'sent') this.reset();
    this.open.set(true);
  }

  protected close(): void {
    this.open.set(false);
    this.unmountCheck();
    // a sent form starts afresh next time; an unsent one keeps what was typed
    if (this.stage() === 'sent') this.reset();
  }

  protected escape(): void {
    if (this.open() && this.stage() !== 'sending') this.close();
  }

  protected async toggleLog(on: boolean): Promise<void> {
    this.attachLog.set(on);
    this.logPreview.set('');
    this.logNote.set('');
    if (!on) return;
    const store = this.library.store();
    const latest = store ? await readLatestLog(store) : null;
    if (!this.attachLog()) return;
    if (!latest || !latest.lines.length) {
      this.logNote.set('There is no run log in this library to attach yet.');
      return;
    }
    const head = `# ${latest.actionName || 'a run'}, started ${latest.started || 'at an unknown time'}`;
    const names = [latest.username, this.jobs.config()?.username ?? '', safeGet(USERNAME_KEY)];
    this.logPreview.set(redactLog([head, '', ...latest.lines].join('\n'), names));
  }

  protected async send(event?: Event): Promise<void> {
    event?.preventDefault();
    if (!this.canSend()) return;
    this.stage.set('sending');
    this.problem.set('');
    try {
      // offline is a failure like any other, said at once rather than after a timeout
      if (navigator.onLine === false) throw new Error('this computer is offline');
      const response = await fetch(this.helper.settings().feedbackUrl, {
        method: 'POST',
        signal: AbortSignal.timeout(SEND_TIMEOUT_MS),
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sentiment: this.sentiment(),
          message: this.message().trim(),
          name: this.name().trim(),
          log: this.attachLog() ? this.logPreview() : '',
          version: this.helper.settings().version,
          copy: this.helper.isLocal() ? 'on their own computer' : 'the hosted page',
          storage: this.storageKind(),
          browser: navigator.userAgent,
          turnstileToken: this.token(),
        }),
      });
      const answer = (await response.json().catch(() => ({}))) as {
        number?: number;
        url?: string;
        error?: string;
      };
      if (!response.ok || !answer.url) {
        throw new Error(answer.error || `the feedback service answered ${response.status}`);
      }
      this.sent.set({ number: answer.number ?? 0, url: answer.url });
      this.stage.set('sent');
      this.unmountCheck();
    } catch (error) {
      this.problem.set(failureReason(error));
      this.stage.set('form');
      // a token works once: whatever happened to this one, the next try needs another
      this.token.set('');
      if (this.widgetId) this.turnstile.reset(this.widgetId);
    }
  }

  /**
   * Where the library the page has open lives - Dropbox or this computer - and nothing more.
   * Never the folder's name: the issue is public, and a folder can be named for its owner.
   */
  protected storageKind(): string {
    const store = this.library.store();
    if (store instanceof DropboxLibraryStore) return 'Dropbox';
    if (store instanceof LocalLibraryStore) return 'a folder on this computer';
    // a browser without a folder picker hands a folder over as files, which can be read only
    if (this.library.data()) return 'a folder on this computer (read only)';
    return 'no library open';
  }

  /** everything that was written, as a file, so a failed send never loses it */
  protected downloadAttempt(): void {
    const lines = [
      '# ao3downloader feedback - not sent',
      '',
      `Sentiment: ${this.sentiment() || '(not chosen)'}`,
      `Name: ${this.name().trim() || '(none given)'}`,
      `Version: ${this.helper.settings().version || '(built on this computer)'}`,
      `Library: ${this.storageKind()}`,
      `Written: ${new Date().toISOString()}`,
      '',
      '## Feedback',
      '',
      this.message().trim(),
    ];
    if (this.attachLog() && this.logPreview()) {
      lines.push('', '## Latest run log (AO3 username removed)', '', this.logPreview());
    }
    saveText(lines.join('\n') + '\n', `ao3downloader-feedback-${new Date().toISOString().slice(0, 10)}`);
  }

  private reset(): void {
    this.stage.set('form');
    this.sentiment.set('');
    this.message.set('');
    this.name.set('');
    this.attachLog.set(false);
    this.logPreview.set('');
    this.logNote.set('');
    this.problem.set('');
    this.sent.set(null);
    this.token.set('');
  }

  private async mountCheck(element: HTMLElement): Promise<void> {
    this.unmountCheck();
    this.checkProblem.set('');
    try {
      const id = await this.turnstile.render(element, this.helper.settings().turnstileSiteKey, (value) =>
        this.token.set(value),
      );
      // closed while it loaded: the element it went into is gone
      if (!this.open() || this.widget()?.nativeElement !== element) {
        this.turnstile.remove(id);
        return;
      }
      this.widgetId = id;
    } catch {
      this.checkProblem.set(
        'The bot check would not load - this computer may be offline, or a blocker or this ' +
          'network may be stopping it.',
      );
    }
  }

  private unmountCheck(): void {
    if (this.widgetId) this.turnstile.remove(this.widgetId);
    this.widgetId = '';
    this.token.set('');
  }
}

/** why a send failed, in words for the failure panel */
export function failureReason(error: unknown): string {
  if (error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')) {
    return 'the feedback service took too long to answer';
  }
  const reason = error instanceof Error ? error.message : String(error);
  // what a browser says when it never got an answer at all: offline, blocked, or the service down
  if (error instanceof TypeError) return 'the feedback service could not be reached';
  return reason || 'something went wrong';
}
