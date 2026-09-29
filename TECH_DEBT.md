# Tech debt

Known weak spots: things that work today but are fragile, incomplete, or only safe because
of an assumption nobody enforces. Each says what the weakness is, what it costs when it
bites, and what a proper fix would look like. `CLAUDE.md` explains how things work; this is
where they are thin.

## `from_collections` is brittle

An index entry's `from_collections` lists the collections a work (or external work) was
found in. It is right most of the time, but it is not kept by one mechanism with one rule -
it is patched in from several places, and nothing ever checks it as a whole.

**Four writers.** It is written by:

1. a collection run with *Index and download encountered works*, as each work is saved
   (`save_collection_work`, through `indexing.merge`, which only ever adds to it)
2. the same run, for an external work (`save_collection_external` / `save_entry`)
3. the cleanup step of a collection run, for works already indexed (`collection_links` /
   `write_collection_links`, which writes the identity field straight onto the file,
   bypassing `merge`)
4. the cleanup step of a full, quick or custom scan, for the works it indexed

Each has its own idea of which works to look at. They agree today because they were written
together; a change to one is easy to make without the others.

**It only ever grows.** Nothing removes a name. A work taken out of a collection, a
collection deleted on AO3, a collection file deleted from the library - the entry still
names the collection. Fixing this needs a pass that rebuilds the field from every collection
file, not an update per run.

**It is only as right as the collection files.** Every writer trusts `work_ids`,
`bookmark_ids` and `external_ids`. Those can be stale: a collection run without the works
option skips re-reading a listing whose count has not changed (`unchanged_items`), so a
collection that gained one work and lost another keeps its old list, and the entries are
linked from that old list.

**Coverage has holes.** The cleanup linking runs on collection runs and on the full, quick
and custom scans. The combined run, 'new bookmarks only', the single-fic run and the update
run never link. A quick scan links only what it indexed, which is only what changed since
its floor, so older works wait for a full scan.

**Entries are found by the number their file name starts with.** The cleanup linking and
the collection runs look entries up that way (`entries_missing`, `Ao3.entry_path`). A file
renamed by hand so it no longer starts with the work number is not found. Nothing in the app
does that, but people do.

**Numbering.** External works have AO3's separate numbering (`/external_works/<n>`), kept in
`external_ids` and `indexing/external/`. Mixing the two - an external number looked up among
works - would link the wrong entry. The page and the helper both keep them apart today, by
hand.

**Nothing shows it.** The page does not display `from_collections`, so a wrong or missing
value is not noticed by anyone using the app.

**A proper fix** would be one function that, given every collection file, sets
`from_collections` on every entry to exactly the collections that list it - adding and
removing - run as its own step, and the only writer. The per-run writers above would then be
removed.

## Most index writes find an entry by the name it would have now

`Ao3.metadata_path` builds a file name from the work number, title and author. The scans'
walks (`get_metadata`) and the series walk (`save_series_work`) write to that name, built
from what the listing says now. (The single-fic and update runs do not have this problem:
they start from the entry already in the index and rewrite only its stats, so its title -
and so its name - is the one it already has.) When a work is retitled on AO3, or its author renames themselves, the
name changes: the next write goes to a **second file** for the same work, the old one is left
as it was, and the page shows whichever it reads last. For a work found through a series or
a collection, the new file is also recorded as not bookmarked, since the lookup that would
have found your bookmark missed.

Collection runs no longer do this - they find the entry by its number (`Ao3.entry_path`),
as series entries already were (`series_path`) - because a test caught a collection run
creating the second file and losing the bookmark. The rest of the index writes have not been
changed yet. Moving them all to `entry_path` would stop the duplicates; cleaning up the
duplicates already in someone's library would need a separate pass that merges them.

## Other known gaps

- **The order of a collection's works listing** was not checked against the live site. A
  resumed collection run re-reads the earlier pages when a works listing comes up short of
  the collection's count, so nothing is missed whichever order it is - but that costs
  requests, and knowing the order would say whether it ever needs to.
- **`unchanged_items` cannot see one work added and another removed** between runs of a
  collection: the count is the same, so the saved list is kept. Deleting the collection's
  json forces a full crawl.
