"""The Windows app: one double-click in place of Start-Application.ps1.

Built into `ao3downloader.exe` by `package_windows.py`. It does what the PowerShell launcher
does in a generated build - starts the local helper, serves the prebuilt page, and points the
browser at it - with Python and every dependency inside the exe's folder, so nothing has to
be installed first.

Everything the app writes sits beside the exe: `config/` (settings.ini, data.json) and
`logs/`. The library - where fics are saved - is still whichever folder the page opens.

The page is served at exactly `http://localhost:4200`, never another port: the Dropbox
sign-in returns to the page's own address, and that address has to be registered with the
Dropbox app. A page on 4201 could not sign in to Dropbox.
"""

import functools
import os
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from source_code import server, strings

PAGE_HOST = '127.0.0.1'
PAGE_PORT = 4200
# what the browser is sent to. localhost, not 127.0.0.1: it is the address the Dropbox app
# has registered, and the two are different origins to a browser
PAGE_URL = f'http://localhost:{PAGE_PORT}/'
# what the window tells people to open, for when the browser does not open by itself - or
# they closed it, or want a different one
OPEN_THIS = f'open any web browser to http://localhost:{PAGE_PORT}'

CONFIG_FOLDER = 'config'
LOG_FOLDER = 'logs'
WEB_FOLDER = 'web'

# set to anything to start without opening a browser - for the build's own smoke test
ENV_NO_BROWSER = 'AO3DOWNLOADER_NO_BROWSER'

# how long to wait for the helper to answer before opening the browser anyway
HELPER_WAIT_SECONDS = 15


def app_folder() -> str:
    """The folder the exe is in - or, run as plain python, the current folder."""

    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.getcwd())


def web_folder() -> str:
    """The prebuilt page. Packed inside the exe's own files, not beside it: nothing in it is
    for the user to change."""

    bundled = getattr(sys, '_MEIPASS', None)
    return os.path.join(bundled or app_folder(), WEB_FOLDER)


def use_folders(root: str) -> None:
    """Keep settings and logs beside the exe, as a generated build keeps them beside its
    launcher - wherever the app is started from."""

    config = os.path.join(root, CONFIG_FOLDER)
    logs = os.path.join(root, LOG_FOLDER)
    os.makedirs(config, exist_ok=True)
    os.makedirs(logs, exist_ok=True)
    os.environ[strings.ENV_CONFIG_FOLDER] = config
    os.environ[strings.ENV_LOG_FOLDER] = logs


class QuietPage(SimpleHTTPRequestHandler):
    """Serves the page without a line per file - the window is for what the helper says."""

    def log_message(self, format, *args) -> None:
        pass


def page_server(folder: str) -> ThreadingHTTPServer:
    handler = functools.partial(QuietPage, directory=folder)
    return ThreadingHTTPServer((PAGE_HOST, PAGE_PORT), handler)


def open_browser_when_ready(port: int) -> None:
    """Open the page once the helper answers, so the first thing it does - asking the helper
    for its settings - does not fail. Opened anyway after a while: the page can still browse
    a library without the helper."""

    deadline = time.monotonic() + HELPER_WAIT_SECONDS
    while time.monotonic() < deadline and not server.already_listening(server.HOST, port):
        time.sleep(0.25)
    print()
    print(OPEN_THIS)
    print()
    if not os.environ.get(ENV_NO_BROWSER): webbrowser.open(PAGE_URL)


def stop(message: str) -> int:
    """Say what went wrong and hold the window open. A double-clicked console app that fails
    closes before anybody can read why."""

    print()
    print(message)
    try:
        input('\npress enter to close this window')
    except (EOFError, KeyboardInterrupt):
        pass
    return 1


def main() -> int:
    root = app_folder()
    use_folders(root)
    web = web_folder()
    port = int(os.environ.get(server.ENV_PORT) or server.DEFAULT_PORT)

    print('ao3downloader')
    print(f'settings and logs: {root}')
    print('leave this window open while you use the app.')
    print()

    if not os.path.isfile(os.path.join(web, 'index.html')):
        return stop(f'the page is missing from {web}. download the app again.')
    if server.already_listening(server.HOST, port) or server.already_listening(PAGE_HOST, PAGE_PORT):
        # almost always the app already running, in another window. opening the page is
        # what the person wanted, so do that rather than only complaining
        print('ao3downloader seems to be running already, in another window.')
        print(OPEN_THIS)
        if not os.environ.get(ENV_NO_BROWSER): webbrowser.open(PAGE_URL)
        return stop('if the page does not work, close every ao3downloader window and start it again.')

    try:
        page = page_server(web)
    except OSError as e:
        return stop(f'could not serve the page on {PAGE_URL}: {e}')
    threading.Thread(target=page.serve_forever, daemon=True).start()

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    try:
        # the helper runs here, in the foreground, as it does from the PowerShell launcher.
        # it reads settings.ini (writing it first if missing) and prints what it is doing
        server.serve(port=port)
    except SystemExit as e:
        if e.code not in (None, 0):
            return stop('the helper could not start - see above.')
    finally:
        page.shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
