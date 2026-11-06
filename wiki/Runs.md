A **run** is one press of a button: it logs in to AO3, indexes, downloads, and reports.

## Which run to use

| Run | Where | Use it for | Cost |
| --- | --- | --- | --- |
| **Quick Scan** | Bookmarks | Everyday use: new bookmarks, and anything AO3 updated since your last scan | Small |
| **(Full scan) Reindex & Update All** | Bookmarks | Repairing the index, or catching a finished fic that was added to | Reads everything - hours on a large library |
| **Download/update a specific fic** | Bookmarks | One fic, by link or work number. Always re-downloads it | One fic |
| **Download/update several fics** | Bookmarks | A pasted list of links or work numbers (any separators, up to 500). Always re-downloads them | One fic each |
| **Import works found in your library** | Offered when a library opens, and under the tabs | Files in `works/` with no index entry: date them, index them, add formats | One fic each |
| **Custom run** | Bookmarks | A slice of pages, a date range, or working from the index without reading AO3 | Depends |
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
- **Check all non-bookmarks for updates too** - re-checks works you have indexed but not bookmarked: works added by URL or id, imported works, works indexed from a collection (with *Index and download encountered works*), and works in a series you have indexed. Their series are read first; it is not limited by a date range.
- **Overwrite existing downloads** - full scan and custom run only. Fetches every format again, for when you suspect a damaged file. If a file you have is **newer** than the version it would be replaced with, the run asks first (no, keep it, if you don't answer). The fic runs, which always replace, ask the same.
- **Save embedded images separately** - custom run only. Usually unnecessary: images are already inside the downloaded work.
- **Index and download encountered works** - collection runs only. Off: just records which works the collection holds. On: indexes and downloads them too.
- **Include subcollections / parent collections** - collection runs only. Follows the family, each collection once, up to 200.
- **Skip AO3 login?** - on every run's login page, below the username and password, off by default. Not recommended: logged out, private bookmarks are missed and fics restricted to AO3 users can't be reached, so they may have to come from FicHub instead. Scans of your own bookmarks or collections still ask for your username, never your password.

## Questions a run may stop to ask

- **Undated files** - files saved before names carried a date. Give them a date (renamed, nothing downloaded), re-download them, or skip them.
- **Older copies** - two copies of one work and format. Keep only the newest, or leave them.
- **How far back to go** - a Quick Scan with no earlier scan, but an index already there.
- **Try FicHub?** - at the end, when AO3 wouldn't give the run some works. Try FicHub, or leave them as failures.
- **Replace a copy of a work your index has no entry for?** - when a file in your library is for a work the index did not know when the run began, there is nothing to tell which version it holds. The run reads the date in the file's name (as *Infer date* does), recommends yes only if the incoming version from AO3 or FicHub is newer, and says why. **No** if you don't answer.
- **Replace a newer copy with an older version?** - on a run that replaces files, when the copy you have is newer than what would replace it (from AO3 or FicHub). **No** if you don't answer.
- **Take FicHub's older version?** - when FicHub's copy is older than your index says the fic is, and you have no file at all in a format you asked for. Yes takes the older version of just that format.

Closing the page or stopping takes the answer that changes nothing - except for the two FicHub questions, where it is yes.

## Pause and Stop

- **Pause** takes effect at once, in every workflow at every step - while logging in, while AO3 is still thinking about a request, during a rate-limit break, or between reads and writes of your library. Whatever was in flight is dropped and done again on Resume (the same fic looked up, the same file fetched, the login started again); a break carries on with only the time left of it. Nothing is ever half-written. It stays paused until you press Resume.
- **Stop** takes effect at once too, the same way, and keeps everything already saved.
- **Force stop** - in **History**, on the run pinned at the top - is the last resort for a run that will not stop or whose window has gone. It ends the run straight away, records it as *Stopped* with its log and issues, and lets another run start.
- A long pause can let your AO3 login expire. If works start failing after Resume, stop and start again.

## Background runs

Tick **Run as background task** on its own page, just before the login, to let the helper finish with the page closed.

- Only on the hosted copy - the bundle and the Windows, Mac and Linux apps don't offer it, since their helper stops when you close its window.
- Dropbox libraries only - the helper can't reach a folder on your computer without the page.
- Questions are answered up front, since nobody will be there.
- One run at a time. A banner says when one is going, and **Go to this run** opens it in History.
- A background run left **paused** for 10 minutes (`PausedRunTimeoutMinutes`) is abandoned, keeping what it saved.
- Restarting the helper - closing its window, or a deploy - ends a background run. See [[History and resuming]].

## At the end

Every run finishes with **Try FicHub** (when anything failed), then **Report any failures**:

- **Try FicHub** - first, if AO3 wouldn't give the run some works, it asks whether to try [FicHub](https://fichub.net), a mirror that keeps copies of AO3 works, even some AO3 no longer has. **Yes if you don't answer** within 30 minutes. What FicHub has is indexed and downloaded in your file types (not AZW3), and marked **From FicHub** in your library. If FicHub's copy is **older** than your index, it never replaces a file you already have and the index is left alone. On **Resolve issues**, FicHub follows the repair's own choices: a work only looked up gets just its index entry, your copies are kept unless you chose to replace outdated ones, and its files are renamed to match the new entry, keeping their own dates. Never tried for external works or series. Most useful for a fic you indexed before AO3 deleted it (the index keeps its number) and for a single fic fetched by link or number.
- **Failures** - works that wouldn't download. A later run tries again. A work FicHub couldn't give either says so.
- **Bookmarks that are not works** - series, external works, deleted works. Nothing to retry.
- **Copies to check by hand** - a new file saved, but an older copy couldn't be removed, or the save couldn't be confirmed.

**History > Download issues** saves all of it as one text file.

## Importing works already in your library

When a library opens and `works/` has files named for a work number that your index has no entry for, the page offers to import them. While there is anything to sort out, a **Resolve issues found with import** reminder sits just under the tabs, above whatever the tab shows, whichever tab you are on, and opens the same window - closing the window leaves it there, and its **×** hides it until you open the library again. Undated files of works already in your index are offered for dating too (with nothing else to import, the window finishes after the dates).

1. **Overview.** Under *Issues found in import:*, how many files are duplicates, how many have no date, and how many belong to works with no index - nothing listed yet. Choose **Repair now (recommended)**, **Not now** (reminded next time you open the library), **No, do not ask me again for these files** (listed in `import-excluded.json` and never counted or offered again), or **No, never ask me again** (no window and no reminder; User settings turns them back on).
2. **Duplicates** (only if a work has more than one file in the same format, however they are named). For each, **Keep most recent** (picked to begin with: by the date in each name, then by when each file was last changed - if that still can't tell, the removing step asks you), **Skip** (keeps every file and asks again next time - unless you tick **Don't ask this again for skipped files**), or **I'll choose**, which then shows each one in turn - each file with the date in its name and when it was last changed, the most recent at the top and picked to begin with (marked as only our best guess when we can't tell) - or **Skip for now** / **Skip, and don't ask me again for this file** below the files, with **Previous entry** and **Next entry** (which keeps the picked file), and, at the foot under **Sort any remaining in bulk**, **Skip for now** / **Skip, don't ask again** / **Keep most recent** with **Apply to the rest**. **Continue** waits until every one is sorted; **Back** returns to the list, and coming forward again picks up at the first one still to sort. Nothing is deleted until the next step, which removes the rest with a bar. A set marked Keep most recent that it can't tell stops the bar and asks: take our best guess (picked to begin with - date in the name, then most recently changed, then by name), choose the file yourself, or keep them all - and whether to do the same for any others like it. No answer in 5 minutes keeps that set. Removed files never appear on the later pages. When the repair has more than about 20 requests to make, its run window says so - leave it open until it finishes.
3. **Dates** (only if some files have none). Give each file a date, use one date for all, or skip any or all - a skipped row is greyed out. **Infer date** reads a date out of each file's name, however it is written (2024-03-04, 20240304, 03-04-2024, 14 Dec 2024...); what it found turns yellow and moves to the top. Switch between pages and one scrolling list; hover a long name to see it whole. Every file needs a date or a Skip tick before you can continue: a file with neither is highlighted, and a note says how many are left, with a button to skip them all. Nothing dated? The button says **Skip this step**. Tick **Don't ask this again for skipped files** to list every skipped file in `import-excluded.json`, so it is never offered for dating again (its work is still checked for a missing index entry).
4. **Dating.** A bar while the files are renamed, then how many were dated and any that couldn't be (folded away). A file of a work you have indexed is renamed the way the app names that work, with your date; any other keeps its name with the date added.
5. **Index** (only if some works have no entry - otherwise you go straight to the formats): fetch their index entries from AO3 now? **Yes**, **Not now** (offered again later), or **No, and do not ask again for these works** (listed in `import-excluded.json` with the files they have now - not asked about again unless a new file for that work turns up; their undated files can still be dated).
6. **Formats**: first which works to update - all with issues (the default), just those with date issues, just those with indexing issues, or **Skip this step**. Unless skipped: download them in other formats, and replace a copy when AO3 has a newer version (off by default; undated and current copies are never replaced).
7. If there is a lookup to do, or something to download or replace, the window moves on to the login - titled *Resolve issues found in your library*, listing what the repair will do - with **Start repair**: background (on a hosted copy), then the **AO3 login**, asked in case some of the works are restricted to AO3 users. You can tick **Skip AO3 login?**, but those works will then fail. With nothing to do, the window just closes. Once each work is indexed, its files are renamed to match it, keeping the date each one carries.

Imported works show as **Imported from an external source** in the Works tab, unless they turn out to be your bookmarks. While another run is going nothing is renamed or started; the offer comes back once that run has finished. **No, never ask me again** stops both the window and the reminder; turn them back on in User settings.
