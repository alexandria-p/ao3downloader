"""Version history inside each bookmark's json file.

Indexing the same fic twice should not lose what it looked like the first time, and should
not fill the file with identical copies either. So each file keeps a list of readings, a
new one is added only when something actually changed, and the file always records when it
was last checked - whether or not anything came of it.

    {
      "id": "123", "link": "...", "source": "...", "position": 4,
      "last_indexed": "2026-09-10T12:34:56+00:00",
      "indexes": [
        {"indexed_on": "2026-09-01T10:00:00+00:00", "title": ..., "kudos": 12, ...},
        {"indexed_on": "2026-09-10T12:34:56+00:00", "title": ..., "kudos": 15, ...}
      ]
    }
"""

import datetime

INDEXES = 'indexes'
INDEXED_ON = 'indexed_on'
LAST_INDEXED = 'last_indexed'

# these identify the file rather than describing the work, so they live at the root and
# are not versioned. position in particular changes as bookmarks are added, and versioning
# it would append an entry on every run for every fic.
IDENTITY_FIELDS = ('id', 'link', 'source', 'position')

# a collection is identified by its short name rather than a work id, and has no place
# in a listing order worth keeping
COLLECTION_IDENTITY_FIELDS = ('name', 'link', 'source')


def now() -> str:
    """The moment an indexing run started, as UTC."""

    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def split(document: dict, identity_fields: tuple[str, ...] = IDENTITY_FIELDS) -> tuple[dict, dict]:
    """Separate what identifies a record from what is worth keeping history of."""

    identity = {key: document[key] for key in identity_fields if key in document}
    snapshot = {key: value for key, value in document.items()
                if key not in identity_fields}
    return identity, snapshot


def changed(previous: dict, snapshot: dict) -> bool:
    """Whether a reading differs from the one before it, ignoring when it was taken."""

    return {k: v for k, v in previous.items() if k != INDEXED_ON} != snapshot


def merge(existing: dict | None, document: dict, indexed_on: str,
          identity_fields: tuple[str, ...] = IDENTITY_FIELDS) -> dict:
    """Fold a fresh reading into whatever is already on disk.

    A reading identical to the most recent one is not added again - the file just records
    that it was checked. A second save within the same run replaces that run's entry
    rather than adding another, which is what happens when publication dates are looked up
    after the listing has already been read.
    """

    identity, snapshot = split(document, identity_fields)

    result = dict(existing or {})
    entries = list(result.get(INDEXES) or [])
    entry = {INDEXED_ON: indexed_on, **snapshot}

    if entries and entries[-1].get(INDEXED_ON) == indexed_on:
        entries[-1] = entry
    elif not entries or changed(entries[-1], snapshot):
        entries.append(entry)

    result.update(identity)
    result[LAST_INDEXED] = indexed_on
    result[INDEXES] = entries
    return result
