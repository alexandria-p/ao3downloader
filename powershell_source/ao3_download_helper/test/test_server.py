"""Tests for ao3downloader.server — the local helper behind the web ui.

Nothing here touches the network: the download work itself is the same code the console
menu runs, which is covered by the other suites. What matters here is the plumbing around
it - what gets requested, what gets reported, and what never leaves the machine.
"""

from unittest.mock import MagicMock, patch

import pytest

from source_code import progress, server, strings


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

# endregion


# region resolve_options

def test_resolve_options_defaults_match_the_console_defaults():
    assert server.resolve_options(None) == {
        'pages': 0, 'series': False, 'images': False, 'workdates': False,
    }


def test_resolve_options_reads_what_was_asked_for():
    result = server.resolve_options(
        {'pages': '3', 'series': True, 'images': True, 'workdates': True})

    assert result == {'pages': 3, 'series': True, 'images': True, 'workdates': True}


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


def test_run_update_scans_only_formats_that_can_be_parsed(fake_environment):
    job = server.Job(server.ACTION_UPDATE,
                     [strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML', 'EPUB'], 'Someone')

    with patch.object(server, 'Ao3'), \
         patch.object(server.shared, 'get_files_of_type', return_value=[]) as get_files:
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'], MagicMock())

    scanned = get_files.call_args.args[1]
    assert strings.AO3_DOWNLOAD_TYPE_METADATA not in scanned
    assert sorted(scanned) == ['EPUB', 'HTML']


def test_run_update_takes_the_least_complete_copy_of_a_work(fake_environment):
    # the same work can be on disk in several formats, at different chapter counts
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    ao3 = MagicMock()
    files = [{'path': 'a.html', 'filetype': 'HTML'}, {'path': 'b.html', 'filetype': 'HTML'}]

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'get_files_of_type', return_value=files), \
         patch.object(server.update, 'process_file', side_effect=[
             {'link': 'https://archiveofourown.org/works/1', 'chapters': 9},
             {'link': 'https://archiveofourown.org/works/1', 'chapters': 4}]):
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'], MagicMock())

    ao3.update.assert_called_once_with('https://archiveofourown.org/works/1', '4')


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


def test_run_update_stops_scanning_when_cancelled(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    job.cancel.set()
    files = [{'path': 'a.html', 'filetype': 'HTML'}]

    with patch.object(server, 'Ao3'), \
         patch.object(server.shared, 'get_files_of_type', return_value=files), \
         patch.object(server.update, 'process_file') as process:
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'], MagicMock())

    process.assert_not_called()


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


def test_run_update_survives_a_file_it_cannot_parse(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')
    ao3 = MagicMock()
    files = [{'path': 'bad.html', 'filetype': 'HTML'}, {'path': 'good.html', 'filetype': 'HTML'}]

    with patch.object(server, 'Ao3', return_value=ao3), \
         patch.object(server.shared, 'get_files_of_type', return_value=files), \
         patch.object(server.update, 'process_file', side_effect=[
             ValueError('not an ebook'),
             {'link': 'https://archiveofourown.org/works/2', 'chapters': 3}]):
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'], MagicMock())

    ao3.update.assert_called_once_with('https://archiveofourown.org/works/2', '3')
    fake_environment['fileops'].write_log.assert_called()

# endregion
