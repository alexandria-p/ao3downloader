"""A collections run asked to index and download the works in the collections it crawls.

The crawl already reads every page of a collection's works and bookmarks listings, 20 blurbs
to a page, and each blurb carries everything a bookmarks listing would - so indexing the
works costs nothing on top of it. What follows the crawl is borrowed: the series walk and the
download step every scan ends with.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import indexing, runs, server, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository

from test.test_collections_crawl import (COLLECTIONS_URL, collection_profile, collections_listing,
                                    requested, stored)


WORK_BLURB = """<li class="work blurb group work-{id}" id="work_{id}">
  <div class="header module">
    <h4 class="heading"><a href="/works/{id}">Work {id}</a>
      by <a rel="author" href="/users/writer">writer</a></h4>
    <p class="datetime">14 Dec 2024</p>
  </div>
  <dl class="stats"><dd class="chapters">1/1</dd><dd class="words">1,000</dd></dl>
</li>"""

# somebody else's bookmark of a work, as a collection's bookmarked items listing shows it
BOOKMARK_BLURB = """<li class="bookmark blurb group work-{id}" id="bookmark_9{id}">
  <div class="header module">
    <h4 class="heading"><a href="/works/{id}">Work {id}</a>
      by <a rel="author" href="/users/writer">writer</a></h4>
    <p class="datetime">14 Dec 2024</p>
  </div>
  <div class="user module group">
    <p class="datetime">01 Jan 2025</p>
    <blockquote class="userstuff notes"><p>a stranger's notes</p></blockquote>
    <ul class="meta tags"><li><a class="tag">their tag</a></li></ul>
  </div>
</li>"""


def listing(blurb: str, ids: list[str]) -> BeautifulSoup:
    return BeautifulSoup('<ol class="index group">' +
                         ''.join(blurb.format(id=i) for i in ids) + '</ol>', 'html.parser')


def pages(works: dict[str, list[str]], bookmarks: dict[str, list[str]] | None = None):
    """Serve each collection's pages, with the works and bookmarked items given per slug."""

    bookmarks = bookmarks or {}

    def dispatch(url: str) -> BeautifulSoup:
        if '/users/' in url: return collections_listing(list(works))
        slug = url.split('/collections/')[1].split('/')[0]
        if url.endswith('/profile'): return collection_profile(slug)
        if url.endswith('/works'): return listing(WORK_BLURB, works.get(slug, []))
        if url.endswith('/bookmarks'): return listing(BOOKMARK_BLURB, bookmarks.get(slug, []))
        return collections_listing([])
    return dispatch


def make_ao3(on_disk: dict | None = None, series: bool = False):
    """An Ao3 told to index collection works, over a fake library holding `on_disk`."""

    repo = MagicMock(spec=Repository)
    fileops = MagicMock(spec=FileOps)
    fileops.get_ini_value_boolean.return_value = False
    fileops.get_ini_value_integer.return_value = strings.INI_DEFAULT_NAME_LENGTH
    files = dict(on_disk or {})
    fileops.load_json.side_effect = lambda path: files.get(path)
    fileops.save_json.side_effect = lambda path, data: files.__setitem__(path, data)
    ao3 = Ao3(repo=repo, fileops=fileops, filetypes=['HTML'], pages=None, series=series,
              images=False)
    ao3.collection_works = []
    return ao3, repo, fileops, files


def entries(files: dict) -> dict[str, dict]:
    """Every work entry written to indexing/, flattened, by work id."""

    found = {}
    for path, data in files.items():
        if path.startswith(strings.INDEXING_FOLDER_NAME + os.sep):
            record = indexing.flatten(data)
            if record and record.get('id'): found[str(record['id'])] = record
    return found


# region indexing the works met on the way

def test_every_work_a_collection_holds_is_indexed_off_the_listing():
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111', '222']}, {'alpha': ['333']})

    ao3.get_collections(COLLECTIONS_URL)

    assert sorted(entries(files)) == ['111', '222', '333']
    assert [w['id'] for w in ao3.collection_works] == ['111', '222', '333']


def test_a_work_new_to_the_index_is_recorded_as_not_bookmarked():
    # the same rule as a work met through a series: it is in the index because of the
    # collection, not because you bookmarked it
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111']})

    ao3.get_collections(COLLECTIONS_URL)

    assert entries(files)['111'][strings.BOOKMARKED_FIELD] is False
    assert entries(files)['111'][indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_work_you_bookmarked_keeps_your_bookmark():
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111']})
    path = ao3.metadata_path({'id': '111', 'title': 'Work 111', 'authors': ['writer']})
    files[path] = {'id': '111', 'source': 'https://archiveofourown.org/users/me/bookmarks',
                   indexing.INDEXES: [{indexing.INDEXED_ON: 'earlier', 'title': 'Work 111',
                                       'authors': ['writer'], 'bookmark_notes': 'mine',
                                       strings.BOOKMARKED_FIELD: True}]}

    ao3.get_collections(COLLECTIONS_URL)

    entry = entries(files)['111']
    assert entry[strings.BOOKMARKED_FIELD] is True
    assert entry['bookmark_notes'] == 'mine'
    # and where it first came from
    assert entry['source'] == 'https://archiveofourown.org/users/me/bookmarks'


def test_somebody_elses_bookmark_is_not_written_in_as_yours():
    # a collection's bookmarked items are other people's bookmarks, notes and all
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': []}, {'alpha': ['333']})

    ao3.get_collections(COLLECTIONS_URL)

    entry = entries(files)['333']
    assert entry['bookmark_notes'] == ''
    assert entry['bookmark_tags'] == []
    assert entry['date_bookmarked'] == ''
    assert entry[strings.BOOKMARKED_FIELD] is False


def test_a_work_in_two_collections_is_read_once_and_found_through_both():
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111'], 'beta': ['111', '222']})

    ao3.get_collections(COLLECTIONS_URL)

    assert [w['id'] for w in ao3.collection_works] == ['111', '222']
    assert entries(files)['111'][indexing.FROM_COLLECTIONS] == ['alpha', 'beta']


def test_an_unchanged_count_does_not_skip_the_listing_when_indexing_works():
    # the count says the work numbers are the same, not that the works are - and indexing
    # them is reading the listing
    previous = stored(work_count=2, work_ids=['111', '222'], bookmark_count=3,
                      bookmark_ids=['333'])
    ao3, repo, _, files = make_ao3({os.path.join(strings.COLLECTIONS_FOLDER_NAME,
                                                 'alpha.json'): previous})
    repo.get_soup.side_effect = pages({'alpha': ['111', '222']}, {'alpha': ['333']})

    ao3.get_collections(COLLECTIONS_URL)

    assert any(url.endswith('/alpha/works') for url in requested(repo))
    assert sorted(entries(files)) == ['111', '222', '333']


def test_a_work_in_an_unrevealed_collection_is_indexed_and_held_back():
    ao3, repo, _, files = make_ao3()
    mystery = ('<ol class="index group"><li class="work blurb group work-444">'
               '<div class="header module"><h4 class="heading">Mystery Work</h4>'
               '</div></li></ol>')

    def dispatch(url):
        if url.endswith('/works'): return BeautifulSoup(mystery, 'html.parser')
        return pages({'alpha': []})(url)
    repo.get_soup.side_effect = dispatch

    ao3.get_collections(COLLECTIONS_URL)

    assert '444' in ao3.unrevealed
    assert [x['id'] for x in ao3.skipped_works] == ['444']


def test_the_series_of_each_work_are_marked_when_the_run_follows_them():
    ao3, repo, _, _ = make_ao3(series=True)
    in_series = WORK_BLURB.replace(
        '</dl>', '</dl><ul class="series"><li>Part 2 of <a href="/series/77">A Series</a></li></ul>')

    def dispatch(url):
        if url.endswith('/works'): return listing(in_series, ['111'])
        return pages({'alpha': []})(url)
    repo.get_soup.side_effect = dispatch

    ao3.get_collections(COLLECTIONS_URL)

    assert list(ao3.series_marked) == ['77']


def test_without_the_option_no_work_is_indexed():
    ao3, repo, _, files = make_ao3()
    ao3.collection_works = None
    repo.get_soup.side_effect = pages({'alpha': ['111']})

    ao3.get_collections(COLLECTIONS_URL)

    assert entries(files) == {}

# endregion


# region the run around it

def job_for(action=server.ACTION_COLLECTIONS, filetypes=('JSON', 'HTML'), **options):
    return server.Job(action, list(filetypes), 'Someone', server.resolve_options(options),
                      url='https://archiveofourown.org/collections/alpha')


@pytest.mark.parametrize('action', server.COLLECTION_ACTIONS)
def test_the_plan_downloads_what_the_crawl_indexed(action):
    ids = [step for step, _ in server.step_plan(job_for(action, collectionWorks=True))]

    assert ids[1] in ('collections', 'collection')
    assert ids[2:] == ['check', 'download', 'cleanup', 'report']


def test_the_plan_walks_series_only_when_asked_to():
    ids = [step for step, _ in server.step_plan(job_for(collectionWorks=True, series=True))]

    assert ids[2] == 'series'


def test_the_plan_of_a_collections_run_on_its_own_is_unchanged():
    ids = [step for step, _ in server.step_plan(job_for())]

    assert ids == ['login', 'collections', 'cleanup', 'report']


def test_a_metadata_only_run_indexes_the_works_without_downloading_them():
    ids = [step for step, _ in server.step_plan(job_for(filetypes=['JSON'], collectionWorks=True))]

    assert 'download' not in ids


@pytest.mark.parametrize('action', server.COLLECTION_ACTIONS)
def test_the_run_downloads_the_works_it_indexed(action):
    job = job_for(action, collectionWorks=True)
    ao3 = MagicMock()
    ao3.collection_works = None
    ao3.filetypes = ['HTML']
    found = [{'id': '111', 'link': 'https://archiveofourown.org/works/111'}]

    def crawl(_link):
        ao3.collection_works = found
        return [{'name': 'alpha'}]
    ao3.get_collections.side_effect = crawl
    ao3.get_collection.side_effect = crawl

    with patch.object(server, 'Ao3', return_value=ao3) as made, \
         patch.object(server, 'download_planned') as download, \
         patch.object(server, 'finish_run'):
        getattr(server, 'run_' + action)(job, MagicMock(), MagicMock(), MagicMock())

    # told what to download, and to follow no series it was not asked to
    assert made.call_args.args[2] == ['HTML']
    assert made.call_args.args[4] is False
    assert download.call_args.args[3] == found
    assert download.call_args.args[4] == ['HTML']


def test_the_run_walks_the_series_it_marked_before_downloading():
    job = job_for(collectionWorks=True, series=True)
    ao3 = MagicMock()
    ao3.filetypes = ['HTML']

    def crawl(_link):
        ao3.collection_works = [{'id': '111'}]
        return []
    ao3.get_collections.side_effect = crawl

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'index_marked_series', return_value=[{'id': '222'}]), \
         patch.object(server, 'download_planned') as download, \
         patch.object(server, 'finish_run'):
        server.run_collections(job, MagicMock(), MagicMock(), MagicMock())

    assert [x['id'] for x in download.call_args.args[3]] == ['111', '222']


def test_without_the_option_nothing_is_downloaded():
    job = job_for()
    ao3 = MagicMock()
    ao3.collection_works = None
    ao3.get_collections.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned') as download, \
         patch.object(server, 'finish_run'):
        server.run_collections(job, MagicMock(), MagicMock(), MagicMock())

    download.assert_not_called()


def started(action, options, filetypes=('JSON', 'HTML')):
    """Post a job and hand back the options and file types it was started with."""

    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {
        'action': action, 'username': 'Someone', 'password': 'a-password',
        'filetypes': list(filetypes), 'options': options,
        'url': 'https://archiveofourown.org/collections/alpha'}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)
    with patch.object(server.threading, 'Thread'), patch.dict(server.Handler.jobs, clear=True):
        server.Handler.do_POST(handler)
    assert sent['status'] == 202, sent
    return sent['body']['options'], sent['body']['filetypes']


@pytest.mark.parametrize('action', [server.ACTION_BOOKMARKS, server.ACTION_QUICK,
                                    server.ACTION_SYNC])
def test_only_a_collections_run_can_be_told_to_index_collection_works(action):
    options, _ = started(action, {'collectionWorks': True})

    assert options['collectionWorks'] is False


@pytest.mark.parametrize('action', server.COLLECTION_ACTIONS)
def test_a_collections_run_on_its_own_saves_no_works_and_follows_no_series(action):
    # the record must not say it saved html, or walked series it never looked at
    options, filetypes = started(action, {'series': True})

    assert filetypes == ['JSON']
    assert options['series'] is False


@pytest.mark.parametrize('action', server.COLLECTION_ACTIONS)
def test_a_collections_run_indexing_works_keeps_its_file_types_and_series(action):
    options, filetypes = started(action, {'collectionWorks': True, 'series': True})

    assert filetypes == ['JSON', 'HTML']
    assert options['series'] is True

# endregion


# region the link, kept for running it again

def test_a_run_record_keeps_the_link_it_was_pointed_at(tmp_path):
    fileops = MagicMock()
    fileops.runsfolder = str(tmp_path)
    saved = {}
    fileops.write_text.side_effect = lambda path, text: saved.update(json.loads(text))

    runs.RunRecord(fileops, 'abcdef123', server.ACTION_COLLECTION, 'Index collection by URL',
                   ['JSON'], {}, url='https://archiveofourown.org/collections/alpha')

    assert saved['url'] == 'https://archiveofourown.org/collections/alpha'


def test_run_job_hands_the_record_the_jobs_link():
    job = job_for(server.ACTION_COLLECTION)
    with patch.object(server.runs, 'RunRecord') as record, \
         patch.object(server, 'FileOps'), patch.object(server, 'Repository'), \
         patch.object(server, 'run_collection'):
        server.run_job(job, 'a-password')

    assert record.call_args.kwargs['url'] == 'https://archiveofourown.org/collections/alpha'

# endregion
