"""Resuming a stopped, failed or interrupted run - see RESUMING.md.

A run saves how far it got as it goes; a resumed run takes the earlier attempt's workflow,
settings and progress, and carries on: a walk sorted by date bookmarked from the page it
stopped on (found again however the pages have moved), a walk sorted by date updated from
the top, and everything after indexing over the works the earlier attempt had settled.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import parse_text, progress, runs, server, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository

LINK = 'https://archiveofourown.org/users/Someone/bookmarks?' + strings.AO3_SORT_BY_BOOKMARKED


# region a listing, and a library to index it into

def blurb(work: int) -> str:
    """A bookmark blurb; a higher work number was bookmarked later, on day `work` of 2025."""
    day = f'{work:02d} Jan 2025'
    return (f'<li id="bookmark_{work}" class="bookmark blurb group work-{work} user-1">'
            f'<div class="header module"><h4 class="heading"><a href="/works/{work}">'
            f'Work {work}</a> by <a href="/users/a/pseuds/a" rel="author">A</a></h4>'
            f'<p class="datetime">{day}</p></div>'
            f'<div class="user module group"><p class="datetime">{day}</p></div></li>')


def listing(*pages: list[int], link: str = LINK) -> dict[str, BeautifulSoup]:
    """Pages of a listing by address, each holding these works newest first."""
    numbers = ''.join(f'<li>{i}</li>' for i in range(1, len(pages) + 1))
    pagination = f'<ol class="pagination actions">{numbers}</ol>' if len(pages) > 1 else ''
    return {parse_text.set_page_number(link, i): BeautifulSoup(
        f'<ol class="bookmark index group">{"".join(blurb(w) for w in works)}</ol>{pagination}',
        'html.parser') for i, works in enumerate(pages, start=1)}


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()
    return fileops


def an_ao3(fileops: FileOps, pages: dict) -> tuple[Ao3, MagicMock]:
    repo = MagicMock(spec=Repository)
    repo.get_soup.side_effect = lambda link: pages[link]
    return Ao3(repo=repo, fileops=fileops, filetypes=['HTML'], pages=None, series=False,
               images=False), repo


def seed(fileops: FileOps, *works: int) -> None:
    writer, _ = an_ao3(fileops, {})
    for work in works:
        writer.save_metadata({'id': str(work), 'title': f'Work {work}', 'authors': ['A'],
                              'link': f'https://archiveofourown.org/works/{work}'})


def a_job(fileops: FileOps, action=server.ACTION_BOOKMARKS, earlier: dict | None = None,
          baseline: str = '2025-03-01T10:00:00') -> tuple[server.Job, list[dict]]:
    job = server.Job(action, ['JSON', 'HTML'], 'Someone')
    job.record = runs.RunRecord(fileops, job.id, job.action, 'Full scan', job.filetypes, {})
    if earlier is not None:
        job.resume = {'id': 'earlier', 'file': '', 'first': 'earlier', 'baseline': baseline,
                      'progress': earlier}
        job.baseline = baseline
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))
    return job, events


def fetched(repo: MagicMock) -> list[int]:
    return [parse_text.get_page_number(c.args[0]) for c in repo.get_soup.call_args_list]

# endregion


# region finding where the earlier attempt stopped

ANCHOR = {'id': 'bookmark_7', 'date': '2025-01-07'}


def test_the_bookmark_is_found_where_it_was():
    ao3, repo = an_ao3(MagicMock(), listing([10, 9], [8, 7], [6, 5]))
    assert server.find_anchor(ao3, LINK, 2, ANCHOR) == 2
    assert fetched(repo) == [2]


def test_bookmarks_added_since_move_it_down_and_the_dates_say_so():
    # two new bookmarks at the top push every page along
    ao3, repo = an_ao3(MagicMock(), listing([12, 11], [10, 9], [8, 7], [6, 5]))
    assert server.find_anchor(ao3, LINK, 2, ANCHOR) == 3
    assert fetched(repo) == [2, 3]


def test_bookmarks_removed_since_move_it_up():
    ao3, repo = an_ao3(MagicMock(), listing([8, 7], [6, 5]))
    assert server.find_anchor(ao3, LINK, 2, ANCHOR) == 1
    assert fetched(repo) == [2, 1]


def test_a_page_past_the_end_of_a_shorter_listing_is_brought_back_to_it():
    pages = listing([8, 7], [6, 5])
    # ao3 answers a page past the end with an empty one, still showing the real page count
    pages[parse_text.set_page_number(LINK, 9)] = BeautifulSoup(
        '<ol class="bookmark index group"></ol>'
        '<ol class="pagination actions"><li>1</li><li>2</li></ol>', 'html.parser')
    ao3, repo = an_ao3(MagicMock(), pages)
    assert server.find_anchor(ao3, LINK, 9, ANCHOR) == 1
    assert fetched(repo) == [9, 2, 1]


def test_a_bookmark_that_is_gone_is_not_found():
    # unbookmarked since: nowhere to carry on from, so the walk starts again
    ao3, _ = an_ao3(MagicMock(), listing([10, 9], [8, 6], [5, 4]))
    assert server.find_anchor(ao3, LINK, 2, ANCHOR) is None

# endregion


# region a walk that saves its place, and picks it up again

def test_a_walk_saves_its_page_its_last_bookmark_and_its_works(library):
    ao3, _ = an_ao3(library, listing([10, 9], [8, 7]))
    job, _ = a_job(library)

    server.walk_listing(job, library, ao3, 'all', LINK, anchored=True, own_bookmarks=True)

    walk = job.progress()['walks']['all']
    assert walk == {'page': 2, 'anchor': ANCHOR, 'done': True,
                    'works': ['10', '9', '8', '7']}
    # and on disk, not only in memory
    with open(job.record.path, encoding='utf-8') as f:
        assert json.load(f)['progress']['walks']['all']['done'] is True


def test_a_resumed_walk_carries_on_from_the_page_it_stopped_on(library):
    seed(library, 10, 9, 8, 7)
    ao3, repo = an_ao3(library, listing([12, 11], [10, 9], [8, 7], [6, 5]))
    job, _ = a_job(library, earlier={'walks': {'all': {
        'page': 2, 'anchor': ANCHOR, 'done': False, 'works': ['10', '9', '8', '7']}}})

    records = server.walk_listing(job, library, ao3, 'all', LINK, anchored=True,
                                  own_bookmarks=True)

    # found on page 3 now, re-read from there; pages 1 and 2 were the first attempt's
    assert fetched(repo) == [2, 3, 3, 4]
    assert sorted(int(r['id']) for r in records) == [5, 6, 7, 8, 9, 10]
    assert job.progress()['walks']['all']['done'] is True


def test_a_walk_the_earlier_attempt_finished_is_not_walked_again(library):
    seed(library, 10, 9)
    ao3, repo = an_ao3(library, {})
    job, _ = a_job(library, earlier={'walks': {'all': {'done': True, 'works': ['10', '9']}}})

    records = server.walk_listing(job, library, ao3, 'all', LINK, anchored=True)

    repo.get_soup.assert_not_called()
    assert ao3.walk_skipped
    assert [r['id'] for r in records] == ['10', '9']


def test_a_listing_sorted_by_date_updated_is_walked_again_from_the_top(library):
    ao3, repo = an_ao3(library, listing([10, 9], [8, 7]))
    job, _ = a_job(library, earlier={'walks': {'updated': {
        'page': 2, 'anchor': ANCHOR, 'done': False, 'works': ['10', '9']}}})

    server.walk_listing(job, library, ao3, 'updated', LINK, anchored=False)

    assert fetched(repo) == [1, 2]


def test_a_walk_that_was_stopped_is_not_saved_as_done(library):
    ao3, _ = an_ao3(library, listing([10, 9], [8, 7]))
    job, _ = a_job(library)
    job.cancel.set()
    ao3.cancelled = job.cancel.is_set

    server.walk_listing(job, library, ao3, 'all', LINK, anchored=True)

    assert not job.progress().get('walks', {}).get('all', {}).get('done')

# endregion


# region the steps after indexing

def test_series_the_earlier_attempt_walked_are_not_walked_again(library):
    seed(library, 1)
    ao3, repo = an_ao3(library, {})
    job, events = a_job(library, earlier={'seriesMarked': [{'id': '50', 'title': 'S'}],
                                          'seriesDone': ['50'], 'seriesWorks': ['1']})
    server.restore_series(job, ao3)

    works = server.index_marked_series(job, ao3, None)

    repo.get_soup.assert_not_called()
    assert [w['id'] for w in works] == ['1']
    assert ('series', progress.STEP_EARLIER) in [(e['id'], e['status']) for e in events
                                                 if e['type'] == progress.STEP]


def test_non_bookmarks_the_earlier_attempt_read_are_not_read_again(library):
    job, _ = a_job(library, earlier={'nonBookmarksDone': ['1']})
    ao3 = MagicMock(reindexed=set())
    ao3.refresh_one.side_effect = lambda record: record

    works = server.update_non_bookmarks(
        job, ao3, [{'id': '1', 'link': 'l1'}, {'id': '2', 'link': 'l2'}], None)

    assert [c.args[0]['id'] for c in ao3.refresh_one.call_args_list] == ['2']
    assert sorted(w['id'] for w in works) == ['1', '2']
    assert job.progress()['nonBookmarksDone'] == ['1', '2']


def test_fics_the_earlier_attempt_finished_are_not_gone_over_again(library):
    job, _ = a_job(library, server.ACTION_CUSTOM, earlier={'updateDone': ['1']})
    records = [{'id': '1', 'link': 'l1'}, {'id': '2', 'link': 'l2'}]

    with patch.object(server, 'update_one_work', return_value=0) as one, \
         patch.object(server.shared, 'scan_downloaded_works', return_value={}), \
         patch.object(server, 'settle_undated', return_value=(False, 0)):
        server.refresh_and_download(job, library, MagicMock(reindexed=set()), records,
                                    ['HTML'], None)

    assert [c.args[1]['id'] for c in one.call_args_list] == ['2']
    assert sorted(job.progress()['updateDone']) == ['1', '2']


def test_every_step_that_starts_is_written_down(library):
    job, _ = a_job(library)
    job.steps = server.Steps(None, server.step_plan(job), on_start=lambda step, label:
                             job.checkpoint(step=step, stepLabel=label))
    job.steps.start('series')
    assert job.progress()['step'] == 'series'
    assert job.progress()['stepLabel'] == strings.STEP_SERIES


def test_a_resumed_run_goes_straight_to_the_works_the_earlier_attempt_settled(library):
    seed(library, 1, 2)
    job, events = a_job(library, server.ACTION_QUICK, earlier={'scope': ['2', '1']})

    with patch.object(server, 'download_planned') as downloading, \
         patch.object(server, 'finish_run'):
        server.run_quick(job, library, MagicMock(), None)

    assert [r['id'] for r in downloading.call_args.args[3]] == ['2', '1']
    marks = {e['id']: e['status'] for e in events if e['type'] == progress.STEP}
    assert marks['bookmarked'] == marks['index'] == progress.STEP_EARLIER

# endregion


# region the quick scan's ceiling and floor

def test_a_resumed_quick_scan_keeps_updates_up_to_when_the_first_attempt_started(library):
    job, _ = a_job(library, server.ACTION_QUICK, baseline='2025-03-01T10:00:00',
                   earlier={'floor': '2025-01-01',
                            'walks': {'bookmarked': {'done': True, 'works': []}}})
    older = {'id': '1', 'link': 'l1', 'date_updated': '2025-02-01'}
    newer = {'id': '2', 'link': 'l2', 'date_updated': '2025-04-01'}

    def walk(job, fileops, ao3, name, link, anchored, **kwargs):
        ao3.walk_skipped = name == 'bookmarked'
        assert kwargs['stop_before'] == '2025-01-01'
        return [] if name == 'bookmarked' else [older, newer]

    with patch.object(server, 'walk_listing', walk), \
         patch.object(server, 'index_series_and_non_bookmarks', return_value=[]), \
         patch.object(server, 'download_planned') as downloading, \
         patch.object(server, 'finish_run'):
        server.run_quick(job, library, MagicMock(), None)

    # the one ao3 updated after the first attempt began is the next scan's to find
    assert downloading.call_args.args[3] == [older]


def write_run(fileops: FileOps, **fields) -> dict:
    record = runs.RunRecord(fileops, fields.pop('id', 'x' * 32), fields.pop('action'),
                            'Run', ['JSON', 'HTML'], fields.pop('options', {}))
    record.data.update(fields)
    record.save()
    return record.data


def test_a_quick_scan_measures_back_to_when_a_run_logged_in_not_when_it_finished(library):
    write_run(library, action=server.ACTION_QUICK, status=runs.STATUS_SUCCESS,
              started='2025-06-02T09:00:00', baseline='2025-05-20T08:00:00')
    # a resumed run that finished on the 2nd carries its first attempt's baseline
    assert server.quick_scan_floor(library) == '2025-05-20'

# endregion


# region which runs can be resumed

def test_what_can_and_cannot_be_resumed():
    ok = {'id': 'a', 'action': server.ACTION_QUICK, 'status': runs.STATUS_STOPPED,
          'options': {}, 'progress': {}}
    assert server.resume_problem(ok, set()) == ''
    assert server.resume_problem(None, set()) == strings.RESUME_NOT_FOUND
    assert server.resume_problem({**ok, 'action': server.ACTION_WORK}, set()) == \
        strings.RESUME_WRONG_ACTION
    assert server.resume_problem({**ok, 'status': runs.STATUS_SUCCESS}, set()) == \
        strings.RESUME_FINISHED
    assert server.resume_problem({**ok, 'status': runs.STATUS_RUNNING}, {'a'}) == \
        strings.RESUME_STILL_RUNNING
    assert server.resume_problem({**ok, 'status': runs.STATUS_RUNNING}, set()) == ''
    assert server.resume_problem({k: v for k, v in ok.items() if k != 'progress'}, set()) == \
        strings.RESUME_TOO_OLD


def test_a_custom_run_over_a_slice_cannot_be_resumed_but_all_bookmarks_or_dates_can():
    custom = {'id': 'a', 'action': server.ACTION_CUSTOM, 'status': runs.STATUS_FAILED,
              'progress': {}}
    assert server.resume_problem({**custom, 'options': {'pages': 5}}, set()) == \
        strings.RESUME_SLICE
    assert server.resume_problem({**custom, 'options': {'start': 3}}, set()) == \
        strings.RESUME_SLICE
    assert server.resume_problem({**custom, 'options': {}}, set()) == ''
    assert server.resume_problem({**custom, 'options': {'dates': True}}, set()) == ''


def test_the_list_offers_unfinished_scans_with_warnings():
    finished = {'id': 'b', 'action': server.ACTION_BOOKMARKS, 'status': runs.STATUS_SUCCESS}
    stopped = {'id': 'a', 'action': server.ACTION_QUICK, 'status': runs.STATUS_STOPPED,
               'progress': {}, 'resumedBy': 'c'}
    single = {'id': 'd', 'action': server.ACTION_WORK, 'status': runs.STATUS_FAILED}

    [offered] = server.resumable_among([finished, stopped, single], set())

    assert offered['id'] == 'a' and offered['resumable']
    assert offered['warnings'] == [strings.RESUME_ALREADY_RESUMED, strings.RESUME_NEWER_SCAN]

# endregion


# region taking on the earlier run

def test_a_resumed_run_takes_the_earlier_runs_workflow_settings_and_answers(library):
    write_run(library, id='e' * 32, action=server.ACTION_QUICK, status=runs.STATUS_STOPPED,
              options={'series': True, 'nonBookmarks': True}, baseline='2025-03-01T10:00:00',
              progress={'step': 'check', 'floor': ''},
              choices=[{'question': server.DUPLICATES_QUESTION, 'choice': 'newest'}])
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'e' * 32}))

    server.prepare_resume(job, library)

    assert job.action == server.ACTION_QUICK
    assert job.filetypes == ['JSON', 'HTML']
    assert job.options['series'] and job.options['nonBookmarks']
    assert job.options['resume'] == 'e' * 32
    # asked again, it answers itself with what the earlier attempt was told
    assert job.ask({'name': server.DUPLICATES_QUESTION}, {'choice': 'leave'}) == \
        {'choice': 'newest'}


def test_a_run_that_cannot_be_resumed_is_refused_before_it_starts(library):
    write_run(library, id='f' * 32, action=server.ACTION_QUICK, status=runs.STATUS_SUCCESS,
              progress={})
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'f' * 32}))

    with pytest.raises(Exception, match='nothing to resume'):
        server.prepare_resume(job, library)


def test_a_resumed_run_keeps_the_first_attempts_baseline_and_says_what_it_resumes(library):
    earlier = write_run(library, id='g' * 32, action=server.ACTION_QUICK,
                        status=runs.STATUS_STOPPED, baseline='2025-03-01T10:00:00',
                        resumes='h' * 32, resumesFirst='h' * 32, progress={'floor': '2025-01-01'})
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'g' * 32}))
    server.prepare_resume(job, library)
    job.record = runs.RunRecord(library, job.id, job.action, 'Quick scan', job.filetypes,
                                job.options)

    server.begin_record(job, library)

    assert job.record.data['baseline'] == '2025-03-01T10:00:00'
    assert job.record.data['resumes'] == 'g' * 32
    # the chain goes back to the first attempt, however many resumes there have been
    assert job.record.data['resumesFirst'] == 'h' * 32
    assert job.record.data['progress'] == {'floor': '2025-01-01'}
    assert runs.find_run(library, earlier['id'])['resumedBy'] == job.id


def test_a_fresh_run_is_given_the_moment_it_logged_in(library):
    job, _ = a_job(library)
    server.begin_record(job, library)
    assert job.record.data['baseline'] == job.baseline
    assert job.record.data['resumes'] is None

# endregion


def test_the_helper_lists_the_runs_it_is_working_on():
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'Someone')
    finished = server.Job(server.ACTION_QUICK, ['JSON'], 'Someone')
    finished.done.set()
    with patch.dict(server.Handler.jobs, {job.id: job, finished.id: finished}, clear=True):
        assert server.active_job_ids() == {job.id}
