"""The Mac app updating itself: which zip it takes, what it keeps as it unpacks, and the bash
script that swaps the files and opens the app again in Terminal.

The swap script is run for real here, under bash, against a stand-in app folder - with `open`
replaced by a script that notes what it was asked to open, since there is no Terminal to open.
"""

import hashlib
import io
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from source_code import desktop, updater as updates
from source_code.updater import UpdateError, Updater

needs_bash = pytest.mark.skipif(sys.platform == 'win32', reason='runs the bash swap script')


# region a Mac zip

def mac_zip(links: dict[str, str] | None = None, leave_out: tuple = ()) -> bytes:
    files = {'ao3downloader/ao3downloader': (b'new program', 0o755),
             f'ao3downloader/{updates.MAC_LAUNCHER}': (b'#!/bin/bash\n', 0o755),
             'ao3downloader/_internal/lib/Python': (b'new python', 0o644),
             'ao3downloader/README.txt': (b'new readme', 0o644)}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, (data, mode) in files.items():
            if name in leave_out: continue
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, data)
        for name, target in (links or {}).items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o755) << 16
            archive.writestr(info, target)
    return buffer.getvalue()


class Answer:
    def __init__(self, body: bytes = b'', data: dict | None = None):
        self.status_code = 200
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


def github(asset: str, body: bytes):
    def get(address, **kwargs):
        if address.endswith('/releases/latest'):
            return Answer(data={'tag_name': 'v1.8.3', 'assets': [
                {'name': 'ao3downloader-windows.zip', 'browser_download_url': 'https://x/windows'},
                {'name': asset, 'browser_download_url': f'https://x/{asset}',
                 'digest': 'sha256:' + hashlib.sha256(body).hexdigest(), 'size': len(body)}]})
        get.fetched = address
        return Answer(body=body)
    return get


def mac_updater(tmp_path, chip='arm64', body=None):
    kind = updates.kind_for('darwin', chip)
    launch, leave = MagicMock(), MagicMock()
    get = github(kind.asset, mac_zip() if body is None else body)
    update = Updater(str(tmp_path), '1.8.2', 'x/y', get=get, launch=launch, leave=leave, kind=kind)
    return update, get, launch

# endregion


# region which zip, and what is in it

def test_each_mac_takes_the_zip_for_its_own_chip_and_windows_keeps_its_own():
    assert updates.kind_for('darwin', 'arm64').asset == 'ao3downloader-macos-apple-silicon.zip'
    assert updates.kind_for('darwin', 'x86_64').asset == 'ao3downloader-macos-intel.zip'
    assert updates.kind_for('win32').asset == 'ao3downloader-windows.zip'
    # a system with no published app has nothing to update from
    assert updates.kind_for('linux') is None


def test_a_mac_downloads_its_own_zip_from_the_release(tmp_path):
    update, get, _ = mac_updater(tmp_path, 'x86_64')
    release = update.latest()

    assert release.download == 'https://x/ao3downloader-macos-intel.zip'


def test_a_mac_zip_must_hold_the_program_not_an_exe():
    archive = zipfile.ZipFile(io.BytesIO(mac_zip()))
    updates.check_zip(archive, updates.MAC_PROGRAM)

    missing = zipfile.ZipFile(io.BytesIO(mac_zip(leave_out=('ao3downloader/ao3downloader',))))
    with pytest.raises(UpdateError, match='has no ao3downloader'):
        updates.check_zip(missing, updates.MAC_PROGRAM)


def test_a_link_inside_the_app_is_allowed():
    archive = zipfile.ZipFile(io.BytesIO(mac_zip(links={
        'ao3downloader/_internal/Python': 'lib/Python',
        'ao3downloader/_internal/lib/Here': '../README-link'})))

    updates.check_zip(archive, updates.MAC_PROGRAM)


@pytest.mark.parametrize('target', ['/etc/passwd', '../../outside', 'lib/../../../outside', '../../config'])
def test_a_link_pointing_out_of_the_app_is_refused(target):
    archive = zipfile.ZipFile(io.BytesIO(mac_zip(links={'ao3downloader/_internal/Python': target})))

    with pytest.raises(UpdateError, match='link pointing out of the app'):
        updates.check_zip(archive, updates.MAC_PROGRAM)

# endregion


# region unpacking

@pytest.mark.skipif(os.name == 'nt', reason='permissions and symlinks')
def test_unpacking_keeps_the_program_executable_and_links_as_links(tmp_path):
    archive = zipfile.ZipFile(io.BytesIO(mac_zip(links={'ao3downloader/_internal/Python': 'lib/Python'})))
    updates.unpack(archive, tmp_path / 'new')

    new = tmp_path / 'new'
    assert os.access(new / 'ao3downloader', os.X_OK)
    assert os.access(new / updates.MAC_LAUNCHER, os.X_OK)
    assert not os.access(new / 'README.txt', os.X_OK)
    assert (new / '_internal' / 'Python').is_symlink()
    assert os.readlink(new / '_internal' / 'Python') == 'lib/Python'
    assert (new / '_internal' / 'Python').read_bytes() == b'new python'


def test_a_mac_update_hands_over_to_bash_with_the_mac_script(tmp_path):
    update, _, launch = mac_updater(tmp_path)
    assert update.claim()
    (tmp_path / updates.UPDATE_FOLDER).mkdir()
    update.install(update.latest())

    command = launch.call_args.args[0]
    script = tmp_path / 'update' / 'apply-update.sh'
    assert command == ['/bin/bash', str(script), str(tmp_path), str(os.getpid())]
    assert script.read_bytes() == updates.MAC_SWAP_SCRIPT.encode('utf-8')
    assert b'\r' not in script.read_bytes()
    assert (tmp_path / 'update' / 'new' / 'ao3downloader').read_bytes() == b'new program'
    assert update.status()['update'] == {'state': 'restarting', 'version': '1.8.3'}

# endregion


# region the swap script, run for real

def stand_in_app(tmp_path: Path) -> Path:
    app = tmp_path / 'ao3downloader'
    (app / '_internal').mkdir(parents=True)
    (app / 'ao3downloader').write_bytes(b'old program')
    (app / '_internal' / 'old-only.txt').write_text('old', encoding='utf-8')
    (app / 'config').mkdir()
    (app / 'config' / 'settings.ini').write_text('[settings]\nExtraWaitTime=42\n', encoding='utf-8')
    new = app / 'update' / 'new'
    (new / '_internal').mkdir(parents=True)
    (new / 'ao3downloader').write_bytes(b'new program')
    (new / '_internal' / 'new-only.txt').write_text('new', encoding='utf-8')
    (new / updates.MAC_LAUNCHER).write_text('#!/bin/bash\n', encoding='utf-8')
    (app / 'update' / 'apply-update.sh').write_text(updates.MAC_SWAP_SCRIPT, encoding='utf-8')
    return app


def swap(tmp_path: Path, app: Path, fail_moving: str = '') -> tuple[str, str]:
    """Run the script with `open` noting what it opened, and `mv` refusing one name."""

    shims = tmp_path / 'shims'
    shims.mkdir()
    opened = tmp_path / 'opened.txt'
    (shims / 'open').write_text(f'#!/bin/bash\necho "$@" >> "{opened}"\n', encoding='utf-8')
    real_mv = subprocess.run(['bash', '-c', 'command -v mv'], capture_output=True, text=True).stdout.strip()
    (shims / 'mv').write_text(
        '#!/bin/bash\n'
        f'if [ -n "{fail_moving}" ] && [ "$(basename "$2")" = "{fail_moving}" ] && [[ "$1" == */new/* ]]; then exit 1; fi\n'
        f'exec {real_mv} "$@"\n', encoding='utf-8')
    for shim in shims.iterdir(): shim.chmod(0o755)
    environment = {**os.environ, 'PATH': f'{shims}{os.pathsep}{os.environ["PATH"]}'}
    # a process that has already gone, as the app has by the time the script runs
    gone = subprocess.Popen(['true'])
    gone.wait()
    subprocess.run(['bash', str(app / 'update' / 'apply-update.sh'), str(app), str(gone.pid)],
                   env=environment, check=True, timeout=60)
    log = (app / 'update' / 'update.log').read_text(encoding='utf-8')
    return log, opened.read_text(encoding='utf-8') if opened.exists() else ''


@needs_bash
def test_the_mac_swap_replaces_the_app_and_opens_it_again_in_terminal(tmp_path):
    app = stand_in_app(tmp_path)
    log, opened = swap(tmp_path, app)

    assert 'swapped' in log and 'started the app again' in log
    assert (app / 'ao3downloader').read_bytes() == b'new program'
    assert (app / '_internal' / 'new-only.txt').exists()
    assert not (app / '_internal' / 'old-only.txt').exists()
    # the user's settings are never moved
    assert 'ExtraWaitTime=42' in (app / 'config' / 'settings.ini').read_text(encoding='utf-8')
    for gone in ('new', 'previous'):
        assert not (app / 'update' / gone).exists()
    assert opened.strip() == f'-a Terminal {app / updates.MAC_LAUNCHER}'
    # so the restarted app does not open a second tab
    assert (app / 'update' / updates.RESTARTED_MARKER).exists()
    assert updates.Updater(str(app), '1.8.3', 'x/y').last_result() == ''


@needs_bash
def test_a_mac_swap_that_cannot_move_a_file_puts_the_old_app_back_and_says_so(tmp_path):
    app = stand_in_app(tmp_path)
    log, opened = swap(tmp_path, app, fail_moving='ao3downloader')

    assert 'putting the old ones back' in log
    assert (app / 'ao3downloader').read_bytes() == b'old program'
    assert (app / '_internal' / 'old-only.txt').exists()
    assert not (app / '_internal' / 'new-only.txt').exists()
    # the old version is started again, and knows the update failed
    assert 'Terminal' in opened
    assert 'could not move the new ao3downloader in' in \
        updates.Updater(str(app), '1.8.2', 'x/y').last_result()

# endregion


# region the app it starts again

def test_the_app_the_swap_starts_opens_no_second_tab_and_only_the_once(tmp_path):
    marker = tmp_path / 'update' / updates.RESTARTED_MARKER
    marker.parent.mkdir()
    marker.write_text('', encoding='utf-8')

    assert desktop.restarted_by_update(str(tmp_path)) is True
    assert not marker.exists()
    assert desktop.restarted_by_update(str(tmp_path)) is False


def test_the_packaged_mac_app_can_update_itself(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop.sys, 'platform', 'darwin')
    monkeypatch.setattr(desktop.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(updates.sys, 'platform', 'darwin')
    monkeypatch.setattr(desktop, 'build_info', lambda web: ('1.8.2', 'x/y'))
    import platform
    monkeypatch.setattr(platform, 'machine', lambda: 'arm64')

    update = desktop.make_updater(str(tmp_path), 'web')

    assert update is not None
    assert update.kind.asset == 'ao3downloader-macos-apple-silicon.zip'
    assert update.status()['updatable'] is True

# endregion
