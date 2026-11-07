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


@pytest.mark.parametrize('name, recommended, why', [
    ('75354806 Wolfbird (14 Dec 2024).epub', 'yes',
     "looks dated 2024-12-14 (a guess), so we think AO3's version (2026-04-27) is newer - we recommend replacing it"),
    ('75354806 Wolfbird (27 Apr 2026).epub', 'no',
     "looks dated 2026-04-27 (a guess), the same as AO3's version - we recommend keeping yours"),
    ('75354806 Wolfbird (1 Oct 2026).epub', 'no',
     "looks dated 2026-10-01 (a guess), so we think yours is newer than AO3's version (2026-04-27) - we recommend keeping yours"),
])
@pytest.mark.parametrize('overwrite', [False, True])
def test_a_guessed_date_is_always_asked_about_with_a_recommendation_and_kept_by_default(
        name, recommended, why, overwrite, capsys):
    records, existing, plan = a_plan({'EPUB': name}, overwrite=overwrite)
    job, asked = answering_job()

    server.ask_about_unsure_copies(job, records, existing, plan, ['EPUB'], overwriting=overwrite)

    [(question, default)] = asked
    assert question['name'] == server.INFERRED_DATE_QUESTION
    assert question['formats'] == ['EPUB'] and question['date'] == '2026-04-27'
    # the same date is recommended for replacing on a run that overwrites
    expected = 'yes' if (overwrite and '27 Apr' in name) else recommended
    assert question['recommended'] == expected
    if not (overwrite and '27 Apr' in name):
        assert why in question['reasons']['EPUB']
    assert default == {'choice': 'no'}
    # nobody answering keeps the file, whatever was recommended, overwriting or not
    assert 'EPUB' not in plan['superseded'].get(LINK, {})
    assert plan['keep'] == {LINK: {'EPUB'}} and LINK not in plan['stale']


@pytest.mark.parametrize('answer, replaced', [('no', False), ('yes', True), ('recommended', True)])
def test_the_answer_decides_whether_a_file_with_a_guessed_date_is_replaced(answer, replaced):
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird (14 Dec 2024).epub'})
    job, asked = answering_job(answer)

    server.ask_about_unsure_copies(job, records, existing, plan, ['EPUB'])

    assert (LINK in plan['stale']) is replaced
    assert ('EPUB' in plan['superseded'].get(LINK, {})) is replaced
    assert LINK not in plan['undated']


def test_a_name_with_no_date_at_all_is_left_to_the_undated_question_when_not_overwriting():
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird.epub'})
    job, asked = answering_job('yes')

    server.ask_about_unsure_copies(job, records, existing, plan, ['EPUB'])

    assert asked == [] and LINK in plan['undated']


def test_an_overwriting_run_asks_before_replacing_a_file_with_no_date_at_all():
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird.epub'}, overwrite=True)
    job, asked = answering_job()

    server.ask_about_unsure_copies(job, records, existing, plan, ['EPUB'], overwriting=True)

    [(question, default)] = asked
    assert question['reasons']['EPUB'].startswith('no date can be read')
    assert question['recommended'] == 'no' and default == {'choice': 'no'}
    assert LINK not in plan['stale'] and plan['keep'] == {LINK: {'EPUB'}}


def test_an_overwriting_run_still_replaces_a_file_with_the_apps_own_date_unasked():
    records, existing, plan = a_plan({'EPUB': '75354806 Wolfbird 2026-04-27.epub'}, overwrite=True)
    job, asked = answering_job()

    server.ask_about_unsure_copies(job, records, existing, plan, ['EPUB'], overwriting=True)

    assert asked == [] and 'EPUB' in plan['superseded'][LINK]

# endregion

# region the long way round (a full scan writing no index)

@pytest.mark.parametrize('overwrite', [False, True])
@pytest.mark.parametrize('name, date, asks', [
    ('75354806 Wolfbird (14 Dec 2024).epub', None, True),
    ('75354806 Wolfbird.epub', None, True),
    # the app's own date: replaced unasked only when overwriting, or behind
    ('75354806 Wolfbird 2026-04-27.epub', '2026-04-27', False),
])
def test_the_long_way_asks_before_replacing_a_file_without_the_apps_own_date(
        fake_fileops, overwrite, name, date, asks):
    job, asked = answering_job()
    ao3 = Ao3(MagicMock(), fake_fileops, ['EPUB'], None, False, False)
    ao3.existing_copies = {'75354806': {'EPUB': {'path': f'works/{name}', 'date': date}}}
    ao3.overwriting = overwrite
    ao3.judge_copy = lambda *copy: server.judge_long_way(job, ao3, *copy)

    fetch = ao3.page_verdict(LINK, '75354806', 'EPUB', '2026-04-27')

    assert bool(asked) is asks
    if asks: assert asked[0][0]['name'] == server.INFERRED_DATE_QUESTION
    # nobody answering keeps it; an app-dated current copy is fetched only to overwrite it
    assert fetch is (overwrite and not asks)


def test_an_overwriting_long_way_asks_before_replacing_a_newer_copy(fake_fileops):
    job, asked = answering_job()
    ao3 = Ao3(MagicMock(), fake_fileops, ['EPUB'], None, False, False)
    ao3.existing_copies = {'75354806': {'EPUB': {'path': 'works/75354806 W 2026-10-01.epub',
                                                 'date': '2026-10-01'}}}
    ao3.overwriting = True
    ao3.judge_copy = lambda *copy: server.judge_long_way(job, ao3, *copy)

    assert ao3.page_verdict(LINK, '75354806', 'EPUB', '2026-04-27') is False
    assert [q['name'] for q, _ in asked] == [server.OVERWRITE_OLDER_QUESTION]

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
@pytest.mark.parametrize('name', ['75354806 Wolfbird - OpalApparition (14 Dec 2024).epub',
                                  '75354806 Wolfbird - OpalApparition (1 Oct 2026).epub',
                                  '75354806 Wolfbird - OpalApparition.epub'])
@pytest.mark.parametrize('answer, replaced', [(None, False), ('yes', True)])
def test_fichub_always_asks_before_replacing_a_file_without_the_apps_own_date(
        library, monkeypatch, index_date, name, answer, replaced):
    # FicHub's copy is 2026-04-27: as new as the index, or older than it - asked either way,
    # whether the guessed date is older, newer, or cannot be read
    indexed(library, index_date)
    a_copy(library, name)

    fetched, asked = a_rescue(library, monkeypatch, answer)

    names = [q['name'] for q, _ in asked]
    assert names[-1] == server.INFERRED_DATE_QUESTION
    question, default = asked[-1]
    assert question['source'] == 'FicHub' and question['date'] == '2026-04-27'
    assert question['recommended'] == ('yes' if '14 Dec' in name else 'no')
    assert default == {'choice': 'no'}
    assert fetched == (['EPUB'] if replaced else [])

# endregion
