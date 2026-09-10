# Alex Tips

Download and view saved fanfic as an Angular web app. Can be ran entirely locally.

![Alt text](Screenshot.png)

Downloads via the site go to whichever location is specified in the config/settings.ini -> DownloadFolder

## Development Build  
settings.ini and data.json can be found in the powershell_source directory
make sure to update the location of your downloads folder here.

### Running full project on your local
Open powershell
powershell.exe -ExecutionPolicy Bypass -File .\run_development_build.ps1
That starts both pieces — the local helper on port 4400 and the web UI on port 4200 — then leave the window open and go to http://localhost:4200.

Ctrl+C in that window stops both

### For running the GUI ONLY:

Open git bash CLI window, 

From the repo root:
npm --prefix GUI start
(or, cd GUI; npm start)

Then open http://localhost:4200.

## Build Artifact

### How to bundle it

(it's worth running uv run python dev/readme.py after a rewrite.(?))

Open powershell in the root directory:
powershell.exe -ExecutionPolicy Bypass -File .\generate_build_artifacts.ps1

Everthing gets bundled to the /build folder.

### How to run the build artifact

Open powershell in the /build directory:
powershell.exe -ExecutionPolicy Bypass -File .\Start-Application.ps1

This starts the local download helper on port 4400 and the web UI on port 4200
Leave the window open and go to http://localhost:4200.


# Original Readme

## What is this?

This is a program intended to help you download fanfiction from the [Archive of Our Own](https://archiveofourown.org/) in bulk. This program is primarily intended to work with links to the Archive of Our Own itself, but has a secondary function of downloading any [Pinboard](https://pinboard.in/) bookmarks that link to the Archive of Our Own. You can ignore the Pinboard functionality if you don't know what Pinboard is or don't use Pinboard.

## Quick Start

Dislike reading? Go directly to either [Windows install](https://nianeyna.github.io/ao3downloader/windows) or [Mac and Linux install](https://nianeyna.github.io/ao3downloader/mac-linux).

## Table of Contents

- [Announcements](#announcements): List of changes that may be of note for returning users (not a complete changelog).
- [Instructions](#instructions): How to install and run ao3downloader.
- [Menu Options](#menu-options-explanation): Explanation of the options you will see when you start ao3downloader and what they do. Note that most of these options will in turn present you with a series of prompts. These should largely be self-explanatory, however, if you are confused by any of the prompts your question may be answered in the [notes](#notes).
- [Notes](#notes): Explanation of some of ao3downloader's features and quirks that may not be immediately obvious. I recommend reading this.
- [Known Issues](#known-issues): List of bugs that I know about but haven't yet been able to fix. If you encounter strange behavior, there may be a workaround here.
- [Troubleshooting](#troubleshooting): If you encounter a problem running the script, please read this section carefully and do any relevant steps in order to the best of your ability before sending a bug report.
- [Contact](#questions-comments-bug-reports): How to get in contact with me. Don't be shy!

## Announcements

New, easier installation instructions are here! You no longer need to install python manually (no more version worries) or unzip any folders or any of that stuff. Just download and run one file. Plus, it can detect updates to the script and install them for you, so you don't have to check back here for updates anymore!

## Instructions

### Install Automatically

For the easiest experience, click on one of these links based on your operating system:

[Windows](https://nianeyna.github.io/ao3downloader/windows)

[Mac or Linux](https://nianeyna.github.io/ao3downloader/mac-linux)

This will take you to a page that contains a downloadable installation script and some instructions for how to use it. (They're very simple instructions, I promise.)

### Install With PyPi

If you know what you're about and don't care for install scripts, you can go directly to the ao3downloader PyPi package which is available [here](https://pypi.org/project/ao3downloader/).

### Install with uv

This is basically what the install script does, but broken out into manual steps in case you're having trouble running the install script for whatever reason:

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
2. Open a command prompt, power shell, or terminal window **pointed at the folder where you want your downloads to be saved**
3. Enter the following command: 
    ```
    uv tool install --python 3.12 --force ao3downloader@latest
    ```
4. Enter the following command:
    ```
    uv run ao3downloader
    ```
5. Anytime you want to run ao3downloader again, repeat steps 2 and 4. If you would like to update your ao3downloader version, repeat step 3.

## Web UI

There is a local web interface, with its source in the `gui_source` folder, for browsing your downloaded bookmarks and starting downloads without using the console menu. Start everything with:

```
.\run_development_build.ps1
```

That launches two things and then opens at <http://localhost:4200>:

- **the Angular app**, which reads your downloads folder in the browser and lists your bookmarks
- **the local helper** (`ao3downloader.server`), which performs the actual downloads

The helper exists because a web page cannot do this work itself. Ao3 sends no CORS headers, so a page cannot read it; a page cannot hold an ao3 login session; and the update scan has to read the ebook files on your disk. The helper listens on `127.0.0.1` only - nothing outside your machine can reach it - and it calls exactly the same code the console menu calls.

The page has two tabs, **Bookmarks** and **Collections**, each carrying the buttons that fill it.

The **Bookmarks** tab lists your indexed bookmarks and has:

- **Download newly added bookmarks** - the same as the console option 'download from ao3 link', pointed at `https://archiveofourown.org/users/<your username>/bookmarks`. Works already in your downloads folder are skipped, so a second run only picks up bookmarks added since the last one.
- **Update any bookmarks marked as incomplete** - the same as the console option 'download latest version of incomplete fics'. It scans your downloads folder for works that were incomplete and re-downloads any with new chapters.

The **Collections** tab lists your indexed collections and has:

- **Index my collections** - reads `https://archiveofourown.org/users/<your username>/collections` and saves a json file describing each collection. No works are downloaded; see [collection files](#collection-files) below.
- **Index collection by URL** - the same thing for any one collection on ao3, whether or not it is yours. Paste a link to it; any page of the collection will do, so a link copied straight out of the address bar works. The file it writes sits alongside your own collections and has exactly the same shape.

Clicking a collection opens what was recorded about it - maintainers, tags, challenge type, counts, the collection it belongs to and any subcollections - along with the works in it, in the same listing the Bookmarks tab uses. A collection records only the *work numbers* it holds, so a work that is in your bookmarks index is shown in full. A collection can also hold works you have never bookmarked: those are still listed, in the collection's own order, but by work number alone with a link to the work on AO3 - because the number really is all that is known about them. A line above the table says how many of them there are. A parent or subcollection that has been indexed too opens in the page; one that has not links out to AO3.

The two bookmark buttons ask which file types you want. JSON is always produced and cannot be unticked - it is the index this page reads, and it costs nothing extra, being read off the listing pages that have to be fetched anyway. Everything else is optional: HTML starts ticked because most people want it, but **unticking it leaves a metadata-only run**, which is far lighter on ao3's rate limit. Indexing reads one page per 20 works; every other file type costs a request per work on top of that, so a full re-download of 700 bookmarks is roughly 1,500 requests where indexing alone is about 40. It then asks the same questions the console menu does - which page to start on and which to stop after (0 for all of them), whether to follow series links, whether to save embedded images, and whether to look up publication dates - leaving out any that do not apply to the action you picked. Finally it asks you to log in to ao3. **Index my collections** has nothing to choose, so it goes straight to the login; **Index collection by URL** asks for the link first.

Start and stop are both positions in the whole listing, so you can fetch a slice out of the middle of it - pages 5 to 9, or page 12 onwards. That is mostly useful for picking up where a stopped run left off without refetching what you already have. Works keep the position they hold in the full listing either way, so a partial run does not renumber them.

While a run is in progress the dialog shows a progress bar, the file types and options you chose, the folder being written to, and the name of the fic being fetched right now along with the format it is being fetched in. A message appears if ao3 asks the script to slow down. **Leave the tab open while a download runs** - refreshing or closing it interrupts the run.

There is a **Stop** button throughout. Stopping is safe: the run finishes what it is writing and unwinds, so everything already saved is kept. It is not a rollback.

If a work has already been downloaded it is skipped rather than fetched again, which is what makes the first button 'newly added'. A work counts as already downloaded when it appears in <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> *and* a file exists for every file type you selected. If either is untrue - the log was deleted, or you asked for a format you did not download last time - it is fetched again and the file is overwritten in place. JSON metadata is the exception: it is always rewritten, so the metadata stays current even for works that are skipped.

On your login details: only your username is saved by the page, in browser storage. Your password is sent to the helper to log in to ao3 and is never written anywhere - let your browser's own password manager remember it if you want it filled in next time.

If you only want to browse bookmarks you have already downloaded, you can run the web app on its own with `npm --prefix gui_source start`; the download buttons will tell you the helper is not running.

To produce a copy you can move to another machine, run `.\generate_build_artifacts.ps1`, which gathers everything needed into a `build` folder. See INSTRUCTIONS.txt.

## File Naming and Indexing

Inside your downloads folder:

| Path | What lands there |
| --- | --- |
| `<!--CHECK-->indexing<!--INDEXING_FOLDER_NAME-->/` | One json file per bookmark - the index. |
| the folder itself | The works: html, epub, pdf and so on. |
| `<!--CHECK-->images<!--IMAGE_FOLDER_NAME-->/` | Images embedded in works, if you asked for them. |
| `<!--CHECK-->collections<!--COLLECTIONS_FOLDER_NAME-->/` | One json file per collection, if you have synced them. |

### How files are named

Every file - json, html, epub, pdf - is named from the '<!--CHECK-->FileNamePattern<!--INI_NAME_PATTERN-->' setting in <!--CHECK-->settings.ini<!--INI_FILE_NAME-->, which defaults to `{worknum} {title} - {author}`. That produces names like `34816549 No Paths Are Bound - Cataclysmic_Cal.html`. The result is then cut to the '<!--CHECK-->FileNameLength<!--INI_NAME_LENGTH-->' setting (50 characters by default), which is why longer titles end mid-word.

### The bare minimum for a file to be linked to its index entry

**The work number has to come first.** That is the only part of the name that matters for pairing a downloaded work with its json entry. The rule is exact:

- the digits at the **start** of the file name, and
- followed immediately by a space, `_`, `.` or `-` (or the name ends there)

So `34816549 No Paths Are Bound.html` links up. `No Paths Are Bound 34816549.html` does not, because the number is not first. `99Red Balloons.html` does not either, because nothing separates the digits from the title - that rule is deliberate, so a title that merely begins with digits is not mistaken for a work number, while `99 Red Balloons.html` is correctly read as work 99.

So for a file you bring in from somewhere else: **start the file name with the AO3 work id, then a separator.** Everything after that is free.

If you change the naming pattern so the work number is no longer first, indexing still works, but the web page can no longer pair works with it - every title opens on AO3 instead of your local copy. The line under the heading tells you when that is happening, by reporting how many works it found a downloaded copy for.

### What is inside an index file

Each json file keeps a history rather than being overwritten, so you can see how a fic changed between runs:

```json
{
  "id": "34816549",
  "link": "https://archiveofourown.org/works/34816549",
  "source": "https://archiveofourown.org/users/you/bookmarks",
  "position": 4,
  "last_indexed": "2026-09-10T12:34:56+00:00",
  "indexes": [
    { "indexed_on": "2026-09-01T10:00:00+00:00", "title": "...", "kudos": 12 },
    { "indexed_on": "2026-09-10T12:34:56+00:00", "title": "...", "kudos": 15 }
  ]
}
```

- `last_indexed` is updated every time the fic is indexed, whether or not anything changed
- a new entry is added to `indexes` only when the reading differs from the one before it
- `position` is where the fic sat in your bookmarks on that run, and is not part of the history - a fic sliding down the list is not a change to the fic

### <span id="collection-files"></span>Collection files

Both collection buttons write one json file per collection into `<!--CHECK-->collections<!--COLLECTIONS_FOLDER_NAME-->/`, named after the collection's ao3 name (the part of the url after `/collections/`) and cut to the same '<!--CHECK-->FileNameLength<!--INI_NAME_LENGTH-->' limit as everything else. Nothing is downloaded: a collection file records what the collection *contains*, by work id, so it pairs up with the fics you already have.

Each file is versioned the same way an index file is - `last_indexed`, plus an `indexes` list that only grows when something actually changed:

```json
{
  "name": "yuletide2024",
  "link": "https://archiveofourown.org/collections/yuletide2024",
  "source": "https://archiveofourown.org/users/you/collections",
  "last_indexed": "2026-09-10T12:34:56+00:00",
  "indexes": [
    {
      "indexed_on": "2026-09-10T12:34:56+00:00",
      "title": "Yuletide 2024",
      "description": "...",
      "maintainers": ["someone"],
      "tags": ["Yuletide"],
      "active_since": "01 Sep 2024",
      "created": "01 Sep 2024",
      "challenge_type": "Gift Exchange Challenge",
      "multifandom": true,
      "closed": true,
      "moderated": true,
      "unrevealed": false,
      "anonymous": false,
      "flags": ["Closed", "Moderated"],
      "fandom_count": 1193,
      "work_count": 4021,
      "bookmark_count": 12,
      "parent_collection": "https://archiveofourown.org/collections/yuletide",
      "subcollection_count": 12,
      "subcollections": ["https://archiveofourown.org/collections/..."],
      "work_ids": ["34816549", "..."],
      "bookmark_ids": ["..."]
    }
  ]
}
```

- `challenge_type` is one of `Gift Exchange Challenge`, `Prompt Meme Challenge` or `No Challenge`
- `multifandom` is simply whether the profile page's sidebar counts more than one fandom
- `parent_collection` and `subcollections` are links, not nested copies - a subcollection you own gets its own file
- `work_ids` and `bookmark_ids` are the work numbers in the collection's works and bookmarked items, which is exactly what the file names in your downloads folder start with

#### Re-indexing a collection you already have

Walking a collection's works is the most expensive thing this program does: one request per twenty works, so a collection the size of Yuletide runs to hundreds of requests on its own.

It is also usually unnecessary. The collection's profile page - which has to be fetched anyway - says how many works and bookmarked items it holds. When that total is the same as the one in the file from last time, the saved ids are kept and the listing is not walked at all. An unchanged collection therefore costs **two requests instead of hundreds**, and the console says so:

```
collection yuletide2024 still has 4021 works, so the saved ones are kept
```

Works, bookmarked items and subcollections are each judged on their own count, so a collection whose works are unchanged but which has gained a bookmark only re-walks the bookmarks.

The one case this cannot see is a collection that had one work added and another removed between runs, leaving the total unchanged. **Delete that collection's json file to force a full crawl.** A crawl that failed or was stopped is never mistaken for a complete one: nothing is written for a collection you stopped on, and a failed listing is stored as an empty list, which is always re-fetched.

## Getting Rate Limited

Ao3 limits by **how fast requests arrive**, not how many you make in total. Go too fast and it answers with `Retry-After` - often several minutes - which the script waits out and then carries on by itself. Nothing is lost, and the **Stop** button keeps everything already written.

Three things decide how often you meet it, in order of how much they matter:

**1. `<!--CHECK-->ExtraWaitTime<!--INI_WAIT_TIME-->` in <!--CHECK-->settings.ini<!--INI_FILE_NAME-->** - how long to wait after *every* request. `0` means "as fast as the network allows", which trips the limit almost immediately: indexing 700 bookmarks is 35 back-to-back page fetches. The default is 15 seconds. If you are being paused repeatedly, this is the first thing to change, and it is usually the only thing you need to change.

**2. Which file types you tick.** JSON metadata is read off the listing pages - **one request per 20 works** - and is always produced. Every other file type is fetched per work, which is one request for the work page plus one per format:

| Run over 700 bookmarks | Roughly |
| --- | --- |
| JSON only (metadata refresh) | 35 requests |
| JSON + HTML | 1,435 requests |
| JSON + HTML + EPUB | 2,135 requests |

So a metadata-only run - untick everything but JSON - is about a fortieth of the work. Works you have already downloaded are skipped before any request is made, so only genuinely new ones cost anything.

The work page itself is only ever fetched **once per fic**, no matter how many formats you tick: every format's download link is read off that single page. The rest is the file transfers, and those cannot be merged - each format is a separate file at its own address on AO3, so three formats means three transfers. Adding a second format to a run therefore costs one extra request per fic, not a second crawl of it.

**3. Indexing collections.** See [re-indexing a collection you already have](#re-indexing-a-collection-you-already-have) - an unchanged collection costs two requests rather than hundreds, but a first run over a large collection is expensive however you cut it.

The 'look up publication dates' option costs one request per work and is not offered in the web UI for that reason.

## Menu Options Explanation

- **'<!--CHECK-->download from ao3 link<!--ACTION_DESCRIPTION_AO3-->'** - this works for most links to [ao3](https://archiveofourown.org/). for example, you can use this to download a single work, a series, or any ao3 page that contains links to works or series (such as your bookmarks or an author's works). the program will download multiple pages automatically without the need to enter the next page link manually. as well as the usual ebook formats, you can choose the file type '<!--CHECK-->JSON<!--AO3_DOWNLOAD_TYPE_METADATA-->' here, which saves detailed information about every work on the page as one json file per work, instead of downloading the works themselves - see [the note below](#json-metadata-export) for what that includes.
- **'<!--CHECK-->get all work links from an ao3 listing (saves links only)<!--ACTION_DESCRIPTION_LINKS_ONLY-->'** - instead of downloading works, this will simply get a list of all the work links on the page you specify (as well as subsequent pages) and save them in a .txt file inside the downloads folder (one link on each line). this is useful if you prefer to download fics through FanFicFare or some other method, rather than using the ao3 download buttons. this option is much, much faster than a full download - usually only a few seconds per page. when using this option you can also choose to download a csv (spreadsheet) file containing detailed work metadata, instead of a plain text file containing links only. Should you need to cancel a links download in the middle, please do so by pressing ctrl+c before closing the window - this will allow the script to save the metadata it has collected so far, so that you don't have to completely start over when/if you choose to resume.
- **'<!--CHECK-->download links from file<!--ACTION_DESCRIPTION_FILE_INPUT-->'** - allows downloading links from a text file with one work or series link on each line. good if you have already harvested the links you want to download via some other method.
- **'<!--CHECK-->download latest version of incomplete fics<!--ACTION_DESCRIPTION_UPDATE-->'** - you can use this to check a folder on your computer (and any subfolders) for files downloaded from ao3 that are incomplete works. for each incomplete fic found, the program will check ao3 to see if there are any new chapters, and if so, will download the new version to the downloads folder.
- **'<!--CHECK-->download missing fics from series<!--ACTION_DESCRIPTION_UPDATE_SERIES-->'** - checks for files downloaded from ao3 that are part of a series, and for each series found, checks the series page on ao3 and downloads any fics in the series that are not already in your library.
- **'<!--CHECK-->re-download fics saved in one format in a different format<!--ACTION_DESCRIPTION_REDOWNLOAD-->'** - checks for _all_ files downloaded from ao3 and redownloads every fic it finds (if possible - failed downloads due to deletion or other reasons will be logged). good if you change your mind about what format you want your library to be in. (file type choices for this option are not saved to settings.)
- **'<!--CHECK-->download marked for later list and mark all as read (requires login)<!--ACTION_DESCRIPTION_MARKED_FOR_LATER-->'** - for those who like to use their marked for later as a download queue, this option takes the headache out of clearing the list after a download. note that this option does not generate 'starting page x' notifications in the console, but will still download all pages.
- **'<!--CHECK-->download bookmarks from pinboard<!--ACTION_DESCRIPTION_PINBOARD-->'** - download ao3 bookmarks from [pinboard](https://pinboard.in/). ignore this if you don't use pinboard. to get the api token go to settings -> password on the pinboard website.
- **'<!--CHECK-->convert logfile into interactable html<!--ACTION_DESCRIPTION_VISUALIZATION-->'** - all downloads from ao3 (and some other actions) are logged in a file called <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> in the '<!--CHECK-->logs<!--LOG_FOLDER_NAME-->' folder (if this folder does not exist it means no logs have been generated yet), along with information such as whether or not the download was successful, details about errors encountered, and so on. this option converts <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> into a much more human-readable, searchable and sortable (click on the column headers to sort) html file that can be opened in any browser. the file is called '<!--CHECK-->logvisualization.html<!--VISUALIZATION_FILE_NAME-->' (filename will also include some numbers indicating the timestamps of the first and last log messages it contains) and is saved in the same place as <!--CHECK-->log.jsonl<!--LOG_FILE_NAME-->. If your log file is particularly large, it may get split up across several html files. Note that the searching and sorting functionality (searchbox, filters, etc) may take some time to load in after the page opens. (If it never loads, you can try refreshing the page in your browser.)
- **'<!--CHECK-->configure ignore list (list of links to never try to download)<!--ACTION_DESCRIPTION_CONFIGURE_IGNORELIST-->'** - creates (if it does not already exist) a file in the main script folder which allows you to specify links to works or series that you never want the script to attempt to download. particularly good if the work or series update option is perpetually grabbing junk you don't want. this option also gives you a chance to auto-add links to the ignore list if they were previously tagged in the log file as failed downloads due to deletion.

## Notes

- **IMPORTANT**: some of your input choices are saved in a file called <!--CHECK-->data.json<!--SETTINGS_FILE_NAME-->. In some cases you will not be able to change these choices unless you clear your settings by deleting <!--CHECK-->data.json<!--SETTINGS_FILE_NAME--> (or editing it, if you are comfortable with json). In addition, please note that saved settings include passwords and keys and are saved in plain text. **Use appropriate caution with this file.**
- **You may change certain behaviors of the script** by editing the file <!--CHECK-->settings.ini<!--INI_FILE_NAME-->. Some of the current configurable options are:
  - Whether the script should save your password - if set to 'false', you will need to re-enter your password every time you log in via the script. (Defaults to false.)
  - How many seconds to pause between requests to Ao3 - the default is 0 seconds, which means that pauses will only be initiated when Ao3 requests them. Normally you should not need to adjust this, but it can be useful if you are running into odd behavior related to the rate limit.
  - The file naming pattern to use. For most people ao3downloader's default file names should work fine, but if you don't like them, you can change that here.
  - Where downloads are saved. By default this is a folder called '<!--CHECK-->downloads<!--DOWNLOAD_FOLDER_NAME-->' inside the folder you started the script from, but you can change it to any folder on your computer using a relative (to the folder you started the script from) or absolute path.
- **The purpose of entering your ao3 login information** is to download archive-locked works or anything else that is not visible when you are not logged in. If you don't care about that, there is no need to enter your login information.
- **Ao3 limits the number of requests** a single user can make to the site in a given time period. When this limit is reached, the script will pause for the amount of time (usually a few minutes) that Ao3 requests. When this happens, the start time, end time, and length of the pause in seconds will be printed to the console. If you try to access Ao3 from your browser during this period, you will see a "Retry later" message. Don't be alarmed by this - it's normal, and you aren't in trouble. Simply wait for the specified amount of time and then refresh the page. Other than during these required pauses, you can use Ao3 as normal while the script is running.
- **If you choose to '<!--CHECK-->get works from all encountered series links<!--AO3_PROMPT_SERIES-->'** then if the script encounters a work that is part of a series, it will also download the entire series that the work is a part of. This can _dramatically_ extend the amount of time the script takes to run. If you don't want this, choose 'n' when you get this prompt. (Series that you have bookmarked directly will always be fully downloaded, regardless of what you choose here.)
- **If you choose to '<!--CHECK-->download embedded images<!--AO3_PROMPT_IMAGES-->'** the script will look for image links on all works it downloads and attempt to save those images to an '<!--CHECK-->images<!--IMAGE_FOLDER_NAME-->' subfolder. Images will be titled with the name of the fic + 'imgxxx' to distinguish them.
  - Note that this feature does not encode any association between the downloaded images and the fic file aside from the file name.
  - Most file formats will include embedded image files anyway, regardless of whether you choose this option. I have confirmed this for PDF, EPUB, MOBI, and AZW3 file formats. (If you saw me contradict this in an earlier version of this readme... no you didn't)
  - Should an image download fail, the details of the failure will be logged in the log file with the message '<!--CHECK-->Problem getting image<!--ERROR_IMAGE-->' along with the work link and the image link. It's a good idea to check the log file for these messages, since you may still be able to download the image manually or track it down some other way.
- <span id="json-metadata-export"></span>**If you choose the '<!--CHECK-->JSON<!--AO3_DOWNLOAD_TYPE_METADATA-->' file type** when using the option '<!--CHECK-->download from ao3 link<!--ACTION_DESCRIPTION_AO3-->', the script does not download any works. Instead it reads through the listing you gave it and writes everything it can see about each work to the downloads folder, as one json file per work. Those files are named using the same '<!--CHECK-->FileNamePattern<!--INI_NAME_PATTERN-->' setting as downloaded works, so a fic's metadata sits next to its epub or html under the same name. This needs a link to a _listing_ of works - bookmarks, search results, an author's works, a series - not a link to a single work.
  - Each file is written as its page is read, rather than everything being saved at the end. A long listing therefore leaves usable output behind even if the run does not finish. If you need to stop early, press ctrl+c rather than closing the window, so the script can finish tidily.
  - Along with the work's own metadata, every file records the listing it came from, when it was retrieved, and the work's position in that listing (so the original bookmark order can be reconstructed).
  - For each work you get: the work id, title, author(s), link, publication and update dates, summary, fandoms, warnings, and tags (rating, categories, relationships, characters, and additional tags), plus word count, chapter counts, comments, kudos, bookmarks, and hits.
  - If the listing is your (or someone else's) bookmarks page, you also get the date the work was bookmarked, the bookmarker's notes, the bookmarker's tags, whether the bookmark is private, whether it is a rec, and any collections the bookmark was added to. On listings that aren't bookmarks, such as search results, these fields are still present but empty.
  - Counts that ao3 leaves off a listing entirely (it omits a stat when it is zero) come out as `null` rather than `0`, so you can tell "nothing there" apart from "ao3 didn't say". The total chapter count is `null` for a work in progress, which ao3 displays as '?'.
  - Bookmarks of series, external works, and deleted works are skipped, since none of the above exists for them. The script prints how many it skipped.
  - This is much faster than a real download, because it reads one page at a time rather than one work at a time. The one exception is the original publication date, which ao3 does not put on listing pages at all. You will be asked whether you want to '<!--CHECK-->look up the original publication date of every work<!--AO3_PROMPT_METADATA_WORK_DATES-->' - saying yes means loading every work separately, which is as slow as a full download, so say no unless you specifically need that field.
  - You can pick '<!--CHECK-->JSON<!--AO3_DOWNLOAD_TYPE_METADATA-->' alongside ebook formats. If you do, the metadata files are written first and then the works are downloaded as normal.
- **If you need to stop a download in the middle,** you can just close the window. When you restart the script:
  - If you are using the option '<!--CHECK-->download from ao3 link<!--ACTION_DESCRIPTION_AO3-->', you will be given an option to restart the download from the page you left off on. The program will attempt to avoid re-downloading works that are already in the downloads folder.
  - If you are using the option '<!--CHECK-->download bookmarks from pinboard<!--ACTION_DESCRIPTION_PINBOARD-->' or '<!--CHECK-->re-download fics saved in one format in a different format<!--ACTION_DESCRIPTION_REDOWNLOAD-->', the list of fics to download will be retrieved as normal but will then be filtered to remove work links that meet the following conditions:
    - A record of a download attempt for that link is present in the log file AND
      - There is a fic with the same title already in the downloads folder OR
      - The download was marked as unsuccessful
  - If you are using the option '<!--CHECK-->download latest version of incomplete fics<!--ACTION_DESCRIPTION_UPDATE-->' or '<!--CHECK-->download missing fics from series<!--ACTION_DESCRIPTION_UPDATE_SERIES-->', just make sure to add any fics you don't want to download again to your library (that is, the folder you entered when prompted '<!--CHECK-->input path to folder containing files you want to check for updates<!--UPDATE_PROMPT_INPUT-->') and clean up any old versions before re-starting the download.
  - Most methods of avoiding repeat downloads rely on a file called <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> which is generated by the script. Make sure not to move, delete, or modify <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> if you want these features to work. (Using the option to generate the log visualization file is fine.)
- **When checking for incomplete fics,** the code makes certain assumptions about how fic files are formatted. I have tried to make this logic as flexible as possible, but there is still some possibility that not all incomplete fics will be properly identified by the updater, especially if the files are old (since ao3 may have made changes to how they format fics for download over time) or have been edited.
- **Custom work skins** are not preserved in downloaded files. I don't currently have a way around that, however, when a work is downloaded the log entry for the download will contain a column (called 'workskin') indicating whether the work had a custom skin or not, so you can at least know which fics are in danger of looking garbled.
- **The reason the installation instructions are on a separate site** is because I didn't want to have to explain how to download the install scripts from github. The install scripts themselves (as well as the complete source code for the instructions site) are hosted in this repository. You can find them at `site/public/install`.

## Known Issues

- When downloading missing fics from series, if you are logged in, and the downloader finds a link to a series that is inaccessible because you do not have permission to access the series page, the downloader will download all of the works linked on your user dashboard page, instead. Yes... really.
- Links containing more than 4095 characters may cause issues on Mac and Linux. To work around this (on Mac and Linux only!) enter `stty -icanon` into your terminal before running ao3downloader. When you are finished running ao3downloader, enter `stty icanon` to restore the default behavior. H/t github user verotheelf for this workaround.
- Links containing more than 8191 characters will cause problems on Windows. There is no workaround, other than using a different link. Thankfully, it is unlikely you will run into this problem, as 8191 characters is quite a lot.

## Troubleshooting

- If you are able to create <!--CHECK-->logvisualization.html<!--VISUALIZATION_FILE_NAME--> (menu option 'v'), take a look through the logs to see if there are any helpful error messages.
- If the downloader is taking a very long time to run but not successfully downloading very many files, your specific IP address may have been blocked or throttled by cloudflare. *Sometimes* you can work around this problem by downloading from a different IP address. Some ways to change your IP address are:
  - If you have a vpn running, turn it completely off while using ao3downloader.
  - If you have a phone hotspot, try using that (as long as your data plan supports it - ebooks aren't huge files, but you might still want to check your plan limits first). For the phone hotspot trick, ensure the "wifi" option on the phone is disabled, otherwise it'll just pipe your normal internet connection through and not change your IP.
  - Transport your whole entire laptop to another location that has wifi (library, friend's house, etc) and try there.
  - Restart your router. This only has a small chance of actually resetting your IP, but it's easy to do and there IS a chance so hey.
  - You can also try petitioning your ISP, sometimes they'll reassign your IP address if you ask. This one involves paperwork and they might say no, though.
  - For the sake of completeness I'll mention that you can also try getting a vpn if you don't have one, since that will also change your IP address. However, turning a vpn on is a lot less likely to help you than turning a vpn off, because most vpns are on cloudflare's shitlist. Also, if you decide to get a vpn please do due diligence to ensure you don't pick a predatory one.

## Questions? Comments? Bug reports?

Feel free to head over to [the discussion board](https://github.com/nianeyna/ao3downloader/discussions) and make a post, or create an [issue](https://github.com/nianeyna/ao3downloader/issues). I prefer to communicate through the above channels if possible, however I understand many of my users don't have github accounts and may not want to make one just for this, so you can also email me at nianeyna@gmail.com if you prefer. Please include "ao3downloader" in the subject line of emails about the downloader. If you are reporting a bug, please describe exactly what you did to make the bug happen to the best of your ability. (More is more! Be as detailed as possible.)

(Please note that while I will absolutely do my best to get back to you, I can't make any promises - I have a job, etc.)
