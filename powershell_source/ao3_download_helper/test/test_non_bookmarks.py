"""Checking non-bookmarks for updates: the works the index holds that you never bookmarked.

A listing of your bookmarks never shows them, so a scan only reads them again when asked
to. Their series are walked first - 20 works a request - and only what that walk does not
reach is opened one work at a time.
"""

from unittest.mock import MagicMock

import pytest

from source_code import exceptions, progress, server, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


def work(number: str, bookmarked, **fields) -> dict:
    record = {'id': number, 'link': f'https://archiveofourown.org/works/{number}',
              'title': f'Work {number}', **fields}
    if bookmarked is not None: record[strings.BOOKMARKED_FIELD] = bookmarked
    return record


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()
    return fileops


def seed(fileops: FileOps, *records: dict) -> None:
    writer = Ao3(repo=MagicMock(spec=Repository), fileops=fileops, filetypes=[], pages=None,
                 series=False, images=False)
    for record in records: writer.save_metadata(dict(record))


def a_run(action=server.ACTION_BOOKMARKS, options=None,
          filetypes=('JSON', 'HTML')) -> tuple[server.Job, list[dict]]:
    job = server.Job(action, list(filetypes), 'Someone',
                     server.resolve_options({'nonBookmarks': True, **(options or {})}))
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))
    return job, events


def marks(events: list[dict]) -> list[tuple[str, str]]:
    return [(e['id'], e['status']) for e in events
            if e['type'] == progress.STEP and e['id'] == 'nonbookmarks']


# region which works count

def test_only_works_marked_not_bookmarked_are_non_bookmarks():
    records = [work('1', False), work('2', True), work('3', None),
               work('4', False, **{strings.BOOKMARK_TYPE_FIELD: strings.BOOKMARK_TYPE_SERIES})]
    # an entry that says nothing is one no run could judge - most likely an old bookmark
    assert [r['id'] for r in server.non_bookmarks_in(records)] == ['1']


def test_the_option_is_off_unless_asked_for():
    assert server.resolve_options({})['nonBookmarks'] is False

# endregion


# region the checklist

def plan_ids(action, options=None, filetypes=('JSON', 'HTML')) -> list[str]:
    job, _ = a_run(action, options, filetypes)
    return [step for step, _ in server.step_plan(job)]


@pytest.mark.parametrize('action, options', [
    (server.ACTION_BOOKMARKS, None),
    (server.ACTION_QUICK, None),
    (server.ACTION_QUICK, {'dates': True, 'dateFrom': '2025-01-01'}),
    (server.ACTION_CUSTOM, None),
    (server.ACTION_CUSTOM, {'dates': True, 'dateFrom': '2025-01-01'}),
])
def test_each_scan_lists_the_step_after_the_series_walk_when_asked(action, options):
    ids = plan_ids(action, options)
    assert ids.index('series') < ids.index('nonbookmarks') < ids.index('check')


def test_the_step_is_not_listed_unless_asked_for():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({}))
    assert 'nonbookmarks' not in [step for step, _ in server.step_plan(job)]


def test_a_custom_run_that_skips_indexing_cannot_check_them():
    # re-reading a work writes its entry, which skipping the indexing has ruled out
    assert 'nonbookmarks' not in plan_ids(server.ACTION_CUSTOM, {'reindex': False})
    assert 'nonbookmarks' not in plan_ids(
        server.ACTION_CUSTOM, {'reindex': False, 'dates': True})


def test_no_other_run_checks_them_even_if_asked():
    for action in server.ACTIONS:
        if action in server.NON_BOOKMARK_ACTIONS: continue
        assert 'nonbookmarks' not in plan_ids(action), action

# endregion


# region marking their series

def test_their_series_are_marked_whether_or_not_the_series_option_is_on(library, capsys):
    seed(library,
         work('1', False, **{strings.SERIES_MEMBERSHIP_FIELD: [{'id': '50', 'title': 'Fifty'}]}),
         work('2', False, from_series=['60']),
         work('3', True, **{strings.SERIES_MEMBERSHIP_FIELD: [{'id': '70', 'title': 'Seventy'}]}))
    job, _ = a_run()
    ao3 = Ao3(repo=MagicMock(spec=Repository), fileops=library, filetypes=[], pages=None,
              series=False, images=False)

    found = server.mark_non_bookmarks(job, library, ao3)

    assert sorted(r['id'] for r in found) == ['1', '2']
    # a bookmark's series is the series option's business, not this one's
    assert sorted(ao3.series_marked) == ['50', '60']
    assert strings.AO3_INFO_NON_BOOKMARKS.format(2) in capsys.readouterr().out


def test_a_work_already_indexed_this_run_is_left_out(library):
    seed(library, work('1', False), work('2', False))
    job, _ = a_run()
    ao3 = Ao3(repo=MagicMock(spec=Repository), fileops=library, filetypes=[], pages=None,
              series=False, images=False)
    ao3.reindexed.add('1')

    assert [r['id'] for r in server.mark_non_bookmarks(job, library, ao3)] == ['2']

# endregion


# region reading the rest one at a time

def reader(reached: set[str], fails: str = '') -> MagicMock:
    ao3 = MagicMock()
    ao3.reindexed = set(reached)

    def refresh(record):
        if record['id'] == fails: raise exceptions.Ao3DownloaderException('gone')
        return {**record, 'fresh': True}

    ao3.refresh_one.side_effect = refresh
    return ao3


def test_only_what_the_series_walk_did_not_reach_is_opened(capsys):
    job, events = a_run()
    ao3 = reader({'1'})

    fresh = server.update_non_bookmarks(job, ao3, [work('1', False), work('2', False)], None)

    assert [r['id'] for r in fresh] == ['2']
    assert [c.args[0]['id'] for c in ao3.refresh_one.call_args_list] == ['2']
    assert marks(events) == [('nonbookmarks', progress.STEP_RUNNING),
                             ('nonbookmarks', progress.STEP_DONE)]
    assert strings.AO3_INFO_NON_BOOKMARKS_READING.format(1) in capsys.readouterr().out


def test_with_everything_reached_the_step_is_skipped(capsys):
    job, events = a_run()
    ao3 = reader({'1'})

    assert server.update_non_bookmarks(job, ao3, [work('1', False)], None) == []
    ao3.refresh_one.assert_not_called()
    assert marks(events) == [('nonbookmarks', progress.STEP_SKIPPED)]
    assert strings.AO3_INFO_NON_BOOKMARKS_NONE_LEFT in capsys.readouterr().out


def test_a_work_that_will_not_read_is_a_failure_and_the_rest_carry_on():
    job, _ = a_run()
    ao3 = reader(set(), fails='1')

    fresh = server.update_non_bookmarks(job, ao3, [work('1', False), work('2', False)], None)

    assert [r['id'] for r in fresh] == ['2']
    ao3.record_failure.assert_called_once()
    assert ao3.record_failure.call_args.args[0] == work('1', False)['link']


def test_a_lapsed_login_ends_the_run():
    job, _ = a_run()
    ao3 = reader(set())
    ao3.refresh_one.side_effect = exceptions.SessionExpiredException('expired')

    with pytest.raises(exceptions.SessionExpiredException):
        server.update_non_bookmarks(job, ao3, [work('1', False)], None)

# endregion


# region the two steps together

def test_without_the_option_nothing_is_read_from_the_index(monkeypatch):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({}))
    job.steps = server.Steps(None, server.step_plan(job))
    monkeypatch.setattr(server.shared, 'read_index',
                        MagicMock(side_effect=AssertionError('read the index')))
    ao3 = MagicMock(series_marked={})

    assert server.index_series_and_non_bookmarks(job, MagicMock(), ao3, None) == []


def test_with_the_option_the_works_both_steps_read_go_on_to_download(library):
    seed(library,
         work('1', False, **{strings.SERIES_MEMBERSHIP_FIELD: [{'id': '50', 'title': 'Fifty'}]}),
         work('2', False))
    job, events = a_run()
    ao3 = Ao3(repo=MagicMock(spec=Repository), fileops=library, filetypes=[], pages=None,
              series=False, images=False)

    def walk():
        # the series walk reaches work 1
        ao3.reindexed.add('1')
        return [work('1', False)]

    ao3.walk_marked_series = walk
    ao3.refresh_one = lambda record: {**record, 'fresh': True}

    works = server.index_series_and_non_bookmarks(job, library, ao3, None)

    assert sorted(w['id'] for w in works) == ['1', '2']
    ids = [e['id'] for e in events if e['type'] == progress.STEP]
    assert ids.index('series') < ids.index('nonbookmarks')

# endregion
