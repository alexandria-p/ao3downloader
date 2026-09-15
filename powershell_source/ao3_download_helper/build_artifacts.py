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
import ast
import os
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

# The bundle runs the helper and nothing else, so it ships what the helper imports and stops
# there. Worked out by following imports rather than by keeping a list, because a list goes
# stale the moment a module gains an import and nobody notices until it breaks.
#
# Nothing is left behind any more: the console menu, its actions, and the ebook parsing only
# they used have been deleted, so the package is exactly what the helper reaches. A name in
# `left_behind` now means dead code, or a module that lost its last import by accident.
HELPER_ENTRY = 'server'

# read at run time through importlib.resources, so no import graph can see them
HELPER_DATA = ['settings']

# never walked into when working out what to keep
IGNORED_DIRS = {'__pycache__', '.pytest_cache', '.venv'}

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


def package_imports(path: Path) -> set[str]:
    """The package's own modules that one file imports, as dotted names.

    Both halves of `from source_code.ao3 import Ao3` are returned - the module and the
    name below it - because only one of them is a file and which one is settled by looking.
    """

    tree = ast.parse(path.read_text(encoding='utf-8'))
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if not node.module or not node.module.startswith(PACKAGE_NAME): continue
            found.add(node.module)
            found.update(f'{node.module}.{alias.name}' for alias in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith(PACKAGE_NAME))

    return found


def module_file(package: Path, dotted: str) -> Path | None:
    """The file a dotted module name refers to, or None when it names something else."""

    if not dotted.startswith(PACKAGE_NAME + '.'): return None
    relative = dotted[len(PACKAGE_NAME) + 1:].replace('.', os.sep)
    candidate = package / (relative + '.py')
    return candidate if candidate.is_file() else None


def helper_modules(package: Path) -> set[str]:
    """Every module the helper reaches, following imports out from its entry point."""

    entry = f'{PACKAGE_NAME}.{HELPER_ENTRY}'
    if not module_file(package, entry):
        raise FileNotFoundError(
            f'{HELPER_ENTRY}.py is not in {package}. Update HELPER_ENTRY in build_artifacts.py.')

    seen: set[str] = set()
    pending = [entry]
    while pending:
        name = pending.pop()
        if name in seen: continue
        path = module_file(package, name)
        if not path: continue
        seen.add(name)
        pending.extend(package_imports(path))

    return seen


def copy_helper_package(package: Path, destination: Path) -> list[str]:
    """Copy the package minus everything the helper never reaches.

    Returns the modules left behind, so a build can say what it dropped rather than
    quietly shipping less than last time.
    """

    keep = helper_modules(package)
    if destination.exists(): shutil.rmtree(destination)

    left_behind: list[str] = []
    kept_folders: set[Path] = set()

    for source in sorted(package.rglob('*.py')):
        relative = source.relative_to(package)
        if any(part in IGNORED_DIRS for part in relative.parts): continue
        if source.name == '__init__.py': continue

        dotted = PACKAGE_NAME + '.' + str(relative.with_suffix('')).replace(os.sep, '.')
        if dotted not in keep:
            left_behind.append(dotted)
            continue

        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        kept_folders.add(relative.parent)

    # a package needs its __init__.py, but only the ones that still have something in them
    for folder in kept_folders:
        marker = package / folder / '__init__.py'
        if marker.is_file():
            shutil.copyfile(marker, destination / folder / '__init__.py')

    for name in HELPER_DATA:
        folder = package / name
        if folder.is_dir():
            shutil.copytree(folder, destination / name, ignore=IGNORED)

    return sorted(left_behind)


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
    left_behind = copy_helper_package(python_home / PACKAGE_NAME, helper_dir / PACKAGE_NAME)
    write_pyproject(python_home, helper_dir)
    for name in PROJECT_FILES:
        shutil.copyfile(python_home / name, helper_dir / name)
    # an earlier build shipped a README here; the bundle no longer has one
    stale_readme = helper_dir / 'README.md'
    if stale_readme.is_file(): stale_readme.unlink()

    created = write_config(build_dir / CONFIG_FOLDER, python_home)
    write_readme(build_dir)

    return {'build_dir': build_dir, 'launcher': launcher, 'config_created': created,
            'left_behind': left_behind}


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

`ao3_download_helper/` holds **only what the web ui can actually invoke**. The console
menu, its actions, and the ebook parsing that only those use are left out of the bundle:
the build follows the helper's imports and ships what it reaches, so nothing arrives here
that nothing here can run. It prints the list of what it left behind each time it builds.

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

## What the buttons do

The page has two tabs, **Bookmarks** and **Collections**, each carrying the buttons that
fill it. All four ask you to log in to ao3 before they start, and none of them store your
password - it is sent to ao3 and forgotten. Only your username is remembered, in the
browser, and only if you tick the box.

### Bookmarks

**Quick Scan** is a full scan that stops early. It indexes in two walks, both back to the
day your last qualifying scan started: first your bookmarks **sorted by date bookmarked**,
stopping at the first one bookmarked before that day - which catches old fics you have only
just bookmarked - then your bookmarks **sorted by when ao3 last updated each work**, stopping
at the first one updated before that day - which catches fics bookmarked long ago that have
changed since. It then reads your existing files and downloads or updates whatever either
walk found, each fic once. With no earlier scan to measure from, the first walk reads
everything and the second is skipped.

You can also choose **which earlier scan to measure back to** instead of the most recent one -
useful if a recent scan may have missed something. The next page lists every completed full
scan and quick scan to pick from; the further back you go, the longer indexing takes.

Two things decide whether an earlier run counts as that mark. It has to have **finished** -
one that failed, was stopped or was interrupted may have given up before reaching works
updated before it started. And it has to be a run that **covered your whole listing**: a
full scan, or another quick scan that was not given a date range. Every other run covers
only part of your bookmarks, so it can finish perfectly while never looking at a fic ao3
updated that day, and measuring back to it would skip that fic for good.

**The first time you run it, it does a full index.** There is nothing to measure back to
until a qualifying scan has completed, so it walks the whole listing and downloads
everything missing - which on a large library is hours. Every run after that is the quick
one. What it gives up is the date: anything ao3 updated before that mark is never looked at,
so a fic missed by an earlier run stays missed.

With the debug tools on it can also be given **a date range of your own** instead of
measuring back to a scan - everything since a date, or between two dates. It uses the same
two walks, down to the older end of the range: once by date bookmarked, keeping works you
bookmarked in the range, and once by date updated, keeping works ao3 updated in it. Both
walks start at your newest bookmark, so works newer than the range are indexed on the way
down but not downloaded. The further back the older end goes, the longer the indexing takes.

**(Full scan) Reindex & Update All** reads `/users/<you>/bookmarks`, writes a json index entry
for every work on it, then downloads the works themselves. Anything already downloaded and
still current is skipped, so a second run only picks up what is new or has changed since.
You choose the file types. It covers every page by definition, so it does not ask which - a
custom run is where that lives. It is the only run that offers series links, because those
are read off a work's own page and it is the only run that fetches one. It is the only run
that
can repair a wrong index or notice a completed fic that has grown - and on a large library
it takes hours, which it says before you start.

Behind **Advanced options**:

**Download/update a specific fic** takes a work link or just the work number, indexes that
one fic, and downloads it in the formats you pick. A link to any chapter of it will do.

**Custom run** is the full scan with its parts made optional. It covers exactly one of
three things, which it asks before anything else: **all bookmarks**, a **slice** of your
listing by page number, or a **date range**. They are alternatives rather than settings that
combine - a run cannot be walking a listing and not walking it - so choosing one puts the
others away.

A date range comes in two shapes, everything updated since a date or between two dates, and
both ends count.

On top of whichever it covers, the run can **skip reading ao3 at all** and work from what is
already indexed. That costs no requests to decide anything, but judges everything against
however old your index is - useful for downloading your fics in a new format, or filling in
blanks in your downloaded files when the index is already up to date.

Unless you tick *skip indexing*, the run indexes first. It reads your bookmarks **sorted by
when ao3 last updated each work** and stops at the first fic older than the earliest date
you gave, because everything past that point is outside the range by definition. Give it no
earliest date and there is nothing to stop at, so it reads the whole listing. It then picks
the works in range out of the index, re-reads them one at a time newest first, and downloads
whatever turns out to be missing or behind.

With indexing skipped it reads no listing at all, and a fic whose index entry is behind ao3
can be picked or missed on the strength of that entry. Works with no recorded update date
are never covered either way, since there is nothing to compare.

Skipping the indexing decides a file type as well: json is the index, so a run that does not
index does not write it, and the json box is ticked or unticked to match and locked either
way. Every run asks its options first and its file types second for that reason, and a run
with nothing to choose skips the options step rather than showing an empty one.

It is also the only run that offers **saving embedded images separately**. That fetches each
work's page after its files are down, purely to read the image links out of it - an extra
request per fic, so it makes the run considerably longer. You probably do not need it:
images are normally embedded in the downloaded work already and display when you read it.
This only writes a second copy of each as its own file, in an `images` subfolder.

**Overwrite existing downloads** is offered here, on the full scan, and on the single-fic
run. It fetches every format you asked for again, whether or not ao3 has a newer version than
the copy you hold. Check it if you are worried about file integrity and would rather simply
download the file again: nothing else can spot a file that is damaged or truncated, because
the name and the date are both right and only the bytes are wrong. Nothing is skipped for
already being current, so it costs a request per format per work and makes the run far
longer. It is deliberately not offered on the routine runs, which exist to be cheap.

Behind **Advanced options**, and only when the debug tools are on:

**Download new bookmarks and update incomplete fics** makes three passes, in this order:
your newest bookmarks, then the fics your index last saw unfinished, then any finished fic
missing a format you asked for on this run. None of them walks your whole listing, so it
stays quick however large your library is.

The order is what makes the third pass cheap. The second has already re-read and downloaded
every *unfinished* fic, so by the time the third runs, everything left is a work the index
calls finished - and a finished work needs nothing but the formats you do not have yet. Each
of those is re-read before it is fetched, so the file is named for the version ao3 has now
rather than whatever the index was holding, and only the missing formats are fetched.

It asks you to acknowledge two things first, and that note can be turned off. Indexing stops
at the first bookmark it recognises, so if your index is incomplete - an earlier run
interrupted, files deleted - the fics behind that point stay unseen. And it never re-reads a
fic the index already calls finished, so chapters added to one afterwards are not noticed. A
full scan answers both.

**Just update any bookmarks marked as incomplete** takes the fics your index last recorded as
unfinished, opens each one on ao3, and brings its index entry up to date. It downloads a fic
only if you have no copy of it or the copy you have is behind - see
[Updating unfinished fics](#updating-unfinished-fics), which also covers the one thing it
cannot find. You have to acknowledge that before it will let you log in.

**Just download newly added bookmarks** indexes from your newest bookmark and stops at the
first one you already have, then downloads what it found. It is the first pass of the
combined run, on its own.

Those three are the individual passes **Quick Scan** and **(Full scan) Reindex &
Update All** are built from, so they are off by default. Set `EnableDebugTools=true` in
`config/settings.ini` to show them - they appear in red, prefixed **[DEBUG]**, because
reaching for one part when you wanted the whole is the easy mistake to make.

### Collections

**Index my collections** reads `/users/<you>/collections` and writes a json file describing
each collection you own - its metadata, and the work numbers it holds. No works are
downloaded.

**Index collection by URL** does the same for any one collection on ao3, yours or not. Paste
a link to it; any page of the collection will do. The file it writes sits alongside your own
and has the same shape.

Clicking a collection opens what was recorded about it, along with the works in it, in the
same listing the Bookmarks tab uses. Works it holds that are not in your index are still
listed, by work number, with a link to ao3.

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

Every file - json, html, epub, pdf - is named the same way, and the naming is **not**
configurable:

```
{worknum} {title} - {author} {date updated}
```

Two parts of that are load-bearing: the work number has to come first for a file to be
matched back to its index entry, and the date has to come last for the version it holds to
be readable. Rearranging them broke both, so it stopped being a setting. The web page shows
the rule back to you under "Settings this run is using".

The name is then cut to `FileNameLength` characters (50 by default), which is why longer
titles end mid-word.

A downloaded work also ends with the date it was last updated on ao3:

```
34816549 No Paths Are Bound - Cataclysmic_Cal 2026-08-23.html
```

That is not when you downloaded it - it is which *version* of the fic the file holds, which
is how the program can tell later that ao3 has a newer one than you do. The date is never
what gets cut: the title is shortened first so the date still fits inside `FileNameLength`.

Json index files are deliberately **not** dated. An index file is the version history for
its fic, so a name that changed whenever the fic did would start a new file and orphan
everything already recorded.

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

## Updating unfinished fics

**Update any bookmarks marked as incomplete** works from the index, not from the files on
disk. Nothing is parsed out of an epub to find a chapter count, and no listing is walked to
find the works:

1. It reads `<downloads>/indexing/` for every fic the index last recorded as unfinished -
   a chapter count of `12/?`, or one short of its own total. That costs no requests, and
   the modal says how many it found.
2. It looks through the downloads folder for the files belonging to those fics, matching
   each one by the work number it starts with.
3. If any of those files were saved before names carried a date, it stops and asks what to
   do about them before going any further. It has to ask now, because the answer decides
   which copies count as out of date.
4. Then it works through the fics **one at a time**. For each one it opens the fic on ao3
   using the link already in its json file (one request), writes what it found back into
   the index, and downloads it only if it has to. Each of those is announced in the modal
   as it happens.

A fic is downloaded **only** if one of two things is true: you have no copy of a format you
asked for, or the copy you have is behind the version ao3 now reports. The old copy is
replaced under the usual safeguards.

The re-read happens for every unfinished fic whether or not anything comes of it, so the
index ends up current even where nothing needed downloading. Only the download is
conditional, which is why a fic that has not moved costs one request and nothing else.

This is a different order from **(Full scan) Reindex & Update All**, which indexes the whole
listing first and downloads afterwards. It can, because one listing request describes twenty
fics at once. Here every fic has to be opened on its own, so there is nothing to gain by
doing all the reading first - and going fic by fic means a run you stop partway has
completely finished every fic it got to.

Only the fields a work's own page can speak to are rewritten. Tags, the summary and your
own bookmark notes come from the listing, so they are left alone and refreshed by a
**(Full scan) Reindex & Update All** run instead.

**What it will not catch:** a fic that had already finished when it was last indexed. If a
work was marked complete and then updated afterwards - an epilogue added, chapters edited -
the index records it as complete, so this pass skips it. The web ui makes you acknowledge
that before it will let you log in. Use **(Full scan) Reindex & Update All** for those: it
re-reads the whole listing and sees anything ao3 reports as updated more recently than your
copy, finished or not.

## Keeping downloads up to date

Because a downloaded work carries the date of the version it holds, the bookmarks run can
tell when ao3 has a newer version than you do. After indexing - which is where the current
dates come from - it reads the downloads folder, matches each file to a work by the number
it starts with, and fetches again anything ao3 has updated since it was saved. Only the
file types you ticked are considered.

When a fic is re-downloaded its name changes, because the date in it changes. The copy it
replaces is removed, but only when all of this holds:

- it is the **same file type** - re-downloading the html never removes the epub
- the new file is really in the downloads folder in use, at its full length
- the name actually changed; if it did not, the write already replaced it in place

A download that fails or is stopped partway leaves the old file exactly where it is. You
never lose the copy you have until the one replacing it is confirmed on disk.

A run does not stop because one fic will not come down - it may have been deleted, made
restricted, or never existed in the format you asked for. Those are skipped, and when the
run finishes it names them: how many, the first few with the reason, and a link to each.
One **Export all issues** button saves every list as a single plain text file, under a
heading per kind - one work per line, with the work number, link and reason - so the numbers
can be fed back in. A work is listed once however many formats failed for it.

Every downloaded file is checked straight after it is written. One that is missing or the
wrong size is deleted and reported as a failure with the reason, leaving any older copy
alone. If the older copy will not delete, or the check itself goes wrong, nothing is removed
and the work is listed as needing checking by hand - at the end of the run, in the exported
file, and in History.

A second list covers **bookmarks that were never works at all**: a series bookmarked as a
series, a work hosted somewhere other than ao3, or one that has since been deleted. Each is
named with the reason the listing gave - and where the listing does not say, it says so
rather than guessing - under its own heading in the exported file. These are kept apart from
the failures above on purpose. Nothing went wrong with them and running again will skip them
again, so mixing the two would make a real failure look routine.

Every button ends this way - its last step is *Report any failures* - including the ones
that only index and downloading a single fic by link.

Works saved before names carried a date cannot be judged: nothing records which version
they are. **The run stops and asks what to do about them before it downloads anything** -
it has to ask then rather than afterwards, because the answer decides which works count as
out of date. Both the bookmarks run and the update run ask, right after working out what
you already have. There are three choices:

**Give them a date.** You say which version to treat them as, and the files are renamed
where they sit. Nothing is downloaded to do this - no requests at all - and the run carries
straight on, so anything ao3 has updated since that date is fetched on the same pass. Today
means "what I have is current"; an earlier date means "my copies are from around then", so
everything touched since is fetched. Long names are cut down as a fresh download would cut
them, and a file is never renamed over one that already exists.

**Re-download them.** Every one counts as out of date from then on. The run carries on in
its usual order and, as it reaches each of them, fetches the current version and removes the
old copy under the usual safeguards. That is a full download of the lot.

**Ignore and skip them.** They stay as they are, nothing is downloaded for them, and the
run continues with everything else. Stopping the run while it is asking does the same.

If a file's name does not start with the work number - one you renamed, or brought in from
elsewhere - the index still builds, but the web page cannot pair the two, so that title
opens on AO3 instead of your local copy. The page tells you when that is happening: the
line under the heading reports how many works it found a downloaded copy for.

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

No page is read to find a download. A work's download link is decided by its work number,
which the index already recorded, so the download step goes straight to the file: the
listing is not walked again to rediscover links, and no fic's page is fetched at all. What
is left is one request per work per format, and those cannot be merged - each format is its
own file at its own address.

Asking for embedded images or series links sends the run the long way round instead, since
both are discovered on the work page, and those runs cost an extra request per fic.

The bookmarks run can also start partway through a listing. Start and stop are both
positions in the whole listing, so pages 5 to 9 fetches just that slice - useful for
carrying on after a stopped run without refetching what you already have.

Nothing is lost when you are paused - the run waits and carries on by itself, and the
**Stop** button keeps everything already written.

## Pausing a run

Next to **Stop** there is a **Pause**, and it takes effect straight away. If a file is
coming down when you press it - a large pdf, say - that transfer is abandoned where it is,
and **Resume** fetches the file again from the beginning. A page of the index behaves the
same way: it is dropped, and read again on resume.

Nothing is ever left half-written by this. A file is only saved once all of it has arrived
and been checked, and a page of the index is only written once the whole page has been read,
so there is nothing on disk to half-finish. All a pause costs is the part of a transfer
already fetched, which is fetched again.

While paused, no requests go out and nothing new is started. It stays paused until you press
**Resume**: it will not start again by itself, because an unattended run going back at ao3
without you is not something that should happen on a timer. **Stop still works while
paused**, so a pause can never leave a run stuck.

This is a different thing from the break ao3 asks for when you go too fast, which the page
also calls a pause. That one nobody chose and it clears up by itself; this one is yours and
ends when you say.

One caveat: an ao3 login does not last forever. A run left paused a long time may find its
session gone when you resume, which shows up as works failing to download. Stop it and start
a new run if that happens.

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
    if result['left_behind']:
        # said out loud so a module dropping out of the bundle is noticed at build time
        print(f'left behind ({len(result["left_behind"])} modules the helper never imports):')
        for name in result['left_behind']:
            print(f'    {name}')
    print(f'run it with: powershell.exe -ExecutionPolicy Bypass -File '
          f'.\\build\\{LAUNCHER_OUTPUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
