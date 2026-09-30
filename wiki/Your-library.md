Your library is one folder - on your computer, or `/Apps/ao3-downloader` in Dropbox. The app never keeps a copy anywhere else.

## Folders

| Folder | Holds |
| --- | --- |
| `works/` | Downloaded fics: html, epub, pdf... |
| `indexing/` | The index: one JSON file per work, plus `series/` and `external/` |
| `collections/` | One JSON file per collection |
| `runs/` | One JSON file per run - the History tab |
| `images/` | Images saved separately, if you asked for them |

## File names

Every downloaded file is named the same way, and it can't be changed:

```
{work number} {title} - {author} {date AO3 last updated it}
34816549 No Paths Are Bound - Cataclysmic_Cal 2026-08-23.html
```

- **The work number comes first** - that's how a file is matched to its index entry. To bring in a file from elsewhere, start its name with the AO3 work number and a space, `_`, `.` or `-`.
- **The date comes last** - it's the version the file holds, not when you downloaded it. That's how a later run knows AO3 has something newer.
- Long titles are shortened to fit `FileNameLength`. The date is never cut.
- Index JSON files carry no date, since each one is the fic's whole history.

## When a file is downloaded again

A copy is **outdated** when AO3's update date in the index is newer than the date in its name. Runs download a format only when you have no copy of it, or yours is outdated. **Overwrite** is the one exception.

An older copy is removed only once the new one is confirmed saved at full length. If it can't be removed, both stay, and the run lists it under *copies to check by hand*. A new file that arrives damaged is deleted and counted as a failure, leaving the old copy where it was.

A fic can finish on AO3 and be updated later. The update-incomplete pass won't see that; a full scan will.

## Index files

Each fic's JSON keeps a history: a new reading is added only when something changed, so you can see when it gained chapters.

```json
{
  "id": "34816549",
  "link": "https://archiveofourown.org/works/34816549",
  "last_indexed": "2026-09-10T12:34:56+00:00",
  "indexes": [
    { "indexed_on": "2026-09-01T10:00:00+00:00", "kudos": 12 },
    { "indexed_on": "2026-09-10T12:34:56+00:00", "kudos": 15 }
  ]
}
```

- `bookmarked` - whether you bookmarked it yourself. Works found through a series or collection are `false` until you do.
- `from_series`, `from_collections` - where else it was found.

## Collection files

A collection's file records what it holds, by number: `work_ids`, `bookmark_ids`, `external_ids` (external works have their own numbering) and `series_ids`. Opening a collection in the page shows the works you have indexed in full, and the rest by number with a link to AO3.

Re-indexing a collection whose counts haven't changed costs two requests, not hundreds. The one thing that misses is a work added and another removed between runs - delete the collection's JSON to force a full read.
