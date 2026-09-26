# Deploying the web page to GitHub Pages

**Status: plan. The code changes in step 1 have not been made yet.** Once they are, the
rest of this file is the standing instructions.

## What gets deployed, and what does not

GitHub Pages serves static files, so only the **Angular page** (`gui_source/`) goes there.
The **helper** (`source_code/server.py`) cannot: it holds your ao3 login, talks to ao3
(which sends no CORS headers, so a page cannot) and writes to your downloads folder. It
keeps running on your own machine, exactly as now.

```
https://alexandria-p.github.io/ao3downloader/   <- the page, from GitHub Pages
        |
        |  fetch http://127.0.0.1:4400/api/...   (from your browser, to your own machine)
        v
the helper, running locally                     <- started by you, same as today
        |
        v
archiveofourown.org, and your downloads folder
```

So the Pages URL replaces `http://localhost:4200` - the second window the launcher opens -
and nothing else. This is consistent with the rule in `CLAUDE.md` about not hosting an api:
nothing but static files is hosted. Browsing a library you have already downloaded works
with no helper at all; the download buttons need the helper running.

## 1. Code changes needed before the first deploy

| # | Change | Where | Why |
|---|---|---|---|
| 1 | Build with `--base-href /ao3downloader/` | the workflow (not `index.html`) | a project page lives under `/<repo>/`; with `<base href="/">` every script 404s. Keeping it a build flag leaves the local build unchanged |
| 2 | Let the helper answer the Pages origin | `Handler.cors` in `server.py` | today it reflects only `http://localhost:*` / `http://127.0.0.1:*`, so the browser blocks every response to the Pages page |
| 3 | Make that origin a setting | `settings.ini`: `AllowedOrigins=https://alexandria-p.github.io` | a fork or a custom domain should not need a code change. Exact-match only, never a prefix test |
| 4 | Answer the local-network preflight | `do_OPTIONS`: `Access-Control-Allow-Private-Network: true` when the request asks | Chromium browsers send this when a public https page calls a loopback address; without the header some versions refuse the call |
| 5 | A "helper only" launch | `Start-Application.ps1 -HelperOnly` | the launcher currently also starts the page server on 4200, which is not needed when the page comes from Pages |
| 6 | Add the Pages URL to the Dropbox app | Dropbox App Console (not code) | Dropbox refuses a sign-in whose return address is not registered - see step 3 |
| 7 | Replace `.github/workflows/site.yml` | new `deploy-pages.yml` | a repo has one Pages site. `site.yml` is upstream's, builds a `./site` folder that this fork does not have, and would overwrite the app if anyone ran it |
| 8 | Docs | `build/README.md` caveat (generated from `build_artifacts.py`), root `README.md`, `CLAUDE.md`, `TERMINOLOGY.md` | both READMEs must stay in step; the "deploying to a server" caveat needs to say the Pages setup is the supported one |

Tests to add with #2-#4: an allowed origin is reflected, a similar-looking one
(`https://alexandria-p.github.io.evil.example`) is not, and the private-network header is
sent only when asked for.

### Why the origin allowlist is safe, and its one limit

The helper can start downloads under your ao3 login, so which pages may call it matters.
An origin is scheme + host only - **every repo you publish on Pages shares
`https://alexandria-p.github.io`**. That is fine while they are all yours; do not add an
origin you do not control.

### The workflow (`.github/workflows/deploy-pages.yml`)

```yaml
name: deploy web page

on:
  push:
    branches: [main]
    paths: ['gui_source/**', '.github/workflows/deploy-pages.yml']
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

# one deploy at a time; a newer push replaces a queued one but never cancels a live deploy
concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: gui_source
    steps:
      - uses: actions/checkout@v6
      - uses: actions/setup-node@v5
        with:
          node-version: 24
          cache: npm
          cache-dependency-path: gui_source/package-lock.json
      - run: npm ci
      - run: npx ng test --watch=false
      - run: npx ng build --base-href /${{ github.event.repository.name }}/
      - uses: actions/upload-pages-artifact@v4
        with:
          path: gui_source/dist/ao3-bookmarks/browser

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

The tests run before the build, so a failing test means nothing is deployed and the
previous version stays up.

## 2. One-time GitHub setup

1. **Settings -> Pages -> Build and deployment -> Source: GitHub Actions.** (Not "Deploy
   from a branch".) This is the only switch that has to be flipped by hand.
2. **Settings -> Environments -> `github-pages`** is created on the first deploy. By default
   it only accepts deploys from `main`; leave that as is.
3. The repo must be **public** for Pages on a free plan.

## 3. Secrets and settings

**The deploy needs no secrets.** Everything it uses is either automatic or public:

| Thing | Kind | Where it lives | To change it |
|---|---|---|---|
| `GITHUB_TOKEN` / OIDC token for `deploy-pages` | automatic | issued per run by GitHub, from the `permissions:` block | nothing to do |
| Dropbox app key | **public**, not a secret | `gui_source/src/app/dropbox-config.ts` | edit the file and push; PKCE means there is no client secret. Never put the Dropbox app *secret* anywhere in this repo |
| Dropbox redirect URI | Dropbox app setting | Dropbox App Console -> your app -> Settings -> OAuth 2 -> Redirect URIs | add `https://alexandria-p.github.io/ao3downloader/` (trailing slash included). Keep `http://localhost:4200/` for local use |
| Allowed origin for the helper | local setting | `AllowedOrigins` in the `settings.ini` your helper reads (`build/config/settings.ini` for a build) | edit the file, restart the helper |
| `AO3_USERNAME` / `AO3_PASSWORD` | Actions secrets | Settings -> Secrets and variables -> Actions | only used by upstream's `validate-fixtures.yml`, **not** by the deploy. Never needed for Pages |

Your ao3 password never goes near GitHub: it is typed into the page and sent only to the
helper on your own machine.

To add or rotate a secret if one is ever needed: **Settings -> Secrets and variables ->
Actions -> New repository secret** (or the pencil icon to update). A secret is read in a
workflow as `${{ secrets.NAME }}`; changing it takes effect on the next run, no redeploy
of anything else needed.

## 4. Triggering a deployment

- **Automatically:** push (or merge a PR) to `main` that touches anything under
  `gui_source/`. Changes to the python helper alone do not redeploy - the page does not
  contain it.
- **By hand:** **Actions -> deploy web page -> Run workflow -> Branch: main -> Run
  workflow**. Or from a terminal:

```bash
gh workflow run deploy-pages.yml --ref main
```

- **Watch it:**

```bash
gh run watch
```

The URL is shown on the run's `deploy` job and under Settings -> Pages. A deploy takes a
minute or two; the browser may cache the old `index.html` briefly, so hard-refresh
(Ctrl+Shift+R) if a change does not appear. The built files are content-hashed, so a stale
mix of old and new cannot happen.

- **Roll back:** revert the commit on `main` and push; that redeploys the older page.

The Claude GitHub app is not involved in deploying - it is for `@claude` in issues and PRs.
You can ask it for a change, and merging its PR to `main` is what triggers the deploy.

## 5. Using it day to day

1. Start the helper on your machine: `.\Start-Application.ps1 -HelperOnly` in a build
   folder (or `uv run python -m source_code.server` from the helper folder).
2. Open `https://alexandria-p.github.io/ao3downloader/` in **Chrome or Edge**.
3. The first time, the browser asks whether the site may connect to devices/apps on your
   local network or this device. **Allow** it - that is the page reaching your helper.
4. Choose your downloads folder again (or sign in to Dropbox again). Both are remembered
   per site, so the Pages site does not share them with `localhost:4200`.

**Browser support:** Chrome and Edge. Firefox cannot open a local folder from a page (no
File System Access API), and Safari blocks an https page from calling `http://127.0.0.1`.
This is the same limit the local build already has, apart from Safari.

## 6. Troubleshooting

| Symptom | Likely cause |
|---|---|
| Blank page, 404s for `main-*.js` in the console | built without `--base-href /ao3downloader/` |
| Page loads, every download button fails, console says CORS | helper not updated to allow the origin, or `AllowedOrigins` not set in the settings.ini it actually reads |
| Same, but console says blocked by local/private network | the permission prompt was declined - site settings (padlock) -> allow local network access |
| Features half-work, new endpoints 404 | an **old helper** still running on 4400 - see `CLAUDE.md`, "Only one helper may run at a time". A new page from Pages talking to an old local helper is the same trap as a rebuild |
| Dropbox sign-in says redirect URI mismatch | the Pages URL (with trailing slash) is not in the Dropbox app's Redirect URIs |
| Deploy job fails with "Pages not enabled" / 404 | Settings -> Pages source is not set to GitHub Actions |

## Other workflows in `.github/workflows`

These came from upstream and assume its layout (`test/` and `dev/` at the repo root), which
this fork does not have:

- `readme.yml` runs on **every push** and calls `dev/readme.py` - it will fail every time.
- `test.yml` runs `pytest test/` from the root; the tests live in
  `powershell_source/ao3_download_helper/test/`.
- `publish.yml`, `validate-fixtures.yml` call `dev/*` scripts that do not exist here.

None of them block a Pages deploy, but they will show red crosses on every commit. Worth
fixing or deleting separately.
