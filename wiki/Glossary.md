The words this project uses. `helper_files/TERMINOLOGY.md` in the repository has the full list, every workflow's steps included.

| Term | Means |
| --- | --- |
| **Work** | One fic on AO3, known by its **work number**. |
| **Bookmark** | A work, series or external work saved to your AO3 bookmarks. |
| **External work** | A bookmark of something hosted off AO3. Indexed, never downloaded. |
| **Non-bookmark** | A work in your index you didn't bookmark - found through a series or collection. |
| **Library** | The folder everything is saved in - on your computer, or in Dropbox. |
| **Index / index entry** | The `indexing/` folder: one JSON file per work, keeping its history. |
| **Index entry's date** | When AO3 (or FicHub) said the fic was last updated, as of the last time the entry was read - so it shows whether the entry's summary, tags and stats are up to date. Each downloaded file has its own version date at the end of its name; that, not the entry, is what says whether the file is outdated. |
| **Run** | One press of a button, from login to report. |
| **Step** | One stage of a run, ticked off in the run window. |
| **Log line** | One thing a run said as it went - "looking up work 7 on AO3", "new download: ..." - with when it was said. The run window shows each line's time in your AO3 time zone (User settings); **Download log** in History keeps the same lines stamped in UTC (`[2026-11-03 10:15:42 UTC]`), so logs from different places line up. Logs from older versions may have no times. |
| **Walk** | Reading a listing page by page, 20 works a page. |
| **Floor** | The date a walk stops at - for a Quick Scan, the date of the last scan that read your whole listing (a partly finished one counts only if all its indexing passed, after a warning); for a date range, its start. A retry keeps the first attempt's. |
| **Ceiling** | On a retry, the newest date a walk wants anything from - the day the first attempt started, or a date range's end. Fics dated after it are left for the next scan. |
| **Retry** | A new run of a run that has ended, picking up wherever you choose - see [[History and resuming]]. |
| **Resume** | Un-pausing a run that is still going. |
| **Outdated** | A file whose date is older than AO3's latest update. |
| **Undated file** | A file saved before names carried a date. |
| **Older copy** | A second, older file of the same work and format. |
| **Background run** | A run the helper finishes with the page closed. Dropbox only. |
| **Abandoned** | A background run left paused too long, ended by the helper. |
| **Interrupted** | A run cut off before it could say how it ended. |
| **The page** | The web app, in your browser. |
| **Helper** | The program that talks to AO3, on `127.0.0.1:4400` or Render. |
| **Bundle** | The page and helper built into `build/`, run with PowerShell and uv. |
| **Windows / Mac / Linux app** | The bundle with Python packed in, as a zip. |
| **Hosted copy** | The page on GitHub Pages and the helper on Render, for one person. |
