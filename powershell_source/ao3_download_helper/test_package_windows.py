"""The Windows app's packaging - everything but running PyInstaller itself, which the
`build windows app` workflow does on Windows and then starts the app it built."""

import zipfile
from pathlib import Path

import build_artifacts
import package_windows


# region what PyInstaller is asked for

def test_the_app_is_a_folder_with_a_console_window():
    arguments = package_windows.pyinstaller_arguments(Path('root'), Path('web'))

    # a folder, not one self-unpacking file; and a window the helper can talk in
    assert '--onedir' in arguments and '--onefile' not in arguments
    assert '--console' in arguments
    assert arguments[arguments.index('--name') + 1] == 'ao3downloader'


def test_the_settings_template_and_the_page_are_packed_in():
    root = Path('root')
    arguments = package_windows.pyinstaller_arguments(root, Path('staged') / 'web')
    data = [arguments[i + 1] for i, a in enumerate(arguments) if a == '--add-data']

    settings = root / build_artifacts.PYTHON_HOME / 'source_code' / 'settings'
    # read through importlib.resources, which PyInstaller cannot see on its own
    assert f'{settings}:source_code/settings' in data
    assert f'{Path("staged") / "web"}:web' in data


def test_the_entry_point_is_the_desktop_module():
    arguments = package_windows.pyinstaller_arguments(Path('root'), Path('web'))

    assert arguments[0] == str(Path('root') / build_artifacts.PYTHON_HOME / 'source_code' / 'desktop.py')
    assert (Path(__file__).parent / 'source_code' / 'desktop.py').is_file()

# endregion


# region what goes beside the exe

def staged(tmp_path: Path) -> Path:
    staging = tmp_path / 'staging'
    (staging / 'config').mkdir(parents=True)
    (staging / 'config' / 'settings.ini').write_text('[settings]\nExtraWaitTime=5\n', encoding='utf-8')
    (tmp_path / 'dist' / 'ao3downloader').mkdir(parents=True)
    return staging


def test_settings_and_a_readme_go_beside_the_exe(tmp_path):
    app = package_windows.assemble(tmp_path, staged(tmp_path))

    assert (app / 'config' / 'settings.ini').read_text(encoding='utf-8') == '[settings]\nExtraWaitTime=5\n'
    # notepad on an older Windows shows a file with bare newlines as one long line
    assert b'\r\n' in (app / 'README.txt').read_bytes()
    assert 'Run anyway' in (app / 'README.txt').read_text(encoding='utf-8')


def test_the_zip_unzips_into_one_folder(tmp_path):
    app = package_windows.assemble(tmp_path, staged(tmp_path))
    (app / '_internal').mkdir()
    (app / '_internal' / 'python.dll').write_bytes(b'x')

    archive = package_windows.make_zip(app, tmp_path / 'app.zip')

    names = zipfile.ZipFile(archive).namelist()
    assert all(name.startswith('ao3downloader/') for name in names)
    assert 'ao3downloader/_internal/python.dll' in names
    assert 'ao3downloader/config/settings.ini' in names


def test_the_zip_is_named_for_the_system_it_was_built_on(monkeypatch):
    monkeypatch.setattr(package_windows.sys, 'platform', 'win32')
    assert package_windows.zip_name() == 'ao3downloader-windows.zip'
    monkeypatch.setattr(package_windows.sys, 'platform', 'linux')
    assert package_windows.zip_name() == 'ao3downloader-linux.zip'

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

    web = package_windows.stage_web(root, staging, skip_web=True, settings=given)

    assert 'ExtraWaitTime=30' in (staging / 'config' / 'settings.ini').read_text(encoding='utf-8')
    assert '"helperUrl": "http://127.0.0.1:4400"' in (web / 'app-config.json').read_text(encoding='utf-8')

# endregion
