## How it fits together

- **The page** (`gui_source/`, Angular) - owns the library. It reads and writes your folder or Dropbox, and shows everything.
- **The helper** (`powershell_source/ao3_download_helper/source_code/server.py`, Python) - talks to AO3. A page can't: AO3 sends no CORS headers, and the page can't hold a login. It runs on `127.0.0.1:4400`, and reaches the library only by asking the page.

`CLAUDE.md` in the repository explains every design decision and the bugs behind them. Read it before changing anything load-bearing.

## Run it

```powershell
# helper on 4400 + ng serve on 4200, with hot reload for the page
powershell.exe -ExecutionPolicy Bypass -File .\run_development_build.ps1
```

Python changes need the helper restarted. Settings for this build are in `powershell_source/settings.ini`.

## Test it

```bash
cd powershell_source/ao3_download_helper && uv run --no-sync pytest -q
cd gui_source && npm test        # not npx vitest
```

CI (`.github/workflows/test.yml`) runs both on every push.

## Build it

| What | Command | Output |
| --- | --- | --- |
| Bundle (needs uv to run) | `generate_build_artifacts.ps1` | `build/` - your `build/config/settings.ini` survives rebuilds |
| Windows/Mac app | `uv sync --group package` then `uv run --no-sync python package_app.py` | `dist/*.zip` - built for the system and chip it runs on |

The **build windows app** and **build mac app** workflows build and smoke-test the apps on every pull request that touches them. **deploy hosted app** publishes them as a release.

## Rules worth knowing

- **Only one helper at a time.** A stale helper on 4400 answers a new page with old code - the usual cause of "half-working" features.
- **`settings.ini` is only ever added to.** Every key the code reads must be in the template, or it gets commented out as deprecated in every install.
- **Nothing is half-written.** A run pauses only before a request or between chunks of a download held in memory, never mid-save.
- **A file's name carries its version.** The work number leads, the AO3 update date trails, and nothing else decides "outdated".
- **Keep `TERMINOLOGY.md` current** with every change to a workflow, option or step.

## Known weak spots

`TECH_DEBT.md` lists them:

- `from_collections` only ever grows.
- Older libraries can hold two index files for one work.
- A collection or series with one work added and one removed looks unchanged.
