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


def run(root: str, action: str, options: dict | None = None,
        listing: str | None = None) -> list[str]:
    asked = []
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)

    def soup(url):
        asked.append(url)
        return BeautifulSoup(SERIES if '/series/' in url else listing or BOOKMARKS, 'html.parser')
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


def entry_files(root: str, work: str) -> list[str]:
    folder = os.path.join(root, strings.INDEXING_FOLDER_NAME)
    return [n for n in os.listdir(folder) if n.startswith(work + ' ') and n.endswith('.json')]


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


def records(root: str) -> dict[str, dict]:
    folder = os.path.join(root, 'runs')
    found = {}
    for name in os.listdir(folder):
        with open(os.path.join(folder, name), encoding='utf-8') as f:
            record = json.load(f)
        found[record['id']] = record
    return found


def log_of_a_new_run(root: str, action: str) -> list[str]:
    """The lines a run printed - read back from its history file, found as the one record
    that was not there before it (two runs can start within the same second)."""

    before = set(records(root))
    run(root, action)
    [record] = [r for i, r in records(root).items() if i not in before]
    return record['log']


def test_the_cleanup_says_it_is_linking_and_how_many_works_it_linked(bookmarked):
    saved_collection(bookmarked, [NEWEST, NEXT])
    log = log_of_a_new_run(bookmarked, server.ACTION_BOOKMARKS)

    assert strings.AO3_INFO_COLLECTIONS_LINKING in log
    assert '2 works have been linked to your collections' in log


def test_one_linked_work_is_said_in_the_singular(bookmarked):
    saved_collection(bookmarked, [NEWEST])
    log = log_of_a_new_run(bookmarked, server.ACTION_BOOKMARKS)

    assert '1 work has been linked to your collections' in log


def test_nothing_to_link_says_nothing_about_linking(bookmarked):
    saved_collection(bookmarked, [NEWEST])
    run(bookmarked, server.ACTION_BOOKMARKS)
    log = log_of_a_new_run(bookmarked, server.ACTION_BOOKMARKS)

    assert not any('linked to your collections' in x or x == strings.AO3_INFO_COLLECTIONS_LINKING
                   for x in log)


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


def test_with_the_works_on_only_the_cleanup_notes_it(bookmarked):
    # one place sets from_collections, for every run - the cleanup step. with it kept out,
    # the crawl indexes the work and leaves the field alone
    run_collection(bookmarked, works=True)
    forget_collections(bookmarked, NEWEST)

    with patch.object(server, 'collection_links', return_value=[]):
        run_collection(bookmarked, works=True)

    assert indexing.FROM_COLLECTIONS not in entry(bookmarked, NEWEST)


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


# region every workflow notes collections in its cleanup, resumed or not

def earlier_attempt(root: str, action: str, listing: str | None = None) -> str:
    """Run `action`, then make its history file read as an attempt that was interrupted
    after its listing walk finished - so a resume takes that walk's works from the index
    rather than reading them again. Returns the run's id."""

    run(root, action, listing=listing)
    folder = os.path.join(root, 'runs')
    name = sorted(os.listdir(folder))[-1]
    with open(os.path.join(folder, name), encoding='utf-8') as f:
        data = json.load(f)
    data['status'] = 'interrupted'
    data['finished'] = None
    with open(os.path.join(folder, name), 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data['id']


def test_a_resumed_scan_notes_collections_on_what_the_earlier_attempt_indexed(tmp_path):
    # the resumed attempt does not read the listing again - its walk was done - so nothing is
    # indexed this attempt; the works are still covered, through the progress it carries
    root = str(tmp_path / 'library')
    earlier = earlier_attempt(root, server.ACTION_BOOKMARKS)
    saved_collection(root, [NEWEST])
    asked = run(root, server.ACTION_CUSTOM, {'resume': earlier})

    assert not any('/bookmarks' in url for url in asked)
    assert entry(root, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_resumed_scan_notes_collections_on_external_works_the_earlier_attempt_saved(tmp_path):
    # external work 1 is among your bookmarks; the earlier attempt saved its entry, and the
    # resume reads nothing - so only the earlier attempt's progress can say it was covered
    with open(os.path.join(FIXTURES, 'externalWork.html'), encoding='utf-8') as f:
        listing = f.read()
    root = str(tmp_path / 'library')
    earlier = earlier_attempt(root, server.ACTION_BOOKMARKS, listing)
    os.makedirs(os.path.join(root, strings.COLLECTIONS_FOLDER_NAME), exist_ok=True)
    with open(os.path.join(root, strings.COLLECTIONS_FOLDER_NAME, 'alpha.json'), 'w',
              encoding='utf-8') as f:
        json.dump({'name': 'alpha', 'indexes': [{'indexed_on': 'x', 'work_ids': [],
                                                 'bookmark_ids': [], 'external_ids': ['1']}]}, f)

    asked = run(root, server.ACTION_CUSTOM, {'resume': earlier}, listing)

    assert not any('/bookmarks' in url for url in asked)
    folder = os.path.join(root, strings.INDEXING_FOLDER_NAME, strings.EXTERNAL_INDEX_FOLDER_NAME)
    [name] = [n for n in os.listdir(folder) if n.startswith('1 ')]
    with open(os.path.join(folder, name), encoding='utf-8') as f:
        assert indexing.flatten(json.load(f))[indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_resume_of_a_resume_still_carries_the_first_attempts_external_works(tmp_path):
    with open(os.path.join(FIXTURES, 'externalWork.html'), encoding='utf-8') as f:
        listing = f.read()
    root = str(tmp_path / 'library')
    first = earlier_attempt(root, server.ACTION_BOOKMARKS, listing)
    run(root, server.ACTION_CUSTOM, {'resume': first}, listing)

    folder = os.path.join(root, 'runs')
    records = []
    for name in os.listdir(folder):
        with open(os.path.join(folder, name), encoding='utf-8') as f:
            records.append(json.load(f))
    second = next(r for r in records if r['id'] != first)
    assert second['progress']['externalsSaved'] == ['1']


def test_the_single_fic_run_notes_the_collections_holding_its_fic(bookmarked):
    saved_collection(bookmarked, [NEXT])
    work_page = os.path.join(FIXTURES, 'unlockedWork.html')
    with open(work_page, encoding='utf-8') as f:
        page = f.read()
    number = __import__('re').search(r'/works/(\d+)', page).group(1)
    saved_collection(bookmarked, [number])

    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)
    repo.get_soup.side_effect = lambda url: BeautifulSoup(page, 'html.parser')
    job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', server.resolve_options({}),
                     url=f'https://archiveofourown.org/works/{number}')
    job.emit = lambda event: None
    with patch.object(server, 'FileOps', side_effect=lambda *a, **k: FileOps(LocalStorage(bookmarked))), \
         patch.object(server, 'Repository', return_value=repo):
        server.run_job(job, 'a-password')

    assert entry(bookmarked, number)[indexing.FROM_COLLECTIONS] == ['alpha']


@pytest.mark.parametrize('action', [server.ACTION_SYNC, server.ACTION_NEW])
def test_the_debug_runs_do_not_note_collections(tmp_path, action):
    root = str(tmp_path / 'library')
    saved_collection(root, [NEWEST])

    run(root, action)

    assert indexing.FROM_COLLECTIONS not in entry(root, NEWEST)

# endregion


# region every index write finds its entry by the number its name starts with

def retitle(root: str, work: str, title: str) -> str:
    """Give an entry's file the name it would have had under an older title."""

    old = entry_path(root, work)
    new = os.path.join(os.path.dirname(old), f'{work} {title} - someone.json')
    os.rename(old, new)
    return new


def test_a_scan_writes_to_a_retitled_works_existing_file(bookmarked):
    kept = retitle(bookmarked, NEWEST, 'An Older Title')

    run(bookmarked, server.ACTION_BOOKMARKS)

    assert len(entry_files(bookmarked, NEWEST)) == 1
    with open(kept, encoding='utf-8') as f:
        data = json.load(f)
    assert indexing.flatten(data)[strings.BOOKMARKED_FIELD] is True
    # the reading this scan took is in that file
    assert len(data['indexes']) >= 1 and data['last_indexed'] != ''


def test_a_series_walk_writes_to_a_retitled_works_existing_file(bookmarked):
    # the series on the fixture page lists works the scan indexed through it
    series_works = [n.split(' ')[0] for n in os.listdir(os.path.join(
        bookmarked, strings.INDEXING_FOLDER_NAME)) if n.endswith('.json')]
    work = next(w for w in series_works
                if indexing.FROM_SERIES in entry(bookmarked, w))
    retitle(bookmarked, work, 'An Older Title')

    run(bookmarked, server.ACTION_BOOKMARKS)

    assert len(entry_files(bookmarked, work)) == 1


def test_duplicates_an_older_version_left_are_written_to_the_newest_and_named(bookmarked, capsys):
    newest = entry_path(bookmarked, NEWEST)
    with open(newest, encoding='utf-8') as f:
        data = json.load(f)
    stale = dict(data, last_indexed='2000-01-01T00:00:00+00:00')
    older = os.path.join(os.path.dirname(newest), f'{NEWEST} An Older Title - someone.json')
    with open(older, 'w', encoding='utf-8') as f:
        json.dump(stale, f)
    with open(older, encoding='utf-8') as f:
        before_older = f.read()

    run(bookmarked, server.ACTION_BOOKMARKS)

    # the older copy is left as it was; nothing is deleted
    with open(older, encoding='utf-8') as f:
        assert f.read() == before_older
    assert len(entry_files(bookmarked, NEWEST)) == 2
    # the most recently indexed one is the entry, and got this run's reading
    with open(newest, encoding='utf-8') as f:
        assert json.load(f)['last_indexed'] > data['last_indexed']

# endregion


def test_a_resumed_collection_run_notes_its_collection_on_what_it_holds(bookmarked):
    # the earlier attempt finished the collection, so the resume reads nothing of it - its
    # cleanup still notes the collection on the works it holds
    run_collection(bookmarked, works=False)
    forget_collections(bookmarked, NEWEST)
    folder = os.path.join(bookmarked, 'runs')
    name = sorted(os.listdir(folder))[-1]
    with open(os.path.join(folder, name), encoding='utf-8') as f:
        data = json.load(f)
    assert data['action'] == server.ACTION_COLLECTION
    data['status'] = 'interrupted'
    with open(os.path.join(folder, name), 'w', encoding='utf-8') as f:
        json.dump(data, f)

    asked = run(bookmarked, server.ACTION_CUSTOM, {'resume': data['id']})

    assert asked == []
    assert entry(bookmarked, NEWEST)[indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_new_series_entry_is_named_from_its_title_not_from_a_lookup_by_number(tmp_path):
    # the series walk looks a series up by its number before it has read the series page. a
    # name built from that lookup alone - no title, no author - must never be the file's name
    root = str(tmp_path / 'library')
    run(root, server.ACTION_BOOKMARKS, {'series': True})

    folder = os.path.join(root, strings.INDEXING_FOLDER_NAME, strings.SERIES_INDEX_FOLDER_NAME)
    names = [n for n in os.listdir(folder) if n.endswith('.json')]
    assert names
    assert not [n for n in names if n.endswith(' -.json') or '  ' in n]
