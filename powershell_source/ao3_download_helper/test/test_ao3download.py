"""Tests for ao3downloader.actions.ao3download — json metadata export wiring."""

from unittest.mock import MagicMock, patch

import pytest

from source_code import strings
from source_code.actions import ao3download


LISTING_URL = 'https://archiveofourown.org/users/someone/bookmarks'


@pytest.fixture
def patched_action():
    """Patch out everything action() touches, and hand back the mocks worth asserting on."""
    fileops = MagicMock()
    fileops.downloadfolder = 'downloads'
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)
    ao3 = MagicMock()
    ao3.get_metadata.return_value = [{'id': '111'}]

    with patch('source_code.actions.ao3download.FileOps', return_value=fileops), \
         patch('source_code.actions.ao3download.Repository', return_value=repo), \
         patch('source_code.actions.ao3download.Ao3', return_value=ao3) as ao3_class, \
         patch.object(ao3download.shared, 'link', return_value=LISTING_URL), \
         patch.object(ao3download.shared, 'pages', return_value=None), \
         patch.object(ao3download.shared, 'ao3_login'), \
         patch.object(ao3download.shared, 'visited', return_value=[]), \
         patch.object(ao3download.shared, 'series', return_value=False) as series, \
         patch.object(ao3download.shared, 'images', return_value=False) as images, \
         patch.object(ao3download.shared, 'metadata_work_dates', return_value=False) as workdates:
        yield {'fileops': fileops, 'ao3': ao3, 'ao3_class': ao3_class,
               'series': series, 'images': images, 'workdates': workdates}


def test_action_exports_metadata_and_skips_downloading(patched_action, capsys):
    with patch.object(ao3download.shared, 'download_types',
                      return_value=[strings.AO3_DOWNLOAD_TYPE_METADATA]):
        ao3download.action()

    ao3 = patched_action['ao3']
    ao3.get_metadata.assert_called_once_with(LISTING_URL, False)
    ao3.download.assert_not_called()
    # the files are written per work during the crawl, not in one go afterwards
    patched_action['fileops'].save_json.assert_not_called()
    # JSON never produces work files, so the ebook-only prompts are not worth asking
    patched_action['series'].assert_not_called()
    patched_action['images'].assert_not_called()
    patched_action['workdates'].assert_called_once()


def test_action_says_where_the_files_went(patched_action, capsys):
    with patch.object(ao3download.shared, 'download_types',
                      return_value=[strings.AO3_DOWNLOAD_TYPE_METADATA]):
        ao3download.action()

    out = capsys.readouterr().out
    assert 'downloads' in out
    # and tells the user how to stop early without losing the run
    assert 'ctrl+c' in out


def test_action_passes_only_real_filetypes_to_the_downloader(patched_action):
    with patch.object(ao3download.shared, 'download_types',
                      return_value=['EPUB', strings.AO3_DOWNLOAD_TYPE_METADATA]):
        ao3download.action()

    # JSON must not reach Ao3, which would look for a JSON download link on every work
    assert patched_action['ao3_class'].call_args.args[2] == ['EPUB']
    patched_action['ao3'].get_metadata.assert_called_once()
    patched_action['ao3'].download.assert_called_once()


def test_action_without_metadata_type_downloads_as_before(patched_action):
    with patch.object(ao3download.shared, 'download_types', return_value=['EPUB']):
        ao3download.action()

    patched_action['ao3'].get_metadata.assert_not_called()
    patched_action['ao3'].download.assert_called_once_with(LISTING_URL, [])
    patched_action['series'].assert_called_once()
    patched_action['images'].assert_called_once()


def test_action_reports_when_no_works_were_found(patched_action, capsys):
    patched_action['ao3'].get_metadata.return_value = []

    with patch.object(ao3download.shared, 'download_types',
                      return_value=[strings.AO3_DOWNLOAD_TYPE_METADATA]):
        ao3download.action()

    assert strings.AO3_INFO_METADATA_NONE in capsys.readouterr().out


def test_action_asks_for_work_dates_and_passes_the_answer(patched_action):
    patched_action['workdates'].return_value = True

    with patch.object(ao3download.shared, 'download_types',
                      return_value=[strings.AO3_DOWNLOAD_TYPE_METADATA]):
        ao3download.action()

    patched_action['ao3'].get_metadata.assert_called_once_with(LISTING_URL, True)
