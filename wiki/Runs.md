A **run** is one press of a button: it logs in to AO3, indexes, downloads, and reports.

## Which run to use

| Run | Where | Use it for | Cost |
| --- | --- | --- | --- |
| **Quick Scan** | Bookmarks | Everyday use: new bookmarks, and anything AO3 updated since your last scan | Small |
| **(Full scan) Reindex & Update All** | Bookmarks | Repairing the index, or catching a finished fic that was added to | Reads everything - hours on a large library |
| **Download/update a specific fic** | Advanced options | One fic, by link or work number. Always re-downloads it | One fic |
| **Custom run** | Advanced options | A slice of pages, a date range, or working from the index without reading AO3 | Depends |
| **Index my collections** | Collections | Your own collections | 1 request per 20 works |
| **Index collection by URL** | Collections | Any collection, from a link | 1 request per 20 works |

Three more - *new bookmarks + incomplete fics*, *just incomplete*, *just new bookmarks* - are the pieces Quick Scan is made of. They only show when `EnableDebugTools=true` in [[Settings]].

## Quick Scan

It measures back to the start of your last **finished** Quick Scan or full scan, and walks your bookmarks twice:

1. **by date bookmarked** - catches old fics you only just bookmarked
2. **by date updated** - catches fics you bookmarked long ago that have since changed

It then downloads whatever either walk found. With nothing to measure back to, the first walk reads everything.

- **Choose which earlier scan to measure back to** - go further back if you think a recent scan missed something.
- What it gives up: anything missed before that date stays missed. Run a full scan now and then.

## Options

Each run asks its options, then which file types, then your login.

- **File types** - JSON is the index and always on. HTML starts ticked. Untick everything else for a metadata-only run, about a twentieth of the requests.
- **Get all works from encountered series** - also downloads the rest of each series.
- **Include any changes to non-bookmarks** - re-checks works you have indexed but not bookmarked (found through a series or collection).
- **Overwrite existing downloads** - full scan and custom run only. Fetches every format again, for when you suspect a damaged file.
- **Save embedded images separately** - custom run only. Usually unnecessary: images are already inside the downloaded work.
- **Index and download encountered works** - collection runs only. Off: just records which works the collection holds. On: indexes and downloads them too.
- **Include subcollections / parent collections** - collection runs only. Follows the family, each collection once, up to 200.

## Questions a run may stop to ask

- **Undated files** - files saved before names carried a date. Give them a date (renamed, nothing downloaded), re-download them, or skip them.
- **Older copies** - two copies of one work and format. Keep only the newest, or leave them.
- **How far back to go** - a Quick Scan with no earlier scan, but an index already there.

Closing the page or stopping takes the answer that changes nothing.

## Pause and Stop

- **Pause** takes effect at once. A file part-way down is dropped and fetched again on Resume - nothing is ever half-written. It stays paused until you press Resume.
- **Stop** ends at the next safe point and keeps everything saved.
- A long pause can let your AO3 login expire. If works start failing after Resume, stop and start again.

## Background runs

Tick **Run as background task** on the login step to let the helper finish with the page closed.

- Dropbox libraries only - the helper can't reach a folder on your computer without the page.
- Questions are answered up front, since nobody will be there.
- One run at a time. A banner says when one is going, and **Go to this run** opens it in History.
- A background run left **paused** for 10 minutes (`PausedRunTimeoutMinutes`) is abandoned, keeping what it saved.
- Restarting the helper - closing its window, or a deploy - ends a background run. See [[History and resuming]].

## At the end

Every run finishes with **Report any failures**:

- **Failures** - works that wouldn't download. A later run tries again.
- **Bookmarks that are not works** - series, external works, deleted works. Nothing to retry.
- **Copies to check by hand** - a new file saved, but an older copy couldn't be removed, or the save couldn't be confirmed.

**History > Download issues** saves all of it as one text file.
