# CLAUDE.md

Notes for anyone (human or AI) picking this repo up. The README explains what the program
does for a *user*; this explains how it is put together and why, and the things that have
already cost someone a day.

## What this fork adds

Upstream ao3downloader is a console program. This fork adds:

1. **A `JSON` download type** - metadata for every work on a listing, one json file per
   work, with a version history inside each file.
2. **An Angular web UI** (`gui_source/`) that reads a downloads folder in the browser and
   lists what is in it - bookmarks and collections - and can start downloads.
3. **A local helper** (`source_code/server.py`) that the page talks to, because a page
   cannot do the work itself.
4. **Collection indexing** - one json file per collection, recording what it contains.
5. **A bundler** (`generate_build_artifacts.ps1`) producing a self-contained `build/`.

## Layout

```
gui_source/                       Angular 22 app (standalone components, signals)
run_development_build.ps1         dev launcher: helper + ng serve
generate_build_artifacts.ps1      produces build/
powershell_source/
  run-locally.ps1                 console launcher
  settings.ini, data.json         the config the DEV build uses
  logs/, downloads/
  ao3_download_helper/
    source_code/                  the python package (imported as `source_code`)
    test/                         pytest suite
    build_artifacts.py            the bundler itself
    test_build_artifacts.py       its tests (next to it, not in test/)
    pyproject.toml, uv.lock, .venv/
build/                            generated; config/settings.ini is NOT overwritten
```

`build/` is generated but `build/config/settings.ini` and `build/downloads/` are
deliberately preserved across rebuilds - never delete them to "clean up".

## Running things

```bash
# dev: helper on 4400 + ng serve on 4200
powershell.exe -ExecutionPolicy Bypass -File ./run_development_build.ps1

# python tests (run from the helper folder)
cd powershell_source/ao3_download_helper && uv run --no-sync pytest -q

# gui tests - use npm test, NOT npx vitest (the Angular builder does the test setup)
cd gui_source && npm test

# bundle
powershell.exe -ExecutionPolicy Bypass -File ./generate_build_artifacts.ps1
```

**4 tests in `test/test_ao3.py::test_proceed_*` fail with `UnicodeDecodeError`.** They are
pre-existing, present on the unmodified upstream code, and caused by fixtures being read
with the platform default codec (cp1252 on Windows). Do not chase them; do not count them
as regressions. Current: **627 python passed, 4 failed; 114 gui passed.**

On a corporate network that intercepts TLS, add `--system-certs` to `uv sync`.

## Architecture, and why

### The local helper exists because a page cannot replace it

Ao3 sends no CORS headers, so a browser page cannot read it - this was verified with a live
`fetch`, which fails with `TypeError: Failed to fetch`. A page also cannot hold an ao3
login session or read ebook files off disk for the update scan. So the page talks to a
python helper on `127.0.0.1:4400`, which calls exactly the same code the console menu calls.

The user's constraint was originally "client-side only"; the helper was accepted only once
CORS was demonstrated to make that impossible. Don't reintroduce a hosted API - the design
is deliberately local-only, and `build/README.md` explains why deploying it to a server
gives you a broken page.

### Only one helper may run at a time

`serve()` calls `already_listening()` - a TCP **connect** probe - before binding, and exits
with an explanation if something answers. Do not replace this with "just try to bind and
catch the error": on Windows `SO_REUSEADDR` (which `HTTPServer` enables by default) lets a
second process bind a port another is already listening on. Both "start", and which one
answers a request is undefined.

The symptom is vicious and was hit for real: an old helper from an earlier session answers
the new page, using *its* settings.ini and *its* code, which looks exactly like the new
build ignoring its own config. **If you see "unknown action", or settings that seem not to
apply, suspect a stale helper on 4400 first** - `netstat -ano | findstr :4400`.

Turning `SO_REUSEADDR` off was tried and rejected: it also makes the port unbindable for
minutes after a normal shutdown while closed connections sit in `TIME_WAIT`, so stopping
and restarting the app would fail for no reason. Probing separates "a helper is there" from
"the OS still remembers the port".

### Indexing runs before downloading

`server.run_bookmarks` indexes every bookmark to json first, then downloads works. This is
a user requirement, not an implementation detail. It also means a stopped run still leaves
a complete index.

### Rate limiting

Ao3 limits on **how fast** requests arrive, not the total. The cost model:

| Work | Requests |
| --- | --- |
| Indexing (JSON) | 1 per listing page = 1 per **20 works** |
| Each other file type | 1 for the work page + 1 per format, **per work** |
| A collection's works | 1 per 20 works in it |

So JSON is essentially free and everything else is not. `ExtraWaitTime` in settings.ini is
the pacing knob (seconds after every request); `0` trips the limit almost immediately.
`FORCED_FILETYPES` is `[JSON]` only - HTML is in `DEFAULT_FILETYPES`, so it starts ticked
but can be turned off, which makes a metadata-only run possible. Don't re-lock HTML.

Collections skip their works crawl when the profile page's count matches the stored one
(`Ao3.unchanged_items`), turning hundreds of requests into two. It cannot detect one work
added and another removed; delete the collection's json to force a full crawl.

### Stopping must unwind, not just stop waiting

`Repository.wait` **raises `CancelledException`** rather than returning quietly. This was a
real bug: the rate-limit pause used to end early on cancel, then the loop went straight
back to the same request and earned another break of the same length, forever. Every sleep
in the request path (`extra_wait`, retry backoff, the 429 pause) goes through `wait`, and
there is a cancel check at the top of the request loop. When `cancelled is None` (the
console, which has no stop button) `wait` does one plain sleep - some tests depend on that.

### Versioned json

`indexing.py` splits a document into identity (never versioned) and snapshot. `merge`
appends to `indexes` only when the snapshot actually changed, and always updates
`last_indexed`. Two identity sets: `IDENTITY_FIELDS` for works, `COLLECTION_IDENTITY_FIELDS`
for collections. `position` is identity, not history - a fic sliding down the bookmarks
list is not a change to the fic.

### Pairing downloaded files to metadata

A file is matched to its index entry by the work id **at the start of the file name**,
followed by a separator: `/^(\d+)(?:[\s_.\-]|$)/`. `99 Red Balloons.html` is work 99;
`99Red Balloons.html` is not a work number at all. This rule is in `bookmarks.ts`
(`workIdFromFilename`) and documented in both READMEs. A bookmark record's `id` field is
the **work number**, which is what makes collections (which store only work numbers) join
onto the index.

### Bookmarks vs collections are told apart by shape

`Library.readRecords` routes json by `isCollectionRecord`, not by folder. A folder read
through the File System Access API arrives **flat** - the paths are gone. Both kinds carry
an `indexes` history, so without the shape check collections render as bookmarks.

### The works listing is one component

`work-list.ts` is the whole bookmarks table, reused unchanged for the works inside a
collection. If you touch blurb rendering, both places change - that is intentional.

## Gotchas already paid for

- **PowerShell 5.1**: no `&&`, no ternary, no `??`. `Start-Process -ArgumentList` does
  **not** quote arguments, so an absolute path with spaces splits - `run_development_build.ps1`
  passes a *relative* `--project` for exactly this reason. This repo's path contains spaces.
- **Bash heredocs mangle backslashes and quotes** on this setup. Use the Write/Edit tools
  for file content rather than `cat <<EOF`.
- **beautifulsoup**: ao3 never closes the first `<dt>` on a collection profile, so the rest
  nest inside it - pair `dt`/`dd` by document order via `find_next`, not siblings. And bs4
  counts an html `Comment` as a `NavigableString`, which silently corrupted `active_since`
  until filtered.
- **hatchling** cannot reference packages outside its project root, and `sources` remapping
  breaks editable installs. This is why the python lives where it does.
- **`importlib.resources.open_text`** takes a resource *name*, not a path - passing
  `self.inifile` breaks the moment a config folder is set.
- **Angular's test runner rejects `vi.mock` on relative imports.** Injectable seams
  (`FolderStore`) are how the tests stand in for browser APIs, which don't exist in jsdom.
- **`<!--CHECK-->value<!--CONSTANT_NAME-->` markers** in `README.md` tie hardcoded strings
  to `strings.py` constants. Nothing validates them any more; keep them accurate by hand.
  They must not contain `{}`.

## Conventions

- Comments say **why**, not what. Several in here exist to stop a "simplification" that
  would reintroduce a fixed bug - `allow_reuse_address`, the cancel-raises behaviour, and
  the `dt`/`dd` document-order pairing especially.
- Tests are named as sentences describing behaviour
  (`test_a_stop_during_a_rate_limit_break_unwinds_instead_of_asking_again`), and grouped
  with `# region` / `# endregion`.
- Both READMEs must stay in step: the root `README.md` and the one generated into
  `build/README.md` by the `README` string in `build_artifacts.py`. File naming, the
  matching rule, and the collections format are documented in both by requirement.
- Verify claims before reporting them. Several conclusions in this project's history were
  wrong until checked against real fixtures or a live run.

## Data hygiene

`powershell_source/data.json` can contain the user's **ao3 password in plaintext** when
`SavePassword=true`. It is gitignored. Do not paste it, print it, or ship it - the bundler
deliberately does not seed `build/config/data.json`. The web UI never stores a password:
only the username, in `localStorage`, and only when "remember me" is ticked.
