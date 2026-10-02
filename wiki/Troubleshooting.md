## AO3 asked me to slow down

AO3 limits how fast requests arrive. When it says wait, the run waits - often a few minutes - then carries on by itself. Nothing is lost.

If it happens a lot, raise `ExtraWaitTime` in [[Settings]] (default 15 seconds). Roughly, for 700 bookmarks:

| Run | Requests |
| --- | --- |
| JSON only | ~35 |
| JSON + HTML | ~735 |
| JSON + HTML + EPUB | ~1,435 |

Indexing reads 20 works per request; each downloaded format is one request per work.

## Works started failing partway through

Your AO3 login probably lapsed - a restricted work then comes back as a page, not a file. The run checks once, and ends with *login lapsed* if so. Start it again; it skips what's already done.

## The app won't open

- **Windows:** "Windows protected your PC" → **More info** → **Run anyway**.
- **Mac:** **System Settings > Privacy & Security > Open Anyway**. From Terminal, `xattr -dr com.apple.quarantine <the folder>` does the same.
- **Linux:** run `./"Start ao3downloader.sh"` from a terminal to see why. It needs a glibc at least as new as Ubuntu 22.04's.
- **"Seems to be running already":** close every ao3downloader window and start it again.

## I can't choose a folder

Saving to a folder needs Chrome, Chromium, Edge, Brave, Opera or Arc on a computer. Firefox, Safari and phones can't. Use Dropbox instead, or switch browsers.

## New features half-work, or a button says "unknown action"

An old helper is still running on port 4400 and answering the new page. Close every ao3downloader window (or `netstat -ano | findstr :4400` on Windows to find it), then start the app again.

## A run says Interrupted

The helper stopped mid-run - closed, crashed, or a deploy. **Resume** it from History, or run it again. See [[History and resuming]].

## Still stuck

[Open an issue](https://github.com/alexandria-p/ao3downloader/issues). Say what you did, what happened, and your version (bottom of the page). If a run went wrong, attach its log: **History > Download log**.
