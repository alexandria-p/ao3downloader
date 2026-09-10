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

# copied beside the package, verbatim. pyproject.toml is not here because it is rewritten
# on the way - see write_pyproject.
PROJECT_FILES = ['uv.lock']

# the bundle ships no README beside the package, so the field pointing at one has to go
# with it: hatchling refuses to build when readme names a file that is not there.
README_FIELD = 'readme = "README.md"'

# the gui never stores a password, so the bundle should not offer the setting that would
SAVE_PASSWORD_KEY = 'SavePassword'

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


def strip_readme_field(content: str) -> str:
    """Drop pyproject.toml's readme field, since the bundle ships no README beside it.

    Raises if a readme field is present in some other form, rather than shipping a
    pyproject.toml that points at a missing file and fails only at install time.
    """

    kept = []
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith('readme'):
            if stripped != README_FIELD:
                raise ValueError(
                    f'expected {README_FIELD!r} in pyproject.toml but found {stripped!r}. '
                    'Update README_FIELD in build_artifacts.py.')
            continue
        kept.append(line)
    return ''.join(kept)


def strip_setting(content: str, key: str) -> str:
    """Remove one ini setting along with the comment block that documents it."""

    kept: list[str] = []
    for line in content.splitlines(keepends=True):
        if line.strip().lower().startswith(key.lower() + '='):
            # take the explanation with it, and the blank line that separated the pair
            # from whatever came before
            while kept and kept[-1].lstrip().startswith('#'):
                kept.pop()
            while kept and not kept[-1].strip():
                kept.pop()
            continue
        kept.append(line)
    return ''.join(kept)


def write_pyproject(python_home: Path, helper_dir: Path) -> None:
    content = (python_home / 'pyproject.toml').read_text(encoding='utf-8')
    (helper_dir / 'pyproject.toml').write_text(strip_readme_field(content), encoding='utf-8')


def write_config(config_dir: Path, python_home: Path) -> list[str]:
    """Seed settings.ini, leaving one that is already there alone.

    A rebuild must not throw away the download folder, so it is only ever created when
    missing. data.json is deliberately not seeded: the web ui remembers the username in
    the browser and never stores a password, and the application creates the file itself
    on first run if it needs one.
    """

    config_dir.mkdir(parents=True, exist_ok=True)
    created = []

    settings = config_dir / 'settings.ini'
    if not settings.exists():
        template = (python_home / PACKAGE_NAME / 'settings' / 'settings.ini').read_text(
            encoding='utf-8')
        # the web ui logs in each time and never stores a password, so offering the
        # setting that would only invites confusion
        settings.write_text(strip_setting(template, SAVE_PASSWORD_KEY), encoding='utf-8')
        created.append(settings.name)

    # an earlier build seeded this; it is the application's to create, not the build's
    stale_data = config_dir / 'data.json'
    if stale_data.is_file(): stale_data.unlink()

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
    write_pyproject(python_home, helper_dir)
    for name in PROJECT_FILES:
        shutil.copyfile(python_home / name, helper_dir / name)
    # an earlier build shipped a README here; the bundle no longer has one
    stale_readme = helper_dir / 'README.md'
    if stale_readme.is_file(): stale_readme.unlink()

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
| `ao3_download_helper/` | The python behind the download buttons. |
| `config/settings.ini` | Your settings, including where fics are saved. |

`config/data.json` is not shipped. The web ui remembers your username in the browser and
never stores a password, so the application creates that file itself if it needs one.

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

Inside it:

| Path | What lands there |
| --- | --- |
| `<downloads>/indexing/` | One json file per bookmark - the index. |
| `<downloads>/` | The works themselves: html, epub, pdf and so on. |
| `<downloads>/images/` | Images embedded in works, if you asked for them. |
| `<downloads>/collections/` | One json file per collection, if you have synced them. |

## How files are named, and how they get linked together

Every file - json, html, epub, pdf - is named from the `FileNamePattern` setting in
`config/settings.ini`. It defaults to:

```
{worknum} {title} - {author}
```

...producing names like `34816549 No Paths Are Bound - Cataclysmic_Cal.html`. The name is
then cut to `FileNameLength` characters (50 by default), which is why longer titles end
mid-word.

**The work number has to come first.** That is the only part that matters for matching a
downloaded work to its entry in the index. The rule is exact:

- the digits at the **start** of the file name, and
- followed by a space, `_`, `.` or `-` (or the name ends there)

So `34816549 No Paths Are Bound.html` links up; `No Paths Are Bound 34816549.html` does
not, because the number is not first. `99Red Balloons.html` does not either, because
nothing separates the digits from the title - which is deliberate, so a title that merely
begins with digits is not mistaken for a work number.

That is the bare minimum for a file you bring in from somewhere else: **start the file
name with the AO3 work id, then a separator.** Everything after that is free.

If you change `FileNamePattern` so the work number is no longer first, the index still
builds, but the web page can no longer pair works with it - every title will open on AO3
instead of your local copy. The page tells you when that is happening: the line under the
heading reports how many works it found a downloaded copy for.

## What is inside an index file

Each json file keeps a history rather than being overwritten, so you can see how a fic
changed over time:

```json
{
  "id": "34816549",
  "link": "https://archiveofourown.org/works/34816549",
  "source": "https://archiveofourown.org/users/you/bookmarks",
  "position": 4,
  "last_indexed": "2026-09-10T12:34:56+00:00",
  "indexes": [
    { "indexed_on": "2026-09-01T10:00:00+00:00", "title": "...", "kudos": 12 },
    { "indexed_on": "2026-09-10T12:34:56+00:00", "title": "...", "kudos": 15 }
  ]
}
```

- `last_indexed` is updated every time the fic is indexed, whether or not anything changed
- a new entry is added to `indexes` only when the reading differs from the one before it
- `position` is where the fic sat in your bookmarks that run, and is not part of the
  history - a fic sliding down the list is not a change to the fic

## What is inside a collection file

Two buttons write these. **Index my collections** reads your own collections listing;
**Index collection by URL** takes a link to any one collection on ao3, yours or not - any
page of it will do. Both write one json file per collection into
`<downloads>/collections/`, named after the collection's ao3 name - the part of the url
after `/collections/` - cut to the same `FileNameLength` limit.

No works are downloaded by either. A collection file records what the collection
*contains*, by work id, which is what lets it pair up with fics you already have. Works it
lists that are not in your index are still shown on the collections page, by work number
with a link to ao3, since the number is all that is known about them. It is versioned
exactly like an index file:

```json
{
  "name": "yuletide2024",
  "link": "https://archiveofourown.org/collections/yuletide2024",
  "source": "https://archiveofourown.org/users/you/collections",
  "last_indexed": "2026-09-10T12:34:56+00:00",
  "indexes": [
    {
      "indexed_on": "2026-09-10T12:34:56+00:00",
      "title": "Yuletide 2024",
      "description": "...",
      "maintainers": ["someone"],
      "tags": ["Yuletide"],
      "active_since": "01 Sep 2024",
      "challenge_type": "Gift Exchange Challenge",
      "multifandom": true,
      "closed": true,
      "moderated": true,
      "fandom_count": 1193,
      "work_count": 4021,
      "parent_collection": "https://archiveofourown.org/collections/yuletide",
      "subcollections": ["https://archiveofourown.org/collections/..."],
      "work_ids": ["34816549", "..."],
      "bookmark_ids": ["..."]
    }
  ]
}
```

- `challenge_type` is `Gift Exchange Challenge`, `Prompt Meme Challenge` or `No Challenge`
- `multifandom` is whether the collection's profile page counts more than one fandom
- `parent_collection` and `subcollections` are links rather than nested copies - a
  subcollection you own gets a file of its own
- `work_ids` and `bookmark_ids` are the work numbers in the collection's works and
  bookmarked items, which is what your downloaded file names start with

### Re-indexing a collection you already have

Walking a collection's works is the most expensive thing this program does: one request
per twenty works, so a large collection runs to hundreds of requests on its own.

It is also usually unnecessary. The profile page - which has to be fetched anyway - says
how many works and bookmarked items the collection holds. When that total matches the one
already in the file, the saved ids are kept and the listing is not walked at all, so an
unchanged collection costs two requests instead of hundreds. Works, bookmarked items and
subcollections are each judged on their own count.

The one case this cannot see is a collection that had one work added and another removed
between runs, leaving the total unchanged. Delete that collection's json file to force a
full crawl. A crawl that failed or was stopped is never mistaken for a complete one.

## Keeping ao3 happy

Ao3 rate-limits by *how fast* requests arrive, not how many you make in total, and it
answers a burst with a pause of several minutes. Two settings decide how often you meet it:

- `ExtraWaitTime` in `config/settings.ini` is how long to wait after every request. `0`
  means "as fast as possible", which is what trips the limit fastest. 15 seconds is the
  default here and is a reasonable place to start.
- The file types you tick. Indexing reads one page per 20 works; every other type costs a
  request per work on top. Unticking everything but JSON gives a metadata-only run, which
  is roughly a fortieth of the requests.

A fic's page is fetched once however many formats you tick - every format's download link
is read off that one page - so a second format costs one extra transfer per fic, not a
second crawl of it. The transfers themselves cannot be merged: each format is its own file
at its own address.

The bookmarks run can also start partway through a listing. Start and stop are both
positions in the whole listing, so pages 5 to 9 fetches just that slice - useful for
carrying on after a stopped run without refetching what you already have.

Nothing is lost when you are paused - the run waits and carries on by itself, and the
**Stop** button keeps everything already written.

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
