# Hosting your own copy

This puts the app on the web for **one person**: the page on GitHub Pages, the helper on
Render's free plan. Everyone else should download the app and run it on their own computer,
which needs none of this.

A hosted copy is locked two ways:

- **A passcode.** The page opens with a window asking for it. The helper, not the page,
  checks it, then the browser remembers it. The helper refuses every request without it. The
  page it is published for gets `401`; anything else gets `404`, as if nothing were there.
- **An encrypted login.** The page encrypts your AO3 username and password with the helper's
  public key before sending them, so only the helper can read them. Each encrypted login
  expires after five minutes and can be used once.

Neither secret is ever written into anything that gets published. The passcode and the
private key live in GitHub secrets, and the workflow hands them straight to Render as
environment variables.

## What you end up with

| Piece | Where | Address |
| --- | --- | --- |
| The page | GitHub Pages, under `/app/` | `https://<you>.github.io/<repo>/app/` |
| The helper | Render web service, from a Docker image | `https://<service>.onrender.com` |
| The image | GitHub Container Registry | `ghcr.io/<you>/ao3downloader-helper` |

Your library still lives on your computer or in Dropbox, never on Render. The helper asks the
page to read and write every file, so the page has to stay open while a run is going, as it
always has.

## One-time setup

### 1. Make a key pair

On any computer with OpenSSL (Git for Windows includes it):

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out helper-private.pem
```

Use 4096 bits. RSA can only encrypt a small message, and 4096 bits leaves room for a password
of a few hundred characters (2048 bits, for only about a hundred). You never need
the public half separately, because the workflow derives it from this file.

**Keep `helper-private.pem` out of the repo.** Once it is in GitHub's secrets, delete the file.

### 2. Decide the helper's address

Pick a name for the Render service, e.g. `ao3-helper`. Its address will be
`https://ao3-helper.onrender.com`. If Render says the name is taken, it adds a suffix. Use
whatever address it actually gives you in the variable below.

### 3. Add the GitHub variables and secrets

In the repo: **Settings → Secrets and variables → Actions**.

**Variables** (not secret - they end up in the public page and image). **Every setting in
`settings.ini` has one**, named after the key in upper snake case, so the hosted
`settings.ini` is written entirely from here. Any you don't set keep the default shown:

| Variable | settings.ini key | Default | What it does |
| --- | --- | --- | --- |
| `HELPER_URL` | `HelperUrl` | **required** | the helper's address, exactly as Render shows it, e.g. `https://ao3-helper-latest.onrender.com` |
| `REQUIRE_PASSCODE` | `RequirePasscode` | `true` | leave it on; a hosted helper refuses to start without it |
| `PAGE_ORIGIN` | `PageOrigin` | `https://<owner>.github.io` | the page's address, with no path |
| `EXTRA_WAIT_TIME` | `ExtraWaitTime` | `15` | seconds to wait after every request to AO3 |
| `MAX_RETRIES` | `MaxRetries` | `30` | retries for a failed request; `0` retries for ever |
| `MAX_TIMEOUTS` | `MaxTimeouts` | `3` | timeouts in a row before giving up on a request; `0` turns the cutoff off |
| `FILE_NAME_LENGTH` | `FileNameLength` | `50` | longest file name before the title is shortened; `0` never shortens |
| `ENABLE_DEBUG_LOGGING` | `EnableDebugLogging` | `false` | more detail in the helper's log |
| `ENABLE_DEBUG_TOOLS` | `EnableDebugTools` | `false` | the debug panel and the single-pass runs in the page |
| `ENABLE_CONSOLE_LOGGING` | `EnableConsoleLogging` | `false` | print every request and every line a run says to Render's **Logs** tab |
| `PAUSED_RUN_TIMEOUT_MINUTES` | `PausedRunTimeoutMinutes` | `10` | minutes a paused background run is kept before it is abandoned; `0` never |

Numbers have to be whole numbers and switches `true` or `false`; anything else fails the
deploy, naming the variable. `SavePassword` is the one key left out: the page never stores
a password, so a hosted copy has no use for it. The deploy's log lists every value it wrote
and whether it came from a variable or a default.

A setting added to `settings.ini` in future gets a variable the same way, with no change to
the workflow.

**Secrets**:

| Name | Value |
| --- | --- |
| `AO3DOWNLOADER_PASSCODE` | the passcode you'll type into the page. Make it long; it is all that stands between the internet and your helper |
| `AO3DOWNLOADER_PRIVATE_KEY` | the whole of `helper-private.pem`, including the `BEGIN`/`END` lines |
| `RENDER_API_KEY` | from step 5 |
| `RENDER_SERVICE_ID` | from step 5 |
| `RENDER_DEPLOY_HOOK` | from step 5 |

The three `RENDER_` secrets can wait until step 5.

### 4. Turn on GitHub Pages, and publish the image once

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Actions → deploy hosted app → Run workflow.**

This first run builds the image and pushes it to `ghcr.io/<you>/ao3downloader-helper`. It
then **stops on purpose** at "check the render secrets are there", because Render can't be
pointed at an image that doesn't exist yet.

3. Make the image public so Render can pull it: on your GitHub profile, **Packages →
   ao3downloader-helper → Package settings → Change visibility → Public**. It contains
   nothing secret, only the code and a settings.ini built from the variables above. If
   you'd rather keep it private, give Render a registry credential instead (a GitHub token
   with `read:packages`).

### 5. Create the Render service

In Render: **New → Web Service → Existing image**.

- **Image URL**: `ghcr.io/<you>/ao3downloader-helper:latest`
- **Name**: the one you picked in step 2
- **Instance type**: Free
- Leave the port alone. The image listens on `10000`, Render's default.
- No environment variables needed here. The workflow sets `AO3DOWNLOADER_PASSCODE` and
  `AO3DOWNLOADER_PRIVATE_KEY` on every run.

Render starts the service at once, and **the first start fails**, saying no passcode is set.
That's expected: it refuses to run unprotected.

Then collect the three values for GitHub:

- `RENDER_SERVICE_ID`: in the service's URL on the dashboard, the part starting `srv-`.
- `RENDER_DEPLOY_HOOK`: **Settings → Deploy Hook**, the whole URL.
- `RENDER_API_KEY`: **Account Settings → API Keys → Create API Key**.

**Keep it to one instance.** Runs are held in the helper's memory, so a second instance
would receive half of a run's requests and know nothing about it. The free plan only ever
runs one.

### 6. Run the workflow again

**Actions → deploy hosted app → Run workflow.** This time it:

1. writes settings.ini and the page's `app-config.json` from your variables, refusing anything
   that could not work (a plain `http://` helper, no passcode, no key)
2. builds and pushes the image
3. sets the passcode and private key on Render
4. deploys that exact image to Render
5. builds the page and publishes it under `/app/`, with the site's root sending visitors
   there

Open `https://<you>.github.io/<repo>/app/`, type the passcode, and you're in.

### 7. Dropbox (only if you use it)

Dropbox only signs in from addresses it has been told about. In the
[Dropbox App Console](https://www.dropbox.com/developers/apps), open the app named in
`gui_source/src/app/dropbox-config.ts` and add the page's exact address to **OAuth 2 →
Redirect URIs**, e.g. `https://alexandria-p.github.io/ao3downloader/app/`.

## Deploying changes

Run **deploy hosted app** again. The helper is always deployed before the page, so a new page
never goes out ahead of the helper it expects.

To **change the passcode or the key**, update the secret and run the workflow. Each browser
that saved the old passcode is asked for the new one the next time it talks to the helper.
A new key needs the page rebuilt too, which the same run does.

The same run also builds the **Windows app** and publishes it on the `windows-app` release
(the `windows` job, which calls **build windows app**). It runs alongside the hosted deploy
and has nothing to do with it - the app runs its own helper on the computer it is started on.
Its settings.ini is written from the same variables, except `HELPER_URL`, `REQUIRE_PASSCODE`
and `PAGE_ORIGIN`, which it ignores: it always points at its own helper, and the build fails
rather than ship a file naming your hosted one.

## Things to know

- **Background runs keep the helper awake - unless paused.** A free Render service is
  stopped after about 15 minutes without a request from outside, and a run with the page
  closed has nothing talking to it. So while a background run is going, the helper requests
  its own address (`RENDER_EXTERNAL_URL`, which Render sets) every 10 minutes. A **paused**
  run does not: it is waiting for you, and after `PAUSED_RUN_TIMEOUT_MINUTES` (10 by default)
  the helper abandons it - it ends keeping everything it saved, and can be resumed from
  History. Keep that timeout under Render's 15 minutes, or Render may end the run first (it
  then shows as interrupted, still resumable).
- **Deploying ends a background run.** The helper holds runs in memory, so a new version
  starting means the old run is gone. Wait for a background run to finish before running
  **deploy hosted app**; if you don't, it shows in History as interrupted, and starting it
  again carries on from what is still missing.

- **A free Render service sleeps** after about 15 minutes without requests, and takes up to a
  minute to wake. If the passcode window says it couldn't reach the helper, wait and try
  again. A run in progress should keep it awake, since the page holds an event stream open
  to it the whole time and the helper writes to it every ten seconds - but that has not been
  tested on Render itself.
- **The page must be opened over https.** Browsers only let https pages encrypt, so the
  GitHub Pages address works and a plain `http://` copy of the page can't send a login.
- **The helper's own disk is wiped on every restart and redeploy.** That costs nothing that
  matters: your library and run history live in your folder or Dropbox, not on Render. What
  is lost is the helper's request log (a debugging trail nothing reads back) and any
  `ignorelist.txt`, which a hosted helper doesn't have.
- **AO3 sees Render's address, not yours.** AO3 limits by IP, and a datacenter IP may be
  limited sooner than a home connection. `ExtraWaitTime` is your pacing knob, same as ever.
- **The page's code is public**, as it always was: the repo is open source. The passcode
  protects what matters, which is the helper, your AO3 login and your runs.
- **Only the published page gets `401`.** The distinction comes from the browser's `Origin`
  header, which anything outside a browser can fake, so all it reveals is that something is
  there. It never lets anything through.
