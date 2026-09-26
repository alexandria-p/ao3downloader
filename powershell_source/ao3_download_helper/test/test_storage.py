"""Tests for source_code.storage - the downloads folder kept in Dropbox.

Everything here runs against `FakeDropbox`, an in-memory stand-in for the handful of Dropbox
endpoints the helper calls, so nothing reaches the network. It answers the way Dropbox does
where it matters: case-insensitive paths, 409 with an `error_summary` for a missing path or
a name already taken, 401 for an expired token, 429 with Retry-After when it is busy.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from source_code import runs, server, strings
from source_code.actions import shared
from source_code.fileio import FileOps
from source_code.storage import (DropboxClient, DropboxError, DropboxStorage, LocalStorage,
                                 api_arg)


class Answer:
    """Just enough of a requests.Response for the client."""

    def __init__(self, status: int, body=None, content: bytes | None = None,
                 headers: dict | None = None) -> None:
        self.status_code = status
        self.ok = 200 <= status < 300
        self.headers = headers or {}
        if content is not None:
            self.content = content
        else:
            self.content = json.dumps(body).encode('utf-8') if body is not None else b''
        self.text = self.content.decode('utf-8', 'replace')

    def json(self):
        return json.loads(self.content)


def conflict(summary: str) -> Answer:
    return Answer(409, {'error_summary': summary})


class FakeDropbox:
    """An app folder in memory, reached through the same calls the real one is."""

    def __init__(self) -> None:
        self.refresh_token = 'refresh-1'
        self.issued = 0
        self.token = ''
        self.files: dict[str, tuple[str, bytes]] = {}   # lower path -> (display path, bytes)
        self.folders: dict[str, str] = {}               # lower path -> display path
        self.ids: dict[str, str] = {}                   # id -> lower path
        self.calls: list[str] = []
        self.headers: list[dict] = []
        self.busy = 0
        self.page_size = 3
        self.cursors: dict[str, list[dict]] = {}

    # region setting it up

    def folder(self, path: str, folder_id: str = '') -> None:
        parts = path.strip('/').split('/')
        for i in range(1, len(parts) + 1):
            display = '/' + '/'.join(parts[:i])
            self.folders.setdefault(display.lower(), display)
        if folder_id: self.ids[folder_id] = path.lower()

    def put(self, path: str, content: bytes = b'x') -> None:
        # dropbox makes the folders above a file as it writes one
        parent = path.rsplit('/', 1)[0]
        if parent: self.folder(parent)
        self.files[path.lower()] = (path, content)

    def names(self) -> list[str]:
        return sorted(display for display, _ in self.files.values())

    def expire(self) -> None:
        self.token = 'expired'

    # endregion

    def post(self, url: str, headers=None, data=None, timeout=None) -> Answer:
        endpoint = url.split('.com/')[-1].removeprefix('2/')
        self.calls.append(endpoint)
        self.headers.append(dict(headers or {}))

        if endpoint == 'oauth2/token':
            if data.get('refresh_token') != self.refresh_token or not data.get('client_id'):
                return Answer(400, {'error': 'invalid_grant',
                                    'error_description': 'refresh token is invalid or revoked'})
            self.issued += 1
            self.token = f'access-{self.issued}'
            return Answer(200, {'access_token': self.token, 'expires_in': 14400,
                                'token_type': 'bearer'})

        if (headers or {}).get('Authorization') != f'Bearer {self.token}':
            return Answer(401, {'error_summary': 'expired_access_token/'})
        if self.busy:
            self.busy -= 1
            return Answer(429, {'error_summary': 'too_many_write_operations/'},
                          headers={'Retry-After': '2'})

        if endpoint in ('files/upload', 'files/download'):
            arg = json.loads(headers['Dropbox-API-Arg'])
            return getattr(self, endpoint.replace('files/', ''))(arg, data)
        args = json.loads(data) if data else {}
        return getattr(self, endpoint.replace('files/', '').replace('/', '_'))(args)

    # region endpoints

    def resolve(self, path: str) -> str:
        return self.ids.get(path, path.lower())

    def meta(self, lower: str) -> dict | None:
        if lower in self.files:
            display, content = self.files[lower]
            return {'.tag': 'file', 'name': display.rsplit('/', 1)[-1], 'path_display': display,
                    'path_lower': lower, 'size': len(content), 'id': 'id:' + lower}
        if lower in self.folders:
            display = self.folders[lower]
            folder_id = next((k for k, v in self.ids.items() if v == lower), 'id:' + lower)
            return {'.tag': 'folder', 'name': display.rsplit('/', 1)[-1],
                    'path_display': display, 'path_lower': lower, 'id': folder_id}
        return None

    def upload(self, arg: dict, content: bytes) -> Answer:
        self.put(arg['path'], content)
        return Answer(200, self.meta(arg['path'].lower()))

    def download(self, arg: dict, _) -> Answer:
        found = self.files.get(self.resolve(arg['path']))
        if not found: return conflict('path/not_found/..')
        return Answer(200, content=found[1])

    def get_metadata(self, args: dict) -> Answer:
        meta = self.meta(self.resolve(args['path']))
        return Answer(200, meta) if meta else conflict('path/not_found/.')

    def list_folder(self, args: dict) -> Answer:
        base = self.resolve(args['path'])
        if base and base not in self.folders: return conflict('path/not_found/..')
        entries = []
        for lower in sorted(set(self.files) | set(self.folders)):
            if not lower.startswith(base + '/'): continue
            rest = lower[len(base) + 1:]
            if not args.get('recursive') and '/' in rest: continue
            entries.append(self.meta(lower))
        cursor = f'c{len(self.cursors)}'
        self.cursors[cursor] = entries
        return self.list_folder_continue({'cursor': cursor})

    def list_folder_continue(self, args: dict) -> Answer:
        remaining = self.cursors.pop(args['cursor'])
        page, rest = remaining[:self.page_size], remaining[self.page_size:]
        cursor = f'c{len(self.cursors) + 100}'
        if rest: self.cursors[cursor] = rest
        return Answer(200, {'entries': page, 'cursor': cursor, 'has_more': bool(rest)})

    def delete_v2(self, args: dict) -> Answer:
        lower = args['path'].lower()
        if lower not in self.files: return conflict('path_lookup/not_found/..')
        meta = self.meta(lower)
        del self.files[lower]
        return Answer(200, {'metadata': meta})

    def move_v2(self, args: dict) -> Answer:
        old, new = args['from_path'].lower(), args['to_path'].lower()
        if old not in self.files: return conflict('from_lookup/not_found/..')
        if new in self.files and new != old: return conflict('to/conflict/file/..')
        _, content = self.files.pop(old)
        self.put(args['to_path'], content)
        return Answer(200, {'metadata': self.meta(new)})

    # endregion


@pytest.fixture
def dropbox():
    return FakeDropbox()


def client_for(dropbox: FakeDropbox, waits: list | None = None) -> DropboxClient:
    return DropboxClient('app-key', 'refresh-1', session=dropbox,
                         sleep=(waits.append if waits is not None else (lambda _: None)))


def library(dropbox: FakeDropbox, folder: str = '/Fics') -> FileOps:
    """A FileOps whose downloads folder is `folder` in the fake Dropbox."""

    if folder: dropbox.folder(folder)
    return FileOps(storage=DropboxStorage(client_for(dropbox), folder))


# region paths

def test_a_dropbox_path_can_never_be_mistaken_for_a_folder_on_this_computer(dropbox):
    fileops = library(dropbox)
    assert fileops.downloadfolder == 'dropbox:/Fics'
    assert not os.path.isabs(fileops.downloadfolder)


def test_paths_built_the_usual_way_become_dropbox_paths(dropbox):
    storage = library(dropbox).storage
    built = os.path.join(storage.root, strings.INDEXING_FOLDER_NAME, '123 A Fic.json')
    assert storage.remote(built) == '/Fics/indexing/123 A Fic.json'


def test_the_app_folder_itself_is_the_empty_path(dropbox):
    storage = DropboxStorage(client_for(dropbox), '')
    assert storage.root == 'dropbox:'
    assert storage.remote(os.path.join(storage.root, 'runs', 'a.json')) == '/runs/a.json'


def test_a_path_outside_the_chosen_folder_is_refused(dropbox):
    storage = library(dropbox).storage
    with pytest.raises(ValueError):
        storage.remote('dropbox:/Elsewhere/secret.txt')
    with pytest.raises(ValueError):
        storage.remote(r'C:\Users\someone\Fics\123.html')


def test_a_path_is_described_as_where_it_is_in_dropbox(dropbox):
    fileops = library(dropbox)
    assert fileops.describe(os.path.join(fileops.downloadfolder, 'x.html')) == 'Dropbox app folder/Fics/x.html'


def test_a_fic_title_in_a_header_goes_as_plain_ascii():
    # a header must be ascii and titles are anything but
    header = api_arg({'path': '/Fics/123 Café ☕ - Autor.html\x7f'})
    assert header.isascii()
    assert '\\u00e9' in header and '\\u2615' in header and '\\u007f' in header
    assert json.loads(header)['path'] == '/Fics/123 Café ☕ - Autor.html\x7f'

# endregion


# region reading and writing

def test_json_goes_into_dropbox_and_comes_back_the_same(dropbox):
    fileops = library(dropbox)
    name = os.path.join(strings.INDEXING_FOLDER_NAME, '123 Café - Someone.json')

    fileops.save_json(name, {'title': 'Café', 'indexes': [1, 2]})

    assert dropbox.names() == ['/Fics/indexing/123 Café - Someone.json']
    assert fileops.load_json(name) == {'title': 'Café', 'indexes': [1, 2]}


def test_json_that_is_not_there_is_absent_rather_than_an_error(dropbox):
    assert library(dropbox).load_json('indexing/999.json') is None


def test_damaged_json_is_absent_rather_than_ending_the_run(dropbox):
    fileops = library(dropbox)
    dropbox.put('/Fics/indexing/1.json', b'not json')
    assert fileops.load_json('indexing/1.json') is None


def test_a_downloaded_work_is_confirmed_from_the_upload_without_asking_again(dropbox):
    # the upload's own answer is dropbox saying what it stored - a second request per file
    # to ask the same thing would cost a request for every format of every fic
    fileops = library(dropbox)
    saved = fileops.save_bytes('123 A Fic - Someone 2024-12-14.html', b'the whole fic')
    before = len(dropbox.calls)

    assert fileops.saved_intact(saved, len(b'the whole fic')) is True
    assert fileops.saved_intact(saved, 999) is False
    assert len(dropbox.calls) == before


def test_a_file_this_run_did_not_write_is_looked_up(dropbox):
    fileops = library(dropbox)
    dropbox.put('/Fics/123 Old.html', b'twelve bytes')
    path = os.path.join(fileops.downloadfolder, '123 Old.html')

    assert fileops.saved_intact(path, 12) is True
    assert 'files/get_metadata' in dropbox.calls


def test_a_file_that_is_not_there_says_where_it_was_looked_for(dropbox):
    fileops = library(dropbox)
    path = os.path.join(fileops.downloadfolder, '123 Gone.html')
    assert fileops.saved_problem(path, 10) == strings.SAVED_NOT_FOUND.format('Dropbox app folder/Fics/123 Gone.html')


def test_deleting_a_file_already_gone_counts_as_done(dropbox):
    fileops = library(dropbox)
    assert fileops.delete_file(os.path.join(fileops.downloadfolder, 'nothing.html')) is True


def test_a_replaced_copy_goes_to_the_dropbox_trash(dropbox):
    fileops = library(dropbox)
    dropbox.put('/Fics/123 A 2024-01-01.html', b'old')
    assert fileops.delete_file(os.path.join(fileops.downloadfolder, '123 A 2024-01-01.html'))
    assert dropbox.names() == []
    assert 'files/delete_v2' in dropbox.calls


def test_renaming_will_not_write_over_a_file_already_there(dropbox):
    fileops = library(dropbox)
    dropbox.put('/Fics/1 A.html', b'a')
    dropbox.put('/Fics/1 A 2024-01-01.html', b'b')
    root = fileops.downloadfolder

    assert fileops.rename_file(os.path.join(root, '1 A.html'),
                               os.path.join(root, '1 A 2024-01-01.html')) is False
    assert dropbox.files['/fics/1 a 2024-01-01.html'][1] == b'b'


def test_asking_after_many_files_costs_one_listing_not_a_request_each(dropbox):
    # `shared.visited` asks this of every work in the log, in every format
    for work in range(10):
        dropbox.put(f'/Fics/{work} Fic.html')
    fileops = library(dropbox)
    root = fileops.downloadfolder

    found = [fileops.exists(os.path.join(root, f'{work} Fic.html')) for work in range(20)]

    assert found == [True] * 10 + [False] * 10
    assert dropbox.calls.count('files/get_metadata') == 0
    assert dropbox.calls.count('files/list_folder') == 1


def test_what_this_run_writes_deletes_and_renames_is_seen_straight_away(dropbox):
    fileops = library(dropbox)
    root = fileops.downloadfolder
    assert not fileops.exists(os.path.join(root, 'a.html'))

    fileops.save_bytes('a.html', b'a')
    assert fileops.exists(os.path.join(root, 'a.html'))
    fileops.rename_file(os.path.join(root, 'a.html'), os.path.join(root, 'b.html'))
    assert not fileops.exists(os.path.join(root, 'a.html'))
    assert fileops.exists(os.path.join(root, 'b.html'))
    fileops.delete_file(os.path.join(root, 'b.html'))
    assert not fileops.exists(os.path.join(root, 'b.html'))
    assert dropbox.calls.count('files/list_folder') == 1


def test_the_same_name_in_another_case_is_the_same_file(dropbox):
    fileops = library(dropbox)
    assert fileops.same_file('dropbox:/Fics/123 A.html', 'dropbox:/fics/123 a.HTML')

# endregion


# region reading the library back

def test_the_downloaded_works_are_found_in_one_recursive_listing(dropbox):
    # a page per so many files, rather than a request per subfolder
    dropbox.put('/Fics/111 One - A 2024-01-01.html')
    dropbox.put('/Fics/old/222 Two - B.epub')
    dropbox.put('/Fics/indexing/111 One - A.json')
    dropbox.put('/Fics/runs/2026-01-01.json')
    dropbox.put('/Fics/images/111_1.png')
    dropbox.put('/Fics/notes.html')
    fileops = library(dropbox)

    found = shared.scan_downloaded_works(fileops.downloadfolder, ['HTML', 'EPUB', 'JSON', 'PNG'],
                                         storage=fileops.storage)

    assert set(found) == {'111', '222'}
    assert found['111']['HTML'] == {'path': 'dropbox:/Fics/111 One - A 2024-01-01.html',
                                    'date': '2024-01-01'}
    assert found['222']['EPUB']['date'] is None
    assert dropbox.calls.count('files/list_folder') == 1


def test_a_library_folder_that_is_empty_is_an_empty_library(dropbox):
    fileops = library(dropbox)
    assert shared.scan_downloaded_works(fileops.downloadfolder, ['HTML'],
                                        storage=fileops.storage) == {}
    assert shared.read_index(fileops) == []
    assert shared.indexed_work_ids(fileops) == set()


def test_the_index_is_read_from_dropbox_across_pages_of_the_listing(dropbox):
    fileops = library(dropbox)
    for work in ('111', '222', '333', '444'):
        fileops.save_json(os.path.join(strings.INDEXING_FOLDER_NAME, f'{work} Fic.json'), {
            'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'indexes': [{'title': f'Work {work}'}]})

    assert shared.indexed_work_ids(fileops) == {'111', '222', '333', '444'}
    assert [x['id'] for x in shared.read_index(fileops)] == ['111', '222', '333', '444']
    assert 'files/list_folder/continue' in dropbox.calls


def test_undated_files_are_dated_where_they_sit_in_dropbox(dropbox):
    dropbox.put('/Fics/34816549 No Paths - Cal.html', b'fic')
    fileops = library(dropbox)
    existing = shared.scan_downloaded_works(fileops.downloadfolder, ['HTML'],
                                            storage=fileops.storage)

    result = shared.stamp_undated_works(fileops, existing, {'34816549'}, '2024-06-01', 50)

    assert (result['renamed'], result['skipped']) == (1, 0)
    assert dropbox.names() == ['/Fics/34816549 No Paths - Cal 2024-06-01.html']
    assert existing['34816549']['HTML']['date'] == '2024-06-01'

# endregion


# region run history

def test_a_run_writes_its_history_into_the_dropbox_folder_and_reads_it_back(dropbox):
    fileops = library(dropbox)
    record = runs.RunRecord(fileops, 'abcdef1234', 'quick', 'Quick Scan', ['JSON'], {})
    record.finish(runs.STATUS_SUCCESS)

    assert [x.startswith('/Fics/runs/') for x in dropbox.names()] == [True]
    history = runs.read_runs(fileops)
    assert [(x['id'], x['status']) for x in history] == [('abcdef1234', runs.STATUS_SUCCESS)]


def test_a_dropbox_library_with_no_history_has_none(dropbox):
    assert runs.read_runs(library(dropbox)) == []

# endregion


# region the session

def test_an_expired_access_token_is_renewed_and_the_call_made_again(dropbox):
    fileops = library(dropbox)
    fileops.save_json('a.json', {})
    dropbox.expire()

    fileops.save_json('b.json', {})

    assert dropbox.issued == 2
    assert dropbox.names() == ['/Fics/a.json', '/Fics/b.json']


def test_renewing_sends_the_app_key_and_no_secret(dropbox):
    sent = []
    real = dropbox.post
    dropbox.post = lambda url, headers=None, data=None, timeout=None: (
        sent.append(data) if url.endswith('oauth2/token') else None) or real(url, headers, data, timeout)
    library(dropbox).save_json('a.json', {})

    assert sent[0] == {'grant_type': 'refresh_token', 'refresh_token': 'refresh-1',
                       'client_id': 'app-key'}


def test_a_session_dropbox_will_not_renew_says_to_sign_in_again(dropbox):
    dropbox.refresh_token = 'revoked from dropbox.com'
    with pytest.raises(DropboxError) as raised:
        library(dropbox).save_json('a.json', {})
    assert 'sign in again' in str(raised.value)


def test_a_busy_dropbox_is_waited_out_for_as_long_as_it_asks(dropbox):
    waits = []
    dropbox.folder('/Fics')
    fileops = FileOps(storage=DropboxStorage(client_for(dropbox, waits), '/Fics'))
    dropbox.busy = 2

    fileops.save_json('a.json', {})

    assert waits == [2.0, 2.0]
    assert dropbox.names() == ['/Fics/a.json']


def test_the_chosen_folder_is_found_by_id_after_a_rename(dropbox):
    dropbox.folder('/Library', folder_id='id:lib')

    storage = DropboxStorage.connect(client_for(dropbox), 'id:lib', '/Fics')

    assert storage.folder_path == '/Library'


def test_a_folder_that_has_gone_is_named_before_the_run_does_anything(dropbox):
    with pytest.raises(DropboxError) as raised:
        DropboxStorage.connect(client_for(dropbox), 'id:gone', '/Fics')
    assert '/Fics' in str(raised.value)
    assert 'not there any more' in str(raised.value)


def test_a_folder_deleted_mid_session_is_caught_when_the_run_starts(dropbox):
    fileops = FileOps(storage=DropboxStorage(client_for(dropbox), '/Fics'))
    with pytest.raises(DropboxError):
        fileops.storage.ensure_root()

# endregion


# region the helper's side of the request

DROPBOX = {'kind': 'dropbox', 'appKey': 'app-key', 'refreshToken': 'refresh-1',
           'folderId': 'id:fics', 'folderPath': '/Fics'}


def test_a_request_with_no_storage_is_the_local_folder():
    assert server.storage_request({}) is None
    assert server.storage_request({'storage': {'kind': 'local'}}) is None


def test_a_dropbox_request_carries_what_a_run_needs():
    assert server.storage_request({'storage': DROPBOX}) == {
        'appKey': 'app-key', 'refreshToken': 'refresh-1', 'folderId': 'id:fics',
        'folderPath': '/Fics'}


@pytest.mark.parametrize('broken', [
    {**DROPBOX, 'refreshToken': ''},
    {**DROPBOX, 'appKey': ''},
    {**DROPBOX, 'folderPath': 'Fics'},
    {**DROPBOX, 'kind': 'gdrive'},
])
def test_a_dropbox_request_missing_something_is_refused(broken):
    with pytest.raises(ValueError):
        server.storage_request({'storage': broken})


def post_job(body: dict) -> tuple[dict, list]:
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = body
    handler.send_json.side_effect = lambda status, answer: sent.update(status=status, body=answer)
    with patch.object(server.threading, 'Thread') as thread:
        server.Handler.do_POST(handler)
    return sent, thread.call_args_list


def test_a_job_is_handed_the_dropbox_session_and_never_echoes_it_back():
    sent, threads = post_job({'action': server.ACTION_QUICK, 'username': 'Someone',
                              'password': 'a-password', 'filetypes': ['JSON'],
                              'storage': DROPBOX})

    assert sent['status'] == 202
    assert 'refresh-1' not in json.dumps(sent['body'])
    job = threads[0].kwargs['args'][0]
    assert job.storage['refreshToken'] == 'refresh-1'
    assert 'refresh-1' not in json.dumps(job.options)


def test_an_incomplete_dropbox_session_is_refused_before_a_job_starts():
    sent, threads = post_job({'action': server.ACTION_QUICK, 'username': 'Someone',
                              'password': 'a-password', 'storage': {**DROPBOX, 'refreshToken': ''}})
    assert sent['status'] == 400
    assert threads == []


def test_a_run_writes_into_the_library_it_was_handed(dropbox, tmp_path, monkeypatch):
    # the whole path a real run takes: a session in, a library opened, a history file out -
    # and the session itself in none of what the run leaves behind
    monkeypatch.chdir(tmp_path)
    dropbox.folder('/Fics', folder_id='id:fics')
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone',
                     storage=server.storage_request({'storage': DROPBOX}))
    repo = MagicMock()
    repo.__enter__ = MagicMock(return_value=repo)
    repo.__exit__ = MagicMock(return_value=False)

    with patch.object(server, 'DropboxClient', side_effect=lambda key, token: client_for(dropbox)), \
         patch.object(server, 'Repository', return_value=repo), \
         patch.object(server, 'run_bookmarks'):
        server.run_job(job, 'a-password')

    assert job.history[-1]['type'] != 'failed', job.history[-1]
    started = next(e for e in job.history if e['type'] == 'started')
    assert started['folder'] == 'Dropbox app folder/Fics'
    [record] = [display for display, _ in dropbox.files.values()]
    assert record.startswith('/Fics/runs/')
    written = dropbox.files[record.lower()][1].decode('utf-8')
    assert 'refresh-1' not in written
    assert 'refresh-1' not in json.dumps(job.history)
    # the request log and settings stay on this computer
    assert not any('log' in name for name in dropbox.names())


def test_a_run_whose_folder_has_gone_fails_saying_which(dropbox, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    job = server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'someone',
                     storage=server.storage_request({'storage': DROPBOX}))

    with patch.object(server, 'DropboxClient', side_effect=lambda key, token: client_for(dropbox)):
        server.run_job(job, 'a-password')

    assert job.history[-1]['type'] == 'failed'
    assert 'not there any more' in job.history[-1]['error']


def test_the_history_of_a_dropbox_library_is_asked_for_by_post(dropbox, tmp_path, monkeypatch):
    # the session travels in the body, never in a url
    monkeypatch.chdir(tmp_path)
    dropbox.folder('/Fics', folder_id='id:fics')
    fileops = library(dropbox)
    runs.RunRecord(fileops, 'abcdef1234', 'quick', 'Quick Scan', ['JSON'], {}).finish(
        runs.STATUS_SUCCESS)

    sent = {}
    handler = MagicMock()
    handler.path = '/api/runs'
    handler.read_json.return_value = {'storage': DROPBOX}
    handler.send_json.side_effect = lambda status, answer: sent.update(status=status, body=answer)
    handler.send_runs.side_effect = lambda spec: server.Handler.send_runs(handler, spec)

    with patch.object(server, 'DropboxClient', side_effect=lambda key, token: client_for(dropbox)):
        server.Handler.do_POST(handler)

    assert sent['status'] == 200
    assert [x['id'] for x in sent['body']['runs']] == ['abcdef1234']

# endregion


# region the local folder is unchanged

def test_a_local_run_makes_every_folder_a_library_is_expected_to_have(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fileops = FileOps()
    fileops.downloadfolder = str(tmp_path / 'library')
    fileops.initialize()

    assert sorted(os.listdir(tmp_path / 'library')) == sorted(strings.LIBRARY_FOLDER_NAMES)
    assert fileops.worksfolder == os.path.join(str(tmp_path / 'library'), 'works')


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
