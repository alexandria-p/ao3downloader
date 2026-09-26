/**
 * Signing in to Dropbox, whose app folder stands in for the downloads folder.
 *
 * **This is OAuth with PKCE, straight from the page - there is no server in it.** A browser
 * app cannot keep a client secret, so it proves it started the sign-in by a one-off
 * `code_verifier` instead: its hash goes out with the sign-in, the verifier itself comes
 * back with the code, and only whoever holds both gets a token. The app key is public.
 *
 * Tokens: the access token lasts a few hours and is kept **in memory only**; the refresh
 * token (`token_access_type=offline`) is what is remembered, in IndexedDB, and is traded
 * for a fresh access token whenever one runs out. The helper will be handed the refresh
 * token per run for the same reason - a run can outlast any one access token.
 *
 * Direct `fetch` rather than the `dropbox` npm package, deliberately: this needs six
 * endpoints, and the SDK is a large dependency for a page already near its size budget.
 * Every Dropbox endpoint used here answers CORS, so the page can call them itself.
 *
 * The app is an **App folder** app, so every path is relative to `/Apps/<app name>/` and
 * `''` is that folder itself - the page cannot see or touch anything outside it. **That
 * folder is the library**, always: there is nothing to choose, so signing in is all it
 * takes to open it. Letting people pick a subfolder was tried and taken out - it was one
 * more thing to set up, for a folder that already belongs to this app alone.
 */

import { Injectable, InjectionToken, computed, inject, signal } from '@angular/core';
import { DROPBOX_APP_FOLDER, DROPBOX_APP_KEY } from './dropbox-config';
import { deleteValue, getValue, putValue } from './folder-store';

const AUTHORIZE_URL = 'https://www.dropbox.com/oauth2/authorize';
const TOKEN_URL = 'https://api.dropboxapi.com/oauth2/token';
const API_URL = 'https://api.dropboxapi.com/2/';
const CONTENT_URL = 'https://content.dropboxapi.com/2/';

const SESSION_KEY = 'dropbox-session';
const PENDING_KEY = 'ao3.dropboxPending';

/** refresh this long before the access token actually runs out, so none expires mid-call */
const EXPIRY_MARGIN_MS = 60_000;
/** the most files Dropbox moves in one request */
const MOVE_BATCH_SIZE = 1000;
/** how long to leave a batch move before asking whether it has finished */
const MOVE_POLL_MS = 1000;

export const DROPBOX_KEY = new InjectionToken<string>('dropbox app key', {
  providedIn: 'root',
  factory: () => DROPBOX_APP_KEY,
});

export type DropboxStatus = 'unconfigured' | 'signed-out' | 'signing-in' | 'signed-in';

export interface DropboxAccount {
  id: string;
  name: string;
  email: string;
}

/**
 * The folder the library lives in. It is always the app folder - `path` `''` - but is kept
 * as a value rather than assumed, so the helper is told plainly where to write.
 */
export interface DropboxFolder {
  id: string;
  path: string;
  name: string;
}

/**
 * What the helper is handed to write a run into Dropbox.
 *
 * The refresh token goes because a run can outlast any one access token and has to renew
 * its own; the app key goes because renewing a PKCE session needs it and nothing else. The
 * helper keeps these in memory for the run and writes them nowhere.
 */
export interface DropboxStorageRequest {
  kind: 'dropbox';
  appKey: string;
  refreshToken: string;
  folderId: string;
  folderPath: string;
}

/** one file in the library, as a recursive listing describes it */
export interface DropboxFile {
  name: string;
  path: string;
  /** when Dropbox last saw it change, in ms; picks the newest of two copies of one work */
  modified: number;
}

/** the app folder itself - it has no id of its own to look up, and needs none */
export const APP_FOLDER: DropboxFolder = { id: '', path: '', name: DROPBOX_APP_FOLDER };

/**
 * The library, as a person would say where it is. The helper words the same folder the same
 * way, so the run dialog does not change its mind once a run starts.
 */
export const APP_FOLDER_LABEL = 'Dropbox app folder';

/** where to find it in Dropbox itself, for anyone who goes looking */
export const APP_FOLDER_PATH = `/Apps/${DROPBOX_APP_FOLDER}`;

/** what is remembered between visits; the access token never is */
interface StoredSession {
  refreshToken: string;
  account: DropboxAccount;
}

/** the sign-in in flight, kept across the redirect to dropbox.com and back */
interface Pending {
  verifier: string;
  state: string;
  redirectUri: string;
}

/** A failed Dropbox call, with Dropbox's own `error_summary` when it gave one. */
export class DropboxError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly summary = '',
  ) {
    super(message);
  }
}

// region PKCE

export function base64url(bytes: Uint8Array): string {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** RFC 7636: the challenge is the verifier's SHA-256, base64url-encoded without padding */
export async function challengeFor(verifier: string, browser: DropboxBrowser): Promise<string> {
  return base64url(new Uint8Array(await browser.sha256(verifier)));
}

// endregion

/**
 * The browser APIs this needs, behind an injectable seam - for the same reason as
 * `FolderStore`: Angular's test runner will not mock relative imports, and a test must
 * never really redirect the page or reach dropbox.com.
 */
@Injectable({ providedIn: 'root' })
export class DropboxBrowser {
  fetch(url: string, init: RequestInit): Promise<Response> {
    return fetch(url, init);
  }

  currentUrl(): string {
    return location.href;
  }

  /** leave for dropbox.com; the page is unloaded, so nothing after this runs */
  redirect(url: string): void {
    location.assign(url);
  }

  /** rewrite the address bar without reloading, so a used code is not left sitting there */
  replaceUrl(url: string): void {
    history.replaceState(history.state, '', url);
  }

  random(length: number): Uint8Array {
    return crypto.getRandomValues(new Uint8Array(length));
  }

  wait(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  sha256(text: string): Promise<ArrayBuffer> {
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  }

  /**
   * sessionStorage, not localStorage: the verifier is needed once, by this tab, on the way
   * back from dropbox.com, and should not outlive it.
   */
  getPending(): string {
    try {
      return sessionStorage.getItem(PENDING_KEY) ?? '';
    } catch {
      return '';
    }
  }

  setPending(value: string): void {
    try {
      sessionStorage.setItem(PENDING_KEY, value);
    } catch {
      // private window - the sign-in will fail on the way back and say so
    }
  }

  clearPending(): void {
    try {
      sessionStorage.removeItem(PENDING_KEY);
    } catch {
      // nothing to clean up
    }
  }

  load<T>(key: string): Promise<T | null> {
    return getValue<T>(key);
  }

  save(key: string, value: unknown): Promise<void> {
    return putValue(key, value);
  }

  remove(key: string): Promise<void> {
    return deleteValue(key);
  }
}

@Injectable({ providedIn: 'root' })
export class DropboxSession {
  private readonly browser = inject(DropboxBrowser);
  private readonly appKey = inject(DROPBOX_KEY);

  readonly status = signal<DropboxStatus>(this.appKey ? 'signed-out' : 'unconfigured');
  readonly account = signal<DropboxAccount | null>(null);
  /** the library: the app folder, the moment there is a session to reach it with */
  readonly folder = computed<DropboxFolder | null>(() =>
    this.status() === 'signed-in' ? APP_FOLDER : null,
  );
  readonly error = signal('');

  private refreshToken = '';
  private accessToken = '';
  private expiresAt = 0;
  /** one refresh at a time; calls that find a refresh under way wait for the same one */
  private refreshing: Promise<string> | null = null;

  /**
   * Called at startup. Finishes a sign-in if this load is the way back from dropbox.com,
   * otherwise picks up the session remembered from last time.
   */
  async restore(): Promise<void> {
    if (!this.appKey) return;

    if (this.browser.getPending()) {
      await this.completeSignIn();
      return;
    }

    const session = await this.browser.load<StoredSession>(SESSION_KEY);
    if (!session?.refreshToken) return;
    this.refreshToken = session.refreshToken;
    this.account.set(session.account);
    this.status.set('signed-in');
  }

  /** Leave for dropbox.com to sign in. The page comes back to `restore`. */
  async signIn(): Promise<void> {
    if (!this.appKey) return;
    this.error.set('');

    const verifier = base64url(this.browser.random(64));
    const state = base64url(this.browser.random(16));
    // the page's own address, stripped of any query - it has to match a redirect uri
    // registered in the app console exactly, and the query is where the answer comes back
    const here = new URL(this.browser.currentUrl());
    const redirectUri = here.origin + here.pathname;
    this.browser.setPending(JSON.stringify({ verifier, state, redirectUri } satisfies Pending));

    const url = new URL(AUTHORIZE_URL);
    url.search = new URLSearchParams({
      client_id: this.appKey,
      response_type: 'code',
      code_challenge: await challengeFor(verifier, this.browser),
      code_challenge_method: 'S256',
      // without this there is no refresh token, and the session ends in four hours
      token_access_type: 'offline',
      redirect_uri: redirectUri,
      state,
    }).toString();
    this.browser.redirect(url.toString());
  }

  /** Forget the session here and ask Dropbox to revoke it. */
  async signOut(): Promise<void> {
    if (this.refreshToken) {
      try {
        await this.call('auth/token/revoke');
      } catch {
        // revoking is a courtesy - the session is forgotten here either way
      }
    }
    await this.forgetSession();
  }

  /** everything signing out does, short of asking Dropbox to revoke */
  private async forgetSession(): Promise<void> {
    await this.browser.remove(SESSION_KEY);
    this.refreshToken = '';
    this.accessToken = '';
    this.expiresAt = 0;
    this.account.set(null);
    this.status.set(this.appKey ? 'signed-out' : 'unconfigured');
  }

  /** The session and folder for a run, or null when there is not both to hand over. */
  runStorage(): DropboxStorageRequest | null {
    const folder = this.folder();
    if (this.status() !== 'signed-in' || !this.refreshToken || !folder) return null;
    return {
      kind: 'dropbox',
      appKey: this.appKey,
      refreshToken: this.refreshToken,
      folderId: folder.id,
      folderPath: folder.path,
    };
  }

  // region the way back from dropbox.com

  private async completeSignIn(): Promise<void> {
    const pending = this.readPending();
    this.browser.clearPending();

    const url = new URL(this.browser.currentUrl());
    const params = url.searchParams;
    const code = params.get('code') ?? '';
    const state = params.get('state') ?? '';
    const denied = params.get('error') ?? '';
    const description = params.get('error_description') ?? '';

    // the code is single-use and the state is spent; neither should survive a reload or
    // end up in a bookmark
    for (const name of ['code', 'state', 'error', 'error_description']) params.delete(name);
    this.browser.replaceUrl(url.pathname + (params.toString() ? `?${params}` : '') + url.hash);

    if (denied) {
      this.error.set(
        denied === 'access_denied'
          ? 'Dropbox sign-in was cancelled.'
          : `Dropbox would not sign you in: ${description || denied}`,
      );
      return;
    }
    if (!pending || !code) return; // came back with nothing - left dropbox.com some other way
    if (state !== pending.state) {
      // not the sign-in this tab started, so the code is not one to trust
      this.error.set('That Dropbox sign-in did not come from this page. Please try again.');
      return;
    }

    this.status.set('signing-in');
    try {
      const tokens = await this.token({
        grant_type: 'authorization_code',
        code,
        code_verifier: pending.verifier,
        redirect_uri: pending.redirectUri,
      });
      if (!tokens.refresh_token) throw new DropboxError('Dropbox sent no refresh token.', 0);
      this.refreshToken = tokens.refresh_token;
      this.keepAccessToken(tokens);

      type Account = { account_id: string; email: string; name: { display_name: string } };
      const me = await this.call<Account>('users/get_current_account');
      const account = { id: me.account_id, name: me.name.display_name, email: me.email };
      this.account.set(account);
      await this.browser.save(SESSION_KEY, {
        refreshToken: this.refreshToken,
        account,
      } satisfies StoredSession);
      this.status.set('signed-in');
    } catch (error) {
      this.refreshToken = '';
      this.accessToken = '';
      this.account.set(null);
      this.status.set('signed-out');
      this.error.set(`Could not finish signing in to Dropbox. ${describe(error)}`);
    }
  }

  private readPending(): Pending | null {
    try {
      const pending = JSON.parse(this.browser.getPending()) as Pending;
      return pending?.verifier && pending?.state ? pending : null;
    } catch {
      return null;
    }
  }

  // endregion

  // region reading the library

  /**
   * Every file below `path`, in one recursive listing - a page per 2,000 entries rather
   * than a call per folder. A folder that is not there is an empty library, not an error.
   */
  async listFiles(path: string): Promise<DropboxFile[]> {
    type Entry = {
      '.tag': string;
      name: string;
      path_display: string;
      server_modified?: string;
    };
    type Page = { entries: Entry[]; cursor: string; has_more: boolean };

    const files: DropboxFile[] = [];
    let page: Page;
    try {
      page = await this.call<Page>('files/list_folder', { path, recursive: true, limit: 2000 });
    } catch (error) {
      if (error instanceof DropboxError && error.summary.startsWith('path/not_found')) return [];
      throw error;
    }
    for (;;) {
      for (const entry of page.entries) {
        if (entry['.tag'] !== 'file') continue;
        files.push({
          name: entry.name,
          path: entry.path_display,
          modified: Date.parse(entry.server_modified ?? '') || 0,
        });
      }
      if (!page.has_more) break;
      page = await this.call<Page>('files/list_folder/continue', { cursor: page.cursor });
    }
    return files;
  }

  /** The folders and files directly inside the app folder, by name. */
  async topLevel(): Promise<{ folders: string[]; files: string[] }> {
    type Entry = { '.tag': string; name: string };
    type Page = { entries: Entry[]; cursor: string; has_more: boolean };
    const folders: string[] = [];
    const files: string[] = [];
    let page = await this.call<Page>('files/list_folder', { path: '', recursive: false });
    for (;;) {
      for (const entry of page.entries) {
        if (entry['.tag'] === 'folder') folders.push(entry.name);
        else if (entry['.tag'] === 'file') files.push(entry.name);
      }
      if (!page.has_more) break;
      page = await this.call<Page>('files/list_folder/continue', { cursor: page.cursor });
    }
    return { folders, files };
  }

  /** Make a folder in the app folder. One already there is not an error. */
  async makeFolder(name: string): Promise<void> {
    try {
      await this.call('files/create_folder_v2', { path: `/${name}`, autorename: false });
    } catch (error) {
      if (error instanceof DropboxError && error.summary.startsWith('path/conflict')) return;
      throw error;
    }
  }

  /**
   * Move files from the app folder's top level into one of its folders.
   *
   * In batches, because Dropbox moves up to a thousand files per request and a library can
   * hold thousands of works - one request each would be slow and would run into Dropbox's
   * limit on writes. A batch runs as a job on Dropbox's side, asked after until it is done.
   * `autorename` is off, so a name already taken in the folder is refused and both files
   * are left as they were.
   */
  async moveInto(
    folder: string,
    names: string[],
    progress: (done: number) => void,
  ): Promise<{ moved: number; notMoved: string[] }> {
    type Entry = { '.tag': 'success' | 'failure' };
    type Answer = { '.tag': string; async_job_id?: string; entries?: Entry[] };

    let moved = 0;
    const notMoved: string[] = [];
    for (let start = 0; start < names.length; start += MOVE_BATCH_SIZE) {
      const batch = names.slice(start, start + MOVE_BATCH_SIZE);
      let answer = await this.call<Answer>('files/move_batch_v2', {
        entries: batch.map((name) => ({ from_path: `/${name}`, to_path: `/${folder}/${name}` })),
        autorename: false,
      });
      // the job id comes once, with the first answer; 'in_progress' answers do not repeat it
      const job = answer.async_job_id ?? '';
      while (answer['.tag'] === 'async_job_id' || answer['.tag'] === 'in_progress') {
        await this.browser.wait(MOVE_POLL_MS);
        answer = await this.call<Answer>('files/move_batch/check_v2', { async_job_id: job });
      }
      if (answer['.tag'] !== 'complete') {
        throw new DropboxError(`Dropbox could not move the files (${answer['.tag']}).`, 0);
      }
      (answer.entries ?? []).forEach((entry, i) => {
        if (entry['.tag'] === 'success') moved++;
        else notMoved.push(batch[i]);
      });
      progress(Math.min(start + batch.length, names.length));
    }
    return { moved, notMoved };
  }

  /** One file's contents. */
  async download(path: string): Promise<Blob> {
    return (await this.content('files/download', { path })).blob();
  }

  /**
   * A whole folder as one zip - how the index is read, since it is a file per fic and a
   * request each would be thousands of them. Dropbox refuses a folder of more than 10,000
   * entries or 20 GB; the caller falls back to reading files one at a time.
   */
  async downloadZip(path: string): Promise<ArrayBuffer> {
    return (await this.content('files/download_zip', { path })).arrayBuffer();
  }

  // endregion

  // region calls

  /**
   * One Dropbox RPC call. An expired access token is refreshed and the call tried once
   * more; anything else is thrown as a `DropboxError`.
   */
  private async call<T>(endpoint: string, args?: unknown): Promise<T> {
    const response = await this.send(API_URL + endpoint, (token) => {
      const init: RequestInit = { method: 'POST', headers: { Authorization: `Bearer ${token}` } };
      // endpoints that take no arguments want no body at all - not `null`, not `{}`
      if (args !== undefined) {
        init.headers = { ...init.headers, 'Content-Type': 'application/json' };
        init.body = JSON.stringify(args);
      }
      return init;
    });
    const text = await response.text();
    return (text ? JSON.parse(text) : null) as T;
  }

  /** A call to a content endpoint: the argument in a header, the file in the response body. */
  private content(endpoint: string, arg: unknown): Promise<Response> {
    return this.send(CONTENT_URL + endpoint, (token) => ({
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Dropbox-API-Arg': apiArg(arg) },
    }));
  }

  private async send(url: string, build: (token: string) => RequestInit): Promise<Response> {
    for (let attempt = 0; ; attempt++) {
      const token = await this.validAccessToken(attempt > 0);
      const response = await this.browser.fetch(url, build(token));
      if (response.status === 401 && attempt === 0) continue;
      if (response.ok) return response;
      throw await errorFrom(response);
    }
  }

  private async validAccessToken(force: boolean): Promise<string> {
    if (!force && this.accessToken && Date.now() < this.expiresAt - EXPIRY_MARGIN_MS) {
      return this.accessToken;
    }
    if (!this.refreshing) {
      this.refreshing = this.refresh().finally(() => (this.refreshing = null));
    }
    return this.refreshing;
  }

  private async refresh(): Promise<string> {
    if (!this.refreshToken) throw new DropboxError('Not signed in to Dropbox.', 401);
    try {
      const tokens = await this.token({
        grant_type: 'refresh_token',
        refresh_token: this.refreshToken,
      });
      this.keepAccessToken(tokens);
      return this.accessToken;
    } catch (error) {
      // a refused refresh token means the app was disconnected from the Dropbox side, and
      // no retry will change that - so the session goes, and the page says why
      if (error instanceof DropboxError && (error.status === 400 || error.status === 401)) {
        // not `signOut`: revoking would need an access token, which means waiting on this
        // very refresh
        await this.forgetSession();
        this.error.set('Dropbox access has ended - it may have been disconnected. Sign in again.');
      }
      throw error;
    }
  }

  private async token(fields: Record<string, string>): Promise<TokenResponse> {
    const response = await this.browser.fetch(TOKEN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ ...fields, client_id: this.appKey }).toString(),
    });
    if (!response.ok) throw await errorFrom(response);
    return (await response.json()) as TokenResponse;
  }

  private keepAccessToken(tokens: TokenResponse): void {
    this.accessToken = tokens.access_token;
    this.expiresAt = Date.now() + tokens.expires_in * 1000;
  }

  // endregion
}

interface TokenResponse {
  access_token: string;
  expires_in: number;
  refresh_token?: string;
}

async function errorFrom(response: Response): Promise<DropboxError> {
  let summary = '';
  let detail = '';
  try {
    const text = await response.text();
    try {
      const body = JSON.parse(text) as { error_summary?: string; error_description?: string; error?: unknown };
      summary = body.error_summary ?? (typeof body.error === 'string' ? body.error : '');
      detail = body.error_description ?? summary;
    } catch {
      detail = text;
    }
  } catch {
    // no body to read
  }
  if (response.status === 429) {
    const wait = response.headers.get('Retry-After');
    return new DropboxError(
      `Dropbox asked us to slow down${wait ? ` - try again in ${wait} seconds` : ''}.`,
      429,
      summary,
    );
  }
  return new DropboxError(detail || `Dropbox answered ${response.status}.`, response.status, summary);
}

/**
 * The `Dropbox-API-Arg` header for a content call. A header has to be plain ascii and fic
 * titles are anything but, so everything else goes as a `\uXXXX` escape, which Dropbox
 * reads back as json.
 */
export function apiArg(value: unknown): string {
  return JSON.stringify(value).replace(
    /[\u007f-￿]/g,
    (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'),
  );
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong.';
}
