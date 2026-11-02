# Retrying runs [EXPERIMENTAL]

How any run that has ended can be run again - from the top, or carrying on from the first step
that did not finish - and why each part works the way it does. (This was *Resume*; **Resume**
now means only un-pausing a run that is still going, in its own window.) The words used here are defined in
`TERMINOLOGY.md`.

## Which runs can be retried

**Every run that has ended**: finished, partly finished, failed, stopped, interrupted or
abandoned, of every workflow - and a retry is a new run with its own history file, so a retry
can itself be retried. A run still going is not offered: it is paused and resumed in its own
window.

| Way to retry | What it does | Offered on |
| --- | --- | --- |
| **From the top** | The same run again from its first step, asking its questions afresh. A quick scan covers the **same window** as the first attempt: back to its floor, and up to when the first attempt started. | Every run (a fic run needs the links it was given, which older fic runs did not keep) |
| **Start its indexing from the top** | Every listing read again from its first page - nothing taken from the earlier attempt but its window and the answers it was given - then everything checked and downloaded. | Full, quick and custom scans (a slice too), collection runs |
| **Carry on from where its indexing stopped** | Walks it finished are taken from the index; one that broke off carries on from where it stopped (see below); everything is then checked and downloaded, passing over the formats it already saved. | Those runs, but not a custom run over a slice - see below |
| **Start its downloads from the top** | Straight to the works it had settled on, every one checked and downloaded again by the usual rules - which on a run that overwrites means every format again. | Those runs, once they got as far as checking their files |
| **Carry on from where its downloads stopped** | Straight to the works it had settled on, fetching **only the formats it had not saved whole**: nothing for a fic it finished, the rest of one it was partway through (3 of 4 formats saved fetches the 4th), every format of one it never reached - even on a run that overwrites, since it already did the overwriting. | The same |
| **Just the works it could not get** | Only the works in its failures list, and only their formats still missing. For a fic run, runs again over just those fics. | Any scan, collection run or fic run with failures |

**How it knows which formats arrived.** Every format of every work saved whole - checked on disk
at its full length, as every download is - goes into the history file's `formatsDone`, carried
from attempt to attempt by the ways that carry on. The file is saved at least every two minutes
while lines are arriving, so a run killed outright may not have noted its last couple of minutes'
files: on an ordinary run those are passed over anyway (they are on disk and current), and on a
run that overwrites they are fetched once more.

The window picks **the way that carries on from the first step that did not finish**: a run whose
indexing broke off carries on with its indexing, one stopped after settling its works carries on
with its downloads, a finished run with failures retries just those, and a clean finished run
starts from the top. It also lists how each step went (`stepPlan` and `steps` in the history
file) and names the last one that finished.

**Why a slice cannot carry on.** A slice is chosen by page number, and page numbers do not
stay put: every bookmark added or removed since moves every page after it. Carrying on would
cover different bookmarks from the ones it was asked for, so only *from the top* is offered.

A run that has already been retried, or one older than a scan that has since finished, comes
with a warning, because retrying it will mostly go over ground already covered.

## Partly finished runs

A run that ended as it should, but whose **indexing broke off** - a page of your bookmarks that
would not load after its retries, a collection's listing, a fic's own page - is `partial`, not
`success`. What it indexed is kept and downloaded; the rest was never reached. Its history file
says exactly where (`indexFailures`): which listing or collection, the pages read, the page that
failed, the works indexed, and how far back in date the last page read reached. The checklist
marks the index step **failed**, and the History card and the issues file say the same.

**A partly finished run is never a floor for a quick scan** - only a `success` is - so the next
quick scan measures back to an earlier complete run, and nothing beyond the break is skipped.

## Where to find it

- **History tab → Retry [EXPERIMENTAL]** on any ended run's card opens a custom run with that run
  chosen and its default way of retrying picked.
- **Custom run → What this run covers → [EXPERIMENTAL] Retry an earlier run** lists every ended
  run to choose from.

The file types page shows the earlier run's file types, locked. The run then starts **as the
earlier run's own workflow** - a retried quick scan is a quick scan - with its file types and
options. The helper reads all of that from the earlier run's own history file, so nothing the
page sends can change it; a retry request carries no link of its own, and is not checked for one.

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
| a listing page is written | per walk (`walks.all`, `walks.bookmarked`, `walks.updated`): the page number, the **last bookmark on that page** (its bookmark id, and the date it was bookmarked), the works found so far, and whether the walk finished; plus the series marked so far (`seriesMarked`) and every external work the run has saved an entry for (`externalsSaved`) |
| a series is walked | the series walked so far (`seriesDone`) and the works they indexed (`seriesWorks`) |
| a non-bookmark is re-read | the ones done so far (`nonBookmarksDone`) |
| the file check starts | the **scope**: every work this run covers (`scope`) |
| a custom run over a date range finishes a fic | the fics done so far (`updateDone`) |
| a page of a collection's works or bookmarked items is read | per collection and listing (`collections.<name>.listings.work_ids` / `bookmark_ids`): the page number, every work number found so far, the external works and series among the bookmarked items (`externals`, `series`), and whether the listing finished; plus `seriesMarked` and `externalsSaved` |
| a collection is saved | that collection is `done`, with every work number it holds (`collections.<name>.works`) and, when the run follows subcollections or parents, the related collections it links to (`family`) |

A resumed run starts its own history file with a copy of this, and carries on adding to it, so
a resume that is itself interrupted can be resumed from wherever it got to.

## What resuming does, step by step

### Stopped while indexing

**A listing sorted by date bookmarked** - the full scan's walk, the custom run's all-bookmarks
walk, and the quick scan's first walk. The full scan and the custom run now ask AO3 for that
order by name rather than relying on it being the default, because this search depends on it.

Every page a walk finishes saves the last bookmark on it **and the date that bookmark
carries in the listing's own order** - date bookmarked, or date updated. That date is what a
retry looks for, never the bookmark itself: pages move between attempts (new bookmarks push
everything down, removed ones pull it up, an updated fic jumps to the top), and the bookmark
may have moved or gone, but the listing is still in date order, newest first.

1. The same listing, with the same sort and the same floor, is opened at the page the earlier
   attempt last wrote (say page 43).
2. The search is for **the first page that now holds anything dated on or before that date** -
   so the walk starts at the first fic on that day, wherever it is now:
   - everything on the page is newer → it has moved **down**, so the search goes forward
   - the page reaches the date → the search goes **back**, in case fics on that day now start
     on an earlier page
3. It goes as far either way as it takes, bounded only by the listing's length. The step
   doubles and then halves, so a listing that moved by a hundred pages costs a handful of
   requests, not a hundred.
4. **That whole page is indexed again** and the walk carries on to the run's original floor,
   exactly as the first attempt walked - nothing about the walk itself changes.
5. If nothing in the listing is dated that far back any more, the walk starts again from the
   first page, and says so. So does a walk saved by an older version, which recorded no date
   for a listing sorted by date updated.

**A listing sorted by date bookmarked** - the full scan's walk, the custom run's all-bookmarks
walk, and the quick scan's first walk. The full scan and the custom run ask AO3 for that order
by name rather than relying on it being the default, because this search depends on it.
Bookmarks made after the first attempt's baseline land above the resumed page and are not
read; they are after the baseline, so the next quick scan finds them.

**A listing sorted by date updated** - the quick scan's second walk and the custom run's date
range walk - is searched the same way, by the **date updated** it got down to. A fic AO3
updated since the first attempt jumps to the top, above the resumed page - but its new date is
after the first attempt's baseline, which is this retry's ceiling, so it is outside the window
anyway; the next quick scan finds it. Fics on or after the date reached were read by the first
attempt. It stops at the same floor as before.

**A walk the earlier attempt finished is not walked again** - its works are taken from the
index, and the checklist marks it *done in the earlier run*.

### The quick scan, specifically

- The floor is **the earlier attempt's floor**, not one worked out afresh: runs have finished
  since, and this is still that run. It is never asked again.
- Its index step is two walks, *by date bookmarked* then *by date updated*, and each saves
  whether it finished. Carrying on from where indexing stopped:

  | Where the earlier attempt got to | By date bookmarked | By date updated |
  | --- | --- | --- |
  | The first walk did not start | walked from page 1 | walked from page 1 |
  | Stopped during the first walk | carries on from the date it reached | walked from page 1 |
  | First finished, second did not start | taken from the index, no requests | walked from page 1 |
  | Stopped during the second walk | taken from the index, no requests | carries on from the date it reached |
  | Both finished | taken from the index, no requests | taken from the index, no requests |

  A walk taken from the index is ticked *done in the earlier run*. Whatever happens, both
  walks end the retry saved as finished, so a retry of the retry skips both.
  `test_a_quick_scan_carries_on_its_two_walks_from_wherever_it_stopped` runs all five.
- Either way, the *by date updated* walk may read past the first attempt's start on its way
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

### Collection runs

Both collection runs save their place after **every page** of each collection's works and
bookmarked-items listings, and mark each collection finished once its file is written.

- A collection the earlier attempt **finished** is not read at all. The works it holds are
  taken from the index (the earlier attempt indexed them) and downloaded with the rest.
- An **unfinished** collection has its profile read again (one request), then each listing
  that had not finished carries on from its **last saved page** - that page is read again, not
  skipped. A listing that had finished is not read again.
- Reading the saved page again is what keeps the resume from missing anything when the
  collection changed in between. A work removed pulls everything after it up a place, so a
  work that was at the top of the next page is now on the saved page, and gets read. A work
  added pushes everything down, which only means a work is read twice and kept once. Up to 20
  removals between attempts are covered this way.
- A collection's works listing may be ordered by **date updated**, where an updated work jumps
  to the front - onto a page the earlier attempt had already read. So when a resumed works
  listing ends with **fewer works than the collection's own count**, the pages before the
  saved one are read again for them. (Its order could not be checked against the live site
  when this was written; this makes the resume safe either way.)
- Your own collections listing is always walked again from the start - one request per 20
  collections - so a collection added since is not missed.
- Related collections (subcollections, parents) are followed on a resume too: a finished
  collection's saved `family` is queued as though it had just been read, so a relative the
  earlier attempt had not reached yet is read now, and one it had finished is skipped.
- A collection whose listing **failed** partway (an error, not a stop) is saved with what it
  had, as always, but not counted as finished, so a resume reads it again.
- Stopped once the download step had started: the collections are not read again at all, as
  with the scans - see above.

### Failed runs

Resumed the same way. A run that failed because the AO3 login expired simply logs in again.

## What is not covered

- Runs from before this feature have no saved progress and cannot be resumed; start them again.
- A walk's saved place is the last *finished* page. A page being read when the run stopped is
  read again.
- The search for a moved bookmark gives up after a few pages and starts the walk over rather
  than guessing.
