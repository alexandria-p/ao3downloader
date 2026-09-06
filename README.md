# Alex Tips

it's worth running uv run python dev/readme.py after a rewrite.(?)


keep settings.ini and data.json in root directory
make sure to update the location of your downloads folder (my_downloads for me)

Open powershell
powershell.exe -ExecutionPolicy Bypass -File .\run-gui.ps1
That starts both pieces — the local helper on port 4400 and the web UI on port 4200 — then leave the window open and go to http://localhost:4200.

Ctrl+C in that window stops both

downloads via gui go to settings.ini -> DownloadFolder


For running the GUI ONLY:

Open git bash CLI window, 

From the repo root:
npm --prefix GUI start
(or, cd GUI; npm start)

Then open http://localhost:4200.


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

There is a local web interface in the `GUI` folder for browsing your downloaded bookmarks and starting downloads without using the console menu. Start everything with:

```
.\run-gui.ps1
```

That launches two things and then opens at <http://localhost:4200>:

- **the Angular app**, which reads your downloads folder in the browser and lists your bookmarks
- **the local helper** (`ao3downloader.server`), which performs the actual downloads

The helper exists because a web page cannot do this work itself. Ao3 sends no CORS headers, so a page cannot read it; a page cannot hold an ao3 login session; and the update scan has to read the ebook files on your disk. The helper listens on `127.0.0.1` only - nothing outside your machine can reach it - and it calls exactly the same code the console menu calls.

The page has two buttons:

- **Download newly added bookmarks** - the same as the console option 'download from ao3 link', pointed at `https://archiveofourown.org/users/<your username>/bookmarks`. Works already in your downloads folder are skipped, so a second run only picks up bookmarks added since the last one.
- **Update any bookmarks marked as incomplete** - the same as the console option 'download latest version of incomplete fics'. It scans your downloads folder for works that were incomplete and re-downloads any with new chapters.

Each button asks which file types you want. JSON and HTML are always produced and cannot be unticked; the ebook formats are optional. It then asks the same questions the console menu does - which page to stop on (0 for all of them), whether to follow series links, whether to save embedded images, and whether to look up publication dates - leaving out any that do not apply to the action you picked. Finally it asks you to log in to ao3.

While a run is in progress the dialog shows a progress bar, the file types and options you chose, the folder being written to, and the name of the fic being fetched right now along with the format it is being fetched in. A message appears if ao3 asks the script to slow down. **Leave the tab open while a download runs** - refreshing or closing it interrupts the run.

There is a **Stop** button throughout. Stopping is safe: the run finishes what it is writing and unwinds, so everything already saved is kept. It is not a rollback.

If a work has already been downloaded it is skipped rather than fetched again, which is what makes the first button 'newly added'. A work counts as already downloaded when it appears in <!--CHECK-->log.jsonl<!--LOG_FILE_NAME--> *and* a file exists for every file type you selected. If either is untrue - the log was deleted, or you asked for a format you did not download last time - it is fetched again and the file is overwritten in place. JSON metadata is the exception: it is always rewritten, so the metadata stays current even for works that are skipped.

On your login details: only your username is saved by the page, in browser storage. Your password is sent to the helper to log in to ao3 and is never written anywhere - let your browser's own password manager remember it if you want it filled in next time.

If you only want to browse bookmarks you have already downloaded, you can run the web app on its own with `npm --prefix GUI start`; the download buttons will tell you the helper is not running.

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
