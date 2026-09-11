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
as regressions. Current: **803 python passed, 4 failed; 155 gui passed.**

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
| Downloading a work (from the index) | **1 per format**, nothing else |
| Downloading a work (the long way round) | 1 for the work page, plus 1 per format |
| A collection's works | 1 per 20 works in it |

The per-format transfer is irreducible: each format is a separate file at its own url, so
PDF + HTML + EPUB is three transfers no matter what. Everything else was removable, and was
removed - see below.

### The download phase works from the index, not from ao3

`Ao3.download_indexed` is the default path for a bookmarks run. It skips two things the
crawl used to pay for: walking the listing a second time to rediscover links the index
already holds, and fetching each work's page to read a download link that the work number
already determines.

`parse_text.get_direct_download_link` builds
`https://download.archiveofourown.org/downloads/<id>/fic.<ext>`. Verified against the live
site: the slug after the work number is ignored by ao3 (`fic` returns byte-identical
content to the real title slug), the `updated_at` query is only a cache-buster, and the
links on a work page redirect to this host anyway - so going direct also drops a redirect.

**`repo.download_file` checks the response rather than trusting it.** A built link can
point at a work that is deleted, restricted, or absent in that format; ao3 answers those
with a page (verified: 404, `text/html`). Saving that under an `.epub` name would look
downloaded and be unreadable, so a non-200 raises, and so does html arriving for a
non-html format. Don't swap this back to plain `get_book`.

`server.can_use_index` is the guard. Embedded images, series links and mark-as-read are all
discovered *on* the work page, so asking for any of them falls back to `Ao3.download`. The
other cost of the indexed path is that nothing reads the work page, so locked/deleted/hidden
works are no longer recognised as such - they fail and are logged.

### A run that leaves gaps says which ones

`Ao3.failures` collects `{id, link, error}` for every work that would not download, from
both download paths (`record_failure` is called in `download_indexed`'s and
`download_work`'s except blocks). `run_bookmarks` emits it once at the end as a `failures`
event, and the ui lists the first few and offers to save the lot as text.

Two things it deliberately does not do: record a work more than once (a work that fails
usually fails for every format, and a list with the same number five times over is useless
for feeding back in), and treat a **stop** as a failure - `CancelledException` is re-raised
before `record_failure`, because a work that was never attempted is not one that failed.

The export is built in the page, not the helper: `failureReport()` returns the text and
`exportFailures()` does the Blob/anchor work, which is what makes the content testable.

So JSON is essentially free and everything else is not. `ExtraWaitTime` in settings.ini is
the pacing knob (seconds after every request); `0` trips the limit almost immediately.
`FORCED_FILETYPES` is `[JSON]` only - HTML is in `DEFAULT_FILETYPES`, so it starts ticked
but can be turned off, which makes a metadata-only run possible. Don't re-lock HTML.

Collections skip their works crawl when the profile page's count matches the stored one
(`Ao3.unchanged_items`), turning hundreds of requests into two. It cannot detect one work
added and another removed; delete the collection's json to force a full crawl.

### A listing run can start partway through

`Ao3.start` is the page to begin on; `Ao3.pages` is the page to stop after. Both are
**absolute** page numbers, so a run can cover a slice in the middle of a listing - which is
how you pick up after a stopped run without refetching what you already have.

`Ao3.page_progress` reports a page's place **in the slice being fetched**, not in the whole
listing. A run over pages 42 to 80 is fetching 39 pages, and its first is page 1 of 39;
reporting 42 of 80 started the progress bar half full and left it at 100% having fetched
less than half the listing. The stop page counts too - 42 to 60 is 19 pages.

A `page` event carries **both** sets of numbers on purpose: `page`/`total` are the slice
and drive the bar, while `listingPage`/`listingTotal` are the real page numbers and are
what the wording shows ("page 42 of 80" is the page you would go and look at). Don't
collapse them back into one pair - each is wrong in the other's place.

`get_metadata` keeps `source` as the bare listing url rather than the page it began on
(`source` is an identity field, so a page suffix there would look like a different listing),
and offsets `position` by `(start - 1) * AO3_LISTING_PAGE_SIZE`. Without that offset a run
starting at page 5 would number its first fic 1 and collide with a later run over page 1.
The offset assumes ao3's 20-per-page listings, which is the only thing that makes the
skipped pages countable.

### Indexing one collection by link

`ACTION_COLLECTION` (singular) indexes any collection from a url, next to `ACTION_COLLECTIONS`
which indexes the user's own. It is the only action in `ACTIONS_NEEDING_URL`, and the link is
validated in `do_POST` so a bad one is a straight 400 rather than a job that starts and dies.

There is no listing blurb behind it, so the display title, description and flags come from
`parse_soup.get_collection_header` reading the profile page (`#main h2.heading`,
`#main blockquote.userstuff`, `#main p.type`). That runs **only** when there is no blurb -
the listing stays the established source for those fields, and reading them from elsewhere
on a normal crawl would show up as a spurious change in the version history.

Flags are matched exactly, never as substrings: ao3 writes both `Moderated` and
`Unmoderated`, and a substring test reads the second as the first.

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

### Downloaded works carry the version they hold

A downloaded work's name ends in ` YYYY-MM-DD` - **the date ao3 says the work was last
updated**, not the date it was fetched. That is what lets a later run tell that ao3 has a
newer version than the file on disk.

**The naming is fixed, not a setting.** `strings.FILE_NAME_PATTERN` is
`{worknum} {title} - {author}`, with the date appended after it. `FileNamePattern` used to
be in settings.ini and was removed: the work number has to lead for files to be matched to
the index, and the date has to trail for the version check to work, so the only freely
movable parts were the ones that mattered least. `FileNameLength` *is* still a setting - it
exists to keep names under Windows' path limit. `server.read_settings` reports the rule and
an example (built through the real truncation) so the ui can show it instead.

`parse_text.get_valid_filename(parts, maximum, suffix)` cuts the *title* short to leave
room for the stamp, so the date is never the thing that gets truncated. `get_date_stamp`
parses both forms ao3 writes ('14 Dec 2024' on a listing, '2024-12-14' on a work page) and
returns `''` for anything else - it must never be the reason a download fails, so it is
also type-safe against a non-string.

**Json index files are deliberately undated.** An index file *is* the version history for
its fic; a name that changed whenever the fic did would start a new file and orphan
everything recorded so far. `save_metadata` passes no suffix - keep it that way.

The log records `updated` alongside `title`, and `shared.visited` rebuilds the stamp
through `parse_text.get_date_dict` when asking whether a file is already there. Without
that, every existing file looks missing and the console re-downloads the world.

### Replacing a copy is guarded, on purpose

`Ao3.replace_superseded` deletes the file a download supersedes only when **all** of:
the same file type is being replaced, the name actually changed, and `fileops.saved_intact`
confirms the new file is on disk at its full length. Anything else leaves the old file
alone. The failure mode being designed against is losing a file the user has and we do not,
so every one of those conditions is load-bearing - `test_ao3.py` has a test per condition
and two that operate on real files.

`shared.scan_downloaded_works` reads the folder as it is (matching by leading work number,
skipping `indexing/`, `collections/` and `images/`) rather than trusting the log, and
`shared.plan_downloads` turns that plus the index into `{stale, undated, superseded}`.
Undated files are counted but never refetched unless `refreshUndated` is set, which only
the ui's post-run offer does - it is a full re-download of a library.

The third way out of undated files is `stampUndated`, a `YYYY-MM-DD` the ui offers instead
of refetching. `shared.stamp_undated_works` renames those files in place to carry it -
**no requests at all** - and updates the scan dict it was given, so `plan_downloads` runs
straight afterwards and judges them by the ordinary rule with no special case. It cuts long
names down exactly as `get_valid_filename` would, and `fileops.rename_file` refuses to
write over an existing file (`os.replace` would silently destroy it), so collisions are
counted and skipped rather than losing anything.

`resolve_options` runs the value through `parse_text.get_date_stamp`, so anything that is
not a real date becomes `''` and nothing is renamed - a library must not be renamed after a
half-understood date.

### Pairing downloaded files to metadata

A file is matched to its index entry by the work id **at the start of the file name**,
followed by a separator: `/^(\d+)(?:[\s_.\-]|$)/`. `99 Red Balloons.html` is work 99;
`99Red Balloons.html` is not a work number at all. This rule is in `bookmarks.ts`
(`workIdFromFilename`) and documented in both READMEs. A bookmark record's `id` field is
the **work number**, which is what makes collections (which store only work numbers) join
onto the index.

### Nothing creates data.json just by reading it

`FileOps.get_settings_json` returns `{}` for a missing file rather than opening it in `'a'`
mode. It used to create one, and since `/api/config` reads the saved username on every page
load, an empty `data.json` kept appearing in a bundle that is meant not to have one. The
launcher (`ao3-env.ps1`) does not create it either. `save_setting` still does, which is what
the console menu needs. Don't reintroduce a create-on-read.

### A work a collection lists but the index does not have

`placeholderWork(id)` in `bookmarks.ts` stands in for those, carrying `placeholder: true`,
the work number and an ao3 link; `work-list.html` renders them as a stub row. A collection
records what it holds by work number alone and can hold works you never bookmarked, so
dropping them would show fewer works than the collection's own count promises.

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
