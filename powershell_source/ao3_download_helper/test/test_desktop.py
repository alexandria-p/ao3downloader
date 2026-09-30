"""The Windows app's entry point: where it keeps things, and what it says when it cannot
start. The packaged app itself is started by the `build windows app` workflow."""

import os
import sys
import threading
import urllib.request
from unittest.mock import MagicMock, patch

import pytest

from source_code import desktop, server, strings


@pytest.fixture(autouse=True)
def folders_put_back(monkeypatch):
    # the app sets these for the whole process; registered here so every test puts them back
    for name in (strings.ENV_CONFIG_FOLDER, strings.ENV_LOG_FOLDER):
        if name in os.environ: monkeypatch.setenv(name, os.environ[name])
        else: monkeypatch.delenv(name, raising=False)


# region where things are kept

def test_settings_and_logs_go_beside_the_exe(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'ao3downloader.exe'))

    desktop.use_folders(desktop.app_folder())

    assert os.environ[strings.ENV_CONFIG_FOLDER] == str(tmp_path / 'config')
    assert os.environ[strings.ENV_LOG_FOLDER] == str(tmp_path / 'logs')
    assert (tmp_path / 'config').is_dir() and (tmp_path / 'logs').is_dir()


def test_the_page_is_read_from_the_apps_own_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / '_internal'), raising=False)

    assert desktop.web_folder() == str(tmp_path / '_internal' / 'web')


def test_the_page_address_is_the_one_dropbox_knows():
    # the Dropbox sign-in returns to the page's own address, which the Dropbox app has to
    # have registered - localhost and 127.0.0.1 are different addresses to a browser
    assert desktop.PAGE_URL == 'http://localhost:4200/'

# endregion


# region serving the page

def test_the_page_is_served_without_a_line_per_file(tmp_path, monkeypatch, capsys):
    (tmp_path / 'index.html').write_text('<html>the page</html>', encoding='utf-8')
    monkeypatch.setattr(desktop, 'PAGE_PORT', 0)
    page = desktop.page_server(str(tmp_path))
    threading.Thread(target=page.serve_forever, daemon=True).start()
    try:
        port = page.server_address[1]
        body = urllib.request.urlopen(f'http://127.0.0.1:{port}/').read()
    finally:
        page.shutdown()
        page.server_close()

    assert body == b'<html>the page</html>'
    assert capsys.readouterr().err == ''

# endregion


# region when it cannot start, the window says why and stays open

def started(tmp_path, monkeypatch, busy=()):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'ao3downloader.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / '_internal'), raising=False)
    monkeypatch.setenv(desktop.ENV_NO_BROWSER, '1')
    held = MagicMock(return_value='')
    with patch('builtins.input', held), \
         patch.object(server, 'already_listening', side_effect=lambda host, port: port in busy), \
         patch.object(server, 'serve') as serve, \
         patch.object(desktop, 'page_server') as page:
        code = desktop.main()
    return code, held, serve, page


def web(tmp_path):
    (tmp_path / '_internal' / 'web').mkdir(parents=True)
    (tmp_path / '_internal' / 'web' / 'index.html').write_text('', encoding='utf-8')


def test_a_missing_page_is_said_and_the_window_held_open(tmp_path, monkeypatch, capsys):
    code, held, serve, _ = started(tmp_path, monkeypatch)

    assert code == 1
    assert held.called
    assert not serve.called
    assert 'the page is missing' in capsys.readouterr().out


def test_the_app_already_running_is_said_rather_than_starting_a_second_helper(tmp_path, monkeypatch, capsys):
    web(tmp_path)
    code, held, serve, page = started(tmp_path, monkeypatch, busy=(server.DEFAULT_PORT,))

    assert code == 1
    assert held.called
    # a second helper on the same port is the stale-helper trap CLAUDE.md describes
    assert not serve.called and not page.called
    out = capsys.readouterr().out
    assert 'running already' in out
    assert 'open any web browser to http://localhost:4200' in out


def test_a_helper_that_will_not_start_holds_the_window_open(tmp_path, monkeypatch):
    web(tmp_path)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'ao3downloader.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / '_internal'), raising=False)
    monkeypatch.setenv(desktop.ENV_NO_BROWSER, '1')
    held = MagicMock(return_value='')
    with patch('builtins.input', held), \
         patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'serve', side_effect=SystemExit(1)), \
         patch.object(desktop, 'page_server'):
        code = desktop.main()

    assert code == 1
    assert held.called


def test_starting_normally_runs_the_helper_on_its_usual_port(tmp_path, monkeypatch):
    web(tmp_path)
    code, held, serve, page = started(tmp_path, monkeypatch)

    assert code == 0
    assert not held.called
    serve.assert_called_once_with(port=server.DEFAULT_PORT)
    assert page.called

# endregion


# region what the window says once it is running

def test_the_window_says_where_to_point_a_browser_once_the_helper_answers(monkeypatch, capsys):
    monkeypatch.setenv(desktop.ENV_NO_BROWSER, '1')
    with patch.object(server, 'already_listening', return_value=True), \
         patch.object(desktop.webbrowser, 'open') as opened:
        desktop.open_browser_when_ready(server.DEFAULT_PORT)

    assert 'open any web browser to http://localhost:4200' in capsys.readouterr().out
    assert not opened.called


def test_the_browser_is_opened_there_too(monkeypatch):
    monkeypatch.delenv(desktop.ENV_NO_BROWSER, raising=False)
    with patch.object(server, 'already_listening', return_value=True), \
         patch.object(desktop.webbrowser, 'open') as opened:
        desktop.open_browser_when_ready(server.DEFAULT_PORT)

    opened.assert_called_once_with('http://localhost:4200/')

# endregion


# region settings.ini, kept and brought up to date

DEFAULTS = """[settings]

# seconds to wait after every request
ExtraWaitTime=15

# a setting a new version added
NewSetting=7
"""


def packed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / '_internal'), raising=False)
    (tmp_path / '_internal' / 'defaults').mkdir(parents=True)
    (tmp_path / '_internal' / 'defaults' / 'settings.ini').write_text(DEFAULTS, encoding='utf-8')


def test_the_first_start_writes_settings_from_the_builds_own(tmp_path, monkeypatch):
    packed(tmp_path, monkeypatch)

    desktop.settings_up_to_date(str(tmp_path))

    written = (tmp_path / 'config' / 'settings.ini').read_text(encoding='utf-8')
    assert 'ExtraWaitTime=15' in written and 'NewSetting=7' in written


def test_after_an_update_the_users_settings_stay_and_new_ones_arrive_with_the_builds_value(tmp_path, monkeypatch):
    packed(tmp_path, monkeypatch)
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'settings.ini').write_text(
        '[settings]\n# my own note\nExtraWaitTime=60\nRetiredSetting=3\n', encoding='utf-8')

    desktop.settings_up_to_date(str(tmp_path))

    written = (tmp_path / 'config' / 'settings.ini').read_text(encoding='utf-8')
    # theirs, exactly as they left it
    assert '# my own note\nExtraWaitTime=60\n' in written
    # the new one, with this build's value and its explanation
    assert '# a setting a new version added\nNewSetting=7' in written
    # the one this version dropped, commented out and said to be
    assert '# DEPRECATED: RetiredSetting' in written
    assert '# RetiredSetting=3' in written


def test_run_as_plain_python_it_leaves_settings_to_the_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'nothing-packed'), raising=False)

    desktop.settings_up_to_date(str(tmp_path))

    assert not (tmp_path / 'config' / 'settings.ini').exists()

# endregion
