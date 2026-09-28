"""Background runs: the helper reaching Dropbox itself, answered up front, one at a time."""

import base64
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from source_code import access, dropbox_library, exceptions, progress, runs, server, strings
from source_code.storage import PageStorage


DROPBOX = {'refreshToken': 'refresh-me', 'appKey': 'app-key'}


# region a Dropbox that answers from memory

class FakeResponse:
    def __init__(self, status=200, body=None, content=None, headers=None):
        self.status_code = status
        self.headers = headers or {}
        if content is not None:
            self.content = content
        else:
            self.content = json.dumps(body).encode() if body is not None else b''
        self.text = self.content.decode('utf-8', 'replace')

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return json.loads(self.content) if self.content else None


class FakeDropbox:
    """Enough of the Dropbox api for a run: a dict of files, and a log of what was asked."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict]] = []
        self.tokens_issued = 0
        # queued answers that win over the normal ones, for failures
        self.next: list[FakeResponse] = []
        self.refuse_refresh = False

    def post(self, url, data=None, headers=None, timeout=None):
        endpoint = url.split('/2/')[-1] if '/2/' in url else url
        if url == dropbox_library.TOKEN_URL:
            self.calls.append(('token', dict(data)))
            if self.refuse_refresh: return FakeResponse(400, {'error': 'invalid_grant'})
            self.tokens_issued += 1
            return FakeResponse(200, {'access_token': f'token-{self.tokens_issued}',
                                      'expires_in': 14400})
        arg = json.loads(headers['Dropbox-API-Arg']) if 'Dropbox-API-Arg' in (headers or {}) \
            else json.loads(data or b'{}')
        self.calls.append((endpoint, arg))
        if self.next: return self.next.pop(0)
        path = arg.get('path', '')
        if endpoint == 'files/upload':
            self.files[path] = data
            return FakeResponse(200, {'size': len(data)})
        if endpoint == 'files/download':
            if path not in self.files:
                return FakeResponse(409, {'error_summary': 'path/not_found/..'})
            return FakeResponse(200, content=self.files[path])
        if endpoint == 'files/list_folder':
            names = sorted(p for p in self.files if p.startswith(path + '/') or not path)
            if not names and path:
                return FakeResponse(409, {'error_summary': 'path/not_found/'})
            half = len(names) // 2 or len(names)
            return FakeResponse(200, {
                'entries': [{'.tag': 'file', 'path_display': n} for n in names[:half]],
                'has_more': half < len(names), 'cursor': json.dumps(names[half:])})
        if endpoint == 'files/list_folder/continue':
            rest = json.loads(arg['cursor'])
            return FakeResponse(200, {'entries': [{'.tag': 'file', 'path_display': n}
                                                  for n in rest], 'has_more': False})
        if endpoint == 'files/get_metadata':
            if path not in self.files:
                return FakeResponse(409, {'error_summary': 'path/not_found/'})
            return FakeResponse(200, {'.tag': 'file', 'size': len(self.files[path])})
        if endpoint == 'files/delete_v2':
            if path not in self.files:
                return FakeResponse(409, {'error_summary': 'path_lookup/not_found/'})
            del self.files[path]
            return FakeResponse(200, {})
        if endpoint == 'files/move_v2':
            self.files[arg['to_path']] = self.files.pop(arg['from_path'])
            return FakeResponse(200, {})
        if endpoint == 'files/create_folder_v2':
            return FakeResponse(409, {'error_summary': 'path/conflict/folder/'})
        return FakeResponse(400, {'error_summary': f'unknown {endpoint}'})


@pytest.fixture
def dropbox():
    return FakeDropbox()


@pytest.fixture
def channel(dropbox):
    return dropbox_library.DropboxChannel('refresh-me', 'app-key', session=dropbox,
                                          sleep=lambda seconds: None)

# endregion


# region the helper's own line to Dropbox

@pytest.mark.parametrize('path, expected', [('', ''), ('works/a.html', '/works/a.html'),
                                            ('/indexing//x.json', '/indexing/x.json'),
                                            ('works\\a.html', '/works/a.html')])
def test_a_library_path_is_named_as_the_dropbox_api_names_it(path, expected):
    assert dropbox_library.remote(path) == expected


def test_a_write_and_a_read_answer_as_the_page_answers(channel, dropbox):
    assert channel.storage_call('write', {'path': 'works/1 A.html'}, b'<html>') == {'size': 6}
    assert channel.storage_call('read', {'path': 'works/1 A.html'}) == {'text': '<html>'}
    assert dropbox.files == {'/works/1 A.html': b'<html>'}


def test_a_file_that_is_not_there_reads_as_missing_not_as_an_error(channel):
    assert channel.storage_call('read', {'path': 'indexing/9.json'}) == {'missing': True}


def test_a_listing_is_every_file_across_every_page_dropbox_sends(channel, dropbox):
    for name in ['/a.json', '/works/1.html', '/works/2.html', '/runs/r.json']:
        dropbox.files[name] = b'x'

    listed = channel.storage_call('list', {'path': '', 'recursive': True})['files']

    assert sorted(listed) == ['a.json', 'runs/r.json', 'works/1.html', 'works/2.html']
    assert ('files/list_folder/continue', {'cursor': json.dumps(['/works/1.html', '/works/2.html'])}) \
        in dropbox.calls


def test_a_folder_that_is_not_there_lists_as_empty(channel):
    assert channel.storage_call('list', {'path': 'images', 'recursive': True}) == {'files': []}


def test_a_size_is_the_size_dropbox_holds_or_none(channel, dropbox):
    dropbox.files['/works/1.html'] = b'12345'
    assert channel.storage_call('size', {'path': 'works/1.html'}) == {'size': 5}
    assert channel.storage_call('size', {'path': 'works/2.html'}) == {'size': None}


def test_deleting_a_file_already_gone_is_not_an_error(channel):
    assert channel.storage_call('delete', {'path': 'works/gone.html'}) == {}


def test_a_rename_moves_the_file_without_writing_over_anything(channel, dropbox):
    dropbox.files['/works/1 A.html'] = b'x'

    assert channel.storage_call('rename', {'path': 'works/1 A.html',
                                           'to': 'works/1 A 2024-01-01.html'}) == {}

    assert dropbox.calls[-1] == ('files/move_v2', {'from_path': '/works/1 A.html',
                                                   'to_path': '/works/1 A 2024-01-01.html',
                                                   'autorename': False})


def test_a_folder_already_there_is_not_an_error(channel):
    assert channel.storage_call('mkdir', {'path': 'works'}) == {}


def test_the_access_token_is_fetched_once_and_reused(channel, dropbox):
    for n in range(3): channel.storage_call('write', {'path': f'{n}.json'}, b'x')
    assert dropbox.tokens_issued == 1


def test_an_expired_token_is_refreshed_and_the_call_made_again(channel, dropbox):
    dropbox.next = [FakeResponse(401, {'error_summary': 'expired_access_token/'})]

    assert channel.storage_call('write', {'path': 'a.json'}, b'x') == {'size': 1}
    assert dropbox.tokens_issued == 2


def test_being_asked_to_slow_down_is_waited_out(dropbox):
    waited = []
    channel = dropbox_library.DropboxChannel('r', 'k', session=dropbox, sleep=waited.append)
    dropbox.next = [FakeResponse(429, {'error_summary': 'too_many_requests/'},
                                 headers={'Retry-After': '7'})]

    assert channel.storage_call('write', {'path': 'a.json'}, b'x') == {'size': 1}
    assert waited == [7.0]


def test_a_sign_in_that_has_ended_says_so_as_an_error_the_run_can_report(channel, dropbox):
    dropbox.refuse_refresh = True
    answer = channel.storage_call('check', {})
    assert 'sign in to Dropbox again' in answer['error']


def test_the_refresh_token_and_app_key_are_what_a_token_is_asked_for_with(channel, dropbox):
    channel.storage_call('check', {})
    assert dropbox.calls[0] == ('token', {'grant_type': 'refresh_token',
                                          'refresh_token': 'refresh-me',
                                          'client_id': 'app-key'})


def test_the_ordinary_library_rules_sit_in_front_of_it_unchanged(channel, dropbox):
    # PageStorage is the same object a run through the page uses
    storage = PageStorage(channel)
    storage.write_bytes(storage.local('works/1 A.html'), b'<html>')

    assert storage.read_bytes(storage.local('works/1 A.html')) == b'<html>'
    assert storage.size(storage.local('works/1 A.html')) == 6
    assert storage.is_file(storage.local('works/1 A.html'))

# endregion


# region answered up front

def test_answers_are_checked_against_the_question_they_answer():
    assert server.background_answers({'undated': {'choice': 'stamp', 'date': '2024-01-02'},
                                      'duplicates': {'choice': 'newest'}}) == {
        'undated': {'choice': 'stamp', 'date': '2024-01-02'},
        'duplicates': {'choice': 'newest', 'date': ''}}


@pytest.mark.parametrize('answers, reason', [
    ({'undated': {'choice': 'newest'}}, 'not an answer'),
    ({'nonsense': {'choice': 'skip'}}, 'no question'),
    ({'undated': {'choice': 'stamp'}}, 'needs the date'),
    ({'undated': {'choice': 'stamp', 'date': 'soon'}}, 'needs the date'),
    (['skip'], 'by question'),
])
def test_an_answer_that_could_not_be_acted_on_is_refused_before_the_run_starts(answers, reason):
    with pytest.raises(ValueError, match=reason):
        server.background_answers(answers)


def a_background_job(answers=None):
    return server.Job(server.ACTION_SYNC, ['JSON', 'HTML'], 'Someone',
                      server.resolve_options({}), background=True, answers=answers)


def test_a_background_run_uses_the_answer_it_was_given_up_front(capsys):
    job = a_background_job({'undated': {'choice': 'refresh', 'date': ''}})

    got = job.ask({'name': 'undated', 'count': 3}, {'choice': 'skip', 'date': ''})

    assert got['choice'] == 'refresh'
    assert 'before this background run started' in capsys.readouterr().out


def test_a_background_run_never_waits_on_a_question_nobody_will_answer(capsys):
    job = a_background_job()
    began = time.monotonic()

    got = job.ask({'name': 'duplicates', 'count': 2}, {'choice': 'leave'})

    assert got == {'choice': 'leave'}
    # the ordinary wait is half an hour
    assert time.monotonic() - began < 1
    assert 'changes nothing' in capsys.readouterr().out
    assert not any(e.get('type') == progress.QUESTION for e in job.history)

# endregion


# region starting one

def starting(body, stub_thread=True):
    sent = {}
    handler = MagicMock()
    handler.path = '/api/jobs'
    handler.read_json.return_value = {'action': server.ACTION_SYNC, 'username': 'Someone',
                                      'password': 'a-password', 'filetypes': ['JSON'], **body}
    handler.send_json.side_effect = lambda status, b: sent.update(status=status, body=b)
    with patch.object(server.threading, 'Thread'):
        server.Handler.do_POST(handler)
    return sent


def test_a_background_run_starts_with_its_own_line_to_dropbox_and_its_answers():
    sent = starting({'background': True, 'dropbox': DROPBOX,
                     'answers': {'undated': {'choice': 'skip'}}})

    assert sent['status'] == 202, sent
    job = server.Handler.jobs[sent['body']['jobId']]
    assert job.background is True
    assert isinstance(job.library, dropbox_library.DropboxChannel)
    assert job.library.refresh_token == 'refresh-me'
    assert job.prior_answers == {'undated': {'choice': 'skip', 'date': ''}}


def test_a_background_run_without_a_dropbox_sign_in_is_refused():
    # a folder on the user's computer can only be reached through the page
    sent = starting({'background': True})
    assert sent['status'] == 400
    assert 'Dropbox' in sent['body']['error']


def test_a_background_run_with_answers_it_could_not_act_on_is_refused():
    sent = starting({'background': True, 'dropbox': DROPBOX,
                     'answers': {'undated': {'choice': 'stamp'}}})
    assert sent['status'] == 400
    assert not server.Handler.jobs


def test_an_ordinary_run_is_not_handed_the_dropbox_sign_in_even_if_sent_one():
    sent = starting({'dropbox': DROPBOX})
    job = server.Handler.jobs[sent['body']['jobId']]
    assert job.background is False
    assert job.library is None


def test_a_second_run_is_refused_while_one_is_in_progress():
    first = starting({})
    second = starting({})

    assert second['status'] == 409
    assert second['body']['activeJob'] == first['body']['jobId']
    assert 'already in progress' in second['body']['error']


def test_a_new_run_can_start_once_the_last_one_has_finished():
    first = starting({})
    server.Handler.jobs[first['body']['jobId']].done.set()

    assert starting({})['status'] == 202


def test_the_dropbox_sign_in_travels_inside_the_sealed_login(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    monkeypatch.setenv(access.ENV_PRIVATE_KEY, key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode())
    access._KEYS.clear()
    login = {'username': 'Someone', 'password': 'pw', 'sent': time.time() * 1000,
             'nonce': 'background-1', 'dropbox': DROPBOX}
    sealed = base64.b64encode(key.public_key().encrypt(json.dumps(login).encode(), padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(),
        label=None))).decode()
    try:
        assert access.credentials_from({'credentials': sealed}) == ('Someone', 'pw', DROPBOX)
    finally:
        access._KEYS.clear()

# endregion


# region what the page can see of it

def test_the_runs_going_are_described_without_anything_they_were_given():
    sent = starting({'background': True, 'dropbox': DROPBOX})
    job = server.Handler.jobs[sent['body']['jobId']]
    job.held.set()

    described = server.active_jobs()

    assert described == [{'id': job.id, 'action': server.ACTION_SYNC,
                          'actionName': server.action_name(server.ACTION_SYNC),
                          'background': True, 'started': job.started, 'paused': True,
                          'abandonsAt': '', 'step': ''}]
    said = json.dumps(described)
    assert 'refresh-me' not in said and 'a-password' not in said


def test_the_history_file_says_the_run_was_in_the_background(tmp_path):
    fileops = MagicMock()
    fileops.runsfolder = str(tmp_path)
    record = runs.RunRecord(fileops, 'abcdef123456', 'sync', 'Sync', ['JSON'], {},
                            background=True)
    assert record.data['background'] is True


def test_a_background_run_with_nobody_listening_keeps_its_events_in_its_history_alone():
    job = a_background_job()
    job.emit({'type': progress.PHASE, 'name': 'indexing'})
    assert job.events.empty()
    assert job.history[-1]['name'] == 'indexing'


def test_an_ordinary_run_still_queues_every_event_for_its_page():
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone', server.resolve_options({}))
    job.emit({'type': progress.PHASE, 'name': 'indexing'})
    assert not job.events.empty()


def test_a_long_background_run_replays_only_its_latest_lines(monkeypatch):
    monkeypatch.setattr(server, 'BACKGROUND_KEPT_MESSAGES', 20)
    job = a_background_job()
    job.emit({'type': progress.STEPS, 'steps': []})
    for n in range(100): job.emit({'type': progress.MESSAGE, 'text': f'line {n}'})

    kept = [e['text'] for e in job.history if e['type'] == progress.MESSAGE]
    assert len(kept) <= 22
    assert kept[-1] == 'line 99'
    # anything that is not a printed line is never dropped - the checklist needs it
    assert job.history[0]['type'] == progress.STEPS


@pytest.fixture
def live():
    httpd = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f'http://{server.HOST}:{httpd.server_address[1]}'
    finally:
        httpd.shutdown()
        httpd.server_close()


def read_events(url, until_done=True, timeout=5):
    events = []
    with urllib.request.urlopen(url, timeout=timeout) as response:
        for raw in response:
            line = raw.decode().strip()
            if line.startswith('data:'):
                events.append(json.loads(line[5:]))
                if until_done and events[-1]['type'] in ('finished', 'failed'): break
    return events


def test_a_page_attaching_later_is_shown_everything_so_far_then_what_comes_next(live):
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    job.emit({'type': progress.STEPS, 'steps': [{'id': 'login', 'label': 'Log in'}]})
    job.emit({'type': progress.MESSAGE, 'text': 'before the page came back'})

    def carry_on():
        time.sleep(0.3)
        job.emit({'type': progress.MESSAGE, 'text': 'after'})
        job.emit({'type': progress.FINISHED, 'cancelled': False})
        job.finish()

    threading.Thread(target=carry_on, daemon=True).start()
    events = read_events(f'{live}/api/jobs/{job.id}/events')

    texts = [e.get('text') for e in events if e['type'] == 'message']
    assert texts == ['before the page came back', 'after']
    assert events[0]['type'] == 'steps'
    assert events[-1]['type'] == 'finished'


def test_a_page_attaching_to_a_run_already_over_gets_its_account_and_is_let_go(live):
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    job.emit({'type': progress.FINISHED, 'cancelled': False})
    job.finish()
    # whoever was listening took the end; a page arriving now must not wait for ever
    job.events.get_nowait()

    events = read_events(f'{live}/api/jobs/{job.id}/events', until_done=False)

    assert events[-1]['type'] == 'finished'


def test_the_page_is_told_which_runs_are_going_and_whether_in_the_background(live):
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    with urllib.request.urlopen(f'{live}/api/jobs', timeout=5) as response:
        body = json.loads(response.read())
    assert body['active'] == [job.id]
    assert body['jobs'][0]['background'] is True

# endregion


# region kept awake on a host that sleeps

def test_nothing_is_knocked_on_without_a_background_run():
    get = MagicMock()
    assert server.keep_awake_once('https://helper.example', get) is False
    get.assert_not_called()


def test_nothing_is_knocked_on_when_the_host_gives_no_address():
    server.Handler.jobs['x'] = a_background_job()
    get = MagicMock()
    assert server.keep_awake_once('', get) is False
    get.assert_not_called()


def test_a_background_run_keeps_the_helper_awake_by_calling_its_own_address():
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    get = MagicMock()

    assert server.keep_awake_once('https://helper.example/', get) is True
    get.assert_called_once_with('https://helper.example/api/awake', timeout=30)


def test_a_knock_that_fails_does_not_take_the_helper_down():
    server.Handler.jobs['x'] = a_background_job()
    assert server.keep_awake_once('https://helper.example',
                                  MagicMock(side_effect=OSError('no network'))) is True


def test_an_ordinary_run_does_not_keep_the_helper_awake():
    # a page is talking to it, which already counts
    server.Handler.jobs['x'] = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone',
                                          server.resolve_options({}))
    get = MagicMock()
    assert server.keep_awake_once('https://helper.example', get) is False

# endregion


# region a background run left paused

def paused_background_job(minutes_ago: float, now: float = 1000.0):
    job = a_background_job()
    job.held.set()
    job.held_since = now - minutes_ago * 60
    server.Handler.jobs[job.id] = job
    return job


def test_a_background_run_paused_past_the_timeout_is_abandoned():
    job = paused_background_job(11)

    assert server.abandon_overdue(now=1000.0, minutes=10) == [job.id]
    # ended the way a stop ends it, so it unwinds at the pause gate keeping what it saved
    assert job.cancel.is_set()
    assert job.abandoned is True
    assert 'abandoned it' in job.history[-1]['text']


def test_a_pause_inside_the_timeout_is_left_alone():
    job = paused_background_job(9)
    assert server.abandon_overdue(now=1000.0, minutes=10) == []
    assert not job.cancel.is_set()


def test_a_timeout_of_nought_never_abandons_anything():
    job = paused_background_job(600)
    assert server.abandon_overdue(now=1000.0, minutes=0) == []
    assert not job.cancel.is_set()


def test_a_run_that_is_not_in_the_background_is_never_abandoned():
    # it needs its page, and ends when the page goes anyway
    job = server.Job(server.ACTION_SYNC, ['JSON'], 'Someone', server.resolve_options({}))
    job.held.set()
    job.held_since = 0.0
    server.Handler.jobs[job.id] = job

    assert server.abandon_overdue(now=10_000.0, minutes=10) == []


def test_a_working_background_run_is_never_abandoned():
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    assert server.abandon_overdue(now=10_000.0, minutes=10) == []


def test_the_timeout_comes_from_settings_ini(tmp_path, monkeypatch):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    (tmp_path / strings.INI_FILE_NAME).write_text('[settings]\nPausedRunTimeoutMinutes=25\n',
                                                  encoding='utf-8')
    assert server.paused_run_timeout() == 25


def test_the_timeout_is_ten_minutes_unless_settings_ini_says_otherwise(tmp_path, monkeypatch):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    assert server.paused_run_timeout() == 10


def holding(job, hold):
    handler = MagicMock()
    server.Handler.hold_job(handler, job.id, hold)


def test_pausing_starts_the_clock_and_resuming_stops_it():
    job = a_background_job()
    server.Handler.jobs[job.id] = job

    holding(job, True)
    first = job.held_since
    assert first is not None and job.held_at

    # a second press does not buy more time
    holding(job, True)
    assert job.held_since == first

    holding(job, False)
    assert job.held_since is None and job.held_at == ''


def test_a_paused_background_run_does_not_keep_the_helper_awake():
    # it is waiting for someone, not working; if nobody comes it is abandoned anyway
    job = paused_background_job(1)
    get = MagicMock()

    assert server.keep_awake_once('https://helper.example', get) is False
    get.assert_not_called()
    job.held.clear()
    assert server.keep_awake_once('https://helper.example', get) is True


def test_the_page_is_told_when_a_paused_run_will_be_abandoned(monkeypatch):
    monkeypatch.setattr(server, 'paused_run_timeout', lambda: 10)
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    holding(job, True)
    job.held_at = '2026-09-28T13:00:00'

    assert server.active_jobs()[0]['abandonsAt'] == '2026-09-28T13:10:00'


def test_an_abandoned_run_is_recorded_as_abandoned_not_as_stopped():
    job = a_background_job()

    def left_paused(job, *args):
        job.abandoned = True
        job.cancel.set()

    sent = []
    with patch.object(job, 'emit', side_effect=sent.append), \
         patch.object(server, 'Repository'), patch.object(server, 'FileOps'), \
         patch.object(server.runs, 'RunRecord') as record, \
         patch.object(server, 'begin_record'), \
         patch.object(server, 'runners', return_value={job.action: left_paused}):
        server.run_job(job, 'a-password')

    record.return_value.finish.assert_called_once_with(runs.STATUS_ABANDONED, '')
    finished = [e for e in sent if e['type'] == progress.FINISHED][0]
    assert finished['abandoned'] is True and finished['cancelled'] is True


def test_an_abandoned_run_can_be_resumed():
    record = {'id': 'x', 'action': server.ACTION_QUICK, 'status': runs.STATUS_ABANDONED,
              'options': {}, 'progress': {'step': 'index'}}
    assert server.resume_problem(record, set()) == ''

def ending_with(job, runner):
    sent = []
    with patch.object(job, 'emit', side_effect=sent.append), \
         patch.object(server, 'Repository'), patch.object(server, 'FileOps'), \
         patch.object(server.runs, 'RunRecord') as record, \
         patch.object(server, 'begin_record'), \
         patch.object(server, 'runners', return_value={job.action: runner}):
        server.run_job(job, 'a-password')
    return record.return_value.finish.call_args.args[0], [e for e in sent if e['type'] in ('finished', 'failed')]


def test_a_stop_that_escapes_the_runner_is_a_stop_not_a_failure():
    # a pause gate outside the runner's own loops - during the login, say - raises straight up
    def stopped_at_a_gate(job, *args):
        job.cancel.set()
        raise exceptions.CancelledException()

    status, ends = ending_with(a_background_job(), stopped_at_a_gate)

    assert status == runs.STATUS_STOPPED
    assert ends == [{'type': 'finished', 'cancelled': True, 'abandoned': False}]


def test_an_abandonment_that_escapes_the_runner_is_still_recorded_as_abandoned():
    def abandoned_at_a_gate(job, *args):
        job.abandoned = True
        job.cancel.set()
        raise exceptions.CancelledException()

    status, ends = ending_with(a_background_job(), abandoned_at_a_gate)

    assert status == runs.STATUS_ABANDONED
    assert ends[0]['abandoned'] is True

def test_a_run_lets_go_of_the_dropbox_sign_in_when_it_ends():
    # the page promised it would; the job stays listed a while after for a page reattaching
    job = a_background_job()
    job.library = dropbox_library.DropboxChannel('refresh-me', 'app-key')

    ending_with(job, lambda job, *args: None)

    assert job.library is None
    assert job.done.is_set()


def test_a_background_run_told_to_stop_no_longer_keeps_the_helper_awake():
    # it is only unwinding, and a stop has to leave the host free to sleep
    job = a_background_job()
    server.Handler.jobs[job.id] = job
    job.cancel.set()
    get = MagicMock()

    assert server.keep_awake_once('https://helper.example', get) is False
    get.assert_not_called()


def test_a_stopped_background_run_is_recorded_as_stopped_and_can_be_resumed():
    def stopped(job, *args):
        job.cancel.set()

    status, ends = ending_with(a_background_job(), stopped)

    assert status == runs.STATUS_STOPPED
    assert ends[0]['cancelled'] is True and ends[0]['abandoned'] is False
    assert server.resume_problem({'id': 'x', 'action': server.ACTION_QUICK, 'status': status,
                                  'options': {}, 'progress': {'step': 'index'}}, set()) == ''


def test_a_run_that_ended_an_hour_ago_is_forgotten_and_one_still_going_is_not():
    recent = a_background_job()
    recent.finish()
    ended = a_background_job()
    ended.finish()
    ended.finished_at = recent.finished_at - server.FORGET_FINISHED_SECONDS - 1
    going = a_background_job()
    for job in (ended, going, recent): server.Handler.jobs[job.id] = job

    assert server.forget_finished(now=recent.finished_at + 10) == [ended.id]
    assert set(server.Handler.jobs) == {going.id, recent.id}

# endregion


# region the run's log

def test_everything_a_run_says_goes_into_its_history_file_including_before_it_existed():
    job = a_background_job()

    def says(job, *args):
        print('new download: 1 A.html')

    with patch.object(job, 'emit'), patch.object(server, 'Repository'), \
         patch.object(server, 'FileOps'), patch.object(server.runs, 'RunRecord') as record, \
         patch.object(server, 'begin_record'), \
         patch.object(server, 'runners', return_value={job.action: says}):
        server.run_job(job, 'a-password')

    # the lines before the file existed start its log - the login being tried, for one
    printed = record.call_args.kwargs['printed']
    assert any('logging in' in line for line in printed)
    lines = [c.args[0] for c in record.return_value.line.call_args_list]
    assert 'new download: 1 A.html' in lines


def test_the_history_file_says_which_helper_the_run_was_started_on():
    sent = starting({'background': True, 'dropbox': DROPBOX,
                     'helper': 'https://helper.example.com'})
    job = server.Handler.jobs[sent['body']['jobId']]
    assert job.helper == 'https://helper.example.com'

    fileops = MagicMock()
    fileops.runsfolder = '/tmp'
    record = runs.RunRecord(fileops, 'abcdef123456', 'sync', 'Sync', ['JSON'], {},
                            helper=job.helper)
    assert record.data['helper'] == 'https://helper.example.com'

# endregion
