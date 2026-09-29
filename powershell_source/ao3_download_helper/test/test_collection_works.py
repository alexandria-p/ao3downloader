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

from source_code import indexing, parse_soup, parse_text, runs, server, strings
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
    # the library is rooted at '', so a folder is listed straight off the paths saved in it
    fileops.downloadfolder = ''
    fileops.list_files.side_effect = lambda folder: [
        os.path.basename(path) for path in files if os.path.dirname(path) == folder]
    ao3 = Ao3(repo=repo, fileops=fileops, filetypes=['HTML'], pages=None, series=series,
              images=False)
    ao3.collection_works = []
    return ao3, repo, fileops, files


def linked(ao3, fileops, records: list[dict], action: str = 'collections') -> None:
    """End the crawl the way a run does: its cleanup step, which is where `from_collections`
    is set - never the crawl itself."""

    job = server.Job(action, ['JSON'], 'Someone')
    job.collections_read = [str(r['name']) for r in records if r.get('name')]
    job.steps = MagicMock()
    server.cleanup(job, fileops, ao3)


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
    ao3, repo, fileops, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111']})

    records = ao3.get_collections(COLLECTIONS_URL)
    linked(ao3, fileops, records)

    assert entries(files)['111'][strings.BOOKMARKED_FIELD] is False
    assert entries(files)['111'][indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_work_you_bookmarked_keeps_your_bookmark():
    ao3, repo, fileops, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111']})
    path = ao3.metadata_path({'id': '111', 'title': 'Work 111', 'authors': ['writer']})
    files[path] = {'id': '111', 'source': 'https://archiveofourown.org/users/me/bookmarks',
                   indexing.INDEXES: [{indexing.INDEXED_ON: 'earlier', 'title': 'Work 111',
                                       'authors': ['writer'], 'bookmark_notes': 'mine',
                                       strings.BOOKMARKED_FIELD: True}]}

    records = ao3.get_collections(COLLECTIONS_URL)
    linked(ao3, fileops, records, 'collections')

    entry = entries(files)['111']
    assert entry[strings.BOOKMARKED_FIELD] is True
    assert entry['bookmark_notes'] == 'mine'
    # and where it first came from
    assert entry['source'] == 'https://archiveofourown.org/users/me/bookmarks'
    # now also found through the collection
    assert entry[indexing.FROM_COLLECTIONS] == ['alpha']


def test_a_bookmarked_work_found_through_a_series_too_keeps_that_as_well():
    ao3, repo, fileops, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111'], 'beta': ['111']})
    path = ao3.metadata_path({'id': '111', 'title': 'Work 111', 'authors': ['writer']})
    files[path] = {'id': '111', indexing.FROM_SERIES: ['77'],
                   indexing.INDEXES: [{indexing.INDEXED_ON: 'earlier', 'title': 'Work 111',
                                       'authors': ['writer'], strings.BOOKMARKED_FIELD: True}]}

    records = ao3.get_collections(COLLECTIONS_URL)
    linked(ao3, fileops, records, 'collections')

    entry = entries(files)['111']
    assert entry[indexing.FROM_SERIES] == ['77']
    assert entry[indexing.FROM_COLLECTIONS] == ['alpha', 'beta']
    assert entry[strings.BOOKMARKED_FIELD] is True


def test_without_the_works_option_a_bookmarked_work_is_not_touched():
    ao3, repo, _, files = make_ao3()
    ao3.collection_works = None
    repo.get_soup.side_effect = pages({'alpha': ['111']})
    path = ao3.metadata_path({'id': '111', 'title': 'Work 111', 'authors': ['writer']})
    files[path] = {'id': '111', indexing.INDEXES: [{indexing.INDEXED_ON: 'earlier',
                                                    strings.BOOKMARKED_FIELD: True}]}

    ao3.get_collections(COLLECTIONS_URL)

    assert indexing.FROM_COLLECTIONS not in files[path]


def test_the_crawl_itself_never_writes_from_collections():
    # it is set in one place only, the run's cleanup step - see `server.collection_links`
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111']}, {'alpha': ['333']})

    ao3.get_collections(COLLECTIONS_URL)

    assert all(indexing.FROM_COLLECTIONS not in e for e in entries(files).values())


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
    ao3, repo, fileops, files = make_ao3()
    repo.get_soup.side_effect = pages({'alpha': ['111'], 'beta': ['111', '222']})

    records = ao3.get_collections(COLLECTIONS_URL)
    linked(ao3, fileops, records, 'collections')

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


# region resuming a collection run from the page it got to

def paged(ids_by_page: list[list[str]], blurb: str = WORK_BLURB):
    """A listing served a page at a time, with ao3's pagination on every page."""

    def page_of(url: str) -> BeautifulSoup:
        number = parse_text.get_page_number(url)
        ids = ids_by_page[number - 1] if number <= len(ids_by_page) else []
        nav = ''.join(f'<li><a>{n}</a></li>' for n in range(1, len(ids_by_page) + 1))
        return BeautifulSoup('<ol class="index group">' +
                             ''.join(blurb.format(id=i) for i in ids) + '</ol>' +
                             f'<ol class="pagination">{nav}</ol>', 'html.parser')
    return page_of


def profile_holding(slug: str, works: int, bookmarks: int = 0) -> BeautifulSoup:
    return BeautifulSoup(str(collection_profile(slug))
                         .replace('Works (2)', f'Works ({works})')
                         .replace('Bookmarked Items (3)', f'Bookmarked Items ({bookmarks})'),
                         'html.parser')


def one_collection(works_pages: list[list[str]], count: int):
    def dispatch(url: str) -> BeautifulSoup:
        if url.endswith('/profile'): return profile_holding('alpha', count)
        if '/alpha/works' in url: return paged(works_pages)(url)
        if '/alpha/bookmarks' in url: return listing(BOOKMARK_BLURB, [])
        return collections_listing([])
    return dispatch


ALPHA = 'https://archiveofourown.org/collections/alpha'


def test_every_page_of_a_collection_listing_is_checkpointed():
    ao3, repo, _, _ = make_ao3()
    repo.get_soup.side_effect = one_collection([['1', '2'], ['3', '4'], ['5']], 5)
    pages = []
    ao3.on_collection_page = lambda slug, key, page, ids, done=False, externals=None: \
        pages.append((slug, key, page, ids, done))

    ao3.get_collection(ALPHA)

    works = [x for x in pages if x[1] == 'work_ids']
    assert works[:3] == [('alpha', 'work_ids', 1, ['1', '2'], False),
                         ('alpha', 'work_ids', 2, ['1', '2', '3', '4'], False),
                         ('alpha', 'work_ids', 3, ['1', '2', '3', '4', '5'], False)]
    assert works[-1] == ('alpha', 'work_ids', None, ['1', '2', '3', '4', '5'], True)


def test_a_finished_collection_says_so_with_every_work_it_holds():
    ao3, repo, _, _ = make_ao3()
    repo.get_soup.side_effect = one_collection([['1', '2']], 2)
    finished = []
    ao3.on_collection_done = lambda slug, works, family: finished.append((slug, works))

    ao3.get_collection(ALPHA)

    assert finished == [('alpha', ['1', '2'])]


def test_a_collection_whose_listing_failed_partway_is_not_counted_as_finished():
    ao3, repo, _, _ = make_ao3()

    def dispatch(url):
        if '/alpha/works' in url and 'page=2' in url: raise ConnectionError('gone')
        return one_collection([['1', '2'], ['3']], 3)(url)
    repo.get_soup.side_effect = dispatch
    finished = []
    ao3.on_collection_done = lambda slug, works, family: finished.append(slug)

    ao3.get_collection(ALPHA)

    assert finished == []


def test_a_resumed_listing_carries_on_from_the_last_page_it_saved():
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = one_collection([['1', '2'], ['3', '4'], ['5']], 5)
    ao3.records_for = lambda ids: [{'id': x} for x in ids]
    ao3.collections_before = {'alpha': {'listings': {'work_ids': {'page': 2, 'ids': ['1', '2', '3', '4']}}}}

    records = ao3.get_collection(ALPHA)

    works_pages = [u for u in requested(repo) if '/alpha/works' in u]
    # the saved page is read again, the ones before it are not
    assert works_pages == [ALPHA + '/works?page=2', ALPHA + '/works?page=3']
    assert records[0]['work_ids'] == ['1', '2', '3', '4', '5']
    # the works read before are downloaded with the rest
    assert sorted(w['id'] for w in ao3.collection_works) == ['1', '2', '3', '4', '5']


def test_reading_the_saved_page_again_catches_a_work_pulled_up_by_a_removal():
    # work 1 left the collection, so everything moved up a place: work 5 is now on page 2,
    # which the earlier attempt had already finished
    ao3, repo, _, _ = make_ao3()
    repo.get_soup.side_effect = one_collection([['2', '3'], ['4', '5'], ['6']], 5)
    ao3.records_for = lambda ids: [{'id': x} for x in ids]
    ao3.collections_before = {'alpha': {'listings': {'work_ids': {'page': 2, 'ids': ['1', '2', '3', '4']}}}}

    records = ao3.get_collection(ALPHA)

    assert '5' in records[0]['work_ids']


def test_a_resumed_listing_short_of_the_collections_count_reads_the_earlier_pages_again():
    # work 9 was updated since, and jumped to the front - onto a page already read
    ao3, repo, _, _ = make_ao3()
    repo.get_soup.side_effect = one_collection([['9', '1'], ['2', '3'], ['4', '5']], 6)
    ao3.records_for = lambda ids: [{'id': x} for x in ids]
    ao3.collections_before = {'alpha': {'listings': {'work_ids': {'page': 2, 'ids': ['1', '2']}}}}

    records = ao3.get_collection(ALPHA)

    assert sorted(records[0]['work_ids']) == ['1', '2', '3', '4', '5', '9']
    assert ALPHA + '/works' in requested(repo)


def test_a_listing_the_earlier_attempt_finished_is_not_read_again():
    ao3, repo, _, _ = make_ao3()
    repo.get_soup.side_effect = one_collection([['1', '2']], 2)
    ao3.records_for = lambda ids: [{'id': x} for x in ids]
    ao3.collections_before = {'alpha': {'listings': {
        'work_ids': {'page': 1, 'ids': ['1', '2'], 'done': True}}}}

    records = ao3.get_collection(ALPHA)

    assert not any('/alpha/works' in u for u in requested(repo))
    assert records[0]['work_ids'] == ['1', '2']


def test_a_collection_the_earlier_attempt_finished_is_skipped_and_its_works_kept():
    ao3, repo, _, _ = make_ao3()
    repo.get_soup.side_effect = one_collection([['1', '2']], 2)
    ao3.records_for = lambda ids: [{'id': x, 'link': 'l' + x} for x in ids]
    ao3.collections_before = {'alpha': {'done': True, 'works': ['1', '2']}}

    ao3.get_collection(ALPHA)

    repo.get_soup.assert_not_called()
    assert [w['id'] for w in ao3.collection_works] == ['1', '2']


def resumable_record(**over) -> dict:
    return {'id': 'r1', 'action': server.ACTION_COLLECTION, 'status': runs.STATUS_INTERRUPTED,
            'options': {'collectionWorks': True}, 'filetypes': ['JSON', 'HTML'],
            'url': ALPHA, 'progress': {}, **over}


@pytest.mark.parametrize('action', server.COLLECTION_ACTIONS)
def test_collection_runs_can_be_resumed(action):
    assert server.resume_problem(resumable_record(action=action), set()) == ''


def test_a_collection_run_from_before_links_were_saved_cannot_be_resumed():
    assert server.resume_problem(resumable_record(url=''), set()) == strings.RESUME_NO_LINK


def test_a_resumed_collection_run_is_pointed_at_the_same_collection():
    job = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone',
                     server.resolve_options({'resume': 'r1'}))
    with patch.object(server.runs, 'find_run', return_value=resumable_record()):
        server.prepare_resume(job, MagicMock())

    assert job.action == server.ACTION_COLLECTION
    assert job.url == ALPHA
    assert job.options['collectionWorks'] is True


def test_a_collection_run_saves_where_it_got_to_after_every_page():
    job = job_for(collectionWorks=True)
    job.record = MagicMock()
    job.record.data = {'progress': {}}
    ao3 = Ao3(MagicMock(), MagicMock(), ['HTML'], None, False, False)

    server.watch_collections(job, MagicMock(), ao3)
    ao3.on_collection_page('alpha', 'work_ids', 3, ['1', '2'])
    ao3.on_collection_done('beta', ['7'])

    saved = job.record.checkpoint.call_args.kwargs['collections']
    assert saved['alpha']['listings']['work_ids'] == {'ids': ['1', '2'], 'done': False, 'page': 3}
    assert saved['beta'] == {'done': True, 'works': ['7'], 'family': []}


def test_a_resumed_collection_run_starts_from_what_the_earlier_attempt_saved():
    job = job_for(collectionWorks=True)
    job.record = MagicMock()
    job.record.data = {'progress': {}}
    earlier = {'alpha': {'done': True, 'works': ['1']},
               'beta': {'done': False, 'listings': {'work_ids': {'page': 4, 'ids': ['2']}}}}
    job.resume = {'id': 'r1', 'progress': {'collections': earlier}}
    ao3 = Ao3(MagicMock(), MagicMock(), ['HTML'], None, False, False)

    server.watch_collections(job, MagicMock(), ao3)

    assert ao3.collections_before == earlier
    # a second resume skips what the first attempt finished, too
    assert job.record.data['progress']['collections']['alpha'] == {'done': True, 'works': ['1']}


def test_a_run_resumed_at_its_download_step_goes_straight_back_to_it():
    job = job_for(collectionWorks=True, series=True)
    job.resume = {'id': 'r1', 'progress': {'scope': ['1', '2']}}
    ao3 = MagicMock()
    ao3.filetypes = ['HTML']

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'records_by_id', return_value=[{'id': '1'}, {'id': '2'}]), \
         patch.object(server, 'index_marked_series') as series, \
         patch.object(server, 'download_planned') as download, \
         patch.object(server, 'finish_run'):
        server.run_collection(job, MagicMock(), MagicMock(), MagicMock())

    ao3.get_collection.assert_not_called()
    series.assert_not_called()
    assert [x['id'] for x in download.call_args.args[3]] == ['1', '2']

# endregion


# region following a collection's family - its subcollections and its parent

def family_profile(slug: str, parent: str | None, children: list[str]) -> BeautifulSoup:
    parent_li = f'<li><a href="/collections/{parent}">Parent Collection</a></li>' if parent else ''
    subs = (f'<li><a href="/collections/{slug}/collections">Subcollections ({len(children)})</a></li>'
            if children else '')
    return BeautifulSoup(f"""
      <div id="main" class="collection_profile-show">
        <h2 class="heading">Title of {slug}</h2>
        <ul class="navigation actions"><li><a href="/collections/{slug}">Dashboard</a></li>{parent_li}</ul>
        <ul class="navigation actions">{subs}
          <li><a href="/collections/{slug}/works">Works (1)</a></li>
          <li><a href="/collections/{slug}/bookmarks">Bookmarked Items (0)</a></li>
        </ul>
      </div>""", 'html.parser')


def family(tree: dict[str, tuple[str | None, list[str]]], own: list[str] | None = None):
    """Serve a family of collections: each name's (parent, children), and one work each,
    numbered after the collection so it can be told where it came from."""

    def dispatch(url: str) -> BeautifulSoup:
        if '/users/' in url: return collections_listing(own or [])
        slug = url.split('/collections/')[1].split('/')[0].split('?')[0]
        parent, children = tree[slug]
        if url.endswith('/profile'): return family_profile(slug, parent, children)
        if url.endswith(f'/{slug}/collections'): return collections_listing(children)
        if '/works' in url: return listing(WORK_BLURB, [str(abs(hash(slug)) % 100000)])
        if '/bookmarks' in url: return listing(BOOKMARK_BLURB, [])
        raise AssertionError(url)
    return dispatch


def profiles_read(repo) -> list[str]:
    return [u.split('/collections/')[1].split('/')[0] for u in requested(repo)
            if u.endswith('/profile')]


def following(subcollections=False, parents=False):
    ao3, repo, fileops, files = make_ao3()
    ao3.collection_works = None
    ao3.follow_subcollections = subcollections
    ao3.follow_parents = parents
    return ao3, repo, fileops, files


def test_subcollections_are_read_too_when_asked_and_their_own_in_turn():
    ao3, repo, _, _ = following(subcollections=True)
    repo.get_soup.side_effect = family({'a': (None, ['b', 'c']), 'b': ('a', ['d']),
                                        'c': ('a', []), 'd': ('b', [])})

    records = ao3.get_collection('https://archiveofourown.org/collections/a')

    assert [r['name'] for r in records] == ['a', 'b', 'c', 'd']


def test_a_parent_is_not_followed_unless_asked():
    ao3, repo, _, _ = following(subcollections=True)
    repo.get_soup.side_effect = family({'b': ('a', []), 'a': (None, ['b'])})

    ao3.get_collection('https://archiveofourown.org/collections/b')

    assert profiles_read(repo) == ['b']


def test_parents_are_read_too_when_asked_all_the_way_up():
    ao3, repo, _, _ = following(parents=True)
    repo.get_soup.side_effect = family({'c': ('b', []), 'b': ('a', ['c', 'x']),
                                        'a': (None, ['b']), 'x': ('b', [])})

    records = ao3.get_collection('https://archiveofourown.org/collections/c')

    # parents only: the sibling x is a subcollection, which was not asked for
    assert [r['name'] for r in records] == ['c', 'b', 'a']


def test_a_family_that_links_round_in_a_circle_is_read_once_each_and_the_run_ends():
    # every one of these points at the others, several steps round
    ao3, repo, _, _ = following(subcollections=True, parents=True)
    repo.get_soup.side_effect = family({'a': ('c', ['b']), 'b': ('a', ['c']),
                                        'c': ('b', ['a', 'b'])})

    records = ao3.get_collection('https://archiveofourown.org/collections/a')

    assert sorted(r['name'] for r in records) == ['a', 'b', 'c']
    assert sorted(profiles_read(repo)) == ['a', 'b', 'c']


def test_a_collection_that_is_its_own_parent_is_read_once():
    ao3, repo, _, _ = following(subcollections=True, parents=True)
    repo.get_soup.side_effect = family({'a': ('a', ['a'])})

    ao3.get_collection('https://archiveofourown.org/collections/a')

    assert profiles_read(repo) == ['a']


def test_a_family_bigger_than_the_limit_stops_there_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(strings, 'COLLECTION_FAMILY_LIMIT', 3)
    ao3, repo, _, _ = following(subcollections=True)
    chain = {f'c{n}': (None, [f'c{n + 1}']) for n in range(10)}
    chain['c10'] = (None, [])
    repo.get_soup.side_effect = family(chain)

    records = ao3.get_collection('https://archiveofourown.org/collections/c0')

    # the one asked for, then three relatives
    assert [r['name'] for r in records] == ['c0', 'c1', 'c2', 'c3']
    assert 'the most one run will follow' in capsys.readouterr().out


def test_your_own_collections_are_not_read_again_as_each_others_family():
    ao3, repo, _, _ = following(subcollections=True, parents=True)
    repo.get_soup.side_effect = family({'a': (None, ['b']), 'b': ('a', [])}, own=['a', 'b'])

    ao3.get_collections(COLLECTIONS_URL)

    assert sorted(profiles_read(repo)) == ['a', 'b']


def test_the_works_of_the_family_are_indexed_with_the_rest():
    ao3, repo, fileops, files = make_ao3()
    ao3.follow_subcollections = True
    repo.get_soup.side_effect = family({'a': (None, ['b']), 'b': ('a', [])})

    records = ao3.get_collection('https://archiveofourown.org/collections/a')
    linked(ao3, fileops, records, 'collection')

    assert len(ao3.collection_works) == 2
    assert sorted(e[indexing.FROM_COLLECTIONS][0] for e in entries(files).values()) == ['a', 'b']


def test_a_finished_collection_says_which_relatives_it_links_to():
    ao3, repo, _, _ = following(subcollections=True)
    repo.get_soup.side_effect = family({'a': (None, ['b']), 'b': ('a', [])})
    finished = []
    ao3.on_collection_done = lambda slug, works, family: finished.append((slug, family))

    ao3.get_collection('https://archiveofourown.org/collections/a')

    assert finished == [('a', ['b']), ('b', [])]


def test_a_resume_still_follows_the_family_of_a_collection_it_skips():
    ao3, repo, _, _ = following(subcollections=True)
    ao3.records_for = lambda ids: []
    ao3.collections_before = {'a': {'done': True, 'works': [], 'family': ['b']}}
    repo.get_soup.side_effect = family({'a': (None, ['b']), 'b': ('a', [])})

    records = ao3.get_collection('https://archiveofourown.org/collections/a')

    assert profiles_read(repo) == ['b']
    assert [r['name'] for r in records] == ['a', 'b']


@pytest.mark.parametrize('action', [server.ACTION_BOOKMARKS, server.ACTION_QUICK, server.ACTION_SYNC])
def test_only_a_collection_run_can_follow_a_collections_family(action):
    options, _ = started(action, {'subcollections': True, 'parentCollections': True})

    assert options['subcollections'] is False
    assert options['parentCollections'] is False


@pytest.mark.parametrize('action', server.COLLECTION_ACTIONS)
def test_a_collection_run_is_told_which_relatives_to_follow(action):
    job = job_for(action, subcollections=True, parentCollections=False)
    ao3 = MagicMock()
    ao3.get_collections.return_value = []
    ao3.get_collection.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), patch.object(server, 'finish_run'):
        getattr(server, 'run_' + action)(job, MagicMock(), MagicMock(), MagicMock())

    assert ao3.follow_subcollections is True
    assert ao3.follow_parents is False

# endregion


# region external works among a collection's bookmarked items

def external_listing() -> BeautifulSoup:
    """A real ao3 listing holding one external work - its number is 1, and its title links to
    an ao3 address (/en/works/863) that it must never be taken for."""

    with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'externalWork.html'),
              encoding='utf-8') as f:
        return BeautifulSoup(f.read(), 'html.parser')


def with_external(slugs: list[str] | None = None):
    def dispatch(url: str) -> BeautifulSoup:
        if '/bookmarks' in url: return external_listing()
        return pages({slug: ['111'] for slug in (slugs or ['alpha'])})(url)
    return dispatch


def externals(files: dict) -> dict[str, dict]:
    folder = os.path.join(strings.INDEXING_FOLDER_NAME, strings.EXTERNAL_INDEX_FOLDER_NAME)
    return {str(indexing.flatten(data)['id']): indexing.flatten(data)
            for path, data in files.items() if path.startswith(folder + os.sep)}


def test_an_external_work_in_a_collections_bookmarks_is_indexed_with_your_external_works():
    ao3, repo, fileops, files = make_ao3()
    repo.get_soup.side_effect = with_external()

    records = ao3.get_collections(COLLECTIONS_URL)
    linked(ao3, fileops, records, 'collections')

    entry = externals(files)['1']
    assert entry[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_EXTERNAL
    assert entry['link'] == 'https://archiveofourown.org/en/works/863'
    assert entry[indexing.FROM_COLLECTIONS] == ['alpha']
    assert entry[strings.BOOKMARKED_FIELD] is False
    # never a work: not among the collection's work numbers, not downloaded, and never
    # taken for the ao3 work its title links to
    assert records[0]['bookmark_ids'] == []
    assert [w['id'] for w in ao3.collection_works] == ['111']
    assert '863' not in entries(files)


def test_somebody_elses_notes_on_an_external_work_are_not_written_in_as_yours():
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = with_external()

    ao3.get_collections(COLLECTIONS_URL)

    entry = externals(files)['1']
    assert entry['bookmark_notes'] == ''
    assert entry['bookmark_tags'] == []


def test_an_external_work_you_bookmarked_keeps_your_bookmark():
    ao3, repo, _, files = make_ao3()
    repo.get_soup.side_effect = with_external()
    blurb = parse_soup.get_blurbs(external_listing())[0]
    yours = parse_soup.get_external_bookmark_metadata(blurb, '1')
    path = ao3.metadata_path(yours, strings.EXTERNAL_INDEX_FOLDER_NAME)
    files[path] = {'id': '1', indexing.INDEXES: [{indexing.INDEXED_ON: 'earlier',
                                                  'bookmark_notes': 'mine',
                                                  strings.BOOKMARKED_FIELD: True}]}

    ao3.get_collections(COLLECTIONS_URL)

    entry = externals(files)['1']
    assert entry[strings.BOOKMARKED_FIELD] is True
    assert entry['bookmark_notes'] == 'mine'


def test_an_external_work_in_two_collections_is_found_through_both():
    ao3, repo, fileops, files = make_ao3()
    repo.get_soup.side_effect = with_external(['alpha', 'beta'])

    records = ao3.get_collections(COLLECTIONS_URL)
    linked(ao3, fileops, records, 'collections')

    assert externals(files)['1'][indexing.FROM_COLLECTIONS] == ['alpha', 'beta']


def test_external_works_are_left_alone_unless_the_works_are_asked_for():
    ao3, repo, _, files = make_ao3()
    ao3.collection_works = None
    repo.get_soup.side_effect = with_external()

    ao3.get_collections(COLLECTIONS_URL)

    assert externals(files) == {}

# endregion


def test_a_collection_records_the_external_works_among_its_bookmarked_items():
    # whether or not the works are indexed: the numbers come off the page read anyway
    for works in (True, False):
        ao3, repo, _, _ = make_ao3()
        if not works: ao3.collection_works = None
        repo.get_soup.side_effect = with_external()

        records = ao3.get_collections(COLLECTIONS_URL)

        assert records[0]['external_ids'] == ['1']
        assert records[0]['bookmark_ids'] == []


def test_an_unchanged_collection_keeps_the_external_works_it_had():
    previous = stored(work_count=2, work_ids=['111', '222'], bookmark_count=3,
                      bookmark_ids=['333'], external_ids=['1'])
    ao3, repo, _, _ = make_ao3({os.path.join(strings.COLLECTIONS_FOLDER_NAME, 'alpha.json'): previous})
    ao3.collection_works = None
    repo.get_soup.side_effect = with_external()

    records = ao3.get_collections(COLLECTIONS_URL)

    assert records[0]['external_ids'] == ['1']


def test_a_resumed_listing_keeps_the_external_works_it_had_found():
    ao3, repo, _, _ = make_ao3()
    ao3.records_for = lambda ids: []
    ao3.collections_before = {'alpha': {'listings': {
        'bookmark_ids': {'page': 1, 'ids': [], 'externals': ['7'], 'done': True}}}}
    repo.get_soup.side_effect = with_external()

    records = ao3.get_collection('https://archiveofourown.org/collections/alpha')

    assert records[0]['external_ids'] == ['7']


def test_the_external_works_found_so_far_go_into_the_checkpoint():
    job = job_for(collectionWorks=True)
    job.record = MagicMock()
    job.record.data = {'progress': {}}
    ao3 = Ao3(MagicMock(), MagicMock(), ['HTML'], None, False, False)

    server.watch_collections(job, MagicMock(), ao3)
    ao3.on_collection_page('alpha', 'bookmark_ids', 2, ['5'], externals=['1'])

    saved = job.record.checkpoint.call_args.kwargs['collections']
    assert saved['alpha']['listings']['bookmark_ids']['externals'] == ['1']
