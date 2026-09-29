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


# region noting which collections hold an indexed work, in the cleanup step

from test.test_collection_works import external_listing  # noqa: E402
from test.test_collections_crawl import collection_profile  # noqa: E402

WORK_BLURB = """<li class="work blurb group work-{id}" id="work_{id}">
  <div class="header module"><h4 class="heading"><a href="/works/{id}">Work {id}</a>
    by <a rel="author" href="/users/writer">writer</a></h4>
  <p class="datetime">14 Dec 2024</p></div></li>"""


def collection_pages(url: str) -> BeautifulSoup:
    """Collection 'alpha': the newest bookmark among its works, and an external work among
    its bookmarked items."""

    if url.endswith('/profile'): return collection_profile('alpha')
    if '/alpha/works' in url:
        return BeautifulSoup(f'<ol class="index group">{WORK_BLURB.format(id=NEWEST)}</ol>',
                             'html.parser')
    if '/alpha/bookmarks' in url: return external_listing()
    raise AssertionError(url)


def run_collection(root: str, works: bool = False) -> None:
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)
    repo.get_soup.side_effect = collection_pages
    repo.download_file.side_effect = lambda url, filetype: b'<html>work</html>'
    job = server.Job(server.ACTION_COLLECTION, ['JSON', 'HTML'] if works else ['JSON'],
                     'Someone', server.resolve_options({'collectionWorks': works}),
                     url='https://archiveofourown.org/collections/alpha')
    job.emit = lambda event: None
    job.ask = MagicMock(side_effect=AssertionError('no question expected'))
    with patch.object(server, 'FileOps', side_effect=lambda *a, **k: FileOps(LocalStorage(root))), \
         patch.object(server, 'Repository', return_value=repo):
        server.run_job(job, 'a-password')


def readings(root: str, work: str) -> int:
    with open(entry_path(root, work), encoding='utf-8') as f:
        return len(json.load(f)['indexes'])


def saved_collection(root: str, works: list[str]) -> None:
    os.makedirs(os.path.join(root, strings.COLLECTIONS_FOLDER_NAME), exist_ok=True)
    with open(os.path.join(root, strings.COLLECTIONS_FOLDER_NAME, 'alpha.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'name': 'alpha', 'indexes': [{'indexed_on': 'x', 'work_ids': works,
                                                 'bookmark_ids': []}]}, f)


@pytest.fixture
def bookmarked(tmp_path):
    """Every bookmark on the page indexed as yours, and no collection yet."""

    root = str(tmp_path / 'library')
    run(root, server.ACTION_BOOKMARKS)
    return root


def test_a_collection_run_without_the_works_notes_itself_on_a_work_you_already_indexed(bookmarked):
    before = readings(bookmarked, NEWEST)

    run_collection(bookmarked, works=False)

    found = entry(bookmarked, NEWEST)
    assert found[indexing.FROM_COLLECTIONS] == ['alpha']
    # it is still yours, and nothing about the work itself was re-read or re-recorded
    assert found[strings.BOOKMARKED_FIELD] is True
    assert readings(bookmarked, NEWEST) == before
    # a work the collection does not hold is left alone
    assert indexing.FROM_COLLECTIONS not in entry(bookmarked, NEXT)


def test_a_collection_run_notes_itself_on_an_external_work_already_indexed(bookmarked):
    folder = os.path.join(bookmarked, strings.INDEXING_FOLDER_NAME, strings.EXTERNAL_INDEX_FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, '1 Elsewhere - someone.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '1', 'indexes': [{'indexed_on': 'x', 'title': 'Elsewhere',
                                           strings.BOOKMARKED_FIELD: True}]}, f)

    run_collection(bookmarked, works=False)

    with open(os.path.join(folder, '1 Elsewhere - someone.json'), encoding='utf-8') as f:
        assert json.load(f)[indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_collection_run_never_creates_an_entry_for_a_work_it_does_not_index(tmp_path):
    root = str(tmp_path / 'library')
    run_collection(root, works=False)

    folder = os.path.join(root, strings.INDEXING_FOLDER_NAME)
    written = [n for n in os.listdir(folder) if n.endswith('.json')] if os.path.isdir(folder) else []
    assert written == []


@pytest.mark.parametrize('action', [server.ACTION_BOOKMARKS, server.ACTION_QUICK, server.ACTION_CUSTOM])
def test_a_scan_notes_the_saved_collections_that_hold_what_it_indexed(tmp_path, action):
    # the collection was indexed first, with its works left off - then the scan finds the work
    root = str(tmp_path / 'library')
    saved_collection(root, [NEWEST])

    run(root, action)

    assert entry(root, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']
    assert indexing.FROM_COLLECTIONS not in entry(root, NEXT)


def test_noting_it_again_changes_nothing(bookmarked):
    run_collection(bookmarked, works=False)
    with open(entry_path(bookmarked, NEWEST), encoding='utf-8') as f:
        first = f.read()

    run_collection(bookmarked, works=False)

    with open(entry_path(bookmarked, NEWEST), encoding='utf-8') as f:
        assert f.read() == first


def test_a_run_with_nothing_to_note_or_remove_skips_its_cleanup():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')
    job.steps = MagicMock()
    fileops = MagicMock()
    fileops.list_files.return_value = []

    server.cleanup(job, fileops, MagicMock())

    job.steps.skip.assert_called_once_with('cleanup')


def test_a_stopped_run_notes_nothing():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')
    job.steps = MagicMock()
    job.cancel.set()
    fileops = MagicMock()

    server.cleanup(job, fileops, MagicMock())

    fileops.save_json.assert_not_called()
    job.steps.skip.assert_called_once_with('cleanup')

# endregion


def forget_collections(root: str, work: str) -> None:
    path = entry_path(root, work)
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    data.pop(indexing.FROM_COLLECTIONS, None)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)


def test_with_the_works_on_an_unchanged_work_still_learns_its_collection(bookmarked):
    # the second run reads exactly what the first did, so the work itself has not changed
    # and gets no new reading - but it still has to be told the collection holds it
    run_collection(bookmarked, works=True)
    forget_collections(bookmarked, NEWEST)
    before = readings(bookmarked, NEWEST)

    run_collection(bookmarked, works=True)

    assert entry(bookmarked, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']
    assert readings(bookmarked, NEWEST) == before
    assert entry(bookmarked, NEWEST)[strings.BOOKMARKED_FIELD] is True


def test_with_the_works_on_the_crawl_alone_would_note_it(bookmarked):
    # two ways write it on a run with the works on - the crawl's own save, and the cleanup.
    # each is enough on its own: here the cleanup is kept out of it
    run_collection(bookmarked, works=True)
    forget_collections(bookmarked, NEWEST)

    with patch.object(server, 'collection_links', return_value=[]):
        run_collection(bookmarked, works=True)

    assert entry(bookmarked, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']


def test_with_the_works_on_the_cleanup_alone_would_note_it(bookmarked):
    run_collection(bookmarked, works=True)
    forget_collections(bookmarked, NEWEST)
    real_save = server.Ao3.save_collection_work

    def save_without_the_collection(self, document, collection, listing):
        return real_save(self, document, '', listing)

    with patch.object(server.Ao3, 'save_collection_work', save_without_the_collection):
        run_collection(bookmarked, works=True)

    assert entry(bookmarked, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']


def entry_files(root: str, work: str) -> list[str]:
    folder = os.path.join(root, strings.INDEXING_FOLDER_NAME)
    return [n for n in os.listdir(folder) if n.startswith(work + ' ') and n.endswith('.json')]


def test_a_work_retitled_since_it_was_indexed_keeps_its_one_entry_and_your_bookmark(bookmarked):
    # the collection lists it as 'Work 66326125' by 'writer' - not the title and author it
    # was indexed under - so the name its entry would be given now is not the one it has
    assert len(entry_files(bookmarked, NEWEST)) == 1

    run_collection(bookmarked, works=True)

    assert len(entry_files(bookmarked, NEWEST)) == 1
    found = entry(bookmarked, NEWEST)
    assert found[strings.BOOKMARKED_FIELD] is True
    assert found[indexing.FROM_COLLECTIONS] == ['alpha']
    assert found['title'] == f'Work {NEWEST}'
