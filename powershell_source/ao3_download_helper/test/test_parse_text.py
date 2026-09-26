import datetime
import os

import pytest

import source_code.parse_text as parse_text


# region normalize_path_input

@pytest.mark.parametrize('raw, expected', [
    ('/tmp/fics', '/tmp/fics'),
    ('  /tmp/fics  ', '/tmp/fics'),
    ('"/tmp/fics"', '/tmp/fics'),
    ("'/tmp/fics'", '/tmp/fics'),
    ('"C:\\Users\\foo\\fics"', 'C:\\Users\\foo\\fics'),
    ('  "/tmp/fics"  ', '/tmp/fics'),
    ('"/tmp/fics\'', '"/tmp/fics\''),
    ('"/tmp/fics', '"/tmp/fics'),
    ('/tmp/fics"', '/tmp/fics"'),
    ('', ''),
    ('"', '"'),
])
def testnormalize_path_input(raw: str, expected: str) -> None:
    assert parse_text.normalize_path_input(raw) == expected

# endregion


# region get_valid_filename

def test_get_valid_filename_no_directories():
    filename = ['valid filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'valid filename'


def test_get_valid_filename_one_directory():
    filename = ['valid', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'filename')


def test_get_valid_filename_multiple_directories():
    filename = ['valid', 'directory', 'structure']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'directory', 'structure')


def test_get_valid_filename_one_invalid_directory():
    filename = ['*', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'filename'


def test_get_valid_filename_multiple_invalid_directories():
    filename = ['*', '*', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'filename'


def test_get_valid_filename_valid_and_invalid_directories():
    filename = ['valid', '*', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'filename')


def test_get_valid_filename_empty_directory():
    filename = ['valid', '', 'filename']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('valid', 'filename')


def test_get_valid_filename_empty_string():
    filename = ['']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == ''


def test_get_valid_filename_whitespace():
    filename = ['   ']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == ''


def test_get_valid_filename_invalid_characters():
    filename = ['invalid', 'filename<>:"\|?*.']
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('invalid', 'filename')


def test_get_valid_filename_maximum_length():
    filename = ['a' * 100]
    result = parse_text.get_valid_filename(filename, 50)
    assert result == 'a' * 50


def test_get_valid_filename_multiple_directories_maximum_length():
    filename = ['a' * 100, 'b' * 100]
    result = parse_text.get_valid_filename(filename, 50)
    assert result == os.path.join('a' * 50, 'b' * 50)

# endregion


# region get_pinboard_url

def test_get_pinboard_url_no_date():
    url = parse_text.get_pinboard_url('abc123', None)
    assert url == 'https://api.pinboard.in/v1/posts/all?auth_token=abc123'


def test_get_pinboard_url_pads_single_digit_month_and_day():
    url = parse_text.get_pinboard_url('abc123', datetime.datetime(2025, 3, 5))
    assert 'fromdt=2025-03-05T00:00:00Z' in url
    assert 'auth_token=abc123' in url


def test_get_pinboard_url_four_digit_year():
    url = parse_text.get_pinboard_url('tok', datetime.datetime(1999, 12, 31))
    assert 'fromdt=1999-12-31T00:00:00Z' in url


def test_get_pinboard_url_includes_token():
    url = parse_text.get_pinboard_url('my-secret-token', datetime.datetime(2020, 6, 15))
    assert 'auth_token=my-secret-token' in url

# endregion


# region get_file_type

@pytest.mark.parametrize('filetype, expected', [
    ('EPUB', '.epub'),
    ('PDF', '.pdf'),
    ('MOBI', '.mobi'),
    ('AZW3', '.azw3'),
    ('HTML', '.html'),
])
def test_get_file_type_lowercases_and_prefixes_dot(filetype, expected):
    assert parse_text.get_file_type(filetype) == expected

# endregion


# region get_work_number

@pytest.mark.parametrize('link, expected', [
    ('https://archiveofourown.org/works/12345', '12345'),
    ('https://archiveofourown.org/works/12345/', '12345'),
    ('https://archiveofourown.org/works/12345/chapters/67890', '12345'),
    ('https://archiveofourown.org/works/12345?view_adult=true', '12345'),
    ('/works/7', '7'),
])
def test_get_work_number_extracts_digits(link, expected):
    assert parse_text.get_work_number(link) == expected


def test_get_work_number_returns_none_when_missing():
    assert parse_text.get_work_number('https://archiveofourown.org/series/123') is None


def test_get_work_number_returns_none_when_no_digits_after():
    assert parse_text.get_work_number('https://archiveofourown.org/works/abc') is None

# endregion


# region get_series_number

@pytest.mark.parametrize('link, expected', [
    ('https://archiveofourown.org/series/789', '789'),
    ('https://archiveofourown.org/series/789/', '789'),
    ('https://archiveofourown.org/series/789?foo=bar', '789'),
])
def test_get_series_number_extracts_digits(link, expected):
    assert parse_text.get_series_number(link) == expected


def test_get_series_number_returns_none_for_work_url():
    assert parse_text.get_series_number('https://archiveofourown.org/works/123') is None

# endregion


# region is_work / is_series

def test_is_work_true():
    assert parse_text.is_work('https://archiveofourown.org/works/123') is True


def test_is_work_false():
    assert parse_text.is_work('https://archiveofourown.org/series/123') is False


def test_is_series_true():
    assert parse_text.is_series('https://archiveofourown.org/series/123') is True


def test_is_series_false():
    assert parse_text.is_series('https://archiveofourown.org/works/123') is False

# endregion


# region is_subscriptions

@pytest.mark.parametrize('link', [
    'https://archiveofourown.org/users/SomeName/subscriptions',
    'https://archiveofourown.org/users/somename/subscriptions', # casing is irrelevant
    'https://archiveofourown.org/users/SomeName/subscriptions?type=series', # query string
    'https://archiveofourown.org/users/SomeName/subscriptions/', # trailing slash
])
def test_is_subscriptions_true(link):
    assert parse_text.is_subscriptions(link) is True


@pytest.mark.parametrize('link', [
    'https://archiveofourown.org/users/SomeName/bookmarks',
    'https://archiveofourown.org/works/123',
])
def test_is_subscriptions_false(link):
    assert parse_text.is_subscriptions(link) is False

# endregion


# region get_digits_after

def test_get_digits_after_stops_at_non_digit():
    assert parse_text.get_digits_after('/works/', '/works/42abc') == '42'


def test_get_digits_after_returns_none_when_test_absent():
    assert parse_text.get_digits_after('/works/', '/series/42') is None


def test_get_digits_after_returns_none_when_no_digits():
    assert parse_text.get_digits_after('/works/', '/works/abc') is None

# endregion


# region get_next_page

def test_get_next_page_adds_querystring_when_none_present():
    assert parse_text.get_next_page('https://example.com/foo') == 'https://example.com/foo?page=2'


def test_get_next_page_appends_to_existing_querystring():
    assert parse_text.get_next_page('https://example.com/foo?a=1') == 'https://example.com/foo?a=1&page=2'


def test_get_next_page_increments_existing_page_param():
    assert parse_text.get_next_page('https://example.com/foo?page=3') == 'https://example.com/foo?page=4'


def test_get_next_page_handles_9_to_10_boundary():
    # Catches a bug where get_num_from_link returns '1' instead of '9' if digit-range
    # extraction is off-by-one; replacing 'page=9' with 'page=10' should not touch 'page=99'.
    assert parse_text.get_next_page('https://example.com/foo?page=9') == 'https://example.com/foo?page=10'


def test_get_next_page_increments_multi_digit_page():
    assert parse_text.get_next_page('https://example.com/foo?page=99') == 'https://example.com/foo?page=100'

# endregion


# region get_page_number

def test_get_page_number_returns_1_when_no_page_param():
    assert parse_text.get_page_number('https://example.com/foo') == 1


def test_get_page_number_reads_existing_param():
    assert parse_text.get_page_number('https://example.com/foo?page=7') == 7


def test_get_page_number_reads_multi_digit():
    assert parse_text.get_page_number('https://example.com/foo?page=123&a=b') == 123

# endregion


# region chapters

def test_get_total_chapters_basic():
    text = 'Chapters: 3/10 Words: 5000'
    index = text.find('/')
    assert parse_text.get_total_chapters(text, index) == '10'


def test_get_current_chapters_basic():
    text = 'Chapters: 3/10 Words: 5000'
    index = text.find('/')
    assert parse_text.get_current_chapters(text, index) == '3'


def test_get_current_chapters_multi_digit():
    text = 'Chapters: 42/100 Words: 5000'
    index = text.find('/')
    assert parse_text.get_current_chapters(text, index) == '42'


def test_get_current_chapters_handles_index_0():
    # No characters before index 0, so we get an empty string back.
    assert parse_text.get_current_chapters('/10', 0) == ''


@pytest.mark.parametrize('text, expected', [
    ('1,158,737', 1158737),
    ('7', 7),
    ('  2,053,077  ', 2053077),
    # ao3 leaves a stat out of the blurb when it is zero, so an absent value stays
    # absent rather than being reported as a count of zero
    ('', None),
    ('Hits:', None),
])
def test_get_count_parses_displayed_stats(text, expected):
    assert parse_text.get_count(text) == expected


@pytest.mark.parametrize('text, expected', [
    ('152/152', (152, 152)),
    ('3/?', (3, None)),
    ('1/1', (1, 1)),
    ('\n            3\n          /?', (3, None)),
    # a listing without a chapter count at all
    ('', (None, None)),
    # no separator: treat the whole thing as the published count
    ('12', (12, None)),
])
def test_get_chapter_counts_splits_published_and_total(text, expected):
    assert parse_text.get_chapter_counts(text) == expected

# endregion


# region reading history

# reproduces the whitespace of the real viewed heading element
VIEWED_HEADING = ('Last visited: 10 Jul 2026\n\n          (Latest version.)'
                  '\n\n          Visited 6 times\n\n          (Marked for Later.)')


def test_get_last_visited_extracts_date():
    assert parse_text.get_last_visited(VIEWED_HEADING) == '10 Jul 2026'


def test_get_last_visited_returns_empty_when_absent():
    assert parse_text.get_last_visited('') == ''


def test_get_times_visited_multiple():
    assert parse_text.get_times_visited(VIEWED_HEADING) == '6'


def test_get_times_visited_once():
    text = 'Last visited: 09 Jul 2026 (Update available.) Visited once (Marked for Later.)'
    assert parse_text.get_times_visited(text) == '1'


def test_get_times_visited_returns_empty_when_absent():
    assert parse_text.get_times_visited('') == ''

# endregion


# region get_payload

def test_get_payload_contains_expected_fields():
    payload = parse_text.get_payload('alice', 'hunter2', 'csrf-token')
    assert payload == {
        'user[login]': 'alice',
        'user[password]': 'hunter2',
        'user[remember_me]': '1',
        'authenticity_token': 'csrf-token',
    }

# endregion


# region get_unsuccessful_downloads

def test_get_unsuccessful_downloads_deduplicates():
    logs = [
        {'link': 'https://a/works/1', 'success': False},
        {'link': 'https://a/works/1', 'success': False},
        {'link': 'https://a/works/2', 'success': False},
    ]
    assert parse_text.get_unsuccessful_downloads(logs) == [
        'https://a/works/1', 'https://a/works/2',
    ]


def test_get_unsuccessful_downloads_ignores_success_entries():
    logs = [
        {'link': 'https://a/works/1', 'success': True},
        {'link': 'https://a/works/2', 'success': False},
    ]
    assert parse_text.get_unsuccessful_downloads(logs) == ['https://a/works/2']


def test_get_unsuccessful_downloads_ignores_entries_without_success_field():
    logs = [
        {'link': 'https://a/works/1'},
        {'link': 'https://a/works/2', 'success': False},
    ]
    assert parse_text.get_unsuccessful_downloads(logs) == ['https://a/works/2']


def test_get_unsuccessful_downloads_empty_list():
    assert parse_text.get_unsuccessful_downloads([]) == []

# endregion


# region the date stamp on a downloaded file

@pytest.mark.parametrize('text,expected', [
    ('14 Dec 2024', '2024-12-14'),          # a listing blurb
    ('2024-12-14', '2024-12-14'),           # a work page's status line
    ('Updated: 2024-12-14', '2024-12-14'),  # ...sometimes with a label on it
    ('14 December 2024', '2024-12-14'),
    ('  14 Dec 2024  ', '2024-12-14'),
])
def test_get_date_stamp_reads_the_dates_ao3_writes(text, expected):
    assert parse_text.get_date_stamp(text) == expected


@pytest.mark.parametrize('text', ['', None, 'not a date', 'sometime', '99 Xyz 2024', 42, {}])
def test_get_date_stamp_gives_nothing_rather_than_a_wrong_date(text):
    # a date is a nicety on a file name and must never be why a download fails
    assert parse_text.get_date_stamp(text) == ''


def test_a_work_page_date_is_rewritten_the_way_a_listing_writes_it():
    # the index keeps one field for this. two passes writing it two ways would rewrite
    # each other forever, each looking like a change
    assert parse_text.get_listing_date('2024-12-14') == '14 Dec 2024'


def test_normalising_a_listing_date_leaves_it_exactly_as_it_was():
    assert parse_text.get_listing_date('14 Dec 2024') == '14 Dec 2024'


def test_normalising_a_date_twice_changes_nothing_the_second_time():
    once = parse_text.get_listing_date('2024-12-14')

    assert parse_text.get_listing_date(once) == once


@pytest.mark.parametrize('text', ['', 'sometime', 'not a date'])
def test_something_that_is_not_a_date_is_kept_rather_than_blanked(text):
    # better to keep whatever ao3 said than to lose it
    assert parse_text.get_listing_date(text) == text


def test_get_date_suffix_is_the_stamp_with_its_separator():
    assert parse_text.get_date_suffix('14 Dec 2024') == ' 2024-12-14'
    assert parse_text.get_date_suffix('not a date') == ''


@pytest.mark.parametrize('name,expected', [
    ('34816549 No Paths Are Bound - Cal 2024-12-14.html', '2024-12-14'),
    ('34816549 No Paths Are Bound - Cal 2024-12-14.epub', '2024-12-14'),
    (r'downloads\sub\34816549 A 2024-12-14.pdf', '2024-12-14'),
    ('34816549 No Paths Are Bound - Cal.html', None),
    ('34816549 A Fic About 2024-12-14 Being A Date.html', None),
    ('', None),
])
def test_get_date_from_filename_reads_only_a_trailing_stamp(name, expected):
    assert parse_text.get_date_from_filename(name) == expected


@pytest.mark.parametrize('name,expected', [
    ('34816549 No Paths - Cal 2024-12-14.html', '34816549'),
    ('34816549.epub', '34816549'),
    ('34816549_something.pdf', '34816549'),
    ('99 Red Balloons.html', '99'),
    # deliberately not a work number: nothing separates the digits from the title
    ('99Red Balloons.html', None),
    ('No Paths 34816549.html', None),
])
def test_get_work_number_from_filename_matches_the_documented_rule(name, expected):
    assert parse_text.get_work_number_from_filename(name) == expected

# endregion


# region get_valid_filename with a date on the end

SUFFIX = ' 2024-12-14'


def test_the_date_survives_a_title_too_long_to_fit():
    name = parse_text.get_valid_filename(
        ['34816549 No Paths Are Bound And Nothing Is Ever Simple - Cataclysmic_Cal'], 50, SUFFIX)

    assert len(name) == 50
    assert name.endswith(SUFFIX)
    # the work number still leads, so the file can still be matched to its index entry
    assert parse_text.get_work_number_from_filename(name) == '34816549'


def test_a_short_title_keeps_all_of_itself_and_the_date():
    assert parse_text.get_valid_filename(['34816549 Short - Cal'], 50, SUFFIX) == \
        '34816549 Short - Cal 2024-12-14'


def test_no_suffix_leaves_names_exactly_as_they_were():
    assert parse_text.get_valid_filename(['34816549 Short - Cal'], 50) == '34816549 Short - Cal'


def test_only_the_file_name_is_dated_not_the_folders_above_it():
    name = parse_text.get_valid_filename(
        ['A Fandom', '34816549 Some Very Long Title Indeed Here - Cal'], 50, SUFFIX)

    folder, _, filename = name.rpartition(os.sep)
    assert folder == 'A Fandom'
    assert filename.endswith(SUFFIX)
    assert len(filename) == 50


def test_a_title_that_sanitises_away_still_gets_a_dated_name():
    assert parse_text.get_valid_filename([''], 50, SUFFIX) == '2024-12-14'


def test_no_length_limit_means_the_whole_title_and_the_date():
    name = parse_text.get_valid_filename(['34816549 A Very Long Title Indeed - Cal'], 0, SUFFIX)

    assert name == '34816549 A Very Long Title Indeed - Cal 2024-12-14'


def test_the_date_is_never_the_thing_that_gets_cut():
    # a limit shorter than the stamp itself still keeps the stamp whole
    name = parse_text.get_valid_filename(['34816549 Something'], 5, SUFFIX)

    assert name.endswith('2024-12-14')

# endregion


# region set_page_number

def test_set_page_number_adds_a_querystring_when_there_is_none():
    assert parse_text.set_page_number('https://example.com/foo', 5) == \
        'https://example.com/foo?page=5'


def test_set_page_number_appends_to_an_existing_querystring():
    assert parse_text.set_page_number('https://example.com/foo?a=1', 5) == \
        'https://example.com/foo?a=1&page=5'


def test_set_page_number_replaces_a_page_that_is_already_there():
    assert parse_text.set_page_number('https://example.com/foo?page=3', 12) == \
        'https://example.com/foo?page=12'


@pytest.mark.parametrize('page', [1, 0, -3])
def test_set_page_number_leaves_the_link_alone_for_the_first_page(page):
    # ao3 serves the first page with no page= element, so adding one says nothing
    assert parse_text.set_page_number('https://example.com/foo', page) == \
        'https://example.com/foo'


def test_set_page_number_round_trips_with_get_page_number():
    link = parse_text.set_page_number('https://example.com/foo?a=1', 7)

    assert parse_text.get_page_number(link) == 7

# endregion


# region get_direct_download_link

def test_a_download_link_is_built_from_the_work_number_alone():
    assert parse_text.get_direct_download_link('92361536', 'HTML') == \
        'https://download.archiveofourown.org/downloads/92361536/fic.html'


@pytest.mark.parametrize('filetype,extension', [
    ('AZW3', '.azw3'), ('EPUB', '.epub'), ('MOBI', '.mobi'),
    ('PDF', '.pdf'), ('HTML', '.html'),
])
def test_every_format_hangs_off_the_same_link(filetype, extension):
    link = parse_text.get_direct_download_link('92361536', filetype)

    assert link.endswith('/92361536/fic' + extension)


def test_the_link_goes_to_the_download_host_rather_than_the_site():
    # the links on a work page point at the site and redirect here; going straight there
    # saves the redirect
    link = parse_text.get_direct_download_link('92361536', 'EPUB')

    assert link.startswith('https://download.archiveofourown.org/')

# endregion


# region get_collection_name

@pytest.mark.parametrize('link,expected', [
    ('https://archiveofourown.org/collections/yuletide2024', 'yuletide2024'),
    ('https://archiveofourown.org/collections/yuletide2024/profile', 'yuletide2024'),
    ('https://archiveofourown.org/collections/yuletide2024/works?page=2', 'yuletide2024'),
    ('https://archiveofourown.org/collections/Some_Name-1/bookmarks', 'Some_Name-1'),
])
def test_get_collection_name_reads_any_page_of_a_collection(link, expected):
    assert parse_text.get_collection_name(link) == expected


@pytest.mark.parametrize('link', [
    '',
    None,
    'https://archiveofourown.org/collections',
    # a user's own collections listing is not one collection
    'https://archiveofourown.org/users/Someone/collections',
    # the form for making one, not one that exists
    'https://archiveofourown.org/collections/new',
    'https://archiveofourown.org/works/123',
])
def test_get_collection_name_returns_nothing_for_what_is_not_one_collection(link):
    assert parse_text.get_collection_name(link) is None
    assert parse_text.is_collection(link) is False

# endregion
