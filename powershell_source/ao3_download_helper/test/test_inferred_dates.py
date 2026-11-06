"""Replacing a file on a version check is only automatic for a date in the app's own form.

A file's version is the date ending its name, written ` YYYY-MM-DD` by this app. A date
written any other way - `(14 Dec 2024)`, `2024.12.14`, mid-name - can still be read out of the
name the way the Resolve issues window's *Infer date* reads one, but it is only inferred: the
run judges by it and **asks** before replacing, saying it only *thinks* the incoming version is
newer, and keeps the file if nobody answers. From AO3 and FicHub alike.
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from source_code import parse_text, server, strings
from source_code.actions import shared
from source_code.ao3 import Ao3

LINK = 'https://archiveofourown.org/works/75354806'

# region what counts as the app's own date

@pytest.mark.parametrize('name, date', [
    ('75354806 Wolfbird - OpalApparition 2026-04-27.epub', '2026-04-27'),
    ('75354806 Wolfbird - OpalApparition (27 Apr 2026).epub', None),
    ('75354806 Wolfbird - OpalApparition 2026.04.27.epub', None),
    # no space before it: not how this app writes one
    ('75354806 Wolfbird - OpalApparition_2026-04-27.epub', None),
    # not a real day
    ('75354806 Wolfbird - OpalApparition 2026-13-45.epub', None),
])
def test_only_a_date_written_the_apps_way_is_a_files_version(name, date):
    assert parse_text.get_date_from_filename(name) == date


def test_a_date_written_another_way_can_still_be_inferred():
    assert parse_text.infer_date_from_filename(
        '75354806 Wolfbird - OpalApparition (27 Apr 2026).epub') == '2026-04-27'

# endregion

# region asking

def answering_job(answer=None):
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB'], 'Someone')
    asked = []

    def ask(question, default):
        asked.append((question, default))
        return dict(default) if answer is None else {'choice': answer}
    job.ask = ask
    return job, asked


def a_plan(copies: dict, date='2026-04-27', overwrite=False):
    records = [{'id': '75354806', 'link': LINK, 'date_updated': date}]
    existing = {'75354806': {fmt: {'path': f'works/{name}',
                                   'date': parse_text.get_date_from_filename(name)}
                             for fmt, name in copies.items()}}
    plan = shared.plan_downloads(records, existing, list(copies), overwrite=overwrite)
    return records, existing, plan


@pytest.mark.parametrize('answer, replaced', [(None, False), ('no', False), ('yes', True)])
def test_an_inferred_date_older_than_the_incoming_version_is_asked_about_default_no(
        answer, replaced, capsys):
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird (14 Dec 2024).epub'})
    # the version check alone would have left it as undated, not behind
    assert LINK in plan['undated'] and LINK not in plan['stale']
    job, asked = answering_job(answer)

    server.ask_about_inferred_dates(job, records, existing, plan, ['EPUB'])

    question, default = asked[0]
    assert question['name'] == server.INFERRED_DATE_QUESTION
    assert question['formats'] == ['EPUB'] and question['date'] == '2026-04-27'
    assert question['fileDates'] == {'EPUB': '2024-12-14'} and question['source'] == 'AO3'
    assert default == {'choice': 'no'}
    assert (LINK in plan['stale']) is replaced
    assert ('EPUB' in plan['superseded'].get(LINK, {})) is replaced
    assert ('EPUB' in plan['keep'].get(LINK, set())) is not replaced
    assert LINK not in plan['undated']
    out = capsys.readouterr().out
    assert 'only inferred. We think AO3\'s copy (2026-04-27) is newer, but cannot be sure' in out


def test_an_inferred_date_not_older_than_the_incoming_version_is_kept_unasked(capsys):
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird (27 Apr 2026).epub'})
    job, asked = answering_job('yes')

    server.ask_about_inferred_dates(job, records, existing, plan, ['EPUB'])

    assert asked == []
    assert plan['keep'] == {LINK: {'EPUB'}} and LINK not in plan['stale']
    assert "AO3's copy (2026-04-27) does not look newer - keeping it" in capsys.readouterr().out


def test_a_name_with_no_date_at_all_is_left_to_the_undated_question():
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird.epub'})
    job, asked = answering_job('yes')

    server.ask_about_inferred_dates(job, records, existing, plan, ['EPUB'])

    assert asked == [] and LINK in plan['undated']


def test_a_run_that_overwrites_asks_nothing_about_an_inferred_date():
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird (14 Dec 2024).epub'},
                                     overwrite=True)
    job, asked = answering_job('no')

    server.ask_about_inferred_dates(job, records, existing, plan, ['EPUB'], overwriting=True)

    assert asked == [] and LINK in plan['stale']

# endregion

# region in a scan

@pytest.fixture
def library(fake_fileops):
    for name in (strings.INDEXING_FOLDER_NAME, strings.WORKS_FOLDER_NAME):
        os.makedirs(os.path.join(fake_fileops.downloadfolder, name), exist_ok=True)
    return fake_fileops


def a_copy(library, name: str) -> None:
    with open(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME, name), 'w') as f:
        f.write('what you had')


def indexed(library, date: str) -> None:
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'date_updated': date}, f)


def test_a_scan_asks_about_an_inferred_date_instead_of_the_undated_question(library):
    indexed(library, '2026-01-01')
    a_copy(library, '75354806 Wolfbird - OpalApparition (14 Dec 2024).epub')
    job, asked = answering_job()
    job.ao3 = Ao3(MagicMock(), library, ['EPUB'], None, False, False)
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-04-27'}]

    plan = server.plan_refresh(job, library, records, ['EPUB'], MagicMock())

    assert [q['name'] for q, _ in asked] == [server.INFERRED_DATE_QUESTION]
    assert LINK not in plan['stale'] and plan['keep'] == {LINK: {'EPUB'}}


def test_re_downloading_undated_files_leaves_a_work_with_an_inferred_date_to_its_own_question(library):
    indexed(library, '2026-01-01')
    a_copy(library, '75354806 Wolfbird - OpalApparition (14 Dec 2024).epub')
    a_copy(library, '1 Other.epub')
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '1 Other.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '1', 'link': 'https://archiveofourown.org/works/1', 'date_updated': '2026-01-01'}, f)
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB'], 'Someone')
    asked = []

    def ask(question, default):
        asked.append(question['name'])
        return ({'choice': server.UNDATED_REFRESH, 'date': ''}
                if question['name'] == server.UNDATED_QUESTION else dict(default))
    job.ask = ask
    job.ao3 = Ao3(MagicMock(), library, ['EPUB'], None, False, False)
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-04-27'},
               {'id': '1', 'link': 'https://archiveofourown.org/works/1', 'date_updated': '2026-04-27'}]

    plan = server.plan_refresh(job, library, records, ['EPUB'], MagicMock())

    # the undated question was about work 1 alone; work 75354806 had its own, answered no
    assert asked == [server.UNDATED_QUESTION, server.INFERRED_DATE_QUESTION]
    assert 'https://archiveofourown.org/works/1' in plan['stale']
    assert LINK not in plan['stale']

# endregion

# region from FicHub

def wolfbird() -> dict:
    path = os.path.join(os.path.dirname(__file__), 'fixtures', 'fichub', 'wolfbird.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def a_rescue(library, monkeypatch, answer=None):
    fetched: list[str] = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, answer, filetype: fetched.append(filetype) or b'from fichub')
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'EPUB'], 'Someone')
    asked = []

    def ask(question, default):
        asked.append((question, default))
        if question['name'] == server.FICHUB_QUESTION: return {'choice': 'yes'}
        return dict(default) if answer is None else {'choice': answer}
    job.ask = ask
    ao3 = Ao3(MagicMock(), library, ['EPUB'], None, False, False)
    ao3.failures = [{'id': '75354806', 'link': LINK, 'error': 'not a work file (404)'}]
    server.rescue_with_fichub(job, library, ao3, MagicMock())
    return fetched, asked


@pytest.mark.fichub
@pytest.mark.parametrize('index_date', ['2026-04-27', '2026-05-10'])
@pytest.mark.parametrize('answer, replaced', [(None, False), ('yes', True)])
def test_fichub_asks_before_replacing_a_file_whose_date_was_only_inferred(
        library, monkeypatch, index_date, answer, replaced):
    # FicHub's copy is 2026-04-27: as new as the index, or older than it - asked either way
    indexed(library, index_date)
    a_copy(library, '75354806 Wolfbird - OpalApparition (14 Dec 2024).epub')

    fetched, asked = a_rescue(library, monkeypatch, answer)

    names = [q['name'] for q, _ in asked]
    assert names[-1] == server.INFERRED_DATE_QUESTION
    assert server.FICHUB_UNDATED_QUESTION not in names
    question, default = asked[-1]
    assert question['source'] == 'FicHub' and question['date'] == '2026-04-27'
    assert default == {'choice': 'no'}
    assert fetched == (['EPUB'] if replaced else [])

# endregion
