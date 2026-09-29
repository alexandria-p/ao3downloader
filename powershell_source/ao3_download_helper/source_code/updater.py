"""Updating the Windows app from inside itself: the page's **Update now**.

Only the Windows app can do this (`desktop.py` sets `Handler.updater`) - it is the one copy
that is a folder of files on someone's computer, installed from a GitHub release. A helper run
any other way answers the update endpoints 404, and its page never shows the button.

What happens, in order:

1. `latest` asks GitHub for the repository's latest release and finds its
   `ao3downloader-windows.zip`. It has to be newer than this app, or nothing happens.
2. `install` downloads it into `update/` beside the exe and checks it: against the SHA-256
   GitHub publishes for the file, and entry by entry - every file has to land inside the
   app's own folder, and the zip has to hold the exe and its `_internal/`. Anything wrong and
   nothing is touched.
3. It unpacks it into `update/new/`, writes `update/apply-update.ps1`, starts that - hidden,
   detached - and closes the app.
4. The script waits for the app to be gone (a running exe cannot be replaced on Windows),
   moves each top-level item of the old app into `update/previous/` and the new one in its
   place, and starts the app again. If a move fails it puts every old item back first, so the
   app that starts is always a whole one - the new version, or the old one it was. It writes
   what it did to `update/update.log`, which the restarted app reads (`last_result`) so the
   page can say an update failed.

`config/` and `logs/` are never moved: they are not in the zip, and the script skips them by
name as well. So an update never touches the user's settings.ini - the restarted app adds any
new setting to it, and comments out any the new version dropped (`desktop.settings_up_to_date`).
"""

import hashlib
import os
import re
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import requests

ASSET_NAME = 'ao3downloader-windows.zip'
# the folder the zip unpacks into: every entry has to be inside it
ZIP_ROOT = 'ao3downloader'
EXE_NAME = 'ao3downloader.exe'
UPDATE_FOLDER = 'update'
# never moved or replaced: the user's, not the app's
KEPT = ('config', 'logs', UPDATE_FOLDER)
GITHUB_API = 'https://api.github.com'
# a stand-in for GitHub's api, so an update can be tried end to end without a real release -
# the Windows build does exactly that. only ever set by whoever starts the app
ENV_UPDATE_SOURCE = 'AO3DOWNLOADER_UPDATE_SOURCE'
SCRIPT_NAME = 'apply-update.ps1'
LOG_NAME = 'update.log'
# what the swap script itself printed, errors included
OUTPUT_NAME = 'swap-output.txt'
PYINSTALLER_RESET = 'PYINSTALLER_RESET_ENVIRONMENT'
DOWNLOAD_NAME = 'download.zip'
TIMEOUT_SECONDS = 60
# the response to the page has to get out before the app closes
EXIT_DELAY_SECONDS = 1.5

# while any of these, a run may not start - the app is about to close
BUSY = ('checking', 'downloading', 'restarting')

VERSION = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)$')


class UpdateError(Exception):
    """An update that cannot go ahead, and why - said to the page as it is."""


@dataclass
class Release:
    version: str
    download: str
    # sha256 of the zip, as GitHub publishes it for each file of a release; '' if it did not
    digest: str
    size: int


def version_parts(text: str) -> tuple[int, int, int] | None:
    match = VERSION.match(str(text or '').strip())
    return tuple(int(x) for x in match.groups()) if match else None


def is_newer(candidate: str, current: str) -> bool:
    a, b = version_parts(candidate), version_parts(current)
    return bool(a and b and a > b)


def check_zip(archive: zipfile.ZipFile) -> None:
    """Refuse a zip that is not this app, or that would write anywhere but the app's folder."""

    names = archive.namelist()
    for name in names:
        path = PurePosixPath(name.replace('\\', '/'))
        # a ':' anywhere is refused too: on Windows a part like 'C:' jumps to another drive
        if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != ZIP_ROOT \
                or any(':' in part for part in path.parts):
            raise UpdateError(f'the download has a file where it should not be ({name}) - '
                              'not installing it')
    if f'{ZIP_ROOT}/{EXE_NAME}' not in names:
        raise UpdateError(f'the download has no {EXE_NAME} - not installing it')
    if not any(name.startswith(f'{ZIP_ROOT}/_internal/') for name in names):
        raise UpdateError('the download has no _internal folder - not installing it')


def unpack(archive: zipfile.ZipFile, destination: Path) -> None:
    """Everything under the zip's top folder into `destination`, except anything under a
    folder that is the user's - a zip that carried one would otherwise replace it."""

    for info in archive.infolist():
        parts = PurePosixPath(info.filename.replace('\\', '/')).parts[1:]
        if not parts or parts[0] in KEPT: continue
        target = destination.joinpath(*parts)
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, open(target, 'wb') as out:
            while chunk := source.read(1024 * 1024):
                out.write(chunk)


def launch_environment() -> dict:
    """What the swap script, and the app it starts again, run with.

    A frozen app hands its children PyInstaller's own variables (`_PYI_*`), and PyInstaller
    says to reset them when starting another frozen program - the relaunched exe would
    otherwise take them as its own. The script sets the flag again before it starts the app."""

    environment = dict(os.environ)
    environment[PYINSTALLER_RESET] = '1'
    return environment


def launch_detached(command: list[str], output: Path | None = None) -> None:
    """Start the swap script so it outlives this process, with no window of its own.

    What it prints goes to `output`: a script that will not even start - refused by policy,
    or failing to parse - never reaches its own log, and would otherwise leave no trace."""

    flags = 0
    if sys.platform == 'win32':
        # a hidden console of its own rather than none: Windows PowerShell started with no
        # console at all (DETACHED_PROCESS) was seen to end before running a single line
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    sink = open(output, 'ab') if output else subprocess.DEVNULL
    try:
        subprocess.Popen(command, creationflags=flags, close_fds=True, env=launch_environment(),
                         stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT)
    finally:
        if output: sink.close()


class Updater:
    """Everything the update endpoints need, for one running app."""

    def __init__(self, app_dir: str, version: str, repository: str,
                 get: Callable = requests.get,
                 launch: Callable[..., None] = launch_detached,
                 leave: Callable[[], None] = lambda: os._exit(0)):
        self.app_dir = Path(app_dir)
        self.version = version
        self.repository = repository
        self.get = get
        self.launch = launch
        self.leave = leave
        self.lock = threading.Lock()
        self.source = (os.environ.get(ENV_UPDATE_SOURCE) or GITHUB_API).rstrip('/')
        # what the page is told: idle, downloading, restarting, or failed with why
        self.state: dict = {'state': 'idle'}
        failure = self.last_result()
        if failure: self.state = {'state': 'failed', 'error': failure}

    @property
    def update_dir(self) -> Path:
        return self.app_dir / UPDATE_FOLDER

    def busy(self) -> bool:
        """Whether an update is under way - asked before a run may start."""

        with self.lock:
            return self.state.get('state') in BUSY

    def claim(self) -> bool:
        """Mark an update as under way, unless one already is. The helper calls this under the
        same lock it starts runs under, so a run and an update can never both begin."""

        with self.lock:
            if self.state.get('state') in BUSY: return False
            self.state = {'state': 'checking'}
            return True

    def status(self) -> dict:
        with self.lock:
            return {'version': self.version, 'updatable': True, 'update': dict(self.state)}

    def last_result(self) -> str:
        """Why the last update failed, if the swap script said it did - read as the app
        starts again, so the page can say so rather than wait for a version that never came."""

        log = self.update_dir / LOG_NAME
        try:
            lines = [x for x in log.read_text(encoding='utf-8', errors='replace').splitlines() if x.strip()]
        except OSError:
            return ''
        # the log keeps every update's lines; only the latest outcome counts
        outcome = next((x for x in reversed(lines) if 'update failed' in x or 'swapped' in x), '')
        if 'update failed' not in outcome: return ''
        return outcome.split('update failed', 1)[1].strip(' :-') or 'the update did not complete'

    def latest(self) -> Release:
        url = f'{self.source}/repos/{self.repository}/releases/latest'
        try:
            response = self.get(url, headers={'Accept': 'application/vnd.github+json'},
                                timeout=TIMEOUT_SECONDS)
        except requests.RequestException as e:
            raise UpdateError(f'could not reach GitHub to find the latest version ({e})') from e
        if response.status_code != 200:
            raise UpdateError(f'GitHub did not say what the latest version is ({response.status_code})')
        release = response.json()
        version = str(release.get('tag_name') or '').removeprefix('v')
        if not version_parts(version):
            raise UpdateError(f"the latest release is not a version this app understands ({version or 'none'})")
        asset = next((a for a in release.get('assets') or [] if a.get('name') == ASSET_NAME), None)
        if not asset or not asset.get('browser_download_url'):
            raise UpdateError(f'the latest release, {version}, has no {ASSET_NAME}')
        download = str(asset['browser_download_url'])
        # the real thing is only ever https; a stand-in source is on this computer
        if not download.startswith('https://') and self.source == GITHUB_API:
            raise UpdateError('the download is not over https - not fetching it')
        digest = str(asset.get('digest') or '')
        return Release(version=version, download=download,
                       digest=digest.removeprefix('sha256:') if digest.startswith('sha256:') else '',
                       size=int(asset.get('size') or 0))

    def begin(self) -> Release:
        """Check there is a newer version and start installing it in the background, once
        `claim`ed. Returns the release; raises UpdateError - and stands down - when there is
        nothing to do or it cannot."""

        try:
            return self.start_install()
        except Exception as e:
            # whatever went wrong - an answer from GitHub that is not what it should be, say -
            # the updater stands down, or it would refuse every run until the app restarted
            with self.lock:
                self.state = {'state': 'idle'}
            if isinstance(e, UpdateError): raise
            raise UpdateError(f'could not start the update ({e})') from e

    def start_install(self) -> Release:
        release = self.latest()
        if not is_newer(release.version, self.version):
            raise UpdateError(f'this is already the latest version ({self.version})')
        try:
            self.update_dir.mkdir(exist_ok=True)
            probe = self.update_dir / '.writable'
            probe.write_text('', encoding='utf-8')
            probe.unlink()
        except OSError as e:
            raise UpdateError(f'the app cannot write to its own folder ({self.app_dir}) - if it '
                              'is somewhere Windows protects, like Program Files, move it to '
                              'your own folders and start it from there') from e
        with self.lock:
            self.state = {'state': 'downloading', 'version': release.version}
        threading.Thread(target=self.install, args=(release,), daemon=True).start()
        return release

    def install(self, release: Release) -> None:
        try:
            archive_path = self.download(release)
            new = self.update_dir / 'new'
            if new.exists(): remove_tree(new)
            with zipfile.ZipFile(archive_path) as archive:
                check_zip(archive)
                unpack(archive, new)
            script = self.update_dir / SCRIPT_NAME
            script.write_text(SWAP_SCRIPT, encoding='utf-8-sig')
            with self.lock:
                self.state = {'state': 'restarting', 'version': release.version}
            print(f'updating to {release.version}: the app will close and start again in a moment')
            self.launch(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                         '-WindowStyle', 'Hidden', '-File', str(script),
                         '-AppDir', str(self.app_dir), '-ProcessId', str(os.getpid())],
                        self.update_dir / OUTPUT_NAME)
            threading.Timer(EXIT_DELAY_SECONDS, self.leave).start()
        except Exception as e:
            message = str(e) if isinstance(e, UpdateError) else f'the update failed ({e})'
            print(f'update: {message}')
            with self.lock:
                self.state = {'state': 'failed', 'version': release.version, 'error': message}

    def download(self, release: Release) -> Path:
        target = self.update_dir / DOWNLOAD_NAME
        digest = hashlib.sha256()
        size = 0
        try:
            with self.get(release.download, stream=True, timeout=TIMEOUT_SECONDS) as response:
                if response.status_code != 200:
                    raise UpdateError(f'the download failed ({response.status_code})')
                with open(target, 'wb') as out:
                    for chunk in response.iter_content(1024 * 1024):
                        if not chunk: continue
                        out.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
        except requests.RequestException as e:
            raise UpdateError(f'the download failed ({e})') from e
        if release.size and size != release.size:
            raise UpdateError(f'the download came out {size} bytes, not {release.size} - not installing it')
        if release.digest and digest.hexdigest().lower() != release.digest.lower():
            raise UpdateError('the download does not match the checksum GitHub published for it '
                              '- not installing it')
        return target


def remove_tree(path: Path) -> None:
    for child in sorted(path.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        child.rmdir() if child.is_dir() and not child.is_symlink() else child.unlink()
    path.rmdir()


# Written into update/ and run by powershell once the app has closed. Windows PowerShell 5.1
# is on every Windows 10 and 11, so it is the one thing this can rely on being there. It never
# touches config/, logs/ or update/, and puts every old item back if any move fails, so the app
# it starts again is always a whole one.
SWAP_SCRIPT = r'''param(
    [Parameter(Mandatory = $true)] [string] $AppDir,
    [Parameter(Mandatory = $true)] [int] $ProcessId
)

$ErrorActionPreference = 'Stop'
$update = Join-Path $AppDir 'update'
$new = Join-Path $update 'new'
$previous = Join-Path $update 'previous'
$log = Join-Path $update 'update.log'
$kept = @('config', 'logs', 'update')

function Say([string] $message) {
    Add-Content -LiteralPath $log -Value ((Get-Date).ToString('u') + ' ' + $message)
}

# a file can stay locked for a moment after its process has gone - an antivirus scan, say -
# so a move is tried again for a while. whatever a failed attempt left at the destination is
# cleared first: where a rename is refused, a move can fall back to copying, and a half-made
# copy would otherwise make every later attempt fail on it
function Move-Carefully([string] $from, [string] $to) {
    for ($attempt = 1; $attempt -le 40; $attempt++) {
        try {
            if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Recurse -Force }
            Move-Item -LiteralPath $from -Destination $to
            return
        }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (Test-Path -LiteralPath $to) { Remove-Item -LiteralPath $to -Recurse -Force }
    Move-Item -LiteralPath $from -Destination $to
}

try {
    Say "waiting for the app (process $ProcessId) to close"
    try { Wait-Process -Id $ProcessId -Timeout 60 -ErrorAction Stop } catch { }

    if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
    New-Item -ItemType Directory -Path $previous | Out-Null

    $names = @(Get-ChildItem -LiteralPath $new -Force | ForEach-Object { $_.Name } |
        Where-Object { $kept -notcontains $_ })
    $moved = @()
    $placed = @()
    try {
        foreach ($name in $names) {
            $target = Join-Path $AppDir $name
            if (Test-Path -LiteralPath $target) {
                Move-Carefully $target (Join-Path $previous $name)
                $moved += $name
            }
            Move-Carefully (Join-Path $new $name) $target
            $placed += $name
        }
    }
    catch {
        Say "could not swap the files ($_) - putting the old ones back"
        foreach ($name in $placed) {
            Remove-Item -LiteralPath (Join-Path $AppDir $name) -Recurse -Force -ErrorAction SilentlyContinue
        }
        foreach ($name in $moved) {
            Move-Item -LiteralPath (Join-Path $previous $name) -Destination (Join-Path $AppDir $name) -ErrorAction SilentlyContinue
        }
        throw
    }

    Say "swapped $($names -join ', ')"
    Remove-Item -LiteralPath $previous -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $new -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $update 'download.zip') -Force -ErrorAction SilentlyContinue
}
catch {
    Say "update failed: $_"
}
finally {
    # started again whether the swap worked or not - the new version, or the whole old one.
    # the page is still open in the browser and reloads itself, so no second tab
    $env:AO3DOWNLOADER_NO_BROWSER = '1'
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Start-Process -FilePath (Join-Path $AppDir 'ao3downloader.exe') -WorkingDirectory $AppDir
    Say 'started the app again'
}
'''
