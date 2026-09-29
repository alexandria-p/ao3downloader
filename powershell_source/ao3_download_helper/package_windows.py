"""Build the Windows app: a zip holding `ao3downloader.exe` and everything it needs.

Unzipped and double-clicked, the exe does what `Start-Application.ps1` does in a generated
build - see `source_code/desktop.py` - with Python and every dependency packed beside it, so
the person using it needs no PowerShell, uv or Python.

A folder in a zip rather than one self-contained exe, on purpose: a one-file exe unpacks
itself into a temporary folder on every start, which is slow and is the thing antivirus
programs most often object to, and the app needs a folder beside it for its settings and
logs anyway.

PyInstaller builds for the system it runs on, so the Windows zip is built on Windows - the
`build windows app` workflow does it on a Windows runner. Run elsewhere, this builds the same
app for that system, which is how it is tested.

    uv sync --group package
    uv run --no-sync python package_windows.py [--skip-web] [--settings windows-settings.ini]

`--settings` is the settings.ini to ship - the workflow writes one from the deployment's
variables with `deploy_config.py local-settings`, pointed at the app's own helper. Without it
the app ships the template's.

The zip lands in `dist/` at the repository root.
"""

import argparse
import shutil
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

README = """ao3downloader
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
config\\settings.ini   the app's settings - pacing, file names and the rest. Created on the
                      first start; edit it while the app is closed.
logs\\                 the helper's own log.

Your fics are saved in whichever folder you open in the app, on this computer or in Dropbox.

Updating
--------
Download the new zip and unzip it over this folder, or into a new one and copy your config
folder across. Your settings are only ever added to, never replaced.

If it will not start
--------------------
The window says why and stays open. The usual reason is that the app is already running in
another window: close every ao3downloader window and start it again.
"""


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


def pyinstaller_arguments(root: Path, web: Path) -> list[str]:
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
    ]


def assemble(root: Path, staging: Path) -> Path:
    """Put the settings and a README beside the exe, and return the app's folder."""

    app = root / DIST / APP_NAME
    config = app / build_artifacts.CONFIG_FOLDER
    config.mkdir(exist_ok=True)
    # shipped so it can be edited before the first start; the app adds to it, never replaces it
    shutil.copyfile(staging / build_artifacts.CONFIG_FOLDER / 'settings.ini', config / 'settings.ini')
    (app / 'README.txt').write_text(README, encoding='utf-8', newline='\r\n')
    return app


def zip_name() -> str:
    system = 'windows' if sys.platform == 'win32' else sys.platform
    return f'{APP_NAME}-{system}.zip'


def make_zip(app: Path, destination: Path) -> Path:
    """Zip the app's folder, keeping the folder itself at the top so unzipping makes one
    folder rather than scattering files."""

    if destination.exists(): destination.unlink()
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():
                archive.write(path, Path(APP_NAME) / path.relative_to(app))
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
    PyInstaller.__main__.run(pyinstaller_arguments(root, web))

    app = assemble(root, staging)
    archive = make_zip(app, root / DIST / zip_name())
    print(f'\napp written to {app}')
    print(f'zip written to {archive}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
