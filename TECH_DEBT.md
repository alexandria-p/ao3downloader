# Tech debt

Known weak spots: things that work today but are fragile, incomplete, or only safe because
of an assumption nobody enforces. Each says what the weakness is, what it costs when it
bites, and what a proper fix would look like. `CLAUDE.md` explains how things work; this is
where they are thin.

## `from_collections` is still thinner than it looks

An index entry's `from_collections` lists the collections that hold a work (or external
work). It is now written in **one place** - the cleanup step (`collection_links` /
`write_collection_links`) - for every workflow but the debug ones, over every work the run
covered, a resumed run's earlier attempt included. It used to have four writers, each with its
own idea of which works to look at; that was the brittle part, and it is gone. What is left:

**It only ever grows.** Nothing removes a name. A work taken out of a collection, a
collection deleted on AO3, a collection file deleted from the library - the entry still
names the collection. Fixing this means the cleanup setting the field to exactly the
collections that list the work - removing as well as adding - which needs every collection
in the library to be current first, or it would remove names that are right.

**It is only as right as the collection files.** The cleanup trusts `work_ids`,
`bookmark_ids`, `external_ids` and `series_ids` - and, for a series, the `work_ids` its own
entry lists. Those can be stale: a collection run without the works
option skips re-reading a listing whose count has not changed (`unchanged_items`), so a
collection that gained one work and lost another keeps its old list, and the entries are
linked from that old list.

**Coverage still has edges.**
- The debug workflows (the combined run, 'new bookmarks only', update incomplete) never
  link - by choice.
- A run that is stopped, abandoned or fails never reaches its cleanup, so it links nothing -
  until it is resumed, when the resume links what both attempts covered. One never resumed
  waits for the next run to cover those works.
- A quick scan covers only what changed since its floor, so older works wait for a full scan.

**Entries are found by the number their file name starts with.** A file renamed by hand so
it no longer starts with the work number is not found. Nothing in the app does that, but
people do.

**Numbering.** External works have AO3's separate numbering (`/external_works/<n>`), kept in
`external_ids` and `indexing/external/`. Mixing the two - an external number looked up among
works - would link the wrong entry. The page and the helper both keep them apart today, by
hand.

**Nothing shows it.** The page does not display `from_collections`, so a wrong or missing
value is not noticed by anyone using the app.

## Older libraries can hold two index files for one work

Index writes used to go to the name a work would be given from its current title and author
(`Ao3.metadata_path`). When a work was retitled on AO3, or its author renamed themselves, the
next scan or series walk wrote a **second file** for the same work, left the old one as it
was, and - for a work found through a series or a collection - recorded the new one as not
bookmarked.

**Every index write now finds its entry by the number its file name starts with**
(`Ao3.entry_path`), so no new duplicates are made. The ones already in a library are left
where they are: `list_entries` picks the most recently indexed file for a number, writes only
to that one, and the run says which numbers it found doubled. The older file is never
touched or deleted. The page, reading every file, shows whichever it reads last for that
number - usually, not always, the same one.

**A proper fix** is a one-off pass that merges each number's files into one - their readings
in date order, the union of `from_series` and `from_collections`, `bookmarked` true if either
said so - and deletes the rest. It needs care, since it deletes files, and it has not been
written.

## TODO: collection listings do not yet refuse a page that is not a listing

**What is missing.** The bookmarks walk (`get_metadata`) refuses a page with no blurbs that is
not a listing at all (`parse_soup.looks_like_listing`: an `ol.index`, or a heading naming what
it lists) with `ERROR_LISTING_UNREADABLE`, so a login page or an error page ao3 serves as 200
becomes an index gap instead of the end of your bookmarks. A collection's works and
bookmarked-items listings (`Ao3.walk_pages`, from `collect_work_ids`) only have the status
check (`fetch_page`, which catches 401/403/404/5xx and maintenance).

**What it costs.** Such a page mid-collection reads as an empty last page: the collection is
saved with only the works found so far - possibly none - and marked done, with nothing in the
run saying so.

**Why it is not done.** The marker was checked against a real bookmarks page
(`test/fixtures/bookmarks.html`), but there is no fixture of a collection's works or
bookmarked-items listing, empty or not. If an empty collection's listing carried neither
marker, every empty collection would be flagged as a failure. AO3 was down when this came up,
so it could not be checked live.

**The fix.** Refresh the fixtures from live AO3 (`dev/refresh_fixtures.py`) with a collection
works listing, a bookmarked-items listing, and an **empty** collection; confirm
`looks_like_listing` accepts all three; then call it in `walk_pages` (or `collect_work_ids`)
the way `get_metadata` does, raising `ERROR_LISTING_UNREADABLE` so the collection's gap
records `reason: no-data`, with tests on the new fixtures.

## TODO: hosted and downloaded copies keep settings in different places

**What happens now.** Where a setting lives depends on which copy you are using, and the
order is not the same:

- **A downloaded app, the bundle, a dev build:** settings.ini only. User settings edits it,
  and the browser keeps nothing but the prompts and the default formats.
- **A hosted copy:** settings.ini comes from the deployment's variables and the page cannot
  edit it. So *Questions a run may ask* (`QuestionTimeoutMinutes` and the six default answers)
  is kept in the browser (`ao3.answerDefaults`, `ao3.questionTimeoutMinutes`), sent with each
  run, and used **ahead of** settings.ini (`run_question_settings`, `Job.answer_defaults`).
  Every other setting stays deployment-only.

So the same choice is settings.ini-first on one copy and browser-first on the other. Each
browser of a hosted copy also has its own set, and a downloaded app's set is shared by every
browser on that computer.

**What happens when the pipeline changes a variable.** A hosted helper's settings.ini is
written fresh from the variables on every deploy, so the new value is in force at once. But a
browser that already saved its own choice for that question keeps it, and keeps sending it -
the deployment's change never reaches that browser's runs. The page only stores values that
differ from the helper's, so a browser with nothing saved follows the new value. A downloaded
app is different again: an update appends new settings to settings.ini but never changes a
value already there (**A settings.ini is only ever added to**), so a variable changed after
someone installed never reaches them either, and its new value only shows as the "default"
in User settings and what Reset to defaults writes.

**To decide.** One rule for both: which settings (some or all) live in the browser and which
in settings.ini; which wins when both have a value; and what a changed deployment variable
does to a value someone has already chosen - override it, leave it, or tell them. Possible
answers: everything per-user goes in the browser on both (settings.ini keeping only what the
helper needs before a page exists); or a hosted copy gets an editable store of its own on the
helper side, so both are settings.ini-first. Whichever, the page should say where each value
comes from.

## Other known gaps

- **The order of a collection's works listing** was not checked against the live site. A
  resumed collection run re-reads the earlier pages when a works listing comes up short of
  the collection's count, so nothing is missed whichever order it is - but that costs
  requests, and knowing the order would say whether it ever needs to.
- **`unchanged_items` cannot see one work added and another removed** between runs of a
  collection: the count is the same, so the saved list is kept. Deleting the collection's
  json forces a full crawl.
- **A series a collection holds is not read again when its entry already lists as many works
  as the collection's blurb says** (`series_unchanged`), so the same blind spot applies: one
  work removed and another added leaves the count unchanged and the old list kept. Deleting
  the series' entry in `indexing/series/` makes the next collection run read it. A series
  you bookmarked is read in full by every scan of your bookmarks anyway, which corrects it.
- **Intel Macs are held on `cryptography<49`.** 49 was the first release with no Intel Mac
  wheel, and building it from source there links an OpenSSL PyInstaller does not pack. So the
  Intel Mac app gets no cryptography fixes after 48.x. When that matters, either build it on
  the Intel runner with OpenSSL linked statically (`OPENSSL_STATIC=1`, `OPENSSL_DIR` at
  Homebrew's `openssl@3`), or drop the Intel build.
