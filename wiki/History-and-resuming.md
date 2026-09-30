Every run is written into the **History** tab (`runs/` in your library) the moment it logs in, and kept up to date as it goes. Each entry offers **Download log**, and **Download issues** when there is anything to report.

## What the status means

| Status | Meaning |
| --- | --- |
| **Running** | The helper is working on it now. Pinned at the top. *Not confirmed by the helper* means the helper hasn't answered yet; *on another helper* means another copy of the app started it. |
| **Paused** | You pressed Pause. |
| **Finished** | It reached the end. Some works may still have failed - see its issues. |
| **Stopped** | You pressed Stop. |
| **Abandoned** | A background run left paused too long. Ends like a stop. |
| **Failed** | Something ended it early - login refused or lapsed, library unreachable. The reason is on the entry. |
| **Interrupted** | The helper stopped, crashed or restarted mid-run. Its log goes up to its last save, at most about two minutes before. |

Whatever the status, what the run saved stays saved.

## Resuming [experimental]

**Resume** on a stopped, failed, abandoned or interrupted run carries on as that same run, with its settings. Also under **Custom run > Pick up where an earlier run left off**.

| Run | Resumable |
| --- | --- |
| Full scan, Quick Scan, custom run (all bookmarks or date range) | Yes |
| Collection runs | Yes |
| Custom run over a slice of pages | No - page numbers move as bookmarks change |
| Specific fic, debug runs | No - just start again |

How it picks up:

- **Walks by date bookmarked** carry on from the page holding the last bookmark saved. If that bookmark has moved, it looks a few pages either way, then starts over.
- **Walks by date updated** start from the top again, since updated fics jump to the front.
- **After indexing**, it goes straight to checking and downloading the works the first attempt covered.
- **Collection runs** skip finished collections and carry on from each listing's last saved page, read again in case works shifted.
- **Answers** the first attempt gave to questions are reused.

A resumed scan keeps its first attempt's start time, so the next Quick Scan measures back to when the chain began.

Anything that can't be resumed can simply be run again: every run skips what is already downloaded and current.
