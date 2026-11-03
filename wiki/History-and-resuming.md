Every run is written into the **History** tab (`runs/` in your library) the moment it logs in, and kept up to date as it goes. Each entry names the **AO3 account** it logged in as (never the password) and offers **Download log** (every line timestamped in UTC, under the run's links, file types, options and settings), and **Download issues** when there is anything to report. The tab lists your 100 most recent runs; older ones stay in `runs/` but are not shown.

## What the status means

| Status | Meaning |
| --- | --- |
| **Running** | The helper is working on it now. Pinned at the top. *Not confirmed by the helper* means the helper hasn't answered yet; *on another helper* means another copy of the app started it. |
| **Paused** | You pressed Pause. |
| **Finished** | It reached the end and got everything it set out to: every listing page and fic indexed, every format downloaded. Bookmarks that were never works (series, external works, deleted works) don't count against it. |
| **Partly finished** | It reached the end, but **some indexing failed** - a page of your bookmarks, a collection, or a fic's own page would not load (AO3 down or in maintenance, an error status such as 500, 401, 403 or 404, or a page that was not what was asked for) - or **some fics or formats could not be downloaded**. The entry says exactly what. It counts as a Quick Scan floor only when **all its indexing passed** and none of its failed downloads were down to AO3 maintenance - and then the Quick Scan warns first, naming the works it missed, and offers to choose a different scan. |
| **Stopped** | You pressed Stop. |
| **Abandoned** | A background run left paused too long. Ends like a stop. |
| **Failed** | Something ended it early - login refused or lapsed, library unreachable - or **every part of its indexing failed and nothing was downloaded**. The reason is on the entry. |
| **Interrupted** | The helper stopped, crashed or restarted mid-run. Its log goes up to its last save, at most about two minutes before. |

Whatever the status, what the run saved stays saved.

**Every failure says why**: *AO3 was down for maintenance*, *AO3 answered with status 404* (or
401, 500...), *AO3 could not be reached*, or *the page AO3 served had nothing on it that could be
read* - for a listing page, a fic's page, and a file alike, in History and in the issues file.

## Resuming

**Resume** only un-pauses a run that is still going - after you pressed **Pause**. A run that has
ended is never resumed; it is **retried**.

## Retrying [experimental]

**Retry** is on every run that has ended - finished, partly finished, failed, stopped,
interrupted or abandoned - from its History entry, or from **Custom run > Retry an earlier
run**. A retry is a **new run** with its own History entry, linked both ways to the run it
retries, so a retry can be retried in turn.

From History, **Retry** opens straight on how to retry that run; from Custom run you pick the run first, then choose how. Before it goes on, the Retry window lists **the original run's dates and settings** - for a
Quick Scan, back to its floor and up to the day it first started; for a date range, the range;
its file types and the options it had ticked - and asks you to tick that you understand the
retry uses those, not today's date or settings chosen now.

**Retrying a partly finished run.** It reached the end, so there is nothing to carry on from -
both carry-on choices are greyed out (except on Download several fics). Instead:

- **If some indexing failed**, a warning says so and *Start its indexing from the top* is chosen
  for you - a fic that was not indexed cannot be downloaded, so it may have missed some.
- **If only downloads failed**, *Just the works it could not get* is chosen for you: it takes the
  fics and formats still missing and gets just those.
- **Download several fics** is chosen *Just the fics it could not get* either way - it reads each
  of those fics' pages again, so it is safe after an indexing failure too.

### The ways to retry

| Choice | What it does |
| --- | --- |
| **From the top** | The whole run again, as if fresh, with the same workflow and options and the first attempt's floor and ceiling, asking its questions afresh. |
| **Start its indexing from the top** | Every walk read again from its start - its ceiling, if it has one (below), otherwise page 1 - then everything checked and downloaded. Unlike *from the top*, the first attempt's answers are reused. |
| **Carry on from where its indexing stopped** | Walks that finished are taken from your index - no requests. A walk that broke off carries on from the date it had got down to. A walk that never started starts at its ceiling (below). Then everything is checked and downloaded. |
| **Start its downloads from the top** | The works it had settled on, every format judged afresh against the index: a missing or older copy is fetched, a current one kept. On a run that overwrites, every format is fetched again. |
| **Carry on from where its downloads stopped** | Only what it hadn't saved: nothing for a fic it finished, the missing formats of one it was partway through, every format of one it never reached. Even on a run that overwrites, what it already saved is not fetched again. |
| **Just the works it could not get** | Only its failures, and only the formats each is missing. For a fic run, just those fics. |

The window shows how each of the run's steps went and the last one that finished, and picks
the choice that carries on from the first step that did not finish. The two download choices need the run to have reached its downloads: works are settled on as the check step starts, so a run stopped while indexing has them greyed out. The default: indexing broke off →
*carry on from where its indexing stopped*; stopped after indexing → *carry on from where its
downloads stopped*; finished with failures → *just the works it could not get*; otherwise
*from the top*. Choices that cannot apply are greyed out, with the reason.

### Which choices each workflow has

| Workflow | From the top | Start its indexing from the top | Carry on from where its indexing stopped | Start its downloads from the top | Carry on from where its downloads stopped | Just the works it could not get |
| --- | --- | --- | --- | --- | --- | --- |
| **Full Scan** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Quick Scan** (with or without a date range) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Custom run** - all bookmarks, or a date range | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Custom run** - a slice of pages | ✓ | ✓ | – | – | – | ✓ |
| **Index your collections** / **index a collection by link** | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Download several fics** | ✓ | – | – | – | ✓ (*carry on from where it stopped*) | ✓ (just those fics) |
| **Download a fic** | ✓ | – | – | – | – | ✓ |
| **Debug runs** (combined run, update incomplete, new bookmarks only) | ✓ | – | – | – | – | – |

- The two download choices also need the run to have **reached its downloads** - a run stopped
  while indexing has them greyed out. *Just the works it could not get* needs the run to have
  had failures.
- **Both carry-on choices are greyed out once a run has finished both its indexing and its
  downloads** - there is nothing left to carry on from. Start its indexing or its downloads
  from the top instead, or retry just the works it could not get.
- **Download several fics** carries on fic by fic: a fic it saved in every format is passed
  over without being looked up, the one it was partway through gets only its missing formats,
  and every fic it never reached is done in full. A single fic is quick to fetch again, so it
  has no carry-on - retry it from the top.
- **Carry on from where its indexing stopped** differs by workflow: every walk - the Full
  Scan's, a custom run's, a Quick Scan's two - starts from its ceiling unless it had got further;
  collection runs take finished collections from your index and carry on each unfinished one
  from its last saved page. See below.
- **A slice of pages cannot be carried on**: page numbers move as bookmarks change.
- **The fic runs** have no listing to walk. *Just the fics it could not get* retries only those
  fics, and only their missing formats.

### How a walk is picked up again

A walk is one read down a listing of your bookmarks. Pages move between attempts - new bookmarks
push everything down, removed ones pull it up, and an updated fic jumps to the top of a listing
sorted by date updated - so a walk is never picked up by page number alone. Every page it reads
saves **the date it got down to**, in the order the listing is sorted by, and a retry looks for
**the first page now holding that date** (starting from the page it stopped on, going forwards
or backwards as far as it needs to), then walks on from there to the floor. If nothing in the
listing is that old any more, the walk starts again from page 1.

The **floor** is the date a walk stops at; the **ceiling** is the newest date a retry wants
anything from. Both are the first attempt's, kept by every retry in a chain.

| Workflow | Walks | Floor | Ceiling on a retry |
| --- | --- | --- | --- |
| **Full Scan** | 1, by date bookmarked | none - the whole listing | the day the first attempt started |
| **Quick Scan** | 2: by date bookmarked, then by date updated (just the first when there is no floor - it then reads everything) | the date of the last complete Full or Quick Scan, as the first attempt worked it out | the day the first attempt started, for both walks |
| **Quick Scan, date range** | 2, as above | the range's start | the range's end, or the day the first attempt started if that is earlier (with no start date, the first walk starts at page 1 - it also supplies the dates updated) |
| **Custom run, all bookmarks** | 1, by date bookmarked | none | the day the first attempt started |
| **Custom run, date range** | 1, by date updated | the range's start | the range's end, or the day the first attempt started if that is earlier |

On every retry - *from the top* included - a walk that **never started** starts at the page holding its ceiling; one that
**broke off** carries on from the date it reached (always on or before the ceiling); one that
**finished** is taken from your index. The ceiling counts: fics dated on it are indexed, fics
dated after it are left for your next scan. A first attempt always walks from page 1.

For a Quick Scan, that gives:

| Where the first attempt got to | By date bookmarked | By date updated |
| --- | --- | --- |
| The first walk did not start | ceiling → floor | ceiling → floor |
| Stopped during the first walk | date reached → floor | ceiling → floor |
| First finished, second did not start | from your index | ceiling → floor |
| Stopped during the second walk | from your index | date reached → floor |
| Both walks finished | from your index | from your index |

The debug new-bookmarks walk (combined run, new bookmarks only) starts at the same ceiling on a
retry. **Collection runs** and **fic runs** have no ceiling: a collection's listings are not
known to be in date order, and a fic run has no listing. **Collection runs** skip collections the first attempt finished (their works taken from your
index), and carry on each unfinished listing from its last saved page, reading it again in
case works shifted.

### What a retry checks before carrying on

- **Every fic the first attempt indexed still has its index file.** One that does not is
  indexed again from its own page.
- **Every file it saved is still in the folder, dated as the index says.** One that is missing,
  undated or dated differently is fetched again. Each index entry records which run last wrote
  it, so the log says when another run has changed one since.

### What carries through every retry

- The workflow, its file types and its **options** - overwriting included.
- The first attempt's **floor**, **ceiling** and start time, so the next Quick Scan measures back
  to when the chain began.
- The **answers** the first attempt gave to its questions - except on *from the top*, which asks
  again.
