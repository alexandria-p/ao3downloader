"""The full scan's download the long way round - each work's own page, when there is no
index to work from (JSON unticked) - follows the same per-format rule as every other
download: fetch a format with no copy, or a copy dated before the page's last update; keep a
current copy; leave an undated one alone; fetch everything when overwriting.
"""

from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

from source_code import strings
from source_code.ao3 import Ao3
from source_code.repo import Repository

WORK = 'https://archiveofourown.org/works/7'


def an_ao3(copies: dict | None, filetypes=('HTML', 'EPUB', 'PDF'), overwriting=False) -> Ao3:
    ao3 = Ao3(repo=MagicMock(spec=Repository), fileops=MagicMock(), filetypes=list(filetypes),
              pages=None, series=False, images=False)
    ao3.existing_copies = copies
    ao3.overwriting = overwriting
    return ao3


def copy(date: str | None) -> dict:
    return {'path': f'works/7 Work - A {date or ""}.x', 'date': date}


# region each format, judged against the work page's date

def test_a_missing_or_older_format_is_fetched_and_a_current_one_kept():
    ao3 = an_ao3({'7': {'HTML': copy('2025-01-07'), 'EPUB': copy('2024-12-01')}})

    fetch = {x: ao3.page_verdict(WORK, '7', x, '2025-01-07') for x in ('HTML', 'EPUB', 'PDF')}

    assert fetch == {'HTML': False, 'EPUB': True, 'PDF': True}
    # the older copy is the one the new file replaces
    assert ao3.superseded == {WORK: {'EPUB': copy('2024-12-01')['path']}}


def test_an_undated_copy_cannot_be_judged_and_is_left_alone():
    ao3 = an_ao3({'7': {'HTML': copy(None)}})
    with patch('builtins.print') as said:
        assert ao3.page_verdict(WORK, '7', 'HTML', '2025-01-07') is False
    assert said.call_args.args[0] == strings.AO3_INFO_FORMAT_UNDATED.format('HTML')


def test_an_overwriting_run_fetches_every_format_even_a_current_one():
    ao3 = an_ao3({'7': {'HTML': copy('2025-01-07')}}, overwriting=True)
    assert ao3.page_verdict(WORK, '7', 'HTML', '2025-01-07') is True
    assert ao3.superseded[WORK]['HTML']


def test_without_a_folder_scan_every_format_is_fetched_as_before():
    assert an_ao3(None).page_verdict(WORK, '7', 'HTML', '2025-01-07') is True

# endregion


# region a work already on disk in every format

def a_listing(date: str) -> BeautifulSoup:
    return BeautifulSoup(
        '<ol class="bookmark index group"><li id="bookmark_7" class="bookmark blurb group">'
        '<div class="header module"><h4 class="heading"><a href="/works/7">Work</a> by '
        f'<a href="/users/a/pseuds/a" rel="author">A</a></h4><p class="datetime">{date}</p>'
        '</div></li></ol>', 'html.parser')


def test_a_work_behind_the_listing_is_opened_though_every_format_is_on_disk():
    ao3 = an_ao3({'7': {'HTML': copy('2025-01-01'), 'EPUB': copy('2025-01-07')}},
                 filetypes=('HTML', 'EPUB'))
    ao3.note_listing_dates(a_listing('07 Jan 2025'))

    with patch.object(Ao3, 'download_work') as opening:
        ao3.download_recursive(WORK, {}, [WORK])
        # once only
        ao3.download_recursive(WORK, {}, [WORK])

    assert opening.call_count == 1


def test_a_work_current_in_every_format_is_not_opened():
    ao3 = an_ao3({'7': {'HTML': copy('2025-01-07'), 'EPUB': copy('2025-01-07')}},
                 filetypes=('HTML', 'EPUB'))
    ao3.note_listing_dates(a_listing('07 Jan 2025'))

    with patch.object(Ao3, 'download_work') as opening:
        ao3.download_recursive(WORK, {}, [WORK])

    opening.assert_not_called()


def test_an_overwriting_run_opens_every_work_on_disk():
    ao3 = an_ao3({'7': {'HTML': copy('2025-01-07')}}, filetypes=('HTML',), overwriting=True)
    ao3.note_listing_dates(a_listing('07 Jan 2025'))

    with patch.object(Ao3, 'download_work') as opening:
        ao3.download_recursive(WORK, {}, [WORK])

    assert opening.call_count == 1

# endregion
