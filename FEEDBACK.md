# Feedback from inside the app

Every copy of the app built by the deploy has a **Feedback** tab on the right edge of the page.
That covers the hosted page and the Windows, Mac and Linux apps people download. Clicking it
opens a short form. Sending the form opens a GitHub issue in this repository, labelled
`feedback` and either `positive` or `negative`. Nobody leaves the page, and nobody needs a
GitHub account or anything else.

This document covers how a submission travels, and how to set up the Cloudflare side once.

## How a submission gets to GitHub

```
the page  --POST-->  feedback Worker (Cloudflare)  --checks-->  Turnstile
                              |
                              +--POST /repos/<repo>/issues-->  GitHub  -->  issue #N
```

1. **The form.** It asks for:
   - positive or negative (required);
   - a message (required);
   - a name (optional);
   - whether to attach the log of the latest run (optional).

   There is no email field. The issue is public, so an address would be published to anyone.
2. **The bot check.** Cloudflare's Turnstile widget sits in the form and usually passes on
   its own, with nothing to click. It gives the page a one-use token.
3. **The log, if ticked.** It is the newest run record's log in the library that is open
   (`runs/*.json`, newest by name).
   - Before it is shown or sent, every AO3 username the page knows is replaced with
     `[your AO3 username]`, in any letter case. The page knows the one in the run record,
     the helper's saved one, and the one this browser remembers.
   - Anything shaped like `password=...` is taken out as well. No run prints a password, so
     this is only a backstop.
   - **See exactly what will be sent** shows the result before it goes.
4. **The page sends it to the feedback Worker, never to the helper.** The hosted copy's
   Render helper holds an AO3 login and answers one person; it is not asked to do this. The
   page sends:
   - the form;
   - the token;
   - the page's version;
   - whether it is the hosted page or a copy on someone's computer;
   - the browser's user agent.
5. **The Worker** (`feedback_worker/worker.js`):
   - refuses a page whose origin is not in `ALLOWED_ORIGINS`;
   - checks the form and caps every field;
   - checks the token with Cloudflare;
   - only then opens the issue with its own GitHub token, and answers with the issue's
     number and address.
6. **The page says where it went:**
   - a link to the new issue, which exists the moment the page is told;
   - a link to the [list of feedback](https://github.com/alexandria-p/ao3downloader/issues?q=label%3Afeedback).
     GitHub's list can take up to a minute to show a new issue, and the page says so.
   - **If anything fails**, the page says *Uh oh - we couldn't submit your feedback* and why.
     Failures include Cloudflare refusing the request, GitHub refusing the issue, being
     offline, no answer within 30 seconds, or the bot check not loading. The page then:
     - keeps what was typed, and gets a fresh bot check for another try;
     - offers **Download what I wrote**, a text file with the message, name, version and any
       attached log, so nothing is lost;
     - links **Submit it on GitHub instead**, which opens GitHub's new-issue page in a new tab
       with the title and message filled in. That way needs a GitHub account. The log is not
       filled in, because browsers cap how long an address can be.

The issue's title is `Feedback (positive|negative): <first line of the message>`. Its body
holds:

- the message;
- the name, version, which copy it came from and the browser;
- the log, if attached, folded away under **Latest run log**.

### Which copies show the tab

Only a page whose `app-config.json` has both of these:

- `feedbackUrl`: the Worker's https address;
- `turnstileSiteKey`: the widget's site key, which is public by design.

The deploy writes both from two repository **variables**, `FEEDBACK_URL` and
`TURNSTILE_SITE_KEY`:

- the hosted page through `deploy_config.py page-config`;
- the apps through `package_app.py`, which reads the same two from its environment.

Rules:

- Set both or neither. One without the other fails the build, and so does a URL that is not
  https.
- With neither set there is no tab. That is also what a bundle built on your own computer
  gets.
- They are not in `settings.ini`. That file is the user's own and is only ever added to.

### What keeps it from being a spam cannon

- **Turnstile on every submission.** This is the real gate. A token works once, and the
  Worker checks it with Cloudflare's secret before anything reaches GitHub.
- **The origin allowlist.** Only the hosted page (`https://alexandria-p.github.io`) and the
  apps' `http://localhost:4200` get an answer a browser lets them read. A script outside a
  browser can fake an origin, so this keeps out other websites, not determined people. The
  bot check stops those.
- **Caps on every field.** Message: 5,000 characters. Name: 100. Log: the last 60,000.
- **A token that can do nothing else.** The Worker's GitHub token is fine-grained: Issues
  read and write, on this one repository. If it leaked, all it could do is file and edit
  issues here.
- **Cloudflare's free limits** are 100,000 Worker requests a day, and Turnstile is free.
  Feedback will never come near either.

## Setting it up (once)

You need a free Cloudflare account. No domain is needed: the Worker lives on `workers.dev`.

### 1. A workers.dev address

1. Sign in at [dash.cloudflare.com](https://dash.cloudflare.com).
2. Open **Workers & Pages**.
3. The first time, Cloudflare asks you to choose a `workers.dev` subdomain, e.g. `alexandria`.

The Worker will then be at:

```
https://ao3downloader-feedback.<your-subdomain>.workers.dev
```

The first part is the `name` in `feedback_worker/wrangler.toml`.

### 2. Your account ID

On the **Workers & Pages** overview (or your account's home page), copy the **Account ID**.
It is in the right-hand column, or under the account's **...** menu as **Copy account ID**.

### 3. An API token for deploying

1. Open **My Profile → API Tokens → Create Token**.
2. Use the **Edit Cloudflare Workers** template.
3. Limit it to your own account. The zone can be left as **All zones**, since nothing here
   uses one.
4. Copy the token. Cloudflare shows it once.

### 4. A Turnstile widget

1. Open **Turnstile** (search for it with the dashboard's search box if the sidebar does not
   show it), then **Add widget**.
2. **Name:** `ao3downloader feedback`.
3. **Hostnames:** add both of these:
   - `alexandria-p.github.io`, the hosted page;
   - `localhost`, the Windows, Mac and Linux apps, which serve the page on
     `http://localhost:4200`.
4. **Widget mode:** **Managed**.
5. Create it, then copy the **Site Key** (public) and the **Secret Key** (secret).

> Cloudflare warns against putting `localhost` on a production widget. It means anyone can
> use the widget from a page on their own computer. Here that is the point: the apps are
> pages on people's own computers. It costs nothing, because each submission still has to
> pass the check, and the Worker accepts `http://localhost:4200` anyway. Leave `localhost`
> off and the tab works on the hosted page only.

### 5. A GitHub token for opening issues

1. On GitHub, open **Settings → Developer settings → Personal access tokens → Fine-grained
   tokens → Generate new token**.
2. **Repository access:** **Only select repositories**, then `alexandria-p/ao3downloader`.
3. **Permissions:** under **Repository permissions**, set **Issues** to **Read and write**.
   Nothing else; *Metadata: read* is added by itself.
4. **Expiration:** your choice. When it expires, submissions fail with *GitHub did not take
   it*. Make a new token, update the secret below, and run the deploy again. A calendar
   reminder helps.

### 6. The repository's secrets and variables

In the repository, open **Settings → Secrets and variables → Actions**.

**Secrets:**

| Name | Value |
| --- | --- |
| `CLOUDFLARE_API_TOKEN` | the token from step 3 |
| `CLOUDFLARE_ACCOUNT_ID` | the account ID from step 2 |
| `TURNSTILE_SECRET_KEY` | the widget's **Secret Key** from step 4 |
| `FEEDBACK_GITHUB_TOKEN` | the token from step 5 |

**Variables:**

| Name | Value |
| --- | --- |
| `FEEDBACK_URL` | `https://ao3downloader-feedback.<your-subdomain>.workers.dev` |
| `TURNSTILE_SITE_KEY` | the widget's **Site Key** from step 4 |

### 7. Deploy

Run **Actions → build & deploy hosted app and github releases → Run workflow**, or push to
`main`. The **deploy the feedback service to cloudflare** job then does three things:

1. It makes the `feedback`, `positive` and `negative` labels, if they are not there. The
   Worker's token only writes issues, and GitHub drops a label that does not exist rather
   than creating it.
2. It deploys `feedback_worker/` with `wrangler deploy`.
3. It hands the Worker its two secrets, `GITHUB_TOKEN` and `TURNSTILE_SECRET`, straight from
   the repository's secrets through stdin. They never land in a file, the page or the image.

The same run builds the hosted page and the apps with `FEEDBACK_URL` and
`TURNSTILE_SITE_KEY`, so they get the tab. Apps already downloaded get it with their next
update.

Until the four secrets are set, the job skips itself and prints a notice naming the missing
ones. Nothing else in the deploy waits on it.

## Changing it

- **The issues go to a different repository, or the page lives somewhere else:** edit
  `GITHUB_REPO` and `ALLOWED_ORIGINS` in `feedback_worker/wrangler.toml`. Also add the
  page's host to the Turnstile widget's hostnames, and give the GitHub token access to the
  other repository.
- **Turn it off:** delete the `FEEDBACK_URL` and `TURNSTILE_SITE_KEY` variables. The next
  build has no tab. The Worker can stay or be deleted in the dashboard.
- **Tests:** `cd feedback_worker && npm test` runs the Worker's tests on Node's own test
  runner, with Cloudflare and GitHub stood in for. Nothing to install. CI runs them on every
  pull request.
- **Watching it:** **Workers & Pages → ao3downloader-feedback → Logs** in the Cloudflare
  dashboard shows each request. Turnstile's page shows how many checks passed and failed.
