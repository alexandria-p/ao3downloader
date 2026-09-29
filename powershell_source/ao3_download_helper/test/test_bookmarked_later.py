"""A work first indexed because a collection holds it, then bookmarked by you.

A collection run indexes the works it meets as `bookmarked: false` - they are there because
of the collection. The day you bookmark one yourself, the next walk down your bookmarks has
to mark it `true`, and keep what the collection run recorded about where it was found.

These run the real helper code over a real library folder, with only ao3 faked by a live
bookmarks page from the fixtures.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import indexing, server, strings
from source_code.actions import shared
from source_code.fileio import FileOps
from source_code.storage import LocalStorage

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
with open(os.path.join(FIXTURES, 'bookmarks.html'), encoding='utf-8') as f:
    BOOKMARKS = f.read()
with open(os.path.join(FIXTURES, 'seriesPage.html'), encoding='utf-8') as f:
    SERIES = f.read()

# the newest bookmark on the page - where a new-bookmarks walk starts
NEWEST = '66326125'
# the one after it, which is an ordinary bookmark the index already holds
NEXT = '18623245'


def run(root: str, action: str, options: dict | None = None) -> list[str]:
    asked = []
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)

    def soup(url):
        asked.append(url)
        return BeautifulSoup(SERIES if '/series/' in url else BOOKMARKS, 'html.parser')
    repo.get_soup.side_effect = soup
    repo.download_file.side_effect = lambda url, filetype: b'<html>work</html>'
    job = server.Job(action, ['JSON'], 'Someone', server.resolve_options(options or {}))
    job.emit = lambda event: None
    job.ask = MagicMock(side_effect=AssertionError('no question expected'))
    with patch.object(server, 'FileOps', side_effect=lambda *a, **k: FileOps(LocalStorage(root))), \
         patch.object(server, 'Repository', return_value=repo):
        server.run_job(job, 'a-password')
    return asked


def entry_path(root: str, work: str) -> str:
    folder = os.path.join(root, strings.INDEXING_FOLDER_NAME)
    return os.path.join(folder, next(n for n in os.listdir(folder) if n.startswith(work + ' ')))


def entry(root: str, work: str) -> dict:
    with open(entry_path(root, work), encoding='utf-8') as f:
        return indexing.flatten(json.load(f))


@pytest.fixture
def library(tmp_path):
    """Every bookmark on the page indexed, then the newest turned into a work only a
    collection led the index to: not bookmarked, found through collection 'alpha'."""

    root = str(tmp_path / 'library')
    run(root, server.ACTION_BOOKMARKS)
    path = entry_path(root, NEWEST)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data['indexes'][-1][strings.BOOKMARKED_FIELD] = False
    data['indexes'][-1]['bookmark_notes'] = ''
    data[indexing.FROM_COLLECTIONS] = ['alpha']
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.makedirs(os.path.join(root, strings.COLLECTIONS_FOLDER_NAME), exist_ok=True)
    with open(os.path.join(root, strings.COLLECTIONS_FOLDER_NAME, 'alpha.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'name': 'alpha', 'indexes': [{'indexed_on': 'x', 'work_ids': [NEWEST],
                                                 'bookmark_ids': []}]}, f)
    assert entry(root, NEWEST)[strings.BOOKMARKED_FIELD] is False
    return root


def test_a_full_scan_marks_a_collection_found_work_you_have_since_bookmarked(library):
    run(library, server.ACTION_BOOKMARKS)

    found = entry(library, NEWEST)
    assert found[strings.BOOKMARKED_FIELD] is True
    # where it was found is kept, and your own bookmark's fields are read off the listing
    assert found[indexing.FROM_COLLECTIONS] == ['alpha']
    assert found['date_bookmarked']


@pytest.mark.parametrize('action', [server.ACTION_SYNC, server.ACTION_NEW])
def test_a_new_bookmarks_walk_does_not_stop_at_a_collection_found_work(library, action):
    # the walk stops at the first work already indexed - but a work only a collection led
    # the index to is not one you had bookmarked, so reaching it is not reaching the known
    run(library, action)

    assert entry(library, NEWEST)[strings.BOOKMARKED_FIELD] is True
    assert entry(library, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']


def test_the_walk_still_stops_at_the_first_work_you_had_already_bookmarked(library):
    known = shared.indexed_work_ids(FileOps(LocalStorage(library)))

    assert NEWEST in known.doubtful
    assert known.confirmed(NEWEST) is False
    assert known.confirmed(NEXT) is True


def test_a_collection_found_work_you_had_bookmarked_is_known(library):
    # once a walk has marked it, it is an ordinary known work again
    run(library, server.ACTION_BOOKMARKS)

    known = shared.indexed_work_ids(FileOps(LocalStorage(library)))
    assert known.confirmed(NEWEST) is True


def test_a_quick_scan_marks_it_too_when_the_bookmark_is_newer_than_its_floor(library):
    # a quick scan reads bookmarks made since its floor - which a work you bookmarked today is.
    # here the floor is set before the page's bookmark dates, standing in for that
    ao3 = server.Ao3(MagicMock(), FileOps(LocalStorage(library)), [], None, False, False)
    ao3.repo.get_soup.side_effect = lambda url: BeautifulSoup(BOOKMARKS, 'html.parser')

    ao3.get_metadata(server.sorted_bookmarks_link(
        server.Job(server.ACTION_QUICK, ['JSON'], 'Someone')), False,
        stop_before='2000-01-01', stop_on='bookmarked', own_bookmarks=True)

    assert entry(library, NEWEST)[strings.BOOKMARKED_FIELD] is True


def test_a_later_collection_run_does_not_unmark_it(library):
    run(library, server.ACTION_BOOKMARKS)
    ao3 = server.Ao3(MagicMock(), FileOps(LocalStorage(library)), [], None, False, False)
    document = {'id': NEWEST, 'title': entry(library, NEWEST)['title'],
                'authors': entry(library, NEWEST)['authors'], 'bookmark_notes': 'a stranger'}

    ao3.save_collection_work(document, 'alpha', 'https://archiveofourown.org/collections/alpha/works')

    assert entry(library, NEWEST)[strings.BOOKMARKED_FIELD] is True
