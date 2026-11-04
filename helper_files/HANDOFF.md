# Handoff

What is in flight and what is undecided, as of **14 September 2026**. `CLAUDE.md` explains
how the project is built; this is only the loose ends, so it can be thrown away once they
are closed.

A full transcript of the session this came out of is at
`../session-transcript-2026-09-14.jsonl` (36.5 MB, deliberately outside the repo so it
cannot be committed by accident).

## The big one: moving file ownership to the browser

**Goal.** The user picks a folder in the page, and everything lives there - works, `indexing/`,
`collections/`, `images/`, `runs/`. `DownloadFolder` disappears from `settings.ini`
entirely. The helper stops touching the disk.

**Why it is possible.** A page never learns a *path* - `showDirectoryPicker` hands back a
handle, and there is no way to ask it where that folder is. But a handle granted
`readwrite` can create subfolders and write files, which is all this needs. The helper does
not need a path; it needs to stop writing.

**Done so far**

- the picker asks for `readwrite`, and the permission checks match
- `FolderStore` has the primitives: `write`, `remove`, and `stream` (a `pipeTo` straight
  from a response body to disk, so a downloaded file is never held whole in memory)
- every workflow button is hidden until a folder is chosen
- a one-off dismissable notice says this needs a Chromium browser

**Still to do**

- the helper returns bytes and records instead of saving them; it keeps only the work CORS
  forces server-side (authenticate, fetch, parse)
- the page writes works, index json, images and run records; scans the folder for what is
  already there; deletes superseded copies
- `DownloadFolder` comes out of `settings.ini` and out of the generated one
- the request log (`logs/log.jsonl`) is still written server-side - decide whether it moves

This touches `server.py`, `ao3.py`, `fileio.py` and `shared.py`, and adds a real
orchestration layer in the page. Worth doing in reviewable stages.

**Accepted consequence.** Firefox and Safari have no File System Access API, so downloading
becomes Chromium-only. Browsing an existing library still degrades gracefully. The user has
accepted this and the notice tells people on the first visit.

## Undecided: where the helper runs

The helper is the process on `127.0.0.1:4400`. The stated goal is "lots of users accessing
this site", and that does **not** work with a hosted helper:

- **AO3 rate-limits by IP.** One helper serving many users puts every request behind one
  address, so they share one budget and a block takes out everyone at once. Indexing 700
  bookmarks is ~35 requests; downloading them is ~735.
- **Credentials.** Users' AO3 passwords would pass through that server to reach AO3.
- It is single-user by construction anyway: one login session, one `settings.ini`, one log.

The shape that works is the page served from anywhere and the helper on each user's own
machine. GitHub Pages can host the page - especially once the page owns the files, since
there is then nothing to persist server-side. Two obstacles, both solvable:

- **mixed content**: an HTTPS page calling `http://127.0.0.1`. Chromium treats `127.0.0.1`
  as trustworthy so it is generally allowed, but it is worth not depending on quietly.
- **CORS in reverse**: the helper would have to allow the Pages origin explicitly.

What that buys: the page updates for everyone without a reinstall, and `build/` stops
shipping a web bundle. What it does not buy: a helper-free experience.

## Smaller open items

- **The run log is built but unwired.** `runs.py` has `RunRecord.line`, its batching and its
  cap, all tested - and nothing calls it, so no run json contains a log. The wiring in
  `server.run_job` was added and then reverted on request. Either finish it (feed printed
  lines to `record.line`, plus somewhere to hold the ones printed before the record exists)
  or delete the machinery. Do not leave it half-connected.
- **A date-window run still re-indexes some fics.** Anything the listing walk did not reach -
  skip-indexing, a run writing no json, or a fic no longer bookmarked - is re-read one at a
  time. Deliberate: downloading from a stale entry writes a file stamped with a stale date,
  which then looks current for ever. Revisit only with that in mind.
- **Three dependencies are now unused.** `mobi`, `pypdf` and `tqdm` are imported by nothing
  since the console app was deleted. Removing them needs a `uv lock` regeneration, which may
  resolve new versions of `bs4`/`requests` and wants a full re-verify - and on a network that
  intercepts TLS, `--system-certs`.
- **The root README's "Original Readme"** is the upstream console documentation. The console
  app is gone, so that section is kept only for provenance and is marked as such. It could be
  deleted outright.
