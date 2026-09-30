"""Build the app for Windows or macOS: a zip holding the `ao3downloader` program and everything
it needs.

Unzipped and started, the program does what `Start-Application.ps1` does in a generated build -
see `source_code/desktop.py` - with Python and every dependency packed beside it, so the person
using it needs no PowerShell, uv or Python.

A folder in a zip rather than one self-contained program, on purpose: a one-file program
unpacks itself into a temporary folder on every start, which is slow and is the thing antivirus
programs most often object to, and the app needs a folder beside it for its settings and logs
anyway.

PyInstaller builds for the system it runs on, so each zip is built on its own system - the
`build windows app` and `build mac app` workflows do it on a Windows and a macOS runner. Run on
Linux, this builds the same app for Linux, which is how it is tested.

    uv sync --group package
    uv run --no-sync python package_app.py [--skip-web] [--settings app-settings.ini]

`--settings` is the settings.ini to ship - the workflows write one from the deployment's
variables with `deploy_config.py local-settings`, pointed at the app's own helper. Without it
the app ships the template's.

The zip lands in `dist/` at the repository root.
"""

import argparse
import os
import platform as machines
import shutil
import stat
import sys
import zipfile
from pathlib import Path

import build_artifacts
from build_artifacts import PACKAGE_NAME, PYTHON_HOME

APP_NAME = 'ao3downloader'
ENTRY = Path(PACKAGE_NAME) / 'desktop.py'
# where PyInstaller puts things, under the repository root. dist/ is where the zip goes
DIST = 'dist'
STAGING = Path(DIST) / 'staging'
WORK = Path(DIST) / 'pyinstaller'
# the settings the app starts from, packed inside it: config/settings.ini is created from
# them on the first start and completed from them on every start after. never in the zip's
# config/ - there is no config/ in the zip at all, so unzipping an update can never replace
# the one the user has edited
DEFAULTS_FOLDER = 'defaults'

# on a Mac, what someone double-clicks. A program downloaded from the internet is quarantined,
# and so is every file unzipped from it; macOS asks once about this script (see MAC_README),
# and the script then lifts the quarantine off the rest of the folder, so the program and its
# libraries are not each refused in turn
MAC_LAUNCHER = 'Start ao3downloader.command'
MAC_LAUNCHER_SCRIPT = """#!/bin/bash
# double-click to start ao3downloader. it opens in Terminal - leave that window open while you
# use the app, and close it to stop.
cd "$(dirname "$0")" || exit 1
# a downloaded zip marks everything in it as quarantined; this app is opened on purpose
xattr -dr com.apple.quarantine . 2>/dev/null
exec ./ao3downloader
"""

WINDOWS_README = """ao3downloader
=============

Starting it
-----------
Double-click ao3downloader.exe. A window opens and your browser opens the app. If it
does not, open any web browser to http://localhost:4200 - the window says so too. Leave the
window open while you use the app; close it to stop. Everything the app does is shown in it.

The first time, Windows may say "Windows protected your PC", because the app is not signed.
Click "More info", then "Run anyway".

Where things are
----------------
config\\settings.ini   the app's settings - pacing, file names and the rest. Created the
                      first time the app starts; edit it while the app is closed.
logs\\                 the helper's own log.

Your fics are saved in whichever folder you open in the app, on this computer or in Dropbox.

Updating
--------
When a newer version is out, the app says so at the top of the page. Click "Update now": it
downloads the new version, closes, swaps itself for it and starts again - a few seconds.

Or download the new zip yourself and unzip it over this folder. Nothing in the zip is in the
config folder, so your settings.ini is never replaced either way. Each time the app starts it
adds any setting a new version introduced, and comments out - marked DEPRECATED - any setting
it no longer uses. Nothing you set is ever changed or deleted.

If it will not start
--------------------
The window says why and stays open. The usual reason is that the app is already running in
another window: close every ao3downloader window and start it again.
"""

# which Mac a build is for - PyInstaller builds for the chip it runs on, so each is built on its
# own runner. the Intel one would also run on Apple silicon through Rosetta, but more slowly,
# and Apple is winding Rosetta down, so each Mac gets its own
MAC_CHIPS = {'arm64': 'apple-silicon', 'x86_64': 'intel'}
MAC_FOR = {
    'apple-silicon': ('This is for Macs with Apple silicon (M1 or later). For an Intel Mac, download\n'
                      f'{APP_NAME}-macos-intel.zip instead.'),
    'intel': ('This is for Intel Macs. For a Mac with Apple silicon (M1 or later), download\n'
              f'{APP_NAME}-macos-apple-silicon.zip instead - this one would run there too, through\n'
              'Rosetta, but more slowly.'),
}

MAC_README = f"""ao3downloader
=============

{{which}}

Starting it
-----------
Move this folder somewhere to keep it - your Applications or Documents folder - then
double-click "{MAC_LAUNCHER}". A Terminal window opens and Google Chrome opens the app. If
it does not, open Chrome to http://localhost:4200 - the window says so too. Leave the window
open while you use the app; close it to stop. Everything the app does is shown in it.

Use Chrome, or Edge, Brave, Opera or Arc. Safari and Firefox cannot open a folder on your Mac
for a web page, so they cannot save your fics.

The first time, macOS says it cannot check the app for malicious software, because the app is
not signed by Apple. Click "Done" (not "Move to Trash"), then open System Settings, go to
Privacy & Security, scroll down, and click "Open Anyway" next to "{MAC_LAUNCHER}". Confirm,
and it starts. You only do this once: the first start clears the warning for the whole folder.

Where things are
----------------
config/settings.ini   the app's settings - pacing, file names and the rest. Created the
                      first time the app starts; edit it while the app is closed.
logs/                 the helper's own log.

Your fics are saved in whichever folder you open in the app, on this Mac or in Dropbox.

Updating
--------
When a newer version is out, the app says so at the top of the page. Click "Update now": it
downloads the new version, closes, swaps itself for it and opens again in a new Terminal
window - a few seconds. The old window can then be closed.

Or download the new zip yourself and copy everything in it over this folder. Nothing in the
zip is in the config folder, so your settings.ini is never replaced either way. Each time the app starts it adds any setting a new version
introduced, and comments out - marked DEPRECATED - any setting it no longer uses. Nothing you
set is ever changed or deleted.

If it will not start
--------------------
The window says why and stays open. The usual reason is that the app is already running in
another window: close every ao3downloader window in Terminal and start it again.
"""


def mac_chip(machine: str | None = None) -> str:
    """apple-silicon or intel: which Macs a build made here runs on."""

    machine = machine or machines.machine()
    return MAC_CHIPS.get(machine, machine)


def system(platform: str | None = None, machine: str | None = None) -> str:
    """What the zip is named for: windows, macos-apple-silicon, macos-intel, or whatever else
    it was built on. Windows stays plain `windows` - the in-app updater looks for that name."""

    platform = platform or sys.platform
    if platform == 'darwin': return f'macos-{mac_chip(machine)}'
    return {'win32': 'windows'}.get(platform, platform)


def mac_readme(chip: str) -> str:
    return MAC_README.format(which=MAC_FOR.get(chip, MAC_FOR['apple-silicon']))


def stage_web(root: Path, staging: Path, skip_web: bool, settings: Path | None = None,
              version: str = '', repository: str = '') -> Path:
    """The prebuilt page, with the config that points it at the helper on this computer.

    `settings` is the settings.ini to ship in place of the template's - it is also what the
    page's own config is read from, so the two agree.

    `--skip-web` reuses the page already in `build/web` - from the PowerShell bundle - rather
    than compiling it again.
    """

    web = staging / build_artifacts.WEB_FOLDER
    source = root / 'build' / build_artifacts.WEB_FOLDER if skip_web \
        else build_artifacts.compile_web(root)
    if not (source / 'index.html').is_file():
        raise SystemExit(f'no page at {source} - build it first, or leave out --skip-web')
    build_artifacts.copy_tree(source, web)
    config = staging / build_artifacts.CONFIG_FOLDER
    if settings:
        config.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(settings, config / 'settings.ini')
    build_artifacts.write_config(config, root / PYTHON_HOME)
    build_artifacts.write_page_config(staging, version, repository)
    return web


def pyinstaller_arguments(root: Path, web: Path, defaults: Path) -> list[str]:
    python_home = root / PYTHON_HOME
    settings = python_home / PACKAGE_NAME / 'settings'
    return [
        str(python_home / ENTRY),
        '--name', APP_NAME,
        # a folder, not one file - see the module docstring
        '--onedir',
        # a console window: it is what the helper talks to, and closing it stops the app
        '--console',
        '--noconfirm',
        '--clean',
        '--distpath', str(root / DIST),
        '--workpath', str(root / WORK),
        '--specpath', str(root / WORK),
        # `from source_code import ...` resolves against the helper's folder
        '--paths', str(python_home),
        # read through importlib.resources, which no import graph can see - the same reason
        # build_artifacts.HELPER_DATA names it
        '--add-data', f'{settings}:{PACKAGE_NAME}/settings',
        '--add-data', f'{web}:{build_artifacts.WEB_FOLDER}',
        '--add-data', f'{defaults}:{DEFAULTS_FOLDER}',
    ]


def assemble(root: Path, platform: str | None = None, machine: str | None = None) -> Path:
    """Put a README beside the program - and on a Mac the script that starts it - and return
    the app's folder. No settings: see `DEFAULTS_FOLDER`."""

    app = root / DIST / APP_NAME
    if (platform or sys.platform) == 'darwin':
        (app / 'README.txt').write_text(mac_readme(mac_chip(machine)), encoding='utf-8', newline='\n')
        launcher = app / MAC_LAUNCHER
        launcher.write_text(MAC_LAUNCHER_SCRIPT, encoding='utf-8', newline='\n')
        launcher.chmod(0o755)
    else:
        # notepad on an older Windows shows a file with bare newlines as one long line
        (app / 'README.txt').write_text(WINDOWS_README, encoding='utf-8', newline='\r\n')
    return app


def zip_name(platform: str | None = None, machine: str | None = None) -> str:
    return f'{APP_NAME}-{system(platform, machine)}.zip'


def make_zip(app: Path, destination: Path) -> Path:
    """Zip the app's folder, keeping the folder itself at the top so unzipping makes one
    folder rather than scattering files.

    Each file keeps its permissions - the program and the Mac launcher have to stay
    executable - and a symlink is stored as a symlink, never followed: PyInstaller's Mac
    build links parts of its own folder to each other, and a link followed into a copy
    would duplicate what it points at, or be left out when it points at a folder."""

    if destination.exists(): destination.unlink()
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for folder, folders, files in os.walk(app):
            folders.sort()
            for name in sorted(folders + files):
                path = Path(folder) / name
                entry = (Path(APP_NAME) / path.relative_to(app)).as_posix()
                if path.is_symlink():
                    link = zipfile.ZipInfo(entry)
                    link.create_system = 3
                    link.external_attr = (stat.S_IFLNK | 0o755) << 16
                    archive.writestr(link, os.readlink(path))
                elif path.is_file():
                    archive.write(path, entry)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--skip-web', action='store_true',
                        help='reuse the page already in build/web instead of compiling it')
    parser.add_argument('--settings', type=Path,
                        help='the settings.ini to ship, in place of the template')
    parser.add_argument('--version', default='',
                        help="this build's version, e.g. 1.8.3 - the page checks for newer ones")
    parser.add_argument('--repo', default='',
                        help='owner/name of the repository its releases are published on')
    args = parser.parse_args()
    if args.settings and not args.settings.is_file():
        raise SystemExit(f'no settings.ini at {args.settings}')

    root = Path(__file__).resolve().parents[len(PYTHON_HOME.parts)]
    staging = root / STAGING
    if staging.exists(): shutil.rmtree(staging)
    staging.mkdir(parents=True)

    web = stage_web(root, staging, args.skip_web, args.settings.resolve() if args.settings else None,
                    args.version, args.repo)

    # imported here, so the rest of this module - and its tests - need no PyInstaller
    import PyInstaller.__main__
    PyInstaller.__main__.run(pyinstaller_arguments(root, web, staging / build_artifacts.CONFIG_FOLDER))

    app = assemble(root)
    archive = make_zip(app, root / DIST / zip_name())
    print(f'\napp written to {app}')
    print(f'zip written to {archive}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
