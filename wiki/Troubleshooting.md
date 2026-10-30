## AO3 asked me to slow down

AO3 limits how fast requests arrive. When it says wait, the run waits - often a few minutes - then carries on by itself. Nothing is lost.

If it happens a lot, raise `ExtraWaitTime` in [[Settings]] (default 15 seconds). Roughly, for 700 bookmarks:

| Run | Requests |
| --- | --- |
| JSON only | ~35 |
| JSON + HTML | ~735 |
| JSON + HTML + EPUB | ~1,435 |

Indexing reads 20 works per request; each downloaded format is one request per work.

## AO3 is down for maintenance

AO3 shows a *The archive is down for maintenance* page in place of everything. A run notices it, says so in its log, checks twice more 30 seconds apart, then stops asking AO3 for the rest of the run - every fic after that fails at once with *AO3 is down for maintenance*, rather than each one retrying for minutes. Fics with a work number are then offered to FicHub at the end. A run that has to log in fails at the login. Check [AO3's status page](https://status.archiveofourown.org) and start again once it is back.

A request AO3 doesn't answer says `still waiting for AO3 to answer ...` every 15 seconds, and gives up after 60 seconds in all - it is tried again up to `MaxTimeouts` (3) times, then that fic fails and goes to FicHub at the end.

Any other error AO3 answers with is retried, and every retry is said in the run's log (`AO3 answered 503 ... trying again in 4s (attempt 3 of 30)`). **Stop works during a retry.**

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
