"""Assemble a deployable bundle in build/.

Everything needed to run the site on another machine ends up in one folder: the compiled
web app, the python that serves it and performs downloads, the launcher, and a settings
file. Nothing in here is needed to work on the project - it only produces output.

The bundle mirrors the working copy: the python sits in ao3_download_helper/ exactly as it
does under powershell_source/, so pyproject.toml needs no rewriting on the way.

Run it through generate_build_artifacts.ps1 in the repository root, or directly:

    uv run python build_artifacts.py
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# where the launcher dot-sources its shared functions in the working copy. a shipped copy
# has no powershell_source beside it, so the functions are pasted in at this point instead.
DOT_SOURCE = """$envScript = Join-Path $PSScriptRoot 'powershell_source\\ao3_download_helper\\ao3-env.ps1'
. $envScript"""

# the python project, relative to the repository root
PYTHON_HOME = Path('powershell_source') / 'ao3_download_helper'
PACKAGE_NAME = 'source_code'

# the launcher: one file in the working copy, one in the bundle, nothing in between
LAUNCHER_SOURCE = 'run_development_build.ps1'
LAUNCHER_OUTPUT = 'Start-Application.ps1'

# folder names inside the bundle
HELPER_FOLDER = 'ao3_download_helper'
CONFIG_FOLDER = 'config'
WEB_FOLDER = 'web'

ANGULAR_OUTPUT = Path('dist') / 'ao3-bookmarks' / 'browser'

# copied beside the package. README.md is not optional: pyproject.toml's readme field
# points at it, and hatchling refuses to build the package without it.
PROJECT_FILES = ['pyproject.toml', 'uv.lock', 'README.md']

# left by older bundle layouts, cleared so a rebuild does not leave two of everything
STALE = ['download_helper_scripts', 'ao3downloader', 'source_code', 'run-gui.ps1',
         'pyproject.toml', 'uv.lock', 'settings.ini', 'data.json']

IGNORED = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache', '.venv')


def generate_launcher(launcher: str, shared: str) -> str:
    """Fold the shared functions into the launcher so the shipped file is self-contained.

    Raises if the expected dot-source block is missing, rather than shipping a launcher
    that would fail at run time with an unhelpful "Get-Ao3Root is not recognised".
    """

    if DOT_SOURCE not in launcher:
        raise ValueError(
            f'{LAUNCHER_SOURCE} no longer contains the expected dot-source block, so the '
            'shared functions cannot be inlined. Update DOT_SOURCE in build_artifacts.py.')

    inlined = (
        '# --- inlined from ao3-env.ps1 by build_artifacts.py ---\n'
        f'{shared.strip()}\n'
        '# --- end of inlined functions ---')

    return launcher.replace(DOT_SOURCE, inlined)


def build_launcher(root: Path, build_dir: Path) -> Path:
    """Write the self-contained launcher straight into the bundle."""

    generated = generate_launcher(
        (root / LAUNCHER_SOURCE).read_text(encoding='utf-8'),
        (root / PYTHON_HOME / 'ao3-env.ps1').read_text(encoding='utf-8'))

    output = build_dir / LAUNCHER_OUTPUT
    output.write_text(generated, encoding='utf-8', newline='\r\n')
    return output


def compile_web(root: Path) -> Path:
    """Compile the Angular app and return the folder holding the static files."""

    gui = root / 'gui_source'
    subprocess.run(['npm', '--prefix', str(gui), 'run', 'build'],
                   check=True, shell=sys.platform == 'win32')

    output = gui / ANGULAR_OUTPUT
    if not output.is_dir():
        raise FileNotFoundError(f'the web build produced nothing at {output}')
    return output


def copy_tree(source: Path, destination: Path) -> None:
    if destination.exists(): shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=IGNORED)


def write_config(config_dir: Path, python_home: Path) -> list[str]:
    """Seed settings.ini and data.json, leaving any that are already there alone.

    A rebuild must not throw away the download folder or the saved username, so these two
    are only ever created when missing.
    """

    config_dir.mkdir(parents=True, exist_ok=True)
    created = []

    settings = config_dir / 'settings.ini'
    if not settings.exists():
        shutil.copyfile(python_home / PACKAGE_NAME / 'settings' / 'settings.ini', settings)
        created.append(settings.name)

    data = config_dir / 'data.json'
    if not data.exists():
        # no BOM: python's json reader rejects one
        data.write_text('{}', encoding='utf-8')
        created.append(data.name)

    return created


def clear_stale(build_dir: Path) -> None:
    """Remove anything an older bundle layout left at the top level."""

    for name in STALE:
        path = build_dir / name
        if path.is_dir(): shutil.rmtree(path)
        elif path.is_file(): path.unlink()


def write_readme(build_dir: Path) -> None:
    (build_dir / 'README.md').write_text(README, encoding='utf-8')


def build(root: Path, skip_web: bool = False) -> dict:
    """Produce the bundle. Returns a summary of what was written."""

    build_dir = root / 'build'
    build_dir.mkdir(exist_ok=True)
    clear_stale(build_dir)

    launcher = build_launcher(root, build_dir)

    if not skip_web:
        copy_tree(compile_web(root), build_dir / WEB_FOLDER)

    python_home = root / PYTHON_HOME
    helper_dir = build_dir / HELPER_FOLDER
    copy_tree(python_home / PACKAGE_NAME, helper_dir / PACKAGE_NAME)
    for name in PROJECT_FILES:
        shutil.copyfile(python_home / name, helper_dir / name)

    created = write_config(build_dir / CONFIG_FOLDER, python_home)
    write_readme(build_dir)

    return {'build_dir': build_dir, 'launcher': launcher, 'config_created': created}


README = """# ao3downloader - deployable bundle

This folder was produced by `generate_build_artifacts.ps1` in the project root. Everything
needed to run the site is here; nothing outside this folder is required.

Do not edit anything in here by hand except `config/settings.ini`. Regenerating the bundle
overwrites the rest.

## What is in it

| Path | What it is |
| --- | --- |
| `Start-Application.ps1` | Starts the helper and serves the site. Self-contained. |
| `web/` | The compiled web app - plain static files. |
| `ao3_download_helper/` | The python behind the two download buttons. |
| `config/settings.ini` | Your settings, including where fics are saved. |
| `config/data.json` | Saved username and file type choices. |

All of it is needed. The site will display bookmarks without `ao3_download_helper/`, but
both download buttons will fail, because that folder *is* what they call.

Running it also creates `ao3_download_helper/.venv/`, `ao3_download_helper/logs/` and your
downloads folder. Those are working files rather than part of the bundle - if you copy this
folder somewhere else, leave `.venv/` behind and let the first run rebuild it.

## Running it

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). Node is *not*
needed - the web app is already compiled.

```
powershell.exe -ExecutionPolicy Bypass -File .\\Start-Application.ps1
```

The first run creates the python environment, which takes a minute. Then open
<http://localhost:4200>. Ctrl+C in that window stops everything.

To use a different port: `.\\Start-Application.ps1 -Port 8080`

## Where downloads go

Whatever `DownloadFolder` in `config/settings.ini` says. A relative path is resolved from
this folder, so the default `downloads` means `./downloads` here.

## A caveat about deploying this to a server

The web app is static and will serve from anywhere. The download buttons will not.

They talk to the helper on `127.0.0.1:4400`, which means the helper has to run on the same
machine as the *browser*, and downloads land on the machine running the *helper*. Putting
this on a remote server gives visitors a bookmark browser whose buttons fail, and any
download that did run would save to the server's disk, logged in as whoever's ao3 account
was typed in.

Treat it as something you run locally, or on a machine you alone use.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-web', action='store_true',
                        help='reuse the existing web/ folder instead of recompiling')
    args = parser.parse_args()

    # this module lives at <root>/PYTHON_HOME/, so climb back out by that many levels
    # rather than a fixed number, which would silently break if the folder moves again
    root = Path(__file__).resolve().parents[len(PYTHON_HOME.parts)]
    if not (root / LAUNCHER_SOURCE).is_file():
        raise SystemExit(f'expected {LAUNCHER_SOURCE} in {root}; is PYTHON_HOME still right?')

    result = build(root, skip_web=args.skip_web)

    print(f'\nbundle written to {result["build_dir"]}')
    if result['config_created']:
        print(f'created: {", ".join(result["config_created"])}')
    print(f'run it with: powershell.exe -ExecutionPolicy Bypass -File '
          f'.\\build\\{LAUNCHER_OUTPUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
