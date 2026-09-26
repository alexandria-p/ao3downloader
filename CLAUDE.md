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

**Open fixtures with `encoding='utf-8'`.** Without it Python uses the platform default codec
(cp1252 on Windows), and the first non-ascii character in a real ao3 page fails with
`UnicodeDecodeError`. That is what broke the 4 `test_ao3.py::test_proceed_*` tests, which
failed on unmodified upstream code too, until `get_soup_from_fixture` was given it.
Current: **1174 python passed; 455 gui passed.**

On a corporate network that intercepts TLS, add `--system-certs` to `uv sync`.

## Architecture, and why

### The local helper exists because a page cannot replace it

Ao3 sends no CORS headers, so a browser page cannot read it - this was verified with a live
`fetch`, which fails with `TypeError: Failed to fetch`. A page also cannot hold an ao3
login session, and cannot read or write the downloads folder. So the page talks to a python
helper on `127.0.0.1:4400`.

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
build ignoring its own config. **If you see "unknown action", settings that seem not to
apply, or an endpoint 404ing that plainly exists in the source, suspect a stale helper on
4400 first** - `netstat -ano | findstr :4400`, then compare
`Get-Process -Id <pid> | Select StartTime` against the build's write time.

This has been hit for real more than once, and the newest form is the nastiest: refreshing
the browser reloads the **page** from `build/`, but the **helper** is a long-running process
that keeps the code it started with. An app left running across a rebuild therefore serves a
new page from an old helper, and a feature added to both looks half-broken - the new log
messages appear (they come from the page) while a new endpoint 404s. `Jobs.setPaused` says
so in as many words when a pause 404s, because the fix is to restart the app and nothing
about the symptom suggests that.

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

**Only `run_bookmarks` can take that fallback**, and that decides what the ui offers. Every
other action downloads a *subset* of the index through `download_planned` /
`download_one_indexed`, and `Ao3.download` cannot do a subset - it walks a listing. So
**series expansion is offered on the full scan alone** (`picksSeries`): nothing else goes
the long way round, so there is nothing for a series to expand into.

**Embedded images take the other route.** `Ao3.save_images_for` fetches a work's page on its
own, purely to read the `<img>` tags out of it, and `server.save_images` runs that as a
separate pass **after** the files are down - never instead of them, and last, because a work
page fetched for pictures is the most expendable request in a run. It costs one extra
request per work, which is why only the custom run offers it (`picksImages`) and why the ui
says so twice: that it makes the run much longer, and that the images are normally embedded
in the downloaded work already, so most people do not want it at all.

`Ao3.save_images` is shared with `download_work`, which already had the page in hand. An
image that will not come down is logged and skipped, never fatal - the hosts are third
parties and a dead image link is the most ordinary failure here.

### The bundle ships only what the helper imports

`copy_helper_package` walks imports out from `source_code/server.py` (`HELPER_ENTRY`) with
`ast` and copies only what it reaches. `build()` returns `left_behind` and the build prints
it, so a module silently dropping out is visible.

**That list is empty now, and it should stay empty.** It used to hold 14 modules - the
console menu, its actions, and the ebook parsing only they used - and those have been
deleted, so the package is exactly what the helper needs. A name appearing in `left_behind`
again means either dead code worth removing or a module that lost its last import by
accident; either way, look rather than ignore it.

It follows imports rather than keeping a list on purpose: a list goes stale the moment a
module gains an import, and the failure shows up as an ImportError in a shipped bundle
rather than at build time. There is a test for exactly that - add an import to the fake
`server.py` and the new module gets shipped without anyone listing it.

`HELPER_DATA` is the escape hatch for what no import graph can see: `settings/settings.ini`
is read through `importlib.resources`, so it is named explicitly. If you add another resource
read that way, add it to `HELPER_DATA` or it will be missing from the bundle only.

### Eight actions, one dispatch table

`ACTIONS` is the allowlist and `runners()` maps each name to the function that runs it.
**`runners()` is built per call, not held at module level**, because a module-level dict
captures the functions at import - so replacing one afterwards (which every test of the
dispatch does) would change the name and not the table. It replaced a chain of elifs whose
last branch was a bare `else`, which quietly made any unrecognised action an update run.

The three that walk a listing differ only in where they stop:

| Action | Walks | For |
| --- | --- | --- |
| `bookmarks` | every page | repairing an index, or catching a finished fic that grew |
| `custom` | the pages asked for, or none at all | filling in a format, or a slice of a listing |
| `new` / `sync` | until the first fic already indexed | everything routine |

`Ao3.get_metadata(link, workdates, known=...)` is what makes the short walk possible: it
stops at the first work whose id is in `known`, and returns only the works ahead of it.
`shared.indexed_work_ids` builds that set **from the index file names alone** - the work
number leads the name by the same rule that pairs a download to its entry - because parsing
a few thousand json files to answer "seen this one?" per blurb would cost more than the
requests saved.

**The assumption is that ao3 lists bookmarks newest first**, which is what makes one stop
enough. Re-bookmarking an old fic moves it to the front, so the walk still stops correctly;
what it cannot see is a gap *behind* the stopping point, left by an interrupted earlier run.
That, and never re-reading a fic the index calls finished, are the two things `sync` makes
the user acknowledge - and the note can be turned off, because a warning on the run people
are meant to use routinely is one they otherwise learn to click past.

`run_sync` is the three passes in order, on **one** `Ao3` so every failure lands in the same
list and is reported once: `index_new_bookmarks` â†’ `download_planned` â†’
`update_incomplete` â†’ `fill_missing_formats`. The order is load-bearing - the gap check is
told which works the first two already handled, or it would fetch them again.

**The gap pass belongs to the combined run alone.** It used to run after a full scan, a
quick scan and a custom run too, through a `fill_gaps_in` wrapper that has been deleted.
Those runs cover what they cover in one pass, so a second sweep could only re-attempt works
that had just failed - which they already report as failures. The combined run is different
in kind: its earlier passes deliberately leave works untouched (a finished fic missing a
format nobody asked for last time), so something has to come back for them. There is a test
over `ACTIONS` asserting no other action lists a `gaps` step.

`fill_missing_formats` is the case neither other pass covers: a fic indexed and saved as
html long ago, on a run that now also asks for pdf. It is finished (so the update pass skips
it) and old (so the newest-first walk never reached it). **It fetches only the formats
actually missing**, by borrowing the caller's `Ao3` and setting `filetypes` per work - and
puts it back in a `finally`, because that object belongs to the run rather than to this
pass. Fetching the whole set would spend a request per format already on disk, and rate
limit is the scarce thing here.

**Every run asks its options before its file types.** A custom run has to - one of its
options decides a file type, since skipping the indexing means no json and **json is the
index** - and asking which types you want and then changing one behind you would read as the
dialog overruling you. The rest follow the same order because two orders is one more than
anybody needs to learn.

A run with nothing to ask has **no options step at all** (`hasOptions`), rather than a page
saying so: a step with nothing on it reads as one that failed to load. Which steps exist
therefore varies per run, so `stepBefore` builds the list and takes the one before - don't
hardcode a back target.

So json is locked on that run in *both* directions - ticked and disabled while it indexes,
unticked and disabled while it does not - rather than merely locked on. `chosenFiletypes`
reconciles that with `selected` before anything is sent, and `resolve_filetypes` takes a
`force` flag so the helper does not add json back to a run that will never write it. A
reported file type the run does not produce is worse than not offering it.

The steps are therefore **not in a fixed order**, which is why the dialog carries
`data-step` and `advanceTo` in the spec walks by where it is rather than counting clicks.
Counting clicks made every test quietly depend on which runs have an acknowledgement.

`Ao3.index_one_work` backs the single-fic action. A work page and a listing blurb describe a
fic differently, so an entry created there fills in only what a work page can honestly
answer for - title, author, and the versioned stats - and leaves tags, summary and the
bookmark's own fields empty rather than inventing a second schema. A fic already indexed
keeps everything it has and only its stats are rewritten, exactly as `refresh_one` does.
`server.work_link` accepts a link or a bare work number and normalises both to a work url in
`do_POST`, so a bad one is a 400 rather than a job that starts and dies.

### The update action is driven by the index

`run_update` was rewritten to work from `downloads/indexing/` rather than from the ebooks on
disk. **Do not reintroduce a `process_file` here** - parsing a chapter count back out of an
epub was the old way. `update.py` was what did it, and it has been deleted along with the
rest of the console app.

The flow, in the order the ui narrates it:

1. `shared.read_index` â†’ `shared.incomplete_works`, off disk, no requests at all
   (`scanning`)
2. `shared.scan_downloaded_works` - what is already in the folder for those works
   (`checking_files`)
3. `settle_undated` - the question about files with no date in the name, asked **here**,
   before a single request, because the answer decides which copies count as behind
4. then one fic at a time (`updating`), through `update_one_work`: `Ao3.refresh_one`
   re-reads it and rewrites its entry, `shared.plan_downloads` judges that one work, and
   `Ao3.download_one_indexed` fetches it only if it has to

`fill_missing_formats` re-reads its fics the same way, for the same reason: a file written
from a stale entry is named with a stale date, and would read as current for ever after.
See **What "outdated" means, exactly**.

**This is deliberately not the bookmarks order.** `run_bookmarks` indexes everything before
downloading anything, and can, because one listing request describes twenty works. Here
each fic has to be opened individually before there is anything new to say about it, so
batching the re-reads would buy nothing and would mean a stopped run had half-finished every
fic instead of wholly finishing the ones it reached. Don't "make it consistent" with the
bookmarks run.

**The re-read is unconditional; only the download is not.** Every unfinished fic gets
re-read and its entry rewritten, so the index ends up current whether or not anything was
fetched. There are exactly two reasons to download: no copy of a requested format, or a copy
`plan_downloads` calls stale. Don't add a third - an earlier version had a
`works_worth_fetching`/`gained_chapters` pair that also fired on chapter growth. That is
redundant for a dated file (gaining a chapter moves ao3's `date_updated`, so the file is
already `stale`) and only ever mattered for undated ones, which are now settled by asking
the user outright. Both functions were deleted; guessing from a chapter count is not a
substitute for the answer.

Each step prints a line and emits an event, so the modal reads as a running account rather
than a bar that sits still: `AO3_INFO_UPDATE_WORK` names the fic, `_READING` says it is
about to open the fic page, then `_INDEXED` and one of `_MISSING`, `_BEHIND`, `_CURRENT` or
`_NOTHING` say what was decided about it. `_READING` goes **before** the request, not after:
that request is the slow part, and a line printed afterwards leaves the run looking stalled
on the fic it has only just named.

`parse_soup.get_work_stats` is **deliberately a subset**. A work page and a listing blurb
describe a fic differently, and writing the whole of one into a record shaped by the other
would make every field look changed and fill the history with schema noise. Only chapters,
words, comments, kudos, bookmarks, hits and the updated date are rewritten; tags, summary
and the bookmark's own fields stay as the listing left them.

`parse_text.get_listing_date` exists for one reason: a work page writes `2024-12-14` and a
listing writes `14 Dec 2024` for the same date. The index keeps one field for it, so without
normalising, an update pass and a bookmarks pass would rewrite each other forever, each one
looking like a change. It is idempotent - normalising twice changes nothing.

**The limitation is inherent, not a bug.** `indexing.is_incomplete` reads what the index
last recorded, so a fic that had finished by then is invisible however much was added after.
The ui has an `acknowledge` step that must be ticked before the login for exactly this, and
points at the bookmarks run instead, which re-reads the listing and catches those.

### Debug tools, off unless settings.ini asks

`EnableDebugTools` adds a panel to the download window, and **gates three of the buttons**:
the combined run, 'just update incomplete' and 'just download new bookmarks'. Those are the
passes the quick scan and the full scan are built from, each usable alone, and offering them
beside the two runs people should reach for invites picking a part when the whole was wanted.
They carry a `[DEBUG]` prefix and the red `.button.debug` treatment so they never read as
part of the ordinary set. `App` reads the flag off `Jobs.config`, loading it as the page
opens rather than waiting for a dialog to need it.

The panel itself is for working on the app rather than for using it, and the two things it
offers are deliberately different in kind:

- **Skip this step** is real. `job.skip` is checked at the same loop boundaries `cancel` is,
  and `Job.skipping()` **clears the flag as it reads it** so one press skips one step rather
  than every step after it. The abandoned step is marked `skipped`, never `done` - what it
  would have done did not happen, and the checklist must not claim otherwise.
- **Show a made-up report** is entirely in the page. Nothing is sent to the helper and no
  run is touched; it fills both end-of-run lists with one entry of every kind so their
  layout can be checked without waiting for a long run and hoping something goes wrong.

### A login that lapses mid-run ends the run

A lapsed ao3 session does not announce itself: ao3 serves the logged-out view, so a
restricted work comes back as a page instead of a file and `download_file` rejects it - the
**same failure a deleted work produces**. The difference is that a lapsed session fails
everything from then on.

So `Ao3.check_session` is called only from the download `except` blocks, and asks
`repo.still_logged_in()` **at most once per run** (`session_checked`). It costs a request,
and asking again after each of four hundred failures would cost four hundred. If the session
is alive it is a per-work failure like any other and the run carries on.

`SessionExpiredException` must **propagate**, so every per-work handler that would otherwise
swallow it re-raises explicitly - `Ao3.download`, `update_one_work`, `fill_missing_formats`,
`save_images`. Miss one and the run grinds on producing a failure list of hundreds of
identical reasons, which is exactly what this exists to prevent. `still_logged_in` answers
**True** when the check itself fails: ending a run because a check timed out would be worse
than the problem.

`run_job` flags it on the `failed` event (`sessionExpired`) rather than leaving the ui to
recognise it from the error text - it is not a crash, and there is a specific thing to do.

**There is no resume-from-position, and none is needed.** Every run works out what to do
from the index and the folder - `visited`, `plan_downloads`, `fill_gaps_in` - not from where
a previous run got to. Starting the same run again *is* the resume: it fetches what is
missing or outdated and skips what is not. The ui says so on the failure.

### Every run writes itself down

`runs/` is a subfolder of the **downloads folder** (`downloads/runs`, wherever
`DownloadFolder` points), one json file per run: which button, which settings, which fics were reindexed / downloaded / updated, the
choices it stopped to ask, what it could not get, and how it ended. `GET /api/runs` reads
them back for the history tab.

**Living in the downloads folder costs two skips, and both are load-bearing.** That folder
is read as though everything in it were a work, so `shared.scan_downloaded_works` lists
`RUNS_FOLDER_NAME` alongside `indexing`, `collections` and `images` - a run record is json,
and json is a requested file type on most runs. The web page needs the same protection and
cannot use the folder name for it: a directory read through the File System Access API
arrives **flat**, so `jobs.isRunRecord` recognises one by shape and `Library.readRecords`
passes it over. Without that a run record renders as a bookmark, because `flattenRecord`
hands back anything carrying an `id` and a run record has one.

`FileOps.initialize` creates the runs folder **after** the downloads folder rather than
before. Creating it first would make an unusable `DownloadFolder` fail with a bare `OSError`
from a line that says nothing about which setting is wrong, instead of
`MESSAGE_DOWNLOAD_FOLDER_ERROR`.

**The file is written when the run starts, not when it ends.** A run killed mid-flight
cannot write its own epitaph, so a record still saying `running` *is* the evidence that it
was interrupted - that is how the history tab recognises one.

**'Starts' means 'is about to try the login'**, not 'the job object exists'. `run_job`
creates the `RunRecord` between `steps.start('login')` and `repo.login`, so a history file
always means a run that got as far as reaching for ao3. Everything before that point is
setup that cannot touch the network, and a file written for one of those would sit in the
history for ever describing a run that never happened. A login that is *refused* still gets
its record, because it did happen - it is written before the attempt for exactly that
reason.

Note what this does **not** fix: a `running` record whose fic lists are all empty means the
helper went away almost immediately after the login - the app closed, the process killed, or
restarted to pick up a rebuild. Nothing the run itself can do will close that file, which is
the whole point of writing it up front. Everything in `runs.py`
swallows its own errors: a run that downloaded a library must not be reported as failed
because a note about it could not be saved.

**`RunRecord.line` can keep the console output too (`log`), but nothing currently calls
it.** The machinery is built and tested - lines are batched because `save` rewrites the
whole file and a run prints a line per fic per format, so `LOG_FLUSH_EVERY` lines go out at
a time; `LOG_MAX_LINES` caps it and drops the **start** when reached, because whatever went
wrong is at the end, with `logTrimmed` counting what went. `read_runs` leaves `log` out of
the listing by default and reports `logLines` instead, since a hundred records of thousands
of lines each would be tens of megabytes for a page that does not show them.

The wiring in `server.run_job` that fed it was reverted at the user's request, so no run
writes a log today. Either finish it - the missing piece is passing printed lines to
`record.line`, plus somewhere to hold the ones printed before the record exists - or delete
the machinery; do not leave it half-connected and assume it works.

**settings.ini goes in beside the run's own choices** (`settings`). `filetypes` and
`options` are what the user picked in the dialog; this is what the run inherited - pacing,
naming, retries - and without it a run cannot be explained after the fact. The path is part
of it because *which* settings.ini was in force depends on where the helper was started
from, which is the usual explanation for settings that appear to have been ignored.
`settings_for_record` gathers it in a try/except for the same reason everything in
`runs.py` swallows its own errors: a run that downloaded a library must not be reported as
failed because the note about it could not be filled in.

The three fic lists are separate because they answer different questions - `reindexed` (a
fresh index entry), `downloaded` (a file arrived), `updated` (an old copy was actually
replaced, tracked where `replace_superseded` deletes it).

`runs.last_successful` ignores stopped, failed and interrupted runs, and takes a `match`
predicate for the rest. **Finishing is not enough to be a floor.** A quick scan measures
back to the last run that reached every work ao3 had updated by the time it started, and
`server.covered_the_whole_listing` says which those are: a full scan, and a quick scan that
was *not* given a date range. Nothing else qualifies - the combined run and 'just new
bookmarks' stop at the first fic they recognise, an update run and a date window read no
listing at all, a custom run covers whatever slice it was told to, and a quick scan over a
date range stops at the user's date rather than the previous floor. Any of those can finish
perfectly while never looking at a fic ao3 updated that day, and measuring back to one would
skip that fic permanently.

The predicate takes the whole record rather than a set of action names because whether a run
covered everything depends on the options it ran with, not only on which button it was -
which is exactly the date-range quick scan.

### A quick scan stops where ao3 stopped changing things

`run_quick` indexes in **two walks**, both back to the same floor (`quick_scan_floor`, the
day the last qualifying run started), and downloads whatever either one found:

1. the listing **sorted by date bookmarked** (`AO3_SORT_BY_BOOKMARKED`, `created_at`),
   stopping at the first bookmark made before the floor (`stop_on='bookmarked'`, which
   reads `div.user p.datetime`)
2. the listing **sorted by date updated** (`AO3_SORT_BY_UPDATED`, `bookmarkable_date`),
   stopping at the first work ao3 last updated before the floor (`div.header p.datetime`)

**Each walk catches what the other cannot.** A fic bookmarked yesterday that ao3 last
updated in 2019 sits far below the floor on the updated-date listing, so walk 2 never
reaches it; a fic bookmarked years ago that was updated yesterday sits far below it on the
bookmarked listing, so walk 1 never does. Both sort names were verified against ao3's own
search form. `merge_by_work` joins the two by work number, so a fic both walks found is
downloaded once.  With **no floor** the first walk already reads every bookmark, so the
second is skipped at runtime rather than paying to read the whole listing twice.

One side effect to know about: `position` and `source` are identity fields that `merge`
overwrites on every save, so a fic both walks found keeps the values from walk 2, whose
order is the updated-date one rather than the listing's own.

**The sort is not optional, and this was verified against the live site.** The default
bookmarks listing is ordered by when each work was *bookmarked* and jumps about by years
(28 Apr, 30 Aug, 10 Sep, 23 Feb...). Sorted by `bookmarkable_date` it is strictly
descending. A stop-at-first-older walk down the default listing would halt after a fic or
two and miss nearly everything, so `get_metadata`'s `stop_before` is only sound on that
order and says so.

**The stop rule may never fire, and that is fine.** Every bookmark updated since the
floor, or a floor older than the whole library, and nothing is ever older than it. The
walk then ends the ordinary way - `current >= total_pages`, or no pagination at all -
so **running out of pages is the fallback that guarantees termination**, not the date
check. `get_next_page` always increments, so `current` always advances toward that
bound. There is a test per case, because otherwise the only thing ending the walk would
be a rule that is allowed not to fire.

**The floor can be picked by hand.** The options step offers *Choose which earlier scan to
measure back to*, and a `floor` page lists the candidates from `GET /api/runs/floors`. That
list is `floor_runs` - the same rule `quick_scan_floor` applies to the latest run, applied to
all of them - so what the page offers and what the helper accepts cannot drift apart. Only the
run's **id** travels (`floorRun`): `chosen_floor` reads the date off that run's own record, and
`do_POST` answers 400 for an id that is not a valid floor, so a request can never invent one.
The option is clamped away for every other action. A chosen run whose history file vanishes
between the start and the run falls back to the usual rules rather than guessing at a date.

**With no completed run there is no floor, and the walk runs to the end** - `stop_before`
is `''`, which `get_metadata` treats as no limit at all. So the first quick scan is a full
index and download. The ui promises this in as many words, and there is a test asserting it
rather than trusting the promise.

The stop itself is in `get_metadata`: each blurb's `p.datetime` is the work's own updated
date, and the walk breaks at the first one where `updated < stop_before`. The comparison is
strict, so **a work updated on the floor date is still indexed** - a run that started that
afternoon cannot tell it apart from a work updated that morning. A blurb with no readable
date never stops the walk, because it cannot be judged and stopping on it would cut the run
short.

**A quick scan can be given a date range instead** (a debug option), and it keeps the quick
scan's **two walks** rather than borrowing the custom run's window. The range's older end
becomes the floor both walks stop at, and `works_dated_between` then keeps, from each walk,
only the works whose *own* date - bookmarked for walk 1, updated for walk 2 - falls between
the two ends. A listing cannot be entered at a date, so both walks start at the newest
bookmark and read past the ceiling on the way down: what lies above it is indexed but not
downloaded. With no older end the first walk reads everything, and the updated-date half of
the range is picked out of that same walk instead of walking the listing a second time.

`run_custom_dates` is the **custom run's** alone now - one walk by date updated, then a
per-fic pass over the index. `step_plan` sends only `ACTION_CUSTOM` down that branch; a
quick scan with dates keeps the quick scan's checklist with window-worded labels.

Its acknowledgement branches on that choice, and has to: the default shape can do a full
index on its first run and cannot restore what an earlier run missed, while a date range
cannot do either of those things and instead gets slower the further back it reaches. One
note covering both would be half untrue whichever way it was worded.

The quick scan is given the combined run's acknowledgement but **not** its wording: it
re-reads any completed fic ao3 has touched since the floor, so "will not notice changes to
fics already marked complete" would be untrue of it. Its own caveat is the one that applies
- it trusts the date, so anything missed before that date stays missed.

### A run publishes the steps it intends to take

`step_plan(job)` builds the checklist from the action **and the options**, so a step that
depends on a choice - images, skipping the indexing, a metadata-only run - appears only when
it will actually happen. A checklist that lists work the run will not do is worse than none.
`Steps` sends it once as a `STEPS` event before anything starts, then one `STEP` event per
change, and `job.steps` is a no-op `Steps(None, [])` until `run_job` swaps in the real one -
so every run function marks its steps without first checking whether anyone is listening.

**This cannot be built from `PHASE` events**, which is why it is separate. A phase says what
*kind* of work is happening and repeats - a combined run downloads twice and checks files
twice - while a step is a place in a plan and happens once. Only the second can drive a
checklist.

**Whether an unnecessary step is listed depends on who made it unnecessary.**

- **the workflow never had it** - left off the plan entirely. `new` lists no gap pass
  because `run_new` runs none; a run writing no json lists no indexing step, because json
  *is* the index. Listing work a run was never going to do is worse than not listing it.
- **the user turned it off** - listed, and marked `skipped`. Ticking *skip indexing* on a
  date-window run is a decision worth seeing reflected back, so `step_plan` keeps the step
  and `run_custom_dates` marks it skipped as it passes. An option that silently removes a
  line from the checklist reads as the app having forgotten it.

The ui says which is which: a skipped step carries a `[SKIP]` tag on the label and is
stepped over (`Â»`) rather than ticked, dimmed rather than coloured like a failure - nothing
went wrong, the run simply had no reason to do it.

**A step with nothing to do at runtime is `skipped`, never `failed`.** A run with no
unfinished fics has not gone wrong, and the ui colours the two differently for that reason. `fail_current` marks
only the step that was actually running: the ones after it never started, and blaming them
for something that happened before they were reached would be a lie.

### Decisions are per format, and works are done newest first

`say_what_each_format_needs` classifies **each requested format** for one work - missing,
outdated, undated or current - prints a line for each, and returns only the ones to fetch.
`fetch_formats` then borrows `ao3.filetypes`, sets it to exactly that list, and puts it back
in a `finally`.

This was per *fic*: anything missing or stale meant `download_one_indexed` with the run's
whole filetype list, so a fic that had a current html and no pdf re-fetched the html too. A
request each, spent for nothing.

**The verdicts come out of `plan_downloads`, not from judging again here.** `superseded`
already names the exact formats it decided to replace, so there is one definition of
outdated (see **What "outdated" means, exactly**) and this only puts words to it. `stale` and
`superseded` always move together in a real plan - a test stub with one and not the other is
a stub that cannot happen.

`newest_first` orders by `date_updated` through `get_date_stamp`, so the two formats ao3
writes sort together and an entry with no usable date goes last. Every pass that works
through a list of fics uses it, because **a run can be stopped** and where it got to should
be the half worth having.

`fill_gaps_in` runs after the download phase of a full scan or custom run. The download phase
decides what to skip from `shared.visited`, which is built from the **log**; this reads the
folder instead, so a file deleted by hand or a trimmed log cannot leave a work looking
downloaded when it is not. It passes `reindex=False` (the caller has just had these entries
off the listing) and `only=` the works this run covered - the index can hold fics no longer
bookmarked, and fetching those would be a surprise.

### A run names what it could not get, in two lists

`report_failures` emits **both**, and every one of the eight actions calls it - there is a
parametrised test over `runners()` asserting exactly that, because the coverage had gaps
twice: `run_collections` and `run_collection` never called it at all, and in `run_bookmarks`
it sat *inside* `if downloadtypes`, so a metadata-only run reported nothing even though
indexing is precisely where skipped bookmarks are found.

- `Ao3.failures` - works that should have downloaded and did not. Worth retrying.
- `Ao3.skipped_works` - bookmarks that were never works: a series, something hosted
  elsewhere, one since deleted. **Never worth retrying**, because there is no work there.

**Keep them apart.** They are different events (`FAILURES` / `SKIPPED`), different panels,
and different colours - the skipped one deliberately does not wear the failure red. Merging
them would make a real failure look routine and send people retrying things that cannot
change.

`parse_soup.get_blurb_skip_reason` works out *why* from the blurb, returning the same
`{id, link, error}` shape a failure does so both lists render and export through one code
path. It reads what the page says - a `/series/` link, an off-site href, the deleted stub -
and where the listing does not say, `SKIPPED_UNKNOWN` says that rather than dressing a guess
up as a reason. This used to be a bare count (`AO3_INFO_METADATA_SKIPPED`), which left no way
to tell *which* bookmark was passed over or to go and look at it.

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

**Each page sends two of those events**: one before the request carrying `fetching=True`,
one after it carrying `works`. The caption has to name what is happening, not what last
finished - the fetch is the slow part of indexing, so a caption written only once a page is
in names the *previous* page for the whole time the next one is on its way. The console
output already said both ("fetching page 4 of 80" before, "finished page 3 of 80" after);
the progress bar was reading the second one alone.

The pre-request event deliberately does **not** move the bar to that page. It sets it to
`(page - 1) / total` - what has actually arrived - because a page being asked for is not a
page that has been fetched, and a bar that counts it is claiming work that may yet fail. It
also carries no `works` count, since the only count available would be the previous page's.
On the first page it carries no total either: the total is read off that page, so nothing
knows it yet, and the ui says "fetching page 1" rather than "page 1 of ?".

**A walk that can stop early never states a total.** A date floor (`stop_before`) or a set of
already-indexed works (`known`) ends the walk wherever the first older or familiar fic sits,
so the listing's page count is not the number of pages the run will read. `get_metadata`
marks such a walk `open_ended` and sends `None` for `total`/`listingTotal` and drops the
`of Y` from its lines - `finished page 3. 57 works so far`, not `of 80` on a walk that stops
at page 4. The bar stays indeterminate for the same reason. `total_pages` is still read and
still ends the walk; it is only never *said*. A walk with nothing to stop it early - a full
scan, or a quick scan with no floor - really does read every page, so it keeps its total.

The stopping page also reports finishing: `reached_known` breaks **after** the page's
`finished` line and event, not before, so a walk stopped by a floor no longer ends on
`fetching page 4` with nothing to say the page was read.

`get_metadata` keeps `source` as the bare listing url rather than the page it began on
(`source` is an identity field, so a page suffix there would look like a different listing),
and offsets `position` by `(start - 1) * AO3_LISTING_PAGE_SIZE`. Without that offset a run
starting at page 5 would number its first fic 1 and collide with a later run over page 1.
The offset assumes ao3's 20-per-page listings, which is the only thing that makes the
skipped pages countable.

### A custom run can cover a date window instead of a listing slice

The two are alternatives, never both: pages pick works by **where they sit in the listing**,
a window picks them by **when ao3 last updated them**, and a run that tried to honour both
would have no honest answer for a fic that satisfied one and not the other. `resolve_options`
carries `dates`, `dateFrom` and `dateTo` alongside `start`/`pages`, and `dates` is what says
which pair is read at all. The ui enforces the same thing by hiding the page inputs while the
window is chosen, rather than leaving a slice showing that the run will ignore.

`run_custom` branches to `run_custom_dates`, which reads `downloads/indexing/`, filters with
`works_updated_between`, and hands the result to `refresh_and_download` - the same function
the unfinished-fics pass uses, extracted from `update_incomplete` so the two cannot drift
apart.

It brings the index up to date first, and **the walk that does it is the quick scan's**:
the bookmarks listing sorted by `AO3_SORT_BY_UPDATED`, with `stop_before` set to the
window's **older** end. Only the older end can stop a walk that runs newest first - the
newer end is passed on the way down, so stopping at it would halt before the window was
reached. With no older end there is nothing to stop at and the listing is read in full,
which is the same answer a first quick scan gives and is said in as many words in the ui.

`pages` and `start` are forced to `None`/`1` for a window. The page inputs are hidden once
a window is chosen but the run still carries whatever was in them, and a leftover limit
would cut the walk short of its floor.

The whole index is filtered afterwards rather than just what the walk returned: a fic
inside the window that is no longer bookmarked is still one the window asked for. Skipping
the indexing (or a run with no json, since json *is* the index) leaves the pass working
from the index as it stands, and then a fic whose entry is behind ao3 is picked or missed
on the strength of that entry - the ui says so where the option is.

Both ends are inclusive and an empty end means no limit there. The dates go through
`parse_text.get_date_stamp`, so anything unparseable becomes `''` - a bad date widens the
window rather than failing the run, which is the safe direction when the alternative is a
window that silently matches nothing. Records with no usable `date_updated` are **excluded**,
not included as a maybe: there is nothing to compare, which is the same rule as
**What "outdated" means, exactly**.

**The per-fic pass does not re-read what the walk just indexed.** `refresh_and_download`
snapshots `ao3.reindexed` before it starts and passes it to `update_one_work` as
`already_fresh`; anything in that set keeps the entry it has and goes straight to the
download decision. A listing blurb reports the same `date_updated` a work page does, so on a
date window - where the walk indexed exactly the fics the window then picks - this is the
difference between one request per fic and none, and it is the largest cost in that run.

The set is the right test rather than a "did we index?" flag, because it stays correct in
the cases a flag would get wrong: skip indexing and it is empty, so everything is re-read;
and a fic in the window that is no longer bookmarked was never on the walk, so it is re-read
too. An entry from an earlier run cannot say whether ao3 has moved on since - see
**What "outdated" means, exactly**.

The picks are ordered by `newest_first`, because a window is usually opened to catch up on
what moved most recently and a stopped run should have finished the fics that mattered most.

`step_plan` gives the window its own steps (`login â†’ index â†’ read â†’ check â†’ update â†’
report`) rather than reusing the indexing plan, since three of the scan's steps never run,
and drops the `index` step when the run will not do one. An empty window is **skipped, not
failed** - no fic updated in that range is an answer, not an error.

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

### Whether a fic is bookmarked is only written when something actually knows

Index entries carry `bookmarked` (`strings.BOOKMARKED_FIELD`). There are exactly two
sources, and the field is **absent**, never `False`, when neither has spoken:

- **a walk down your own bookmarks listing** writes `True` for every fic on it. Every
  `get_metadata` call in `server.py` passes `own_bookmarks=True`, and a test counts them - the
  caller says so because a bookmarks url does not say whose bookmarks they are.
- **a work page** (`index_one_work`, `refresh_one` - the single-fic run, the update pass, the
  gap pass) reads the navigation's bookmark link through `parse_soup.get_bookmarked`: `Edit
  Bookmark` is `True`, `Bookmark` is `False`. Both wordings are in the logged-in fixtures.
  No link (logged out, an unexpected page) is `None`, and `ao3.bookmark_state` then writes
  nothing, so a page that could not see the button never unmarks a fic.

It is a snapshot field, not identity: unbookmarking a fic is a real change worth a history
entry.

### The undated question names works, and dating names files

`settle_undated` counts **works** (the question is about works) but a work saved in two
formats is two files, so it says both - `12 works (24 files)` - and prints the work numbers.
Without that, `dated 24 files` straight after `12 works` read as a miscount. The run
record's choice carries `works` and `files` when asked, and `RunRecord.amend_choice` adds
`renamed` (`{id, from, to}` per file, from `stamp_undated_works`'s `files`) once the renames
are done - the choice is written first so a run that dies mid-rename still shows the answer.
The history tab lists both, and describes the quick-floor question as itself rather than as
undated files.

### Versioned json

`indexing.py` splits a document into identity (never versioned) and snapshot. `merge`
appends to `indexes` only when the snapshot actually changed, and always updates
`last_indexed`. Two identity sets: `IDENTITY_FIELDS` for works, `COLLECTION_IDENTITY_FIELDS`
for collections. `position` is identity, not history - a fic sliding down the bookmarks
list is not a change to the fic.

### What "outdated" means, exactly

**A copy is outdated when the most recent `date_updated` in the index is newer than the
date in the file's own name.** That is the whole definition, it is the only one, and every
part of this project that decides whether to fetch something again means precisely this.

`shared.plan_downloads` is where it lives: `current` is the record's `date_updated` run
through `parse_text.get_date_stamp`, `copy['date']` is read back out of the file name by
`parse_text.get_date_from_filename`, and the test is `copy['date'] < current`. A plain string
comparison is correct because both sides are `YYYY-MM-DD`, which sorts lexically.

Three things follow from it, and each is load-bearing somewhere else:

- **A file with no date in its name cannot be judged at all** - there is nothing to compare.
  Those are `undated`, never `stale`, and the run stops and asks what to do about them
  rather than guessing.
- **The index has to be current before the comparison is worth anything.** An entry that has
  not been re-read cannot say ao3 has moved on. This is why the update pass re-reads a fic
  before judging it, and why the gap pass re-reads one before writing a file - a file named
  from a stale entry carries a stale date, and would then look current forever.
- **Nothing here looks at the file's own timestamp, its contents, or a chapter count.** An
  earlier version also fired on chapter growth; it was removed, because for a dated file
  that is redundant (gaining a chapter moves ao3's `date_updated`) and for an undated one
  the answer comes from the user instead.

### Overwriting is the one exception, and it is the user's to make

`plan_downloads(..., overwrite=True)` puts **every** copy of a requested type into
`superseded`, current or not. That is not a second definition of outdated - it is the
admission that nothing here can see a file that is damaged or truncated. The name is right,
the date is right, and only the bytes are wrong, so no version check can ever catch it and
the only honest answer is to ask the user and act on what they say.

There are exactly three answers, and which one a run gets is not negotiable:

- **the full scan and the custom run offer it** as a checkbox. They are the runs pointed at a
  library and told to spend more on it.
- **the single-fic run always does it**, and offers no checkbox - see below.
- **every other run never does it.** They exist to be cheap, and skip whatever is already on
  disk and current.

`OVERWRITE_ACTIONS` holds the first group and `do_POST` clamps the option to `False` for
anything outside it, next to the line that clamps file types the same way. The ui never sends
it otherwise, but the rule belongs at the boundary where a request becomes a run: a stray
flag must not be able to make a routine run re-fetch a whole library.

**The single-fic run always overwrites, and does not offer the box.** A box that cannot be
unticked is not a choice. Every other run is pointed at a library and has to be careful about
what it spends, so it skips what is on disk and current; this one is pointed at a single fic
by hand, where being told nothing happened because the copy looked fine is not the answer
anybody came for, and being wrong costs one request per format for one work. `run_work` sets
the flag on the job's own options, so the history file records what the run actually did. `sync`, `quick` and `update`
exist to be cheap; a run that re-fetches everything it already holds is the opposite of
that, and putting the option there would invite it to be left on.

Two things follow, and both are in `plan_refresh` and `refresh_and_download`:

- **the undated question is not asked.** It exists to decide what happens to copies that
  cannot be judged, and this has decided it - for those and for every other copy. Stopping
  to ask would be asking about works the run is about to fetch again anyway.
- **the wording changes.** `AO3_INFO_OVERWRITING` replaces `AO3_INFO_OUT_OF_DATE`, and
  `AO3_INFO_FORMAT_REPLACING` replaces `AO3_INFO_FORMAT_OUTDATED`, because most of what an
  overwrite replaces is perfectly current and calling it outdated would read as the version
  check having gone wrong. The plan carries an `overwrite` flag purely so
  `say_what_each_format_needs` can tell which sentence is true.

`replace_superseded` needs nothing new: the re-fetched file usually has the *same* name, so
there is no old file to delete and the write lands on top of it. The guard only fires when a
name actually changed, which is still exactly right.

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

**Every file a download writes is announced, once.** Both download paths
(`download_one_indexed` and `try_download`) save through `Ao3.save_download`, which prints
exactly one line naming only the **new** file: `INFO_SAVED_NEW_COPY` (`new download:`),
`INFO_REPLACED_OLD_COPY` (`replaced the older copy:` - said both for an outdated copy deleted
and for a copy written over under the same name, which also counts in `updated`), or
`INFO_KEPT_OLD_COPY`. Only the deleted-copy case used to print, so a run bringing down
hundreds of new formats looked idle. `replace_superseded` returns
`(REPLACED | KEPT | None, old name, reason)` and prints nothing itself, or a replacement
would be said twice. Call `save_download`, never `save_bytes`, for a work's file - a test
reads both methods' source to hold that.

**A failing format does not stop the work's other formats.** Both download loops wrap each
format in `Ao3.one_format`, which notes the failure (`INFO_FORMAT_FAILED`) and carries on;
`raise_if_formats_failed` then fails the work once, with every failed format named
(`EPUB: ...; PDF: ...`). Each format is its own file at its own url, so ao3 lacking an epub
says nothing about the pdf - which used to be abandoned unasked. A stop and a lapsed login
still end everything. The work goes into `downloaded` if any format arrived, but its log entry
is **not** `success`, because `shared.visited` skips logged successes and the missing format
would never be fetched again. The combined exception is a `SavedFileException` only when every
failure was one, so a single ao3 failure among them still gets the login check.
`repo.download_file` names the format and the status in its own message too.

**Every saved file is checked, first download or not, and there are three ways it can go
wrong.** `save_download` calls `saved_intact` itself, before `replace_superseded`:

1. **the new file is missing or short** - `discard_damaged` deletes it, prints
   `INFO_DAMAGED_KEPT_OLD` (naming the older copy still there) or `INFO_DAMAGED_REMOVED`, and
   raises `SavedFileException` with `fileops.saved_problem`'s detail (not found at the path,
   or expected/found sizes). Every download caller already turns an exception into
   `record_failure`, so it becomes an ordinary failure and the work is not counted as
   downloaded. It is deleted rather than kept because its name carries the current date - a
   short file left behind would be judged up to date by every later run. **This covers first
   downloads and same-name overwrites too**, which were never checked before. `check_session`
   returns early for this exception (read off `sys.exc_info()`): a folder problem says
   nothing about the login, and asking costs a request.
2. **the older copy will not delete** - `KEPT`, `INFO_KEPT_OLD_COPY`, `KEPT_NOT_DELETED`.
3. **the check itself raises** - `UNCONFIRMED`, `INFO_UNCONFIRMED`, nothing removed.

2 and 3 go into `Ao3.kept_copies` as `{id, link, file, old, error}` (`old` empty for a first
download) - reported as a `keptCopies` event, stored by `RunRecord.collect`, listed in
History as "needs checking by hand", amber rather than red. `replace_superseded` still
checks `saved_intact` as a second line of defence and answers `UNCONFIRMED` if it fails.

**The end-of-run export is one file.** `issuesReport()` writes a `## heading` per kind
(failures, kept copies, bookmarks that are not works) with tab-separated rows under each, and
leaves out a kind with nothing in it; one `Export all issues` button replaces the per-list
buttons. The step that does the reporting is `STEP_REPORT` = `Report any failures`, and it is
the last step of **every** plan - there is a test over `ACTIONS` asserting it.

### A run can stop and ask a question

Undated files are the one thing a run cannot decide for itself, so it **stops and asks**.
`server.settle_undated` is called from `plan_refresh`, which both `run_bookmarks` and
`run_update` go through, and it runs *before* planning - the answer decides which works
count as out of date, and asking afterwards would be too late to act on.

`Job.ask` emits a `question` event and blocks; the ui replies through
`POST /api/jobs/<id>/answer`, which `Job.reply` hands back. Three things keep that from
hanging, and all three matter:

- the wait is in `ANSWER_POLL_SECONDS` slices, checking `job.cancel` each time, so a stop
  releases a run nobody is answering
- `ANSWER_TIMEOUT_SECONDS` gives up after 30 minutes, so a closed tab cannot leave a thread
  waiting for an answer that can never arrive
- **the default is always `skip`** - the option that changes nothing. Whatever goes wrong,
  a run must not rename or refetch a library on its own

`answer_job` rejects a choice outside `UNDATED_CHOICES` and runs the date through
`parse_text.get_date_stamp`, so a run waiting on an answer is never handed something it
cannot act on, and a library is never renamed after a half-understood date.

**The answer applies to the works the question was asked about, and nothing else.**
`stamp_undated_works` takes a required `works` set for this reason. `existing` is the whole
downloads folder - `scan_downloaded_works` reads all of it, because a work's copy has to be
found wherever it sits - while `plan_downloads(records, ...)` narrows that to the run's own
records. Handing the folder scan straight to the renamer was a real bug, hit for real: an
update run reported a few hundred undated works and then dated 1,690 files across the whole
library. The scope is the works in `undated`, not in `records` - a work that is stale in one
format and undated in another counts as stale, so it is not in the number the user was shown
and is about to be refetched anyway. The file types are already narrowed, by the scan.

This was `refreshUndated` / `stampUndated` job options, decided up front and acted on after
the downloads. Don't put it back: the count is not known until the folder has been read, and
by the time the downloads are done there is nothing left to act on.

**There is more than one question now.** `settle_quick_floor` asks a quick scan how far
back to go when no run qualifies as a floor but the index already holds something - a full
listing is hours on a large library, and an index in the folder may be perfectly recent,
built by an older version, a restored backup, or a run whose history file was lost. It is
offered rather than taken: `last_indexed` says when an entry was last written, not that
everything was seen, so **the default is the whole listing** - the answer that cannot leave
a gap.

`answer_job` validates against `ANSWER_CHOICES`, the union of both questions' answers. The
run only reads the reply to the question it actually asked, so one list is enough to keep
nonsense out at the door. The ui keys its panel on the question **name**, not on the count:
both arrive as a `question` event with a count, and keying on that alone showed the undated
buttons for whichever question asked last.

A test that drives `run_bookmarks`, `run_update` **or `run_quick`** for real **must** stub
`Job.ask` or the suite hangs - that is what `updating()` in `test_server.py` does, and what
`asked_quick()` does for the quick scan. `run_quick` only reaches the question when the
index is non-empty and no run qualifies, which is why the existing no-floor tests pass
without stubbing: their `downloadfolder` is an empty tmp path, so `read_index` returns
nothing and the question is never asked.

### A run can be paused, and there are exactly two places it may pause

Both are inside the request path, and both are before anything reaches disk:

1. `Repository.hold_if_asked`, at the top of the `my_request` loop, **before a request goes
   out**. This is where a run with nothing in flight waits.
2. `Repository.read_body`, which pulls a response body down in `chunk_size` pieces and
   raises `PausedException` between them. `my_request` catches it, waits at
   `hold_if_asked`, then **re-issues the same request from the start**.

The second exists because bodies used to arrive inside a single `session.request` call, so
pausing during a large pdf did nothing until the transfer finished - the button looked
broken. Requests are now made with `stream=True` and `read_body` fills in `_content` /
`_content_consumed` itself, which is what keeps streaming an implementation detail: every
caller still uses `.content` and `.text` unchanged.

**Abandoning a body is free, and that is the point.** Bytes are held in memory until the
caller has all of them and has judged them (`download_file` checks status and content type
before anything is written), so there is no part-written file to clean up and the retry
starts from nothing. **Only GETs are abandoned** - a GET can be asked for again, while
re-sending a login form or a mark-as-read is not the same as asking for a page twice.

A pause-retry does **not** increment `attempt`: the user pausing is not the server failing,
and it must not eat the retry budget.

**Do not add a third gate** inside a download or a save loop. A gate that can fire anywhere
can fire halfway through writing an epub, and the result - a truncated file whose name says
it is complete - is the exact failure `saved_intact` and `replace_superseded` exist to
prevent.

For the same reason `get_metadata` buffers a page's records and saves them only once the
whole page has been parsed. A page is one unit of work - fetched, parsed, then written - so
a page abandoned partway leaves no half-built entries and is simply asked for again. Saving
as each blurb was parsed made a part-read page a part-written index by definition.

It is deliberately **not** folded into `check_cancelled`, even though the two look alike.
`check_cancelled` is called from inside `wait`, so a hold there would stretch an ao3 rate
limit break and then return to a request ao3 had just told us to wait longer for.

Three things keep a pause from becoming a hang:

- the wait is in `pause_slice` slices, each checking `cancelled`, so **stop works through a
  pause**. The ui never disables Stop while paused, and there is a test per side of that
- a stop taken during a hold unwinds without emitting `released`, so the log never claims a
  run resumed when it actually stopped
- `hold_job` only sets a flag and answers 202 at once. It must not wait for the run to
  reach the gate, or the browser would hang for the length of a download

There is **no timeout**, unlike `Job.ask`. A question nobody answers has a safe default
(`skip`, which changes nothing); a pause has no safe default, because auto-resuming would
send an unattended run back at ao3. A paused run stays paused. The cost is that a long pause
holds an ao3 session that may expire - that surfaces as ordinary download failures on
resume, and the fix is to stop and start again.

**`held`/`released` are separate events from `paused`/`resumed` on purpose.** Those are
ao3's own rate limit break, which nobody chose and which ends by itself. They read almost
the same on screen and have nothing else in common, and collapsing them would leave the ui
unable to tell "wait, this will clear up" from "you stopped this, press Resume".

The ui tracks `held` and `holdPending` separately for the same reason the helper answers
immediately: the button says `Pausing...` until the run itself sends `held`, because saying
`Paused` on the button press would claim the run had stopped while it was still downloading.

### Pairing downloaded files to metadata

A file is matched to its index entry by the work id **at the start of the file name**,
followed by a separator: `/^(\d+)(?:[\s_.\-]|$)/`. `99 Red Balloons.html` is work 99;
`99Red Balloons.html` is not a work number at all. This rule is in `bookmarks.ts`
(`workIdFromFilename`) and documented in both READMEs. A bookmark record's `id` field is
the **work number**, which is what makes collections (which store only work numbers) join
onto the index.

### Nothing creates data.json just by reading it, or by clearing nothing

`FileOps.get_settings_json` returns `{}` for a missing file rather than opening it in `'a'`
mode. It used to create one, and since `/api/config` reads the saved username on every page
load, an empty `data.json` kept appearing in a bundle that is meant not to have one. The
launcher (`ao3-env.ps1`) does not create it either. `save_setting` still creates it when
there is something to write - which, now the console menu is gone, means only clearing a
password an older console install had saved.

**It also stops short of writing when asked to remove a key that is not there.**
`FileOps.initialize` clears the saved password on every start whenever `SavePassword` is off
- which in a bundle is always, because the bundler strips that setting out - so every run
was leaving a `data.json` holding `{}` behind, recording the absence of a key that had never
existed. Don't reintroduce a create-on-read, and don't let a no-op removal write.

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
collection. If you touch blurb rendering, both places change - that is intentional, and it
applies to the filters too: narrowing works the same way inside a collection.

**The filters narrow what is already on disk.** Title and author are case-insensitive
substring matches; the two date ranges are inclusive at both ends and compare through
`bookmarks.dateStamp`, the browser's half of `parse_text.get_date_stamp` - ao3 writes
`14 Dec 2024` on a listing and `2024-12-14` on a work page, and an index holds whichever the
run that wrote it saw, so both are normalised before comparing. Nothing here reaches ao3, so
filtering costs no requests and works with the helper stopped.

Three rules worth keeping:

- **filters narrow together.** Every one filled in has to match, which is what someone
  hunting for a single fic expects.
- **a work with no readable date is excluded by a date range, never kept.** It cannot be
  placed, and including it would make the range a lie - the same rule
  `works_updated_between` follows on the helper. With no date filter set it shows normally.
- **sorting is not filtering.** Date bookmarked and date created each sort either way, with
  undated works **last in both directions** - first on an ascending sort would bury every dated
  work under blanks. A sort does not show `(filtered from N)`, because it hides nothing.
  `date_created` is only filled by a per-work lookup the app does not run, so on a real library
  it is empty everywhere (0 of 1,482 when checked) - `sortHasNoDates` says so on screen rather
  than leaving a control that silently does nothing.
- **pagination follows the filtered set, and the page resets when it changes.** `page` is a
  `linkedSignal` sourced on `filtered` rather than on the input: staying on page 9 of a
  result that now has one page shows an empty listing and reads as the filter having found
  nothing. The heading says `(filtered from N)` for the same reason - a short listing must
  not be mistaken for a small library.

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
- **Keep `TERMINOLOGY.md` (project root) up to date with every change to the codebase.** It
  lists the project's terms (with the synonyms used in chat), each workflow's programmatic
  name, options and steps, and how every step works. Whenever a change adds, renames or
  removes a term, workflow, option or step - or changes what a step does - update that file
  in the same change. Take its facts from the code (`step_plan`, the `STEP_*` strings, the
  dialog's `picks*` computeds), not from memory.

## Data hygiene

`powershell_source/data.json` can contain the user's **ao3 password in plaintext** when
`SavePassword=true`. It is gitignored. Do not paste it, print it, or ship it - the bundler
deliberately does not seed `build/config/data.json`. The web UI never stores a password:
only the username, in `localStorage`, and only when "remember me" is ticked.
