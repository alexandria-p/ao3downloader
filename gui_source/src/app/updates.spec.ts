import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { DEFAULT_PAGE_CONFIG, HelperConnection, readPageConfig } from './helper-connection';
import { DISMISSED_KEY, UpdateCheck, isNewer } from './updates';

function page(version: string, releasesRepo = 'someone/ao3downloader'): HelperConnection {
  const helper = new HelperConnection();
  helper.settings.set({ ...DEFAULT_PAGE_CONFIG, version, releasesRepo });
  return helper;
}

function latestIs(tag: string, status = 200) {
  return vi.fn(async (_url: string, _init?: RequestInit) =>
    new Response(
      JSON.stringify({ tag_name: tag, html_url: `https://github.com/someone/ao3downloader/releases/tag/${tag}` }),
      { status },
    ),
  );
}

function checking(version: string, fetcher: ReturnType<typeof latestIs>): UpdateCheck {
  const updates = new UpdateCheck(page(version));
  updates.fetcher = fetcher;
  return updates;
}

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe('isNewer', () => {
  it('compares number by number, not as text', () => {
    expect(isNewer('1.10.0', '1.9.0')).toBe(true);
    expect(isNewer('1.8.3', '1.8.2')).toBe(true);
    expect(isNewer('2.0.0', '1.99.99')).toBe(true);
  });

  it('is never newer when the same or older', () => {
    expect(isNewer('1.8.2', '1.8.2')).toBe(false);
    expect(isNewer('1.8.1', '1.8.2')).toBe(false);
  });

  it('is never newer when either cannot be read', () => {
    expect(isNewer('latest', '1.0.0')).toBe(false);
    expect(isNewer('1.1.0', '')).toBe(false);
  });
});

describe('UpdateCheck', () => {
  it('asks for the latest release of the repository the page was built from', async () => {
    const fetcher = latestIs('v1.8.2');
    await checking('1.8.2', fetcher).check();

    expect(fetcher.mock.calls[0][0]).toBe('https://api.github.com/repos/someone/ao3downloader/releases/latest');
  });

  it('says so when a later release is out, with where to get it', async () => {
    const updates = checking('1.8.2', latestIs('v1.8.3'));
    await updates.check();

    expect(updates.newer()).toEqual({
      version: '1.8.3',
      url: 'https://github.com/someone/ao3downloader/releases/tag/v1.8.3',
    });
  });

  it('says nothing when this page is the latest', async () => {
    const updates = checking('2.0.0', latestIs('v2.0.0'));
    await updates.check();

    expect(updates.newer()).toBeNull();
  });

  it('never asks for a page built with no version', async () => {
    // a bundle built on this computer is whatever its builder made it - nothing to compare
    const fetcher = latestIs('v9.9.9');
    const updates = checking('', fetcher);
    await updates.check();

    expect(fetcher).not.toHaveBeenCalled();
    expect(updates.newer()).toBeNull();
  });

  it('still checks once the banner is dismissed, for the footer', async () => {
    const first = checking('1.0.0', latestIs('v1.0.1'));
    await first.check();
    first.dismiss();

    // the banner is told to go for good; what was found is still known
    expect(first.dismissed()).toBe(true);
    expect(localStorage.getItem(DISMISSED_KEY)).toBe('true');
    expect(first.newer()?.version).toBe('1.0.1');

    const fetcher = latestIs('v1.0.2');
    const later = checking('1.0.0', fetcher);
    await later.check();
    expect(later.dismissed()).toBe(true);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(later.newer()?.version).toBe('1.0.2');
  });

  it('knows it is the latest only once GitHub has answered', async () => {
    const answered = checking('1.0.0', latestIs('v1.0.0'));
    await answered.check();
    expect(answered.checked()).toBe(true);

    const offline = checking('1.0.0', latestIs('v1.0.0', 500));
    await offline.check();
    expect(offline.checked()).toBe(false);
  });

  it('treats anything going wrong as nothing newer', async () => {
    const failing = checking('1.0.0', latestIs('v2.0.0', 403));
    await failing.check();
    expect(failing.newer()).toBeNull();

    const offline = new UpdateCheck(page('1.0.0'));
    offline.fetcher = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    await expect(offline.check()).resolves.toBeUndefined();
    expect(offline.newer()).toBeNull();
  });

  it('links the latest release whatever it is called', () => {
    expect(new UpdateCheck(page('1.0.0')).latestUrl()).toBe(
      'https://github.com/someone/ao3downloader/releases/latest',
    );
  });
});

describe('updating the Windows app from the page', () => {
  function json(status: number, body: object): Response {
    return new Response(JSON.stringify(body), { status });
  }

  /** a helper that answers each request with the next of `answers` - an Error for none at all */
  function helperAnswering(answers: (Response | Error)[]) {
    const asked: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      asked.push(url);
      const next = answers.shift() ?? json(200, { app: { version: '1.8.2', updatable: true } });
      if (next instanceof Error) throw next;
      return next;
    }));
    const updates = new UpdateCheck(page('1.8.2'));
    updates.pollMs = 0;
    updates.waitMs = 5_000;
    updates.reload = vi.fn();
    return { updates, asked };
  }

  afterEach(() => vi.unstubAllGlobals());

  it('only offers to for a helper that is the Windows app', () => {
    const updates = new UpdateCheck(page('1.8.2'));
    updates.appStatus(undefined);
    expect(updates.canUpdate()).toBe(false);
    updates.appStatus({ version: '1.8.2', updatable: true });
    expect(updates.canUpdate()).toBe(true);
  });

  it('waits out the app closing, and reloads once it is back as the new version', async () => {
    const { updates, asked } = helperAnswering([
      json(202, { version: '1.8.3' }),
      new TypeError('Failed to fetch'),
      new TypeError('Failed to fetch'),
      json(200, { app: { version: '1.8.3', updatable: true } }),
    ]);

    await updates.updateNow();

    expect(asked[0]).toBe('http://127.0.0.1:4400/api/update');
    expect(updates.reload).toHaveBeenCalledOnce();
  });

  it('says why when the app will not update', async () => {
    const { updates } = helperAnswering([
      json(409, { error: 'A run is in progress. Updating restarts the app, which would stop it - update once it is complete.' }),
    ]);

    await updates.updateNow();

    expect(updates.updating()).toEqual({
      state: 'failed',
      error: 'A run is in progress. Updating restarts the app, which would stop it - update once it is complete.',
    });
    expect(updates.reload).not.toHaveBeenCalled();
  });

  it('says so when the app comes back as the version it was', async () => {
    // the swap failed and the app put its old files back
    const { updates } = helperAnswering([
      json(202, { version: '1.8.3' }),
      new TypeError('Failed to fetch'),
      json(200, { app: { version: '1.8.2', updatable: true, update: { state: 'failed', error: 'the file is in use' } } }),
    ]);

    await updates.updateNow();

    expect(updates.updating()).toEqual({ state: 'failed', error: 'the file is in use' });
    expect(updates.reload).not.toHaveBeenCalled();
  });

  it('gives up waiting in the end, saying what to do', async () => {
    const { updates } = helperAnswering([json(202, { version: '1.8.3' })]);
    updates.waitMs = 0;

    await updates.updateNow();

    expect(updates.updating().state).toBe('failed');
  });

  it('shows a failure the app reports once, until it has been read', () => {
    const failed = { version: '1.8.2', updatable: true, update: { state: 'failed', error: 'disk full' } };
    const first = new UpdateCheck(page('1.8.2'));
    first.appStatus(failed);
    expect(first.updating()).toEqual({ state: 'failed', error: 'disk full' });

    first.acknowledgeFailure();
    expect(first.updating()).toEqual({ state: 'idle' });

    const later = new UpdateCheck(page('1.8.2'));
    later.appStatus(failed);
    expect(later.updating()).toEqual({ state: 'idle' });
  });
});

describe('the version in the page config', () => {
  it('is read when it is three numbers', () => {
    expect(readPageConfig({ version: '1.8.3' }).version).toBe('1.8.3');
  });

  it('is nothing when it is anything else', () => {
    expect(readPageConfig({ version: 'v1.8' }).version).toBe('');
    expect(readPageConfig({ version: 3 }).version).toBe('');
    expect(readPageConfig({}).version).toBe('');
  });

  it('keeps the default repository unless given one that looks like owner/name', () => {
    expect(readPageConfig({ releasesRepo: 'fork/ao3downloader' }).releasesRepo).toBe('fork/ao3downloader');
    expect(readPageConfig({ releasesRepo: 'https://evil.example' }).releasesRepo).toBe(
      DEFAULT_PAGE_CONFIG.releasesRepo,
    );
  });
});
