"""Older copies of a work beside the newest one: found, asked about, marked, cleaned up.

Nothing is removed where it is decided. A copy the user says to drop is marked, written
into the run's history at once, and removed in the cleanup step just before the report -
so a run that stops or fails first removes nothing, and says which files it had marked.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from source_code import progress, runs, server, strings
from source_code.actions import shared
from source_code.fileio import FileOps


def make(folder, *names: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names: (folder / name).write_bytes(b'x')


def record(work: str) -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}'}


# region finding them

def test_the_scan_keeps_the_older_copies_it_passes_over(tmp_path):
    make(tmp_path, '111 A 2024-01-01.pdf', '111 A 2025-06-01.pdf', '111 A.pdf')

    found = shared.scan_downloaded_works(str(tmp_path), ['PDF'])

    newest = found['111']['PDF']
    assert newest['date'] == '2025-06-01'
    assert sorted(x['date'] or '' for x in newest['older']) == ['', '2024-01-01']


def test_only_strictly_older_copies_count(tmp_path):
    # the same date twice cannot say which one to keep, so neither is offered for removal
    make(tmp_path, '111 A 2025-06-01.pdf', '111 A renamed 2025-06-01.pdf', '111 A.pdf')
    existing = shared.scan_downloaded_works(str(tmp_path), ['PDF'])

    older = shared.older_copies(existing, {'111'}, ['PDF'])

    assert [x['file'] for x in older] == ['111 A.pdf']


def test_only_the_runs_own_works_are_looked_at(tmp_path):
    make(tmp_path, '111 A 2024-01-01.pdf', '111 A 2025-06-01.pdf',
         '222 B 2024-01-01.pdf', '222 B 2025-06-01.pdf')
    existing = shared.scan_downloaded_works(str(tmp_path), ['PDF'])

    older = shared.older_copies(existing, {'111'}, ['PDF'])

    assert [(x['id'], x['file'], x['keeping']) for x in older] == [
        ('111', '111 A 2024-01-01.pdf', '111 A 2025-06-01.pdf')]


def test_different_formats_of_a_work_are_not_duplicates(tmp_path):
    make(tmp_path, '111 A 2024-01-01.pdf', '111 A 2025-06-01.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['PDF', 'HTML'])
    assert shared.older_copies(existing, {'111'}, ['PDF', 'HTML']) == []

# endregion


# region asking, and marking

@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()
    make(tmp_path / 'library' / 'works', '111 A 2024-01-01.pdf', '111 A 2025-06-01.pdf')
    return fileops


def a_job(fileops: FileOps, answer: str | None) -> server.Job:
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'PDF'], 'Someone')
    job.record = runs.RunRecord(fileops, job.id, job.action, 'Full scan', job.filetypes, {})
    asked = []
    job.ask = lambda question, default: (asked.append(question),
                                         {'choice': answer} if answer else default)[1]
    job.asked = asked
    events: list[dict] = []
    job.steps = server.Steps(events.append, server.step_plan(job))
    job.events_seen = events
    return job


def on_record(fileops: FileOps) -> dict:
    folder = os.path.join(fileops.downloadfolder, strings.RUNS_FOLDER_NAME)
    [name] = os.listdir(folder)
    with open(os.path.join(folder, name), encoding='utf-8') as f:
        return json.load(f)


def settled(fileops: FileOps, job: server.Job) -> dict:
    existing = shared.scan_downloaded_works(fileops.worksfolder, ['PDF'])
    server.settle_duplicates(job, [record('111')], existing, ['PDF'])
    return existing


def test_it_asks_about_works_with_older_copies(library):
    job = a_job(library, 'newest')
    settled(library, job)
    assert job.asked == [{'name': server.DUPLICATES_QUESTION, 'count': 1, 'files': 1,
                          'choices': ['newest', 'leave']}]


def test_keeping_the_newest_marks_the_older_copies_and_records_them_at_once(library):
    job = a_job(library, 'newest')

    settled(library, job)

    # marked, not removed: nothing leaves the folder until the cleanup step
    assert os.path.exists(os.path.join(library.worksfolder, '111 A 2024-01-01.pdf'))
    assert [(x['file'], x['status']) for x in job.removals] == [('111 A 2024-01-01.pdf', 'pending')]
    written = on_record(library)
    assert written['removals'] == [{'id': '111', 'filetype': 'PDF', 'file': '111 A 2024-01-01.pdf',
                                    'keeping': '111 A 2025-06-01.pdf', 'status': 'pending'}]
    assert written['choices'][-1]['choice'] == 'newest'


def test_the_default_leaves_every_copy_where_it_is(library):
    # a stop, a closed tab, or no answer at all changes nothing
    job = a_job(library, None)
    settled(library, job)
    assert job.removals == []


def test_nothing_is_asked_when_there_are_no_older_copies(library):
    os.remove(os.path.join(library.worksfolder, '111 A 2024-01-01.pdf'))
    job = a_job(library, 'newest')
    settled(library, job)
    assert job.asked == []

# endregion


# region the cleanup step

def test_cleanup_removes_what_was_marked_and_records_it(library):
    job = a_job(library, 'newest')
    settled(library, job)

    server.cleanup(job, library, MagicMock(written=[]))

    assert sorted(os.listdir(library.worksfolder)) == ['111 A 2025-06-01.pdf']
    assert job.removals[0]['status'] == 'removed'
    assert on_record(library)['removals'][0]['status'] == 'removed'
    marks = [(e['id'], e['status']) for e in job.events_seen if e['type'] == progress.STEP]
    assert marks == [('cleanup', progress.STEP_RUNNING), ('cleanup', progress.STEP_DONE)]


def test_cleanup_with_nothing_marked_is_skipped(library):
    job = a_job(library, None)
    server.cleanup(job, library, None)
    marks = [(e['id'], e['status']) for e in job.events_seen if e['type'] == progress.STEP]
    assert marks == [('cleanup', progress.STEP_SKIPPED)]


def test_a_stopped_run_removes_nothing_and_reports_what_it_had_marked(library):
    job = a_job(library, 'newest')
    settled(library, job)
    job.cancel.set()
    reported: list[dict] = []

    server.finish_run(job, library, MagicMock(written=[], failures=[], skipped_works=[],
                                              kept_copies=[]), reported.append)

    assert len(os.listdir(library.worksfolder)) == 2
    [left] = [e for e in reported if e['type'] == progress.NOT_REMOVED]
    assert left['notRemoved'][0]['file'] == '111 A 2024-01-01.pdf'
    assert left['notRemoved'][0]['error'] == strings.CLEANUP_STOPPED
    assert on_record(library)['removals'][0]['status'] == 'kept'


def test_a_file_this_run_downloaded_over_is_never_removed(library):
    # the older copy's name is the one a fresh download was just written to
    job = a_job(library, 'newest')
    settled(library, job)
    fresh = os.path.join(library.worksfolder, '111 A 2024-01-01.pdf')

    server.cleanup(job, library, MagicMock(written=[fresh]))

    assert os.path.exists(fresh)
    assert job.removals[0]['status'] == 'kept'
    assert job.removals[0]['error'] == strings.CLEANUP_WROTE_OVER


def test_a_file_that_will_not_delete_is_reported(library, monkeypatch):
    job = a_job(library, 'newest')
    settled(library, job)
    monkeypatch.setattr(library, 'delete_file', lambda path: False)
    reported: list[dict] = []

    server.finish_run(job, library, MagicMock(written=[], failures=[], skipped_works=[],
                                              kept_copies=[]), reported.append)

    [left] = [e for e in reported if e['type'] == progress.NOT_REMOVED]
    assert left['notRemoved'][0]['error'] == strings.CLEANUP_NOT_DELETED


def test_a_run_that_fails_still_says_what_it_had_marked(library):
    # marked during the check, then the run dies before the cleanup step
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON', 'PDF'], 'Someone')
    job.ask = lambda question, default: {'choice': 'newest'}
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)

    def marks_then_fails(job, fileops, repo, report):
        settled(fileops, job)
        raise RuntimeError('the connection dropped')

    with patch.object(server, 'FileOps', return_value=library),          patch.object(server, 'Repository', return_value=repo),          patch.object(server, 'run_bookmarks', marks_then_fails):
        server.run_job(job, 'a-password')

    assert len(os.listdir(library.worksfolder)) == 2
    [left] = [e for e in job.history if e['type'] == progress.NOT_REMOVED]
    assert left['notRemoved'][0]['file'] == '111 A 2024-01-01.pdf'
    assert left['notRemoved'][0]['error'] == strings.CLEANUP_FAILED_RUN
    assert job.history[-1]['type'] == progress.FAILED
    # and the history file says so, not just the modal
    written = on_record(library)
    assert written['removals'][0]['status'] == 'kept'
    assert written['removals'][0]['error'] == strings.CLEANUP_FAILED_RUN


def test_every_plan_cleans_up_just_before_it_reports():
    for action in server.ACTIONS:
        job = server.Job(action, ['JSON', 'HTML'], 'Someone', server.resolve_options(
            {'dates': True} if action == server.ACTION_CUSTOM else None))
        ids = [step for step, _ in server.step_plan(job)]
        assert ids[-2:] == ['cleanup', 'report'], action

# endregion
