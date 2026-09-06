"""Tests for build_artifacts.py — assembling the deployable bundle.

These live next to the code they cover rather than in test/, because everything involved
in producing the bundle belongs together.
"""

import importlib.util
import json
from pathlib import Path

import pytest


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
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'settings' / 'settings.ini').write_text(
        '[settings]\nDownloadFolder=downloads\n', encoding='utf-8')
    # should not be copied into the bundle
    (package / '__pycache__').mkdir()
    (package / '__pycache__' / 'junk.pyc').write_text('x', encoding='utf-8')

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


def test_build_copies_pyproject_unchanged(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    source = (fake_root / build_artifacts.PYTHON_HOME / 'pyproject.toml').read_text(encoding='utf-8')
    shipped = (helper_dir(fake_root) / 'pyproject.toml').read_text(encoding='utf-8')
    assert shipped == source

# endregion


# region config

def test_build_seeds_config_in_its_own_folder(fake_root):
    result = build_artifacts.build(fake_root, skip_web=True)

    assert 'DownloadFolder' in (config_dir(fake_root) / 'settings.ini').read_text(encoding='utf-8')
    assert json.loads((config_dir(fake_root) / 'data.json').read_text(encoding='utf-8')) == {}
    assert sorted(result['config_created']) == ['data.json', 'settings.ini']
    # and not at the top level, where an older bundle put them
    assert not (bundle(fake_root) / 'settings.ini').exists()


def test_build_does_not_overwrite_config_that_is_already_there(fake_root):
    # a rebuild must not throw away the download folder or the saved username
    build_artifacts.build(fake_root, skip_web=True)
    settings = config_dir(fake_root) / 'settings.ini'
    data = config_dir(fake_root) / 'data.json'
    settings.write_text('[settings]\nDownloadFolder=D:\\fic\n', encoding='utf-8')
    data.write_text('{"username": "Someone"}', encoding='utf-8')

    result = build_artifacts.build(fake_root, skip_web=True)

    assert 'D:\\fic' in settings.read_text(encoding='utf-8')
    assert json.loads(data.read_text(encoding='utf-8'))['username'] == 'Someone'
    assert result['config_created'] == []

# endregion


# region rebuilds

def test_build_writes_a_readme_explaining_how_to_run_it(fake_root):
    build_artifacts.build(fake_root, skip_web=True)

    readme = (bundle(fake_root) / 'README.md').read_text(encoding='utf-8')
    assert build_artifacts.LAUNCHER_OUTPUT in readme
    assert 'localhost:4200' in readme


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
