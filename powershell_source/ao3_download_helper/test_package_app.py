"""The app's packaging, for Windows and macOS - everything but running PyInstaller itself,
which the `build windows app` and `build mac app` workflows do on their own systems and then
start the app they built."""

import json
import os
import stat
import zipfile
from pathlib import Path

import build_artifacts
import package_app
import pytest


# region what PyInstaller is asked for

def test_the_app_is_a_folder_with_a_console_window():
    arguments = package_app.pyinstaller_arguments(Path('root'), Path('web'), Path('defaults'))

    # a folder, not one self-unpacking file; and a window the helper can talk in
    assert '--onedir' in arguments and '--onefile' not in arguments
    assert '--console' in arguments
    assert arguments[arguments.index('--name') + 1] == 'ao3downloader'


def test_the_settings_template_and_the_page_are_packed_in():
    root = Path('root')
    arguments = package_app.pyinstaller_arguments(root, Path('staged') / 'web', Path('staged') / 'config')
    data = [arguments[i + 1] for i, a in enumerate(arguments) if a == '--add-data']

    settings = root / build_artifacts.PYTHON_HOME / 'source_code' / 'settings'
    # read through importlib.resources, which PyInstaller cannot see on its own
    assert f'{settings}:source_code/settings' in data
    assert f'{Path("staged") / "web"}:web' in data
    # the deployment's settings, packed inside the app as the defaults it starts from
    assert f'{Path("staged") / "config"}:defaults' in data


def test_the_entry_point_is_the_desktop_module():
    arguments = package_app.pyinstaller_arguments(Path('root'), Path('web'), Path('defaults'))

    assert arguments[0] == str(Path('root') / build_artifacts.PYTHON_HOME / 'source_code' / 'desktop.py')
    assert (Path(__file__).parent / 'source_code' / 'desktop.py').is_file()

# endregion


# region what goes beside the exe

def app_folder(tmp_path: Path) -> Path:
    (tmp_path / 'dist' / 'ao3downloader').mkdir(parents=True)
    return tmp_path


def test_a_readme_goes_beside_the_exe(tmp_path):
    app = package_app.assemble(app_folder(tmp_path), 'win32')

    # notepad on an older Windows shows a file with bare newlines as one long line
    assert b'\r\n' in (app / 'README.txt').read_bytes()
    assert 'Run anyway' in (app / 'README.txt').read_text(encoding='utf-8')
    assert 'Update now' in (app / 'README.txt').read_text(encoding='utf-8')
    assert not (app / package_app.MAC_LAUNCHER).exists()


def test_on_a_mac_a_script_to_double_click_goes_beside_the_program(tmp_path):
    app = package_app.assemble(app_folder(tmp_path), 'darwin')

    launcher = app / package_app.MAC_LAUNCHER
    script = launcher.read_text(encoding='utf-8')
    assert script.startswith('#!/bin/bash\n')
    # a downloaded zip quarantines every file in it; the script lifts that off the folder, so
    # macOS asks once, about the script, and not about each library the program loads
    assert 'xattr -dr com.apple.quarantine .' in script
    assert 'exec ./ao3downloader' in script
    assert os.access(launcher, os.X_OK)
    assert b'\r' not in launcher.read_bytes()


def test_the_mac_readme_says_how_to_get_past_the_first_warning_and_which_browser_to_use(tmp_path):
    readme = (package_app.assemble(app_folder(tmp_path), 'darwin') / 'README.txt').read_text(encoding='utf-8')

    assert 'Open Anyway' in readme
    assert package_app.MAC_LAUNCHER in readme
    assert 'Chrome' in readme and 'Safari' in readme
    # no in-app updater on a Mac - the swap is a Windows script
    assert 'Update now' not in readme


def test_the_zip_unzips_into_one_folder_and_holds_no_settings(tmp_path):
    app = package_app.assemble(app_folder(tmp_path), 'win32')
    (app / '_internal' / 'defaults').mkdir(parents=True)
    (app / '_internal' / 'defaults' / 'settings.ini').write_text('[settings]\n', encoding='utf-8')
    (app / '_internal' / 'python.dll').write_bytes(b'x')

    archive = package_app.make_zip(app, tmp_path / 'app.zip')

    names = zipfile.ZipFile(archive).namelist()
    assert all(name.startswith('ao3downloader/') for name in names)
    assert 'ao3downloader/_internal/python.dll' in names
    # nothing in config/ - so unzipping an update over the app can never replace the
    # settings.ini someone has edited
    assert not any(name.startswith('ao3downloader/config/') for name in names)


def test_the_zip_is_named_for_the_system_it_was_built_on(monkeypatch):
    monkeypatch.setattr(package_app.sys, 'platform', 'win32')
    assert package_app.zip_name() == 'ao3downloader-windows.zip'
    monkeypatch.setattr(package_app.sys, 'platform', 'darwin')
    monkeypatch.setattr(package_app.machines, 'machine', lambda: 'arm64')
    assert package_app.zip_name() == 'ao3downloader-macos-apple-silicon.zip'
    monkeypatch.setattr(package_app.machines, 'machine', lambda: 'x86_64')
    assert package_app.zip_name() == 'ao3downloader-macos-intel.zip'
    monkeypatch.setattr(package_app.sys, 'platform', 'linux')
    assert package_app.zip_name() == 'ao3downloader-linux.zip'


def test_each_mac_readme_says_which_macs_it_is_for_and_where_the_other_one_is(tmp_path):
    silicon = (package_app.assemble(app_folder(tmp_path / 'one'), 'darwin', 'arm64') / 'README.txt').read_text(encoding='utf-8')
    assert 'Apple silicon (M1 or later)' in silicon.split('Starting it')[0]
    assert 'ao3downloader-macos-intel.zip' in silicon

    intel = (package_app.assemble(app_folder(tmp_path / 'two'), 'darwin', 'x86_64') / 'README.txt').read_text(encoding='utf-8')
    assert 'This is for Intel Macs' in intel
    assert 'ao3downloader-macos-apple-silicon.zip' in intel


def test_the_zip_keeps_the_program_executable(tmp_path):
    app = package_app.assemble(app_folder(tmp_path), 'darwin')
    program = app / 'ao3downloader'
    program.write_bytes(b'program')
    program.chmod(0o755)

    archive = zipfile.ZipFile(package_app.make_zip(app, tmp_path / 'app.zip'))

    for name in ('ao3downloader/ao3downloader', f'ao3downloader/{package_app.MAC_LAUNCHER}'):
        assert (archive.getinfo(name).external_attr >> 16) & 0o111


@pytest.mark.skipif(not hasattr(os, 'symlink') or os.name == 'nt', reason='symlinks')
def test_a_symlink_in_the_app_is_zipped_as_a_symlink_and_never_followed(tmp_path):
    # PyInstaller's Mac build links parts of its folder to each other. followed, a link to a
    # folder is left out altogether, and a link to a file becomes a second copy of it
    app = package_app.assemble(app_folder(tmp_path), 'darwin')
    (app / '_internal' / 'lib').mkdir(parents=True)
    (app / '_internal' / 'lib' / 'Python').write_bytes(b'python')
    os.symlink('lib/Python', app / '_internal' / 'Python')
    os.symlink('lib', app / '_internal' / 'Frameworks')

    archive = zipfile.ZipFile(package_app.make_zip(app, tmp_path / 'app.zip'))

    for name, target in (('ao3downloader/_internal/Python', 'lib/Python'),
                         ('ao3downloader/_internal/Frameworks', 'lib')):
        info = archive.getinfo(name)
        assert stat.S_ISLNK(info.external_attr >> 16)
        assert archive.read(name).decode() == target
    assert not any(n.startswith('ao3downloader/_internal/Frameworks/') for n in archive.namelist())

# endregion


# region the settings it ships

def test_a_given_settings_ini_is_shipped_and_the_page_is_pointed_by_it(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    python_home = root / build_artifacts.PYTHON_HOME
    (python_home / 'source_code' / 'settings').mkdir(parents=True)
    (python_home / 'source_code' / 'settings' / 'settings.ini').write_text(
        '[settings]\nExtraWaitTime=15\nHelperUrl=http://127.0.0.1:4400\n', encoding='utf-8')
    (root / 'build' / 'web').mkdir(parents=True)
    (root / 'build' / 'web' / 'index.html').write_text('', encoding='utf-8')
    given = tmp_path / 'windows-settings.ini'
    given.write_text('[settings]\nExtraWaitTime=30\nHelperUrl=http://127.0.0.1:4400\n', encoding='utf-8')
    staging = tmp_path / 'staging'

    web = package_app.stage_web(root, staging, skip_web=True, settings=given,
                                    version='1.8.3', repository='someone/ao3downloader')

    assert 'ExtraWaitTime=30' in (staging / 'config' / 'settings.ini').read_text(encoding='utf-8')
    config = json.loads((web / 'app-config.json').read_text(encoding='utf-8'))
    assert config['helperUrl'] == 'http://127.0.0.1:4400'
    # the page in the app knows what it is, so it can tell when a newer one is out
    assert config['version'] == '1.8.3'
    assert config['releasesRepo'] == 'someone/ao3downloader'

# endregion
