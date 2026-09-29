# Terminology

The words this project uses, and what each means. Alternatives in brackets are words used for
the same thing in conversation.

## AO3 and what you bookmark

- **Work** [fic, fanfic, story] - one story on AO3, identified by its work number.
- **Work number** [work id, id] - the number in a work's AO3 address; every file for a work starts with it.
- **Bookmark** - something saved to your AO3 bookmarks: a work, a series, or an external work.
- **Individual work** - a work with its own entry on AO3. typically found by this app via your bookmarks, or through a series.
- **Series** - an AO3 series: an ordered set of works.
- **Series bookmark** [bookmarked series] - a bookmark of a whole series rather than one of its works.
- **External work** - a bookmark of a work hosted somewhere other than AO3; indexed, never downloaded.
- **Collection** - an AO3 collection; indexed as a list of the works it holds, and optionally the works themselves.

## Index properties

- **Bookmark type** [type] - what an index entry is: `individual work`, `series bookmark` or `external work`.
- **Bookmarked** [is_bookmark] - whether you bookmarked a work or series yourself (`true`/`false`, or absent when unknown).
- **Non-bookmark** - an individual work in the index with `bookmarked: false`: there because a run was led to it some other way, usually through another work's series or a collection.
- **From series** [from_series] - the series a work was found through; added to, never replaced.
- **From collections** [from_collections] - the collections a work was found through, by short name, when a collection run indexed its works; added to, never replaced.

## Reading AO3

- **Run** [job] - one use of a workflow, from pressing Start to its report.
- **Step** [checklist item] - one stage of a run, shown ticked, skipped, failed, or *done in the earlier run* (a resumed run's step its earlier attempt finished) in the run window.
- **Option** [checkbox, configuration] - a choice made before a run starts.
- **Question** - something a run stops to ask part-way through (undated files, older copies, how far back to go).
- **Scan** - can be used either to describe a scan workflow (full or quick), or to describe reading the library's existing files (the check step).
- **Cleanup** - the step that removes older copies you chose to remove.
- **Report** - the end-of-run lists of what failed, was skipped, or needs checking.
- **Run status** [outcome] - what a run's History entry says about how it went. Every status keeps what the run saved, and offers **Download log** and (when there are any) **Download issues**:
  - **In progress - running** - the helper is working on it now; pinned at the top of History. Its own entry says *Running*, or *Running - not confirmed by the helper* (the helper has not answered yet), or *Running on another helper* (started from another copy of the app on the same library). Record status `running`.
  - **In progress - paused** - the user pressed Pause; it waits before its next request, never mid-save. Not a record status: the record still says `running`. A background run left paused becomes *Abandoned*; any other stays paused until resumed or stopped.
  - **Finished** [successful] - reached its end. Individual works may still have failed; they are in its issues. Record status `success`.
  - **Stopped** - the user pressed Stop; it ended at the next safe point. Record status `stopped`.
  - **Abandoned** - see below. Record status `abandoned`.
  - **Failed** - an error ended it early (login refused, login lapsed, library unreachable); the reason is on the entry. Record status `failed`.
  - **Interrupted** - see below. Record status `interrupted`.
- **Interrupted** - a run that never wrote its ending (the page closed, the helper stopped, crashed or restarted - a deploy included). The page marks its history file `interrupted` once the helper confirms it is not working on it. Its log and issues go up to its last save, at most about two minutes behind.
- **Resume** [pick up where it left off, re-attempt] - carry on a stopped, failed, abandoned or interrupted scan or collection run as that same workflow, with its settings. See `RESUMING.md`. [EXPERIMENTAL]
- **Baseline** - the moment a run's AO3 login succeeded; a resumed run keeps its first attempt's. What a quick scan measures back to.
- **Progress** [checkpoint] - what a run saves in its history file as it goes, so it can be resumed: its step, each walk's page and last bookmark, series walked, and its scope.
- **Scope** - every work a run covers, saved as its file check starts; a run resumed after that point works from it without indexing.


## What happens in a run
- **Indexing** [the index step, reindexing] - writing or updating index entries from what AO3 shows.
- **Index entry** [entry, record, JSON file] - metadata for one work, series or external work saved as a JSON file. Each index file keeps a history. When a fic is indexed again in a future run, a new entry is added to the index file only if something actually changed, so you can see when a work gained chapters or was updated.
- **Listing** [bookmarks listing] - an AO3 list of blurbs, 20 to a page, such as your bookmarks.
- **Page** [listing page] - one page of a listing (20 blurbs). Not to be confused with "the page", the web app.
- **Blurb** - one entry on a listing: a work's (or series') summary box.
- **Walk** - reading a listing page by page from the first, to index what is on it.
- **Floor** - the date a quick scan walks back to: the day of the last qualifying scan's baseline.
- **Ceiling** - the newest date a walk keeps works from. A resumed quick scan's by-date-updated walk keeps works updated up to its first attempt's baseline.
- **Anchor** - the last bookmark a walk saved; a resumed walk finds it again to know where to carry on.
- **Series walkthrough** [walking a series] - reading a series' own AO3 page to index every work in it.
- **Marked for walkthrough** - a series queued, during indexing, to be walked once indexing is over.
- **Crawl** [the long way round] - the old download path that re-reads the listing and opens each work's page; now only a fallback.
- **Rate limit** - AO3's limit on how fast requests may arrive; why runs avoid extra requests.
- **Run history** [run record, history file] - one JSON file per run in `runs/`, saying what it did.

## Saved works

- **File** [download, copy, downloaded file] - a work saved in one format, in `works/`.
- **Format** [file type] - HTML, EPUB, PDF, MOBI, AZW3, or JSON (which is the index itself).
- **Dated name** - a file name ending in the date AO3 last updated the work, e.g. `123 Title - Author 2025-06-01.html`.
- **Undated file** - a file saved before names carried a date; its version is unknown.
- **Outdated** [stale, behind] - a file whose date is older than AO3's latest update in the index.
- **Older copy** [duplicate] - a second, older-dated file of the same work and format.


## Your library

- **Library** [downloads folder, library folder] - the folder everything lives in: a folder on this computer, or the Dropbox app folder.
- **Dropbox app folder** - `/Apps/ao3-downloader` in Dropbox; the only Dropbox folder the app can see.
- **Library folders** - `indexing`, `collections`, `images`, `runs` and `works`, created when a library is opened.
- **Index** - the `indexing` folder: one JSON file per work, plus `series/` and `external/` subfolders.
- **Run history** [run record, history file] - one JSON file per run in `runs/`, saying what it did.


## The app

- **The page** [web app, site, Angular app] - the Angular app you use in the browser; it owns the library.
- **Helper** [local helper, server, python] - the program that talks to AO3: on `127.0.0.1:4400` normally, or on Render for a hosted copy.
- **Hosted copy** [hosted helper, GitHub Pages copy, Render] - one person's copy on the web: the page on GitHub Pages under `/app/`, the helper on Render. Set up by `HOSTING.md`, deployed by the `deploy hosted app` workflow.
- **Passcode** - what a hosted copy asks for before anything works. Checked by the helper, remembered by the browser once accepted. Its value is a secret (`AO3DOWNLOADER_PASSCODE`); `RequirePasscode` in settings.ini only turns it on.
- **Passcode window** [passcode gate, passcode popup] - the window a passcode-protected page opens with, and comes back to if the helper refuses the saved passcode.
- **Sealed login** [encrypted login, credentials] - the AO3 username and password, encrypted by the page with the helper's public key. Good for five minutes and one use.
- **Key pair** [public key, private key] - the RSA keys a login is sealed and opened with. The private key is a secret on the helper (`AO3DOWNLOADER_PRIVATE_KEY`); the public key is built into the page.
- **Page config** [app-config.json] - the page's own small config: where the helper is (`HelperUrl`), whether to ask for a passcode, and the public key. Public, so it never holds a secret.
- **Library store** [PageStorage, the page's storage] - how the helper reads and writes the library: it asks the page, which does it.
- **Setting** [config] - the properties in the config/settings.ini file which are used by the Page and Helper (for example, it specifies the length of cooldown in seconds between each request to AO3)
- **Hosting settings** - `HelperUrl` (where the page finds the helper), `RequirePasscode` and `PageOrigin` (the page allowed to call a hosted helper). For a hosted copy the deploy workflow writes every setting from a GitHub variable named after it in upper snake case (`HELPER_URL`, `EXTRA_WAIT_TIME`, ...).
- **Console logging** [EnableConsoleLogging, ENABLE_CONSOLE_LOGGING] - a setting that makes the helper print every request (method, path, answer) and every line a run says, tagged `[run xxxxxxxx]`, to its own console - the PowerShell window, or Render's Logs tab. Never the passcode or the login. Off by default. Not the same as debug logging, which writes more to the helper's log file.
- **Background run** [background task, backgrounded run] - a run the helper carries on with after the page is closed, reaching the Dropbox library itself. Chosen with *Run as background task*; recorded as `background` in its run history.
- **Up-front answers** [pre-answered questions] - a background run's answers to the questions it could stop to ask (undated files, older copies, how far back a quick scan goes), given before it starts because nobody will be there to answer. A question it was not given an answer for gets the one that changes nothing.
- **Run in progress** [active run] - a run the helper is working on right now. Only one at a time: while there is one, a banner says so at the top of the page, the run buttons are held, and a second start is refused.
- **Pinned run** [in-progress panel] - the run in progress, shown at the top of the History tab. *View progress* opens its progress window again for a background run.
- **Abandoned** [abandoned run] - a background run the helper ended because it was left paused longer than `PausedRunTimeoutMinutes` (10 by default). It ends the way a stopped run does - everything saved is kept - and can be resumed. The page asks before a background run is paused, and says when a paused one will be abandoned. Ordinary runs are never abandoned.
- **Paused-run timeout** [PausedRunTimeoutMinutes, PAUSED_RUN_TIMEOUT_MINUTES] - the setting for how many minutes a paused background run is kept; 0 is never.
- **Continue in background** - the button that closes a background run's progress window and leaves the run going.
- **Download log** - the button on a run's History entry that saves everything the run said in its window, line by line, as a text file. Kept in the run's history file as it goes, so a run that was stopped, abandoned or interrupted has one too. An interrupted run's stops at its last save.
- **Run log save interval** - how often a running run saves its history file while it prints: when a line arrives at least 120 seconds after the last save (fixed, not a setting). Checkpoints and the run ending save at once. Every save carries the issues and fic lists as well as the log.
- **Download issues** - the button on a run's History entry that saves everything it reported (failures, copies to check, bookmarks that are not works) as one text file. Was *Export all issues* at the end of a run.
- **Deployment variable** [GitHub variable, repository variable] - a GitHub Actions variable the deploy workflow turns into a `settings.ini` key: `EXTRA_WAIT_TIME` becomes `ExtraWaitTime`. Every key has one except `SavePassword`.

---

# Workflows

* Run
* Workflow (logic of a run)
* Steps (stages in a workflow)
* Options (run configuration)

- **Workflow** [action, button] - describes the logic executed by a run. Each workflow type is a different collection of steps that will be executed by a run using that workflow: full scan, quick scan, custom run, and so on.

**Every workflow** also offers, on its login step:

- *Run as background task* - only for a library in Dropbox, signed in; greyed out for a folder on this computer, which the helper can only reach through the page. When ticked, it lists the up-front answers this workflow may need: *undated files* and *older copies* on any workflow that downloads works (not *undated files* when it overwrites every copy anyway), and *how far back to go* on a quick scan that is not measuring back to a chosen scan or a date range. A workflow that downloads nothing (a collection run not taking its works, or JSON only) asks none. Its steps are the workflow's own, unchanged.

## Quick scan

- **Programmatic name:** `quick`
- **Options:**
  - What it covers: *anything changed since my last run* (default), or *choose which earlier scan to measure back to*
  - *[DEBUG] choose my own date range* (only with debug tools on)
  - *Get all works from encountered series*
  - *Include any changes to non-bookmarks* - not limited by the floor or date range
  - File types (JSON always on)
  - An acknowledgement of its limits, shown until turned off
- **Steps:**
  1. Log in to AO3
  2. Index bookmarks added since your last run
  3. Index works AO3 has updated since your last run
  4. Index works in series marked for walkthrough
  5. Check remaining non-bookmarks for updates (only when chosen)
  6. Read your existing downloaded files
  7. Download or update works as necessary
  8. Cleanup
  9. Report any failures

With a date range, steps 2 and 3 read "…in that date range".

## Full scan

- **Programmatic name:** `bookmarks`
- **Options:**
  - *Overwrite existing downloads, even if there has been no update*
  - *Get all works from encountered series*
  - *Include any changes to non-bookmarks*
  - File types (JSON always on)
  - An acknowledgement, every time
- **Steps:**
  1. Log in to AO3
  2. Index every bookmark
  3. Index works in series marked for walkthrough
  4. Check remaining non-bookmarks for updates (only when chosen)
  5. Read your existing downloaded files
  6. Download or update works as necessary
  7. Cleanup
  8. Report any failures

## Download/update a specific fic

- **Programmatic name:** `work`
- **Options:**
  - A link or work number
  - *Get all works from encountered series*
  - File types
  - Always replaces the fic's own files; no overwrite checkbox
- **Steps:**
  1. Log in to AO3
  2. Index this fic
  3. Index works in series marked for walkthrough
  4. Read your existing downloaded files
  5. Download this fic
  6. Cleanup
  7. Report any failures

## Custom run

- **Programmatic name:** `custom`
- **Options:**
  - What it covers: *all bookmarks*, *a slice of your bookmarks listing* (start page, number of pages), *[EXPERIMENTAL] pick up where an earlier run left off* (then runs as that run's own workflow and settings, which are greyed out - see `RESUMING.md`), or *choose my own date range* (from, and optionally to)
  - *Skip indexing* - work from the index already saved (JSON is then off)
  - *Overwrite existing downloads, even if there has been no update*
  - *Save embedded images separately*
  - *Get all works from encountered series*
  - *Include any changes to non-bookmarks* - not limited by the date range; not offered when skipping indexing
  - File types
- **Steps (all bookmarks, or a slice):**
  1. Log in to AO3
  2. Index every bookmark, or Read the index already saved (when skipping indexing)
  3. Index works in series marked for walkthrough
  4. Check remaining non-bookmarks for updates (only when chosen)
  5. Read your existing downloaded files
  6. Download or update works as necessary
  7. Save embedded images separately (only when chosen)
  8. Cleanup
  9. Report any failures
- **Steps (a date range):**
  1. Log in to AO3
  2. Index works AO3 has updated since that date (shown skipped when skipping indexing)
  3. Find indexed works updated in that date range
  4. Index works in series marked for walkthrough
  5. Check remaining non-bookmarks for updates (only when chosen)
  6. Read your existing downloaded files
  7. Download or update each fic as necessary
  8. Cleanup
  9. Report any failures

## Index my collections / Index collection by URL

- **Programmatic names:** `collections` (your own, from `/users/<you>/collections`) and `collection` (any one, from a link)
- **Options:**
  - A collection link (`collection` only)
  - *Index and download encountered works* [collection works, `collectionWorks`] - index every work in the collections' works and bookmarked-items listings as they are crawled, then download them. Off: only the collections' files are written.
  - *Get all works from encountered series* - only offered with the option above
  - *Include subcollections* [`subcollections`] and *Include parent collections* [`parentCollections`] - also read each collection's subcollections, or its parent, and theirs in turn however far removed. Each related collection is indexed like the ones asked for, and its works too when *Index and download encountered works* is ticked. With both, siblings are reached through their parent. Each collection is read at most once per run, so a family whose members link to each other cannot loop; a run follows at most 200 relatives (`COLLECTION_FAMILY_LIMIT`) and says so if it stops there.
  - File types - only asked with the option above; without it the run is JSON only
- **Steps (collections only):**
  1. Log in to AO3
  2. Index your collections / Index this collection
  3. Cleanup
  4. Report any failures
- **Steps (with their works):**
  1. Log in to AO3
  2. Index your collections and the works in them / Index this collection and the works in it
  3. Index works in series marked for walkthrough (only when chosen)
  4. Read your existing downloaded files (only when downloading)
  5. Download or update works as necessary (only when downloading)
  6. Cleanup
  7. Report any failures
- Resumable (**Resume**, [EXPERIMENTAL]): a checkpoint after every page of each collection's works and bookmarked-items listings, and when each collection is saved. A resumed run skips finished collections, carries each unfinished listing on from its last saved page (read again, in case works moved), and re-reads the earlier pages if a resumed works listing comes up short of the collection's count. A `collection` run from before the link was saved cannot be resumed. See `RESUMING.md`.
- The run's link is saved as its `url`, shown in History, and reused when a `collection` run is resumed.

---

# Steps

### Log in to AO3
Used by: every workflow.
- Logs in with your AO3 username and password; nothing else can start until it works.
- Writes the run's history file first, so a refused login is still recorded.

### Index every bookmark
Used by: full scan; custom run (all bookmarks or a slice).
- Walks your bookmarks listing page by page, sorted by date bookmarked, one request per 20 bookmarks.
- **Resumed:** carries on from the page holding the last bookmark the earlier attempt saved.
- Writes an index entry for every work, series bookmark and external work; marks every one `bookmarked: true`.
- Marks series bookmarks for walkthrough, and the series of each work when the series option is on.
- **Custom run:** a slice walks only the pages asked for.

### Read the index already saved
Used by: custom run, when skipping indexing.
- Reads the index from the library; makes no requests.
- Marks series for walkthrough from what each entry records, when the series option is on.

### Index bookmarks added since your last run
Used by: quick scan.
- Walks your bookmarks sorted by date bookmarked, stopping at the floor.
- With no floor, reads everything, which makes the next step unnecessary.
- **Resumed:** carries on from where the earlier attempt stopped, as the full scan's walk does; skipped if that attempt finished it.
- **Date range:** stops at the range's start date, and keeps only works bookmarked in the range.

### Index works AO3 has updated since your last run
Used by: quick scan.
- Walks your bookmarks sorted by date updated, stopping at the floor.
- Skipped when the previous step already read everything.
- **Resumed:** always walked again from the top, keeping only works updated up to the first attempt's baseline.
- **Date range:** stops at the range's start, and keeps only works updated in the range.

### Index works AO3 has updated since that date
Used by: custom run (date range).
- Walks your bookmarks sorted by date updated, stopping at the range's start date.
- Shown as skipped when told to skip indexing.

### Find indexed works updated in that date range
Used by: custom run (date range).
- Picks, from the whole index, the works AO3 last updated in the range; no requests.
- Marks their series for walkthrough when the series option is on.

### Index this fic
Used by: specific fic.
- Reads the fic's own AO3 page: one request.
- Sets `bookmarked` from the page's bookmark button (Edit Bookmark = true, Bookmark = false).
- Marks its series for walkthrough when the series option is on.

### Index works in series marked for walkthrough
Used by: every workflow that indexes (including the debug runs).
- Reads each marked series' AO3 page: one request per 20 works in it.
- Skips works already indexed this run; updates existing entries keeping their `bookmarked`; new entries get `bookmarked: false`.
- Writes the series' own entry with its list of works.
- The works it indexes go on to be downloaded; skipped when nothing was marked.
- With *Include any changes to non-bookmarks*, the series of every non-bookmark not already indexed this run are marked here too, whether or not the series option is on.

### Check remaining non-bookmarks for updates
Used by: full scan, quick scan, custom run - only when *Include any changes to non-bookmarks* is chosen (and, on a custom run, not skipping indexing).
- Re-reads, from its own AO3 page, each non-bookmark the series walk did not reach: one request per work.
- Not limited by a floor or date range: every non-bookmark is checked.
- Updates the entry (including `bookmarked`, if you have since bookmarked it); a work that will not read is a failure.
- The works it re-reads go on to be downloaded; skipped when the series walk reached them all.

### Read your existing downloaded files
Used by: every workflow that downloads.
- Scans `works/` and matches files to works by work number.
- Asks about undated files, then about older copies (only for this run's works).
- Decides, per work and format, what is missing, outdated or current.
- **Overwrite** (full scan, custom run) treats every copy as needing replacing; **specific fic** always replaces that fic, and only that fic.

### Download or update works as necessary
Used by: full scan; quick scan; custom run (all bookmarks or a slice).
- Fetches every missing or outdated format straight from AO3's download address: one request per format.
- Newest works first, so a stopped run has done the most useful half.
- Replaces an outdated copy only once the new file is confirmed saved at full length.

### Download this fic
Used by: specific fic.
- As above, for the fic and any series works indexed with it; the fic itself is always replaced.

### Download or update each fic as necessary
Used by: custom run (date range).
- For each picked fic: re-reads its AO3 page (unless indexed this run), then downloads only what is missing or outdated.

### Save embedded images separately
Used by: custom run, when chosen.
- Opens each downloaded work's page and saves its images to `images/`: one extra request per work.
- Runs last, after the files are down.

### Cleanup
Used by: every workflow.
- Removes the older copies you chose to remove at the older-copies question.
- Keeps any file this run has since downloaded over, and anything if the run was stopped.
- Skipped when nothing was marked.

### Report any failures
Used by: every workflow.
- Lists works that would not download, bookmarks that are not works, copies that need checking by hand, and older copies marked for removal but not removed.
- Everything it lists can be exported as one text file.

### Steps used only by other workflows
- **Index bookmarks added since last time** - the debug "new bookmarks" and combined runs; walks until the first bookmark already indexed.
- **Download newly added works** - the same two runs; downloads what that walk found.
- **Read existing index for unfinished fics** - the update run; lists works the index says are unfinished.
- **Re-index each fic, then download or update as necessary** - the update run and the combined run; re-reads each unfinished fic's page.
- **Fetch any format still missing** - the combined run; fills formats missing from works the other passes left alone.
- **Index your collections** / **Index this collection** - the two collection runs. Reads each collection's profile, then its works and bookmarked-items listings (one request per 20), skipping a listing whose count has not changed.
- Either step, with *Include subcollections* or *Include parent collections*, then reads each related collection once the ones asked for are done - one at a time, queueing theirs in turn, never the same collection twice.
- **Index your collections and the works in them** / **Index this collection and the works in it** - the same, with *Index and download encountered works*. Never skips a listing on its count, because it indexes every work blurb on it: an existing entry keeps its own bookmark fields; a new one gets `bookmarked: false`; somebody else's bookmark notes and tags from a bookmarked-items listing are blanked, never written in as yours. Each work records the collection in `from_collections`, is read once however many collections hold it, and has its series marked when that option is on. Works in an unrevealed collection are indexed and held back from download. The works go on to the ordinary series, check and download steps.
