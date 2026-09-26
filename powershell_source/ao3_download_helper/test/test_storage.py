"""Tests for source_code.storage - the library as the web page holds it.

A run never touches the library itself: the page owns the folder (a File System Access
handle, or Dropbox), so every read and write is a request to the page. `FakePage` stands in
for it - a library in memory that answers the requests the way the page does - and
`answering` runs one on its own thread against a real `Job`, so the whole round trip is
exercised: request out on the event queue, bytes collected, answer posted back.
"""

import json
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from source_code import progress, runs, server, strings
from source_code.actions import shared
from source_code.fileio import FileOps
from source_code.storage import LocalStorage, PageStorage


class FakePage:
    """A library in memory, answering requests as the page does. Paths are page paths:
    `works/123 A.html`, `indexing/123.json`."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.folders: set[str] = set()
        self.calls: list[str] = []
        # set by a test to make one kind of request fail, as a full disk or a refusal would
        self.refuse: set[str] = set()

    def put(self, path: str, content: bytes = b'x') -> None:
        self.files[path] = content

    def find(self, path: str) -> str | None:
        return next((k for k in self.files if k.lower() == path.lower()), None)

    def storage_call(self, op: str, args: dict, content: bytes | None = None) -> dict:
        """The channel `PageStorage` talks through - here, straight to this fake."""

        self.calls.append(op)
        if op in self.refuse: return {'error': f'the page could not {op} that'}
        path = args.get('path', '')
        if op == 'check':
            return {}
        if op == 'mkdir':
            self.folders.add(path)
            return {}
        if op == 'list':
            prefix = path + '/' if path else ''
            names = [k for k in self.files if k.lower().startswith(prefix.lower())]
            if not args.get('recursive'):
                names = [k for k in names if '/' not in k[len(prefix):]]
            return {'files': names}
        if op == 'read':
            found = self.find(path)
            return {'missing': True} if found is None else {'text': self.files[found].decode('utf-8')}
        if op == 'write':
            self.files[path] = content or b''
            return {'size': len(content or b'')}
        if op == 'size':
            found = self.find(path)
            return {'size': None if found is None else len(self.files[found])}
        if op == 'delete':
            found = self.find(path)
            if found is not None: del self.files[found]
            return {}
        if op == 'rename':
            found = self.find(path)
            if found is None: return {'error': 'nothing to rename'}
            if self.find(args['to']) is not None: return {'error': 'already there'}
            self.files[args['to']] = self.files.pop(found)
            return {}
        return {'error': f'unknown request {op}'}

    def names(self) -> list[str]:
        return sorted(self.files)


@pytest.fixture
def page():
    return FakePage()


def library(page: FakePage) -> FileOps:
    return FileOps(storage=PageStorage(page))


# region paths

def test_a_library_path_can_never_be_mistaken_for_a_folder_on_this_computer(page):
    fileops = library(page)
    assert fileops.downloadfolder == 'library:'
    assert not os.path.isabs(fileops.downloadfolder)


def test_paths_built_the_usual_way_become_page_paths(page):
    storage = library(page).storage
    built = os.path.join(storage.root, strings.INDEXING_FOLDER_NAME, '123 A Fic.json')
    assert storage.relative(built) == 'indexing/123 A Fic.json'
    assert storage.relative(storage.root) == ''


def test_a_path_outside_the_library_is_refused(page):
    with pytest.raises(ValueError):
        library(page).storage.relative(r'C:\Users\someone\Fics\123.html')


def test_a_path_is_described_as_where_it_sits_in_the_library(page):
    fileops = library(page)
    assert fileops.describe(fileops.worksfolder + '/123 A.html') == 'works/123 A.html'


def test_the_same_name_in_another_case_is_the_same_file(page):
    assert library(page).same_file('library:/works/123 A.html', 'library:/Works/123 a.HTML')

# endregion


# region reading and writing

def test_json_goes_to_the_page_and_comes_back_the_same(page):
    fileops = library(page)
    name = os.path.join(strings.INDEXING_FOLDER_NAME, '123 Café - Someone.json')

    fileops.save_json(name, {'title': 'Café', 'indexes': [1, 2]})

    assert page.names() == ['indexing/123 Café - Someone.json']
    assert fileops.load_json(name) == {'title': 'Café', 'indexes': [1, 2]}


def test_json_the_page_does_not_have_is_absent_rather_than_an_error(page):
    assert library(page).load_json('indexing/999.json') is None


def test_damaged_json_is_absent_rather_than_ending_the_run(page):
    page.put('indexing/1.json', b'not json')
    assert library(page).load_json('indexing/1.json') is None


def test_a_page_that_cannot_read_a_file_is_the_same_as_a_file_that_cannot_be_read(page):
    page.put('indexing/1.json', b'{}')
    page.refuse.add('read')
    assert library(page).load_json('indexing/1.json') is None


def test_a_download_is_confirmed_from_the_page_answer_without_asking_again(page):
    # the page's answer to the write is the page saying what it stored
    fileops = library(page)
    saved = fileops.save_bytes('works/123 A Fic - Someone 2024-12-14.html', b'the whole fic')
    before = len(page.calls)

    assert fileops.saved_intact(saved, len(b'the whole fic')) is True
    assert fileops.saved_intact(saved, 999) is False
    assert len(page.calls) == before


def test_a_file_this_run_did_not_write_is_asked_about(page):
    page.put('works/123 Old.html', b'twelve bytes')
    fileops = library(page)
    assert fileops.saved_intact(os.path.join(fileops.worksfolder, '123 Old.html'), 12) is True
    assert 'size' in page.calls


def test_a_file_that_is_not_there_says_where_it_was_looked_for(page):
    fileops = library(page)
    path = os.path.join(fileops.worksfolder, '123 Gone.html')
    assert fileops.saved_problem(path, 10) == strings.SAVED_NOT_FOUND.format('works/123 Gone.html')


def test_a_write_the_page_refuses_fails_the_download(page):
    page.refuse.add('write')
    with pytest.raises(OSError):
        library(page).save_bytes('works/1.html', b'x')


def test_deleting_a_file_already_gone_counts_as_done(page):
    fileops = library(page)
    assert fileops.delete_file(os.path.join(fileops.worksfolder, 'nothing.html')) is True


def test_a_delete_the_page_refuses_is_reported_as_not_deleted(page):
    page.put('works/1 A.html')
    page.refuse.add('delete')
    fileops = library(page)
    assert fileops.delete_file(os.path.join(fileops.worksfolder, '1 A.html')) is False
    assert page.names() == ['works/1 A.html']


def test_renaming_will_not_write_over_a_file_already_there(page):
    page.put('works/1 A.html', b'a')
    page.put('works/1 A 2024-01-01.html', b'b')
    fileops = library(page)
    works = fileops.worksfolder

    assert fileops.rename_file(os.path.join(works, '1 A.html'),
                               os.path.join(works, '1 A 2024-01-01.html')) is False
    assert page.files['works/1 A 2024-01-01.html'] == b'b'


def test_asking_after_many_files_costs_one_listing_not_a_request_each(page):
    for work in range(10):
        page.put(f'works/{work} Fic.html')
    fileops = library(page)

    found = [fileops.exists(os.path.join(fileops.worksfolder, f'{work} Fic.html'))
             for work in range(20)]

    assert found == [True] * 10 + [False] * 10
    assert page.calls.count('list') == 1


def test_what_this_run_writes_deletes_and_renames_is_seen_straight_away(page):
    fileops = library(page)
    works = fileops.worksfolder
    assert not fileops.exists(os.path.join(works, 'a.html'))

    fileops.save_bytes('works/a.html', b'a')
    assert fileops.exists(os.path.join(works, 'a.html'))
    fileops.rename_file(os.path.join(works, 'a.html'), os.path.join(works, 'b.html'))
    assert not fileops.exists(os.path.join(works, 'a.html'))
    assert fileops.exists(os.path.join(works, 'b.html'))
    fileops.delete_file(os.path.join(works, 'b.html'))
    assert not fileops.exists(os.path.join(works, 'b.html'))
    assert page.calls.count('list') == 1

# endregion


# region reading the library back

def test_the_downloaded_works_are_found_in_works_alone(page):
    page.put('works/111 One - A 2024-01-01.html')
    page.put('works/old/222 Two - B.epub')
    page.put('333 Three - C 2024-01-01.html')
    page.put('indexing/111 One - A.json')
    fileops = library(page)

    found = shared.scan_downloaded_works(fileops.worksfolder, ['HTML', 'EPUB'],
                                         storage=fileops.storage)

    assert set(found) == {'111', '222'}
    assert found['111']['HTML'] == {'path': 'library:/works/111 One - A 2024-01-01.html',
                                    'date': '2024-01-01'}
    assert found['222']['EPUB']['date'] is None


def test_the_index_is_read_through_the_page(page):
    fileops = library(page)
    for work in ('111', '222'):
        fileops.save_json(os.path.join(strings.INDEXING_FOLDER_NAME, f'{work} Fic.json'), {
            'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'indexes': [{'title': f'Work {work}'}]})

    assert shared.indexed_work_ids(fileops) == {'111', '222'}
    assert [x['id'] for x in shared.read_index(fileops)] == ['111', '222']


def test_undated_files_are_dated_where_they_sit(page):
    page.put('works/34816549 No Paths - Cal.html', b'fic')
    fileops = library(page)
    existing = shared.scan_downloaded_works(fileops.worksfolder, ['HTML'], storage=fileops.storage)

    result = shared.stamp_undated_works(fileops, existing, {'34816549'}, '2024-06-01', 50)

    assert (result['renamed'], result['skipped']) == (1, 0)
    assert page.names() == ['works/34816549 No Paths - Cal 2024-06-01.html']

# endregion


# region run history

def test_a_run_writes_its_history_into_the_library_and_reads_it_back(page):
    fileops = library(page)
    runs.RunRecord(fileops, 'abcdef1234', 'quick', 'Quick Scan', ['JSON'], {}).finish(
        runs.STATUS_SUCCESS)

    assert [x.startswith('runs/') for x in page.names()] == [True]
    assert [(x['id'], x['status']) for x in runs.read_runs(fileops)] == [
        ('abcdef1234', runs.STATUS_SUCCESS)]


def test_the_floors_are_picked_out_of_whatever_history_the_page_sends():
    # the page reads the history out of the library; the rule for which runs qualify stays
    # here, in one place
    records = [
        {'id': 'a', 'status': runs.STATUS_SUCCESS, 'action': server.ACTION_BOOKMARKS},
        {'id': 'b', 'status': runs.STATUS_FAILED, 'action': server.ACTION_BOOKMARKS},
        {'id': 'c', 'status': runs.STATUS_SUCCESS, 'action': server.ACTION_UPDATE},
        'not a record',
    ]
    assert [x['id'] for x in server.floors_among(records)] == ['a']


def test_the_page_asks_for_the_floors_by_sending_the_history():
    sent = {}
    handler = MagicMock()
    handler.path = '/api/runs/floors'
    handler.read_json.return_value = {'runs': [
        {'id': 'a', 'status': runs.STATUS_SUCCESS, 'action': server.ACTION_BOOKMARKS}]}
    handler.send_json.side_effect = lambda status, answer: sent.update(status=status, body=answer)

    server.Handler.do_POST(handler)

    assert sent['status'] == 200
    assert [x['id'] for x in sent['body']['runs']] == ['a']

# endregion


# region the round trip through a real job

def answering(job: server.Job, page: FakePage, stop: threading.Event) -> threading.Thread:
    """What the page does: read requests off the stream, do them, post the answers."""

    def run() -> None:
        job.page_connected(True)
        try:
            while not stop.is_set():
                try:
                    event = job.events.get(timeout=0.05)
                except Exception:
                    continue
                if not event or event.get('type') != progress.STORAGE: continue
                args = {k: v for k, v in event.items() if k not in ('type', 'id', 'op', 'blob')}
                # the bytes are collected separately, as the page fetches them
                content = job.blobs.get(event['id']) if event.get('blob') else None
                job.storage_reply(event['id'], page.storage_call(event['op'], args, content))
        finally:
            job.page_connected(False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def test_a_request_goes_out_on_the_stream_and_the_answer_comes_back(page):
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'someone')
    stop = threading.Event()
    answering(job, page, stop)
    try:
        fileops = library_for(job)
        fileops.save_bytes('works/1 A.html', b'bytes')
        assert fileops.storage.read_bytes('library:/works/1 A.html') == b'bytes'
    finally:
        stop.set()
    assert page.files == {'works/1 A.html': b'bytes'}
    # and nothing about the library went into the history a reconnecting page is replayed
    assert not [e for e in job.history if e.get('type') == progress.STORAGE]


def library_for(job: server.Job) -> FileOps:
    return FileOps(storage=PageStorage(job))


def test_the_bytes_of_a_write_are_there_to_collect_until_it_is_answered(page):
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'someone')
    job.page_connected(True)
    result = {}
    writer = threading.Thread(target=lambda: result.update(
        answer=job.storage_call('write', {'path': 'works/1.html'}, b'an epub')))
    writer.start()
    event = job.events.get(timeout=2)

    assert event['blob'] is True and 'content' not in event
    assert job.blobs[event['id']] == b'an epub'
    job.storage_reply(event['id'], {'size': 7})
    writer.join(2)

    assert result['answer'] == {'size': 7}
    assert event['id'] not in job.blobs


def test_a_page_that_reconnects_is_sent_what_it_never_answered(page):
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'someone')
    job.page_connected(True)
    reader = threading.Thread(target=lambda: job.storage_call('read', {'path': 'a.json'}))
    reader.start()
    event = job.events.get(timeout=2)

    assert job.unanswered() == [event]
    job.storage_reply(event['id'], {'missing': True})
    reader.join(2)
    assert job.unanswered() == []


def test_a_run_whose_page_has_gone_fails_saying_so(monkeypatch):
    monkeypatch.setattr(server, 'PAGE_GRACE_SECONDS', 0)
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'someone')
    job.page_connected(True)
    job.page_connected(False)
    time.sleep(0.01)

    with pytest.raises(OSError) as raised:
        job.storage_call('read', {'path': 'a.json'})
    assert str(raised.value) == strings.ERROR_PAGE_GONE


def test_an_answer_for_nothing_waiting_is_turned_away():
    job = server.Job(server.ACTION_QUICK, ['JSON'], 'someone')
    assert job.storage_reply('made-up', {}) is False


def test_a_whole_run_writes_into_the_library_the_page_has_open(page, tmp_path, monkeypatch):
    # the real path a run takes: a library opened through the page, the folders it should
    # have made, a history file written into it - and nothing written on this computer
    monkeypatch.chdir(tmp_path)
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)
    stop = threading.Event()
    answering(job, page, stop)

    try:
        with patch.object(server, 'Repository', return_value=repo), \
             patch.object(server, 'run_bookmarks'):
            server.run_job(job, 'a-password')
    finally:
        stop.set()

    assert job.history[-1]['type'] == progress.FINISHED, job.history[-1]
    assert page.folders == set(strings.LIBRARY_FOLDER_NAMES)
    [record] = page.names()
    assert record.startswith('runs/')
    assert json.loads(page.files[record])['status'] == runs.STATUS_SUCCESS
    # no library was made beside the helper
    assert not (tmp_path / 'downloads').exists()


def test_a_run_with_no_page_fails_rather_than_hanging(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, 'PAGE_GRACE_SECONDS', 0)
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone')

    server.run_job(job, 'a-password')

    assert job.history[-1]['type'] == progress.FAILED
    assert job.history[-1]['error'] == strings.ERROR_PAGE_GONE

# endregion


# region the local folder is unchanged

def test_a_local_library_is_exactly_the_folder_it_always_was(tmp_path):
    storage = LocalStorage(str(tmp_path))
    path = os.path.join(str(tmp_path), 'sub', '1 A.html')
    storage.write_bytes(path, b'abc')

    assert storage.size(path) == 3
    assert storage.files_under(str(tmp_path)) == [path]
    assert storage.list_files(os.path.join(str(tmp_path), 'sub')) == ['1 A.html']
    assert storage.rename(path, path) is False
    assert storage.delete(path) is True
    assert storage.size(path) is None

# endregion
