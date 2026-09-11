"""Tests for ao3downloader.server — the local helper behind the web ui.

Nothing here touches the network: the download work itself is the same code the console
menu runs, which is covered by the other suites. What matters here is the plumbing around
it - what gets requested, what gets reported, and what never leaves the machine.
"""

import os
import socket
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest

from source_code import parse_text, progress, server, strings


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
        'refreshUndated': False, 'stampUndated': '',
    }


def test_resolve_options_reads_what_was_asked_for():
    result = server.resolve_options(
        {'start': '5', 'pages': '8', 'series': True, 'images': True, 'workdates': True,
         'refreshUndated': True, 'stampUndated': '2024-06-01'})

    assert result == {'start': 5, 'pages': 8, 'series': True, 'images': True,
                      'workdates': True, 'refreshUndated': True,
                      'stampUndated': '2024-06-01'}


def test_refreshing_undated_files_is_off_unless_asked_for():
    # it refetches an entire library, so it must never be what happens by default
    assert server.resolve_options({})['refreshUndated'] is False


def test_dating_undated_files_is_off_unless_asked_for():
    # it renames files the user already has, so it is never a default either
    assert server.resolve_options({})['stampUndated'] == ''


@pytest.mark.parametrize('given', ['not a date', '2024-13-45', 'today', 42, None, ''])
def test_a_date_to_stamp_that_cannot_be_read_is_ignored(given):
    # renaming a library after a half-understood date would be worse than doing nothing
    assert server.resolve_options({'stampUndated': given})['stampUndated'] == ''


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


def test_run_update_reports_scanning_then_downloading(fake_environment):
    job = server.Job(server.ACTION_UPDATE, ['HTML'], 'Someone')

    events = []
    with patch.object(server, 'Ao3', return_value=MagicMock()), \
         patch.object(server.shared, 'get_files_of_type', return_value=[]):
        server.run_update(job, fake_environment['fileops'], fake_environment['repo'],
                          events.append)

    phases = [e['name'] for e in events if e['type'] == progress.PHASE]
    assert phases == [progress.SCANNING, progress.DOWNLOADING]


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
