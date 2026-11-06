"""A copy of a work the index had no entry for when the run began.

With no entry of its own, nothing but the copy's name says which version it holds, so the run
asks before replacing it - from AO3 or from FicHub, overwriting or not - recommending an answer
from the date in the name and saying why, but taking **no** whenever nobody answers. And every
question a run asks is recorded with how it was answered.
"""

import json
import os
from unittest.mock import MagicMock

import pytest

from source_code import parse_text, runs, server, strings
from source_code.actions import shared
from source_code.ao3 import Ao3


LINK = 'https://archiveofourown.org/works/75354806'


# region reading a date out of a file's name, as the Resolve issues window does

@pytest.mark.parametrize('name, date', [
    ('123 A Fic - Me 2024-12-14.epub', '2024-12-14'),
    ('123 A Fic 14 Dec 2023.pdf', '2023-12-14'),
    ('123 A Fic Dec 14, 2022.html', '2022-12-14'),
    ('123 A Fic 2021_03_04.html', '2021-03-04'),
    ('123 A Fic 20200102.html', '2020-01-02'),
    ('123 A Fic.html', ''),
    ('123 A Fic 2024-13-40.html', ''),
    # the work number the name starts with is never read as a date
    ('20240304 A Fic.html', ''),
    ('works/123 A Fic 2024-12-14.epub', '2024-12-14'),
])
def test_a_date_is_read_out_of_a_file_name_the_way_infer_date_reads_one(name, date):
    assert parse_text.infer_date_from_filename(name) == date

# endregion

# region what is recommended, and why - for each copy on its own

def test_a_newer_incoming_version_is_recommended_with_its_reason():
    choice, reason = server.unindexed_copy_advice('2026-05-10', '2026-01-01', 'AO3')
    assert choice == 'yes'
    assert reason == ('recommended: yes - the AO3 version (2026-05-10) is newer than the date in '
                      'your file name (2026-01-01)')


def test_the_same_date_is_recommended_only_on_a_run_that_overwrites():
    assert server.unindexed_copy_advice('2026-05-10', '2026-05-10', 'AO3')[0] == 'no'
    choice, reason = server.unindexed_copy_advice('2026-05-10', '2026-05-10', 'AO3', overwriting=True)
    assert choice == 'yes' and 'this run overwrites existing downloads' in reason


@pytest.mark.parametrize('overwriting', [False, True])
def test_an_older_incoming_version_is_never_recommended(overwriting):
    choice, reason = server.unindexed_copy_advice('2026-05-10', '2026-06-01', 'FicHub', overwriting)
    assert choice == 'no' and reason.startswith('recommended: no - your file name says 2026-06-01')


@pytest.mark.parametrize('overwriting', [False, True])
def test_a_copy_whose_name_holds_no_date_is_never_recommended_for_replacing(overwriting):
    choice, reason = server.unindexed_copy_advice('2026-05-10', '', 'AO3', overwriting)
    assert choice == 'no' and 'no date could be read from your file name' in reason


def test_an_incoming_version_with_no_date_is_not_recommended():
    assert server.unindexed_copy_advice('', '2026-01-01', 'AO3')[0] == 'no'

# endregion

# region the question

def answering_job(answer=None):
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB'], 'Someone')
    asked = []

    def ask(question, default):
        asked.append((question, default))
        return dict(default) if answer is None else {'choice': answer}
    job.ask = ask
    return job, asked


def a_plan(copies: dict, date='2026-04-27', overwrite=False):
    link = 'https://archiveofourown.org/works/1'
    records = [{'id': '1', 'link': link, 'date_updated': date}]
    existing = {'1': {fmt: {'path': f'works/{name}', 'date': parse_text.get_date_from_filename(name)}
                      for fmt, name in copies.items()}}
    plan = shared.plan_downloads(records, existing, list(copies), overwrite=overwrite)
    return link, records, existing, plan


def test_a_work_with_no_earlier_entry_is_asked_about_judging_each_copy():
    link, records, existing, plan = a_plan({'EPUB': '1 A 2026-01-01.epub', 'HTML': '1 A.html'})
    job, asked = answering_job()

    server.ask_about_unindexed_copies(job, records, existing, plan, ['EPUB', 'HTML'], set())

    question, default = asked[0]
    assert question['name'] == server.UNINDEXED_COPY_QUESTION
    assert question['ids'] == ['1'] and question['formats'] == ['EPUB', 'HTML']
    assert question['date'] == '2026-04-27'
    assert question['fileDates'] == {'EPUB': '2026-01-01', 'HTML': ''}
    assert question['recommended'] == 'recommended' and question['recommendedFormats'] == ['EPUB']
    assert 'is newer than' in question['reasons']['EPUB']
    assert 'no date could be read' in question['reasons']['HTML']
    assert question['choices'] == ['recommended', 'yes', 'no']
    assert question['source'] == 'AO3'
    assert default == {'choice': 'no'}


@pytest.mark.parametrize('overwrite', [False, True])
def test_nobody_answering_keeps_the_copy_overwriting_or_not_even_when_yes_is_recommended(overwrite):
    # the version check would have replaced it (behind), and overwriting would too
    link, records, existing, plan = a_plan({'EPUB': '1 A 2026-01-01.epub'}, overwrite=overwrite)
    job, asked = answering_job()

    server.ask_about_unindexed_copies(job, records, existing, plan, ['EPUB'], set(), overwriting=overwrite)

    assert asked[0][0]['recommended'] == 'yes' and asked[0][0]['choices'] == ['yes', 'no']
    assert link not in plan['superseded'] and link not in plan['stale']
    assert plan['keep'] == {link: {'EPUB'}}


def test_yes_replaces_a_copy_the_version_check_would_have_kept():
    # named as newer than AO3's version: kept as current without the question
    link, records, existing, plan = a_plan({'EPUB': '1 A 2026-06-01.epub'})
    job, asked = answering_job('yes')

    server.ask_about_unindexed_copies(job, records, existing, plan, ['EPUB'], set())

    assert asked[0][0]['recommended'] == 'no'
    assert plan['superseded'][link] == {'EPUB': 'works/1 A 2026-06-01.epub'}
    assert link in plan['stale']


def test_an_undated_copy_is_asked_about_here_rather_than_by_the_undated_question():
    link, records, existing, plan = a_plan({'EPUB': '1 A.epub'})
    job, asked = answering_job()

    server.ask_about_unindexed_copies(job, records, existing, plan, ['EPUB'], set())

    assert asked[0][0]['recommended'] == 'no'
    assert link not in plan['undated']


def test_a_work_the_index_had_before_the_run_is_judged_by_its_entry_and_not_asked_about():
    link, records, existing, plan = a_plan({'EPUB': '1 A 2026-01-01.epub'})
    job, asked = answering_job()

    server.ask_about_unindexed_copies(job, records, existing, plan, ['EPUB'], {'1'})

    assert asked == []
    assert link in plan['stale']


def test_a_format_with_no_copy_is_fetched_whatever_is_answered_about_the_others():
    link, records, existing, plan = a_plan({'EPUB': '1 A 2026-01-01.epub'})
    job, asked = answering_job('no')

    server.ask_about_unindexed_copies(job, records, existing, plan, ['EPUB', 'HTML'], set())

    assert asked[0][0]['formats'] == ['EPUB']
    # kept, but still downloaded for the html it has none of
    assert plan['keep'] == {link: {'EPUB'}}
    assert link in plan['stale']

# endregion

# region the index as the run found it

def test_the_index_as_the_run_found_it_leaves_out_what_the_run_wrote(fake_fileops):
    folder = os.path.join(fake_fileops.downloadfolder, strings.INDEXING_FOLDER_NAME)
    os.makedirs(folder)
    with open(os.path.join(folder, '7 Old - A.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '7', 'title': 'Old'}, f)
    ao3 = Ao3(MagicMock(), fake_fileops, ['EPUB'], None, False, False)

    ao3.save_metadata({'id': '8', 'link': 'https://archiveofourown.org/works/8',
                       'title': 'New', 'authors': ['B']})

    assert ao3.indexed_before_run() == {'7'}


def test_an_import_and_a_stand_in_downloader_ask_nothing(fake_fileops):
    job = server.Job(server.ACTION_IMPORT, ['EPUB'], 'Someone')
    job.ao3 = Ao3(MagicMock(), fake_fileops, ['EPUB'], None, False, False)
    assert server.indexed_before(job) is None

    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB'], 'Someone')
    job.ao3 = MagicMock()
    assert server.indexed_before(job) is None

# endregion

# region from AO3: the shared check step

@pytest.fixture
def library(fake_fileops):
    for name in (strings.INDEXING_FOLDER_NAME, strings.WORKS_FOLDER_NAME):
        os.makedirs(os.path.join(fake_fileops.downloadfolder, name), exist_ok=True)
    return fake_fileops


def a_copy(library, name: str) -> None:
    with open(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME, name), 'w') as f:
        f.write('what you had')


def a_scan(library, answer=None, overwrite=False):
    job, asked = answering_job(answer)
    job.options['overwrite'] = overwrite
    job.ao3 = Ao3(MagicMock(), library, ['EPUB'], None, False, False)
    return job, asked


@pytest.mark.parametrize('overwrite', [False, True])
def test_a_scan_asks_about_a_copy_of_a_work_it_has_just_indexed_for_the_first_time(library, overwrite):
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-01-01.epub')
    a_copy(library, '75354806 Wolfbird - OpalApparition.html')
    job, asked = a_scan(library, overwrite=overwrite)
    # the walk indexes it: the first index write of the run
    job.ao3.save_metadata({'id': '75354806', 'link': LINK, 'title': 'Wolfbird',
                           'authors': ['OpalApparition'], 'date_updated': '2026-04-27'})
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-04-27'}]

    plan = server.plan_refresh(job, library, records, ['EPUB', 'HTML'], MagicMock())

    # one question, about this work - not the undated one, not the overwrite-older one
    assert [q['name'] for q, _ in asked] == [server.UNINDEXED_COPY_QUESTION]
    assert asked[0][0]['formats'] == ['EPUB', 'HTML']
    # the epub is behind; the html's name says nothing
    assert asked[0][0]['recommendedFormats'] == ['EPUB']
    assert plan['keep'] == {LINK: {'EPUB', 'HTML'}}
    assert LINK not in plan['stale']


def test_a_scan_judges_a_work_it_already_had_by_its_entry_as_before(library):
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    with open(os.path.join(folder, '75354806 Wolfbird - OpalApparition.json'), 'w', encoding='utf-8') as f:
        json.dump({'id': '75354806', 'link': LINK, 'title': 'Wolfbird', 'date_updated': '2026-01-01'}, f)
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-01-01.epub')
    job, asked = a_scan(library)
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-04-27'}]

    plan = server.plan_refresh(job, library, records, ['EPUB'], MagicMock())

    assert asked == []
    assert LINK in plan['stale']

# endregion

# region from FicHub

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'fichub', 'wolfbird.json')


def wolfbird() -> dict:
    with open(FIXTURE, encoding='utf-8') as f:
        return json.load(f)


def work_files(library) -> list[str]:
    return sorted(os.listdir(os.path.join(library.downloadfolder, strings.WORKS_FOLDER_NAME)))


@pytest.mark.fichub
@pytest.mark.parametrize('answer, replaced', [(None, False), ('no', False), ('yes', True)])
def test_fichub_asks_before_replacing_a_copy_of_a_work_with_no_entry(library, monkeypatch,
                                                                    answer, replaced):
    # FicHub's copy is 2026-04-27; yours is named as newer, and there is no entry to say more
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-10.epub')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, given, filetype: fetched.append(filetype) or b'fichub')
    job, asked = answering_job()
    job.ao3 = ao3 = Ao3(MagicMock(), library, ['EPUB'], None, False, False)
    ao3.failures = [{'id': '75354806', 'link': LINK, 'error': 'not a work file (404)'}]

    def ask(question, default):
        asked.append((question, default))
        if question['name'] == server.UNINDEXED_COPY_QUESTION:
            return dict(default) if answer is None else {'choice': answer}
        return {'choice': 'yes'}
    job.ask = ask

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    question, default = [x for x in asked if x[0]['name'] == server.UNINDEXED_COPY_QUESTION][0]
    assert question['source'] == 'FicHub' and question['recommended'] == 'no'
    assert question['fileDates'] == {'EPUB': '2026-05-10'} and question['date'] == '2026-04-27'
    assert default == {'choice': 'no'}
    if replaced:
        assert fetched == ['EPUB']
        # named with FicHub's own date
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub']
    else:
        assert fetched == []
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-05-10.epub']

# endregion

# region how each question was answered

class Recorded:
    pending_how = None


def a_recorded_job(**kwargs):
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB'], 'Someone', **kwargs)
    job.record = Recorded()
    return job


def test_an_answer_given_is_recorded_as_given(monkeypatch):
    job = a_recorded_job()
    job.emit = lambda event: (setattr(job, 'answer', {'choice': 'yes'}), job.answered.set())
    job.ask({'name': server.FICHUB_QUESTION}, {'choice': 'yes'})
    assert job.record.pending_how == server.ANSWERED_BY_YOU


def test_a_question_nobody_answers_in_time_is_recorded_as_timed_out(monkeypatch):
    monkeypatch.setattr(server, 'question_timeout_seconds', lambda: 0.01)
    job = a_recorded_job()
    job.emit = MagicMock()
    job.ask({'name': server.FICHUB_QUESTION}, {'choice': 'yes'})
    assert job.record.pending_how == server.ANSWERED_TIMED_OUT


def test_a_background_run_s_default_and_a_stop_are_recorded_as_such():
    job = a_recorded_job(background=True)
    job.ask({'name': server.FICHUB_QUESTION}, {'choice': 'yes'})
    assert job.record.pending_how == server.ANSWERED_BACKGROUND_DEFAULT

    job = a_recorded_job()
    job.cancel.set()
    job.ask({'name': server.FICHUB_QUESTION}, {'choice': 'yes'})
    assert job.record.pending_how == server.ANSWERED_STOPPED


def test_an_earlier_attempt_s_answer_is_recorded_as_reused_but_never_for_a_per_work_question():
    job = a_recorded_job()
    job.prior_answers = {server.FICHUB_QUESTION: {'choice': 'no'},
                         server.UNINDEXED_COPY_QUESTION: {'choice': 'yes'}}
    assert job.ask({'name': server.FICHUB_QUESTION}, {'choice': 'yes'}) == {'choice': 'no'}
    assert job.record.pending_how == server.ANSWERED_EARLIER

    job.cancel.set()
    # one work's answer is never another's: asked again, and a stop keeps the copy
    assert job.ask({'name': server.UNINDEXED_COPY_QUESTION}, {'choice': 'no'}) == {'choice': 'no'}


def test_the_run_s_record_keeps_how_each_question_was_answered(fake_fileops, monkeypatch):
    record = runs.RunRecord(fake_fileops, 'abc', server.ACTION_BOOKMARKS, 'Full scan', ['EPUB'], {})
    monkeypatch.setattr(record, 'save', lambda: None)
    record.pending_how = server.ANSWERED_TIMED_OUT

    record.choice({'question': server.FICHUB_QUESTION, 'choice': 'yes'})
    record.choice({'question': server.UNDATED_QUESTION, 'choice': 'skip'})

    assert record.data['choices'][0]['how'] == 'timed-out'
    # said once, for the answer it was about
    assert 'how' not in record.data['choices'][1]

# endregion

# region the version each format holds, in the index

def an_entry(library, work='1', date='2026-11-06', **fields):
    folder = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f'{work} Fic A - B.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'id': work, 'link': f'https://archiveofourown.org/works/{work}',
                   'indexes': [{'indexed_on': '2026-11-06T00:00:00+00:00', 'id': work,
                                'title': 'Fic A', 'authors': ['B'], 'date_updated': date}],
                   **fields}, f)
    return path


def read(path) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def test_each_saved_format_s_version_is_noted_on_the_entry_and_an_undated_one_taken_out(fake_fileops):
    path = an_entry(fake_fileops)
    ao3 = Ao3(MagicMock(), fake_fileops, ['EPUB'], None, False, False)

    assert ao3.note_format_dates('1', {'EPUB': '2026-11-04', 'PDF': '6 Nov 2026'})
    assert read(path)['format_dates'] == {'EPUB': '2026-11-04', 'PDF': '2026-11-06'}
    # the same again writes nothing
    assert not ao3.note_format_dates('1', {'EPUB': '2026-11-04'})
    assert ao3.note_format_dates('1', {'EPUB': None})
    assert read(path)['format_dates'] == {'PDF': '2026-11-06'}
    # a work with no entry has nowhere to note it
    assert not ao3.note_format_dates('2', {'EPUB': '2026-11-04'})


def test_a_new_reading_never_writes_over_the_format_dates_or_adds_them_to_the_history(fake_fileops):
    path = an_entry(fake_fileops, format_dates={'EPUB': '2026-11-04'})
    ao3 = Ao3(MagicMock(), fake_fileops, ['EPUB'], None, False, False)
    from source_code import indexing
    # a record carried forward from before the note, as a re-read does
    stale = {**indexing.flatten(read(path)), 'format_dates': {'EPUB': '2020-01-01'},
             'kudos': 5}

    ao3.save_metadata(stale)

    data = read(path)
    assert data['format_dates'] == {'EPUB': '2026-11-04'}
    assert all('format_dates' not in reading for reading in data['indexes'])


def test_a_download_notes_the_date_its_files_are_named_with(library):
    path = an_entry(library, work='75354806', date='2026-11-06')
    ao3 = Ao3(MagicMock(), library, ['PDF'], None, False, False)
    ao3.repo.download_file.return_value = b'%PDF the work'

    ao3.download_one_indexed({'id': '75354806', 'link': LINK, 'title': 'Fic A', 'authors': ['B'],
                              'date_updated': '2026-11-06'}, 50, {}, 1, 1)

    assert work_files(library) == ['75354806 Fic A - B 2026-11-06.pdf']
    assert read(path)['format_dates'] == {'PDF': '2026-11-06'}

# endregion

# region your three scenarios: an imported Fic A, left unindexed, then a full scan that overwrites

def imported(library, pdf=True) -> None:
    if pdf: a_copy(library, '75354806 Fic A - B 2026-11-06.pdf')
    a_copy(library, '75354806 Fic A - B 2026-11-03.epub')
    a_copy(library, '75354806 Fic A - B.html')


FORMATS = ['PDF', 'EPUB', 'HTML']


def test_scenario_1_an_entry_from_an_earlier_quick_scan_lets_overwriting_replace_every_copy(library):
    # a quick scan for PDF only indexed Fic A (6 Nov) and saved its PDF: now there is an entry
    imported(library)
    an_entry(library, work='75354806', date='2026-11-06', format_dates={'PDF': '2026-11-06'})
    job, asked = a_scan(library, overwrite=True)
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-11-06'}]

    plan = server.plan_refresh(job, library, records, FORMATS, MagicMock())

    # the entry judges them, and overwriting replaces them all - the undated html included -
    # without asking: none is newer than the version written
    assert asked == []
    assert sorted(plan['superseded'][LINK]) == ['EPUB', 'HTML', 'PDF']
    assert LINK in plan['stale']


@pytest.mark.parametrize('answer, replaced', [
    (None, []), ('no', []), ('recommended', ['EPUB', 'PDF']), ('yes', ['EPUB', 'HTML', 'PDF']),
])
def test_scenario_2_no_entry_so_the_full_scan_indexes_first_then_asks_about_each_copy(
        library, answer, replaced):
    imported(library)
    job, asked = a_scan(library, answer=answer, overwrite=True)
    # the full scan indexes every bookmark before downloading anything: AO3 says 6 Nov
    job.ao3.save_metadata({'id': '75354806', 'link': LINK, 'title': 'Fic A', 'authors': ['B'],
                           'date_updated': '2026-11-06'})
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-11-06'}]

    plan = server.plan_refresh(job, library, records, FORMATS, MagicMock())

    [(question, default)] = asked
    assert question['name'] == server.UNINDEXED_COPY_QUESTION
    # the pdf is the same version but this run overwrites; the epub is behind; the html's
    # name says nothing, so replacing it is never recommended
    assert question['recommendedFormats'] == ['PDF', 'EPUB']
    assert question['recommended'] == 'recommended'
    assert default == {'choice': 'no'}
    assert sorted(plan['superseded'].get(LINK, {})) == replaced
    assert sorted(plan['keep'].get(LINK, set())) == sorted(set(FORMATS) - set(replaced))


@pytest.mark.fichub
@pytest.mark.parametrize('answer, fetched_formats', [(None, []), ('recommended', ['EPUB'])])
def test_scenario_3_ao3_down_so_fichub_s_older_copy_replaces_only_what_it_is_newer_than(
        library, monkeypatch, answer, fetched_formats):
    # FicHub's copy is 2026-04-27 (its fixture). The pdf is named newer than that, the epub
    # older, the html not at all. AO3 indexed Fic A off the listing (2026-05-10) before it
    # went down, so FicHub's copy is also older than the index
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-05-10.pdf')
    a_copy(library, '75354806 Wolfbird - OpalApparition 2026-01-01.epub')
    a_copy(library, '75354806 Wolfbird - OpalApparition.html')
    fetched = []
    monkeypatch.setattr(server.fichub, 'lookup', lambda repo, link: wolfbird())
    monkeypatch.setattr(server.fichub, 'download',
                        lambda repo, given, filetype: fetched.append(filetype) or b'fichub copy')
    job, asked = answering_job()
    job.filetypes = ['JSON'] + FORMATS
    job.options['overwrite'] = True
    job.ao3 = ao3 = Ao3(MagicMock(), library, FORMATS, None, False, False)
    ao3.save_metadata({'id': '75354806', 'link': LINK, 'title': 'Wolfbird',
                       'authors': ['OpalApparition'], 'date_updated': '2026-05-10'})
    ao3.failures = [{'id': '75354806', 'link': LINK, 'error': 'AO3 is down for maintenance'}]
    index = os.path.join(library.downloadfolder, strings.INDEXING_FOLDER_NAME,
                         '75354806 Wolfbird - OpalApparition.json')

    def ask(question, default):
        asked.append((question, default))
        if question['name'] == server.UNINDEXED_COPY_QUESTION:
            return dict(default) if answer is None else {'choice': answer}
        return {'choice': 'yes'}
    job.ask = ask

    server.rescue_with_fichub(job, library, ao3, MagicMock())

    [question] = [q for q, _ in asked if q['name'] == server.UNINDEXED_COPY_QUESTION]
    assert question['source'] == 'FicHub' and question['date'] == '2026-04-27'
    assert question['recommendedFormats'] == ['EPUB']
    # not the older-copy questions: they judge by an entry this work did not have
    assert server.OVERWRITE_OLDER_QUESTION not in [q['name'] for q, _ in asked]
    assert fetched == fetched_formats
    if fetched_formats:
        # named with FicHub's own date; the old epub replaced, the pdf and html as they were
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-04-27.epub',
                                       '75354806 Wolfbird - OpalApparition 2026-05-10.pdf',
                                       '75354806 Wolfbird - OpalApparition.html']
        # the index is newer than FicHub's copy, so it stays - and says the epub is older
        data = read(index)
        assert data['indexes'][-1]['date_updated'] == '10 May 2026' or \
            data['indexes'][-1]['date_updated'].startswith('2026-05-10') or \
            parse_text.get_date_stamp(data['indexes'][-1]['date_updated']) == '2026-05-10'
        assert data['format_dates'] == {'EPUB': '2026-04-27'}
    else:
        assert work_files(library) == ['75354806 Wolfbird - OpalApparition 2026-01-01.epub',
                                       '75354806 Wolfbird - OpalApparition 2026-05-10.pdf',
                                       '75354806 Wolfbird - OpalApparition.html']

# endregion

# region scenario 4: a repair that looks up the index, then a quick scan

def test_scenario_4_a_repair_s_lookup_notes_each_file_s_own_date_on_the_new_entry(library):
    # dating skipped; the lookup made Fic A's entry from AO3, which says 8 Nov
    a_copy(library, '75354806 Fic A - B 2026-11-06.pdf')
    a_copy(library, '75354806 Fic A - B 2026-11-03.epub')
    a_copy(library, '75354806 Fic A - B.html')
    path = an_entry(library, work='75354806', date='2026-11-08')
    ao3 = Ao3(MagicMock(), library, FORMATS, None, False, False)
    record = {'id': '75354806', 'link': LINK, 'title': 'Fic A', 'authors': ['B'],
              'date_updated': '2026-11-08'}

    server.name_files_from_index(library, [record], ao3)

    # the entry says AO3's 8 Nov; each file keeps - and the entry notes - its own version
    assert read(path)['indexes'][-1]['date_updated'] == '2026-11-08'
    assert read(path)['format_dates'] == {'EPUB': '2026-11-03', 'PDF': '2026-11-06'}
    assert work_files(library) == ['75354806 Fic A - B 2026-11-03.epub',
                                   '75354806 Fic A - B 2026-11-06.pdf',
                                   '75354806 Fic A - B.html']


def test_scenario_4_the_quick_scan_after_it_judges_by_that_entry_and_asks_nothing_new(library):
    a_copy(library, '75354806 Fic A - B 2026-11-06.pdf')
    a_copy(library, '75354806 Fic A - B 2026-11-03.epub')
    a_copy(library, '75354806 Fic A - B.html')
    path = an_entry(library, work='75354806', date='2026-11-08',
                    format_dates={'EPUB': '2026-11-03', 'PDF': '2026-11-06'})
    job, asked = a_scan(library)
    records = [{'id': '75354806', 'link': LINK, 'date_updated': '2026-11-08'}]

    plan = server.plan_refresh(job, library, records, FORMATS, MagicMock())

    # the pdf and epub are behind 8 Nov and replaced. the undated html is left as it is: a
    # work behind in one format counts as behind, not undated, so nothing asks about it
    assert asked == []
    assert sorted(plan['superseded'][LINK]) == ['EPUB', 'PDF']
    assert LINK in plan['stale'] and LINK not in plan['undated']
    # a reading never touches what the entry says each format holds
    job.ao3.save_metadata({**records[0], 'title': 'Fic A', 'authors': ['B'], 'kudos': 9})
    assert read(path)['format_dates'] == {'EPUB': '2026-11-03', 'PDF': '2026-11-06'}

# endregion
