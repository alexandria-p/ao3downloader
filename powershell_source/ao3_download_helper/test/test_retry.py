"""Where indexing broke off, a run that is only partly done, and retrying a run.

A listing walk that stops on an error keeps what it read and says exactly how far it got;
the run carries on, ends as `partial` rather than `success`, and is never a floor for a quick
scan. Any run that has ended can be retried: from the top, carrying on with its indexing,
from its downloads, or only the works it could not get.
"""

import re
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import exceptions, parse_text, progress, runs, server, strings
from source_code.ao3 import Ao3, describe_listing_gap, index_gaps
from source_code.fileio import FileOps
from source_code.repo import Repository

LINK = 'https://archiveofourown.org/users/Someone/bookmarks?' + strings.AO3_SORT_BY_BOOKMARKED


def blurb(work: int) -> str:
    """A bookmark blurb, bookmarked on day `work` of 2025 and updated a day before."""
    marked, updated = f'{work:02d} Jan 2025', f'{work - 1:02d} Jan 2025'
    return (f'<li id="bookmark_{work}" class="bookmark blurb group work-{work} user-1">'
            f'<div class="header module"><h4 class="heading"><a href="/works/{work}">'
            f'Work {work}</a> by <a href="/users/a/pseuds/a" rel="author">A</a></h4>'
            f'<p class="datetime">{updated}</p></div>'
            f'<div class="user module group"><p class="datetime">{marked}</p></div></li>')


def listing(*pages: list[int], link: str = LINK) -> dict[str, BeautifulSoup]:
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


def breaking_at(fileops: FileOps, pages: dict, broken: int) -> Ao3:
    """An Ao3 over `pages` whose page `broken` cannot be read."""
    repo = MagicMock(spec=Repository)

    def get_soup(link):
        if parse_text.get_page_number(link) == broken:
            raise exceptions.Ao3DownloaderException('the page would not load')
        return pages[link]
    repo.get_soup.side_effect = get_soup
    return Ao3(repo=repo, fileops=fileops, filetypes=['HTML'], pages=None, series=False,
               images=False)


def write_run(fileops: FileOps, **fields) -> dict:
    record = runs.RunRecord(fileops, fields.pop('id', 'x' * 32), fields.pop('action'),
                            'Run', ['JSON', 'HTML'], fields.pop('options', {}))
    record.data.update(fields)
    record.save()
    return record.data


# region a walk that breaks off says exactly how far it got

def test_a_walk_that_breaks_off_keeps_its_pages_and_records_where_it_stopped(library):
    pages = listing([20, 19], [18, 17], [16, 15], [14, 13], [12, 11])
    ao3 = breaking_at(library, pages, 3)

    records = ao3.get_metadata(LINK, False)

    assert [r['id'] for r in records] == ['20', '19', '18', '17']
    assert ao3.walk_failed and not ao3.walk_finished
    [gap] = ao3.index_failures
    assert gap == {**gap, 'kind': 'listing', 'sort': 'bookmarked', 'firstPage': 1,
                   'lastPage': 2, 'failedPage': 3, 'totalPages': 5, 'works': 4,
                   'reachedBookmarked': '2025-01-17', 'reachedUpdated': '2025-01-16',
                   'error': 'the page would not load'}


def test_the_line_said_names_the_pages_read_the_page_that_failed_and_the_date_reached(library):
    ao3 = breaking_at(library, listing([20, 19], [18, 17], [16, 15]), 3)
    ao3.get_metadata(LINK, False)

    assert describe_listing_gap(ao3.index_failures[0]) == (
        'indexing stopped: your bookmarks could not be read at page 3 of 3. pages 1 to 2 '
        'were indexed (4 works). the last page read reached works bookmarked on 2025-01-17.')


def test_a_walk_that_breaks_on_its_first_page_says_no_page_was_read(library):
    ao3 = breaking_at(library, listing([20, 19], [18, 17]), 1)

    assert ao3.get_metadata(LINK, False) == []
    [gap] = ao3.index_failures
    assert gap['lastPage'] is None and gap['failedPage'] == 1 and gap['totalPages'] is None
    assert 'no page was indexed before it' in describe_listing_gap(gap)


def test_a_listing_sorted_by_date_updated_reports_the_updated_date_it_reached(library):
    link = 'https://archiveofourown.org/users/Someone/bookmarks?' + strings.AO3_SORT_BY_UPDATED
    ao3 = breaking_at(library, listing([20, 19], [18, 17], [16], link=link), 3)
    ao3.get_metadata(link, False)

    gap = ao3.index_failures[0]
    assert gap['sort'] == 'updated'
    assert describe_listing_gap(gap).endswith('reached works updated on 2025-01-16.')


def test_a_walk_that_ends_as_it_should_leaves_no_gap(library):
    ao3 = breaking_at(library, listing([20, 19], [18, 17]), 99)
    ao3.get_metadata(LINK, False)

    assert ao3.walk_finished and not ao3.walk_failed and ao3.index_failures == []


def test_a_stop_is_not_a_gap(library):
    ao3 = breaking_at(library, listing([20, 19], [18, 17]), 99)
    ao3.cancelled = lambda: True

    ao3.get_metadata(LINK, False)

    assert ao3.index_failures == [] and not ao3.walk_failed


def test_a_fic_ficHub_supplied_in_the_end_is_not_left_as_a_gap():
    ao3 = MagicMock()
    ao3.index_failures = [{'kind': 'work', 'id': '1'}, {'kind': 'work', 'id': '2'},
                          {'kind': 'listing'}]
    ao3.failures = [{'id': '2'}]

    assert index_gaps(ao3) == [{'kind': 'work', 'id': '2'}, {'kind': 'listing'}]

# endregion


# region the run is partly done, and the checklist says so

def test_a_run_whose_indexing_broke_off_is_partly_done_not_a_success(library):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone', server.resolve_options({}))
    job.record = runs.RunRecord(library, job.id, job.action, 'Run', ['JSON'], {})
    job.ao3 = breaking_at(library, listing([20], [18]), 2)
    job.ao3.get_metadata(LINK, False)

    server.close_record(job, runs.STATUS_SUCCESS)

    assert job.record.data['status'] == runs.STATUS_PARTIAL
    assert job.record.data['indexFailures'][0]['failedPage'] == 2


def test_a_run_with_no_gaps_still_finishes_as_a_success(library):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone', server.resolve_options({}))
    job.record = runs.RunRecord(library, job.id, job.action, 'Run', ['JSON'], {})
    job.ao3 = breaking_at(library, listing([20]), 99)
    job.ao3.get_metadata(LINK, False)

    server.close_record(job, runs.STATUS_SUCCESS)

    assert job.record.data['status'] == runs.STATUS_SUCCESS
    assert job.record.data['indexFailures'] == []


def test_a_broken_walk_marks_its_step_failed_and_a_whole_one_done():
    marked = []
    job = MagicMock()
    job.steps.fail = lambda step: marked.append(('failed', step))
    job.steps.done = lambda step: marked.append(('done', step))

    server.finish_walk_step(job, MagicMock(walk_skipped=False, walk_failed=True), 'index')
    server.finish_walk_step(job, MagicMock(walk_skipped=False, walk_failed=False), 'bookmarked')

    assert marked == [('failed', 'index'), ('done', 'bookmarked')]


def test_the_history_file_keeps_how_each_step_went():
    seen = []
    steps = server.Steps(None, [('login', 'Log in'), ('index', 'Index')],
                         on_change=lambda outcomes: seen.append(outcomes))

    steps.done('login')
    steps.start('index')
    steps.fail('index')

    assert seen[-1] == {'login': progress.STEP_DONE, 'index': progress.STEP_FAILED}


def test_a_partly_done_quick_scan_is_never_a_floor(library):
    write_run(library, id='a' * 32, action=server.ACTION_BOOKMARKS, status=runs.STATUS_SUCCESS,
              started='2025-01-01T09:00:00')
    write_run(library, id='b' * 32, action=server.ACTION_QUICK, status=runs.STATUS_PARTIAL,
              started='2025-06-01T09:00:00')

    assert server.quick_scan_floor(library) == '2025-01-01'
    assert [run['id'] for run in server.floor_runs(library)] == ['a' * 32]

# endregion


# region how a run can be retried

def a_record(**fields) -> dict:
    return {'id': 'r', 'action': server.ACTION_QUICK, 'status': runs.STATUS_STOPPED,
            'options': {}, 'progress': {}, 'failures': [], **fields}


@pytest.mark.parametrize('status', [runs.STATUS_SUCCESS, runs.STATUS_FAILED, runs.STATUS_PARTIAL,
                                    runs.STATUS_STOPPED, runs.STATUS_INTERRUPTED,
                                    runs.STATUS_ABANDONED])
def test_any_run_that_has_ended_can_be_retried_from_the_top(status):
    assert server.retry_problem(a_record(status=status), server.RETRY_TOP, set()) == ''


def test_a_run_still_going_is_not_retried():
    record = a_record(status=runs.STATUS_RUNNING)

    assert server.retry_problem(record, server.RETRY_TOP, {'r'}) == strings.RETRY_STILL_RUNNING
    assert server.retryable_among([record], {'r'}) == []


def test_only_a_run_that_settled_its_works_can_go_straight_to_its_downloads():
    assert server.retry_problem(a_record(), server.RETRY_DOWNLOADS, set()) == \
        strings.RETRY_NO_DOWNLOADS
    assert server.retry_problem(a_record(progress={'scope': ['1']}), server.RETRY_DOWNLOADS,
                                set()) == ''


def test_only_a_run_with_failures_can_retry_just_those():
    assert server.retry_problem(a_record(), server.RETRY_FAILED, set()) == strings.RETRY_NO_FAILURES
    record = a_record(failures=[{'id': '7', 'link': 'https://archiveofourown.org/works/7'}])
    assert server.retry_problem(record, server.RETRY_FAILED, set()) == ''


def test_a_single_fic_run_is_offered_the_top_and_its_failed_fic_only():
    record = a_record(action=server.ACTION_WORK, url='https://archiveofourown.org/works/7',
                      failures=[{'id': '7', 'link': 'https://archiveofourown.org/works/7'}])

    choices = server.retry_choices(record, set())

    assert [m['mode'] for m in choices['modes']] == [server.RETRY_TOP, server.RETRY_FAILED]
    assert choices['default'] == server.RETRY_FAILED and choices['failedWorks'] == 1


def test_several_fics_can_also_carry_on_from_where_they_stopped():
    record = a_record(action=server.ACTION_WORKS, url='https://archiveofourown.org/works/7',
                      failures=[{'id': '7', 'link': 'https://archiveofourown.org/works/7'}])

    choices = server.retry_choices(record, set())

    assert [m['mode'] for m in choices['modes']] == [server.RETRY_TOP, server.RETRY_DOWNLOADS,
                                                     server.RETRY_FAILED]
    # it stopped, so carrying on is offered first - which takes in its failed fic too
    assert choices['default'] == server.RETRY_DOWNLOADS


@pytest.mark.parametrize('record, wanted', [
    # it reached the end, but some indexing failed: index everything again
    (a_record(status=runs.STATUS_PARTIAL, indexFailures=[{'kind': 'listing'}]), server.RETRY_REINDEX),
    # it reached the end, and only downloads failed: just those
    (a_record(status=runs.STATUS_PARTIAL,
              failures=[{'id': '9', 'link': 'https://archiveofourown.org/works/9'}]),
     server.RETRY_FAILED),
    # stopped while indexing: carry on with it
    (a_record(progress={'steps': {'index': progress.STEP_FAILED}}), server.RETRY_INDEX),
    # stopped after settling its works: carry on with the downloads
    (a_record(progress={'scope': ['1'], 'steps': {'index': progress.STEP_DONE}}),
     server.RETRY_DOWNLOADS),
    # interrupted while indexing, before settling anything
    (a_record(status=runs.STATUS_INTERRUPTED,
              progress={'steps': {'index': progress.STEP_RUNNING}}), server.RETRY_INDEX),
    # finished, but some works would not come
    (a_record(status=runs.STATUS_SUCCESS, failures=[{'id': '7'}]), server.RETRY_FAILED),
    # finished cleanly: the whole run again
    (a_record(status=runs.STATUS_SUCCESS), server.RETRY_TOP),
])
def test_the_retry_offered_first_picks_up_from_the_first_step_that_did_not_finish(record, wanted):
    assert server.retry_choices(record, set())['default'] == wanted


def test_each_way_of_retrying_takes_on_what_it_needs_of_the_earlier_attempt():
    earlier = a_record(progress={'floor': '2025-01-01', 'scope': ['1', '2'], 'step': 'download',
                                 'walks': {'bookmarked': {'done': True}}},
                       failures=[{'id': '9', 'link': 'https://archiveofourown.org/works/9'}])

    assert server.retry_progress(earlier, server.RETRY_TOP) == {'floor': '2025-01-01'}
    assert server.retry_progress(earlier, server.RETRY_INDEX) == {
        'floor': '2025-01-01', 'walks': {'bookmarked': {'done': True}}}
    assert server.retry_progress(earlier, server.RETRY_DOWNLOADS) == earlier['progress']
    assert server.retry_progress(earlier, server.RETRY_FAILED) == {
        'floor': '2025-01-01', 'scope': ['9']}


def test_a_retry_from_the_top_keeps_the_first_attempts_window(library):
    write_run(library, id='e' * 32, action=server.ACTION_QUICK, status=runs.STATUS_PARTIAL,
              baseline='2025-03-01T10:00:00', progress={'floor': '2025-02-01', 'scope': ['1']})
    job = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'e' * 32, 'retryMode': 'top'}))

    server.prepare_resume(job, library)

    assert job.action == server.ACTION_QUICK
    # its floor, and up to when it first started - nothing settled is carried over
    assert job.resume['progress'] == {'floor': '2025-02-01'}
    assert job.resume['baseline'] == '2025-03-01T10:00:00'


def test_retrying_a_fic_runs_failures_asks_for_just_those_fics(library):
    write_run(library, id='f' * 32, action=server.ACTION_WORKS, status=runs.STATUS_PARTIAL,
              url='https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/2\n'
                  'https://archiveofourown.org/works/3',
              failures=[{'id': '2', 'link': 'https://archiveofourown.org/works/2'},
                        {'id': '3', 'link': 'https://archiveofourown.org/works/3'}])
    job = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'f' * 32, 'retryMode': 'failed'}))

    server.prepare_resume(job, library)

    assert job.action == server.ACTION_WORKS
    assert job.url == 'https://archiveofourown.org/works/2\nhttps://archiveofourown.org/works/3'


def test_a_retry_mode_the_run_cannot_take_is_refused_before_anything_starts(library):
    write_run(library, id='g' * 32, action=server.ACTION_QUICK, status=runs.STATUS_SUCCESS,
              progress={})
    job = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'g' * 32, 'retryMode': 'failed'}))

    with pytest.raises(exceptions.Ao3DownloaderException, match='nothing that failed'):
        server.prepare_resume(job, library)


def test_an_unknown_retry_mode_is_dropped_rather_than_trusted():
    assert server.resolve_options({'retryMode': 'everything'})['retryMode'] == ''

# endregion


# region every kind of run can be retried, a retry is a run of its own, and it can be retried

def started(library, record_id: str, mode: str) -> server.Job:
    """A retry of the run `record_id`, taken on as the run thread does before it logs in."""
    job = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone',
                     server.resolve_options({'resume': record_id, 'retryMode': mode}))
    server.prepare_resume(job, library)
    return job


@pytest.mark.parametrize('action', [server.ACTION_BOOKMARKS, server.ACTION_QUICK,
                                    server.ACTION_CUSTOM, server.ACTION_COLLECTIONS,
                                    server.ACTION_COLLECTION])
@pytest.mark.parametrize('mode', [server.RETRY_TOP, server.RETRY_INDEX])
def test_every_scan_and_collection_run_can_be_retried(library, action, mode):
    write_run(library, id='s' * 32, action=action, status=runs.STATUS_STOPPED,
              url='https://archiveofourown.org/collections/yuletide', progress={'walks': {}})

    job = started(library, 's' * 32, mode)

    assert job.action == action
    assert job.options['retryMode'] == mode


@pytest.mark.parametrize('action, url', [
    (server.ACTION_WORK, 'https://archiveofourown.org/works/1'),
    (server.ACTION_WORKS, 'https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/2'),
])
def test_a_fic_run_can_be_retried_from_the_top_with_the_fics_it_was_given(library, action, url):
    write_run(library, id='w' * 32, action=action, status=runs.STATUS_SUCCESS, url=url)

    job = started(library, 'w' * 32, server.RETRY_TOP)

    assert job.action == action and job.url == url


def test_a_fic_run_from_before_runs_kept_their_links_cannot_be_retried(library):
    record = a_record(action=server.ACTION_WORK)
    assert server.retry_problem(record, server.RETRY_TOP, set()) == strings.RETRY_NO_FIC_LINKS


def test_a_retry_is_a_new_run_of_its_own_linked_both_ways_to_the_one_it_retries(library):
    earlier = write_run(library, id='a' * 32, action=server.ACTION_QUICK,
                        status=runs.STATUS_STOPPED, baseline='2025-03-01T10:00:00',
                        progress={'floor': '2025-02-01'})
    job = started(library, 'a' * 32, server.RETRY_INDEX)
    job.record = runs.RunRecord(library, job.id, job.action, 'Quick Scan', job.filetypes,
                                job.options)

    server.begin_record(job, library)

    assert job.id != earlier['id']
    assert job.record.data['resumes'] == 'a' * 32
    assert runs.find_run(library, 'a' * 32)['resumedBy'] == job.id
    # still measuring from when the first attempt logged in
    assert job.record.data['baseline'] == '2025-03-01T10:00:00'
    assert len(runs.read_runs(library)) == 2


def test_a_retry_can_itself_be_retried_and_keeps_the_first_attempts_window(library):
    write_run(library, id='a' * 32, action=server.ACTION_QUICK, status=runs.STATUS_PARTIAL,
              baseline='2025-03-01T10:00:00', progress={'floor': '2025-02-01'})
    # the first retry, which itself broke off
    write_run(library, id='b' * 32, action=server.ACTION_QUICK, status=runs.STATUS_FAILED,
              baseline='2025-03-01T10:00:00', resumes='a' * 32, resumesFirst='a' * 32,
              progress={'floor': '2025-02-01'}, options={'retryMode': 'index'})

    assert server.retry_choices(runs.find_run(library, 'b' * 32), set())['default']
    job = started(library, 'b' * 32, server.RETRY_TOP)

    assert job.resume['id'] == 'b' * 32 and job.resume['first'] == 'a' * 32
    assert job.resume['baseline'] == '2025-03-01T10:00:00'
    assert job.resume['progress'] == {'floor': '2025-02-01'}


def test_a_retry_of_a_fic_runs_failures_can_be_retried_in_turn(library):
    write_run(library, id='f' * 32, action=server.ACTION_WORKS, status=runs.STATUS_PARTIAL,
              url='https://archiveofourown.org/works/1\nhttps://archiveofourown.org/works/2',
              failures=[{'id': '2', 'link': 'https://archiveofourown.org/works/2'}])
    job = started(library, 'f' * 32, server.RETRY_FAILED)
    # the retry is a single fic run now, and records the one fic it was given
    assert job.action == server.ACTION_WORK
    write_run(library, id='g' * 32, action=job.action, status=runs.STATUS_PARTIAL, url=job.url,
              failures=[{'id': '2', 'link': 'https://archiveofourown.org/works/2'}])

    again = started(library, 'g' * 32, server.RETRY_FAILED)

    assert again.action == server.ACTION_WORK
    assert again.url == 'https://archiveofourown.org/works/2'


@pytest.mark.parametrize('action', [server.ACTION_COLLECTION, server.ACTION_WORK,
                                    server.ACTION_WORKS])
def test_a_retry_request_carries_no_link_and_is_not_refused_for_it(action):
    # the run takes the earlier run's link from its record, after the request is accepted
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {
        'action': server.ACTION_CUSTOM if action != server.ACTION_COLLECTION else action,
        'username': 'Someone', 'password': 'a-password', 'filetypes': ['JSON'],
        'options': {'resume': 'r' * 32, 'retryMode': 'top'}}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    with patch.object(server.threading, 'Thread'):
        server.Handler.do_POST(handler)

    assert sent['status'] == 202, sent
    assert sent['body']['options']['retryMode'] == 'top'

# endregion



# region carrying on with downloads fetches only what is still missing

FORMATS = ['HTML', 'EPUB', 'PDF', 'MOBI']


def a_fic(work: int) -> dict:
    return {'id': str(work), 'link': f'https://archiveofourown.org/works/{work}',
            'title': f'Work {work}', 'authors': ['A'], 'date_updated': '2025-01-01'}


def downloader(library: FileOps) -> tuple[Ao3, list[tuple[str, str]]]:
    fetched: list[tuple[str, str]] = []
    repo = MagicMock(spec=Repository)

    def download_file(link, filetype):
        fetched.append((re.search(r'/downloads/(\d+)/', link).group(1), filetype))
        return f'{link} {filetype}'.encode()
    repo.download_file.side_effect = download_file
    return Ao3(repo=repo, fileops=library, filetypes=list(FORMATS), pages=None, series=False,
               images=False), fetched


def already_saved(library: FileOps, work: int, formats: list[str]) -> None:
    """What an earlier attempt left: the work's index entry, and these formats on disk."""
    ao3, _ = downloader(library)
    ao3.save_metadata(a_fic(work))
    ao3.filetypes = list(formats)
    ao3.download_one_indexed(a_fic(work), 50, {}, 1, 1)


def test_carrying_on_fetches_only_the_formats_and_fics_the_earlier_attempt_had_not_saved(library):
    # 8 fics: the first 5 had every format saved, the 6th only its html, the last 2 nothing
    ao3, fetched = downloader(library)
    ao3.formats_done = {**{str(w): set(FORMATS) for w in range(1, 6)}, '6': {'HTML'}}

    for done, work in enumerate(range(1, 9), start=1):
        ao3.download_one_indexed(a_fic(work), 50, {}, done, 8)

    assert fetched == [('6', 'EPUB'), ('6', 'PDF'), ('6', 'MOBI'),
                       *[(str(w), f) for w in (7, 8) for f in FORMATS]]


def test_a_run_remembers_every_format_it_saved_whole_for_a_retry_to_carry_on_from(library):
    ao3, _ = downloader(library)
    ao3.filetypes = ['HTML', 'EPUB']
    ao3.download_one_indexed(a_fic(6), 50, {}, 1, 1)
    record = runs.RunRecord(library, 'r' * 32, server.ACTION_BOOKMARKS, 'Run', ['HTML'], {})
    record.data['progress']['formatsDone'] = {'5': ['HTML']}   # from an attempt it carries on

    record.collect(ao3)

    assert record.data['progress']['formatsDone'] == {'5': ['HTML'], '6': ['EPUB', 'HTML']}


def test_a_format_that_did_not_arrive_whole_is_not_remembered_as_done(library):
    ao3, _ = downloader(library)
    ao3.filetypes = ['HTML']
    with patch.object(library, 'saved_intact', return_value=False):
        with pytest.raises(Exception):
            ao3.download_one_indexed(a_fic(6), 50, {}, 1, 1)

    assert ao3.saved_formats == {}


@pytest.mark.parametrize('mode, carries', [
    (server.RETRY_DOWNLOADS, True), (server.RETRY_INDEX, True), (server.RETRY_FAILED, True),
    (server.RETRY_REDOWNLOAD, False), (server.RETRY_REINDEX, False), (server.RETRY_TOP, False),
])
def test_only_the_ways_that_carry_on_pass_over_what_the_earlier_attempt_saved(library, mode, carries):
    write_run(library, id='d' * 32, action=server.ACTION_BOOKMARKS, status=runs.STATUS_STOPPED,
              progress={'scope': ['6'], 'formatsDone': {'6': ['HTML']}},
              failures=[{'id': '6', 'link': 'https://archiveofourown.org/works/6'}])
    already_saved(library, 6, ['HTML'])
    job = started(library, 'd' * 32, mode)
    ao3, fetched = downloader(library)

    job.ao3 = ao3
    ao3.download_one_indexed(a_fic(6), 50, {}, 1, 1)

    assert (('6', 'HTML') in fetched) is not carries
    assert ('6', 'EPUB') in fetched


def test_carrying_on_passes_over_what_was_saved_even_on_a_run_that_overwrites(library):
    # the earlier attempt already did the overwriting; doing it again would spend a request
    # per format for nothing
    write_run(library, id='o' * 32, action=server.ACTION_BOOKMARKS, status=runs.STATUS_STOPPED,
              options={'overwrite': True},
              progress={'scope': ['6'], 'formatsDone': {'6': ['HTML', 'EPUB', 'PDF', 'MOBI']}})
    already_saved(library, 6, FORMATS)
    job = started(library, 'o' * 32, server.RETRY_DOWNLOADS)
    ao3, fetched = downloader(library)
    job.ao3 = ao3

    ao3.download_one_indexed(a_fic(6), 50, {}, 1, 1)

    assert job.options['overwrite'] is True and fetched == []


def test_starting_indexing_from_the_top_keeps_only_the_window_and_the_answers(library):
    write_run(library, id='i' * 32, action=server.ACTION_QUICK, status=runs.STATUS_PARTIAL,
              progress={'floor': '2025-02-01', 'walks': {'bookmarked': {'done': True}},
                        'scope': ['1'], 'formatsDone': {'1': ['HTML']}},
              choices=[{'question': server.DUPLICATES_QUESTION, 'choice': 'newest'}])

    job = started(library, 'i' * 32, server.RETRY_REINDEX)
    assert job.resume['progress'] == {'floor': '2025-02-01'}
    assert server.DUPLICATES_QUESTION in job.prior_answers

    # from the top asks every question again
    assert started(library, 'i' * 32, server.RETRY_TOP).prior_answers == {}


def test_starting_downloads_from_the_top_keeps_the_works_it_settled_on_but_fetches_every_format():
    earlier = a_record(progress={'floor': '', 'scope': ['1', '2'], 'formatsDone': {'1': ['HTML']}})
    assert server.retry_progress(earlier, server.RETRY_REDOWNLOAD) == {'floor': '', 'scope': ['1', '2']}
    assert server.retry_problem(a_record(), server.RETRY_REDOWNLOAD, set()) == \
        strings.RETRY_NO_DOWNLOADS


def test_a_slice_can_start_its_indexing_from_the_top_but_not_carry_on():
    record = a_record(action=server.ACTION_CUSTOM, options={'pages': 5})
    assert server.retry_problem(record, server.RETRY_REINDEX, set()) == ''
    assert server.retry_problem(record, server.RETRY_INDEX, set()) == strings.RESUME_SLICE

# endregion
