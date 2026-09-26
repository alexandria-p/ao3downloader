"""Tests for source_code.indexing — version history inside a bookmark's json file."""

import datetime

from source_code import indexing


FIRST = '2026-09-01T10:00:00+00:00'
SECOND = '2026-09-10T12:34:56+00:00'


def document(**overrides) -> dict:
    """A reading of one bookmark, as get_metadata builds it."""
    reading = {
        'source': 'https://archiveofourown.org/users/Someone/bookmarks',
        'bookmark_type': 'individual work',
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

    assert sorted(identity) == ['bookmark_type', 'id', 'link', 'source']
    assert 'bookmark_type' not in snapshot
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
    assert result['bookmark_type'] == 'individual work'
    assert 'bookmark_type' not in result[indexing.INDEXES][0]


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


def test_merge_drops_the_listing_position_earlier_versions_wrote():
    # the page sorts and filters for itself now, so a fic's place in the listing is not
    # kept - taken out of a file the next time it is saved, root and readings alike
    old = indexing.merge(None, {**document(), 'position': 4}, FIRST)
    old['position'] = 4
    old[indexing.INDEXES][0]['position'] = 4

    result = indexing.merge(old, document(), SECOND)

    assert 'position' not in result
    assert all('position' not in reading for reading in result[indexing.INDEXES])


def test_merge_adds_to_the_series_a_work_was_found_through_rather_than_replacing_them():
    # a work in two bookmarked series was found through both, whichever was read last
    first = indexing.merge(None, document(from_series=['12']), FIRST)

    second = indexing.merge(first, document(from_series=['7']), SECOND)
    third = indexing.merge(second, document(), SECOND)

    assert second[indexing.FROM_SERIES] == ['7', '12']
    # a reading off the bookmarks listing says nothing about series, and loses none
    assert third[indexing.FROM_SERIES] == ['7', '12']
    assert len(third[indexing.INDEXES]) == 1


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


# region flatten

def test_flatten_reads_the_newest_reading_with_the_identity_over_it():
    document = {
        'id': '111', 'link': 'https://ao3/works/111', 'bookmark_type': 'individual work',
        indexing.LAST_INDEXED: SECOND,
        indexing.INDEXES: [
            {indexing.INDEXED_ON: FIRST, 'title': 'Old', 'kudos': 12},
            {indexing.INDEXED_ON: SECOND, 'title': 'New', 'kudos': 20},
        ],
    }

    record = indexing.flatten(document)

    assert record['title'] == 'New'
    assert record['kudos'] == 20
    # identity is not versioned, so the root wins
    assert record['id'] == '111'
    assert record['bookmark_type'] == 'individual work'


def test_flatten_reads_a_flat_file_written_before_the_history_existed():
    record = indexing.flatten({'id': '111', 'title': 'A Fic', 'kudos': 3})

    assert record['title'] == 'A Fic'


def test_flatten_gives_nothing_for_what_it_cannot_read():
    assert indexing.flatten(None) is None
    assert indexing.flatten('not a record') is None
    assert indexing.flatten({}) is None
    assert indexing.flatten({indexing.INDEXES: []}) is None
    assert indexing.flatten({indexing.INDEXES: ['not a reading']}) is None

# endregion


# region is_incomplete

def test_a_work_in_progress_has_no_chapter_total():
    # ao3 shows '12/?' for a work still being written
    assert indexing.is_incomplete({'chapters_published': 12, 'chapters_total': None}) is True


def test_a_work_short_of_its_own_total_is_unfinished():
    assert indexing.is_incomplete({'chapters_published': 3, 'chapters_total': 10}) is True


def test_a_work_that_reached_its_total_is_finished():
    assert indexing.is_incomplete({'chapters_published': 10, 'chapters_total': 10}) is False
    assert indexing.is_incomplete({'chapters_published': 1, 'chapters_total': 1}) is False


def test_a_record_with_no_counts_at_all_is_treated_as_unfinished():
    # better to re-read one that did not need it than to miss one that did
    assert indexing.is_incomplete({}) is True
    assert indexing.is_incomplete({'chapters_published': None, 'chapters_total': None}) is True

# endregion
