"""Tests for source_code.runs - the per-run history files."""

import json
import os
from unittest.mock import MagicMock

from source_code import runs


def fake_fileops(tmp_path):
    fileops = MagicMock()
    fileops.runsfolder = str(tmp_path / 'runs')
    return fileops


def a_record(tmp_path, action='sync', filetypes=('JSON', 'HTML'), options=None):
    return runs.RunRecord(fake_fileops(tmp_path), 'abcdef1234', action, 'A Button',
                          list(filetypes), options or {'pages': 0})


def written(tmp_path) -> list[dict]:
    folder = tmp_path / 'runs'
    return [json.loads((folder / name).read_text(encoding='utf-8'))
            for name in sorted(os.listdir(folder))]


# region a run writes itself down as it goes

def test_a_run_is_on_disk_before_it_has_done_anything(tmp_path):
    # a run killed mid-flight cannot write its own epitaph, so the file has to exist from
    # the start - that is what makes an interrupted run recognisable at all
    a_record(tmp_path)

    records = written(tmp_path)
    assert len(records) == 1
    assert records[0]['status'] == runs.STATUS_RUNNING
    assert records[0]['finished'] is None


def test_a_record_says_which_button_and_which_settings(tmp_path):
    a_record(tmp_path, action='custom', filetypes=['JSON', 'PDF'],
             options={'pages': 3, 'reindex': False})

    record = written(tmp_path)[0]
    assert record['action'] == 'custom'
    assert record['actionName'] == 'A Button'
    assert record['filetypes'] == ['JSON', 'PDF']
    assert record['options']['pages'] == 3
    assert record['options']['reindex'] is False
    assert record['started']


def test_finishing_stamps_the_outcome_and_the_time(tmp_path):
    record = a_record(tmp_path)

    record.finish(runs.STATUS_SUCCESS)

    saved = written(tmp_path)[0]
    assert saved['status'] == runs.STATUS_SUCCESS
    assert saved['finished']
    assert saved['error'] == ''


def test_a_failure_keeps_the_reason(tmp_path):
    record = a_record(tmp_path)

    record.finish(runs.STATUS_FAILED, 'invalid username or password')

    assert written(tmp_path)[0]['error'] == 'invalid username or password'


def test_the_fic_lists_are_kept_apart(tmp_path):
    # they answer different questions: what got a fresh entry, what arrived as a file, and
    # what replaced a copy that was already there
    ao3 = MagicMock()
    ao3.reindexed = {'111', '222'}
    ao3.downloaded = {'222'}
    ao3.updated = {'333'}
    ao3.failures = [{'id': '444', 'link': 'x', 'error': 'timed out'}]
    ao3.skipped_works = [{'id': None, 'link': '', 'error': 'deleted'}]
    record = a_record(tmp_path)

    record.collect(ao3)
    record.finish(runs.STATUS_SUCCESS)

    saved = written(tmp_path)[0]
    assert saved['reindexed'] == ['111', '222']
    assert saved['downloaded'] == ['222']
    assert saved['updated'] == ['333']
    assert saved['failures'][0]['id'] == '444'
    assert saved['skipped'][0]['error'] == 'deleted'


def test_a_run_with_no_downloader_still_finishes(tmp_path):
    # a run that failed before it built one still has to close its record
    record = a_record(tmp_path)

    record.collect(None)
    record.finish(runs.STATUS_FAILED, 'never got going')

    assert written(tmp_path)[0]['status'] == runs.STATUS_FAILED


def test_a_choice_the_run_stopped_to_ask_is_recorded(tmp_path):
    # so a library renamed months ago can be explained by what was asked and answered
    record = a_record(tmp_path)

    record.choice({'question': 'undated', 'count': 12, 'choice': 'stamp',
                   'date': '2024-06-01'})

    choices = written(tmp_path)[0]['choices']
    assert choices[0]['choice'] == 'stamp'
    assert choices[0]['date'] == '2024-06-01'
    assert choices[0]['at']


def test_the_console_output_is_kept_with_the_run(tmp_path):
    # the modal is gone once the tab is closed, and this is the only lasting copy
    record = a_record(tmp_path)

    record.line('indexing')
    record.line('fetching page 1 of 80')
    record.finish(runs.STATUS_SUCCESS)

    assert written(tmp_path)[0]['log'] == ['indexing', 'fetching page 1 of 80']


def test_lines_printed_before_the_record_existed_are_not_lost(tmp_path):
    # the run says it is logging in before there is a file to say it into
    record = runs.RunRecord(fake_fileops(tmp_path), 'abc', 'sync', 'A', ['JSON'], {},
                            printed=['logging in as someone'])

    record.line('logged in')
    record.finish(runs.STATUS_SUCCESS)

    assert written(tmp_path)[0]['log'] == ['logging in as someone', 'logged in']


def test_the_log_is_not_written_to_disk_a_line_at_a_time(tmp_path):
    # save rewrites the whole file, so a line per fic per format would rewrite a growing
    # file thousands of times over a long run
    record = a_record(tmp_path)
    record.save = MagicMock()

    for n in range(runs.LOG_FLUSH_EVERY - 1):
        record.line(f'line {n}')

    record.save.assert_not_called()
    record.line('one more')
    record.save.assert_called_once()


def test_an_interrupted_run_still_has_most_of_what_it_said(tmp_path):
    # nothing closes the file, so what is on disk is whatever the last batch left
    record = a_record(tmp_path)

    for n in range(runs.LOG_FLUSH_EVERY * 2):
        record.line(f'line {n}')

    assert len(written(tmp_path)[0]['log']) == runs.LOG_FLUSH_EVERY * 2


def test_a_very_long_run_keeps_the_end_of_its_log_and_says_what_it_dropped(tmp_path):
    # whatever went wrong is at the end, so the start is what gives way - and a log that
    # begins in the middle has to say so rather than reading as the whole run
    record = a_record(tmp_path)

    for n in range(runs.LOG_MAX_LINES + 10):
        record.line(f'line {n}')
    record.finish(runs.STATUS_SUCCESS)

    saved = written(tmp_path)[0]
    assert len(saved['log']) == runs.LOG_MAX_LINES
    assert saved['log'][-1] == f'line {runs.LOG_MAX_LINES + 9}'
    assert saved['logTrimmed'] == 10


def test_a_line_that_cannot_be_kept_does_not_take_the_run_down(tmp_path):
    record = a_record(tmp_path)
    record.data.pop('log')

    record.line('something')


def test_a_history_file_that_cannot_be_written_does_not_raise(tmp_path):
    # a note about the run is not worth taking the run down for
    fileops = MagicMock()
    fileops.runsfolder = str(tmp_path / 'runs')
    record = runs.RunRecord(fileops, 'abc', 'sync', 'A', ['JSON'], {})
    record.path = str(tmp_path / 'runs' / 'no' / 'such' / '\0bad.json')

    record.finish(runs.STATUS_SUCCESS)

# endregion


# region reading the history back

def test_runs_come_back_newest_first(tmp_path):
    folder = tmp_path / 'runs'
    folder.mkdir(parents=True)
    for name in ['2026-01-01T000000-a.json', '2026-06-01T000000-b.json']:
        (folder / name).write_text(json.dumps({'id': name[:4]}), encoding='utf-8')

    found = runs.read_runs(fake_fileops(tmp_path))

    assert [x['file'] for x in found] == ['2026-06-01T000000-b.json',
                                          '2026-01-01T000000-a.json']


def test_a_damaged_record_does_not_hide_the_rest(tmp_path):
    folder = tmp_path / 'runs'
    folder.mkdir(parents=True)
    (folder / '2026-01-01T000000-a.json').write_text('{not json', encoding='utf-8')
    (folder / '2026-02-01T000000-b.json').write_text(json.dumps({'id': 'b'}),
                                                     encoding='utf-8')

    assert [x['id'] for x in runs.read_runs(fake_fileops(tmp_path))] == ['b']


def test_no_history_yet_is_not_an_error(tmp_path):
    assert runs.read_runs(fake_fileops(tmp_path)) == []


def test_the_last_successful_run_ignores_the_ones_that_did_not_finish(tmp_path):
    # a stopped run may have stopped before reaching fics updated before it started, so
    # trusting it as a floor would leave exactly those unseen
    folder = tmp_path / 'runs'
    folder.mkdir(parents=True)
    (folder / '2026-01-01T000000-a.json').write_text(
        json.dumps({'id': 'old', 'status': runs.STATUS_SUCCESS}), encoding='utf-8')
    (folder / '2026-02-01T000000-b.json').write_text(
        json.dumps({'id': 'stopped', 'status': runs.STATUS_STOPPED}), encoding='utf-8')
    (folder / '2026-03-01T000000-c.json').write_text(
        json.dumps({'id': 'running', 'status': runs.STATUS_RUNNING}), encoding='utf-8')

    assert runs.last_successful(fake_fileops(tmp_path))['id'] == 'old'


def test_there_may_never_have_been_a_successful_run(tmp_path):
    assert runs.last_successful(fake_fileops(tmp_path)) is None

# endregion
