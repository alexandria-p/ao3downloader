# Resuming interrupted runs [EXPERIMENTAL]

How a full scan, quick scan or custom run that did not finish can be picked up where it left
off, and why each part works the way it does. The words used here are defined in
`TERMINOLOGY.md`.

## Which runs can be resumed

| Run | Resumable? |
| --- | --- |
| Full scan | Yes |
| Quick scan | Yes, with or without a date range |
| Custom run over **all bookmarks** (indexing or not) | Yes |
| Custom run over **a date range** | Yes |
| Custom run over **a slice of your bookmarks listing** | **No** - see below |
| Specific fic, collections, the debug runs | No - they are short, so starting again is the resume |

A run can be resumed when it **stopped**, **failed**, or was **interrupted**, and was made by a
version of the app that saves its progress (older runs have nothing to pick up from).

**Why a slice cannot be resumed.** A slice is chosen by page number, and page numbers do not
stay put: every bookmark added or removed since moves every page after it. A resumed slice
would be covering different bookmarks from the ones it was asked for, so it is listed but
greyed out, and says why when you hover over it.

Any unfinished run is offered, including one that has already been resumed, or one older than
a scan that has since finished. Those come with a warning, because resuming them will mostly
go over ground already covered.

## Where to find it

- **Custom run → What this run covers → [EXPERIMENTAL] Pick up where an earlier run left off.**
  Every other option on the page is then greyed out, and the next page lists the unfinished
  runs to choose from, each saying how far it got.
- **History tab → Resume [EXPERIMENTAL]** on an unfinished run's card opens that same custom
  run with the run already chosen.

The file types page shows the earlier run's file types, locked. The run then starts **as the
earlier run's own workflow** - a resumed quick scan is a quick scan, a resumed full scan is a
full scan - with its file types and options. The helper reads all of that from the earlier
run's own history file, so nothing the page sends can change it.

## How an interrupted run is recognised

A run writes its history file (`runs/<date>-<id>.json`) as soon as it tries to log in, saying
`status: "running"`, and writes its ending when it finishes. A run that never gets to write
its ending - the page was closed, the helper stopped or crashed - stays `running` for ever.

The page asks the helper which runs it is working on right now (`GET /api/jobs`). Any record
still saying `running` that the helper is not working on was interrupted, and the page
rewrites it as `status: "interrupted"`. If the helper is not running at all, nothing can be
running, so every such record was interrupted. A run in another tab is still listed by the
helper, so it is left alone.

This check happens:

- when you press any run's button - a spinner says *Checking your run history...* until it is
  done, and the run window opens after
- when the History tab loads, if any run still says `running`
- when the list of runs to resume is fetched

## The baseline: when a run's reach begins

Every run records a **baseline**: the moment its AO3 login succeeded. Runs can take all night,
so it is the date and time the run actually began looking at AO3, not when it finished.

- A resumed run **keeps the first attempt's baseline**, however many times it has been
  resumed. It is finishing that attempt's work, and anything AO3 changed after that moment is
  the next scan's to find.
- Each history file also records `resumes` (the run it picked up from) and `resumesFirst` (the
  first attempt of the chain), and the run that was picked up gets `resumedBy`. The History tab
  shows the link both ways.
- **A quick scan measures back to a run's baseline**, not to when it started or finished. So
  when *Anything that has changed since my last run* - or *Choose which earlier scan to measure
  back to* - lands on a resumed scan that finished, it measures back to when its **first**
  attempt logged in. That is what makes the chain unbroken: the first attempt covered AO3 as it
  stood at that moment, the resume finished that coverage, and the next quick scan picks up
  everything since.

Older runs have no baseline; their start time stands in.

## What a run saves as it goes

A `progress` section in the history file, written straight away each time:

| When | What |
| --- | --- |
| a step starts | which step (`step`, `stepLabel`) |
| a quick scan settles its floor | the floor it measures back to (`floor`) |
| a listing page is written | per walk (`walks.all`, `walks.bookmarked`, `walks.updated`): the page number, the **last bookmark on that page** (its bookmark id, and the date it was bookmarked), the works found so far, and whether the walk finished; plus the series marked so far (`seriesMarked`) |
| a series is walked | the series walked so far (`seriesDone`) and the works they indexed (`seriesWorks`) |
| a non-bookmark is re-read | the ones done so far (`nonBookmarksDone`) |
| the file check starts | the **scope**: every work this run covers (`scope`) |
| a custom run over a date range finishes a fic | the fics done so far (`updateDone`) |

A resumed run starts its own history file with a copy of this, and carries on adding to it, so
a resume that is itself interrupted can be resumed from wherever it got to.

## What resuming does, step by step

### Stopped while indexing

**A listing sorted by date bookmarked** - the full scan's walk, the custom run's all-bookmarks
walk, and the quick scan's first walk. The full scan and the custom run now ask AO3 for that
order by name rather than relying on it being the default, because this search depends on it.

1. The same listing, with the same sort and the same floor, is opened at the page the earlier
   attempt last wrote (say page 43).
2. The bookmark it saved last is looked for on that page.
3. If it is not there, the dates on the page say which way it went. The listing is newest
   first, so:
   - every bookmark on the page newer than it → it has moved **down** (new bookmarks pushed it),
     so page 44 is next
   - every bookmark older than it → it has moved **up** (bookmarks were removed), so page 42
   - the page straddles its day → the pages either side are tried
4. Once found, **that whole page is indexed again** and the walk carries on to the run's
   original floor.
5. If it is not found within a few pages - it was unbookmarked, say - the walk starts again
   from the first page, and says so.

Bookmarks made after the first attempt's baseline land above the resumed page and are not
read; they are after the baseline, so the next quick scan finds them.

**A listing sorted by date updated** - the quick scan's second walk and the custom run's date
range walk - **is always walked again from the first page.** A fic AO3 updates moves to the
top, so nothing in that listing stays put between attempts. It stops at the same floor as
before.

**A walk the earlier attempt finished is not walked again** - its works are taken from the
index, and the checklist marks it *done in the earlier run*.

### The quick scan, specifically

- The floor is **the earlier attempt's floor**, not one worked out afresh: runs have finished
  since, and this is still that run. It is never asked again.
- Stopped during the *bookmarks by date bookmarked* walk: that walk is picked up from its page
  as above, then the *by date updated* walk runs from the top.
- Stopped during the *by date updated* walk: the first walk is not repeated; the second runs
  again from the top.
- Either way, the *by date updated* walk now reads past the first attempt's start on its way
  down, so it keeps only works AO3 updated **up to the first attempt's baseline** - the
  **ceiling**. Anything updated after that is the next quick scan's to find, measured from the
  same baseline. A quick scan with a date range uses whichever is earlier: its own end date or
  the baseline.

### Stopped while walking marked series

The series marked so far are restored, and the ones already walked are skipped; the works
those found are carried into the download.

### Stopped while checking remaining non-bookmarks

The ones already re-read are skipped, and carried into the download.

### Stopped while reading your existing files

The step runs again from the start. If the earlier attempt **recorded an answer** to a
question - dating undated files, keeping only the newest copy - that answer is used again, and
the log says so. A question it never got an answer to is asked again. Anything the answer
already did (files renamed, say) simply is not found the second time.

### Stopped while downloading, or later

Indexing is skipped entirely: the run takes the works in its saved **scope** from the index,
checks them against your files again, and downloads what is still missing or outdated. Works
the earlier attempt already downloaded are now current, so they are skipped by the ordinary
rules - no list of finished downloads is needed. A custom run over a date range also skips the
fics it had already finished.

### Failed runs

Resumed the same way. A run that failed because the AO3 login expired simply logs in again.

## What is not covered

- Runs from before this feature have no saved progress and cannot be resumed; start them again.
- A walk's saved place is the last *finished* page. A page being read when the run stopped is
  read again.
- The search for a moved bookmark gives up after a few pages and starts the walk over rather
  than guessing.
