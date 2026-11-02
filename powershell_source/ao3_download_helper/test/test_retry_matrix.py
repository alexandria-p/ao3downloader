"""Retrying each scan from each place it can be retried from - see RESUMING.md.

The full scan, the quick scan (with and without a date range) and the custom run (over all
your bookmarks, and over a date range), each retried:

- from wherever its index walk(s) stopped - the first walk not started, stopped during it,
  and, where there is a second walk, first finished and second not started, stopped during
  the second, and both finished
- with its downloads started from the top, carried on (a fic partway through its formats
  included), or only the works it could not get

and, for the runs that offer it, with overwriting on. Everything a run does is real down to
the requests: the listing pages it asks for and the files it asks for are what is checked.
"""

import re
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from source_code import parse_text, runs, server, strings
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository

FORMATS = ['HTML', 'EPUB', 'PDF', 'MOBI']
BASE = 'https://archiveofourown.org/users/Someone/bookmarks?'
BOOKMARKED = BASE + strings.AO3_SORT_BY_BOOKMARKED
UPDATED = BASE + strings.AO3_SORT_BY_UPDATED
EARLIER = 'e' * 32


# region a library, a listing, and a run to retry

@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()
    return fileops


def blurb(work: int) -> str:
    """Bookmarked and updated on day `work` of January 2025."""
    day = f'{work:02d} Jan 2025'
    return (f'<li id="bookmark_{work}" class="bookmark blurb group">'
            f'<div class="header module"><h4 class="heading"><a href="/works/{work}">'
            f'Work {work}</a> by <a href="/users/a/pseuds/a" rel="author">A</a></h4>'
            f'<p class="datetime">{day}</p></div>'
            f'<div class="user module group"><p class="datetime">{day}</p></div></li>')


def listing(link: str, *pages: list[int]) -> dict[str, BeautifulSoup]:
    numbers = ''.join(f'<li>{i}</li>' for i in range(1, len(pages) + 1))
    return {parse_text.set_page_number(link, i): BeautifulSoup(
        f'<ol class="bookmark index group">{"".join(blurb(w) for w in works)}</ol>'
        f'<ol class="pagination actions">{numbers}</ol>', 'html.parser')
        for i, works in enumerate(pages, start=1)}


def a_fic(work: int) -> dict:
    return {'id': str(work), 'link': f'https://archiveofourown.org/works/{work}',
            'title': f'Work {work}', 'authors': ['A'], 'date_updated': f'{work:02d} Jan 2025',
            'date_bookmarked': f'{work:02d} Jan 2025'}


def a_repo(pages: dict) -> tuple[MagicMock, list, list]:
    """ao3, as far as these runs reach it: listing pages, and files."""
    repo = MagicMock(spec=Repository)
    asked: list[tuple[str, int]] = []
    files: list[tuple[str, str]] = []

    def get_soup(link):
        asked.append(('updated' if strings.AO3_SORT_BY_UPDATED in link else 'bookmarked',
                      parse_text.get_page_number(link)))
        return pages[link]

    def download_file(link, filetype):
        files.append((re.search(r'/downloads/(\d+)/', link).group(1), filetype))
        return f'{link} {filetype}'.encode()

    repo.get_soup.side_effect = get_soup
    repo.download_file.side_effect = download_file
    return repo, asked, files


def saved(library: FileOps, work: int, formats: list[str]) -> None:
    """What the earlier attempt left of a work: its index entry, and these formats."""
    ao3 = Ao3(repo=a_repo({})[0], fileops=library, filetypes=list(formats), pages=None,
              series=False, images=False)
    ao3.save_metadata(a_fic(work))
    if formats: ao3.download_one_indexed(a_fic(work), 50, {}, 1, 1)


def earlier_run(library: FileOps, action: str, options: dict, progress: dict,
                failures: list[int] = ()) -> None:
    record = runs.RunRecord(library, EARLIER, action, 'Run', ['JSON', *FORMATS], options)
    record.data.update(status=runs.STATUS_STOPPED, baseline='2025-01-20T10:00:00',
                       progress=progress,
                       failures=[{'id': str(w), 'link': f'https://archiveofourown.org/works/{w}',
                                  'error': 'no'} for w in failures])
    record.save()


def retry(library: FileOps, repo, mode: str) -> server.Job:
    """Retry the earlier run as the run thread would, up to and through its runner."""
    job = server.Job(server.ACTION_CUSTOM, ['JSON'], 'Someone',
                     server.resolve_options({'resume': EARLIER, 'retryMode': mode}))
    server.prepare_resume(job, library)
    job.record = runs.RunRecord(library, job.id, job.action, 'Retry', job.filetypes, job.options)
    # what `begin_record` does once the login works: a retry measures from its first attempt
    job.baseline = job.resume.get('baseline') or ''
    job.steps = server.Steps(None, server.step_plan(job))
    with patch.object(server.Job, 'ask', side_effect=AssertionError('nothing should be asked')), \
         patch.object(server, 'index_series_and_non_bookmarks', return_value=[]), \
         patch.object(server, 'finish_run'):
        server.runners()[job.action](job, library, repo, None)
    return job

# endregion


# region the workflows, and how each is set up

QUICK = (server.ACTION_QUICK, {})
QUICK_RANGE = (server.ACTION_QUICK, {'dates': True, 'dateFrom': '2025-01-08',
                                     'dateTo': '2025-01-19'})
FULL = (server.ACTION_BOOKMARKS, {})
CUSTOM_ALL = (server.ACTION_CUSTOM, {})
CUSTOM_RANGE = (server.ACTION_CUSTOM, {'dates': True, 'dateFrom': '2025-01-08',
                                       'dateTo': '2025-01-19'})

# endregion


# region retried from wherever indexing stopped

# bookmarks 22 and 21 were made after the first attempt began (the 20th, the ceiling); 23 and
# 24 were updated after it. pages: date bookmarked 22-21 | 20-19 | 18-17,
# date updated 24-23 | 12-11 | 10-9 | 8-7
PAGES = {**listing(BOOKMARKED, [22, 21], [20, 19], [18, 17]),
         **listing(UPDATED, [24, 23], [12, 11], [10, 9], [8, 7])}
B, U = 'bookmarked', 'updated'
B_PLACE = {'id': 'bookmark_19', 'date': '2025-01-19', 'sort': 'bookmarked'}
U_PLACE = {'id': 'bookmark_11', 'date': '2025-01-11', 'sort': 'updated'}
B_DONE = {'page': 3, 'anchor': B_PLACE, 'done': True, 'works': ['20', '19', '18', '17']}
U_DONE = {'page': 4, 'anchor': U_PLACE, 'done': True, 'works': ['12', '11', '10', '9', '8', '7']}

WALKS = [
    pytest.param(
        QUICK, {},
        [(B, 1), (B, 2), (B, 2), (B, 3), (U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
        id='quick: the first walk did not start'),
    pytest.param(
        QUICK, {B: {'page': 2, 'anchor': B_PLACE, 'done': False, 'works': ['20', '19']}},
        [(B, 2), (B, 1), (B, 2), (B, 3), (U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
        id='quick: stopped during the first walk'),
    pytest.param(
        QUICK, {B: B_DONE}, [(U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
        id='quick: first finished, second did not start'),
    pytest.param(
        QUICK, {B: B_DONE, U: {'page': 2, 'anchor': U_PLACE, 'done': False,
                               'works': ['12', '11']}},
        [(U, 2), (U, 1), (U, 2), (U, 3), (U, 4)],
        id='quick: stopped during the second walk'),
    pytest.param(QUICK, {B: B_DONE, U: U_DONE}, [], id='quick: both walks finished'),

    pytest.param(
        QUICK_RANGE, {},
        [(B, 1), (B, 2), (B, 2), (B, 3), (U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
        id='quick, date range: the first walk did not start'),
    pytest.param(
        QUICK_RANGE, {B: {'page': 2, 'anchor': B_PLACE, 'done': False, 'works': ['20', '19']}},
        [(B, 2), (B, 1), (B, 2), (B, 3), (U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
        id='quick, date range: stopped during the first walk'),
    pytest.param(
        QUICK_RANGE, {B: B_DONE}, [(U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
        id='quick, date range: first finished, second did not start'),
    pytest.param(
        QUICK_RANGE, {B: B_DONE, U: {'page': 2, 'anchor': U_PLACE, 'done': False,
                                     'works': ['12', '11']}},
        [(U, 2), (U, 1), (U, 2), (U, 3), (U, 4)],
        id='quick, date range: stopped during the second walk'),
    pytest.param(QUICK_RANGE, {B: B_DONE, U: U_DONE}, [],
                 id='quick, date range: both walks finished'),

    # one walk, by date bookmarked, with no ceiling: new bookmarks are what it is for
    pytest.param(FULL, {}, [(B, 1), (B, 2), (B, 3)], id='full: the walk did not start'),
    pytest.param(
        FULL, {'all': {'page': 2, 'anchor': B_PLACE, 'done': False,
                       'works': ['22', '21', '20', '19']}},
        [(B, 2), (B, 1), (B, 2), (B, 3)], id='full: stopped during the walk'),
    pytest.param(
        FULL, {'all': {**B_DONE, 'works': ['22', '21', '20', '19', '18', '17']}}, [],
        id='full: the walk finished'),

    pytest.param(CUSTOM_ALL, {}, [(B, 1), (B, 2), (B, 3)], id='custom: the walk did not start'),
    pytest.param(
        CUSTOM_ALL, {'all': {'page': 2, 'anchor': B_PLACE, 'done': False,
                             'works': ['22', '21', '20', '19']}},
        [(B, 2), (B, 1), (B, 2), (B, 3)], id='custom: stopped during the walk'),
    pytest.param(
        CUSTOM_ALL, {'all': {**B_DONE, 'works': ['22', '21', '20', '19', '18', '17']}}, [],
        id='custom: the walk finished'),

    pytest.param(CUSTOM_RANGE, {}, [(U, 1), (U, 2), (U, 2), (U, 3), (U, 4)],
                 id='custom, date range: the walk did not start'),
    pytest.param(
        CUSTOM_RANGE, {U: {'page': 2, 'anchor': U_PLACE, 'done': False, 'works': ['12', '11']}},
        [(U, 2), (U, 1), (U, 2), (U, 3), (U, 4)], id='custom, date range: stopped during the walk'),
    pytest.param(CUSTOM_RANGE, {U: U_DONE}, [], id='custom, date range: the walk finished'),
]


@pytest.mark.parametrize('overwrite', [False, True], ids=['', 'overwriting'])
@pytest.mark.parametrize('workflow, walks, wanted', WALKS)
def test_a_retry_carries_indexing_on_from_wherever_it_stopped(library, workflow, walks, wanted,
                                                              overwrite):
    action, options = workflow
    if overwrite and action not in server.OVERWRITE_ACTIONS:
        pytest.skip('this run does not offer overwriting')
    for work in [*range(7, 13), *range(17, 25)]: saved(library, work, [])
    earlier_run(library, action, {**options, 'overwrite': overwrite},
                {'floor': '2025-01-08' if action == server.ACTION_QUICK else '', 'walks': walks})
    repo, asked, _ = a_repo(PAGES)

    with patch.object(server, 'download_planned'), \
         patch.object(server, 'refresh_and_download'):
        job = retry(library, repo, server.RETRY_INDEX)

    assert asked == wanted
    assert job.options.get('overwrite', False) is overwrite
    # every walk it has is saved as finished, for a retry of this retry
    assert all(walk.get('done') for walk in job.progress()['walks'].values())

# endregion


# region retried at its downloads

DOWNLOADING = [QUICK, QUICK_RANGE, FULL, CUSTOM_ALL, CUSTOM_RANGE]


def three_fics(library: FileOps) -> dict:
    """1 has every format, 2 only its html, 3 nothing - and 3 is what the attempt failed."""
    saved(library, 1, FORMATS)
    saved(library, 2, ['HTML'])
    saved(library, 3, [])
    return {'floor': '2025-01-01', 'scope': ['1', '2', '3'],
            'walks': {'all': {'done': True}, 'bookmarked': {'done': True},
                      'updated': {'done': True}},
            'formatsDone': {'1': FORMATS, '2': ['HTML']}}


def every(*works: int) -> list[tuple[str, str]]:
    return sorted((str(w), f) for w in works for f in FORMATS)


MISSING_FROM_2 = [('2', 'EPUB'), ('2', 'MOBI'), ('2', 'PDF')]


@pytest.mark.parametrize('overwrite', [False, True], ids=['', 'overwriting'])
@pytest.mark.parametrize('workflow', DOWNLOADING, ids=['quick', 'quick, date range', 'full',
                                                        'custom', 'custom, date range'])
@pytest.mark.parametrize('mode, wanted, wanted_overwriting', [
    # from the top: as a fresh run would - a fic with every format current is left alone, one
    # missing any is fetched whole (the scans' download step works per fic), and overwriting
    # fetches everything
    pytest.param(server.RETRY_REDOWNLOAD, every(2, 3), every(1, 2, 3),
                 id='start its downloads from the top'),
    # carrying on: only what is still missing, a fic partway through its formats included -
    # even when overwriting, since the earlier attempt already overwrote what it saved
    pytest.param(server.RETRY_DOWNLOADS, sorted(MISSING_FROM_2 + every(3)),
                 sorted(MISSING_FROM_2 + every(3)), id='carry on from where downloads stopped'),
    pytest.param(server.RETRY_FAILED, every(3), every(3), id='just the works it could not get'),
])
def test_a_retry_takes_up_its_downloads_from_where_it_was_asked_to(
        library, workflow, mode, wanted, wanted_overwriting, overwrite):
    action, options = workflow
    if overwrite and action not in server.OVERWRITE_ACTIONS:
        pytest.skip('this run does not offer overwriting')
    earlier_run(library, action, {**options, 'overwrite': overwrite}, three_fics(library),
                failures=[3])
    repo, asked, files = a_repo({})

    # a date range's downloads re-read each fic's own page first; ao3 says nothing has changed
    with patch.object(Ao3, 'refresh_one', side_effect=lambda record, *a, **k: record):
        retry(library, repo, mode)

    if workflow == CUSTOM_RANGE and mode == server.RETRY_REDOWNLOAD and not overwrite:
        # a date range's downloads go fic by fic and format by format, so a current copy is
        # kept even in a fic missing other formats
        wanted = sorted(MISSING_FROM_2 + every(3))
    assert asked == []    # no listing is read again
    assert sorted(files) == (wanted_overwriting if overwrite else wanted)

# endregion


# region checking what the earlier attempt says it did

def test_a_format_whose_file_has_gone_is_fetched_again(library):
    progress = three_fics(library)
    # someone deletes fic 1's epub between the attempts
    import os
    folder = library.worksfolder
    [epub] = [name for name in os.listdir(folder) if name.startswith('1 ') and name.endswith('.epub')]
    os.remove(os.path.join(folder, epub))
    earlier_run(library, server.ACTION_BOOKMARKS, {}, progress, failures=[3])
    repo, _, files = a_repo({})

    job = retry(library, repo, server.RETRY_DOWNLOADS)

    assert ('1', 'EPUB') in files and ('1', 'HTML') not in files
    assert 'EPUB' not in job.progress()['formatsDone']['1']


def test_a_format_dated_other_than_the_index_is_fetched_again(library):
    progress = three_fics(library)
    # another run has since found fic 1 updated: its files no longer match the index
    writer = Ao3(repo=a_repo({})[0], fileops=library, filetypes=[], pages=None, series=False,
                 images=False)
    writer.run_id = 'another'
    writer.save_metadata({**a_fic(1), 'date_updated': '05 Feb 2025'})
    earlier_run(library, server.ACTION_BOOKMARKS, {}, progress, failures=[3])
    repo, _, files = a_repo({})

    with patch('builtins.print') as said:
        retry(library, repo, server.RETRY_DOWNLOADS)

    assert every(1)[0] in files and set(every(1)) <= set(files)
    lines = ' '.join(str(c.args[0]) for c in said.call_args_list if c.args)
    assert 'another' in lines


def test_an_indexed_work_whose_entry_has_gone_is_indexed_again(library):
    progress = three_fics(library)
    import os
    folder = __import__('os').path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    [entry] = [name for name in os.listdir(folder) if name.startswith('2 ')]
    os.remove(os.path.join(folder, entry))
    earlier_run(library, server.ACTION_BOOKMARKS, {}, progress, failures=[3])
    repo, _, _ = a_repo({})

    with patch.object(Ao3, 'index_one_work') as indexing:
        retry(library, repo, server.RETRY_DOWNLOADS)

    assert [c.args[0] for c in indexing.call_args_list] == ['https://archiveofourown.org/works/2']


def test_every_entry_a_run_writes_names_the_run(library):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')
    ao3 = Ao3(repo=a_repo({})[0], fileops=library, filetypes=[], pages=None, series=False,
              images=False)
    job.ao3 = ao3
    ao3.save_metadata(a_fic(5))
    entry = library.load_json(ao3.entry_path({'id': '5'}))
    assert entry['last_indexed_by'] == job.id
    # and it is never part of a reading, so it does not fill the history
    assert all('last_indexed_by' not in reading for reading in entry['indexes'])


def test_a_retry_from_the_top_checks_nothing(library):
    earlier_run(library, server.ACTION_BOOKMARKS, {}, three_fics(library), failures=[3])
    repo, _, _ = a_repo(listing(BOOKMARKED, [3, 2], [1]))
    with patch.object(server, 'check_carried') as checking, \
         patch.object(server, 'download_planned'):
        retry(library, repo, server.RETRY_TOP)
    checking.assert_called_once()
    # called, but carries nothing: no works, no formats
    job = checking.call_args.args[0]
    assert server.carried_works(job.earlier_progress()) == set()

# endregion
