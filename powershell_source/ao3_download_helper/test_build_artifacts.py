"""Tests for build_artifacts.py — assembling the deployable bundle.

These live next to the code they cover rather than in test/, because everything involved
in producing the bundle belongs together.
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from source_code import strings


# this folder is a set of scripts rather than a package, so load the module by path
MODULE_PATH = Path(__file__).resolve().parent / 'build_artifacts.py'
_spec = importlib.util.spec_from_file_location('build_artifacts', MODULE_PATH)
build_artifacts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_artifacts)


LAUNCHER = f"""param([int] $Port = 4200)

{build_artifacts.DOT_SOURCE}

Write-Step 'starting'
"""

SHARED = """function Write-Step($message) {
    Write-Host $message
}
"""

PYPROJECT = f"""[project]
name = "ao3downloader"
version = "1.0.0"
{build_artifacts.README_FIELD}

[tool.hatch.build.targets.wheel]
packages = ["source_code"]
"""

SETTINGS_TEMPLATE = """[settings]

# how long to wait between requests
ExtraWaitTime=0

# set this to 'true' to save your password in the settings file
# so that you do not have to enter it every time.
SavePassword=false

# where downloads are saved
DownloadFolder=downloads
"""


def write_module(package: Path, relative: str, imports: list[str]) -> None:
    """A stand-in module that imports the ones named, so the walk has something to follow."""

    path = package / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(imports) + '\n', encoding='utf-8')


@pytest.fixture
def fake_root(tmp_path) -> Path:
    """A working copy with just enough in it to build a bundle."""
    (tmp_path / build_artifacts.LAUNCHER_SOURCE).write_text(LAUNCHER, encoding='utf-8')

    # PYTHON_HOME is nested, so the intermediate folders have to be created too
    python_home = tmp_path / build_artifacts.PYTHON_HOME
    python_home.mkdir(parents=True)
    (python_home / 'ao3-env.ps1').write_text(SHARED, encoding='utf-8')

    package = python_home / build_artifacts.PACKAGE_NAME
    (package / 'settings').mkdir(parents=True)
    (package / 'actions').mkdir(parents=True)
    (package / 'html').mkdir(parents=True)
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'actions' / '__init__.py').write_text('', encoding='utf-8')
    (package / 'settings' / 'settings.ini').write_text(SETTINGS_TEMPLATE, encoding='utf-8')
    # only the console's log visualisation reads this, so the bundle has no use for it
    (package / 'html' / 'template.html').write_text('<html></html>', encoding='utf-8')

    # a package shaped like the real one: the helper at the top of a chain of imports, and
    # the console menu off to one side where nothing the helper does can reach it
    write_module(package, 'server.py', [
        'from source_code import strings',
        'from source_code.ao3 import Ao3',
        'from source_code.actions import shared',
    ])
    write_module(package, 'ao3.py', ['from source_code import parse_text, strings'])
    write_module(package, 'parse_text.py', [])
    write_module(package, 'strings.py', [])
    write_module(package, os.path.join('actions', 'shared.py'), ['from source_code import strings'])
    # reachable only from the console menu
    write_module(package, 'main.py', ['from source_code.actions import updatefics'])
    write_module(package, os.path.join('actions', 'updatefics.py'), ['from source_code import update'])
    write_module(package, 'update.py', ['from source_code import parse_pdf'])
    write_module(package, 'parse_pdf.py', [])

    # should not be copied into the bundle
    (package / '__pycache__').mkdir()
    (package / '__pycache__' / 'junk.pyc').write_text('x', encoding='utf-8')

    (python_home / 'pyproject.toml').write_text(PYPROJECT, encoding='utf-8')
    (python_home / 'README.md').write_text('# helper\n', encoding='utf-8')
    for name in build_artifacts.PROJECT_FILES:
        (python_home / name).write_text(f'# {name}\n', encoding='utf-8')

    return tmp_path


def bundle(root: Path) -> Path:
    return root / 'build'


def helper_dir(root: Path) -> Path:
    return bundle(root) / build_artifacts.HELPER_FOLDER


def config_dir(root: Path) -> Path:
    return bundle(root) / build_artifacts.CONFIG_FOLDER


# region generate_launcher

def test_generate_launcher_inlines_the_shared_functions():
    result = build_artifacts.generate_launcher(LAUNCHER, SHARED)

    assert 'function Write-Step' in result
    # nothing left to dot-source, since ao3-env.ps1 is not shipped
    assert build_artifacts.DOT_SOURCE not in result
    assert "ao3-env.ps1'" not in result


def test_generate_launcher_keeps_the_rest_of_the_script():
    result = build_artifacts.generate_launcher(LAUNCHER, SHARED)

    assert 'param([int] $Port = 4200)' in result
    assert "Write-Step 'starting'" in result


def test_generate_launcher_says_so_when_the_marker_has_moved():
    # a silent miss would ship a launcher that dies with "Get-Ao3Root is not recognised"
    with pytest.raises(ValueError, match='dot-source'):
        build_artifacts.generate_launcher('param()\nWrite-Host hello\n', SHARED)

# endregion


# region layout

def test_build_writes_the_launcher_under_its_shipped_name(fake_root):
    result = build_artifacts.build(fake_root, skip_web=True)

    shipped = bundle(fake_root) / build_artifacts.LAUNCHER_OUTPUT
    assert shipped.exists()
    assert result['launcher'] == shipped
    # the development launcher keeps its own name and is not shipped
    assert not (bundle(fake_root) / build_artifacts.LAUNCHER_SOURCE).exists()


def test_build_ships_a_self_contained_launcher(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    shipped = (bundle(fake_root) / build_artifacts.LAUNCHER_OUTPUT).read_text(encoding='utf-8')

    assert 'function Write-Step' in shipped
    assert build_artifacts.DOT_SOURCE not in shipped


def test_build_mirrors_the_working_copy_layout(fake_root):
    # the bundle puts the python in ao3_download_helper, exactly as powershell_source does,
    # which is what lets pyproject.toml be copied without rewriting
    build_artifacts.build(fake_root, skip_web=True)

    assert (helper_dir(fake_root) / build_artifacts.PACKAGE_NAME).is_dir()
    for name in build_artifacts.PROJECT_FILES:
        assert (helper_dir(fake_root) / name).exists(), name


def test_build_copies_the_package_without_bytecode(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    package = helper_dir(fake_root) / build_artifacts.PACKAGE_NAME
    assert (package / '__init__.py').exists()
    assert not (package / '__pycache__').exists()


def test_build_ships_no_readme_beside_the_package(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    assert not (helper_dir(fake_root) / 'README.md').exists()


def test_build_removes_a_readme_left_by_an_earlier_build(fake_root):
    build_artifacts.build(fake_root, skip_web=True)
    (helper_dir(fake_root) / 'README.md').write_text('# stale\n', encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert not (helper_dir(fake_root) / 'README.md').exists()


def test_build_drops_the_readme_field_from_pyproject(fake_root):
    # hatchling refuses to build when readme names a file the bundle does not ship
    build_artifacts.build(fake_root, skip_web=True)

    shipped = (helper_dir(fake_root) / 'pyproject.toml').read_text(encoding='utf-8')
    assert 'readme' not in shipped
    # the rest of the metadata is untouched
    assert 'name = "ao3downloader"' in shipped
    assert 'packages = ["source_code"]' in shipped


def test_build_says_so_when_the_readme_field_changes_shape(fake_root):
    (fake_root / build_artifacts.PYTHON_HOME / 'pyproject.toml').write_text(
        '[project]\nname = "ao3downloader"\nreadme = {file = "README.md"}\n', encoding='utf-8')

    with pytest.raises(ValueError, match='README_FIELD'):
        build_artifacts.build(fake_root, skip_web=True)


def test_strip_readme_field_leaves_a_pyproject_without_one_alone():
    content = '[project]\nname = "x"\n'

    assert build_artifacts.strip_readme_field(content) == content

# endregion


# region config

def test_build_leaves_the_password_setting_out(fake_root):
    # the web ui logs in each time and never stores a password
    build_artifacts.build(fake_root, skip_web=True)

    settings = (config_dir(fake_root) / 'settings.ini').read_text(encoding='utf-8')
    assert build_artifacts.SAVE_PASSWORD_KEY not in settings
    # and takes the explanation with it rather than leaving it dangling
    assert 'save your password in the settings file' not in settings
    # everything else survives
    assert 'ExtraWaitTime=0' in settings
    assert 'DownloadFolder=downloads' in settings


def test_strip_setting_keeps_a_file_that_does_not_have_it():
    content = '[settings]\n\n# a comment\nOther=1\n'

    assert build_artifacts.strip_setting(content, 'SavePassword') == content


def test_build_seeds_config_in_its_own_folder(fake_root):
    result = build_artifacts.build(fake_root, skip_web=True)

    assert 'ExtraWaitTime' in (config_dir(fake_root) / 'settings.ini').read_text(encoding='utf-8')
    assert result['config_created'] == ['settings.ini']
    # and not at the top level, where an older bundle put them
    assert not (bundle(fake_root) / 'settings.ini').exists()


def test_build_does_not_ship_data_json(fake_root):
    # the web ui keeps the username in the browser and never stores a password, so the
    # application creates this itself if it ever needs one
    build_artifacts.build(fake_root, skip_web=True)

    assert not (config_dir(fake_root) / 'data.json').exists()


def test_build_removes_a_data_json_left_by_an_earlier_build(fake_root):
    build_artifacts.build(fake_root, skip_web=True)
    (config_dir(fake_root) / 'data.json').write_text('{"username": "Someone"}', encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert not (config_dir(fake_root) / 'data.json').exists()


def test_build_does_not_overwrite_config_that_is_already_there(fake_root):
    # a rebuild must not throw away the download folder
    build_artifacts.build(fake_root, skip_web=True)
    settings = config_dir(fake_root) / 'settings.ini'
    settings.write_text('[settings]\nDownloadFolder=D:\\fic\n', encoding='utf-8')

    result = build_artifacts.build(fake_root, skip_web=True)

    assert 'D:\\fic' in settings.read_text(encoding='utf-8')
    assert result['config_created'] == []

# endregion


# region rebuilds

def test_build_writes_a_readme_explaining_how_to_run_it(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    readme = (bundle(fake_root) / 'README.md').read_text(encoding='utf-8')
    assert build_artifacts.LAUNCHER_OUTPUT in readme
    assert 'localhost:4200' in readme


def test_build_documents_the_file_layout_and_naming_every_time(fake_root):
    # the bundle travels on its own, so whoever receives it has only this readme to
    # tell them how downloaded files are named and how to bring their own files in
    build_artifacts.build(fake_root, skip_web=True)

    readme = (bundle(fake_root) / 'README.md').read_text(encoding='utf-8')
    # every folder a library is set up with, works/ included
    for folder in strings.LIBRARY_FOLDER_NAMES:
        assert f'`{folder}/`' in readme, folder
    # and that the page holds the library, which is why it has to stay open
    assert 'keep the page open while a run is going' in readme
    # the naming is fixed rather than a setting, so the readme has to state it outright
    assert strings.FILE_NAME_PATTERN in readme
    assert strings.DATE_STAMP_PLACEHOLDER in readme
    assert strings.INI_NAME_LENGTH in readme
    assert 'work number has to come first' in readme
    assert '"work_ids"' in readme


def test_build_does_not_offer_a_file_name_pattern_setting(fake_root):
    # it was removed: the work number has to lead and the date has to trail, so letting it
    # be rearranged only breaks the matching and the version check
    build_artifacts.build(fake_root, skip_web=True)

    readme = (bundle(fake_root) / 'README.md').read_text(encoding='utf-8')
    assert 'FileNamePattern' not in readme


def test_build_replaces_a_stale_package_copy(fake_root):
    build_artifacts.build(fake_root, skip_web=True)
    stale = helper_dir(fake_root) / build_artifacts.PACKAGE_NAME / 'removed_since.py'
    stale.write_text('# gone in the next build\n', encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert not stale.exists()


def test_build_clears_what_an_older_layout_left_behind(fake_root):
    # earlier bundles put these at the top level; two copies would be worse than none
    older = bundle(fake_root)
    older.mkdir()
    (older / 'download_helper_scripts').mkdir()
    (older / 'pyproject.toml').write_text('# old\n', encoding='utf-8')
    (older / 'run-gui.ps1').write_text('# old\n', encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert not (older / 'download_helper_scripts').exists()
    assert not (older / 'pyproject.toml').exists()
    assert not (older / 'run-gui.ps1').exists()


def test_build_leaves_the_web_folder_alone_when_skipping_it(fake_root):
    web = bundle(fake_root) / build_artifacts.WEB_FOLDER
    web.mkdir(parents=True)
    (web / 'index.html').write_text('<html></html>', encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert (web / 'index.html').exists()

# endregion


# region shipping only what the helper imports

def shipped(root: Path) -> set[str]:
    """Every file under the bundled package, as posix-style relative paths."""

    package = helper_dir(root) / build_artifacts.PACKAGE_NAME
    return {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}


def test_the_bundle_ships_what_the_helper_imports(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    files = shipped(fake_root)
    for name in ('server.py', 'ao3.py', 'parse_text.py', 'strings.py', 'actions/shared.py'):
        assert name in files, name


def test_the_bundle_leaves_behind_what_only_the_console_reaches(fake_root):
    # the console menu, and the ebook parsing only it uses, are not invokable from the ui
    build_artifacts.build(fake_root, skip_web=True)

    files = shipped(fake_root)
    for name in ('main.py', 'update.py', 'parse_pdf.py', 'actions/updatefics.py'):
        assert name not in files, name


def test_a_package_that_is_kept_still_gets_its_init(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    files = shipped(fake_root)
    assert '__init__.py' in files
    assert 'actions/__init__.py' in files


def test_the_settings_template_is_shipped_even_though_nothing_imports_it(fake_root):
    # fileio reads it through importlib.resources, which no import graph can see
    build_artifacts.build(fake_root, skip_web=True)

    assert 'settings/settings.ini' in shipped(fake_root)


def test_data_only_the_console_reads_is_left_behind(fake_root):
    # the log visualisation template is the console's, not the helper's
    build_artifacts.build(fake_root, skip_web=True)

    assert 'html/template.html' not in shipped(fake_root)


def test_the_build_says_what_it_left_behind(fake_root):
    # a module quietly dropping out of the bundle should be visible at build time
    result = build_artifacts.build(fake_root, skip_web=True)

    assert 'source_code.main' in result['left_behind']
    assert 'source_code.server' not in result['left_behind']


def test_a_module_the_helper_starts_importing_is_shipped_without_being_listed(fake_root):
    # the whole reason this follows imports rather than keeping a list
    package = fake_root / build_artifacts.PYTHON_HOME / build_artifacts.PACKAGE_NAME
    write_module(package, 'newly_needed.py', [])
    (package / 'server.py').write_text(
        'from source_code import strings\nfrom source_code import newly_needed\n',
        encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert 'newly_needed.py' in shipped(fake_root)


def test_nothing_is_shipped_from_a_package_with_no_helper_in_it(fake_root):
    package = fake_root / build_artifacts.PYTHON_HOME / build_artifacts.PACKAGE_NAME
    (package / 'server.py').unlink()

    with pytest.raises(FileNotFoundError, match=build_artifacts.HELPER_ENTRY):
        build_artifacts.build(fake_root, skip_web=True)


def test_a_rebuild_drops_a_module_that_is_no_longer_reached(fake_root):
    build_artifacts.build(fake_root, skip_web=True)
    assert 'actions/shared.py' in shipped(fake_root)

    package = fake_root / build_artifacts.PYTHON_HOME / build_artifacts.PACKAGE_NAME
    (package / 'server.py').write_text('from source_code import strings\n', encoding='utf-8')

    build_artifacts.build(fake_root, skip_web=True)

    assert 'actions/shared.py' not in shipped(fake_root)

# endregion
