import { ComponentFixture, TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Feedback, Turnstile, USERNAME_REMOVED, readLatestLog, redactLog } from './feedback';
import { DEFAULT_PAGE_CONFIG, HelperConnection } from './helper-connection';
import { Library } from './library';
import { LibraryStore } from './library-store';

const WORKER = 'https://feedback.example.workers.dev';

/** Cloudflare's widget, passing at once unless told not to */
class FakeTurnstile extends Turnstile {
  rendered = 0;
  resets = 0;
  removed: string[] = [];
  pass = true;
  private give: (token: string) => void = () => {};

  override async render(_element: HTMLElement, _siteKey: string, token: (value: string) => void): Promise<string> {
    this.rendered++;
    this.give = token;
    if (this.pass) token(`token-${this.rendered}`);
    return `widget-${this.rendered}`;
  }

  override reset(_id: string): void {
    this.resets++;
    if (this.pass) this.give(`token-again-${this.resets}`);
  }

  override remove(id: string): void {
    this.removed.push(id);
  }
}

/** a library holding only run records */
function storeWith(files: Record<string, string>): LibraryStore {
  return {
    label: 'test',
    check: async () => {},
    list: async () => Object.keys(files),
    read: async (path: string) => files[path] ?? null,
    write: async () => 0,
    size: async () => null,
    delete: async () => {},
    rename: async () => {},
    mkdir: async () => {},
  };
}

function record(over: Record<string, unknown> = {}): string {
  return JSON.stringify({
    actionName: 'Quick scan',
    started: '2026-10-20T10:00:00',
    username: 'ReaderName',
    log: ['logging in as ReaderName', 'new download: 1 A.html'],
    ...over,
  });
}

let turnstile: FakeTurnstile;
let helper: HelperConnection;
let fixture: ComponentFixture<Feedback>;
let element: HTMLElement;

function answering(status: number, body: object) {
  const fetching = vi.fn(async (_url: unknown, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetching);
  return fetching;
}

async function settle() {
  for (let i = 0; i < 4; i++) {
    await fixture.whenStable();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  fixture.detectChanges();
}

async function make(feedbackUrl = WORKER) {
  helper.settings.set({ ...DEFAULT_PAGE_CONFIG, feedbackUrl, turnstileSiteKey: feedbackUrl ? '0x4AAA' : '' });
  fixture = TestBed.createComponent(Feedback);
  element = fixture.nativeElement as HTMLElement;
  await settle();
}

async function openForm() {
  (element.querySelector('.feedback-tab') as HTMLButtonElement).click();
  await settle();
}

async function fill(sentiment: 'positive' | 'negative', message: string, name = '') {
  (element.querySelector(`input[value="${sentiment}"]`) as HTMLInputElement).dispatchEvent(new Event('change'));
  const text = element.querySelector('textarea') as HTMLTextAreaElement;
  text.value = message;
  text.dispatchEvent(new Event('input'));
  if (name) {
    const input = element.querySelector('input[name="name"]') as HTMLInputElement;
    input.value = name;
    input.dispatchEvent(new Event('input'));
  }
  await settle();
}

function sendButton(): HTMLButtonElement {
  return element.querySelector('button[type="submit"]') as HTMLButtonElement;
}

async function send() {
  element.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
  await settle();
}

async function tickLog() {
  const box = element.querySelector('input[name="attachLog"]') as HTMLInputElement;
  box.checked = true;
  box.dispatchEvent(new Event('change'));
  await settle();
}

function sentBody(fetching: ReturnType<typeof answering>): Record<string, unknown> {
  return JSON.parse(String(fetching.mock.calls[0][1]?.body));
}

describe('Feedback', () => {
  beforeEach(() => {
    localStorage.clear();
    turnstile = new FakeTurnstile();
    helper = new HelperConnection();
    TestBed.configureTestingModule({
      providers: [
        { provide: Turnstile, useValue: turnstile },
        { provide: HelperConnection, useValue: helper },
      ],
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('offers no tab on a copy built without the feedback service', async () => {
    await make('');
    expect(element.querySelector('.feedback-tab')).toBeNull();
  });

  it('opens the form from the tab, with the bot check in it', async () => {
    await make();
    expect(element.querySelector('[role="dialog"]')).toBeNull();

    await openForm();

    expect(element.querySelector('[role="dialog"]')).not.toBeNull();
    expect(turnstile.rendered).toBe(1);
    // nobody is asked how to be contacted: the issue is public
    expect(element.querySelector('input[type="email"]')).toBeNull();
  });

  it('cannot be sent without a sentiment and a message, or before the bot check passes', async () => {
    turnstile.pass = false;
    await make();
    await openForm();
    expect(sendButton().disabled).toBe(true);

    await fill('positive', 'Love it');
    expect(sendButton().disabled).toBe(true);
  });

  it('sends the form to the feedback service, never the helper, and links the issue it made', async () => {
    const fetching = answering(201, { ok: true, number: 12, url: 'https://github.com/o/r/issues/12' });
    await make();
    await openForm();
    await fill('negative', 'The quick scan stopped', 'Sam');
    expect(sendButton().disabled).toBe(false);

    await send();

    expect(fetching.mock.calls[0][0]).toBe(WORKER);
    const body = sentBody(fetching);
    expect(body).toMatchObject({
      sentiment: 'negative',
      message: 'The quick scan stopped',
      name: 'Sam',
      log: '',
      turnstileToken: 'token-1',
    });
    const link = element.querySelector('a[href="https://github.com/o/r/issues/12"]');
    expect(link?.textContent).toContain('issue #12');
    expect(element.textContent).toContain('within a minute');
    expect(element.querySelector('a[href*="label%3Afeedback"]')).not.toBeNull();
  });

  it('says why it was not sent, keeps what was typed, and gets a fresh bot check', async () => {
    answering(403, { error: 'the bot check did not pass - try again' });
    await make();
    await openForm();
    await fill('positive', 'Nice');

    await send();

    expect(element.textContent).toContain('the bot check did not pass');
    expect((element.querySelector('textarea') as HTMLTextAreaElement).value).toBe('Nice');
    expect(turnstile.resets).toBe(1);
    expect(element.querySelector('a[href$="/issues/new"]')).not.toBeNull();
  });

  it('closes on escape, taking the bot check down with it', async () => {
    await make();
    await openForm();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();

    expect(element.querySelector('[role="dialog"]')).toBeNull();
    expect(turnstile.removed).toEqual(['widget-1']);
  });

  it('offers to attach a log only with a library open', async () => {
    await make();
    await openForm();
    const box = element.querySelector('input[name="attachLog"]') as HTMLInputElement;
    expect(box.disabled).toBe(true);
    expect(element.textContent).toContain('Open your library');
  });

  it('attaches the latest run log with the AO3 username taken out, and shows it first', async () => {
    const fetching = answering(201, { ok: true, number: 3, url: 'https://github.com/o/r/issues/3' });
    TestBed.inject(Library).store.set(
      storeWith({
        'runs/2026-10-01T090000-a.json': record({ log: ['an older run'] }),
        'runs/2026-10-20T100000-b.json': record(),
      }),
    );
    await make();
    await openForm();
    await fill('negative', 'It failed');

    await tickLog();

    const preview = element.querySelector('.log pre')?.textContent ?? '';
    expect(preview).toContain('new download: 1 A.html');
    expect(preview).toContain(`logging in as ${USERNAME_REMOVED}`);
    expect(preview).not.toContain('ReaderName');
    expect(preview).not.toContain('an older run');

    await send();

    const log = String(sentBody(fetching)['log']);
    expect(log).toContain('# Quick scan');
    expect(log).not.toContain('ReaderName');
  });

  it('says so when the library has no run log to attach, and does not send without one', async () => {
    TestBed.inject(Library).store.set(storeWith({}));
    await make();
    await openForm();
    await fill('positive', 'Hi');

    await tickLog();

    expect(element.textContent).toContain('no run log in this library');
    expect(sendButton().disabled).toBe(true);
  });
});

describe('redactLog', () => {
  it('takes out every username given, in any case, longest first', () => {
    expect(redactLog('Reader and reader and ReaderTwo', ['Reader', 'readertwo', ''])).toBe(
      `${USERNAME_REMOVED} and ${USERNAME_REMOVED} and ${USERNAME_REMOVED}`,
    );
  });

  it('treats a username as text, not a pattern', () => {
    expect(redactLog('a.b and axb', ['a.b'])).toBe(`${USERNAME_REMOVED} and axb`);
  });

  it('takes out anything that looks like a password', () => {
    expect(redactLog('password=hunter2 {"password": "x"}', [])).toBe(
      'password=[removed] {"password": [removed]}',
    );
  });
});

describe('readLatestLog', () => {
  it('reads the newest run record, by name', async () => {
    const latest = await readLatestLog(
      storeWith({ 'runs/2026-10-20T1.json': record(), 'runs/2026-09-01T1.json': record({ actionName: 'Old' }) }),
    );
    expect(latest?.actionName).toBe('Quick scan');
    expect(latest?.username).toBe('ReaderName');
  });

  it('answers nothing for a library with no runs or a record that will not read', async () => {
    expect(await readLatestLog(storeWith({}))).toBeNull();
    expect(await readLatestLog(storeWith({ 'runs/x.json': 'not json' }))).toBeNull();
  });
});
