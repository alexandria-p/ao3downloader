import os
import shutil
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock

import mobi
import pytest
from bs4 import BeautifulSoup, Tag

import ao3downloader.parse_soup as parse_soup
from ao3downloader import strings

from test.conftest import ebook_fixtures


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')
EBOOK_DIR = os.path.join(FIXTURES_DIR, 'ebook')


def _ids(paths):
    return [os.path.basename(p) for p in paths]


@contextmanager
def _extracted_mobi_soup(path: str):
    """Context manager that extracts a mobi and yields its html as BeautifulSoup."""
    tempdir, filepath = mobi.extract(path)
    try:
        with open(filepath, encoding='utf-8') as f:
            yield BeautifulSoup(f, 'html.parser')
    finally:
        shutil.rmtree(tempdir)


def _load_ebook_html(path: str) -> BeautifulSoup:
    with open(path, encoding='utf-8') as f:
        return BeautifulSoup(f, 'html.parser')


def test_get_work_urls(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    work_urls = parse_soup.get_work_urls(soup)
    assert work_urls == snapshot


def test_get_series_urls_bookmarks(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    series_urls = parse_soup.get_series_urls(soup, False)
    assert series_urls == snapshot


def test_get_series_urls_all(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    series_urls = parse_soup.get_series_urls(soup, True)
    assert series_urls == snapshot


def test_is_locked_true(fixture_soup):
    soup = fixture_soup('lockedWorkLoggedOut')
    assert parse_soup.is_locked(soup) == True


def test_is_locked_false(fixture_soup):
    soup = fixture_soup('lockedWorkLoggedIn')
    assert parse_soup.is_locked(soup) == False


def test_is_deleted_true(fixture_soup):
    soup = fixture_soup('deletedWork')
    assert parse_soup.is_deleted(soup) == True


def test_is_deleted_false(fixture_soup):
    soup = fixture_soup('unlockedWork')
    assert parse_soup.is_deleted(soup) == False


def test_is_explicit_true(fixture_soup):
    soup = fixture_soup('explicitWorkLoggedOut')
    assert parse_soup.is_explicit(soup) == True


def test_is_explicit_false(fixture_soup):
    soup = fixture_soup('explicitWorkLoggedIn')
    assert parse_soup.is_explicit(soup) == False


def test_get_title(fixture_soup, snapshot):
    soup = fixture_soup('unlockedWork')
    link = 'https://archiveofourown.org/works/12345678'
    pattern = (
        'id:{worknum} '
        'title:{title} '
        'author:{author} '
        'fandom:{fandom} '
        'pairing:{pairing} '
        'rating:{rating} '
        'warning:{warning} '
        'category:{category} '
        'words:{words} '
        'chapters:{chapters} '
        'language:{language} '
        'published:{published} '
        'updated:{updated} '
        'series_title:{series_title} '
        'series_index:{series_index}'
    )
    assert parse_soup.get_title(soup, link, pattern) == snapshot


def test_get_title_multiple_series(fixture_soup, snapshot):
    soup = fixture_soup('multipleSeries')
    link = 'https://archiveofourown.org/works/12345678'
    pattern = '{series_title} {series_index} {fandom}'
    assert parse_soup.get_title(soup, link, pattern) == snapshot


def test_get_total_pages(fixture_soup, snapshot):
    soup = fixture_soup('bookmarks')
    assert parse_soup.get_total_pages(soup) == snapshot


def test_get_total_pages_no_pagination(fixture_soup):
    soup = fixture_soup('unlockedWork')
    assert parse_soup.get_total_pages(soup) is None


def test_get_total_pages_empty_pagination():
    soup = BeautifulSoup('<ol class="pagination"></ol>', 'html.parser')
    assert parse_soup.get_total_pages(soup) is None


def test_get_total_pages_only_prev_next():
    soup = BeautifulSoup(
        '<ol class="pagination">'
        '<li><a rel="previous">← Previous</a></li>'
        '<li><a rel="next">Next →</a></li>'
        '</ol>',
        'html.parser')
    assert parse_soup.get_total_pages(soup) is None


def test_get_total_pages_single_page():
    soup = BeautifulSoup(
        '<ol class="pagination">'
        '<li><em class="current">1</em></li>'
        '</ol>',
        'html.parser')
    assert parse_soup.get_total_pages(soup) == 1


# region get_login_token

def test_get_login_token_extracts_value_from_real_login_page(fixture_soup):
    soup = fixture_soup('lockedWorkLoggedOut')

    token = parse_soup.get_login_token(soup)

    # token is a non-empty string; exact value rotates when fixtures are refreshed
    assert isinstance(token, str)
    assert token
    assert not token.isspace()


def test_get_login_token_raises_when_form_missing():
    soup = BeautifulSoup('<html><head><title>A page</title></head></html>', 'html.parser')

    with pytest.raises(Exception, match='A page'):
        parse_soup.get_login_token(soup)


def test_get_login_token_raises_when_token_field_missing():
    soup = BeautifulSoup('<form id="new_user"></form>', 'html.parser')

    with pytest.raises(Exception):
        parse_soup.get_login_token(soup)


def test_get_login_token_raises_when_token_value_empty():
    soup = BeautifulSoup(
        '<form id="new_user">'
        '<input name="authenticity_token" value=""/>'
        '</form>', 'html.parser')

    with pytest.raises(Exception):
        parse_soup.get_login_token(soup)

# endregion


# region get_mark_read_token

def test_get_mark_read_token_returns_value_from_marked_for_later_page(fixture_soup):
    soup = fixture_soup('markedForLater')

    token = parse_soup.get_mark_read_token(soup)

    assert isinstance(token, str)
    assert token
    assert not token.isspace()


def test_get_mark_read_token_returns_none_when_actions_missing():
    soup = BeautifulSoup('<html></html>', 'html.parser')
    assert parse_soup.get_mark_read_token(soup) is None


def test_get_mark_read_token_returns_none_when_mark_li_missing():
    soup = BeautifulSoup(
        '<ul class="work navigation actions"></ul>', 'html.parser')
    assert parse_soup.get_mark_read_token(soup) is None


def test_get_mark_read_token_returns_none_when_form_missing():
    soup = BeautifulSoup(
        '<ul class="work navigation actions"><li class="mark"></li></ul>',
        'html.parser')
    assert parse_soup.get_mark_read_token(soup) is None

# endregion


# region get_image_links

def test_get_image_links_extracts_src_from_workskin(fixture_soup):
    # all locked works have 'lockblue' relative img link
    # relative links will be stripped out later by the 
    # download logic, but the soup logic should return them
    soup = fixture_soup('lockedWorkLoggedIn')

    links = parse_soup.get_image_links(soup)

    assert links
    assert all(isinstance(href, str) and href for href in links)


def test_get_image_links_skips_img_without_src():
    soup = BeautifulSoup(
        '<div id="workskin"><img src="a.png"/><img/></div>', 'html.parser')
    assert parse_soup.get_image_links(soup) == ['a.png']


def test_get_image_links_returns_empty_when_no_workskin(fixture_soup):
    soup = fixture_soup('bookmarks')
    assert parse_soup.get_image_links(soup) == []


def test_get_image_links_returns_empty_when_workskin_has_no_images(fixture_soup):
    soup = fixture_soup('unlockedWork')
    assert parse_soup.get_image_links(soup) == []

# endregion


# region has_custom_skin

def test_has_custom_skin_true(fixture_soup):
    assert parse_soup.has_custom_skin(fixture_soup('unlockedWork')) is True


def test_has_custom_skin_false(fixture_soup):
    assert parse_soup.has_custom_skin(fixture_soup('unlockedWorkNoSkin')) is False

# endregion


# region work metadata

def _list_metadata(fixture_soup, fixture: str, worknum: str) -> dict:
    soup = fixture_soup(fixture)
    return parse_soup.get_work_metadata_from_list(soup, f'https://archiveofourown.org/works/{worknum}')


def _assert_reading_history_format(result: dict) -> None:
    # last_visited and times_visited change whenever the fixtures are refreshed,
    # so assert only that they are a valid AO3 date and a number
    datetime.strptime(result['last_visited'], '%d %b %Y')
    assert result['times_visited'].isdigit()


def _assert_bookmark_date_format(result: dict) -> None:
    # ao3 renders the bookmark date inside a fragment cache that is not keyed
    # on time zone, so the displayed day can shift when the cache regenerates -
    # assert only that it is a valid AO3 date
    datetime.strptime(result['date_bookmarked'], '%d %b %Y')


def test_get_work_metadata_from_work_returns_expected_keys(fixture_soup, snapshot):
    soup = fixture_soup('unlockedWork')
    link = 'https://archiveofourown.org/works/12345678'

    metadata = parse_soup.get_work_metadata_from_work(soup, link)

    assert metadata == snapshot


def test_get_work_metadata_from_list_returns_error_field_on_malformed_blurb():
    # no <li class="work-N"> present — blurb is None so .find will raise
    soup = BeautifulSoup('<html></html>', 'html.parser')

    result = parse_soup.get_work_metadata_from_list(soup, 'https://archiveofourown.org/works/1')

    assert 'error' in result


def test_get_work_metadata_from_list_does_not_leak_from_other_blurbs(fixture_soup):
    # bookmarks.html contains many works; metadata must come from the requested
    # blurb only, not from tags collected across the whole index page. this blurb
    # has no series, bookmarker's tags, or notes while its neighbors have all three.
    result = _list_metadata(fixture_soup, 'bookmarks', '66326125')

    assert 'error' not in result
    assert result['title'] == 'Being An Account of An Abduction, and Its Aftermath'
    assert result['fandoms'] == ['Final Fantasy XIV']
    assert result['relationships'] == ['Honoroit Banlardois/Emmanellain de Fortemps']
    assert result['characters'] == ['Emmanellain de Fortemps', 'Honoroit Banlardois']
    # Tags that belong to other bookmarks in the fixture must NOT leak in.
    assert 'Pon Farr' not in result['tags']
    assert 'Mind Meld' not in result['tags']
    assert result['series'] == []
    assert result['updated'] == '09 Jun 2025'
    _assert_bookmark_date_format(result)
    assert result['bookmarker_tags'] == []
    assert result['bookmarker_notes'] == ''
    # bookmark listings have no reading history data
    assert result['last_visited'] == ''
    assert result['times_visited'] == ''


def test_get_work_metadata_from_list_series_and_bookmarker_tags(fixture_soup):
    result = _list_metadata(fixture_soup, 'bookmarks', '34816549')

    assert result['series'] == ['Part 1 of MXTX - Retellings', 'Part 1 of No Paths Are Bound + Extras']
    assert result['updated'] == '08 Sep 2022'
    _assert_bookmark_date_format(result)
    assert result['bookmarker_tags'] == ['long work']
    assert result['bookmarker_notes'] == ''


def test_get_work_metadata_from_list_bookmarker_notes(fixture_soup):
    result = _list_metadata(fixture_soup, 'bookmarks', '42461841')

    assert result['bookmarker_notes'].strip() == '<p>This bookmark has a note!</p>'
    assert result['bookmarker_tags'] == []
    assert result['updated'] == '18 Oct 2022'
    _assert_bookmark_date_format(result)


def test_get_work_metadata_from_list_marked_for_later(fixture_soup):
    result = _list_metadata(fixture_soup, 'markedForLaterList', '66326125')

    _assert_reading_history_format(result)
    assert result['updated'] == '09 Jun 2025'
    assert result['series'] == []
    # reading history listings have no bookmark data
    assert result['date_bookmarked'] == ''
    assert result['bookmarker_tags'] == []
    assert result['bookmarker_notes'] == ''


def test_get_work_metadata_from_list_marked_for_later_does_not_leak_from_other_blurbs(fixture_soup):
    result = _list_metadata(fixture_soup, 'markedForLaterList', '334557')

    assert result['series'] == ["Part 1 of Watches 'Verse"]
    _assert_reading_history_format(result)
    assert result['updated'] == '06 Feb 2012'


@pytest.mark.parametrize('fixture,worknum', [
    ('bookmarks', '66326125'),
    ('bookmarks', '34816549'),
    ('markedForLaterList', '334557'),
])
def test_get_work_metadata_from_list_returns_same_keys_for_all_listing_types(fixture_soup, fixture, worknum):
    # the csv column headers are derived from these keys, so they must be
    # identical for every work regardless of listing type
    result = _list_metadata(fixture_soup, fixture, worknum)

    assert list(result.keys()) == [
        'title', 'author', 'summary', 'fandoms', 'warnings', 'characters',
        'relationships', 'tags', 'words', 'rating', 'chapters', 'categories',
        'complete', 'series', 'updated', 'date_bookmarked', 'bookmarker_tags',
        'bookmarker_notes', 'last_visited', 'times_visited']


def test_get_work_metadata_from_list_plain_listing_sets_empty_optional_fields():
    # plain listings (search results, tag pages) have no bookmark or reading history data
    html = (
        '<li class="work blurb group work-99" id="work_99">'
        '<div class="header module">'
        '<h4 class="heading"><a href="/works/99">Some Work</a></h4>'
        '<p class="datetime">01 Jan 2020</p>'
        '</div></li>')
    soup = BeautifulSoup(html, 'html.parser')

    result = parse_soup.get_work_metadata_from_list(soup, 'https://archiveofourown.org/works/99')

    assert 'error' not in result
    assert result['updated'] == '01 Jan 2020'
    assert result['series'] == []
    assert result['date_bookmarked'] == ''
    assert result['bookmarker_tags'] == []
    assert result['bookmarker_notes'] == ''
    assert result['last_visited'] == ''
    assert result['times_visited'] == ''

# endregion


# region blurb metadata (json export)

# a bookmark blurb exercising the fields that no fixture covers: a private rec, a
# work in progress, collections, multi-paragraph notes, and a missing comment count
PRIVATE_REC_BLURB = (
    '<ol class="bookmark index group">'
    '<li id="bookmark_1" class="bookmark blurb group work-99 user-1">'
    '<p class="status" title="3 Bookmarks">'
    '<a class="help symbol question modal"><span class="private" title="Private Bookmark">'
    '<span class="text">Private Bookmark</span></span></a>'
    '<a class="help symbol question modal"><span class="rec" title="Rec">'
    '<span class="text">Rec</span></span></a>'
    '</p>'
    '<div class="header module">'
    '<h4 class="heading"><a href="/works/99">A WIP</a> by '
    '<a href="/users/x/pseuds/x" rel="author">Writer</a></h4>'
    '<p class="datetime">01 Jan 2024</p>'
    '</div>'
    '<dl class="stats">'
    '<dt class="words">Words:</dt><dd class="words">1,234</dd>'
    '<dt class="chapters">Chapters:</dt>'
    '<dd class="chapters"><a href="/works/99/chapters/1">3</a>/?</dd>'
    '<dt class="kudos">Kudos:</dt><dd class="kudos"><a>7</a></dd>'
    '</dl>'
    '<div class="own user module group">'
    '<h5 class="byline heading">Bookmarked by <a href="/users/me">me</a></h5>'
    '<p class="datetime">02 Feb 2025</p>'
    '<h6 class="landmark heading">Bookmarker\'s Notes</h6>'
    '<blockquote class="userstuff notes"><p>line one</p><p>line two</p></blockquote>'
    '<h6 class="meta heading">Bookmarker\'s Tags:</h6>'
    '<ul class="meta tags commas"><li><a class="tag" href="/tags/fav/bookmarks">fav</a></li></ul>'
    '<h6 class="landmark heading">Bookmarker\'s Collections</h6>'
    '<ul class="meta commas">'
    '<li><a href="/collections/my_faves">My Faves</a></li>'
    '<li><a href="/collections/reread">Reread Pile</a></li>'
    '</ul>'
    '</div></li></ol>')


def _blurb(html: str) -> Tag:
    return parse_soup.get_blurbs(BeautifulSoup(html, 'html.parser'))[0]


def _blurb_metadata(fixture_soup, fixture: str, worknum: str) -> dict:
    soup = fixture_soup(fixture)
    blurb = next(b for b in parse_soup.get_blurbs(soup)
                 if parse_soup.get_blurb_work_number(b) == worknum)
    return parse_soup.get_blurb_metadata(blurb)


def test_get_blurbs_returns_every_blurb_on_the_page(fixture_soup):
    soup = fixture_soup('bookmarks')

    blurbs = parse_soup.get_blurbs(soup)

    # the fixture holds 19 bookmarked works plus one bookmarked series
    assert len(blurbs) == 20
    assert all(isinstance(x, Tag) for x in blurbs)


def test_get_blurbs_falls_back_when_index_container_is_missing():
    # the ol wrapper is the fast path; a blurb outside one must still be found
    html = '<div><li class="work blurb group work-99"></li></div>'

    assert len(parse_soup.get_blurbs(BeautifulSoup(html, 'html.parser'))) == 1


def test_get_blurb_work_number_skips_non_work_bookmarks(fixture_soup):
    soup = fixture_soup('bookmarks')

    numbers = [parse_soup.get_blurb_work_number(b) for b in parse_soup.get_blurbs(soup)]

    # the bookmarked series has no work number, so it is skipped rather than exported
    assert numbers.count(None) == 1
    assert '34816549' in numbers


def test_get_blurb_work_number_falls_back_to_the_title_link():
    # plain work listings don't always carry the work number in the class list
    html = '<li class="work blurb group"><h4 class="heading"><a href="/works/77">T</a></h4></li>'

    assert parse_soup.get_blurb_work_number(_blurb(html)) == '77'


def test_get_blurb_work_number_ignores_external_works():
    html = ('<li class="bookmark blurb group"><h4 class="heading">'
            '<a href="/external_works/123">Elsewhere</a></h4></li>')

    assert parse_soup.get_blurb_work_number(_blurb(html)) is None


def test_get_blurb_metadata_reads_every_exported_field(fixture_soup):
    result = _blurb_metadata(fixture_soup, 'bookmarks', '34816549')

    assert 'error' not in result
    assert result['id'] == '34816549'
    assert result['link'] == 'https://archiveofourown.org/works/34816549'
    assert result['title'] == 'No Paths Are Bound'
    assert result['authors'] == ['Cataclysmic_Calamity']
    assert result['date_updated'] == '08 Sep 2022'
    assert result['fandoms'] == ['天官赐福 - 墨香铜臭 | Tiān Guān Cì Fú - Mòxiāng Tóngxiù']
    assert result['warnings'] == ['Graphic Depictions Of Violence']
    assert result['tags']['rating'] == 'Explicit'
    assert result['tags']['categories'] == ['M/M']
    assert 'Hua Cheng/Xie Lian (Tian Guan Ci Fu)' in result['tags']['relationships']
    assert 'Xie Lian (Tian Guan Ci Fu)' in result['tags']['characters']
    assert 'Hurt/Comfort' in result['tags']['additional']
    # the summary is a multi-paragraph blockquote; paragraph breaks survive as newlines
    assert result['summary']
    assert '\n' in result['summary']
    assert '<p>' not in result['summary']
    assert result['words'] == 1158737
    assert result['chapters_published'] == 152
    assert result['chapters_total'] == 152
    assert result['comments'] == 11925
    assert result['kudos'] == 36317
    assert result['bookmarks'] == 8141
    assert result['hits'] == 2053077
    assert result['bookmark_tags'] == ['long work']
    _assert_bookmark_date_format(result)
    # the publication date is not on a listing page, so it starts out unset
    assert result['date_created'] is None


def test_get_blurb_metadata_does_not_leak_from_other_blurbs(fixture_soup):
    # this bookmark has no notes or bookmarker's tags while its neighbors do
    result = _blurb_metadata(fixture_soup, 'bookmarks', '66326125')

    assert 'error' not in result
    assert result['title'] == 'Being An Account of An Abduction, and Its Aftermath'
    assert result['fandoms'] == ['Final Fantasy XIV']
    assert result['bookmark_tags'] == []
    assert result['bookmark_notes'] == ''
    assert result['bookmark_collections'] == []
    assert 'Pon Farr' not in result['tags']['additional']


def test_get_blurb_metadata_reads_bookmarker_notes(fixture_soup):
    result = _blurb_metadata(fixture_soup, 'bookmarks', '42461841')

    assert result['bookmark_notes'] == 'This bookmark has a note!'


def test_get_blurb_metadata_reads_private_rec_and_collections():
    result = parse_soup.get_blurb_metadata(_blurb(PRIVATE_REC_BLURB))

    assert 'error' not in result
    assert result['bookmark_private'] is True
    assert result['bookmark_rec'] is True
    assert result['bookmark_collections'] == ['My Faves', 'Reread Pile']
    assert result['bookmark_tags'] == ['fav']
    assert result['bookmark_notes'] == 'line one\nline two'
    assert result['date_bookmarked'] == '02 Feb 2025'


def test_get_blurb_metadata_reads_counts_as_numbers():
    result = parse_soup.get_blurb_metadata(_blurb(PRIVATE_REC_BLURB))

    assert result['words'] == 1234
    assert result['kudos'] == 7
    assert result['chapters_published'] == 3
    # ao3 shows '?' as the total for a work in progress
    assert result['chapters_total'] is None
    # ao3 omits a stat entirely when it is zero, which is not the same as a count of zero
    assert result['comments'] is None
    assert result['hits'] is None


def test_get_blurb_metadata_keeps_sentences_with_inline_markup_intact():
    # splitting on every string node would break this into three lines
    html = ('<li class="work blurb group work-99">'
            '<blockquote class="userstuff summary">'
            '<p>It <em>is</em> the first time.</p>'
            '<p>Second paragraph.</p>'
            '</blockquote></li>')

    result = parse_soup.get_blurb_metadata(_blurb(html))

    assert result['summary'] == 'It is the first time.\nSecond paragraph.'


def test_get_blurb_metadata_breaks_summary_on_line_breaks():
    html = ('<li class="work blurb group work-99">'
            '<blockquote class="userstuff summary"><p>one<br/>two</p></blockquote></li>')

    result = parse_soup.get_blurb_metadata(_blurb(html))

    assert result['summary'] == 'one\ntwo'


def test_get_blurb_metadata_reads_a_summary_with_no_paragraph_markup():
    html = ('<li class="work blurb group work-99">'
            '<blockquote class="userstuff summary">bare <b>text</b></blockquote></li>')

    result = parse_soup.get_blurb_metadata(_blurb(html))

    assert result['summary'] == 'bare text'


def test_get_blurb_metadata_keeps_notes_with_inline_markup_intact():
    html = ('<li class="bookmark blurb group work-99"><div class="user module group">'
            '<blockquote class="userstuff notes"><p>Really <i>love</i> this one.</p></blockquote>'
            '</div></li>')

    result = parse_soup.get_blurb_metadata(_blurb(html))

    assert result['bookmark_notes'] == 'Really love this one.'


def test_get_blurb_metadata_defaults_to_anonymous_without_a_byline():
    html = ('<li class="work blurb group work-99">'
            '<h4 class="heading"><a href="/works/99">Untitled</a></h4></li>')

    result = parse_soup.get_blurb_metadata(_blurb(html))

    assert result['authors'] == ['Anonymous']


def test_get_blurb_metadata_plain_listing_has_empty_bookmark_fields():
    # search results and series pages have no bookmarker section at all
    html = ('<li class="work blurb group work-99">'
            '<div class="header module">'
            '<h4 class="heading"><a href="/works/99">Some Work</a></h4>'
            '<p class="datetime">01 Jan 2020</p></div></li>')

    result = parse_soup.get_blurb_metadata(_blurb(html))

    assert 'error' not in result
    assert result['date_updated'] == '01 Jan 2020'
    assert result['date_bookmarked'] == ''
    assert result['bookmark_notes'] == ''
    assert result['bookmark_tags'] == []
    assert result['bookmark_collections'] == []
    assert result['bookmark_private'] is False
    assert result['bookmark_rec'] is False


def test_get_blurb_metadata_returns_error_field_on_malformed_blurb():
    blurb = Tag(name='li')
    blurb.select_one = MagicMock(side_effect=ValueError('boom'))

    result = parse_soup.get_blurb_metadata(blurb)

    assert 'error' in result


def test_has_bookmark_symbol_matches_on_title_when_class_changes():
    # ao3 could rename the css class; the title must keep the flag from silently going false
    html = '<p class="status"><span class="renamed" title="Private Bookmark"></span></p>'
    status = BeautifulSoup(html, 'html.parser').select_one('p.status')

    assert parse_soup.has_bookmark_symbol(status, 'private', 'Private Bookmark') is True
    assert parse_soup.has_bookmark_symbol(status, 'rec', 'Rec') is False
    assert parse_soup.has_bookmark_symbol(None, 'private', 'Private Bookmark') is False

# endregion


# region is_hidden

def test_is_hidden_true(fixture_soup):
    assert parse_soup.is_hidden(fixture_soup('hiddenWork')) is True


def test_is_hidden_false(fixture_soup):
    assert parse_soup.is_hidden(fixture_soup('unlockedWork')) is False

# endregion


# region HTML format helpers

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_get_work_link_html_on_real_fixture(path):
    link = parse_soup.get_work_link_html(_load_ebook_html(path))

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_html_returns_none_when_not_two_links():
    html = (
        '<div id="preface">'
        '<p class="message">'
        '<a href="https://archiveofourown.org/works/42">only</a>'
        '</p></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_work_link_html(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_get_stats_html_on_real_fixture(path):
    stats = parse_soup.get_stats_html(_load_ebook_html(path))

    assert stats is not None
    assert 'Chapters:' in stats


def test_get_stats_html_returns_none_when_not_found():
    html = (
        '<div id="preface"><div class="meta"><dl class="tags">'
        '<dd>Published: 2024</dd>'
        '</dl></div></div>'
    )
    soup = BeautifulSoup(html, 'html.parser')

    assert parse_soup.get_stats_html(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.html'),
                         ids=_ids(ebook_fixtures('334557', '.html')))
def test_get_series_html_on_work_in_series(path):
    series = parse_soup.get_series_html(_load_ebook_html(path))

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.html'),
                         ids=_ids(ebook_fixtures('23009290', '.html')))
def test_get_series_html_returns_empty_on_work_with_no_series(path):
    assert parse_soup.get_series_html(_load_ebook_html(path)) == []

# endregion


# region MOBI format helpers

@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_get_work_link_mobi_finds_archiveofourown_works_link(path):
    with _extracted_mobi_soup(path) as soup:
        link = parse_soup.get_work_link_mobi(soup)

    assert link is not None
    assert 'archiveofourown.org/works/' in link


def test_get_work_link_mobi_returns_none_when_no_match():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_work_link_mobi(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_get_stats_mobi_finds_blockquote_chapters(path):
    with _extracted_mobi_soup(path) as soup:
        stats = parse_soup.get_stats_mobi(soup)

    assert stats is not None
    assert 'Chapters:' in stats


def test_get_stats_mobi_returns_none_when_missing():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_stats_mobi(soup) is None


@pytest.mark.parametrize('path', ebook_fixtures('334557', '.mobi'),
                         ids=_ids(ebook_fixtures('334557', '.mobi')))
def test_get_series_mobi_returns_series_from_work_in_series(path):
    with _extracted_mobi_soup(path) as soup:
        series = parse_soup.get_series_mobi(soup)

    assert series
    assert all('archiveofourown.org/series/' in s for s in series)


@pytest.mark.parametrize('path', ebook_fixtures('23009290', '.mobi'),
                         ids=_ids(ebook_fixtures('23009290', '.mobi')))
def test_get_series_mobi_returns_empty_when_work_has_no_series(path):
    # mobiTest.mobi is of a solo work with no series
    with _extracted_mobi_soup(path) as soup:
        assert parse_soup.get_series_mobi(soup) == []


def test_get_series_mobi_returns_empty_when_label_missing():
    soup = BeautifulSoup('<html><body></body></html>', 'html.parser')
    assert parse_soup.get_series_mobi(soup) == []

# endregion
