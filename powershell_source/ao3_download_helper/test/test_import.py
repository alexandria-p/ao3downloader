"""Importing works whose files were found in a library with no index entry (`ACTION_IMPORT`).

The page finds them, offers to date the undated ones, and asks which formats to add and
whether to replace outdated copies; the run then indexes each from ao3, marks it imported,
and fetches only what it was told to - never overwriting a copy that is current.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from source_code import exceptions, server, strings
from source_code.ao3 import Ao3

from test.test_ao3 import _work_page_soup, make_ao3
from test.test_server import start_request


def link(n) -> str:
    return f'https://archiveofourown.org/works/{n}'


@pytest.fixture
def library(fake_fileops):
    for name in (strings.INDEXING_FOLDER_NAME, strings.WORKS_FOLDER_NAME):
        os.makedirs(os.path.join(fake_fileops.downloadfolder, name), exist_ok=True)
    return fake_fileops


def a_copy(library, name: str) -> None:
    with open(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME, name), 'wb') as f:
        f.write(b'<html>an old copy</html>')


def importing(library, monkeypatch, filetypes, replace=False, updated='2026-05-01'):
    """Run an import over works 1 and 2, AO3 saying each was last updated on `updated`;
    answers what was fetched, by work."""

    def index_one_work(self, url, existing=None, find_existing=None):
        work = url.rsplit('/', 1)[-1]
        record = {'id': work, 'link': url, 'title': f'Fic {work}', 'authors': ['Someone'],
                  'date_updated': updated, strings.FROM_IMPORT_FIELD: True}
        self.reindexed.add(work)
        return record

    fetched: dict[str, list[str]] = {}

    def download_one_indexed(self, record, *args, **kwargs):
        kept = self.keep_formats.get(record['link']) or set()
        current = self.current_formats(record)
        fetched[record['id']] = [x for x in self.filetypes
                                 if x.upper() not in kept and x.upper() not in current]

    monkeypatch.setattr(Ao3, 'index_one_work', index_one_work)
    monkeypatch.setattr(Ao3, 'download_one_indexed', download_one_indexed)
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    job = server.Job(server.ACTION_IMPORT, filetypes, '',
                     server.resolve_options({'replaceOutdated': replace}),
                     url=f'{link(1)}\n{link(2)}')
    job.ask = MagicMock(side_effect=AssertionError('an import asked a question'))
    server.run_import(job, library, MagicMock(), MagicMock())
    return job, fetched


# region starting one

def test_an_import_takes_the_works_found_one_link_to_a_line():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1 2 3', username='', password='',
                                   skipLogin=True)

    assert sent['status'] == 202
    assert job.url == '\n'.join(link(n) for n in (1, 2, 3))


def test_an_import_with_nothing_found_is_refused():
    sent, jobs, _ = start_request(server.ACTION_IMPORT, ' ')
    assert sent['status'] == 400
    assert sent['body']['error'] == strings.ERROR_NO_IMPORT_WORKS
    assert jobs == []


def test_an_import_takes_far_more_works_than_several_fics_do():
    many = ' '.join(str(n) for n in range(1, server.MAX_WORK_LINKS + 2))
    sent, _, _ = start_request(server.ACTION_IMPORT, many)
    assert sent['status'] == 202
    sent, _, _ = start_request(server.ACTION_WORKS, many)
    assert sent['status'] == 400


def test_an_import_is_refused_past_its_own_limit():
    many = ' '.join(str(n) for n in range(1, server.MAX_IMPORT_LINKS + 2))
    sent, _, _ = start_request(server.ACTION_IMPORT, many)
    assert sent['status'] == 400
    assert str(server.MAX_IMPORT_LINKS) in sent['body']['error']


def test_replacing_outdated_copies_is_the_imports_option_alone():
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1', replaceOutdated=True)
    assert job.options['replaceOutdated'] is True
    sent, [job], _ = start_request(server.ACTION_WORKS, '1', replaceOutdated=True)
    assert job.options['replaceOutdated'] is False


def test_an_import_needs_no_username_without_a_login():
    assert server.ACTION_IMPORT not in server.USERNAME_ACTIONS
    sent, [job], _ = start_request(server.ACTION_IMPORT, '1', username='Someone', password='',
                                   skipLogin=True)
    assert sent['status'] == 202
    assert job.username == ''

# endregion


# region what it does

def test_an_import_has_its_own_checklist_with_no_series_walk():
    job = server.Job(server.ACTION_IMPORT, ['JSON', 'HTML'], '', server.resolve_options({}))
    plan = dict(server.step_plan(job))
    assert plan['index'] == strings.STEP_INDEX_IMPORT
    assert plan['download'] == strings.STEP_DOWNLOAD_IMPORT
    assert 'series' not in plan
    assert list(plan)[-1] == 'report'


def test_an_import_that_only_indexes_downloads_nothing():
    job = server.Job(server.ACTION_IMPORT, ['JSON'], '', server.resolve_options({}))
    plan = dict(server.step_plan(job))
    assert 'download' not in plan


def test_an_import_fetches_only_the_formats_missing_and_keeps_an_outdated_copy(library, monkeypatch):
    # dated before ao3's latest version, so outdated - kept all the same, as told
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    job, fetched = importing(library, monkeypatch, ['JSON', 'HTML', 'EPUB'])

    assert fetched['1'] == ['EPUB']
    assert fetched['2'] == ['HTML', 'EPUB']
    assert job.options['overwrite'] is False


def test_an_import_with_every_format_held_fetches_nothing_for_that_work(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'])

    assert '1' not in fetched


def test_an_import_told_to_replaces_an_outdated_copy(library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert fetched['1'] == ['HTML']


def test_an_import_never_replaces_a_current_copy_even_when_told_to_replace_outdated_ones(
        library, monkeypatch):
    a_copy(library, '1 Fic 1 - Someone 2026-05-01.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert '1' not in fetched


def test_an_import_leaves_an_undated_copy_alone_without_asking(library, monkeypatch, capsys):
    # the page offered to date it before the run; left undated there, it stays so
    a_copy(library, '1 Fic 1 - Someone.html')

    _, fetched = importing(library, monkeypatch, ['JSON', 'HTML'], replace=True)

    assert '1' not in fetched
    assert strings.AO3_INFO_IMPORT_UNDATED_KEPT in capsys.readouterr().out


def test_an_import_says_it_is_keeping_the_copies_you_have(library, monkeypatch, capsys):
    a_copy(library, '1 Fic 1 - Someone 2020-01-01.html')

    importing(library, monkeypatch, ['JSON', 'HTML', 'EPUB'])

    assert strings.AO3_INFO_IMPORT_KEEPING in capsys.readouterr().out


def test_a_work_ao3_will_not_show_is_a_failure_of_that_work_alone(library, monkeypatch):
    def index_one_work(self, url, existing=None, find_existing=None):
        if url.endswith('/1'): raise exceptions.DeletedException('deleted')
        return {'id': '2', 'link': url, 'date_updated': '2026-05-01'}

    monkeypatch.setattr(Ao3, 'index_one_work', index_one_work)
    monkeypatch.setattr(server, 'download_planned', MagicMock())
    monkeypatch.setattr(server, 'finish_run', MagicMock())
    job = server.Job(server.ACTION_IMPORT, ['JSON', 'HTML'], '', server.resolve_options({}),
                     url=f'{link(1)}\n{link(2)}')

    server.run_import(job, library, MagicMock(), MagicMock())

    assert [x['link'] for x in job.ao3.failures] == [link(1)]
    records = server.download_planned.call_args.args[3]
    assert [r['id'] for r in records] == ['2']
    assert server.download_planned.call_args.kwargs['keep_existing'] is True
    server.finish_run.assert_called_once()

# endregion


# region where it says the work came from

@pytest.mark.parametrize('existing, page, marked', [
    (None, {'bookmarked': False}, True),                       # not yours
    (None, {}, True),                                          # the page could not say
    (None, {'bookmarked': True}, False),                       # it is your bookmark
])
def test_a_work_an_import_indexes_is_marked_imported_unless_it_is_your_bookmark(existing, page, marked):
    ao3, repo, _ = make_ao3()
    ao3.origin_field = strings.FROM_IMPORT_FIELD
    repo.get_soup.return_value = _work_page_soup()

    with patch.object(Ao3, 'proceed', side_effect=lambda soup: soup), \
         patch('source_code.ao3.bookmark_state', return_value=page):
        record = ao3.index_one_work(link(111), existing)

    assert record.get(strings.FROM_IMPORT_FIELD) is (True if marked else None)
    # not 'downloaded by its link': nobody asked for it by one
    assert strings.FROM_LINK_FIELD not in record


def test_from_import_is_an_identity_field_kept_through_every_later_reading():
    from source_code import indexing
    first = indexing.merge(None, {'id': '1', 'link': 'l', 'title': 'A', 'from_import': True}, 't1')
    later = indexing.merge(first, {'id': '1', 'link': 'l', 'title': 'B'}, 't2')
    assert indexing.flatten(later)['from_import'] is True
    assert all('from_import' not in reading for reading in later['indexes'])


def test_an_imports_retry_of_its_failures_is_still_an_import():
    job = server.Job(server.ACTION_IMPORT, ['JSON'], '', server.resolve_options({}))
    earlier = {'id': 'r1', 'action': server.ACTION_IMPORT, 'status': 'partial',
               'filetypes': ['JSON'], 'options': {}, 'url': f'{link(1)}\n{link(2)}',
               'failures': [{'id': '1', 'link': link(1), 'error': 'gone'},
                            {'id': '2', 'link': link(2), 'error': 'gone'}]}
    job.options['resume'], job.options['retryMode'] = 'r1', server.RETRY_FAILED
    with patch.object(server.runs, 'find_run', return_value=earlier), \
         patch.object(server, 'retry_progress', return_value={}), \
         patch.object(server, 'retry_problem', return_value=''):
        server.prepare_resume(job, MagicMock())
    assert job.action == server.ACTION_IMPORT
    assert job.url == f'{link(1)}\n{link(2)}'


def test_an_import_can_carry_on_fic_by_fic_like_several_fics():
    record = {'id': 'r1', 'action': server.ACTION_IMPORT, 'status': 'stopped',
              'url': link(1), 'progress': {}, 'options': {}}
    choices = server.retry_choices(record, set())
    assert [m['mode'] for m in choices['modes']] == [
        server.RETRY_TOP, server.RETRY_DOWNLOADS, server.RETRY_FAILED]

# endregion
