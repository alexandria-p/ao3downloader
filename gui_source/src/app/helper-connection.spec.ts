import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PAGE_CONFIG, HelperConnection, drainEvents, readPageConfig } from './helper-connection';
import { Jobs } from './jobs';

const HOSTED = 'https://helper.example.com';

function hosted(publicKey = '', requirePasscode = true): HelperConnection {
  const helper = new HelperConnection();
  helper.settings.set({ helperUrl: HOSTED, requirePasscode, publicKey });
  return helper;
}

function answering(status: number, body: object = {}) {
  const fetching = vi.fn(async (_url: unknown, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetching);
  return fetching;
}

function sentHeaders(fetching: ReturnType<typeof answering>, call = 0): Headers {
  return new Headers(fetching.mock.calls[call][1]?.headers);
}

async function keyPair(): Promise<{ pem: string; privateKey: CryptoKey }> {
  const pair = await crypto.subtle.generateKey(
    { name: 'RSA-OAEP', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' },
    true,
    ['encrypt', 'decrypt'],
  );
  const spki = new Uint8Array(await crypto.subtle.exportKey('spki', pair.publicKey));
  const base64 = btoa(String.fromCharCode(...spki));
  const pem = `-----BEGIN PUBLIC KEY-----\n${base64.match(/.{1,64}/g)!.join('\n')}\n-----END PUBLIC KEY-----`;
  return { pem, privateKey: pair.privateKey };
}

async function open(credentials: string, privateKey: CryptoKey): Promise<Record<string, unknown>> {
  const sealed = Uint8Array.from(atob(credentials), (c) => c.charCodeAt(0));
  const plain = await crypto.subtle.decrypt({ name: 'RSA-OAEP' }, privateKey, sealed);
  return JSON.parse(new TextDecoder().decode(plain));
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('readPageConfig', () => {
  it('keeps the defaults for anything missing or of the wrong type', () => {
    expect(readPageConfig(null)).toEqual(DEFAULT_PAGE_CONFIG);
    expect(readPageConfig({ helperUrl: 4, requirePasscode: 'yes', publicKey: [] })).toEqual(
      DEFAULT_PAGE_CONFIG,
    );
  });

  it('drops a trailing slash, since every path is added to it with its own', () => {
    expect(readPageConfig({ helperUrl: `${HOSTED}/` }).helperUrl).toBe(HOSTED);
  });

  it('asks for the passcode only when told to in so many words', () => {
    // anything but true is off, so a typo cannot lock someone out of their own page
    expect(readPageConfig({ requirePasscode: 'true' }).requirePasscode).toBe(false);
    expect(readPageConfig({ requirePasscode: true }).requirePasscode).toBe(true);
  });
});

describe('HelperConnection.loadPageConfig', () => {
  it('wants the passcode at once on a copy that needs one and has none saved', async () => {
    answering(200, { helperUrl: HOSTED, requirePasscode: true });
    const helper = new HelperConnection();

    await helper.loadPageConfig();

    expect(helper.url('/api/config')).toBe(`${HOSTED}/api/config`);
    expect(helper.passcodeWanted()).toBe(true);
  });

  it('does not ask when this browser already holds one', async () => {
    localStorage.setItem('ao3.helperPasscode', 'saved');
    answering(200, { helperUrl: HOSTED, requirePasscode: true });
    const helper = new HelperConnection();

    await helper.loadPageConfig();

    expect(helper.passcodeWanted()).toBe(false);
  });

  it('never asks on a copy that needs no passcode', async () => {
    answering(200, { requirePasscode: false });
    const helper = new HelperConnection();

    await helper.loadPageConfig();

    expect(helper.passcodeWanted()).toBe(false);
  });

  it('falls back to the helper on this computer when there is no config file', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));
    const helper = new HelperConnection();

    await helper.loadPageConfig();

    expect(helper.settings()).toEqual(DEFAULT_PAGE_CONFIG);
  });

  it('falls back when a dev server answers with the page instead of the file', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<!doctype html>', { status: 200 })));
    const helper = new HelperConnection();

    await helper.loadPageConfig();

    expect(helper.settings()).toEqual(DEFAULT_PAGE_CONFIG);
  });
});

describe('HelperConnection.call', () => {
  it('sends the saved passcode as a bearer token', async () => {
    const fetching = answering(200);
    const helper = hosted();
    helper.passcode.set('secret');

    await helper.call('/api/jobs');

    expect(fetching.mock.calls[0][0]).toBe(`${HOSTED}/api/jobs`);
    expect(sentHeaders(fetching).get('Authorization')).toBe('Bearer secret');
  });

  it('keeps the headers a caller set alongside it', async () => {
    const fetching = answering(200);
    const helper = hosted();
    helper.passcode.set('secret');

    await helper.call('/api/jobs', { headers: { 'Content-Type': 'application/json' } });

    expect(sentHeaders(fetching).get('Content-Type')).toBe('application/json');
  });

  it('sends no Authorization header at all without a passcode', async () => {
    const fetching = answering(200);

    await new HelperConnection().call('/api/config');

    expect(sentHeaders(fetching).has('Authorization')).toBe(false);
  });

  it('puts the passcode window up whenever the helper answers 401', async () => {
    // a passcode changed on the helper after this browser saved the old one
    answering(401, { passcode: true });
    const helper = hosted('', false);
    helper.passcode.set('old');

    await helper.call('/api/config');

    expect(helper.passcodeWanted()).toBe(true);
  });
});

describe('HelperConnection.tryPasscode', () => {
  it('saves a passcode the helper accepts, and stops asking', async () => {
    const fetching = answering(200, { ok: true });
    const helper = hosted();
    helper.passcodeWanted.set(true);

    expect(await helper.tryPasscode('right')).toBe('accepted');

    expect(fetching.mock.calls[0][0]).toBe(`${HOSTED}/api/auth`);
    expect(sentHeaders(fetching).get('Authorization')).toBe('Bearer right');
    expect(localStorage.getItem('ao3.helperPasscode')).toBe('right');
    expect(helper.passcodeWanted()).toBe(false);
  });

  it('keeps nothing the helper refuses', async () => {
    answering(401);
    const helper = hosted();
    helper.passcodeWanted.set(true);

    expect(await helper.tryPasscode('wrong')).toBe('refused');

    expect(localStorage.getItem('ao3.helperPasscode')).toBeNull();
    expect(helper.passcodeWanted()).toBe(true);
  });

  it('says so when the helper cannot be reached at all', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    }));

    expect(await hosted().tryPasscode('anything')).toBe('unreachable');
  });

  it('asks again once the saved one is forgotten', () => {
    localStorage.setItem('ao3.helperPasscode', 'saved');
    const helper = hosted();

    helper.forgetPasscode();

    expect(localStorage.getItem('ao3.helperPasscode')).toBeNull();
    expect(helper.passcodeWanted()).toBe(true);
  });
});

describe('HelperConnection.sealLogin', () => {
  it('sends the login as it is to a helper with no key', async () => {
    expect(await new HelperConnection().sealLogin('Someone', 'pw')).toEqual({
      username: 'Someone',
      password: 'pw',
    });
  });

  it('seals the login so only the private key can open it, with a time and a nonce', async () => {
    const { pem, privateKey } = await keyPair();
    const before = Date.now();

    const login = await hosted(pem).sealLogin('Someone', 'pw');

    expect('password' in login).toBe(false);
    expect(JSON.stringify(login)).not.toContain('pw');
    const opened = await open((login as { credentials: string }).credentials, privateKey);
    expect(opened['username']).toBe('Someone');
    expect(opened['password']).toBe('pw');
    expect(opened['sent']).toBeGreaterThanOrEqual(before);
    expect(typeof opened['nonce']).toBe('string');
  });

  it('never seals two logins the same way, so one cannot pass for another', async () => {
    const { pem, privateKey } = await keyPair();
    const helper = hosted(pem);

    const first = (await helper.sealLogin('a', 'b')) as { credentials: string };
    const second = (await helper.sealLogin('a', 'b')) as { credentials: string };

    expect((await open(first.credentials, privateKey))['nonce']).not.toBe(
      (await open(second.credentials, privateKey))['nonce'],
    );
  });

  it('accepts a key pasted with escaped newlines', async () => {
    const { pem } = await keyPair();
    const login = await hosted(pem.replace(/\n/g, '\\n')).sealLogin('a', 'b');
    expect('credentials' in login).toBe(true);
  });

  it('explains that a page not on https cannot encrypt, rather than failing blankly', async () => {
    // browsers only offer crypto.subtle to a secure page
    const { pem } = await keyPair();
    vi.stubGlobal('crypto', {});
    await expect(hosted(pem).sealLogin('a', 'b')).rejects.toThrow(/https/);
  });

  it('explains a login too long for the key rather than failing blankly', async () => {
    const { pem } = await keyPair();
    await expect(hosted(pem).sealLogin('a', 'x'.repeat(400))).rejects.toThrow(/too long/);
  });
});

describe('Jobs and the page', () => {
  it('share one connection, so a 401 from any run request brings the passcode window up', async () => {
    answering(401, { passcode: true });
    const jobs = TestBed.inject(Jobs);

    await jobs.activeJobs();

    expect(TestBed.inject(HelperConnection).passcodeWanted()).toBe(true);
  });
});

describe('Jobs.start', () => {
  it('sends the sealed login and never the password', async () => {
    const { pem } = await keyPair();
    const fetching = answering(202, { jobId: 'job-1' });

    const jobId = await new Jobs(hosted(pem)).start({
      action: 'sync',
      filetypes: ['JSON'],
      options: {} as never,
      username: 'Someone',
      password: 'a-password',
    });

    expect(jobId).toBe('job-1');
    const body = JSON.parse(String(fetching.mock.calls[0][1]?.body));
    expect(body.password).toBeUndefined();
    expect(body.username).toBeUndefined();
    expect(typeof body.credentials).toBe('string');
    expect(body.action).toBe('sync');
  });

  it('sends it as it always has to the helper on this computer', async () => {
    const fetching = answering(202, { jobId: 'job-1' });

    await new Jobs().start({
      action: 'sync', filetypes: ['JSON'], options: {} as never, username: 'Someone', password: 'pw',
    });

    const body = JSON.parse(String(fetching.mock.calls[0][1]?.body));
    expect(body).toMatchObject({ username: 'Someone', password: 'pw' });
    expect(fetching.mock.calls[0][0]).toBe('http://127.0.0.1:4400/api/jobs');
  });
});

describe('drainEvents', () => {
  it('hands on each complete event and keeps the one still arriving', () => {
    const got: string[] = [];
    const rest = drainEvents('data: {"a":1}\n\ndata: {"b":2}\n\ndata: {"c"', (d) => got.push(d));
    expect(got).toEqual(['{"a":1}', '{"b":2}']);
    expect(rest).toBe('data: {"c"');
  });

  it('passes over the heartbeat, which is a comment', () => {
    const got: string[] = [];
    drainEvents(': still here\n\ndata: x\n\n', (d) => got.push(d));
    expect(got).toEqual(['x']);
  });
});

describe('HelperConnection.stream', () => {
  function streaming(chunks: string[]) {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
    const fetching = vi.fn(async (_url: unknown, _init?: RequestInit) => new Response(body));
    vi.stubGlobal('fetch', fetching);
    return fetching;
  }

  it('reads events split across chunks, then says once that the stream ended', async () => {
    streaming(['data: {"type":"lo', 'g"}\n', '\ndata: {"type":"done"}\n\n']);
    const got: string[] = [];
    const ended = vi.fn();

    await new Promise<void>((resolve) => {
      new HelperConnection().stream('/api/jobs/1/events', (d) => got.push(d), () => {
        ended();
        resolve();
      });
    });

    expect(got).toEqual(['{"type":"log"}', '{"type":"done"}']);
    expect(ended).toHaveBeenCalledOnce();
  });

  it('carries the passcode, which EventSource could not', async () => {
    const fetching = streaming([]);
    const helper = hosted();
    helper.passcode.set('secret');

    await new Promise<void>((resolve) => helper.stream('/api/jobs/1/events', () => {}, resolve));

    expect(sentHeaders(fetching).get('Authorization')).toBe('Bearer secret');
  });

  it('does not report an end the caller asked for itself', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: unknown, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      })));
    const ended = vi.fn();

    const close = new HelperConnection().stream('/api/jobs/1/events', () => {}, ended);
    close();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(ended).not.toHaveBeenCalled();
  });
});
