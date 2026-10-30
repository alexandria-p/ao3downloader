/**
 * The app's feedback form, turned into a GitHub issue - on Cloudflare Workers.
 *
 * The page cannot open an issue itself: that needs a GitHub token, and anything built into a
 * page anyone can download is public. So the page posts the form here, and this - which holds
 * the token as a Worker secret - opens the issue, labelled `feedback` and `positive` or
 * `negative`, and answers with its address. The person never leaves the page or signs up for
 * anything. FEEDBACK.md (repository root) is the setup.
 *
 * It is deliberately not the Render helper: that one holds an ao3 login and answers its owner
 * alone, behind a passcode. This answers anyone, and can do nothing but file feedback.
 *
 * What keeps it from being a spam cannon:
 * - **Turnstile**, Cloudflare's bot check, on every submission. The page shows the widget; its
 *   token is checked with Cloudflare here before anything else, and a token works once.
 * - **The page's origin.** Only the origins in ALLOWED_ORIGINS (the hosted page, and
 *   localhost for the apps) get an answer a browser will let a page read.
 * - **Sizes.** Every field is capped, so nobody can post a novel.
 *
 * Environment (wrangler.toml and Worker secrets):
 *   GITHUB_REPO       owner/name the issues are opened in             (var)
 *   ALLOWED_ORIGINS   comma-separated origins the page is served from (var)
 *   GITHUB_TOKEN      fine-grained token: Issues read and write, that repository only (secret)
 *   TURNSTILE_SECRET  the Turnstile widget's secret key                (secret)
 */

export const LIMITS = { message: 5000, name: 100, log: 60000, version: 40, copy: 60, browser: 300 };
export const SENTIMENTS = ['positive', 'negative'];
const SITEVERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const GITHUB_API = 'https://api.github.com';

/** the origins allowed to read this Worker's answers, from ALLOWED_ORIGINS */
export function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || '')
    .split(',')
    .map((origin) => origin.trim().replace(/\/+$/, ''))
    .filter(Boolean);
}

function cors(origin, env) {
  const headers = { Vary: 'Origin' };
  if (origin && allowedOrigins(env).includes(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS';
    headers['Access-Control-Allow-Headers'] = 'Content-Type';
    headers['Access-Control-Max-Age'] = '86400';
  }
  return headers;
}

function answer(status, body, origin, env) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...cors(origin, env) },
  });
}

/**
 * A second pass over the log, here, for anything that looks like a password. The page removes
 * the ao3 username before sending - only it knows the name - and no run ever prints a password,
 * so this is a backstop and not the main rule.
 */
export function scrubPasswords(text) {
  return String(text).replace(/(password["']?\s*[:=]\s*)("[^"]*"|'[^']*'|\S+)/gi, '$1[removed]');
}

/** Read and check the form. Returns `{ form }` or `{ error }`. */
export function readForm(raw) {
  if (!raw || typeof raw !== 'object') return { error: 'the form did not arrive' };
  const text = (value) => (typeof value === 'string' ? value.trim() : '');
  const sentiment = text(raw.sentiment).toLowerCase();
  if (!SENTIMENTS.includes(sentiment)) return { error: 'choose positive or negative' };
  const message = text(raw.message);
  if (!message) return { error: 'the message is empty' };
  if (message.length > LIMITS.message) {
    return { error: `the message is longer than ${LIMITS.message} characters` };
  }
  const name = text(raw.name);
  if (name.length > LIMITS.name) return { error: `the name is longer than ${LIMITS.name} characters` };
  // a log is kept to its end - whatever went wrong is at the end - and never refused for length
  let log = typeof raw.log === 'string' ? raw.log : '';
  if (log.length > LIMITS.log) log = log.slice(-LIMITS.log);
  return {
    form: {
      sentiment,
      message,
      name,
      log: scrubPasswords(log),
      version: text(raw.version).slice(0, LIMITS.version),
      copy: text(raw.copy).slice(0, LIMITS.copy),
      browser: text(raw.browser).slice(0, LIMITS.browser),
      token: text(raw.turnstileToken),
    },
  };
}

/** A fence the log cannot close early: longer than any run of backticks inside it. */
function fence(text) {
  const longest = Math.max(2, ...(String(text).match(/`+/g) || []).map((run) => run.length));
  return '`'.repeat(longest + 1);
}

/** The issue's title, labels and body. */
export function issueFor(form) {
  const firstLine = form.message.split('\n')[0].trim();
  const short = firstLine.length > 60 ? `${firstLine.slice(0, 57)}...` : firstLine;
  const lines = [
    `**${form.sentiment === 'positive' ? 'Positive' : 'Negative'} feedback**, sent from the app.`,
    '',
    form.message,
    '',
    '---',
    `- **From:** ${form.name || '(no name given)'}`,
    `- **Version:** ${form.version || '(built on their own computer)'}`,
  ];
  if (form.copy) lines.push(`- **Copy:** ${form.copy}`);
  if (form.browser) lines.push(`- **Browser:** ${form.browser}`);
  if (form.log) {
    const mark = fence(form.log);
    lines.push(
      '',
      '<details><summary>Latest run log (AO3 username removed)</summary>',
      '',
      mark,
      form.log.replace(/\s+$/, ''),
      mark,
      '',
      '</details>',
    );
  }
  return {
    title: `Feedback (${form.sentiment}): ${short}`,
    labels: ['feedback', form.sentiment],
    body: lines.join('\n'),
  };
}

async function passesTurnstile(token, request, env, fetcher) {
  if (!token) return false;
  const data = new FormData();
  data.append('secret', env.TURNSTILE_SECRET || '');
  data.append('response', token);
  const ip = request.headers.get('CF-Connecting-IP');
  if (ip) data.append('remoteip', ip);
  try {
    const response = await fetcher(SITEVERIFY, { method: 'POST', body: data });
    const result = await response.json();
    return result && result.success === true;
  } catch {
    return false;
  }
}

async function openIssue(issue, env, fetcher) {
  const response = await fetcher(`${GITHUB_API}/repos/${env.GITHUB_REPO}/issues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'ao3downloader-feedback',
      'X-GitHub-Api-Version': '2022-11-28',
    },
    body: JSON.stringify(issue),
  });
  if (!response.ok) throw new Error(`GitHub answered ${response.status}`);
  const made = await response.json();
  return { number: made.number, url: made.html_url };
}

/** The whole Worker, with `fetch` passed in so the tests can stand in for Cloudflare and GitHub. */
export async function handle(request, env, fetcher = fetch) {
  const origin = (request.headers.get('Origin') || '').replace(/\/+$/, '');
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: cors(origin, env) });
  }
  if (request.method !== 'POST') return answer(405, { error: 'send the form with POST' }, origin, env);
  // a browser always says where the page came from; anything else did not come from the app
  if (!allowedOrigins(env).includes(origin)) {
    return answer(403, { error: 'this page may not send feedback here' }, origin, env);
  }

  let raw;
  try {
    raw = await request.json();
  } catch {
    return answer(400, { error: 'the form did not arrive' }, origin, env);
  }
  const { form, error } = readForm(raw);
  if (error) return answer(400, { error }, origin, env);

  if (!(await passesTurnstile(form.token, request, env, fetcher))) {
    return answer(403, { error: 'the bot check did not pass - try again' }, origin, env);
  }

  try {
    const made = await openIssue(issueFor(form), env, fetcher);
    return answer(201, { ok: true, ...made }, origin, env);
  } catch {
    return answer(502, { error: 'GitHub did not take it - try again in a minute' }, origin, env);
  }
}

export default {
  fetch: (request, env) => handle(request, env),
};
