Every run is written into the **History** tab (`runs/` in your library) the moment it logs in, and kept up to date as it goes. Each entry names the **AO3 account** it logged in as (never the password) and offers **Download log** (every line timestamped in UTC, under the run's links, file types, options and settings), and **Download issues** when there is anything to report.

## What the status means

| Status | Meaning |
| --- | --- |
| **Running** | The helper is working on it now. Pinned at the top. *Not confirmed by the helper* means the helper hasn't answered yet; *on another helper* means another copy of the app started it. |
| **Paused** | You pressed Pause. |
| **Finished** | It reached the end. Some works may still have failed - see its issues. |
| **Partly finished** | It reached the end, but its **indexing broke off** - a page of your bookmarks, a collection or a fic would not load. The card says exactly where: which pages were read, which failed, and how far back in date it got. It never counts as complete for a Quick Scan. |
| **Stopped** | You pressed Stop. |
| **Abandoned** | A background run left paused too long. Ends like a stop. |
| **Failed** | Something ended it early - login refused or lapsed, library unreachable. The reason is on the entry. |
| **Interrupted** | The helper stopped, crashed or restarted mid-run. Its log goes up to its last save, at most about two minutes before. |

Whatever the status, what the run saved stays saved.

## Retrying [experimental]

**Retry** is on every run that has ended, whatever its status, and every workflow. It starts a **new run** (with its own History entry), so a retry can be retried too. **Resume** now only means un-pausing a run that is still going.

The Retry window shows how each step went and the last one that finished, and offers:

- **From the top** - the whole run again, asking its questions afresh. A Quick Scan covers the same dates as the first attempt.
- **Start its indexing from the top** - every listing read again from page 1, then everything checked and downloaded.
- **Carry on from where its indexing stopped** - walks that finished are taken from your index; one that broke off carries on from the date it had got down to - found again however far the pages have moved since; then everything is checked and downloaded.
- **Start its downloads from the top** - every work it had settled on, checked and downloaded again (every format, on a run that overwrites).
- **Carry on from where its downloads stopped** - only what it hadn't saved yet: nothing for a fic it finished, the missing formats of one it was partway through, every format of one it never reached.
- **Just the works it could not get** - only its failures, and only their missing formats. For a fic run, just those fics.

The one that picks up from the first step that did not finish is chosen for you. Also under **Custom run > Retry an earlier run**.

How it carries on:

- **Walks by date bookmarked** carry on from the page holding the last bookmark saved. If that bookmark has moved, it looks a few pages either way, then starts over.
- **Walks by date updated** start from the top again, since updated fics jump to the front.
- **Collection runs** skip finished collections and carry on from each listing's last saved page, read again in case works shifted.
- **Answers** the first attempt gave to questions are reused.
- A custom run over a slice of pages can only be retried from the top - page numbers move as bookmarks change.

A retried scan keeps its first attempt's start time, so the next Quick Scan measures back to when the chain began.
