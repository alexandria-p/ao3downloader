"""Tests for the collection parsing in source_code.parse_soup.

The fixtures are real ao3 pages: a user's collections listing, and three profiles chosen
to cover a plain tagged collection, a gift exchange, and a prompt meme.
"""

import pytest
from bs4 import BeautifulSoup

from source_code import parse_soup


@pytest.fixture
def listing(fixture_soup):
    return fixture_soup('collections')


@pytest.fixture
def tagged(fixture_soup):
    return fixture_soup('collectionProfileTagged')


@pytest.fixture
def exchange(fixture_soup):
    return fixture_soup('collectionProfileExchange')


@pytest.fixture
def prompt_meme(fixture_soup):
    return fixture_soup('collectionProfilePromptMeme')


def blurb_named(listing, name: str):
    for blurb in parse_soup.get_collection_blurbs(listing):
        if parse_soup.get_collection_slug(blurb) == name:
            return blurb
    raise AssertionError(f'no collection named {name} in the fixture')


# region listing

def test_get_collection_blurbs_finds_every_collection(listing):
    assert len(parse_soup.get_collection_blurbs(listing)) == 7


def test_get_collection_slug_reads_the_name_from_the_link(listing):
    blurb = parse_soup.get_collection_blurbs(listing)[0]

    assert parse_soup.get_collection_slug(blurb) == 'Best_of_Hollanov_MS'


def test_get_collection_metadata_reads_the_blurb(listing):
    result = parse_soup.get_collection_metadata(blurb_named(listing, 'DCMK_Works'))

    assert 'error' not in result
    assert result['name'] == 'DCMK_Works'
    assert result['link'] == 'https://archiveofourown.org/collections/DCMK_Works'
    assert result['title']
    assert result['maintainers'] == ['Moonlight_Streak']
    assert result['description']
    assert result['bookmark_count'] == 7


def test_get_collection_flags_splits_the_parenthesised_list(listing):
    blurb = blurb_named(listing, 'Best_of_Hollanov_MS')

    assert parse_soup.get_collection_flags(blurb) == ['Closed', 'Moderated']


def test_get_collection_metadata_derives_the_flags(listing):
    result = parse_soup.get_collection_metadata(blurb_named(listing, 'Best_of_Hollanov_MS'))

    assert result['closed'] is True
    assert result['moderated'] is True
    assert result['unrevealed'] is False
    # nothing in the flag list names a challenge
    assert result['challenge_type'] == 'No Challenge'


def test_get_collection_metadata_notices_an_unrevealed_collection(listing):
    unrevealed = [parse_soup.get_collection_metadata(b)
                  for b in parse_soup.get_collection_blurbs(listing)]

    assert sum(1 for x in unrevealed if x['unrevealed']) == 2


def test_get_collection_metadata_survives_an_unreadable_blurb():
    blurb = BeautifulSoup('<li class="collection blurb"></li>', 'html.parser').select_one('li')

    result = parse_soup.get_collection_metadata(blurb)

    # no slug, but the rest is still filled in rather than raising
    assert result['name'] is None
    assert result['link'] is None

# endregion


# region sidebar

def test_get_collection_sidebar_gathers_every_navigation_block(exchange):
    # ao3 splits the sidebar across several lists; taking the first misses the counts
    labels = [label for label, _ in parse_soup.get_collection_sidebar(exchange)]

    assert 'Parent Collection' in labels
    assert any(x.startswith('Works') for x in labels)
    assert any(x.startswith('Bookmarked Items') for x in labels)


def test_get_collection_sidebar_ignores_the_site_menu(exchange):
    # the site header links to /collections, which is not a collection of its own
    hrefs = [href for _, href in parse_soup.get_collection_sidebar(exchange)]

    assert all('/collections/' in href for href in hrefs)


@pytest.mark.parametrize('label, expected', [
    ('Fandoms (1193)', 1193),
    ('Works (2,707)', 2707),
    ('Subcollections (0)', 0),
    ('Random Items', None),
    ('', None),
])
def test_get_sidebar_count_reads_the_number_in_brackets(label, expected):
    assert parse_soup.get_sidebar_count(label) == expected

# endregion


# region profile

def test_profile_reads_the_meta_list(tagged):
    result = parse_soup.get_collection_profile(tagged)

    assert 'error' not in result
    assert result['active_since'] == '2022-12-27'
    assert len(result['tags']) == 3
    assert result['maintainers'] == ['Moonlight_Streak']


def test_profile_reads_active_since_on_a_challenge(exchange):
    # ao3 puts an html comment inside the first, unclosed <dt>. beautifulsoup counts a
    # comment as a string, so leaving it in makes the label unmatchable.
    assert parse_soup.get_collection_profile(exchange)['active_since'] == '2012-09-21'


def test_profile_reads_the_parent_collection_as_a_link(exchange):
    result = parse_soup.get_collection_profile(exchange)

    assert result['parent_collection'] == 'https://archiveofourown.org/collections/yuletide'


def test_profile_has_no_parent_when_the_collection_is_not_a_child(prompt_meme):
    assert parse_soup.get_collection_profile(prompt_meme)['parent_collection'] is None


def test_profile_reads_subcollections_link_and_count(prompt_meme):
    result = parse_soup.get_collection_profile(prompt_meme)

    assert result['subcollection_count'] == 12
    assert result['subcollections_link'] == \
        'https://archiveofourown.org/collections/TheDisneyKinkMeme/collections'


def test_profile_reads_the_counts_from_the_sidebar(exchange):
    result = parse_soup.get_collection_profile(exchange)

    assert result['fandom_count'] == 1193
    assert result['work_count'] == 2269
    assert result['bookmark_count'] == 49


def test_profile_calls_more_than_one_fandom_multifandom(exchange, tagged):
    assert parse_soup.get_collection_profile(exchange)['multifandom'] is True
    # zero fandoms is not multifandom
    assert parse_soup.get_collection_profile(tagged)['multifandom'] is False


@pytest.mark.parametrize('fixture_name, expected', [
    ('collectionProfileTagged', 'No Challenge'),
    ('collectionProfileExchange', 'Gift Exchange Challenge'),
    ('collectionProfilePromptMeme', 'Prompt Meme Challenge'),
])
def test_profile_tells_the_challenge_types_apart(fixture_soup, fixture_name, expected):
    result = parse_soup.get_collection_profile(fixture_soup(fixture_name))

    assert result['challenge_type'] == expected


def test_profile_survives_a_page_with_no_meta_list():
    soup = BeautifulSoup('<div id="main"></div>', 'html.parser')

    result = parse_soup.get_collection_profile(soup)

    assert result['active_since'] == ''
    assert result['tags'] == []
    assert result['parent_collection'] is None
    assert result['multifandom'] is None

# endregion


# region the header, for a collection indexed by link

def test_the_header_carries_what_a_listing_blurb_would_have_said(tagged):
    # indexing by link has no listing to read, so title, description and flags come off
    # the profile page instead
    result = parse_soup.get_collection_header(tagged)

    assert result['title'] == 'Best of DCMK - Detective Conan & Magic Kaito'
    assert 'curated collection' in result['description']
    assert result['flags'] == ['Closed', 'Moderated']
    assert 'error' not in result


def test_the_header_reads_a_challenge_type_off_the_flags(exchange):
    result = parse_soup.get_collection_header(exchange)

    assert result['title'] == 'Yuletide 2012'
    assert result['challenge_type'] == 'Gift Exchange Challenge'
    assert result['closed'] is True
    assert result['moderated'] is True


def test_the_header_does_not_read_unmoderated_as_moderated(prompt_meme):
    # ao3 writes both words, and a substring test would get this exactly backwards
    result = parse_soup.get_collection_header(prompt_meme)

    assert 'Unmoderated' in result['flags']
    assert result['moderated'] is False
    assert result['challenge_type'] == 'Prompt Meme Challenge'


def test_the_header_says_so_rather_than_raising_when_there_is_nothing_to_read():
    result = parse_soup.get_collection_header(BeautifulSoup('<div></div>', 'html.parser'))

    assert result['title'] == ''
    assert result['description'] == ''
    assert result['flags'] == []
    assert result['challenge_type'] == 'No Challenge'


def test_the_header_and_the_blurb_agree_about_a_collection_in_both(listing, tagged):
    # the same collection read two ways should not look like two different collections
    blurb = blurb_named(listing, 'DCMK_Works')
    from_blurb = parse_soup.get_collection_metadata(blurb)
    from_header = parse_soup.get_collection_header(tagged)

    assert from_header['title'] == from_blurb['title']
    assert from_header['flags'] == from_blurb['flags']
    assert from_header['challenge_type'] == from_blurb['challenge_type']

# endregion
