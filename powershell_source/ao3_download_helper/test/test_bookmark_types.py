"""Bookmark types: individual works, external works and bookmarked series.

Checked against real ao3 markup: `bookmarks.html` holds a series bookmark among its works,
`seriesPage.html` is a series' own page (its works in listing blurbs), and
`externalWork.html` carries an external work - whose title, on the live site, links to an
ao3 address, which is why its kind is read from its class and never from that link.
"""

import json
import os
from unittest.mock import MagicMock

import pytest
from bs4 import BeautifulSoup

from source_code import indexing, parse_soup, strings
from source_code.actions import shared
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
LISTING = 'https://archiveofourown.org/users/Someone/bookmarks'
SERIES = '15213'
SERIES_LINK = f'https://archiveofourown.org/series/{SERIES}'
SERIES_WORKS = ['33671446', '33936370', '34644055', '91688086', '91707641']


def soup(name: str) -> BeautifulSoup:
    with open(os.path.join(FIXTURES, name + '.html'), encoding='utf-8') as f:
        return BeautifulSoup(f.read(), 'html.parser')


def blurb_of(name: str, kind: str) -> tuple:
    for blurb in parse_soup.get_blurbs(soup(name)):
        found, number = parse_soup.get_blurb_kind(blurb)
        if found == kind: return blurb, number
    raise AssertionError(f'no {kind} blurb in {name}')


# region reading a blurb

def test_a_series_bookmark_is_read_as_a_series():
    blurb, number = blurb_of('bookmarks', parse_soup.BLURB_SERIES)
    assert number == SERIES
    assert parse_soup.get_blurb_work_number(blurb) is None


def test_an_external_work_is_never_mistaken_for_the_ao3_work_its_title_links_to():
    # its title links to archiveofourown.org/en/works/863 - going by the link would read
    # it as work 863 and try to download that
    blurb, number = blurb_of('externalWork', parse_soup.BLURB_EXTERNAL)
    assert number == '1'
    assert parse_soup.get_blurb_work_number(blurb) is None


def test_works_are_still_works():
    kinds = [parse_soup.get_blurb_kind(b)[0] for b in parse_soup.get_blurbs(soup('bookmarks'))]
    assert kinds.count(parse_soup.BLURB_WORK) == 19
    assert kinds.count(parse_soup.BLURB_SERIES) == 1


def test_a_bookmarked_series_is_described_from_its_blurb():
    blurb, number = blurb_of('bookmarks', parse_soup.BLURB_SERIES)

    series = parse_soup.get_series_bookmark_metadata(blurb, number)

    assert series['id'] == SERIES
    assert series['link'] == SERIES_LINK
    assert series['title'] == "Watches 'Verse"
    assert series['authors'] == ['bendingsignpost']
    assert (series['works'], series['complete']) == (2, False)
    # the bookmark's own fields, as a work's blurb gives them
    assert series['date_bookmarked'] == '18 May 2026'
    assert 'chapters_published' not in series


def test_an_external_work_is_described_with_where_it_really_is():
    blurb, number = blurb_of('externalWork', parse_soup.BLURB_EXTERNAL)

    work = parse_soup.get_external_bookmark_metadata(blurb, number)

    assert work['link'] == 'https://archiveofourown.org/en/works/863'
    assert work['title'] == 'drift'
    # no account to link to: the author is plain text in the heading
    assert work['authors'] == ['Merry']
    assert work['summary'] == 'In which Charlie puts Don to bed.'

# endregion


# region indexing a listing with a series in it

@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()
    return fileops


def an_ao3(fileops: FileOps, pages: dict[str, BeautifulSoup],
           series: bool = False) -> tuple[Ao3, MagicMock]:
    repo = MagicMock(spec=Repository)
    repo.get_soup.side_effect = lambda link: pages[link]
    return Ao3(repo=repo, fileops=fileops, filetypes=['HTML'], pages=None, series=series,
               images=False), repo


def index_and_walk(ao3: Ao3, link: str = LISTING) -> list[dict]:
    """What a run does: index the listing, then walk every series marked while it did."""
    records = ao3.get_metadata(link, False, own_bookmarks=True)
    return records + ao3.walk_marked_series()


def entries(fileops: FileOps, *folders: str) -> dict[str, dict]:
    folder = os.path.join(fileops.downloadfolder, strings.INDEXING_FOLDER_NAME, *folders)
    found = {}
    for name in sorted(os.listdir(folder)):
        if not name.endswith('.json'): continue
        with open(os.path.join(folder, name), encoding='utf-8') as f:
            record = indexing.flatten(json.load(f))
        found[str(record['id'])] = record
    return found


def listing_with(*blurbs) -> BeautifulSoup:
    page = BeautifulSoup('<ol class="bookmark index group"></ol>', 'html.parser')
    for blurb in blurbs: page.ol.append(BeautifulSoup(str(blurb), 'html.parser'))
    return page


def series_blurb():
    blurb, _ = blurb_of('bookmarks', parse_soup.BLURB_SERIES)
    return blurb


def work_blurb(number: str):
    """A work's blurb from the series page, as it would appear in the bookmarks listing."""
    for blurb in parse_soup.get_blurbs(soup('seriesPage')):
        if parse_soup.get_blurb_kind(blurb)[1] == number: return blurb
    raise AssertionError(number)


def test_a_bookmarked_series_gets_its_own_entry_and_its_works_are_indexed(library):
    ao3, repo = an_ao3(library, {LISTING: listing_with(series_blurb()),
                                 SERIES_LINK: soup('seriesPage')})

    records = index_and_walk(ao3)

    series = entries(library, strings.SERIES_INDEX_FOLDER_NAME)[SERIES]
    assert series[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_SERIES
    assert series[strings.BOOKMARKED_FIELD] is True
    assert series[strings.SERIES_WORKS_FIELD] == SERIES_WORKS

    works = entries(library)
    assert sorted(works) == sorted(SERIES_WORKS)
    for work in works.values():
        assert work[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_WORK
        # in the index because of the series, not bookmarked for itself
        assert work[strings.BOOKMARKED_FIELD] is False
        assert work[indexing.FROM_SERIES] == [SERIES]
        assert work['source'] == SERIES_LINK
    # the series' works go on to be downloaded, as the individual works they are; the
    # series' own entry does not - there is nothing to download for it
    assert sorted(r['id'] for r in records) == sorted(SERIES_WORKS)
    # and a series is no longer reported as a bookmark that could not be indexed
    assert ao3.skipped_works == []


def test_a_work_already_indexed_this_run_is_not_read_again_from_a_series(library):
    # bookmarked for itself, and met on the listing before the series
    ao3, repo = an_ao3(library, {LISTING: listing_with(work_blurb('33671446'), series_blurb()),
                                 SERIES_LINK: soup('seriesPage')})

    records = index_and_walk(ao3)

    work = entries(library)['33671446']
    assert work[strings.BOOKMARKED_FIELD] is True
    assert indexing.FROM_SERIES not in work
    assert work['source'] == LISTING
    # indexed once, downloaded once
    assert [r['id'] for r in records].count('33671446') == 1


def test_a_series_work_later_found_in_your_bookmarks_is_marked_bookmarked(library):
    # the series is met first, and the work afterwards on the listing - as a quick scan's
    # second walk would meet it
    later = LISTING + '?sort=updated'
    ao3, repo = an_ao3(library, {LISTING: listing_with(series_blurb()),
                                 later: listing_with(work_blurb('33671446')),
                                 SERIES_LINK: soup('seriesPage')})

    index_and_walk(ao3)
    assert entries(library)['33671446'][strings.BOOKMARKED_FIELD] is False
    ao3.get_metadata(later, False, own_bookmarks=True)

    work = entries(library)['33671446']
    assert work[strings.BOOKMARKED_FIELD] is True
    # and it keeps the series it was found through
    assert work[indexing.FROM_SERIES] == [SERIES]


def test_an_existing_entry_keeps_its_own_bookmark_when_updated_from_a_series(library):
    # indexed on an earlier run, bookmarked with notes - the series page knows none of that
    earlier, _ = an_ao3(library, {LISTING: listing_with(work_blurb('33671446'))})
    earlier.get_metadata(LISTING, False, own_bookmarks=True)
    path = next(p for p in os.listdir(os.path.join(library.downloadfolder, 'indexing'))
                if p.startswith('33671446'))
    full = os.path.join(library.downloadfolder, 'indexing', path)
    with open(full, encoding='utf-8') as f:
        document = json.load(f)
    document[indexing.INDEXES][-1]['bookmark_notes'] = 'my favourite'
    document[indexing.INDEXES][-1]['date_bookmarked'] = '01 Jan 2026'
    with open(full, 'w', encoding='utf-8') as f:
        json.dump(document, f)

    ao3, _ = an_ao3(library, {LISTING: listing_with(series_blurb()),
                              SERIES_LINK: soup('seriesPage')})
    index_and_walk(ao3)

    work = entries(library)['33671446']
    assert work[strings.BOOKMARKED_FIELD] is True
    assert work['bookmark_notes'] == 'my favourite'
    assert work['date_bookmarked'] == '01 Jan 2026'
    assert work['source'] == LISTING
    assert work[indexing.FROM_SERIES] == [SERIES]


def test_a_series_met_twice_in_a_run_is_read_once(library):
    # bookmarked twice, or met by both of a quick scan's walks
    ao3, repo = an_ao3(library, {LISTING: listing_with(series_blurb()),
                                 SERIES_LINK: soup('seriesPage')})

    index_and_walk(ao3)
    index_and_walk(ao3)

    assert [c.args[0] for c in repo.get_soup.call_args_list].count(SERIES_LINK) == 1
    assert entries(library, 'series')[SERIES][strings.SERIES_WORKS_FIELD] == SERIES_WORKS


def test_a_series_that_will_not_read_keeps_the_works_it_had(library):
    first, _ = an_ao3(library, {LISTING: listing_with(series_blurb()),
                                SERIES_LINK: soup('seriesPage')})
    index_and_walk(first)

    pages = {LISTING: listing_with(series_blurb())}
    ao3, repo = an_ao3(library, pages)
    index_and_walk(ao3)

    assert entries(library, 'series')[SERIES][strings.SERIES_WORKS_FIELD] == SERIES_WORKS


def test_an_external_work_gets_its_own_entry_and_is_never_downloaded(library):
    blurb, _ = blurb_of('externalWork', parse_soup.BLURB_EXTERNAL)
    ao3, repo = an_ao3(library, {LISTING: listing_with(blurb)})

    records = index_and_walk(ao3)

    external = entries(library, strings.EXTERNAL_INDEX_FOLDER_NAME)['1']
    assert external[strings.BOOKMARK_TYPE_FIELD] == strings.BOOKMARK_TYPE_EXTERNAL
    assert external['link'] == 'https://archiveofourown.org/en/works/863'
    assert external[strings.BOOKMARKED_FIELD] is True
    assert records == []
    assert ao3.skipped_works == []
    # and nothing that reads indexing/ as works sees it
    assert shared.read_index(library) == []

# endregion


# region the new-bookmarks walk

def test_a_work_only_in_the_index_through_a_series_does_not_stop_the_new_bookmarks_walk(library):
    # it is not one you bookmarked, so the day you do, the walk has to reach it
    ao3, _ = an_ao3(library, {LISTING: listing_with(work_blurb('33936370'), series_blurb()),
                              SERIES_LINK: soup('seriesPage')})
    index_and_walk(ao3)

    known = shared.indexed_work_ids(library)

    assert known == {'33936370'}


def test_the_index_read_as_works_leaves_series_and_external_entries_out(library):
    ao3, _ = an_ao3(library, {LISTING: listing_with(series_blurb()),
                              SERIES_LINK: soup('seriesPage')})
    index_and_walk(ao3)

    assert sorted(x['id'] for x in shared.read_index(library)) == sorted(SERIES_WORKS)

# endregion


# region series marked for walkthrough

def test_a_work_says_which_series_it_is_part_of():
    # checked against real markup: a blurb and a work's own page say it the same way
    blurb = next(b for b in parse_soup.get_blurbs(soup('bookmarks'))
                 if parse_soup.get_blurb_kind(b)[1] == '34816549')
    assert parse_soup.get_series_memberships(blurb) == [
        {'id': '2627935', 'title': 'MXTX - Retellings', 'part': 1},
        {'id': '3108957', 'title': 'No Paths Are Bound + Extras', 'part': 1},
    ]
    page = parse_soup.get_series_memberships(soup('multipleSeries'))
    assert page[0] == {'id': '3078150', 'title': 'AO3 Skins', 'part': 1}


def test_a_series_page_describes_the_series(library):
    header = parse_soup.get_series_page_metadata(soup('seriesPage'), '2577382')
    assert header['title'] == 'After Hours'
    assert header['authors'] == ['woodironbone']
    assert (header['works'], header['complete'], header['words']) == (5, True, 28131)
    assert header['date_updated'] == '2026-09-01'


# the series the saved series page is of - its works name it as their series
PAGE_SERIES = '2577382'
PAGE_SERIES_LINK = f'https://archiveofourown.org/series/{PAGE_SERIES}'


def test_a_work_marks_its_series_only_when_asked(library, capsys):
    # its blurb names the series it is part of
    off, _ = an_ao3(library, {LISTING: listing_with(work_blurb('33671446'))})
    off.get_metadata(LISTING, False, own_bookmarks=True)
    assert off.series_marked == {}

    on, _ = an_ao3(library, {LISTING: listing_with(work_blurb('33671446'))}, series=True)
    on.get_metadata(LISTING, False, own_bookmarks=True)
    assert list(on.series_marked) == [PAGE_SERIES]
    # said in the modal, once
    assert capsys.readouterr().out.count(
        strings.AO3_INFO_SERIES_MARKED.format('After Hours')) == 1


def test_a_series_bookmark_is_marked_whether_or_not_the_option_is_on(library, capsys):
    ao3, _ = an_ao3(library, {LISTING: listing_with(series_blurb())})
    ao3.get_metadata(LISTING, False, own_bookmarks=True)
    assert list(ao3.series_marked) == [SERIES]
    assert strings.AO3_INFO_SERIES_MARKED_BOOKMARK.format("Watches 'Verse") in capsys.readouterr().out
    # marked, not walked: nothing is read from the series until indexing is over
    assert SERIES not in ao3.series_read


def test_the_series_of_a_work_is_walked_like_a_series_bookmark(library):
    ao3, repo = an_ao3(library, {LISTING: listing_with(work_blurb('33671446')),
                                 PAGE_SERIES_LINK: soup('seriesPage')}, series=True)

    records = index_and_walk(ao3)

    # the listing, then the series' one page - the work bookmarked for itself is read off
    # the listing and not again from the series
    assert repo.get_soup.call_count == 2
    works = entries(library)
    assert works['33671446'][strings.BOOKMARKED_FIELD] is True
    for other in SERIES_WORKS[1:]:
        assert works[other][strings.BOOKMARKED_FIELD] is False
        assert works[other][indexing.FROM_SERIES] == [PAGE_SERIES]
    assert sorted(r['id'] for r in records) == sorted(SERIES_WORKS)
    # the series gets an entry of its own, from its page, as not one you bookmarked
    series = entries(library, strings.SERIES_INDEX_FOLDER_NAME)[PAGE_SERIES]
    assert series[strings.BOOKMARKED_FIELD] is False
    assert series['title'] == 'After Hours'
    assert series[strings.SERIES_WORKS_FIELD] == SERIES_WORKS


def test_walking_a_series_marks_no_further_series(library):
    # every work on a series page names the series in hand - walking is not indexing
    ao3, _ = an_ao3(library, {LISTING: listing_with(series_blurb()),
                              SERIES_LINK: soup('seriesPage')}, series=True)
    index_and_walk(ao3)
    assert list(ao3.series_marked) == [SERIES]


def test_a_series_reached_through_a_work_keeps_a_bookmark_an_earlier_run_recorded(library):
    # bookmarked on an earlier run; this run only reaches it through one of its works
    bookmarked = BeautifulSoup(str(series_blurb()).replace(SERIES, PAGE_SERIES),
                               'html.parser').li
    earlier, _ = an_ao3(library, {LISTING: listing_with(bookmarked),
                                  PAGE_SERIES_LINK: soup('seriesPage')})
    index_and_walk(earlier)

    ao3, _ = an_ao3(library, {LISTING: listing_with(work_blurb('33671446')),
                              PAGE_SERIES_LINK: soup('seriesPage')}, series=True)
    index_and_walk(ao3)

    series = entries(library, strings.SERIES_INDEX_FOLDER_NAME)[PAGE_SERIES]
    assert series[strings.BOOKMARKED_FIELD] is True
    assert series['date_bookmarked'] == '18 May 2026'
    # one entry, not a second file named after the page's title
    assert len(entries(library, strings.SERIES_INDEX_FOLDER_NAME)) == 1


def test_a_work_taken_from_the_index_marks_its_series_without_being_read_again(library):
    # a run that skips indexing still knows each work's series from its entry
    ao3, _ = an_ao3(library, {}, series=True)
    ao3.mark_series_of({'id': '1', strings.SERIES_MEMBERSHIP_FIELD: [
        {'id': '42', 'title': 'Stored', 'part': 2}]})
    assert list(ao3.series_marked) == ['42']

# endregion


# region the single-fic run

def test_a_single_fic_replaces_only_itself_and_not_the_rest_of_its_series():
    existing = {'1': {'HTML': {'path': 'works/1 A 2026-01-01.html', 'date': '2026-01-01'}},
                '2': {'HTML': {'path': 'works/2 B 2026-01-01.html', 'date': '2026-01-01'}}}
    records = [{'id': '1', 'link': 'https://archiveofourown.org/works/1', 'date_updated': '2026-01-01'},
               {'id': '2', 'link': 'https://archiveofourown.org/works/2', 'date_updated': '2026-01-01'}]

    plan = shared.plan_downloads(records, existing, ['HTML'],
                                 overwrite={'https://archiveofourown.org/works/1'})

    assert plan['stale'] == ['https://archiveofourown.org/works/1']

# endregion
