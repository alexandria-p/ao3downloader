"""EnableConsoleLogging: requests and run output printed to the helper's own console."""

import contextlib
import io
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from source_code import access, server, strings


PASSCODE = 'a long passcode'


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """Write a settings.ini the helper will read, from a dict of its values."""

    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    monkeypatch.delenv(access.ENV_PASSCODE, raising=False)
    monkeypatch.delenv(access.ENV_PRIVATE_KEY, raising=False)

    def write(**values):
        lines = ['[settings]'] + [f'{k}={v}' for k, v in values.items()]
        (tmp_path / strings.INI_FILE_NAME).write_text('\n'.join(lines), encoding='utf-8')

    write()
    return write


@pytest.fixture
def console(monkeypatch):
    """The real console, standing in for sys.__stdout__."""

    captured = io.StringIO()
    monkeypatch.setattr(sys, '__stdout__', captured)
    return captured


@pytest.fixture
def live():
    httpd = ThreadingHTTPServer((server.HOST, 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://{server.HOST}:{httpd.server_address[1]}'
    finally:
        httpd.shutdown()
        httpd.server_close()


def ask(base, path, headers=None):
    request = urllib.request.Request(base + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


# region requests

def test_requests_are_not_printed_unless_it_is_turned_on(live, settings, console):
    ask(live, '/api/jobs')
    assert console.getvalue() == ''


def test_each_request_is_printed_with_its_method_path_and_answer(live, settings, console):
    settings(EnableConsoleLogging='true')

    ask(live, '/api/jobs')
    ask(live, '/no/such/path')

    said = console.getvalue()
    assert '[request] GET /api/jobs 200' in said
    assert '[request] GET /no/such/path 404' in said


def test_a_request_turned_away_by_the_passcode_is_printed_too(live, settings, console,
                                                             monkeypatch):
    # so strangers probing a hosted helper show up in the host's log
    settings(EnableConsoleLogging='true', RequirePasscode='true')
    monkeypatch.setenv(access.ENV_PASSCODE, PASSCODE)

    ask(live, '/api/config')

    assert '[request] GET /api/config 404' in console.getvalue()


def test_the_passcode_is_never_printed(live, settings, console, monkeypatch):
    settings(EnableConsoleLogging='true', RequirePasscode='true')
    monkeypatch.setenv(access.ENV_PASSCODE, PASSCODE)

    assert ask(live, '/api/auth', {'Authorization': f'Bearer {PASSCODE}'}) == 200

    said = console.getvalue()
    assert '[request] GET /api/auth 200' in said
    assert PASSCODE not in said


def test_a_request_during_a_run_still_reaches_the_console(live, settings, console):
    # a run redirects stdout into its messages to the page, for the whole process
    settings(EnableConsoleLogging='true')
    to_page = io.StringIO()

    with contextlib.redirect_stdout(to_page):
        ask(live, '/api/jobs')

    assert '[request] GET /api/jobs 200' in console.getvalue()
    assert to_page.getvalue() == ''

# endregion


# region what a run says

def a_job() -> server.Job:
    return server.Job(server.ACTION_SYNC, ['JSON'], 'Someone', server.resolve_options({}))


def run_saying(job, lines):
    """Run a job whose whole run is printing `lines`, and return what it sent the page."""

    def a_run(job, *args, **kwargs):
        for line in lines: print(line)

    sent = []
    with patch.object(job, 'emit', side_effect=sent.append), \
         patch.object(server, 'Repository'), \
         patch.object(server, 'FileOps'), \
         patch.object(server, 'runners', return_value={job.action: a_run}):
        try:
            server.run_job(job, 'a-password')
        except Exception:
            pass # whatever the stubs make of the rest of the run is not what is under test
    return [e['text'] for e in sent if e.get('type') == 'message']


def test_what_a_run_says_is_echoed_to_the_console_tagged_with_the_run(settings, console):
    settings(EnableConsoleLogging='true')
    job = a_job()

    with patch.object(server, 'console_logging', return_value=True):
        run_saying(job, ['fetching page 1', 'new download: 123 A Fic.html'])

    said = console.getvalue()
    assert f'[run {job.id[:8]}] fetching page 1' in said
    assert f'[run {job.id[:8]}] new download: 123 A Fic.html' in said


def test_the_page_still_gets_every_line_when_the_console_does(settings, console):
    with patch.object(server, 'console_logging', return_value=True):
        to_page = run_saying(a_job(), ['fetching page 1'])

    assert 'fetching page 1' in to_page


def test_a_run_says_nothing_to_the_console_unless_it_is_turned_on(settings, console):
    with patch.object(server, 'console_logging', return_value=False):
        run_saying(a_job(), ['fetching page 1'])

    assert 'fetching page 1' not in console.getvalue()

# endregion


def test_the_setting_is_shown_back_with_the_others(settings):
    settings(EnableConsoleLogging='true')
    assert server.read_settings(server.FileOps())['consoleLogging'] is True


def test_the_helper_says_at_start_that_it_is_logging(settings, capsys):
    # so a host's log shows the setting took before any request arrives
    settings(EnableConsoleLogging='true')
    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer'):
        server.serve(port=4400)
    assert 'EnableConsoleLogging is on' in capsys.readouterr().out


def test_the_helper_does_not_fall_over_without_a_console(monkeypatch):
    # pythonw, or a host that closed it
    monkeypatch.setattr(sys, '__stdout__', None)
    server.to_console('anything')
