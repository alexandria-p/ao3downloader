"""Tests for source_code.indexing — version history inside a bookmark's json file."""

import datetime

from source_code import indexing


FIRST = '2026-09-01T10:00:00+00:00'
SECOND = '2026-09-10T12:34:56+00:00'


def document(**overrides) -> dict:
    """A reading of one bookmark, as get_metadata builds it."""
    reading = {
        'source': 'https://archiveofourown.org/users/Someone/bookmarks',
        'position': 1,
        'id': '111',
        'link': 'https://archiveofourown.org/works/111',
        'title': 'A Work',
        'kudos': 12,
        'chapters_published': 3,
    }
    reading.update(overrides)
    return reading


# region now

def test_now_is_utc_and_parseable():
    stamp = indexing.now()

    parsed = datetime.datetime.fromisoformat(stamp)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == datetime.timedelta(0)

# endregion


# region split

def test_split_keeps_identity_out_of_the_history():
    identity, snapshot = indexing.split(document())

    assert sorted(identity) == ['id', 'link', 'position', 'source']
    # position shifts as bookmarks are added; versioning it would append every run
    assert 'position' not in snapshot
    assert snapshot['title'] == 'A Work'
    assert snapshot['kudos'] == 12

# endregion


# region merge

def test_merge_into_nothing_starts_a_history():
    result = indexing.merge(None, document(), FIRST)

    assert result[indexing.LAST_INDEXED] == FIRST
    assert len(result[indexing.INDEXES]) == 1
    assert result[indexing.INDEXES][0][indexing.INDEXED_ON] == FIRST
    # identity sits at the root, not in the entry
    assert result['id'] == '111'
    assert result['position'] == 1
    assert 'position' not in result[indexing.INDEXES][0]


def test_merge_records_a_change_as_a_new_reading():
    first = indexing.merge(None, document(), FIRST)

    second = indexing.merge(first, document(kudos=15), SECOND)

    assert len(second[indexing.INDEXES]) == 2
    assert [e['kudos'] for e in second[indexing.INDEXES]] == [12, 15]
    assert second[indexing.LAST_INDEXED] == SECOND
    # the earlier reading is left exactly as it was
    assert second[indexing.INDEXES][0][indexing.INDEXED_ON] == FIRST


def test_merge_does_not_repeat_an_unchanged_reading():
    first = indexing.merge(None, document(), FIRST)

    second = indexing.merge(first, document(), SECOND)

    assert len(second[indexing.INDEXES]) == 1
    # but the file still records that it was checked
    assert second[indexing.LAST_INDEXED] == SECOND
    assert second[indexing.INDEXES][0][indexing.INDEXED_ON] == FIRST


def test_merge_ignores_a_moved_bookmark_position():
    # a fic sliding down the listing is not a change to the fic
    first = indexing.merge(None, document(position=1), FIRST)

    second = indexing.merge(first, document(position=9), SECOND)

    assert len(second[indexing.INDEXES]) == 1
    assert second['position'] == 9


def test_merge_replaces_a_reading_taken_in_the_same_run():
    # publication dates are looked up after the listing has been read, and save again
    first = indexing.merge(None, document(), FIRST)

    again = indexing.merge(first, document(date_created='01 Jan 2019'), FIRST)

    assert len(again[indexing.INDEXES]) == 1
    assert again[indexing.INDEXES][0]['date_created'] == '01 Jan 2019'


def test_merge_keeps_every_reading_across_several_runs():
    third = '2026-09-20T08:00:00+00:00'

    result = indexing.merge(None, document(kudos=1), FIRST)
    result = indexing.merge(result, document(kudos=2), SECOND)
    result = indexing.merge(result, document(kudos=3), third)

    assert [e['kudos'] for e in result[indexing.INDEXES]] == [1, 2, 3]
    assert result[indexing.LAST_INDEXED] == third


def test_merge_compares_against_the_most_recent_reading_only():
    # a fic that changes and then changes back still records the return
    result = indexing.merge(None, document(kudos=1), FIRST)
    result = indexing.merge(result, document(kudos=2), SECOND)
    result = indexing.merge(result, document(kudos=1), '2026-09-20T08:00:00+00:00')

    assert [e['kudos'] for e in result[indexing.INDEXES]] == [1, 2, 1]


def test_merge_treats_a_file_with_no_history_as_empty():
    # something hand-edited, or written by an older version
    result = indexing.merge({'id': '111'}, document(), FIRST)

    assert len(result[indexing.INDEXES]) == 1

# endregion


# region changed

def test_changed_ignores_when_the_reading_was_taken():
    previous = {indexing.INDEXED_ON: FIRST, 'kudos': 12}

    assert indexing.changed(previous, {'kudos': 12}) is False
    assert indexing.changed(previous, {'kudos': 13}) is True


def test_changed_notices_a_field_appearing_or_disappearing():
    previous = {indexing.INDEXED_ON: FIRST, 'kudos': 12}

    assert indexing.changed(previous, {'kudos': 12, 'hits': 3}) is True
    assert indexing.changed(previous, {}) is True

# endregion
