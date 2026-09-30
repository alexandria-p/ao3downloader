"""The Windows app updating itself: what it will install, what it refuses, and when.

The swap itself runs in PowerShell once the app has closed, so it is tried on Windows by the
`build windows app` workflow - which installs the app, edits its settings.ini, and updates it
from a stand-in release. Everything up to handing over to that script is here.
"""

import hashlib
import io
import json
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock

import pytest

from source_code import server, strings, updater as updates
from source_code.updater import UpdateError, Updater


# region a stand-in GitHub

class Answer:
    def __init__(self, status: int = 200, body: bytes = b'', data: dict | None = None):
        self.status_code = status
        self.body = body
        self.data = data or {}

    def json(self):
        return self.data

    def iter_content(self, size):
        for at in range(0, len(self.body), size):
            yield self.body[at:at + size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def app_zip(extra: dict[str, bytes] | None = None, leave_out: tuple = ()) -> bytes:
    files = {'ao3downloader/ao3downloader.exe': b'new exe',
             'ao3downloader/_internal/python.dll': b'new dll',
             'ao3downloader/README.txt': b'new readme', **(extra or {})}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in files.items():
            if name not in leave_out: archive.writestr(name, data)
    return buffer.getvalue()


def github(tag: str = 'v1.8.3', body: bytes | None = None, digest: str | None = None,
           size: int | None = None, url: str = 'https://github.com/x/y/releases/download/v1.8.3/'
                                                 'ao3downloader-windows.zip'):
    body = app_zip() if body is None else body
    digest = 'sha256:' + hashlib.sha256(body).hexdigest() if digest is None else digest
    asked = []

    def get(address, **kwargs):
        asked.append(address)
        if address.endswith('/releases/latest'):
            return Answer(data={'tag_name': tag, 'assets': [
                {'name': 'something-else.zip', 'browser_download_url': 'https://x/other'},
                {'name': updates.ASSET_NAME, 'browser_download_url': url, 'digest': digest,
                 'size': len(body) if size is None else size}]})
        return Answer(body=body)
    get.asked = asked
    return get


def updater(tmp_path, get, version='1.8.2') -> tuple[Updater, MagicMock, MagicMock]:
    launch, leave = MagicMock(), MagicMock()
    return Updater(str(tmp_path), version, 'x/y', get=get, launch=launch, leave=leave), launch, leave


def installed(tmp_path, get, version='1.8.2'):
    """Run an update through to handing over to the swap script, in this thread."""

    update, launch, leave = updater(tmp_path, get, version)
    assert update.claim()
    release = update.latest()
    (tmp_path / updates.UPDATE_FOLDER).mkdir(exist_ok=True)
    update.install(release)
    return update, launch, leave

# endregion


# region what it looks for

def test_it_asks_for_the_latest_release_of_its_own_repository(tmp_path):
    get = github()
    update, _, _ = updater(tmp_path, get)

    release = update.latest()

    assert get.asked == ['https://api.github.com/repos/x/y/releases/latest']
    assert release.version == '1.8.3'
    assert release.download.endswith('/ao3downloader-windows.zip')
    assert release.digest == hashlib.sha256(app_zip()).hexdigest()


def test_it_does_nothing_when_this_is_the_latest(tmp_path):
    update, launch, _ = updater(tmp_path, github(tag='v1.8.2'))
    assert update.claim()

    with pytest.raises(UpdateError, match='already the latest'):
        update.begin()
    assert not launch.called
    # and stands down, so a run can start
    assert not update.busy()


def test_a_release_without_the_windows_zip_is_not_an_update(tmp_path):
    def get(address, **kwargs):
        return Answer(data={'tag_name': 'v2.0.0', 'assets': []})
    update, _, _ = updater(tmp_path, get)

    with pytest.raises(UpdateError, match='has no ao3downloader-windows.zip'):
        update.latest()


def test_a_download_that_is_not_https_is_refused(tmp_path):
    update, _, _ = updater(tmp_path, github(url='http://example.com/app.zip'))

    with pytest.raises(UpdateError, match='https'):
        update.latest()


def test_github_not_answering_is_said_plainly(tmp_path):
    def get(address, **kwargs):
        return Answer(status=403)
    update, _, _ = updater(tmp_path, get)

    with pytest.raises(UpdateError, match='403'):
        update.latest()


@pytest.mark.parametrize('candidate, current, newer', [
    ('1.8.3', '1.8.2', True), ('1.10.0', '1.9.9', True), ('2.0.0', '1.99.0', True),
    ('1.8.2', '1.8.2', False), ('1.8.1', '1.8.2', False), ('latest', '1.8.2', False),
])
def test_newer_is_number_by_number(candidate, current, newer):
    assert updates.is_newer(candidate, current) is newer

# endregion


# region what it installs, and what it refuses

def test_the_new_version_is_unpacked_and_the_swap_handed_to_powershell(tmp_path):
    update, launch, leave = installed(tmp_path, github())

    new = tmp_path / 'update' / 'new'
    assert (new / 'ao3downloader.exe').read_bytes() == b'new exe'
    assert (new / '_internal' / 'python.dll').read_bytes() == b'new dll'
    command = launch.call_args.args[0]
    assert command[0] == 'powershell.exe'
    assert command[command.index('-AppDir') + 1] == str(tmp_path)
    assert command[command.index('-File') + 1] == str(tmp_path / 'update' / 'apply-update.ps1')
    assert (tmp_path / 'update' / 'apply-update.ps1').read_text(encoding='utf-8-sig') == updates.SWAP_SCRIPT
    assert update.status()['update'] == {'state': 'restarting', 'version': '1.8.3'}


def test_what_the_swap_script_prints_goes_to_a_file_beside_its_log(tmp_path):
    _, launch, _ = installed(tmp_path, github())

    assert launch.call_args.args[1] == tmp_path / 'update' / 'swap-output.txt'


def test_the_swap_script_and_the_app_it_restarts_start_with_pyinstallers_variables_reset(monkeypatch):
    # a frozen app passes its own _PYI_* variables down; the relaunched exe must not take them
    monkeypatch.setenv('_PYI_APPLICATION_HOME_DIR', 'the old app')
    environment = updates.launch_environment()

    assert environment['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
    assert "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'" in updates.SWAP_SCRIPT


def test_a_detached_launch_writes_what_the_command_prints_to_the_file(tmp_path):
    output = tmp_path / 'out.txt'
    updates.launch_detached([sys.executable, '-c', 'print("started")'], output)

    for _ in range(100):
        if output.exists() and 'started' in output.read_text(): break
        time.sleep(0.05)
    assert 'started' in output.read_text()


def test_the_users_own_folders_in_a_zip_are_never_unpacked(tmp_path):
    body = app_zip({'ao3downloader/config/settings.ini': b'[settings]\nExtraWaitTime=0\n',
                    'ao3downloader/logs/log.jsonl': b'{}'})
    installed(tmp_path, github(body=body))

    assert not (tmp_path / 'update' / 'new' / 'config').exists()
    assert not (tmp_path / 'update' / 'new' / 'logs').exists()


@pytest.mark.parametrize('change, reason', [
    ({'digest': 'sha256:' + '0' * 64}, 'checksum'),
    ({'size': 3}, 'bytes'),
    ({'body': app_zip({'ao3downloader/../../evil.txt': b'x'})}, 'where it should not be'),
    ({'body': app_zip({'somewhere-else/evil.txt': b'x'})}, 'where it should not be'),
    # on Windows, a drive letter part would jump out of the app's folder
    ({'body': app_zip({'ao3downloader/C:/Windows/evil.txt': b'x'})}, 'where it should not be'),
    ({'body': app_zip(leave_out=('ao3downloader/ao3downloader.exe',))}, 'no ao3downloader.exe'),
    ({'body': app_zip(leave_out=('ao3downloader/_internal/python.dll',))}, 'no _internal'),
])
def test_a_download_that_is_not_right_is_not_installed(tmp_path, change, reason):
    update, launch, leave = installed(tmp_path, github(**change))

    state = update.status()['update']
    assert state['state'] == 'failed'
    assert reason in state['error']
    assert not launch.called and not leave.called
    assert not (tmp_path / 'update' / 'new' / 'ao3downloader.exe').exists()
    # a failed update is over: a run may start again
    assert not update.busy()


def test_an_unreadable_answer_from_github_stands_the_updater_down(tmp_path):
    # left 'checking', it would refuse every run until the app restarted
    def get(address, **kwargs):
        answer = Answer()
        answer.json = MagicMock(side_effect=ValueError('not json'))
        return answer
    update, _, _ = updater(tmp_path, get)
    assert update.claim()

    with pytest.raises(UpdateError, match='not json'):
        update.begin()
    assert not update.busy()


def test_an_app_folder_it_cannot_write_to_is_said_before_anything_downloads(tmp_path):
    (tmp_path / 'update').write_text('in the way', encoding='utf-8')
    get = github(tag='v2.0.0')
    update, launch, _ = updater(tmp_path, get)
    assert update.claim()

    with pytest.raises(UpdateError, match='cannot write to its own folder'):
        update.begin()
    assert len(get.asked) == 1

# endregion


# region the swap script's own report

@pytest.mark.parametrize('log, failure', [
    ('', ''),
    ('2026-01-01 swapped ao3downloader.exe, _internal\n', ''),
    ('2026-01-01 update failed: the file is in use\n', 'the file is in use'),
    ('2026-01-01 update failed: in use\n2026-02-01 swapped _internal\n', ''),
    ('2026-01-01 swapped _internal\n2026-02-01 update failed: disk full\n', 'disk full'),
])
def test_the_restarted_app_knows_whether_the_last_update_went_through(tmp_path, log, failure):
    if log:
        (tmp_path / 'update').mkdir()
        (tmp_path / 'update' / 'update.log').write_text(log, encoding='utf-8')

    update, _, _ = updater(tmp_path, github())

    assert update.last_result() == failure
    assert (update.status()['update']['state'] == 'failed') is bool(failure)


def test_the_script_never_touches_the_users_folders_and_always_starts_the_app_again():
    script = updates.SWAP_SCRIPT
    assert "$kept = @('config', 'logs', 'update')" in script
    assert "Where-Object { $kept -notcontains $_ }" in script
    # the old files go back if any move fails, and the app starts again either way
    assert 'putting the old ones back' in script
    assert 'finally {' in script and "Start-Process -FilePath (Join-Path $AppDir 'ao3downloader.exe')" in script

# endregion


# region the helper's side

@pytest.fixture
def live():
    httpd = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f'http://{server.HOST}:{httpd.server_address[1]}'
    finally:
        httpd.shutdown()
        httpd.server_close()


def call(url: str, method: str = 'GET', body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(url, method=method, data=json.dumps(body or {}).encode(),
                                     headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_a_helper_that_is_not_the_windows_app_cannot_update(live):
    assert call(f'{live}/api/update', 'POST')[0] == 404
    assert 'app' not in call(f'{live}/api/config')[1]


def test_the_windows_app_says_its_version_and_that_it_can_update(live, tmp_path):
    server.Handler.updater = updater(tmp_path, github())[0]

    assert call(f'{live}/api/config')[1]['app'] == {
        'version': '1.8.2', 'updatable': True, 'update': {'state': 'idle'}}


def test_an_update_is_refused_while_a_run_is_going(live, tmp_path):
    server.Handler.updater = updater(tmp_path, github())[0]
    job = MagicMock(id='running')
    job.done.is_set.return_value = False
    server.Handler.jobs['running'] = job

    status, body = call(f'{live}/api/update', 'POST')

    assert status == 409
    assert body['error'] == strings.ERROR_UPDATE_DURING_RUN
    assert server.Handler.updater.status()['update']['state'] == 'idle'


def test_an_update_starts_and_says_which_version(live, tmp_path):
    update, _, _ = updater(tmp_path, github())
    update.install = MagicMock()
    server.Handler.updater = update

    status, body = call(f'{live}/api/update', 'POST')

    assert (status, body) == (202, {'version': '1.8.3'})
    assert update.status()['update'] == {'state': 'downloading', 'version': '1.8.3'}


def test_a_run_cannot_start_while_the_app_is_updating(live, tmp_path):
    update, _, _ = updater(tmp_path, github())
    assert update.claim()
    server.Handler.updater = update

    status, body = call(f'{live}/api/jobs', 'POST', {'action': server.ACTION_BOOKMARKS,
                                                     'username': 'someone', 'password': 'x'})

    assert status == 409
    assert body['error'] == strings.ERROR_RUN_DURING_UPDATE
    assert not server.Handler.jobs


def test_nothing_newer_is_said_to_the_page(live, tmp_path):
    server.Handler.updater = updater(tmp_path, github(tag='v1.8.2'))[0]

    status, body = call(f'{live}/api/update', 'POST')

    assert status == 409
    assert 'already the latest' in body['error']

# endregion
