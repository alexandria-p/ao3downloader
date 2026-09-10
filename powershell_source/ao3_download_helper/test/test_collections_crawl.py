"""Tests for Ao3.get_collections — crawling a user's collections and saving each one.

The soup is served by url rather than in a fixed order, so the tests do not depend on
exactly how many requests the crawl makes or in what sequence.
"""

import os
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from source_code import exceptions, indexing, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


COLLECTIONS_URL = 'https://archiveofourown.org/users/Someone/collections'


def make_ao3():
    repo = MagicMock(spec=Repository)
    fileops = MagicMock(spec=FileOps)
    fileops.get_ini_value_boolean.return_value = False
    fileops.get_ini_value.return_value = strings.INI_DEFAULT_NAME_PATTERN
    fileops.get_ini_value_integer.return_value = strings.INI_DEFAULT_NAME_LENGTH
    fileops.load_json.return_value = None
    ao3 = Ao3(repo=repo, fileops=fileops, filetypes=[], pages=None, series=False, images=False)
    return ao3, repo, fileops


# region page builders

COLLECTION_BLURB = """<li class="collection blurb group">
  <div class="header module group">
    <h4 class="heading">
      <a href="/collections/{slug}">Title of {slug}</a>
      <span class="name">({slug})</span>
      <a class="owner" href="/users/Someone">Someone</a>
    </h4>
    <p class="datetime">01 Jan 2024</p>
  </div>
  <blockquote class="userstuff summary"><p>About {slug}.</p></blockquote>
  <p class="type">(Closed, Moderated)</p>
  <dl class="stats">
    <dt class="works">Works:</dt><dd class="works"><a href="#">2</a></dd>
    <dt class="bookmarks">Bookmarked Items:</dt><dd class="bookmarks"><a href="#">3</a></dd>
  </dl>
</li>"""

WORK_BLURB = """<li class="bookmark blurb group work-{id} user-1">
  <div class="header module"><h4 class="heading"><a href="/works/{id}">Work {id}</a></h4></div>
</li>"""


def collections_listing(slugs: list[str]) -> BeautifulSoup:
    blurbs = ''.join(COLLECTION_BLURB.format(slug=s) for s in slugs)
    return BeautifulSoup(f'<ol class="collection index group">{blurbs}</ol>', 'html.parser')


def works_listing(ids: list[str]) -> BeautifulSoup:
    blurbs = ''.join(WORK_BLURB.format(id=i) for i in ids)
    return BeautifulSoup(f'<ol class="index group">{blurbs}</ol>', 'html.parser')


def collection_profile(slug: str, subcollections: int = 0, fandoms: int = 3) -> BeautifulSoup:
    subnav = ''
    if subcollections is not None:
        subnav = (f'<li><a href="/collections/{slug}/collections">'
                  f'Subcollections ({subcollections})</a></li>')
    return BeautifulSoup(f"""
      <div id="main" class="collection_profile-show">
        <dl class="meta group">
          <dt>Active since:<dd>2024-01-01</dd>
          <dt>Collection tags:</dt>
          <dd><ul class="tags"><li><a class="tag">A Fandom</a></li></ul></dd>
          <dt class="maintainers">Maintainers:</dt>
          <dd class="maintainers"><ul><li><a href="/users/Someone">Someone</a></li></ul></dd>
        </dl>
        <ul class="navigation actions">
          <li><a href="/collections/{slug}">Dashboard</a></li>
          <li><a href="/collections/parentcoll">Parent Collection</a></li>
        </ul>
        <ul class="navigation actions">
          {subnav}
          <li><a href="/collections/{slug}/fandoms">Fandoms ({fandoms})</a></li>
          <li><a href="/collections/{slug}/works">Works (2)</a></li>
          <li><a href="/collections/{slug}/bookmarks">Bookmarked Items (3)</a></li>
        </ul>
      </div>""", 'html.parser')


def pages_for(slugs: list[str], subcollections: int = 0):
    """Serve whichever collection page is asked for."""
    def dispatch(url: str) -> BeautifulSoup:
        # the user's own listing also ends in /collections, so it is matched first
        if '/users/' in url: return collections_listing(slugs)
        if url.endswith('/profile'):
            slug = url.split('/collections/')[1].split('/')[0]
            return collection_profile(slug, subcollections)
        if url.endswith('/works'): return works_listing(['111', '222'])
        if url.endswith('/bookmarks'): return works_listing(['333'])
        if url.endswith('/collections'): return collections_listing(['childcoll'])
        return collections_listing(slugs)
    return dispatch


def saved(fileops) -> dict[str, dict]:
    return {call.args[0]: call.args[1] for call in fileops.save_json.call_args_list}


def latest_entry(fileops) -> dict:
    return list(saved(fileops).values())[0][indexing.INDEXES][-1]


def path_for(slug: str) -> str:
    return os.path.join(strings.COLLECTIONS_FOLDER_NAME, f'{slug}.json')

# endregion


# region what gets written

def test_saves_one_file_per_collection():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha', 'beta'])

    records = ao3.get_collections(COLLECTIONS_URL)

    assert [r['name'] for r in records] == ['alpha', 'beta']
    assert sorted(saved(fileops)) == sorted([path_for('alpha'), path_for('beta')])


def test_keeps_identity_out_of_the_history():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'])

    ao3.get_collections(COLLECTIONS_URL)

    written = saved(fileops)[path_for('alpha')]
    assert written['name'] == 'alpha'
    assert written['source'] == COLLECTIONS_URL
    assert written[indexing.LAST_INDEXED] == ao3.indexed_on
    # the versioned part describes the collection, not which file it is
    assert 'name' not in written[indexing.INDEXES][-1]


def test_records_only_work_ids_for_its_items():
    # the works are described by the index, so repeating them here would only go stale
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'])

    ao3.get_collections(COLLECTIONS_URL)

    entry = latest_entry(fileops)
    assert entry['work_ids'] == ['111', '222']
    assert entry['bookmark_ids'] == ['333']


def test_saves_the_metadata_from_both_the_blurb_and_the_profile():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'])

    ao3.get_collections(COLLECTIONS_URL)

    entry = latest_entry(fileops)
    assert entry['title'] == 'Title of alpha'      # blurb
    assert entry['closed'] is True                  # blurb flags
    assert entry['active_since'] == '2024-01-01'    # profile
    assert entry['tags'] == ['A Fandom']            # profile
    assert entry['multifandom'] is True             # derived from the sidebar count


def test_reads_the_parent_as_a_link():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'])

    ao3.get_collections(COLLECTIONS_URL)

    assert latest_entry(fileops)['parent_collection'] == \
        'https://archiveofourown.org/collections/parentcoll'


def test_saves_subcollections_as_links():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'], subcollections=1)

    ao3.get_collections(COLLECTIONS_URL)

    assert latest_entry(fileops)['subcollections'] == \
        ['https://archiveofourown.org/collections/childcoll']


def test_does_not_ask_for_subcollections_when_there_are_none():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'], subcollections=0)

    ao3.get_collections(COLLECTIONS_URL)

    asked = [call.args[0] for call in repo.get_soup.call_args_list]
    assert not any(x.endswith('/alpha/collections') for x in asked)
    assert latest_entry(fileops)['subcollections'] == []

# endregion


# region when things go wrong

def test_keeps_a_collection_whose_profile_fails():
    ao3, repo, fileops = make_ao3()
    pages = pages_for(['alpha'])

    def dispatch(url: str):
        if url.endswith('/profile'): raise ValueError('profile exploded')
        return pages(url)

    repo.get_soup.side_effect = dispatch

    records = ao3.get_collections(COLLECTIONS_URL)

    # the blurb already described it, so it is saved rather than dropped
    assert [r['name'] for r in records] == ['alpha']
    assert latest_entry(fileops)['work_ids'] == ['111', '222']
    assert fileops.write_log.called


def test_keeps_a_collection_whose_items_fail():
    ao3, repo, fileops = make_ao3()
    pages = pages_for(['alpha'])

    def dispatch(url: str):
        if url.endswith('/works'): raise ValueError('works exploded')
        return pages(url)

    repo.get_soup.side_effect = dispatch

    ao3.get_collections(COLLECTIONS_URL)

    entry = latest_entry(fileops)
    assert entry['work_ids'] == []
    # the half that did work is still there
    assert entry['bookmark_ids'] == ['333']


def test_stops_when_cancelled_and_keeps_what_it_saved():
    ao3, repo, fileops = make_ao3()
    cancelled = {'value': False}
    ao3.cancelled = lambda: cancelled['value']
    pages = pages_for(['alpha', 'beta'])

    def dispatch(url: str):
        if url.endswith('/beta/profile'): cancelled['value'] = True
        return pages(url)

    repo.get_soup.side_effect = dispatch

    records = ao3.get_collections(COLLECTIONS_URL)

    assert [r['name'] for r in records] == ['alpha']
    assert list(saved(fileops)) == [path_for('alpha')]


def test_rejects_a_link_that_is_not_ao3():
    ao3, repo, _ = make_ao3()

    with pytest.raises(exceptions.InvalidLinkException):
        ao3.get_collections('https://example.com/collections')

    repo.get_soup.assert_not_called()

# endregion


# region history

def test_adds_a_reading_only_when_the_collection_changed():
    ao3, repo, fileops = make_ao3()
    repo.get_soup.side_effect = pages_for(['alpha'])

    ao3.get_collections(COLLECTIONS_URL)
    first = saved(fileops)[path_for('alpha')]

    # feed that back as what is already on disk, and crawl an unchanged collection again
    fileops.load_json.return_value = first
    fileops.save_json.reset_mock()
    repo.get_soup.side_effect = pages_for(['alpha'])

    ao3.get_collections(COLLECTIONS_URL)

    written = saved(fileops)[path_for('alpha')]
    assert len(written[indexing.INDEXES]) == 1
    # checked again, so the file says so even though nothing was added
    assert written[indexing.LAST_INDEXED] == ao3.indexed_on

# endregion


# region not re-walking what has not moved

def requested(repo) -> list[str]:
    return [call.args[0] for call in repo.get_soup.call_args_list]


def stored(**fields) -> dict:
    """One collection's file, as an earlier run would have left it on disk."""

    return {
        'name': fields.pop('name', 'alpha'),
        'source': COLLECTIONS_URL,
        indexing.LAST_INDEXED: '2026-01-01T00:00:00+00:00',
        indexing.INDEXES: [{indexing.INDEXED_ON: '2026-01-01T00:00:00+00:00', **fields}],
    }


def crawl_again(previous: dict, subcollections: int = 0):
    """Crawl one collection with `previous` already on disk, and report what was fetched."""

    ao3, repo, fileops = make_ao3()
    fileops.load_json.return_value = previous
    repo.get_soup.side_effect = pages_for(['alpha'], subcollections)

    ao3.get_collections(COLLECTIONS_URL)

    return requested(repo), saved(fileops)[path_for('alpha')]


def test_keeps_the_saved_ids_when_the_counts_have_not_moved():
    # walking a collection's works costs a request per twenty of them, and the profile
    # page already says how many there are - so an unchanged total means no crawl at all
    urls, _ = crawl_again(stored(work_count=2, work_ids=['111', '222'],
                                 bookmark_count=3, bookmark_ids=['333']))

    assert not any(url.endswith('/works') for url in urls)
    assert not any(url.endswith('/bookmarks') for url in urls)
    # the listing and the profile are all that is left
    assert len(urls) == 2


def test_the_kept_ids_are_written_back_rather_than_dropped():
    # ids a crawl of this fixture could not have produced, so the file can only hold them
    # if they were kept rather than fetched
    _, written = crawl_again(stored(work_count=2, work_ids=['777', '888'],
                                    bookmark_count=3, bookmark_ids=['999']))

    assert written[indexing.INDEXES][-1]['work_ids'] == ['777', '888']
    assert written[indexing.INDEXES][-1]['bookmark_ids'] == ['999']


def test_crawls_again_when_the_work_count_has_changed():
    urls, written = crawl_again(stored(work_count=5, work_ids=['111', '222', '333'],
                                       bookmark_count=3, bookmark_ids=['333']))

    assert any(url.endswith('/works') for url in urls)
    # and the fetched ids replace the stale ones
    assert written[indexing.INDEXES][-1]['work_ids'] == ['111', '222']


def test_each_listing_is_decided_on_its_own_count():
    # the works are unchanged but the bookmarked items are not, so only one is refetched
    urls, _ = crawl_again(stored(work_count=2, work_ids=['111', '222'],
                                 bookmark_count=99, bookmark_ids=['333']))

    assert not any(url.endswith('/works') for url in urls)
    assert any(url.endswith('/bookmarks') for url in urls)


def test_crawls_when_there_is_nothing_saved_to_keep():
    urls, _ = crawl_again(None)

    assert any(url.endswith('/works') for url in urls)
    assert any(url.endswith('/bookmarks') for url in urls)


def test_crawls_when_the_saved_list_is_empty():
    # an empty list is what a failed crawl leaves behind, not a collection with no works
    urls, _ = crawl_again(stored(work_count=2, work_ids=[],
                                 bookmark_count=3, bookmark_ids=['333']))

    assert any(url.endswith('/works') for url in urls)


def test_crawls_when_the_saved_file_never_recorded_a_count():
    urls, _ = crawl_again(stored(work_ids=['111', '222'], bookmark_ids=['333']))

    assert any(url.endswith('/works') for url in urls)


def test_keeps_the_saved_subcollections_when_their_count_has_not_moved():
    subs = ['https://archiveofourown.org/collections/childcoll']
    urls, written = crawl_again(
        stored(work_count=2, work_ids=['111', '222'], bookmark_count=3,
               bookmark_ids=['333'], subcollection_count=2, subcollections=subs),
        subcollections=2)

    assert not any(url.endswith('/alpha/collections') for url in urls)
    assert written[indexing.INDEXES][-1]['subcollections'] == subs


def test_crawls_the_subcollections_when_their_count_has_moved():
    urls, _ = crawl_again(
        stored(work_count=2, work_ids=['111', '222'], bookmark_count=3, bookmark_ids=['333'],
               subcollection_count=7,
               subcollections=['https://archiveofourown.org/collections/old']),
        subcollections=2)

    assert any(url.endswith('/alpha/collections') for url in urls)

# endregion
