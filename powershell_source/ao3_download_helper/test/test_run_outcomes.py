"""How a run that reached its end is judged, and how indexing that fails is caught.

- failed: nothing indexed where it tried, and nothing downloaded
- partial: some indexing failed, or some fic or format could not be downloaded
- success: everything it set out to index and get - bookmarks that were never works aside

and the indexing failures that used to pass unnoticed: a page ao3 answered with 401, 403 or
404, and a page that is not a listing at all.
"""

from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from source_code import exceptions, runs, server, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository

LINK = 'https://archiveofourown.org/users/Someone/bookmarks?' + strings.AO3_SORT_BY_BOOKMARKED


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()
    return fileops


def an_ao3(fileops=None, **found) -> Ao3:
    ao3 = Ao3(repo=MagicMock(spec=Repository), fileops=fileops or MagicMock(), filetypes=['HTML'],
              pages=None, series=False, images=False)
    for name, value in found.items(): setattr(ao3, name, value)
    return ao3


def failure(work: int) -> dict:
    return {'id': str(work), 'link': f'https://archiveofourown.org/works/{work}', 'error': 'x'}


# region what a run that reached its end is called

def test_a_run_that_got_everything_is_a_success_even_with_bookmarks_that_were_not_works():
    ao3 = an_ao3(reindexed={'1'}, downloaded={'1'}, skipped_works=[{'id': '', 'error': 'series'}])
    assert server.outcome_of(ao3) == (runs.STATUS_SUCCESS, '')


def test_a_run_whose_downloads_failed_is_partly_finished():
    ao3 = an_ao3(reindexed={'1', '2'}, downloaded={'1'}, failures=[failure(2)])
    assert server.outcome_of(ao3)[0] == runs.STATUS_PARTIAL


def test_a_run_whose_indexing_partly_failed_is_partly_finished():
    ao3 = an_ao3(reindexed={'1'}, index_failures=[{'kind': 'listing', 'error': 'x'}])
    assert server.outcome_of(ao3)[0] == runs.STATUS_PARTIAL


def test_a_run_whose_indexing_all_failed_and_got_nothing_has_failed():
    ao3 = an_ao3(index_failures=[{'kind': 'listing', 'error': 'x'}])
    assert server.outcome_of(ao3) == (runs.STATUS_FAILED, strings.ERROR_ALL_INDEXING_FAILED)


def test_a_failure_fichub_made_good_does_not_count():
    # a fic run's fic: its page would not read, but FicHub supplied it
    ao3 = an_ao3(reindexed={'1'}, downloaded={'1'},
                 index_failures=[{'kind': 'work', 'id': '1', 'error': 'x'}], failures=[])
    assert server.outcome_of(ao3)[0] == runs.STATUS_SUCCESS

# endregion


# region indexing failures that used to pass unnoticed

def a_page(body: str) -> BeautifulSoup:
    return BeautifulSoup(body, 'html.parser')


def walking(status: int, body: str) -> Ao3:
    ao3 = an_ao3()

    def get_soup(link):
        ao3.repo.last_status = status
        return a_page(body)
    ao3.repo.get_soup.side_effect = get_soup
    return ao3


@pytest.mark.parametrize('status', [401, 403, 404, 410])
def test_a_listing_page_ao3_refused_is_an_indexing_failure_not_the_end_of_the_listing(status):
    ao3 = walking(status, '<h2 class="heading">Error</h2><p>Sorry</p>')

    ao3.get_metadata(LINK, False)

    assert ao3.walk_failed and not ao3.walk_finished
    [gap] = ao3.index_failures
    assert str(status) in gap['error']


def test_a_page_that_is_not_a_listing_is_an_indexing_failure():
    # a login page, or an error page served as 200: no blurbs, and nothing saying it lists
    ao3 = walking(200, '<h2 class="heading">Log In</h2><form></form>')

    ao3.get_metadata(LINK, False)

    assert ao3.walk_failed
    assert ao3.index_failures[0]['error'] == strings.ERROR_LISTING_UNREADABLE


def test_an_empty_listing_is_still_a_listing():
    ao3 = walking(200, '<h2 class="heading">0 Bookmarks by Someone</h2>')

    ao3.get_metadata(LINK, False)

    assert not ao3.walk_failed and ao3.walk_finished


def test_a_fic_that_could_not_be_read_again_is_a_gap_in_the_index():
    ao3 = walking(404, '<p>The page you were looking for does not exist</p>')

    with pytest.raises(Exception):
        ao3.refresh_one({'id': '7', 'link': 'https://archiveofourown.org/works/7'})

    [gap] = ao3.index_failures
    assert gap['kind'] == 'work' and gap['id'] == '7'


def test_a_stop_while_reading_a_fic_again_is_not_a_gap():
    ao3 = an_ao3()
    ao3.repo.get_soup.side_effect = exceptions.CancelledException('stop')

    with pytest.raises(exceptions.CancelledException):
        ao3.refresh_one({'id': '7', 'link': 'https://archiveofourown.org/works/7'})

    assert ao3.index_failures == []

# endregion


# region why it failed is recorded

@pytest.mark.parametrize('error, wanted', [
    (exceptions.Ao3DownException(strings.ERROR_AO3_DOWN), {'reason': 'maintenance'}),
    (exceptions.InvalidStatusCodeException(strings.ERROR_INVALID_STATUS_CODE.format(404)),
     {'reason': 'status', 'status': 404}),
    (exceptions.TimeoutException('slow'), {'reason': 'connection'}),
    (exceptions.Ao3DownloaderException(strings.ERROR_LISTING_UNREADABLE), {'reason': 'no-data'}),
    (exceptions.Ao3DownloaderException(strings.ERROR_WORK_STATS), {'reason': 'no-data'}),
    (ValueError('odd'), {'reason': 'other'}),
    # a work several formats failed for, one of them for maintenance
    (exceptions.DownloadException(f'EPUB: x; PDF: {strings.ERROR_AO3_DOWN}'), {'reason': 'maintenance'}),
])
def test_each_failure_records_why(error, wanted):
    from source_code.ao3 import failure_reason
    assert failure_reason(error) == wanted


def test_a_listing_gap_says_why_it_stopped():
    ao3 = walking(404, '<h2 class="heading">Error</h2>')
    ao3.get_metadata(LINK, False)

    [gap] = ao3.index_failures
    assert (gap['reason'], gap['status']) == ('status', 404)
    from source_code.ao3 import describe_listing_gap
    assert 'AO3 answered with status 404' in describe_listing_gap(gap)


def test_a_failed_download_says_why():
    ao3 = an_ao3()
    ao3.record_failure('https://archiveofourown.org/works/7',
                       exceptions.Ao3DownException(strings.ERROR_AO3_DOWN))
    assert ao3.failures[0]['reason'] == 'maintenance'

# endregion


# region retrying a run that was partly finished

def a_partial(**fields) -> dict:
    return {'id': 'r', 'action': server.ACTION_QUICK, 'status': runs.STATUS_PARTIAL,
            'options': {}, 'url': 'x', 'failures': [], 'indexFailures': [],
            'progress': {'scope': ['1']}, **fields}


def offered(record: dict) -> set[str]:
    return {m['mode'] for m in server.retry_choices(record, set())['modes'] if m['available']}


def test_a_partly_finished_run_has_nothing_to_carry_on_from():
    record = a_partial(failures=[failure(9)])
    assert offered(record) == {server.RETRY_TOP, server.RETRY_REINDEX, server.RETRY_REDOWNLOAD,
                               server.RETRY_FAILED}
    assert server.retry_problem(record, server.RETRY_INDEX, set()) == strings.RETRY_PARTIAL_DONE


def test_index_failures_recommend_indexing_everything_again():
    record = a_partial(indexFailures=[{'kind': 'listing'}], failures=[failure(9)])

    [listed] = server.retryable_among([record], set())

    assert listed['retry']['default'] == server.RETRY_REINDEX
    assert strings.RETRY_WARN_INDEX_FAILED in listed['warnings']


def test_download_failures_alone_recommend_just_those():
    record = a_partial(failures=[failure(9)])

    [listed] = server.retryable_among([record], set())

    assert listed['retry']['default'] == server.RETRY_FAILED
    assert strings.RETRY_WARN_DOWNLOADS_FAILED in listed['warnings']


def test_several_fics_partly_finished_can_still_carry_on_and_are_not_warned_about_indexing():
    record = a_partial(action=server.ACTION_WORKS, indexFailures=[{'kind': 'work', 'id': '9'}],
                       failures=[failure(9)], progress={'formatsDone': {}})

    [listed] = server.retryable_among([record], set())

    assert server.RETRY_DOWNLOADS in offered(record)
    # just the fics re-reads each one, so it is safe after an index failure
    assert listed['retry']['default'] == server.RETRY_FAILED
    assert strings.RETRY_WARN_INDEX_FAILED not in listed['warnings']

# endregion
