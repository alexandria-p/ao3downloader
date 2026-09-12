"""Tests for ao3downloader.server — the local helper behind the web ui.

Nothing here touches the network: the download work itself is the same code the console
menu runs, which is covered by the other suites. What matters here is the plumbing around
it - what gets requested, what gets reported, and what never leaves the machine.
"""

import contextlib
import inspect
import os
import socket
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest

from source_code import exceptions, parse_text, progress, server, strings


# region resolve_filetypes

def test_resolve_filetypes_always_adds_the_forced_types():
    assert sorted(server.resolve_filetypes([])) == sorted(server.FORCED_FILETYPES)


def test_resolve_filetypes_keeps_what_was_asked_for():
    result = server.resolve_filetypes(['EPUB'])

    assert 'EPUB' in result
    for forced in server.FORCED_FILETYPES:
        assert forced in result


def test_resolve_filetypes_does_not_duplicate_a_forced_type():
    result = server.resolve_filetypes([strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML', 'HTML'])

    assert result.count('HTML') == 1
    assert result.count(strings.AO3_DOWNLOAD_TYPE_METADATA) == 1


def test_resolve_filetypes_drops_anything_unrecognised():
    # the request is not to be trusted just because the ui locks the checkboxes
    result = server.resolve_filetypes(['EPUB', 'EXE', '../../etc/passwd'])

    assert 'EXE' not in result
    assert '../../etc/passwd' not in result
    assert 'EPUB' in result


def test_resolve_filetypes_handles_a_missing_list():
    assert sorted(server.resolve_filetypes(None)) == sorted(server.FORCED_FILETYPES)


def test_only_the_metadata_is_forced():
    # everything else costs a request per work, so a metadata-only run has to be possible:
    # indexing reads the listing pages, which is a twentieth of the requests
    assert server.FORCED_FILETYPES == [strings.AO3_DOWNLOAD_TYPE_METADATA]


def test_a_metadata_only_run_downloads_no_works():
    assert server.resolve_filetypes([]) == [strings.AO3_DOWNLOAD_TYPE_METADATA]


def test_html_is_offered_by_default_but_can_be_turned_off():
    assert 'HTML' in server.DEFAULT_FILETYPES
    assert 'HTML' not in server.FORCED_FILETYPES

# endregion


# region resolve_options

def test_resolve_options_defaults_match_the_console_defaults():
    assert server.resolve_options(None) == {
        'start': 1, 'pages': 0, 'series': False, 'images': False, 'workdates': False,
        'reindex': True,
    }


def test_resolve_options_reads_what_was_asked_for():
    result = server.resolve_options(
        {'start': '5', 'pages': '8', 'series': True, 'images': True, 'workdates': True,
         'reindex': False})

    assert result == {'start': 5, 'pages': 8, 'series': True, 'images': True,
                      'workdates': True, 'reindex': False}


def test_json_is_added_back_even_when_a_request_leaves_it_out():
    # the ui locks it on, but a request is not trusted to have honoured that
    assert server.resolve_filetypes(['HTML']) == ['HTML', 'JSON']


def test_a_run_that_will_not_index_is_not_given_json():
    # json *is* the index. adding it back to a run that reads no listing would report a
    # file type the run never writes, which is worse than not offering it
    assert server.resolve_filetypes(['HTML'], force=False) == ['HTML']
    assert server.resolve_filetypes(['HTML', 'JSON'], force=False) == ['HTML', 'JSON']


def test_a_run_indexes_unless_it_was_actually_told_not_to():
    # the dangerous default is the other way round: a run that quietly skipped indexing
    # would judge everything against however stale the index happened to be
    assert server.resolve_options({})['reindex'] is True
    assert server.resolve_options({'reindex': None})['reindex'] is True
    assert server.resolve_options({'reindex': False})['reindex'] is False


def test_a_work_link_is_accepted_as_a_link_or_as_a_bare_number():
    # pasting the number off the address bar is as natural as pasting the whole url
    assert server.work_link('34816549') == 'https://archiveofourown.org/works/34816549'
    assert server.work_link('https://archiveofourown.org/works/34816549') == \
        'https://archiveofourown.org/works/34816549'
    # a chapter link, or anything else with the work number in it, still names one work
    assert server.work_link('https://archiveofourown.org/works/34816549/chapters/86677150') \
        == 'https://archiveofourown.org/works/34816549'


@pytest.mark.parametrize('value', [
    '', '   ', None,
    'https://archiveofourown.org/series/12345',
    'https://archiveofourown.org/collections/somename',
    'https://archiveofourown.org/users/Someone/bookmarks',
    'https://example.com/works/34816549',
    'not a link at all',
])
def test_anything_that_is_not_one_work_is_refused(value):
    # refused before a run starts rather than after, so a typo is an answer not a failure
    assert server.work_link(value) is None


def test_what_to_do_about_undated_files_is_not_a_setting():
    # it is asked during the run, once the count is known, rather than guessed at up front
    assert 'refreshUndated' not in server.resolve_options({})
    assert 'stampUndated' not in server.resolve_options({})


@pytest.mark.parametrize('start', ['abc', None, '', {}, -5, 0])
def test_resolve_options_starts_at_the_first_page_on_junk(start):
    assert server.resolve_options({'start': start})['start'] == 1


def test_resolve_options_ignores_a_stop_that_comes_before_the_start():
    # asking for pages 5 to 2 would otherwise fetch nothing at all
    result = server.resolve_options({'start': 5, 'pages': 2})

    assert result['start'] == 5
    assert result['pages'] == 0


@pytest.mark.parametrize('pages', ['abc', None, '', {}, -5])
def test_resolve_options_falls_back_to_all_pages_on_junk(pages):
    # 0 is the console's wording for "every page"
    assert server.resolve_options({'pages': pages})['pages'] == 0

# endregion


# region LineStream

def test_line_stream_emits_complete_lines():
    seen = []
    stream = server.LineStream(seen.append)

    stream.write('first\nsecond\n')

    assert seen == ['first', 'second']


def test_line_stream_holds_a_partial_line_until_it_ends():
    seen = []
    stream = server.LineStream(seen.append)

    stream.write('half ')
    assert seen == []

    stream.write('a line\n')
    assert seen == ['half a line']


def test_line_stream_skips_blank_lines():
    seen = []
    stream = server.LineStream(seen.append)

    stream.write('one\n\n   \ntwo\n')

    assert seen == ['one', 'two']

# endregion


# region Job

def test_job_keeps_history_for_listeners_that_connect_late():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    job.emit({'type': 'a'})
    job.emit({'type': 'b'})

    assert job.history == [{'type': 'a'}, {'type': 'b'}]


def test_job_finish_marks_done_and_closes_the_queue():
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    job.finish()

    assert job.done.is_set()
    # a None on the queue is what tells a listening stream to stop
    assert job.events.get() is None

# endregion


# region run_job

@pytest.fixture
def fake_environment(tmp_path, monkeypatch):
    """Patch out everything that would touch the disk or the network."""
    monkeypatch.chdir(tmp_path)

    fileops = MagicMock()
    fileops.downloadfolder = str(tmp_path / 'my_downloads')
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)

    with patch.object(server, 'FileOps', return_value=fileops), \
         patch.object(server, 'Repository', return_value=repo):
        yield {'fileops': fileops, 'repo': repo}


def _types(job: server.Job) -> list[str]:
    return [event['type'] for event in job.history]


def test_run_job_logs_in_and_reports_start_and_finish(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks') as run:
        server.run_job(job, 'a-password')

    run.assert_called_once()
    fake_environment['repo'].login.assert_called_once_with('someone', 'a-password')
    assert _types(job)[0] == progress.STARTED
    assert _types(job)[-1] == progress.FINISHED
    assert job.done.is_set()


def test_run_job_reports_a_failure_instead_of_raising(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')
    fake_environment['repo'].login.side_effect = ValueError('invalid username or password')

    server.run_job(job, 'wrong')

    failures = [e for e in job.history if e['type'] == progress.FAILED]
    assert len(failures) == 1
    assert 'invalid username or password' in failures[0]['error']
    assert job.done.is_set()


def test_run_job_never_records_the_password(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')
    secret = 'hunter2-should-not-appear'
    fake_environment['repo'].login.side_effect = ValueError('login failed')

    server.run_job(job, secret)

    # not in the events, and not kept on the job either
    assert secret not in repr(job.history)
    assert secret not in repr(vars(job))


def test_run_job_routes_the_update_action(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'someone')

    with patch.object(server, 'run_update') as run_update, \
         patch.object(server, 'run_bookmarks') as run_bookmarks:
        server.run_job(job, 'a-password')

    run_update.assert_called_once()
    run_bookmarks.assert_not_called()


def test_run_job_turns_printed_output_into_messages(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks', side_effect=lambda *a: print('getting metadata')):
        server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert 'getting metadata' in messages


def test_run_job_says_it_is_logging_in_before_it_tries(fake_environment):
    # logging in is the first thing a run does, and it is slow. without these lines the
    # modal opens on an empty log and looks like it has hung
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    with patch.object(server, 'run_bookmarks'):
        server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert messages[:2] == ['logging in as someone', 'successfully logged in']


def test_run_job_does_not_say_it_logged_in_when_it_did_not(fake_environment):
    fake_environment['repo'].login.side_effect = Exception('invalid username or password')
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    server.run_job(job, 'a-password')

    messages = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert 'logging in as someone' in messages
    assert 'successfully logged in' not in messages

# endregion


# region run_bookmarks / run_update

def test_run_bookmarks_targets_the_users_own_bookmarks_page(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_called_once()
    assert ao3.get_metadata.call_args.args[0] == \
        'https://archiveofourown.org/users/Someone/bookmarks'


def test_run_bookmarks_keeps_json_away_from_the_downloader(fake_environment):
    # Ao3 would look for a JSON download link on every work and fail
    job = server.Job(server.ACTION_BOOKMARKS,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB'], 'Someone')

    with patch.object(server, 'Ao3') as ao3_class, \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3_class.call_args.args[2] == ['EPUB']


def test_run_bookmarks_skips_works_already_downloaded(fake_environment):
    # this is what makes it "newly added" rather than "everything again"
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB', 'HTML'], 'Someone')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=['already/1']) as visited:
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    visited.assert_called_once()
    assert ao3.download.call_args.args[1] == ['already/1']


def test_run_job_routes_the_collections_action(fake_environment):
    job = server.Job(server.ACTION_COLLECTIONS, ['JSON'], 'Someone')

    with patch.object(server, 'run_collections') as run_collections, \
         patch.object(server, 'run_bookmarks') as run_bookmarks, \
         patch.object(server, 'run_update') as run_update:
        server.run_job(job, 'a-password')

    run_collections.assert_called_once()
    run_bookmarks.assert_not_called()
    run_update.assert_not_called()


def test_run_collections_targets_the_users_own_collections(fake_environment):
    job = server.Job(server.ACTION_COLLECTIONS, ['JSON'], 'Someone')
    ao3 = MagicMock()
    ao3.get_collections.return_value = [{'name': 'alpha'}]

    with patch.object(server, 'Ao3', return_value=ao3):
        server.run_collections(job, fake_environment['fileops'],
                               fake_environment['repo'], MagicMock())

    assert ao3.get_collections.call_args.args[0] == \
        'https://archiveofourown.org/users/Someone/collections'


def test_run_collections_downloads_no_works(fake_environment):
    # collections record work ids only; the works themselves come from the index
    job = server.Job(server.ACTION_COLLECTIONS, ['JSON', 'EPUB'], 'Someone')
    ao3 = MagicMock()
    ao3.get_collections.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3) as ao3_class:
        server.run_collections(job, fake_environment['fileops'],
                               fake_environment['repo'], MagicMock())

    assert ao3_class.call_args.args[2] == []
    ao3.download.assert_not_called()


def test_collections_is_an_accepted_action():
    assert server.ACTION_COLLECTIONS in server.ACTIONS


# region downloading from the index instead of crawling again

def _job_with(**options) -> server.Job:
    return server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                      server.resolve_options(options))


RECORDS = [{'id': '111', 'link': 'https://archiveofourown.org/works/111'}]


def test_the_index_is_used_when_nothing_needs_the_work_page():
    assert server.can_use_index(_job_with(), RECORDS) is True


def test_there_is_nothing_to_work_from_without_an_index():
    # a run with json unticked has no record of the work numbers
    assert server.can_use_index(_job_with(), []) is False


def test_embedded_images_need_the_work_page():
    # the image links are on it, and nothing else lists them
    assert server.can_use_index(_job_with(images=True), RECORDS) is False


def test_following_series_links_needs_the_work_page():
    # a series is discovered through the work, not through the bookmarks index
    assert server.can_use_index(_job_with(series=True), RECORDS) is False


def test_run_bookmarks_downloads_from_the_index_when_it_can(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], MagicMock())

    ao3.download_indexed.assert_called_once()
    ao3.download.assert_not_called()


def test_run_bookmarks_reports_the_works_that_would_not_download(fake_environment):
    # a run that leaves gaps should name them, not leave it to be found in the log
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS
    ao3.failures = [{'id': '111', 'link': 'https://archiveofourown.org/works/111',
                     'error': 'deleted'}]
    reported: list[dict] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], reported.append)

    failures = [e for e in reported if e['type'] == progress.FAILURES]
    assert len(failures) == 1
    assert failures[0]['failures'][0]['id'] == '111'


def test_run_bookmarks_says_nothing_when_every_work_came_down(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS
    ao3.failures = []
    reported: list[dict] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], reported.append)

    assert not [e for e in reported if e['type'] == progress.FAILURES]


def test_run_bookmarks_walks_the_listing_when_images_were_asked_for(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'images': True}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = RECORDS

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]), \
         patch.object(server, 'plan_refresh',
                      return_value={'stale': [], 'undated': [], 'superseded': {}}):
        server.run_bookmarks(job, fake_environment['fileops'],
                             fake_environment['repo'], MagicMock())

    ao3.download.assert_called_once()
    ao3.download_indexed.assert_not_called()

# endregion


# region stopping mid-run to ask a question

QUESTION = {'name': 'undated', 'count': 12, 'choices': list(server.UNDATED_CHOICES)}
DEFAULT = {'choice': server.UNDATED_SKIP, 'date': ''}


def a_job() -> server.Job:
    return server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')


def test_a_question_gets_the_answer_that_comes_back():
    job = a_job()
    threading.Timer(
        0.05, lambda: job.reply({'choice': server.UNDATED_REFRESH, 'date': ''})).start()

    answer = job.ask(QUESTION, DEFAULT)

    assert answer['choice'] == server.UNDATED_REFRESH


def test_asking_tells_the_ui_what_is_being_asked():
    job = a_job()
    job.cancel.set()  # so the wait ends at once

    job.ask(QUESTION, DEFAULT)

    asked = [e for e in job.history if e['type'] == progress.QUESTION]
    assert asked[0]['count'] == 12
    assert asked[0]['choices'] == list(server.UNDATED_CHOICES)


def test_a_stop_releases_a_run_waiting_on_a_question():
    # a run paused on a question the user walked away from still has to be stoppable
    job = a_job()
    job.cancel.set()

    assert job.ask(QUESTION, DEFAULT) == DEFAULT


def test_a_question_nobody_answers_gives_up_rather_than_waiting_for_ever(monkeypatch):
    # a tab closed without stopping the run must not leave this thread waiting on an
    # answer that can never arrive
    monkeypatch.setattr(server, 'ANSWER_TIMEOUT_SECONDS', 0)

    assert a_job().ask(QUESTION, DEFAULT) == DEFAULT


def test_the_default_is_always_the_option_that_changes_nothing():
    # whatever goes wrong, a run must not rename or refetch a library on its own
    assert DEFAULT['choice'] == server.UNDATED_SKIP


def answering(job_id, body) -> dict:
    sent: dict = {}
    handler = MagicMock()
    handler.read_json.return_value = body
    handler.send_json.side_effect = lambda status, b: sent.update(status=status, body=b)
    server.Handler.answer_job(handler, job_id)
    return sent


@contextlib.contextmanager
def registered(job: server.Job):
    with server.Handler.jobs_lock:
        server.Handler.jobs[job.id] = job
    try:
        yield job
    finally:
        with server.Handler.jobs_lock:
            server.Handler.jobs.pop(job.id, None)


def holding(job_id, hold: bool) -> dict:
    sent: dict = {}
    handler = MagicMock()
    handler.send_json.side_effect = lambda status, b: sent.update(status=status, body=b)
    server.Handler.hold_job(handler, job_id, hold)
    return sent


def test_pausing_a_run_only_sets_the_flag_the_run_reads():
    # the endpoint must answer at once rather than waiting for the run to reach a safe
    # point, or the browser would sit on a pending request for the length of a download
    with registered(a_job()) as job:
        sent = holding(job.id, True)

        assert sent['status'] == 202
        assert sent['body'] == {'paused': True}
        assert job.held.is_set()


def test_resuming_clears_it_again():
    with registered(a_job()) as job:
        holding(job.id, True)
        holding(job.id, False)

        assert not job.held.is_set()


def test_a_paused_run_can_still_be_stopped():
    # the two buttons must not be able to wedge each other: a run nobody resumes has to
    # still be stoppable, and the run itself notices the stop while it waits
    with registered(a_job()) as job:
        holding(job.id, True)
        job.cancel.set()

        assert job.cancel.is_set()
        assert job.held.is_set()


def test_resuming_a_run_nobody_paused_does_nothing_at_all():
    with registered(a_job()) as job:
        sent = holding(job.id, False)

        assert sent['status'] == 202
        assert not job.held.is_set()


def test_pausing_a_job_that_is_not_there_says_so():
    sent = holding('no-such-job', True)

    assert sent['status'] == 404


def test_a_new_run_does_not_start_out_paused():
    assert not a_job().held.is_set()


def test_an_answer_reaches_the_run_that_asked():
    with registered(a_job()) as job:
        sent = answering(job.id, {'choice': server.UNDATED_STAMP, 'date': '2024-06-01'})

        assert sent['status'] == 202
        assert job.answer == {'choice': server.UNDATED_STAMP, 'date': '2024-06-01'}


@pytest.mark.parametrize('choice', ['', None, 'delete everything', 'Stamp'])
def test_an_answer_that_is_not_one_of_the_choices_is_refused(choice):
    # a run waiting on an answer must not be handed something it cannot act on
    with registered(a_job()) as job:
        sent = answering(job.id, {'choice': choice})

        assert sent['status'] == 400
        assert not job.answered.is_set()


@pytest.mark.parametrize('given', ['not a date', '2024-13-45', 'today', None, ''])
def test_a_date_that_cannot_be_read_does_not_reach_the_run(given):
    # renaming a library after a half-understood date would be worse than doing nothing
    with registered(a_job()) as job:
        answering(job.id, {'choice': server.UNDATED_STAMP, 'date': given})

        assert job.answer['date'] == ''


def test_answering_a_job_that_is_gone_says_so():
    assert answering('no-such-job', {'choice': server.UNDATED_SKIP})['status'] == 404

# endregion


# region what to do about files with no date

def asked_job(answer: dict) -> MagicMock:
    job = MagicMock()
    job.ask.return_value = answer
    return job


def undated_plan(links):
    return {'stale': [], 'undated': list(links), 'superseded': {}}


def test_nothing_is_asked_when_every_file_already_has_a_date(fake_environment):
    job = asked_job(DEFAULT)

    with patch.object(server.shared, 'plan_downloads', return_value=undated_plan([])):
        refresh, stamped = server.settle_undated(
            job, fake_environment['fileops'], RECORDS, {}, ['HTML'])

    job.ask.assert_not_called()
    assert (refresh, stamped) == (False, 0)


def test_choosing_to_skip_leaves_them_exactly_as_they_are(fake_environment):
    job = asked_job({'choice': server.UNDATED_SKIP, 'date': ''})

    with patch.object(server.shared, 'plan_downloads', return_value=undated_plan(['a'])), \
         patch.object(server.shared, 'stamp_undated_works') as stamp:
        refresh, stamped = server.settle_undated(
            job, fake_environment['fileops'], RECORDS, {}, ['HTML'])

    stamp.assert_not_called()
    assert (refresh, stamped) == (False, 0)


def test_choosing_to_refetch_makes_them_count_as_out_of_date(fake_environment):
    job = asked_job({'choice': server.UNDATED_REFRESH, 'date': ''})

    with patch.object(server.shared, 'plan_downloads', return_value=undated_plan(['a'])), \
         patch.object(server.shared, 'stamp_undated_works') as stamp:
        refresh, stamped = server.settle_undated(
            job, fake_environment['fileops'], RECORDS, {}, ['HTML'])

    stamp.assert_not_called()
    assert refresh is True


def test_choosing_to_date_them_renames_them_and_asks_for_no_downloads(fake_environment):
    job = asked_job({'choice': server.UNDATED_STAMP, 'date': '2024-06-01'})

    with patch.object(server.shared, 'plan_downloads',
                      return_value=undated_plan([RECORDS[0]['link']])), \
         patch.object(server.shared, 'stamp_undated_works',
                      return_value={'renamed': 7, 'skipped': 0}) as stamp:
        refresh, stamped = server.settle_undated(
            job, fake_environment['fileops'], RECORDS, {}, ['HTML'])

    assert stamp.call_args.args[3] == '2024-06-01'
    assert (refresh, stamped) == (False, 7)


def test_only_the_works_that_were_asked_about_are_dated(fake_environment):
    # what is handed over to be renamed is the works the question named, not the whole
    # folder scan it was planned from - which holds every download, not just this run's
    job = asked_job({'choice': server.UNDATED_STAMP, 'date': '2024-06-01'})
    whole_folder = {'111': {'HTML': {'path': 'a.html', 'date': None}},
                    '999': {'HTML': {'path': 'b.html', 'date': None}}}

    with patch.object(server.shared, 'plan_downloads',
                      return_value=undated_plan([RECORDS[0]['link']])), \
         patch.object(server.shared, 'stamp_undated_works',
                      return_value={'renamed': 1, 'skipped': 0}) as stamp:
        server.settle_undated(
            job, fake_environment['fileops'], RECORDS, whole_folder, ['HTML'])

    assert stamp.call_args.args[2] == {'111'}


def test_a_work_the_run_is_refetching_anyway_is_not_dated(fake_environment):
    # a work behind in one format and undated in another counts as stale, not undated, so
    # it is not in the count the user was shown and must not be renamed under their answer
    job = asked_job({'choice': server.UNDATED_STAMP, 'date': '2024-06-01'})
    records = RECORDS + [{'id': '222', 'link': 'https://archiveofourown.org/works/222'}]

    with patch.object(server.shared, 'plan_downloads',
                      return_value={'stale': [records[1]['link']],
                                    'undated': [records[0]['link']], 'superseded': {}}), \
         patch.object(server.shared, 'stamp_undated_works',
                      return_value={'renamed': 1, 'skipped': 0}) as stamp:
        server.settle_undated(job, fake_environment['fileops'], records, {}, ['HTML'])

    assert stamp.call_args.args[2] == {'111'}


def test_choosing_to_date_them_without_a_usable_date_changes_nothing(fake_environment):
    job = asked_job({'choice': server.UNDATED_STAMP, 'date': ''})

    with patch.object(server.shared, 'plan_downloads', return_value=undated_plan(['a'])), \
         patch.object(server.shared, 'stamp_undated_works') as stamp:
        refresh, stamped = server.settle_undated(
            job, fake_environment['fileops'], RECORDS, {}, ['HTML'])

    stamp.assert_not_called()
    assert (refresh, stamped) == (False, 0)


def test_the_question_is_asked_before_anything_is_downloaded(fake_environment):
    # asking afterwards would be too late to act on
    order: list[str] = []
    job = MagicMock()
    job.ask.side_effect = lambda q, d: order.append('asked') or DEFAULT

    with patch.object(server.shared, 'scan_downloaded_works', return_value={}), \
         patch.object(server.shared, 'plan_downloads',
                      side_effect=lambda *a, **k: order.append('planned') or undated_plan(['a'])):
        server.plan_refresh(job, fake_environment['fileops'], RECORDS, ['HTML'], MagicMock())

    assert order.index('asked') < order.index('planned', order.index('asked'))

# endregion


# region the settings a run will use

def test_read_settings_reports_what_the_run_will_actually_use(tmp_path):
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'config' / 'settings.ini')
    fileops.downloadfolder = str(tmp_path / 'my_downloads')
    fileops.get_ini_value_integer.side_effect = lambda key, default: {
        strings.INI_WAIT_TIME: 15, strings.INI_NAME_LENGTH: 50,
        strings.INI_MAX_RETRIES: 0, strings.INI_MAX_TIMEOUTS: 3}[key]
    fileops.get_ini_value.return_value = strings.FILE_NAME_PATTERN
    fileops.get_ini_value_boolean.return_value = False

    result = server.read_settings(fileops)

    assert result['extraWaitTime'] == 15
    assert result['fileNameLength'] == 50
    # the whole breakdown, date included, since that is what a file actually looks like
    assert result['fileNamePattern'] == \
        '{worknum} {title} - {author} ' + strings.DATE_STAMP_PLACEHOLDER


def test_read_settings_shows_the_naming_as_a_real_example(tmp_path):
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'settings.ini')
    fileops.downloadfolder = 'downloads'
    fileops.get_ini_value_integer.side_effect = lambda key, default: (
        50 if key == strings.INI_NAME_LENGTH else 0)
    fileops.get_ini_value_boolean.return_value = False

    example = server.read_settings(fileops)['fileNameExample']

    assert parse_text.get_work_number_from_filename(example) == '34816549'
    assert parse_text.get_date_from_filename(example) == '2026-08-23'


def test_the_example_obeys_the_length_that_is_configured(tmp_path):
    # it is built through the real truncation, so a short limit shows a short name
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'settings.ini')
    fileops.downloadfolder = 'downloads'
    fileops.get_ini_value_integer.side_effect = lambda key, default: (
        30 if key == strings.INI_NAME_LENGTH else 0)
    fileops.get_ini_value_boolean.return_value = False

    example = server.read_settings(fileops)['fileNameExample']

    assert len(os.path.splitext(example)[0]) == 30
    # and the date is still the part that survives
    assert parse_text.get_date_from_filename(example) == '2026-08-23'


def test_read_settings_says_which_settings_file_is_in_force(tmp_path):
    # a helper left running from an earlier session is the usual reason settings look
    # ignored, so naming the file it read is what makes that visible
    fileops = MagicMock()
    fileops.inifile = str(tmp_path / 'config' / 'settings.ini')
    fileops.downloadfolder = 'downloads'
    fileops.get_ini_value_integer.return_value = 0
    fileops.get_ini_value.return_value = ''
    fileops.get_ini_value_boolean.return_value = False

    result = server.read_settings(fileops)

    assert result['file'] == os.path.abspath(str(tmp_path / 'config' / 'settings.ini'))
    # relative in the ini, absolute here, so there is no doubt where fics land
    assert os.path.isabs(result['downloadFolder'])

# endregion


# region indexing one collection by link

def test_indexing_a_collection_by_link_is_an_accepted_action():
    assert server.ACTION_COLLECTION in server.ACTIONS
    # it is the one action that cannot work out its own link from the username
    assert server.ACTION_COLLECTION in server.ACTIONS_NEEDING_URL


def test_run_collection_indexes_the_link_it_was_given(fake_environment):
    job = server.Job(server.ACTION_COLLECTION, ['JSON'], 'Someone',
                     url='https://archiveofourown.org/collections/yuletide2024')
    ao3 = MagicMock()
    ao3.get_collection.return_value = [{'name': 'yuletide2024'}]

    with patch.object(server, 'Ao3', return_value=ao3):
        server.run_collection(job, fake_environment['fileops'],
                              fake_environment['repo'], MagicMock())

    assert ao3.get_collection.call_args.args[0] == \
        'https://archiveofourown.org/collections/yuletide2024'


def test_run_collection_downloads_no_works(fake_environment):
    job = server.Job(server.ACTION_COLLECTION, ['JSON'], 'Someone',
                     url='https://archiveofourown.org/collections/yuletide2024')
    ao3 = MagicMock()
    ao3.get_collection.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3) as constructor:
        server.run_collection(job, fake_environment['fileops'],
                              fake_environment['repo'], MagicMock())

    assert constructor.call_args.args[2] == []
    ao3.download.assert_not_called()


@pytest.mark.parametrize('url', [
    '',
    'https://example.com/collections/yuletide',
    'https://archiveofourown.org/users/Someone/collections',
    'https://archiveofourown.org/works/123',
])
def test_a_link_that_is_not_one_collection_is_refused_before_the_job_starts(url):
    # answering the request is more use than a job that starts and immediately fails
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {
        'action': server.ACTION_COLLECTION, 'username': 'Someone',
        'password': 'a-password', 'url': url}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    server.Handler.do_POST(handler)

    assert sent['status'] == 400
    assert 'collection' in sent['body']['error'].lower()


def test_a_collection_link_deeper_than_the_dashboard_is_accepted():
    # whatever page of the collection was open when the link was copied
    assert parse_text.get_collection_name(
        'https://archiveofourown.org/collections/yuletide2024/works?page=2') == 'yuletide2024'

# endregion


INCOMPLETE = {'id': '111', 'link': 'https://archiveofourown.org/works/111',
              'title': 'A Fic', 'chapters_published': 3, 'chapters_total': None}
FINISHED = {'id': '222', 'link': 'https://archiveofourown.org/works/222',
            'title': 'Done', 'chapters_published': 5, 'chapters_total': 5}


SKIP_UNDATED = {'choice': server.UNDATED_SKIP, 'date': ''}


def updating(ao3, index, **patches):
    """Run the update action with the index stubbed out, and nothing touching disk."""

    return [
        patch.object(server, 'Ao3', return_value=ao3),
        patch.object(server.shared, 'read_index', return_value=index),
        patch.object(server.shared, 'scan_downloaded_works',
                     return_value=patches.get('existing', {})),
        patch.object(server.shared, 'plan_downloads',
                     return_value=patches.get('plan',
                                              {'stale': [], 'undated': [], 'superseded': {}})),
        # a run asking about undated files waits for a reply, which would hang a test that
        # is not about the question. the ones that are drive Job.ask directly.
        patch.object(server.Job, 'ask', return_value=patches.get('answer', SKIP_UNDATED)),
    ]


def run_update_with(fake_environment, ao3, index, report=None, job=None, **patches):
    job = job or server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    with contextlib.ExitStack() as stack:
        for item in updating(ao3, index, **patches):
            stack.enter_context(item)
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'],
                          report or MagicMock())


def test_run_update_works_from_the_index_not_from_the_files_on_disk(fake_environment):
    # nothing is parsed out of an ebook any more, and no listing is walked to find works
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    with patch.object(server.shared, 'get_files_of_type') as get_files:
        run_update_with(fake_environment, ao3, [INCOMPLETE])

    get_files.assert_not_called()
    ao3.download.assert_not_called()


def test_run_update_only_re_reads_the_works_the_index_calls_unfinished(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE, FINISHED])

    asked = [call.args[0]['id'] for call in ao3.refresh_one.call_args_list]
    assert asked == ['111']


def test_run_update_asks_ao3_for_nothing_when_the_index_lists_nothing_unfinished(
        fake_environment):
    ao3 = MagicMock()
    ao3.failures = []

    run_update_with(fake_environment, ao3, [FINISHED])

    ao3.refresh_one.assert_not_called()
    ao3.download_one_indexed.assert_not_called()


def test_run_update_downloads_an_undated_copy_when_that_is_what_was_asked_for(
        fake_environment):
    # an undated file has no date to compare against, so nothing can judge it. the answer
    # to the question decides, and 'refresh' means treat every one of them as behind
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(
        fake_environment, ao3, [INCOMPLETE],
        existing={'111': {'HTML': {'path': 'a.html', 'date': None}}},
        answer={'choice': server.UNDATED_REFRESH, 'date': ''},
        plan={'stale': ['https://archiveofourown.org/works/111'], 'undated': [],
              'superseded': {}})

    fetched = ao3.download_one_indexed.call_args.args[0]
    assert fetched['id'] == '111'


def test_run_update_leaves_an_undated_copy_alone_when_that_is_what_was_asked_for(
        fake_environment):
    # 'skip' is the default and the safe answer: an undated copy is left exactly as it is
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(
        fake_environment, ao3, [INCOMPLETE],
        existing={'111': {'HTML': {'path': 'a.html', 'date': None}}},
        plan={'stale': [], 'undated': ['https://archiveofourown.org/works/111'],
              'superseded': {}})

    ao3.download_one_indexed.assert_not_called()


def test_run_update_re_reads_the_index_even_for_works_it_will_not_download(
        fake_environment):
    # the index entry is rewritten for every unfinished fic; only the download is conditional
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE],
                    existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    ao3.refresh_one.assert_called_once()
    ao3.download_one_indexed.assert_not_called()


def test_run_update_leaves_a_work_alone_when_nothing_about_it_moved(fake_environment):
    # a repeat run should cost the re-reads and nothing else
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE],
                    existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    ao3.download_one_indexed.assert_not_called()


def test_run_update_downloads_a_work_it_has_no_copy_of(fake_environment):
    # unchanged, but missing from the folder entirely
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], existing={})

    fetched = ao3.download_one_indexed.call_args.args[0]
    assert fetched['id'] == '111'


def test_run_update_finishes_one_fic_before_starting_the_next(fake_environment):
    # the whole point of the order here: a stopped run has completely finished every fic it
    # touched, rather than having half-finished all of them
    ao3 = MagicMock()
    order: list[str] = []
    ao3.refresh_one.side_effect = lambda record: (order.append('read ' + record['id'])
                                                  or record)
    ao3.download_one_indexed.side_effect = (
        lambda record, *a: order.append('fetch ' + record['id']))
    ao3.failures = []

    run_update_with(fake_environment, ao3,
                    [INCOMPLETE, {**INCOMPLETE, 'id': '333',
                                  'link': 'https://archiveofourown.org/works/333'}],
                    existing={})

    assert order == ['read 111', 'fetch 111', 'read 333', 'fetch 333']


def test_run_update_names_the_works_it_could_not_re_read(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = [{'id': '111', 'link': 'https://archiveofourown.org/works/111',
                     'error': 'deleted'}]
    events: list[dict] = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], report=events.append)

    assert [e for e in events if e['type'] == progress.FAILURES]


# region filling in formats a finished fic never had

def finished(work: str, title: str = 'Done') -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'title': title, 'chapters_published': 5, 'chapters_total': 5}


def filling(fake_environment, ao3, index, existing, skip=None, filetypes=('HTML',)):
    # filetypes defaults through a tuple rather than `or ['HTML']`, so a test passing an
    # empty list gets an empty list rather than the default back
    job = server.Job(server.ACTION_SYNC, ['HTML'], 'Someone')
    # the pass re-reads each fic before fetching it; unless a test says otherwise that
    # hands back what it was given, so the record reaching the download can be asserted on
    if ao3.refresh_one.side_effect is None:
        ao3.refresh_one.side_effect = lambda record: record
    with patch.object(server.shared, 'read_index', return_value=index), \
         patch.object(server.shared, 'scan_downloaded_works', return_value=existing):
        server.fill_missing_formats(job, fake_environment['fileops'], ao3,
                                    skip or set(), list(filetypes), MagicMock())


def test_a_finished_fic_missing_a_requested_format_is_fetched(fake_environment):
    # the case the other two passes leave behind: not new, so the newest-first walk never
    # reached it, and not unfinished, so the update pass ignored it
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111')], existing={})

    assert ao3.download_one_indexed.call_args.args[0]['id'] == '111'


def test_a_gap_is_re_indexed_before_it_is_fetched(fake_environment):
    # the entry first, then the file. a file written from a stale entry carries a stale
    # date in its name, and that date is the whole of how a later run judges it
    ao3 = MagicMock()
    order: list[str] = []
    ao3.refresh_one.side_effect = lambda record: (order.append('index'), record)[1]
    ao3.download_one_indexed.side_effect = lambda *a: order.append('download')

    filling(fake_environment, ao3, [finished('111')], existing={})

    assert order == ['index', 'download']


def test_the_gap_download_uses_the_entry_as_it_now_stands(fake_environment):
    # not the one read off disk before the re-read, or the name would still be the old one
    ao3 = MagicMock()
    fresh = {**finished('111'), 'date_updated': '20 Dec 2026'}
    ao3.refresh_one.side_effect = lambda record: fresh

    filling(fake_environment, ao3, [finished('111')], existing={})

    assert ao3.download_one_indexed.call_args.args[0] is fresh


def test_a_gap_whose_fic_cannot_be_re_read_is_recorded_and_skipped(fake_environment):
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = Exception('deleted')

    filling(fake_environment, ao3, [finished('111')], existing={})

    ao3.download_one_indexed.assert_not_called()
    ao3.record_failure.assert_called_once()


def test_a_finished_fic_that_has_every_format_is_left_alone(fake_environment):
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111')],
            existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    ao3.download_one_indexed.assert_not_called()


def test_only_the_formats_actually_missing_are_fetched(fake_environment):
    # rate limit is the scarce thing here: re-fetching a file already on disk spends a
    # request for nothing, and download_one_indexed takes whatever filetypes it is given
    ao3 = MagicMock()
    seen = []
    ao3.download_one_indexed.side_effect = lambda *a: seen.append(list(ao3.filetypes))

    filling(fake_environment, ao3, [finished('111')],
            existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}},
            filetypes=['HTML', 'PDF'])

    assert seen == [['PDF']]


def test_the_borrowed_downloader_is_handed_back_as_it_was(fake_environment):
    # the Ao3 belongs to the run, not to this pass; leaving it reconfigured would quietly
    # change what every later pass downloads
    ao3 = MagicMock()
    ao3.filetypes = ['HTML', 'PDF']

    filling(fake_environment, ao3, [finished('111')], existing={}, filetypes=['HTML', 'PDF'])

    assert ao3.filetypes == ['HTML', 'PDF']


def test_works_the_earlier_passes_handled_are_not_done_twice(fake_environment):
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111'), finished('222')], existing={},
            skip={'111'})

    assert [c.args[0]['id'] for c in ao3.download_one_indexed.call_args_list] == ['222']


def test_an_unfinished_fic_is_left_to_the_update_pass(fake_environment):
    # it has just been re-read and judged there; doing it again here would double the cost
    ao3 = MagicMock()
    filling(fake_environment, ao3, [INCOMPLETE], existing={})

    ao3.download_one_indexed.assert_not_called()


def test_filling_gaps_asks_ao3_for_nothing_when_no_formats_were_requested(fake_environment):
    ao3 = MagicMock()
    filling(fake_environment, ao3, [finished('111')], existing={}, filetypes=[])

    ao3.download_one_indexed.assert_not_called()

# endregion


# region the combined run

def test_a_combined_run_does_new_then_unfinished_then_the_gaps(fake_environment):
    # each pass covers what the one before it cannot, and the order is the whole design:
    # the gap check has to know what the first two already handled
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')
    order: list[str] = []

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server, 'index_new_bookmarks',
                      side_effect=lambda *a: order.append('new') or []), \
         patch.object(server, 'download_planned',
                      side_effect=lambda *a: order.append('download')), \
         patch.object(server, 'update_incomplete',
                      side_effect=lambda *a: order.append('update')), \
         patch.object(server, 'fill_missing_formats',
                      side_effect=lambda *a: order.append('gaps')):
        server.run_sync(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert order == ['new', 'download', 'update', 'gaps']


def test_a_combined_run_tells_the_gap_check_what_it_already_handled(fake_environment):
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server, 'index_new_bookmarks', return_value=[finished('111')]), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'update_incomplete'), \
         patch.object(server, 'fill_missing_formats') as gaps:
        server.run_sync(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert gaps.call_args.args[3] == {'111'}


def test_a_combined_run_stops_where_it_was_cancelled(fake_environment):
    # a stop during the first pass must not start the next two
    job = server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone')

    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server, 'index_new_bookmarks',
                      side_effect=lambda *a: job.cancel.set() or []), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'update_incomplete') as update, \
         patch.object(server, 'fill_missing_formats') as gaps:
        server.run_sync(job, fake_environment['fileops'], fake_environment['repo'], None)

    update.assert_not_called()
    gaps.assert_not_called()


def test_a_new_bookmarks_run_stops_indexing_at_what_it_already_holds(fake_environment):
    job = server.Job(server.ACTION_NEW, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'indexed_work_ids', return_value={'111', '222'}), \
         patch.object(server, 'download_planned'):
        server.run_new(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.kwargs['known'] == {'111', '222'}
    assert ao3.get_metadata.call_args.args[0] == \
        'https://archiveofourown.org/users/Someone/bookmarks'


def test_a_custom_run_saves_images_only_when_asked(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = [finished('111')]

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned'), \
         patch.object(server, 'save_images') as images:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    images.assert_not_called()


def test_a_custom_run_saves_images_after_the_files_are_down(fake_environment):
    # never instead of them, and never first: a work page fetched for pictures is the most
    # expendable request in the run, so it goes last
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'images': True}))
    ao3 = MagicMock()
    ao3.get_metadata.return_value = [finished('111')]
    order: list[str] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned',
                      side_effect=lambda *a: order.append('files')), \
         patch.object(server, 'save_images', side_effect=lambda *a: order.append('images')):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert order == ['files', 'images']


def test_saving_images_asks_each_work_for_its_own_page(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.save_images_for.return_value = 2

    server.save_images(job, fake_environment['fileops'], ao3,
                       [finished('111'), finished('222')], MagicMock())

    assert [c.args[0]['id'] for c in ao3.save_images_for.call_args_list] == ['111', '222']


def test_a_work_page_that_will_not_load_costs_its_images_and_nothing_else(fake_environment):
    # this is the last thing a run does; losing a second copy of some pictures is not worth
    # ending it over
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.save_images_for.side_effect = [Exception('gone'), 3]

    server.save_images(job, fake_environment['fileops'], ao3,
                       [finished('111'), finished('222')], MagicMock())

    assert ao3.save_images_for.call_count == 2
    ao3.record_failure.assert_called_once()


def test_saving_images_stops_when_the_run_is_cancelled(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['HTML'], 'Someone')
    job.cancel.set()
    ao3 = MagicMock()

    server.save_images(job, fake_environment['fileops'], ao3, [finished('111')], MagicMock())

    ao3.save_images_for.assert_not_called()


def test_a_custom_run_told_to_skip_indexing_reads_no_listing(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone',
                     server.resolve_options({'reindex': False}))
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[finished('111')]), \
         patch.object(server, 'download_planned') as download:
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_not_called()
    assert [x['id'] for x in download.call_args.args[3]] == ['111']


def test_a_custom_run_indexes_by_default(fake_environment):
    job = server.Job(server.ACTION_CUSTOM, ['JSON', 'HTML'], 'Someone')
    ao3 = MagicMock()
    ao3.get_metadata.return_value = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server, 'download_planned'):
        server.run_custom(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.get_metadata.assert_called_once()


def test_one_fic_is_indexed_and_then_downloaded(fake_environment):
    job = server.Job(server.ACTION_WORK, ['JSON', 'HTML'], 'Someone', None,
                     'https://archiveofourown.org/works/111')
    ao3 = MagicMock()
    ao3.index_one_work.return_value = finished('111')

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[]), \
         patch.object(server, 'download_planned') as download:
        server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.index_one_work.call_args.args[0] == 'https://archiveofourown.org/works/111'
    assert [x['id'] for x in download.call_args.args[3]] == ['111']


def test_one_fic_already_indexed_is_handed_the_entry_it_has(fake_environment):
    # so the listing's tags, summary and bookmark fields survive a single-fic run
    job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', None,
                     'https://archiveofourown.org/works/111')
    ao3 = MagicMock()
    ao3.index_one_work.return_value = finished('111')
    held = {**finished('111'), 'summary': 'from the listing'}

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'read_index', return_value=[held]), \
         patch.object(server, 'download_planned'):
        server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.index_one_work.call_args.args[1] == held


def test_one_fic_with_an_unusable_link_never_starts(fake_environment):
    job = server.Job(server.ACTION_WORK, ['JSON'], 'Someone', None, 'not a link')
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3):
        with pytest.raises(exceptions.InvalidLinkException):
            server.run_work(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.index_one_work.assert_not_called()

# endregion


# region naming what a run could not get

def test_skipped_bookmarks_are_listed_with_a_reason_each():
    # a count leaves no way to tell which bookmark was passed over or to go and look at it
    ao3 = MagicMock()
    ao3.failures = []
    ao3.skipped_works = [
        {'id': '12345', 'link': 'https://ao3/series/12345', 'error': 'a series'},
        {'id': None, 'link': '', 'error': 'the work has been deleted'},
    ]
    events: list[dict] = []

    server.report_failures(ao3, events.append)

    sent = [e for e in events if e['type'] == progress.SKIPPED]
    assert len(sent) == 1
    assert [x['error'] for x in sent[0]['skipped']] == ['a series', 'the work has been deleted']


def test_skipped_bookmarks_are_kept_apart_from_failed_downloads():
    # nothing went wrong with a skipped bookmark, and listing them together would make a
    # real failure look routine
    ao3 = MagicMock()
    ao3.skipped_works = [{'id': '1', 'link': 'a', 'error': 'a series'}]
    ao3.failures = [{'id': '2', 'link': 'b', 'error': 'timed out'}]
    events: list[dict] = []

    server.report_failures(ao3, events.append)

    assert [e['type'] for e in events] == [progress.SKIPPED, progress.FAILURES]


def test_nothing_is_reported_when_a_run_got_everything():
    ao3 = MagicMock()
    ao3.skipped_works = []
    ao3.failures = []
    events: list[dict] = []

    server.report_failures(ao3, events.append)

    assert events == []


@pytest.mark.parametrize('action', [
    server.ACTION_BOOKMARKS, server.ACTION_UPDATE, server.ACTION_COLLECTIONS,
    server.ACTION_COLLECTION, server.ACTION_NEW, server.ACTION_SYNC, server.ACTION_WORK,
    server.ACTION_CUSTOM,
])
def test_every_action_ends_by_saying_what_it_could_not_get(action):
    # every button, not most of them: a gap between what is bookmarked and what is on disk
    # is worth naming whichever run left it
    source = inspect.getsource(server.runners()[action])

    assert 'report_failures' in source, action


def test_a_metadata_only_run_still_says_what_it_skipped(fake_environment):
    # it downloads nothing, so this used to sit inside the download block and never run -
    # but indexing is exactly where skipped bookmarks are found
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone')
    ao3 = MagicMock()
    ao3.failures = []
    ao3.skipped_works = [{'id': None, 'link': '', 'error': 'the work has been deleted'}]
    events: list[dict] = []

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'],
                             events.append)

    assert [e for e in events if e['type'] == progress.SKIPPED]

# endregion


def test_run_bookmarks_indexes_every_bookmark_before_downloading_any(fake_environment):
    # the whole point of the order: an interrupted run still leaves a complete index
    job = server.Job(server.ACTION_BOOKMARKS,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB'], 'Someone')
    order = []
    ao3 = MagicMock()
    ao3.get_metadata.side_effect = lambda *a: order.append('metadata')
    ao3.download.side_effect = lambda *a: order.append('download')

    events = []
    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'],
                             events.append)

    assert order == ['metadata', 'download']
    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.INDEXING, progress.DOWNLOADING]


def test_run_bookmarks_reports_only_indexing_when_json_is_the_only_type(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone')

    events = []
    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'],
                             events.append)

    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.INDEXING]


def test_run_update_says_what_it_is_doing_at_each_step(fake_environment):
    # from the outside, 'reading the index' and 'checking what you have' look the same as a
    # stall, so each one says so before the per-fic work begins
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []
    events: list[dict] = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], report=events.append,
                    plan={'stale': ['https://archiveofourown.org/works/111'],
                          'undated': [], 'superseded': {}})

    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.SCANNING, progress.CHECKING_FILES, progress.UPDATING]


def test_run_update_says_it_is_reading_a_fic_before_it_goes_and_reads_it(
        fake_environment, capsys):
    # opening the fic page is the slow part, so the line has to come before the request,
    # not after it - otherwise the run looks stalled on the fic it has only just named
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE],
                    existing={'111': {'HTML': {'path': 'a.html', 'date': '2024-12-14'}}})

    said = [x.strip() for x in capsys.readouterr().out.splitlines() if x.strip()]
    assert said.index('reading latest index') == said.index('index updated') - 1
    assert said.index('[1 of 1] A Fic') == said.index('reading latest index') - 1


def test_run_update_names_each_fic_as_it_reaches_it(fake_environment):
    # one work event per fic, so the modal reads as a running account rather than a bar
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []
    events: list[dict] = []
    # the per-fic events go out through the Ao3 the run builds, not the run's own reporter
    ao3.progress = events.append

    run_update_with(fake_environment, ao3, [INCOMPLETE], report=events.append)

    works = [e for e in events if e['type'] == progress.WORK]
    assert [(e['title'], e['done'], e['total']) for e in works] == [('A Fic', 1, 1)]
    assert works[0]['phase'] == progress.UPDATING


def test_run_bookmarks_passes_the_chosen_options_through(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB', 'HTML'], 'Someone',
                     server.resolve_options({'pages': 3, 'series': True, 'images': True}))

    with patch.object(server, 'Ao3') as ao3_class, \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    args = ao3_class.call_args.args
    assert args[3] == 3      # pages
    assert args[4] is True   # series
    assert args[5] is True   # images


def test_run_bookmarks_treats_page_zero_as_every_page(fake_environment):
    # Ao3 wants None for "no limit"; the console asks for 0
    job = server.Job(server.ACTION_BOOKMARKS, ['HTML'], 'Someone',
                     server.resolve_options({'pages': 0}))

    with patch.object(server, 'Ao3') as ao3_class, \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3_class.call_args.args[3] is None


def test_run_bookmarks_asks_for_work_dates_when_requested(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, [strings.AO3_DOWNLOAD_TYPE_METADATA], 'Someone',
                     server.resolve_options({'workdates': True}))
    ao3 = MagicMock()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    assert ao3.get_metadata.call_args.args[1] is True


def test_run_bookmarks_skips_the_download_phase_once_cancelled(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB'], 'Someone')
    ao3 = MagicMock()
    # metadata finishes, then the user hits stop
    ao3.get_metadata.side_effect = lambda *a: job.cancel.set()

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'visited', return_value=[]):
        server.run_bookmarks(job, fake_environment['fileops'], fake_environment['repo'], None)

    ao3.download.assert_not_called()


def test_run_update_does_not_download_once_cancelled(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    job.cancel.set()
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(fake_environment, ao3, [INCOMPLETE], job=job)

    ao3.refresh_one.assert_not_called()
    ao3.download_one_indexed.assert_not_called()


def test_run_job_reports_a_cancelled_finish_rather_than_a_failure(fake_environment):
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')

    with patch.object(server, 'run_bookmarks', side_effect=lambda *a: job.cancel.set()):
        server.run_job(job, 'a-password')

    finished = [e for e in job.history if e['type'] == progress.FINISHED]
    assert len(finished) == 1
    assert finished[0]['cancelled'] is True
    assert not [e for e in job.history if e['type'] == progress.FAILED]


def test_run_job_announces_the_chosen_filetypes_and_options(fake_environment):
    # the ui shows these back while the run is in progress
    job = server.Job(server.ACTION_BOOKMARKS, ['EPUB', 'HTML'], 'Someone',
                     server.resolve_options({'pages': 2, 'images': True}))

    with patch.object(server, 'run_bookmarks'):
        server.run_job(job, 'a-password')

    started = [e for e in job.history if e['type'] == progress.STARTED][0]
    assert started['filetypes'] == ['EPUB', 'HTML']
    assert started['options']['pages'] == 2
    assert started['options']['images'] is True


def test_run_update_downloads_a_copy_the_version_check_calls_out_of_date(fake_environment):
    # the copy is there in the format asked for, but ao3 now reports a later update than
    # the date the file carries
    ao3 = MagicMock()
    ao3.refresh_one.side_effect = lambda record: record
    ao3.failures = []

    run_update_with(
        fake_environment, ao3, [INCOMPLETE],
        existing={'111': {'HTML': {'path': 'a.html', 'date': '2020-01-01'}}},
        plan={'stale': ['https://archiveofourown.org/works/111'], 'undated': [],
              'superseded': {'https://archiveofourown.org/works/111': {'HTML': 'a.html'}}})

    fetched = ao3.download_one_indexed.call_args.args[0]
    assert fetched['id'] == '111'
    # and the old file is handed over to be replaced only after the new one lands
    assert ao3.superseded == {'https://archiveofourown.org/works/111': {'HTML': 'a.html'}}

# endregion


# region only one helper at a time

def test_a_helper_that_is_actually_listening_is_noticed():
    # on windows SO_REUSEADDR lets a second process bind a port the first is listening on,
    # so binding cannot be relied on to fail. asking by connecting is what catches it.
    live = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    thread = threading.Thread(target=live.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.already_listening(server.HOST, live.server_address[1]) is True
    finally:
        live.shutdown()
        live.server_close()


def test_a_port_with_nothing_on_it_is_free():
    spare = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    spare.bind((server.HOST, 0))
    port = spare.getsockname()[1]
    spare.close()

    assert server.already_listening(server.HOST, port, timeout=0.2) is False


def test_serve_gives_up_rather_than_starting_a_second_helper(capsys):
    with patch.object(server, 'already_listening', return_value=True):
        with pytest.raises(SystemExit):
            server.serve(port=4400)

    said = capsys.readouterr().out
    assert 'already listening' in said
    # the fix is to close the old one, so say so rather than leaving a bare stack trace
    assert 'earlier' in said


def test_serve_starts_when_the_port_is_free(capsys):
    # a port left in TIME_WAIT by a normal shutdown must not stop the next start
    httpd = MagicMock()
    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer', return_value=httpd):
        server.serve(port=4400)

    httpd.serve_forever.assert_called_once()

# endregion


# region telling a stale helper apart from a bad request

def test_an_unknown_action_names_what_this_helper_does_understand():
    sent = {}

    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {'action': 'collections'}
    handler.send_json.side_effect = lambda status, body: sent.update(status=status, body=body)

    # a helper from before collections existed, asked to index collections
    with patch.object(server, 'ACTIONS', ('bookmarks', 'update')):
        server.Handler.do_POST(handler)

    assert sent['status'] == 400
    error = sent['body']['error']
    assert 'collections' in error
    assert 'bookmarks' in error
    # the usual cause is an old helper, not a malformed request
    assert 'older code' in error

# endregion
