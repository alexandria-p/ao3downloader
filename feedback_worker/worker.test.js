// The feedback Worker, with Cloudflare's bot check and GitHub stood in for - nothing here
// reaches either. Run with `node --test` from this folder (CI does, in the tests workflow).

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { LIMITS, handle, issueFor, readForm, scrubPasswords } from './worker.js';

const ENV = {
  GITHUB_REPO: 'someone/ao3downloader',
  ALLOWED_ORIGINS: 'https://someone.github.io, http://localhost:4200',
  GITHUB_TOKEN: 'a-token',
  TURNSTILE_SECRET: 'a-secret',
};

const FORM = {
  sentiment: 'positive',
  message: 'The quick scan is great.\nThank you!',
  name: 'Reader',
  log: 'logging in\nnew download: 1 A.html',
  version: '1.0.2',
  copy: 'Windows app',
  storage: 'Dropbox',
  browser: 'Chrome 140',
  turnstileToken: 'token-1',
};

/** Cloudflare's siteverify and GitHub's issues endpoint, answering as told, noting each call */
function services({ human = true, github = 201 } = {}) {
  const calls = [];
  const fetcher = async (url, init) => {
    calls.push({ url: String(url), init });
    if (String(url).includes('siteverify')) {
      return new Response(JSON.stringify({ success: human }));
    }
    if (github >= 400) return new Response('{}', { status: github });
    return new Response(JSON.stringify({ number: 12, html_url: 'https://github.com/someone/ao3downloader/issues/12' }),
      { status: 201 });
  };
  return { calls, fetcher };
}

function post(body, origin = 'https://someone.github.io', method = 'POST') {
  return new Request('https://feedback.example.workers.dev/', {
    method,
    headers: { Origin: origin, 'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.5' },
    body: method === 'POST' ? JSON.stringify(body) : undefined,
  });
}

describe('sending feedback', () => {
  it('opens a labelled issue and answers with where it is', async () => {
    const { calls, fetcher } = services();
    const response = await handle(post(FORM), ENV, fetcher);

    assert.equal(response.status, 201);
    assert.deepEqual(await response.json(),
      { ok: true, number: 12, url: 'https://github.com/someone/ao3downloader/issues/12' });
    const issue = calls.find((c) => c.url.endsWith('/repos/someone/ao3downloader/issues'));
    const sent = JSON.parse(issue.init.body);
    assert.deepEqual(sent.labels, ['feedback', 'positive']);
    assert.equal(sent.title, 'Feedback (positive): The quick scan is great.');
    assert.equal(issue.init.headers.Authorization, 'Bearer a-token');
    // where the library lives - the kind, never a folder's name
    assert.match(sent.body, /- \*\*Library:\*\* Dropbox/);
  });

  it('lets the page that sent it read the answer', async () => {
    const { fetcher } = services();
    const response = await handle(post(FORM, 'http://localhost:4200'), ENV, fetcher);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:4200');
  });

  it('answers a browser asking first, for an allowed page only', async () => {
    const allowed = await handle(post(null, 'https://someone.github.io', 'OPTIONS'), ENV);
    assert.equal(allowed.status, 204);
    assert.equal(allowed.headers.get('Access-Control-Allow-Methods'), 'POST, OPTIONS');
    const other = await handle(post(null, 'https://elsewhere.example', 'OPTIONS'), ENV);
    assert.equal(other.headers.get('Access-Control-Allow-Origin'), null);
  });

  it('refuses a page it does not know, before asking anyone anything', async () => {
    const { calls, fetcher } = services();
    const response = await handle(post(FORM, 'https://elsewhere.example'), ENV, fetcher);
    assert.equal(response.status, 403);
    assert.equal(calls.length, 0);
  });

  it('opens no issue when the bot check fails, and checks it with the secret and address', async () => {
    const { calls, fetcher } = services({ human: false });
    const response = await handle(post(FORM), ENV, fetcher);

    assert.equal(response.status, 403);
    assert.equal(calls.length, 1);
    const asked = calls[0].init.body;
    assert.equal(asked.get('secret'), 'a-secret');
    assert.equal(asked.get('response'), 'token-1');
    assert.equal(asked.get('remoteip'), '203.0.113.5');
  });

  it('opens no issue without a bot check token at all', async () => {
    const { calls, fetcher } = services();
    const response = await handle(post({ ...FORM, turnstileToken: '' }), ENV, fetcher);
    assert.equal(response.status, 403);
    assert.equal(calls.length, 0);
  });

  it('says so when GitHub will not take it', async () => {
    const { fetcher } = services({ github: 403 });
    const response = await handle(post(FORM), ENV, fetcher);
    assert.equal(response.status, 502);
    assert.match((await response.json()).error, /GitHub/);
  });

  it('takes the form only by POST', async () => {
    const response = await handle(post(null, 'https://someone.github.io', 'GET'), ENV);
    assert.equal(response.status, 405);
  });
});

describe('the form', () => {
  it('needs a sentiment and a message, and nothing else', () => {
    assert.match(readForm({ ...FORM, sentiment: 'meh' }).error, /positive or negative/);
    assert.match(readForm({ ...FORM, message: '   ' }).error, /empty/);
    const { form } = readForm({ sentiment: 'Negative', message: 'It crashed' });
    assert.equal(form.sentiment, 'negative');
    assert.equal(form.name, '');
    assert.equal(form.log, '');
  });

  it('refuses a message or name over the limit, and keeps a long log to its end', () => {
    assert.match(readForm({ ...FORM, message: 'x'.repeat(LIMITS.message + 1) }).error, /longer/);
    assert.match(readForm({ ...FORM, name: 'x'.repeat(LIMITS.name + 1) }).error, /longer/);
    const log = 'start\n' + 'x'.repeat(LIMITS.log) + '\nthe end';
    const { form } = readForm({ ...FORM, log });
    assert.equal(form.log.length, LIMITS.log);
    assert.ok(form.log.endsWith('the end'));
  });

  it('takes out anything in the log that looks like a password', () => {
    assert.equal(scrubPasswords('password=hunter2 and Password: "two words"'),
      'password=[removed] and Password: [removed]');
    assert.equal(readForm({ ...FORM, log: '{"password": "x"}' }).form.log, '{"password": [removed]}');
  });
});

describe('the issue', () => {
  it('says what was sent, by whom, from which version, with the log folded away', () => {
    const issue = issueFor(readForm(FORM).form);
    assert.match(issue.body, /\*\*Positive feedback\*\*/);
    assert.match(issue.body, /The quick scan is great\.\nThank you!/);
    assert.match(issue.body, /\*\*From:\*\* Reader/);
    assert.match(issue.body, /\*\*Version:\*\* 1\.0\.2/);
    assert.match(issue.body, /<details><summary>Latest run log/);
    assert.match(issue.body, /new download: 1 A\.html/);
  });

  it('says no name was given rather than leaving a blank', () => {
    const issue = issueFor(readForm({ sentiment: 'negative', message: 'Hm' }).form);
    assert.match(issue.body, /\(no name given\)/);
    assert.doesNotMatch(issue.body, /<details>/);
  });

  it('shortens a long first line in the title', () => {
    const issue = issueFor(readForm({ ...FORM, message: 'a'.repeat(100) }).form);
    assert.equal(issue.title, `Feedback (positive): ${'a'.repeat(57)}...`);
  });

  it('fences the log so backticks in it cannot break out of the block', () => {
    const issue = issueFor(readForm({ ...FORM, log: 'a ``` b ````' }).form);
    assert.match(issue.body, /\n`````\na ``` b ````\n`````\n/);
  });
});
