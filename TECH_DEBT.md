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
`bookmark_ids`, `external_ids` and `series_work_ids`. Those can be stale: a collection run without the works
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

## Other known gaps

- **The order of a collection's works listing** was not checked against the live site. A
  resumed collection run re-reads the earlier pages when a works listing comes up short of
  the collection's count, so nothing is missed whichever order it is - but that costs
  requests, and knowing the order would say whether it ever needs to.
- **`unchanged_items` cannot see one work added and another removed** between runs of a
  collection: the count is the same, so the saved list is kept. Deleting the collection's
  json forces a full crawl.
