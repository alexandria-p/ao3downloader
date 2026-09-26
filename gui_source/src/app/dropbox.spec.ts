import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  APP_FOLDER,
  APP_FOLDER_LABEL,
  DROPBOX_KEY,
  DropboxBrowser,
  DropboxSession,
  challengeFor,
} from './dropbox';
import { StorageChoice } from './storage-choice';

type Handler = (url: string, init: RequestInit) => Response | undefined;

/** stands in for everything the session reaches outside itself */
class FakeBrowser extends DropboxBrowser {
  url = 'http://localhost:4200/';
  redirectedTo = '';
  pending = '';
  stored = new Map<string, unknown>();
  calls: { url: string; init: RequestInit }[] = [];
  handlers: Handler[] = [];
  private counter = 0;

  override fetch(url: string, init: RequestInit): Promise<Response> {
    this.calls.push({ url, init });
    for (const handler of this.handlers) {
      const response = handler(url, init);
      if (response) return Promise.resolve(response);
    }
    return Promise.reject(new Error('no fake for ' + url));
  }

  override currentUrl(): string {
    return this.url;
  }

  override redirect(url: string): void {
    this.redirectedTo = url;
  }

  override replaceUrl(url: string): void {
    this.url = new URL(url, this.url).toString();
  }

  waited = 0;
  override async wait(): Promise<void> {
    this.waited++;
  }

  override random(length: number): Uint8Array {
    return new Uint8Array(length).fill(++this.counter);
  }

  override getPending(): string {
    return this.pending;
  }

  override setPending(value: string): void {
    this.pending = value;
  }

  override clearPending(): void {
    this.pending = '';
  }

  override async load<T>(key: string): Promise<T | null> {
    return (this.stored.get(key) as T) ?? null;
  }

  override async save(key: string, value: unknown): Promise<void> {
    this.stored.set(key, value);
  }

  override async remove(key: string): Promise<void> {
    this.stored.delete(key);
  }

  /** the endpoint each call went to, without the host */
  endpoints(): string[] {
    return this.calls.map((c) => c.url.replace(/^https:\/\/api\.dropboxapi\.com\/(2\/)?/, ''));
  }
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function on(endpoint: string, answer: (init: RequestInit) => Response): Handler {
  return (url, init) => (url.endsWith(endpoint) ? answer(init) : undefined);
}

const ACCOUNT = { account_id: 'dbid:me', email: 'me@example.com', name: { display_name: 'Me' } };
const tokens = (refresh = 'refresh-1') =>
  json({ access_token: 'access-1', expires_in: 14400, refresh_token: refresh });

function formOf(init: RequestInit): URLSearchParams {
  return new URLSearchParams(String(init.body));
}

describe('DropboxSession', () => {
  let browser: FakeBrowser;

  function session(key = 'app-key'): DropboxSession {
    TestBed.configureTestingModule({
      providers: [
        { provide: DropboxBrowser, useValue: browser },
        { provide: DROPBOX_KEY, useValue: key },
      ],
    });
    return TestBed.inject(DropboxSession);
  }

  /** a session remembered from an earlier visit */
  function remembered(): void {
    browser.stored.set('dropbox-session', {
      refreshToken: 'refresh-1',
      account: { id: 'dbid:me', name: 'Me', email: 'me@example.com' },
    });
  }

  beforeEach(() => {
    browser = new FakeBrowser();
  });

  // region PKCE

  it('derives the challenge from the verifier the way RFC 7636 says', async () => {
    // the worked example from the RFC itself, appendix B
    const challenge = await challengeFor(
      'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
      new DropboxBrowser(),
    );
    expect(challenge).toBe('E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
  });

  // endregion

  // region signing in

  it('offers no sign-in at all when no app key is configured', async () => {
    const dropbox = session('');
    await dropbox.restore();
    await dropbox.signIn();
    expect(dropbox.status()).toBe('unconfigured');
    expect(browser.redirectedTo).toBe('');
  });

  it('sends the user to dropbox with a PKCE challenge and asks for a refresh token', async () => {
    browser.url = 'http://localhost:4200/?stale=1#top';
    const dropbox = session();
    await dropbox.signIn();

    const url = new URL(browser.redirectedTo);
    expect(url.origin + url.pathname).toBe('https://www.dropbox.com/oauth2/authorize');
    expect(url.searchParams.get('client_id')).toBe('app-key');
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('code_challenge_method')).toBe('S256');
    expect(url.searchParams.get('token_access_type')).toBe('offline');
    // registered redirect uris match exactly, so the page's own query must not go with it
    expect(url.searchParams.get('redirect_uri')).toBe('http://localhost:4200/');

    const pending = JSON.parse(browser.pending);
    expect(url.searchParams.get('state')).toBe(pending.state);
    expect(url.searchParams.get('code_challenge')).toBe(
      await challengeFor(pending.verifier, new DropboxBrowser()),
    );
  });

  it('finishes the sign-in on the way back, with the verifier and not a secret', async () => {
    const dropbox = session();
    await dropbox.signIn();
    const { verifier, state } = JSON.parse(browser.pending);
    browser.url = `http://localhost:4200/?code=the-code&state=${state}`;
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('users/get_current_account', () => json(ACCOUNT)),
    );

    await dropbox.restore();

    expect(dropbox.status()).toBe('signed-in');
    expect(dropbox.account()).toEqual({ id: 'dbid:me', name: 'Me', email: 'me@example.com' });
    // signing in is all it takes: the app folder is the library, with nothing to choose
    expect(dropbox.folder()).toEqual(APP_FOLDER);
    const form = formOf(browser.calls[0].init);
    expect(form.get('grant_type')).toBe('authorization_code');
    expect(form.get('code')).toBe('the-code');
    expect(form.get('code_verifier')).toBe(verifier);
    expect(form.get('client_id')).toBe('app-key');
    expect(form.get('redirect_uri')).toBe('http://localhost:4200/');
    expect(form.has('client_secret')).toBe(false);
    // the refresh token is what is remembered; the access token never is
    expect(browser.stored.get('dropbox-session')).toEqual({
      refreshToken: 'refresh-1',
      account: { id: 'dbid:me', name: 'Me', email: 'me@example.com' },
    });
    // a spent code is not left in the address bar
    expect(browser.url).toBe('http://localhost:4200/');
    expect(browser.pending).toBe('');
  });

  it('refuses a code whose state is not the one this tab sent', async () => {
    const dropbox = session();
    await dropbox.signIn();
    browser.url = 'http://localhost:4200/?code=the-code&state=someone-else';

    await dropbox.restore();

    expect(browser.calls).toEqual([]);
    expect(dropbox.status()).toBe('signed-out');
    expect(dropbox.error()).toContain('did not come from this page');
  });

  it('says so plainly when the user cancels on dropbox.com', async () => {
    const dropbox = session();
    await dropbox.signIn();
    browser.url = 'http://localhost:4200/?error=access_denied&error_description=nope';

    await dropbox.restore();

    expect(dropbox.error()).toBe('Dropbox sign-in was cancelled.');
    expect(browser.url).toBe('http://localhost:4200/');
  });

  it('leaves an unrelated code in the address bar alone when no sign-in was started', async () => {
    browser.url = 'http://localhost:4200/?code=not-ours';
    const dropbox = session();
    await dropbox.restore();
    expect(browser.calls).toEqual([]);
    expect(browser.url).toBe('http://localhost:4200/?code=not-ours');
  });

  // endregion

  // region a remembered session

  it('opens the app folder from the session remembered last time, without asking dropbox', async () => {
    remembered();
    const dropbox = session();
    await dropbox.restore();

    expect(dropbox.status()).toBe('signed-in');
    expect(dropbox.folder()).toEqual(APP_FOLDER);
    expect(browser.calls).toEqual([]);
  });

  it('has no library at all while signed out', async () => {
    const dropbox = session();
    await dropbox.restore();
    expect(dropbox.folder()).toBeNull();
    expect(dropbox.runStorage()).toBeNull();
  });

  // endregion

  // region tokens

  it('refreshes an access token dropbox has turned down, and tries the call once more', async () => {
    remembered();
    let listed = 0;
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/list_folder', () =>
        ++listed === 1
          ? json({ error_summary: 'expired_access_token/' }, 401)
          : json({ entries: [], cursor: 'c', has_more: false }),
      ),
    );
    const dropbox = session();
    await dropbox.restore();
    await dropbox.listFiles('');

    expect(browser.endpoints()).toEqual([
      'oauth2/token',
      'files/list_folder',
      'oauth2/token',
      'files/list_folder',
    ]);
    const refresh = formOf(browser.calls[2].init);
    expect(refresh.get('grant_type')).toBe('refresh_token');
    expect(refresh.get('refresh_token')).toBe('refresh-1');
  });

  it('signs out, and says why, when dropbox refuses the refresh token', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => json({ error: 'invalid_grant', error_description: 'revoked' }, 400)),
    );
    const dropbox = session();
    await dropbox.restore();

    await expect(dropbox.listFiles('')).rejects.toThrow();
    expect(dropbox.status()).toBe('signed-out');
    expect(dropbox.folder()).toBeNull();
    expect(dropbox.error()).toContain('Sign in again');
    expect(browser.stored.has('dropbox-session')).toBe(false);
  });

  it('reuses one access token across calls until it nears expiry', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/list_folder', () => json({ entries: [], cursor: 'c', has_more: false })),
    );
    const dropbox = session();
    await dropbox.restore();
    await Promise.all([dropbox.listFiles(''), dropbox.listFiles(''), dropbox.listFiles('')]);

    expect(browser.endpoints().filter((e) => e === 'oauth2/token')).toHaveLength(1);
  });

  it('revokes the token and forgets everything on sign-out', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('auth/token/revoke', () => new Response(null, { status: 200 })),
    );
    const dropbox = session();
    await dropbox.restore();
    await dropbox.signOut();

    const revoke = browser.calls.find((c) => c.url.endsWith('auth/token/revoke'))!;
    // an endpoint with no arguments takes no body at all
    expect(revoke.init.body).toBeUndefined();
    expect(dropbox.status()).toBe('signed-out');
    expect(dropbox.account()).toBeNull();
    expect(dropbox.folder()).toBeNull();
    expect(browser.stored.size).toBe(0);
  });

  // endregion

  // region reading the library

  it('lists every file below the folder in one recursive listing', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/list_folder', (init) => {
        expect(JSON.parse(String(init.body))).toEqual({ path: '', recursive: true, limit: 2000 });
        return json({
          entries: [
            { '.tag': 'folder', name: 'indexing', path_display: '/indexing' },
            {
              '.tag': 'file',
              name: '1.json',
              path_display: '/indexing/1.json',
              server_modified: '2026-01-02T03:04:05Z',
            },
          ],
          cursor: 'c',
          has_more: false,
        });
      }),
    );
    const dropbox = session();
    await dropbox.restore();

    expect(await dropbox.listFiles('')).toEqual([
      { name: '1.json', path: '/indexing/1.json', modified: Date.parse('2026-01-02T03:04:05Z') },
    ]);
  });

  it('treats a folder that is not there as an empty one', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/list_folder', () => json({ error_summary: 'path/not_found/..' }, 409)),
    );
    const dropbox = session();
    await dropbox.restore();
    expect(await dropbox.listFiles('/Gone')).toEqual([]);
  });

  it('moves works into a folder in one batch, waiting for dropbox to finish the job', async () => {
    remembered();
    let checks = 0;
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/move_batch_v2', (init) => {
        expect(JSON.parse(String(init.body))).toEqual({
          entries: [
            { from_path: '/111 A.html', to_path: '/works/111 A.html' },
            { from_path: '/222 B.epub', to_path: '/works/222 B.epub' },
          ],
          autorename: false,
        });
        return json({ '.tag': 'async_job_id', async_job_id: 'job-1' });
      }),
      on('files/move_batch/check_v2', (init) => {
        expect(JSON.parse(String(init.body))).toEqual({ async_job_id: 'job-1' });
        return ++checks < 2
          ? json({ '.tag': 'in_progress' })
          : json({ '.tag': 'complete', entries: [{ '.tag': 'success' }, { '.tag': 'failure' }] });
      }),
    );
    const dropbox = session();
    await dropbox.restore();
    const progress: number[] = [];

    const result = await dropbox.moveInto('works', ['111 A.html', '222 B.epub'], (n) => progress.push(n));

    expect(result).toEqual({ moved: 1, notMoved: ['222 B.epub'] });
    expect(browser.waited).toBe(2);
    expect(progress).toEqual([2]);
  });

  it('makes a folder, and treats one already there as made', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/create_folder_v2', (init) =>
        JSON.parse(String(init.body)).path === '/works'
          ? json({ metadata: {} })
          : json({ error_summary: 'path/conflict/folder/..' }, 409),
      ),
    );
    const dropbox = session();
    await dropbox.restore();

    await dropbox.makeFolder('works');
    await dropbox.makeFolder('runs');
  });

  it('names the folders and files in the top level of the app folder', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/list_folder', (init) => {
        expect(JSON.parse(String(init.body))).toEqual({ path: '', recursive: false });
        return json({
          entries: [
            { '.tag': 'folder', name: 'works' },
            { '.tag': 'file', name: '111 A.html' },
          ],
          cursor: 'c',
          has_more: false,
        });
      }),
    );
    const dropbox = session();
    await dropbox.restore();

    expect(await dropbox.topLevel()).toEqual({ folders: ['works'], files: ['111 A.html'] });
  });

  it('asks for a file with its path in a plain-ascii header, whatever the title', async () => {
    remembered();
    browser.handlers.push(
      on('oauth2/token', () => tokens()),
      on('files/download_zip', () => new Response(new Uint8Array([80, 75]))),
    );
    const dropbox = session();
    await dropbox.restore();
    await dropbox.downloadZip('/Café ☕');

    const call = browser.calls.find((c) => c.url === 'https://content.dropboxapi.com/2/files/download_zip')!;
    const header = (call.init.headers as Record<string, string>)['Dropbox-API-Arg'];
    expect(/^[\x20-\x7e]*$/.test(header)).toBe(true);
    expect(JSON.parse(header)).toEqual({ path: '/Café ☕' });
  });

  // endregion
});

describe('StorageChoice', () => {
  beforeEach(() => localStorage.clear());

  /** a fresh page load: a new injector, so a new StorageChoice reading what was stored */
  function load(): StorageChoice {
    TestBed.resetTestingModule();
    return TestBed.inject(StorageChoice);
  }

  it('starts on this computer, and remembers a switch to dropbox', () => {
    expect(load().mode()).toBe('local');
    load().set('dropbox');
    expect(load().mode()).toBe('dropbox');
  });

  it('hands the helper no dropbox library while this computer is the choice', () => {
    const choice = load();
    TestBed.inject(DropboxSession).status.set('signed-in');

    expect(choice.dropboxLibrary()).toBeNull();
    expect(choice.dropboxFolderLabel()).toBeNull();
  });

  it('hands over nothing until there is a session', () => {
    const choice = load();
    choice.set('dropbox');
    expect(choice.dropboxLibrary()).toBeNull();
  });
});

describe('what a run is handed', () => {
  it('is the session, the app key and the app folder', async () => {
    const browser = new FakeBrowser();
    browser.stored.set('dropbox-session', {
      refreshToken: 'refresh-1',
      account: { id: 'dbid:me', name: 'Me', email: 'me@example.com' },
    });
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        { provide: DropboxBrowser, useValue: browser },
        { provide: DROPBOX_KEY, useValue: 'app-key' },
      ],
    });
    localStorage.setItem('ao3.storageMode', 'dropbox');
    await TestBed.inject(DropboxSession).restore();

    const choice = TestBed.inject(StorageChoice);
    expect(choice.dropboxLibrary()).toEqual({
      kind: 'dropbox',
      appKey: 'app-key',
      refreshToken: 'refresh-1',
      folderId: '',
      folderPath: '',
    });
    expect(choice.dropboxFolderLabel()).toBe(APP_FOLDER_LABEL);
    localStorage.clear();
  });
});
