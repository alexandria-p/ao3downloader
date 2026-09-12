"""Tests for ao3downloader.ao3.Ao3 class."""

import os
from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import exceptions, indexing, parse_soup, parse_text, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


WORK_URL = 'https://archiveofourown.org/works/123'
SERIES_URL = 'https://archiveofourown.org/series/456'
LISTING_URL = 'https://archiveofourown.org/users/test/bookmarks'


def make_ao3(
    filetypes: list[str] | None = None,
    pages: int = 0,
    series: bool = False,
    images: bool = False,
    mark: bool = False,
    debug: bool = False,
    start: int = 1,
) -> tuple[Ao3, MagicMock, MagicMock]:
    """Create an Ao3 instance with mocked dependencies.
    Returns (ao3, repo_mock, fileops_mock)."""
    repo = MagicMock(spec=Repository)
    fileops = MagicMock(spec=FileOps)
    fileops.get_ini_value_boolean.return_value = debug
    fileops.get_ini_value.return_value = strings.FILE_NAME_PATTERN
    fileops.get_ini_value_integer.return_value = strings.INI_DEFAULT_NAME_LENGTH
    # no index on disk yet, unless a test says otherwise
    fileops.load_json.return_value = None
    ao3 = Ao3(repo=repo, fileops=fileops, filetypes=filetypes or ['EPUB'],
              pages=pages, series=series, images=images, mark=mark, start=start)
    return ao3, repo, fileops


def get_soup_from_fixture(filename: str) -> BeautifulSoup:
    fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', filename + '.html')
    with open(fixture_path) as f:
        return BeautifulSoup(f.read(), 'html.parser')


@contextmanager
def try_download_patches() -> Iterator[None]:
    """Patches proceed() and parse functions for try_download's main flow."""
    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_title', return_value=['My Work']), \
         patch('source_code.parse_soup.get_updated_date', return_value='14 Dec 2024'), \
         patch('source_code.parse_soup.get_download_link', return_value='https://ao3.org/dl/work.epub'), \
         patch('source_code.parse_soup.has_custom_skin', return_value=False), \
         patch('source_code.parse_text.get_valid_filename', return_value='My Work'), \
         patch('source_code.parse_text.get_file_type', return_value='.epub'):
        yield


# region proceed() — locked/deleted/explicit gate
# Uses real fixture HTML to test the integration with parse_soup.

def test_proceed_locked_raises() -> None:
    ao3, _, _ = make_ao3()
    soup = get_soup_from_fixture('lockedWorkLoggedOut')
    with pytest.raises(exceptions.LockedException, match=strings.ERROR_LOCKED):
        ao3.proceed(soup)


def test_proceed_deleted_raises() -> None:
    ao3, _, _ = make_ao3()
    soup = get_soup_from_fixture('deletedWork')
    with pytest.raises(exceptions.DeletedException, match=strings.ERROR_DELETED):
        ao3.proceed(soup)


def test_proceed_hidden_raises() -> None:
    ao3, _, _ = make_ao3()
    soup = get_soup_from_fixture('hiddenWork')
    with pytest.raises(exceptions.HiddenException, match=strings.ERROR_HIDDEN):
        ao3.proceed(soup)


def test_proceed_explicit_follows_proceed_link() -> None:
    ao3, repo, _ = make_ao3()
    soup = get_soup_from_fixture('explicitWorkLoggedOut')
    new_soup = MagicMock()
    repo.get_soup.return_value = new_soup

    result = ao3.proceed(soup)

    repo.get_soup.assert_called_once_with('https://archiveofourown.org/works/35369560?view_adult=true')
    assert result is new_soup


def test_proceed_normal_returns_soup_unchanged() -> None:
    ao3, repo, _ = make_ao3()
    soup = get_soup_from_fixture('unlockedWork')

    result = ao3.proceed(soup)

    assert result is soup
    repo.get_soup.assert_not_called()


def test_proceed_locked_checked_before_deleted() -> None:
    """If both conditions match, locked takes priority over deleted."""
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_soup.is_locked', return_value=True), \
         patch('source_code.parse_soup.is_deleted', return_value=True):
        with pytest.raises(exceptions.LockedException):
            ao3.proceed(MagicMock())

# endregion

# region try_download() — core download logic

def test_try_download_happy_path() -> None:
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.get_book.return_value = b'epub content'

    with try_download_patches():
        log: dict[str, object] = {}
        result = ao3.try_download(WORK_URL, log, None)

    assert result is True
    fileops.save_bytes.assert_called_once_with('My Work.epub', b'epub content')
    assert log['title'] == ['My Work']
    assert log['workskin'] is False


def test_try_download_multiple_filetypes() -> None:
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF'])
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('source_code.parse_text.get_file_type', side_effect=['.epub', '.pdf']):
            result = ao3.try_download(WORK_URL, {}, None)

    assert result is True
    assert fileops.save_bytes.call_count == 2
    fileops.save_bytes.assert_any_call('My Work.epub', b'content')
    fileops.save_bytes.assert_any_call('My Work.pdf', b'content')


def test_try_download_chapters_no_update() -> None:
    """Current chapters == given chapters: no update needed, returns False."""
    ao3, _, fileops = make_ao3()

    with try_download_patches():
        with patch('source_code.parse_soup.get_current_chapters', return_value='5'):
            log: dict[str, object] = {}
            result = ao3.try_download(WORK_URL, log, '5')

    assert result is False
    fileops.save_bytes.assert_not_called()
    assert 'title' not in log  # returned before title was set


def test_try_download_chapters_fewer_than_given() -> None:
    """Current=3, given=5: still no update (3 <= 5)."""
    ao3, _, fileops = make_ao3()

    with try_download_patches():
        with patch('source_code.parse_soup.get_current_chapters', return_value='3'):
            result = ao3.try_download(WORK_URL, {}, '5')

    assert result is False
    fileops.save_bytes.assert_not_called()


def test_try_download_chapters_update_available() -> None:
    """Current=10, given=5: update available (10 > 5), downloads proceed."""
    ao3, repo, fileops = make_ao3()
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('source_code.parse_soup.get_current_chapters', return_value='10'):
            result = ao3.try_download(WORK_URL, {}, '5')

    assert result is True
    fileops.save_bytes.assert_called_once()


def test_try_download_images() -> None:
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'img1data', b'img2data']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img1.png', 'https://example.com/img2.jpg']):
            ao3.try_download(WORK_URL, {}, None)

    assert fileops.save_bytes.call_count == 3  # work file + 2 images
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.png'), b'img1data')
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img001.jpg'), b'img2data')


def test_try_download_image_error_does_not_abort() -> None:
    """A failed image download is logged but doesn't stop remaining images."""
    ao3, repo, fileops = make_ao3(images=True)
    # First call: epub download. Second: img1 fails. Third: img2 succeeds.
    repo.get_book.side_effect = [b'epub', Exception('network error'), b'img2data']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img1.png', 'https://example.com/img2.jpg']):
            result = ao3.try_download(WORK_URL, {}, None)

    assert result is True
    # img2 saved with counter=0 because img1's failure didn't increment counter
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.jpg'), b'img2data')
    # Error logged for the failed image
    error_log_calls = [c for c in fileops.write_log.call_args_list
                       if c[0][0].get('message') == strings.ERROR_IMAGE]
    assert len(error_log_calls) == 1


def test_try_download_image_relative_url_skipped() -> None:
    """A relative URL (starting with /) is skipped but remaining images are still downloaded."""
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'img1data', b'img3data']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img1.png',
                                 '/relative/path.png',
                                 'https://example.com/img3.png']):
            ao3.try_download(WORK_URL, {}, None)

    # epub + img1 + img3; the relative URL is skipped
    assert repo.get_book.call_count == 3
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.png'), b'img1data')
    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img001.png'), b'img3data')


def test_try_download_image_url_query_params_stripped() -> None:
    """Query params in image URL don't pollute the file extension."""
    ao3, repo, fileops = make_ao3(images=True)
    repo.get_book.side_effect = [b'epub', b'imgdata']

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links',
                   return_value=['https://example.com/img.png?token=abc123']):
            ao3.try_download(WORK_URL, {}, None)

    fileops.save_bytes.assert_any_call(os.path.join('images', 'My Work img000.png'), b'imgdata')


def test_try_download_mark_as_read() -> None:
    ao3, repo, _ = make_ao3(mark=True)
    repo.get_book.return_value = b'content'
    soup = MagicMock()
    repo.get_soup.return_value = soup

    with try_download_patches():
        ao3.try_download(WORK_URL, {}, None)

    repo.mark_work_as_read.assert_called_once_with(soup, WORK_URL)


def test_try_download_mark_not_called_when_disabled() -> None:
    ao3, repo, _ = make_ao3(mark=False)
    repo.get_book.return_value = b'content'

    with try_download_patches():
        ao3.try_download(WORK_URL, {}, None)

    repo.mark_work_as_read.assert_not_called()


def test_try_download_images_not_fetched_when_disabled() -> None:
    ao3, repo, _ = make_ao3(images=False)
    repo.get_book.return_value = b'content'

    with try_download_patches():
        with patch('source_code.parse_soup.get_image_links') as mock_img:
            ao3.try_download(WORK_URL, {}, None)

    mock_img.assert_not_called()

# endregion

# region download_work() — try/except/else control flow
# The else block only runs when try completes without exception
# AND without a return statement.

def test_download_work_success_logs() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'try_download', return_value=True):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert log['link'] == WORK_URL
    assert log['success'] is True
    fileops.write_log.assert_called_once_with(log)


def test_download_work_no_update_does_not_log() -> None:
    """When try_download returns False, the early return skips both
    the else block (success log) and the except block. No log at all."""
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'try_download', return_value=False):
        ao3.download_work(WORK_URL, {}, '5')

    fileops.write_log.assert_not_called()


def test_download_work_exception_logs_error() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'try_download', side_effect=exceptions.DeletedException('Deleted')):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert log['success'] is False
    assert log['error'] == 'Deleted'
    fileops.write_log.assert_called_once()


def test_download_work_generic_exception_includes_stacktrace() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'try_download', side_effect=ValueError('unexpected')):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert 'stacktrace' in log
    assert 'ValueError' in str(log['stacktrace'])


def test_download_work_ao3_exception_no_stacktrace() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'try_download', side_effect=exceptions.LockedException('Locked')):
        log: dict[str, object] = {}
        ao3.download_work(WORK_URL, log, None)

    assert 'stacktrace' not in log

# endregion

# region log_error() — stacktrace inclusion

def test_log_error_ao3_exception_no_stacktrace() -> None:
    ao3, _, fileops = make_ao3()
    log: dict[str, object] = {}
    ao3.log_error(log, exceptions.LockedException('test'))

    assert log == {'error': 'test', 'success': False}
    fileops.write_log.assert_called_once_with(log)


def test_log_error_generic_exception_includes_stacktrace() -> None:
    ao3, _, _ = make_ao3()
    log: dict[str, object] = {}
    try:
        raise ValueError('boom')
    except ValueError as e:
        ao3.log_error(log, e)

    assert log['error'] == 'boom'
    assert log['success'] is False
    assert 'ValueError' in str(log['stacktrace'])
    assert 'boom' in str(log['stacktrace'])


def test_log_error_preserves_existing_log_keys() -> None:
    ao3, _, _ = make_ao3()
    log: dict[str, object] = {'link': WORK_URL, 'title': ['My Work']}
    ao3.log_error(log, exceptions.DeletedException('gone'))

    assert log['link'] == WORK_URL
    assert log['title'] == ['My Work']
    assert log['error'] == 'gone'
    assert log['success'] is False

# endregion

# region download_recursive() — dispatch and deduplication

def test_download_recursive_work_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=True), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(WORK_URL, {}, [])

    assert mock_dl.call_args is not None
    args = mock_dl.call_args[0]
    assert args[0] == WORK_URL
    assert args[2] is None  # chapters


def test_download_recursive_series_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=True), \
         patch.object(Ao3, 'download_series') as mock_ds:
        ao3.download_recursive(SERIES_URL, {}, [])

    assert mock_ds.call_args is not None
    args = mock_ds.call_args[0]
    assert args[0] == SERIES_URL


def test_download_recursive_already_visited() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work') as mock_is_work:
        ao3.download_recursive(WORK_URL, {}, [WORK_URL])

    mock_is_work.assert_not_called()


def test_download_recursive_adds_to_visited() -> None:
    ao3, _, _ = make_ao3()
    visited: list[str] = []
    with patch('source_code.parse_text.is_work', return_value=True), \
         patch.object(Ao3, 'download_work'):
        ao3.download_recursive(WORK_URL, {}, visited)

    assert WORK_URL in visited


def test_download_recursive_invalid_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=False):
        with pytest.raises(exceptions.InvalidLinkException):
            ao3.download_recursive('https://example.com/fic/123', {}, [])


def test_download_recursive_listing_paginates() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=2), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2, 2]), \
         patch('source_code.parse_text.get_next_page', return_value=page2), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_listing_respects_page_limit() -> None:
    ao3, repo, _ = make_ao3(pages=2)
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'
    page3 = LISTING_URL + '?page=3'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=5), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2, 2, 3]), \
         patch('source_code.parse_text.get_next_page', side_effect=[page2, page3]), \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_mark_mode_refetches_same_url() -> None:
    """In mark mode, the same URL is re-fetched each iteration (no page increment).
    Breaks when total_pages drops to <= 1 (works disappear after being marked read)."""
    ao3, repo, _ = make_ao3(mark=True)
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    soup1 = MagicMock()
    soup2 = MagicMock()
    repo.get_soup.side_effect = [soup1, soup2]

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', side_effect=lambda s: 2 if s is soup1 else 1), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_next_page') as mock_next, \
         patch.object(Ao3, 'download_work') as mock_dl:
        ao3.download_recursive(LISTING_URL, {}, [])

    mock_next.assert_not_called()
    assert mock_dl.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_recursive_mark_mode_breaks_on_none() -> None:
    """Mark mode also breaks when total_pages is None."""
    ao3, repo, _ = make_ao3(mark=True)
    work1 = 'https://archiveofourown.org/works/111'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_and_series_urls', return_value=[work1]), \
         patch.object(Ao3, 'download_work'):
        ao3.download_recursive(LISTING_URL, {}, [])

    assert repo.get_soup.call_count == 1

# endregion

# region download_series()

def test_download_series_single_page() -> None:
    ao3, _, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_urls', return_value=[work1, work2]), \
         patch('source_code.parse_text.get_page_number', return_value=1), \
         patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download_series(SERIES_URL, {}, [])

    assert mock_dr.call_count == 2


def test_download_series_multi_page() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = SERIES_URL + '?page=2'

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_total_pages', return_value=2), \
         patch('source_code.parse_soup.get_work_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2]), \
         patch('source_code.parse_text.get_next_page', return_value=page2), \
         patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download_series(SERIES_URL, {}, [])

    assert mock_dr.call_count == 2
    assert repo.get_soup.call_count == 2


def test_download_series_calls_proceed() -> None:
    ao3, _, _ = make_ao3()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup) as mock_proceed, \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_urls', return_value=[]), \
         patch('source_code.parse_text.get_page_number', return_value=1):
        ao3.download_series(SERIES_URL, {}, [])

    mock_proceed.assert_called_once()


def test_download_series_exception_logs_with_series_link() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = Exception('network error')

    log: dict[str, object] = {}
    ao3.download_series(SERIES_URL, log, [])

    assert log['link'] == SERIES_URL
    assert log['success'] is False
    assert log['error'] == 'network error'

# endregion

# region Entry points — download(), update(), update_series()

def test_download_creates_visited_list() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'download_recursive') as mock_dr:
        ao3.download(WORK_URL)

    assert mock_dr.call_args is not None
    args = mock_dr.call_args[0]
    assert isinstance(args[2], list)


def test_download_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'download_recursive', side_effect=Exception('boom')):
        ao3.download(WORK_URL)

    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False


def test_update_passes_chapters() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'download_work') as mock_dw:
        ao3.update(WORK_URL, '5')

    assert mock_dw.call_args is not None
    args = mock_dw.call_args[0]
    assert args[0] == WORK_URL
    assert args[2] == '5'


def test_update_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'download_work', side_effect=Exception('boom')):
        ao3.update(WORK_URL, '5')

    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False


def test_update_series_delegates() -> None:
    ao3, _, _ = make_ao3()
    visited = ['already']
    with patch.object(Ao3, 'download_series') as mock_ds:
        ao3.update_series(SERIES_URL, visited)

    assert mock_ds.call_args is not None
    args = mock_ds.call_args[0]
    assert args[0] == SERIES_URL


def test_update_series_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'download_series', side_effect=Exception('boom')):
        ao3.update_series(SERIES_URL, [])

    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False

# endregion

# region get_work_links_recursive()

def test_get_work_links_returns_collected_links() -> None:
    ao3, _, _ = make_ao3()
    with patch.object(Ao3, 'get_work_links_recursive') as mock_rec:
        def populate_links(links_list: dict[str, object], *args: object) -> None:
            links_list[WORK_URL] = None
        mock_rec.side_effect = populate_links
        result = ao3.get_work_links(LISTING_URL, False)

    assert result == {WORK_URL: None}


def test_get_work_links_catches_exception() -> None:
    ao3, _, fileops = make_ao3()
    with patch.object(Ao3, 'get_work_links_recursive', side_effect=Exception('boom')):
        result = ao3.get_work_links(LISTING_URL, False)

    assert result == {}  # returns empty dict on error
    fileops.write_log.assert_called_once()
    assert fileops.write_log.call_args is not None
    log = fileops.write_log.call_args[0][0]
    assert log['success'] is False
    assert log['message'] == strings.ERROR_LINKS_LIST


def test_get_work_links_recursive_listing_paginates() -> None:
    ao3, repo, _ = make_ao3()
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'
    page2 = LISTING_URL + '?page=2'
    links_list: dict[str, object] = {}

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', return_value=False), \
         patch('source_code.parse_soup.get_total_pages', return_value=2), \
         patch('source_code.parse_soup.get_work_and_series_urls', side_effect=[[work1], [work2]]), \
         patch('source_code.parse_text.get_page_number', side_effect=[1, 2, 2]), \
         patch('source_code.parse_text.get_next_page', return_value=page2):
        ao3.get_work_links_recursive(links_list, LISTING_URL, [], False)

    assert work1 in links_list
    assert work2 in links_list
    assert repo.get_soup.call_count == 2


def test_get_work_links_work_with_metadata() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}
    soup = MagicMock()
    metadata_dict = {'title': 'My Work', 'author': 'Author'}

    with patch('source_code.parse_text.is_work', return_value=True), \
         patch('source_code.parse_soup.get_work_metadata_from_list', return_value=metadata_dict):
        ao3.get_work_links_recursive(links_list, WORK_URL, [], True, soup)

    assert links_list[WORK_URL] == metadata_dict


def test_get_work_links_work_without_metadata() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}

    with patch('source_code.parse_text.is_work', return_value=True):
        ao3.get_work_links_recursive(links_list, WORK_URL, [], False)

    assert WORK_URL in links_list
    assert links_list[WORK_URL] is None


def test_get_work_links_duplicate_work_skipped() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {WORK_URL: None}

    with patch('source_code.parse_text.is_work', return_value=True), \
         patch('source_code.parse_soup.get_work_metadata_from_list') as mock_meta:
        ao3.get_work_links_recursive(links_list, WORK_URL, [], True)

    mock_meta.assert_not_called()


def test_get_work_links_series_collects_works() -> None:
    ao3, _, _ = make_ao3()
    links_list: dict[str, object] = {}
    work1 = 'https://archiveofourown.org/works/111'
    work2 = 'https://archiveofourown.org/works/222'

    with patch('source_code.parse_text.is_work', side_effect=lambda url: '/works/' in url), \
         patch('source_code.parse_text.is_series', side_effect=lambda url: '/series/' in url), \
         patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_total_pages', return_value=None), \
         patch('source_code.parse_soup.get_work_urls', return_value=[work1, work2]), \
         patch('source_code.parse_text.get_page_number', return_value=1):
        ao3.get_work_links_recursive(links_list, SERIES_URL, [], False)

    assert work1 in links_list
    assert work2 in links_list


def test_get_work_links_duplicate_series_skipped() -> None:
    ao3, repo, _ = make_ao3()
    visited_series = [SERIES_URL]

    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=True):
        ao3.get_work_links_recursive({}, SERIES_URL, visited_series, False)

    repo.get_soup.assert_not_called()


def test_get_work_links_invalid_link() -> None:
    ao3, _, _ = make_ao3()
    with patch('source_code.parse_text.is_work', return_value=False), \
         patch('source_code.parse_text.is_series', return_value=False):
        with pytest.raises(exceptions.InvalidLinkException):
            ao3.get_work_links_recursive({}, 'https://example.com/fic', [], False)

# endregion

# region get_metadata() — json export

def _blurb_html(worknum: str, bookmark_id: str | None = None) -> str:
    return (
        f'<li id="bookmark_{bookmark_id or worknum}" class="bookmark blurb group work-{worknum} user-1">'
        f'<div class="header module">'
        f'<h4 class="heading"><a href="/works/{worknum}">Work {worknum}</a> by '
        f'<a href="/users/a/pseuds/a" rel="author">A</a></h4>'
        f'<p class="datetime">01 Jan 2020</p></div>'
        f'<div class="user module group"><p class="datetime">02 Feb 2021</p></div></li>')


def _listing_soup(worknums: list[str], total_pages: int = 1, extra: str = '') -> BeautifulSoup:
    """A real bookmarks listing page, so the crawl exercises the actual blurb parsing."""
    blurbs = ''.join(_blurb_html(n) for n in worknums)
    pagination = ''
    if total_pages > 1:
        items = ''.join(f'<li>{i}</li>' for i in range(1, total_pages + 1))
        pagination = f'<ol class="pagination actions">{items}</ol>'
    return BeautifulSoup(
        f'<ol class="bookmark index group">{blurbs}{extra}</ol>{pagination}', 'html.parser')


def _work_soup(published: str = '01 Jan 2019', status: str = '05 May 2021') -> BeautifulSoup:
    stats = f'<dd class="published">{published}</dd>'
    if status: stats += f'<dd class="status">{status}</dd>'
    return BeautifulSoup(f'<dl class="stats">{stats}</dl>', 'html.parser')


def test_get_metadata_rejects_a_single_work_link() -> None:
    ao3, repo, _ = make_ao3()

    with pytest.raises(exceptions.InvalidLinkException):
        ao3.get_metadata(WORK_URL, False)

    repo.get_soup.assert_not_called()


def test_get_metadata_rejects_a_non_ao3_link() -> None:
    ao3, repo, _ = make_ao3()

    with pytest.raises(exceptions.InvalidLinkException):
        ao3.get_metadata('https://example.com/fic', False)

    repo.get_soup.assert_not_called()


def test_get_metadata_collects_every_work_on_the_page() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert records[0]['link'] == 'https://archiveofourown.org/works/111'
    assert records[0]['date_bookmarked'] == '02 Feb 2021'
    assert repo.get_soup.call_count == 1


def _indexed(*names: str) -> list[str]:
    """Where save_metadata puts json files: the indexing subfolder of downloads."""
    return sorted(os.path.join(strings.INDEXING_FOLDER_NAME, name) for name in names)


def _saved(fileops) -> dict[str, dict]:
    """Filename -> document, for everything save_json was called with."""
    return {call.args[0]: call.args[1] for call in fileops.save_json.call_args_list}


def test_get_metadata_writes_one_file_per_work() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    ao3.get_metadata(LISTING_URL, False)

    saved = _saved(fileops)
    assert sorted(saved) == _indexed('111 Work 111 - A.json', '222 Work 222 - A.json')
    assert saved[_indexed('111 Work 111 - A.json')[0]]['id'] == '111'


def test_get_metadata_puts_json_in_the_indexing_subfolder() -> None:
    # keeps the downloads folder to actual works, with the index beside rather than among
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops))[0]
    assert os.path.dirname(written) == strings.INDEXING_FOLDER_NAME
    # the file name itself is unchanged, so it still matches its downloaded work
    assert os.path.basename(written) == '111 Work 111 - A.json'


def test_get_metadata_adds_a_reading_when_the_fic_has_changed() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'])
    # what a previous run left behind, with a different kudos count
    fileops.load_json.return_value = {
        'id': '111',
        indexing.LAST_INDEXED: '2020-01-01T00:00:00+00:00',
        indexing.INDEXES: [{indexing.INDEXED_ON: '2020-01-01T00:00:00+00:00',
                            'title': 'Work 111', 'kudos': 1}],
    }

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops).values())[0]
    assert len(written[indexing.INDEXES]) == 2
    assert written[indexing.LAST_INDEXED] == ao3.indexed_on


def test_get_metadata_only_restamps_a_fic_that_has_not_changed() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'])

    # index once, then feed that exact result back as what is already on disk
    ao3.get_metadata(LISTING_URL, False)
    first = list(_saved(fileops).values())[0]
    fileops.load_json.return_value = first
    fileops.save_json.reset_mock()
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops).values())[0]
    assert len(written[indexing.INDEXES]) == 1
    # checked again, so the file says so even though nothing was added
    assert written[indexing.LAST_INDEXED] == ao3.indexed_on


def test_get_metadata_names_files_the_one_fixed_way() -> None:
    # the naming is not a setting any more: the work number has to lead so files can be
    # matched to their index entry, so an ini value must not be able to move it
    ao3, repo, fileops = make_ao3()
    fileops.get_ini_value.return_value = '{title}'
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    assert list(_saved(fileops)) == _indexed('111 Work 111 - A.json')


# region downloading from the index rather than crawling again

def _record(work: str, title: str = 'A Fic', updated: str = '14 Dec 2024') -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': title, 'authors': ['Cal'], 'date_updated': updated}


def test_downloading_from_the_index_never_reads_a_listing_or_a_work_page():
    # this is the whole point: the index already holds every work number, and the download
    # link is determined by that number, so neither page has to be fetched
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111'), _record('222')])

    repo.get_soup.assert_not_called()
    assert repo.download_file.call_count == 2


def test_downloading_from_the_index_goes_straight_to_the_download_host():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111')])

    url = repo.download_file.call_args.args[0]
    assert url == 'https://download.archiveofourown.org/downloads/111/fic.epub'


def test_downloading_from_the_index_names_files_the_usual_way():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111', title='No Paths Are Bound')])

    written = fileops.save_bytes.call_args.args[0]
    assert written == '111 No Paths Are Bound - Cal 2024-12-14.epub'


def test_downloading_from_the_index_skips_what_is_already_downloaded():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111'), _record('222')],
                         visited=['https://archiveofourown.org/works/111'])

    assert repo.download_file.call_count == 1
    assert repo.download_file.call_args.args[0].endswith('/222/fic.epub')


def test_downloading_from_the_index_fetches_each_format_once():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF'])
    repo.download_file.return_value = b'bytes'

    ao3.download_indexed([_record('111')])

    requested = sorted(call.args[0] for call in repo.download_file.call_args_list)
    assert requested == [
        'https://download.archiveofourown.org/downloads/111/fic.epub',
        'https://download.archiveofourown.org/downloads/111/fic.pdf',
    ]


def test_downloading_from_the_index_records_what_a_later_run_needs():
    # without the title and the updated date in the log, the next run cannot rebuild this
    # name and would fetch everything again
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111')])

    logged = fileops.write_log.call_args.args[0]
    assert logged['title'] == ['111 A Fic - Cal']
    assert logged['updated'] == '14 Dec 2024'
    assert logged['success'] is True


def test_downloading_from_the_index_replaces_the_copy_it_supersedes():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'
    fileops.save_bytes.return_value = r'C:\d\111 A Fic - Cal 2024-12-14.epub'
    fileops.saved_intact.return_value = True
    fileops.delete_file.return_value = True
    ao3.superseded = {'https://archiveofourown.org/works/111':
                      {'EPUB': r'C:\d\111 A Fic - Cal 2020-01-01.epub'}}

    ao3.download_indexed([_record('111')])

    fileops.delete_file.assert_called_once_with(r'C:\d\111 A Fic - Cal 2020-01-01.epub')


def test_one_work_that_will_not_download_does_not_end_the_run():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.side_effect = [
        exceptions.DownloadException('gone'), b'epub bytes']

    ao3.download_indexed([_record('111'), _record('222')])

    assert fileops.save_bytes.call_count == 1
    fileops.write_log.assert_called()


def test_downloading_from_the_index_stops_when_asked_to():
    stopped = {'value': False}
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    ao3.cancelled = lambda: stopped['value']

    def fetch(*args):
        stopped['value'] = True
        return b'epub bytes'

    repo.download_file.side_effect = fetch

    ao3.download_indexed([_record('111'), _record('222'), _record('333')])

    # the first work finishes, then the stop is noticed rather than working through the rest
    assert repo.download_file.call_count == 1


def test_a_record_with_no_work_number_is_skipped_rather_than_guessed_at():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])

    ao3.download_indexed([{'id': None, 'link': 'https://archiveofourown.org/works/1'}])

    repo.download_file.assert_not_called()

# endregion


# region re-reading one unfinished fic

def _unfinished(work: str = '111', published: int = 3) -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': 'A Fic', 'authors': ['Cal'], 'summary': 'unchanged',
            'chapters_published': published, 'chapters_total': None,
            'date_updated': '01 Jan 2020', 'kudos': 10}


def _work_page(chapters: str = '9/?', updated: str = '2024-12-14') -> BeautifulSoup:
    return BeautifulSoup(
        f'<dl class="stats"><dd class="chapters">{chapters}</dd>'
        f'<dd class="words">5,688</dd><dd class="kudos">671</dd>'
        f'<dd class="status">{updated}</dd></dl>', 'html.parser')


def test_a_fic_is_re_read_from_its_own_link():
    # the index is the list; no listing is walked to find it
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        ao3.refresh_one(_unfinished('111'))

    repo.get_soup.assert_called_once_with('https://archiveofourown.org/works/111')


def test_re_reading_brings_the_chapter_count_up_to_date():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page(chapters='9/?')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        fresh = ao3.refresh_one(_unfinished(published=3))

    assert fresh['chapters_published'] == 9
    assert fresh['chapters_total'] is None


def test_re_reading_writes_the_updated_date_the_way_a_listing_would():
    # otherwise a bookmarks pass and an update pass rewrite each other forever
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page(updated='2024-12-14')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        fresh = ao3.refresh_one(_unfinished())

    assert fresh['date_updated'] == '14 Dec 2024'


def test_re_reading_leaves_alone_the_fields_a_work_page_says_differently():
    # tags, summary and the bookmark's own fields come from the listing; half-overwriting
    # them from a work page would fill the history with schema noise
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        fresh = ao3.refresh_one(_unfinished())

    assert fresh['summary'] == 'unchanged'
    assert fresh['authors'] == ['Cal']


def test_re_reading_saves_the_entry_back_to_the_index():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        ao3.refresh_one(_unfinished())

    fileops.save_json.assert_called_once()
    written = fileops.save_json.call_args.args[1]
    assert written[indexing.INDEXES][-1]['chapters_published'] == 9


def test_a_page_that_cannot_be_read_raises_rather_than_writing_a_half_entry():
    # the caller turns this into a recorded failure; the entry it already had stays put
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = BeautifulSoup('<div></div>', 'html.parser')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_work_stats', return_value={'error': 'broken'}):
        with pytest.raises(exceptions.Ao3DownloaderException):
            ao3.refresh_one(_unfinished())

    fileops.save_json.assert_not_called()


def test_a_work_that_is_gone_raises_out_of_the_re_read():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = exceptions.DeletedException('deleted')

    with pytest.raises(exceptions.DeletedException):
        ao3.refresh_one(_unfinished())

# endregion


# region works that would not download

def test_a_work_that_fails_is_remembered_with_its_number():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.side_effect = exceptions.DownloadException('gone')

    ao3.download_indexed([_record('111')])

    assert ao3.failures == [{'id': '111',
                             'link': 'https://archiveofourown.org/works/111',
                             'error': 'gone'}]


def test_a_work_is_only_listed_once_however_many_formats_failed():
    # a work that fails usually fails for every format, and the same number five times
    # over is worse than useless for feeding back in
    ao3, repo, fileops = make_ao3(filetypes=['EPUB', 'PDF', 'HTML'])
    repo.download_file.side_effect = exceptions.DownloadException('gone')

    ao3.download_indexed([_record('111')])

    assert [x['id'] for x in ao3.failures] == ['111']


def test_the_works_that_succeeded_are_not_listed():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.side_effect = [
        exceptions.DownloadException('gone'), b'epub bytes']

    ao3.download_indexed([_record('111'), _record('222')])

    assert [x['id'] for x in ao3.failures] == ['111']


def test_a_run_with_nothing_wrong_reports_no_failures():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    repo.download_file.return_value = b'epub bytes'

    ao3.download_indexed([_record('111')])

    assert ao3.failures == []


def test_stopping_a_run_is_not_recorded_as_a_failed_work():
    # the work was never attempted; calling it failed would send you chasing nothing
    stopped = {'value': False}
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])
    ao3.cancelled = lambda: stopped['value']

    def fetch(*args):
        stopped['value'] = True
        return b'epub bytes'

    repo.download_file.side_effect = fetch

    ao3.download_indexed([_record('111'), _record('222')])

    assert ao3.failures == []


def test_the_long_way_round_records_failures_too():
    ao3, repo, fileops = make_ao3(filetypes=['EPUB'])

    with patch.object(Ao3, 'try_download', side_effect=exceptions.DeletedException('deleted')):
        ao3.download_work(WORK_URL, {}, None)

    assert [x['id'] for x in ao3.failures] == ['123']

# endregion


# region progress over a slice of a listing

def test_progress_counts_the_whole_listing_when_the_run_covers_it() -> None:
    ao3, _, _ = make_ao3()

    assert ao3.page_progress(1, 80) == (1, 80)
    assert ao3.page_progress(80, 80) == (80, 80)


def test_progress_counts_only_the_pages_a_later_start_will_fetch() -> None:
    # pages 42 to 80 is 39 pages, and the first of them is the first page of the run -
    # reporting 42 of 80 would start the bar half full
    ao3, _, _ = make_ao3(start=42)

    assert ao3.page_progress(42, 80) == (1, 39)
    assert ao3.page_progress(80, 80) == (39, 39)


def test_progress_counts_only_as_far_as_the_stop_page() -> None:
    # pages 42 to 60 is 19 pages, not 39
    ao3, _, _ = make_ao3(start=42, pages=60)

    assert ao3.page_progress(42, 80) == (1, 19)
    assert ao3.page_progress(60, 80) == (19, 19)


def test_progress_reaches_the_end_exactly_at_the_last_page() -> None:
    ao3, _, _ = make_ao3(start=5, pages=9)

    done, of = ao3.page_progress(9, 80)

    assert done == of  # 100%, not more and not less


def test_progress_says_how_far_along_even_with_no_total_to_go_on() -> None:
    ao3, _, _ = make_ao3(start=3)

    assert ao3.page_progress(4, None) == (2, None)


def test_get_metadata_reports_progress_within_the_slice_it_is_fetching() -> None:
    events: list[dict] = []
    ao3, repo, _ = make_ao3(start=3)
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=10)

    ao3.get_metadata(LISTING_URL, False)

    pages = [e for e in events if e['type'] == 'page']
    assert pages[0]['page'] == 1
    assert pages[0]['total'] == 8  # pages 3 to 10


def test_get_metadata_also_reports_the_real_page_number_for_the_wording() -> None:
    # the bar measures the slice, but 'page 3 of 10' is the page you would go and look at,
    # so both sets of numbers are sent
    events: list[dict] = []
    ao3, repo, _ = make_ao3(start=3)
    ao3.progress = events.append
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=10)

    ao3.get_metadata(LISTING_URL, False)

    page = [e for e in events if e['type'] == 'page'][0]
    assert (page['listingPage'], page['listingTotal']) == (3, 10)
    assert (page['page'], page['total']) == (1, 8)


# region indexing only what is new

def test_indexing_stops_at_the_first_fic_already_held() -> None:
    # ao3 lists bookmarks newest first, so everything before the first familiar one is new
    # and everything after it has been seen. that is what makes one stop enough
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222', '333'], total_pages=9)

    records = ao3.get_metadata(LISTING_URL, False, known={'222'})

    assert [x['id'] for x in records] == ['111']
    # and it did not walk on into the rest of the listing
    assert repo.get_soup.call_count == 1


def test_the_works_ahead_of_a_familiar_one_are_still_written() -> None:
    # only the walking stops there; the new fics found before it are the point of the run
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=9)

    with patch.object(Ao3, 'save_metadata') as save:
        ao3.get_metadata(LISTING_URL, False, known={'222'})

    assert [c.args[0]['id'] for c in save.call_args_list] == ['111']


def test_a_listing_with_nothing_new_indexes_nothing() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=9)

    assert ao3.get_metadata(LISTING_URL, False, known={'111'}) == []


def test_without_a_known_set_the_whole_listing_is_walked() -> None:
    # the full scan must not quietly become a stop-at-the-first-familiar-one walk
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=3)

    records = ao3.get_metadata(LISTING_URL, False)

    assert repo.get_soup.call_count == 3
    assert len(records) == 1  # the same stub page each time, deduped

# endregion


# region indexing one fic from its own page

def _work_page_soup() -> BeautifulSoup:
    return BeautifulSoup(
        '<div class="preface"><h2 class="title">A Fic</h2>'
        '<h3 class="byline">Cal</h3></div>'
        '<dl class="stats"><dd class="chapters">3/?</dd><dd class="words">500</dd>'
        '<dd class="status">2024-12-14</dd></dl>', 'html.parser')


def test_a_fic_never_indexed_gets_an_entry_from_its_own_page() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _work_page_soup()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111')

    assert record['id'] == '111'
    assert record['title'] == 'A Fic'
    assert record['authors'] == ['Cal']
    assert record['chapters_published'] == 3
    fileops.save_json.assert_called_once()


def test_a_fic_already_indexed_keeps_what_the_listing_gave_it() -> None:
    # a work page cannot speak to tags, the summary or your own bookmark notes, so an
    # entry that has them must not be overwritten with a work page's idea of the fic
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _work_page_soup()
    existing = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
                'title': 'A Fic', 'authors': ['Cal'], 'summary': 'from the listing',
                'bookmark_notes': 'mine', 'chapters_published': 1}

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup):
        record = ao3.index_one_work('https://archiveofourown.org/works/111', existing)

    assert record['summary'] == 'from the listing'
    assert record['bookmark_notes'] == 'mine'
    assert record['chapters_published'] == 3   # only the stats moved


def test_a_fic_whose_page_cannot_be_read_raises_rather_than_writing_a_stub() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = BeautifulSoup('<div></div>', 'html.parser')

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.parse_soup.get_work_stats', return_value={'error': 'broken'}):
        with pytest.raises(exceptions.Ao3DownloaderException):
            ao3.index_one_work('https://archiveofourown.org/works/111')

    fileops.save_json.assert_not_called()

# endregion


def test_a_page_is_written_only_once_all_of_it_has_been_read() -> None:
    # a page is one unit of work: fetched, parsed, then saved. saving as each blurb was
    # parsed made a page half-written by definition, so a page abandoned partway - by a
    # pause, or anything else - left entries behind for a page that was never finished
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222', '333'])
    order: list[str] = []

    real_metadata = parse_soup.get_blurb_metadata
    with patch('source_code.parse_soup.get_blurb_metadata',
               side_effect=lambda b: (order.append('parsed'), real_metadata(b))[1]), \
         patch.object(Ao3, 'save_metadata', side_effect=lambda d: order.append('saved')):
        ao3.get_metadata(LISTING_URL, False)

    assert order == ['parsed', 'parsed', 'parsed', 'saved', 'saved', 'saved']


def test_a_page_says_it_is_being_fetched_before_the_request_goes_out(capsys) -> None:
    # fetching a page is the slow part, and a rate-limit break can add minutes to it. a log
    # that only reports finished pages sits unchanged through all of that, which reads as a
    # hang rather than as work in progress
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=3)

    ao3.get_metadata(LISTING_URL, False)

    said = [x.strip() for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert said[0] == 'fetching page 1'
    assert said[1].startswith('finished page 1 of 3')
    assert said[2] == 'fetching page 2 of 3'


def test_the_first_page_counts_towards_no_total_because_there_is_not_one_yet(capsys) -> None:
    # how many pages the listing has is only known once the first has come back, so that
    # line says 'fetching page 1' rather than inventing a total to count towards
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=1)

    ao3.get_metadata(LISTING_URL, False)

    assert 'fetching page 1\n' in capsys.readouterr().out


def test_the_page_a_run_ends_on_still_says_it_finished(capsys) -> None:
    # this line used to sit after the checks that end the loop, so the last page of a
    # listing was fetched, parsed and saved without ever reporting that it was done
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'], total_pages=3)

    ao3.get_metadata(LISTING_URL, False)

    # the same stub page comes back each time and dedupes, so the count stays put; what
    # matters here is that page 3 - the one the run ends on - reports at all
    assert 'finished page 3 of 3. 2 works so far' in capsys.readouterr().out


def test_a_one_page_listing_is_not_said_to_be_one_of_none(capsys) -> None:
    # a single page carries no pagination, so there is no total to count towards. it used
    # not to matter because this line was never reached on a last page at all
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=1)

    ao3.get_metadata(LISTING_URL, False)

    said = capsys.readouterr().out
    assert 'finished page 1. 1 works so far' in said
    assert 'None' not in said


def test_the_page_a_stop_limit_ends_on_still_says_it_finished(capsys) -> None:
    ao3, repo, _ = make_ao3(pages=2)
    repo.get_soup.return_value = _listing_soup(['111'], total_pages=9)

    ao3.get_metadata(LISTING_URL, False)

    said = capsys.readouterr().out
    assert 'finished page 2 of 9' in said
    # and it stopped there rather than carrying on
    assert 'fetching page 3 of 9' not in said

# endregion


def test_get_metadata_begins_on_the_requested_page() -> None:
    ao3, repo, fileops = make_ao3(start=5)
    repo.get_soup.return_value = _listing_soup(['111'])

    ao3.get_metadata(LISTING_URL, False)

    assert repo.get_soup.call_args_list[0].args[0] == LISTING_URL + '?page=5'


def test_get_metadata_counts_positions_on_from_the_pages_it_skipped() -> None:
    # a run over the middle of a listing has to number its works where they actually sit,
    # or a later run over the first pages would collide with them
    ao3, repo, fileops = make_ao3(start=5)
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['position'] for r in records] == [81, 82]


def test_get_metadata_still_records_the_listing_itself_as_the_source() -> None:
    # the page it started on is not the provenance; the listing is
    ao3, repo, fileops = make_ao3(start=3)
    repo.get_soup.return_value = _listing_soup(['111'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert records[0]['source'] == LISTING_URL


def test_get_metadata_records_the_listing_and_its_order() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['position'] for r in records] == [1, 2]
    # the source is the link that was asked for, not the last page walked to
    assert all(r['source'] == LISTING_URL for r in records)
    # when it was read is recorded in the file rather than on the record
    written = list(_saved(fileops).values())
    assert all(w[indexing.LAST_INDEXED] for w in written)


def test_get_metadata_writes_each_page_as_it_is_read() -> None:
    # the point of writing incrementally: a long run leaves usable output behind
    ao3, repo, fileops = make_ao3()
    written_before_second_page = []

    def pages(_url):
        if repo.get_soup.call_count == 2:
            written_before_second_page.append(fileops.save_json.call_count)
        return _listing_soup(['111'] if repo.get_soup.call_count == 1 else ['222'], total_pages=2)

    repo.get_soup.side_effect = pages

    ao3.get_metadata(LISTING_URL, False)

    assert written_before_second_page == [1]
    assert fileops.save_json.call_count == 2


def test_get_metadata_keeps_the_files_written_before_a_page_failed() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [_listing_soup(['111'], total_pages=3), ValueError('connection reset')]

    ao3.get_metadata(LISTING_URL, False)

    assert list(_saved(fileops)) == _indexed('111 Work 111 - A.json')


def test_get_metadata_still_names_a_work_with_no_title_or_author() -> None:
    # whatever else is missing, the work number has to survive, or the file cannot be
    # matched back to anything
    ao3, repo, fileops = make_ao3()
    repo.get_soup.return_value = BeautifulSoup(
        '<ol class="bookmark index group">'
        '<li id="bookmark_1" class="bookmark blurb group work-111 user-1">'
        '<div class="header module"><h4 class="heading">'
        '<a href="/works/111"></a></h4></div></li></ol>', 'html.parser')

    ao3.get_metadata(LISTING_URL, False)

    written = list(_saved(fileops))[0]
    assert parse_text.get_work_number_from_filename(os.path.basename(written)) == '111'


def test_get_metadata_survives_an_unwritable_file() -> None:
    ao3, repo, fileops = make_ao3()
    fileops.save_json.side_effect = OSError('disk full')
    repo.get_soup.return_value = _listing_soup(['111', '222'])

    records = ao3.get_metadata(LISTING_URL, False)

    # both were still parsed, and the failures were logged rather than ending the run
    assert len(records) == 2
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert sum(1 for x in logged if x.get('message') == strings.ERROR_METADATA_SAVE) == 2


def test_get_metadata_rewrites_files_after_work_dates_are_filled() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [_listing_soup(['111']), _work_soup()]

    ao3.get_metadata(LISTING_URL, True)

    # once during the crawl, once with the dates in
    assert fileops.save_json.call_count == 2
    entries = fileops.save_json.call_args.args[1][indexing.INDEXES]
    # the second save replaces this run's reading rather than adding a second one
    assert len(entries) == 1
    assert entries[0]['date_created'] == '01 Jan 2019'


def test_get_metadata_stops_when_cancelled_and_keeps_what_it_saved() -> None:
    # stopping must not throw away pages already written
    ao3, repo, fileops = make_ao3()
    cancelled = {'value': False}
    ao3.cancelled = lambda: cancelled['value']

    def pages(_url):
        if repo.get_soup.call_count == 1:
            return _listing_soup(['111'], total_pages=5)
        cancelled['value'] = True
        return _listing_soup(['222'], total_pages=5)

    repo.get_soup.side_effect = pages

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert sorted(_saved(fileops)) == _indexed('111 Work 111 - A.json', '222 Work 222 - A.json')
    # a stop is not an error
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert not any(x.get('message') == strings.ERROR_LINKS_LIST for x in logged)


def test_get_metadata_stops_before_the_first_page_when_already_cancelled() -> None:
    ao3, repo, fileops = make_ao3()
    ao3.cancelled = lambda: True

    records = ao3.get_metadata(LISTING_URL, False)

    assert records == []
    repo.get_soup.assert_not_called()


def test_add_work_dates_stops_when_cancelled() -> None:
    ao3, repo, _ = make_ao3()
    ao3.cancelled = lambda: True
    records = [{'link': WORK_URL, 'date_created': None, 'date_updated': '01 Jan 2020'}]

    ao3.add_work_dates(records)

    repo.get_soup.assert_not_called()
    assert records[0]['date_created'] is None


def test_download_stops_when_cancelled_without_logging_a_failure() -> None:
    ao3, repo, fileops = make_ao3()
    ao3.cancelled = lambda: True

    ao3.download(LISTING_URL, [])

    repo.get_soup.assert_not_called()
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert not any(x.get('success') is False for x in logged)


def test_check_cancelled_does_nothing_without_a_callback() -> None:
    # the console app passes none, and must be unaffected
    ao3, _, _ = make_ao3()

    assert ao3.cancelled is None
    ao3.check_cancelled()


def test_get_metadata_does_not_load_work_pages_by_default() -> None:
    # the whole point of reading the listing is one request per page, not per work
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111', '222', '333'])

    records = ao3.get_metadata(LISTING_URL, False)

    assert len(records) == 3
    assert repo.get_soup.call_count == 1
    assert all(r['date_created'] is None for r in records)


def test_get_metadata_paginates() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = [
        _listing_soup(['111'], total_pages=2),
        _listing_soup(['222'], total_pages=2)]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert repo.get_soup.call_count == 2


def test_get_metadata_respects_page_limit() -> None:
    ao3, repo, _ = make_ao3(pages=2)
    repo.get_soup.side_effect = [
        _listing_soup(['111'], total_pages=5),
        _listing_soup(['222'], total_pages=5)]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222']
    assert repo.get_soup.call_count == 2


def test_get_metadata_skips_bookmarks_that_are_not_works(capsys) -> None:
    series = ('<li id="bookmark_9" class="bookmark blurb group series-5 user-1">'
              '<h4 class="heading"><a href="/series/5">A Series</a></h4></li>')
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _listing_soup(['111'], extra=series)

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111']
    assert '1' in capsys.readouterr().out


def test_get_metadata_dedupes_a_bookmark_seen_on_two_pages() -> None:
    # works shift between pages while a long list is being read
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = [
        _listing_soup(['111', '222'], total_pages=2),
        _listing_soup(['222', '333'], total_pages=2)]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '222', '333']


def test_get_metadata_keeps_the_same_work_bookmarked_twice() -> None:
    # two pseuds of the same user can each bookmark one work; both are real bookmarks
    ao3, repo, _ = make_ao3()
    both = _blurb_html('111', bookmark_id='1') + _blurb_html('111', bookmark_id='2')
    repo.get_soup.return_value = BeautifulSoup(
        f'<ol class="bookmark index group">{both}</ol>', 'html.parser')

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111', '111']


def test_get_metadata_returns_partial_results_when_a_page_fails() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [
        _listing_soup(['111'], total_pages=3),
        ValueError('connection reset')]

    records = ao3.get_metadata(LISTING_URL, False)

    assert [r['id'] for r in records] == ['111']
    assert fileops.write_log.called


def test_get_metadata_looks_up_work_dates_when_asked() -> None:
    ao3, repo, _ = make_ao3()
    repo.get_soup.side_effect = [_listing_soup(['111']), _work_soup()]

    records = ao3.get_metadata(LISTING_URL, True)

    assert records[0]['date_created'] == '01 Jan 2019'
    assert records[0]['date_updated'] == '05 May 2021'
    assert repo.get_soup.call_count == 2


def test_add_work_dates_keeps_listing_date_when_work_has_no_status() -> None:
    # single chapter works have no 'Updated' line, so the listing date is all there is
    ao3, repo, _ = make_ao3()
    repo.get_soup.return_value = _work_soup(status='')
    records = [{'link': WORK_URL, 'date_created': None, 'date_updated': '01 Jan 2020'}]

    ao3.add_work_dates(records)

    assert records[0]['date_created'] == '01 Jan 2019'
    assert records[0]['date_updated'] == '01 Jan 2020'


def test_add_work_dates_logs_and_continues_past_a_failed_work() -> None:
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = [ValueError('boom'), _work_soup()]
    records = [
        {'link': WORK_URL, 'date_created': None, 'date_updated': '01 Jan 2020'},
        {'link': 'https://archiveofourown.org/works/222', 'date_created': None, 'date_updated': ''}]

    ao3.add_work_dates(records)

    assert records[0]['date_created'] is None
    assert records[1]['date_created'] == '01 Jan 2019'
    logged = [c.args[0] for c in fileops.write_log.call_args_list]
    assert any(x.get('message') == strings.ERROR_METADATA_WORK_DATES for x in logged)

# endregion

# region Constructor

def test_init_reads_debug_from_ini() -> None:
    ao3, _, fileops = make_ao3(debug=True)
    assert ao3.debug is True
    fileops.get_ini_value_boolean.assert_called_once_with(strings.INI_DEBUG_LOGGING, False)

# endregion


# region replacing the copy a download supersedes
#
# The risk here is losing a file the user has and we do not. Every one of these is about
# refusing to delete, so they matter more than the one case that does.

WORK = 'https://archiveofourown.org/works/123'


def superseding(old: str = r'C:\downloads\123 A 2024-01-01.html'):
    ao3, repo, fileops = make_ao3()
    ao3.superseded = {WORK: {'HTML': old}}
    fileops.saved_intact.return_value = True
    fileops.delete_file.return_value = True
    return ao3, fileops


def test_the_old_copy_goes_once_the_new_one_is_confirmed():
    ao3, fileops = superseding()

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 2048)

    fileops.saved_intact.assert_called_once_with(r'C:\downloads\123 A 2024-12-14.html', 2048)
    fileops.delete_file.assert_called_once_with(r'C:\downloads\123 A 2024-01-01.html')


def test_nothing_is_deleted_when_the_new_file_cannot_be_confirmed():
    # a download that failed, was cut short, or landed elsewhere must not take the old one
    ao3, fileops = superseding()
    fileops.saved_intact.return_value = False

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 2048)

    fileops.delete_file.assert_not_called()


def test_nothing_is_deleted_when_there_was_no_older_copy():
    ao3, repo, fileops = make_ao3()

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.delete_file.assert_not_called()


def test_a_different_file_type_is_never_the_one_removed():
    # the epub is out of date too, but this download was the html
    ao3, repo, fileops = make_ao3()
    ao3.superseded = {WORK: {'EPUB': r'C:\downloads\123 A 2024-01-01.epub'}}
    fileops.saved_intact.return_value = True

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.delete_file.assert_not_called()


def test_a_download_that_kept_its_name_deletes_nothing():
    # the write already replaced it in place; deleting would remove what was just saved
    same = r'C:\downloads\123 A 2024-01-01.html'
    ao3, fileops = superseding(same)

    ao3.replace_superseded(WORK, 'HTML', same, 10)

    fileops.delete_file.assert_not_called()


def test_the_same_file_reached_by_a_different_path_is_still_not_deleted():
    ao3, fileops = superseding(r'C:\downloads\sub\..\123 A 2024-01-01.html')

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-01-01.html', 10)

    fileops.delete_file.assert_not_called()


def test_another_works_copy_is_never_touched():
    ao3, repo, fileops = make_ao3()
    ao3.superseded = {'https://archiveofourown.org/works/999':
                      {'HTML': r'C:\downloads\999 B 2024-01-01.html'}}
    fileops.saved_intact.return_value = True

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.delete_file.assert_not_called()


def test_a_download_still_counts_as_done_when_the_old_file_will_not_go():
    ao3, fileops = superseding()
    fileops.delete_file.return_value = False

    # the point is that this does not raise: the new file is saved either way
    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)


def test_a_failure_while_tidying_up_never_breaks_the_download():
    ao3, fileops = superseding()
    fileops.saved_intact.side_effect = OSError('disk went away')

    ao3.replace_superseded(WORK, 'HTML', r'C:\downloads\123 A 2024-12-14.html', 10)

    fileops.write_log.assert_called()


def test_the_replacement_really_removes_the_file_on_disk(tmp_path):
    # the checks above are about refusing; this one proves the real thing works end to end
    ao3, repo, fileops = make_ao3()
    # the real disk checks, with logging still mocked
    fileops.saved_intact.side_effect = lambda p, n: FileOps.saved_intact(fileops, p, n)
    fileops.delete_file.side_effect = lambda p: FileOps.delete_file(fileops, p)

    old = tmp_path / '123 A 2024-01-01.html'
    new = tmp_path / '123 A 2024-12-14.html'
    old.write_bytes(b'old copy')
    new.write_bytes(b'the new copy')
    ao3.superseded = {WORK: {'HTML': str(old)}}

    ao3.replace_superseded(WORK, 'HTML', str(new), len(b'the new copy'))

    assert not old.exists()
    assert new.exists()


def test_a_truncated_new_file_leaves_the_old_one_where_it_is(tmp_path):
    ao3, repo, fileops = make_ao3()
    # the real disk checks, with logging still mocked
    fileops.saved_intact.side_effect = lambda p, n: FileOps.saved_intact(fileops, p, n)
    fileops.delete_file.side_effect = lambda p: FileOps.delete_file(fileops, p)

    old = tmp_path / '123 A 2024-01-01.html'
    new = tmp_path / '123 A 2024-12-14.html'
    old.write_bytes(b'old copy')
    new.write_bytes(b'half')
    ao3.superseded = {WORK: {'HTML': str(old)}}

    # says it should be 2048 bytes, but only 4 arrived
    ao3.replace_superseded(WORK, 'HTML', str(new), 2048)

    assert old.exists()

# endregion
