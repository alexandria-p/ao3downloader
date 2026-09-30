"""The app, for Windows and macOS: one double-click in place of Start-Application.ps1.

Built into the `ao3downloader` program by `package_app.py`. It does what the PowerShell
launcher does in a generated build - starts the local helper, serves the prebuilt page, and
points the browser at it - with Python and every dependency inside the program's folder, so
nothing has to be installed first.

Everything the app writes sits beside the program: `config/` (settings.ini, data.json) and
`logs/`. The library - where fics are saved - is still whichever folder the page opens.

The page is served at exactly `http://localhost:4200`, never another port: the Dropbox
sign-in returns to the page's own address, and that address has to be registered with the
Dropbox app. A page on 4201 could not sign in to Dropbox.

On a Mac the browser matters more than on Windows. The page opens a folder through the File
System Access API, which Chromium has and Safari and Firefox do not - and Safari is what a Mac
opens by default. So there the app asks for Chrome, or another Chromium browser, by name
(`MAC_BROWSERS`), and only falls back to the default browser when none is installed; the page
then says why it cannot open a folder.
"""

import functools
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from source_code import server, strings, updater as updates

PAGE_HOST = '127.0.0.1'
PAGE_PORT = 4200
# what the browser is sent to. localhost, not 127.0.0.1: it is the address the Dropbox app
# has registered, and the two are different origins to a browser
PAGE_URL = f'http://localhost:{PAGE_PORT}/'
# what the window tells people to open, for when the browser does not open by itself - or
# they closed it, or want a different one
OPEN_THIS = f'open any web browser to http://localhost:{PAGE_PORT}'
# on a Mac the default browser is Safari, which cannot open a folder for the page
OPEN_THIS_ON_A_MAC = (f'open Chrome to http://localhost:{PAGE_PORT} - not Safari or Firefox, '
                      'which cannot open a folder to save your fics in')
# asked for by name on a Mac, first installed wins: each can open a folder for the page
MAC_BROWSERS = ('Google Chrome', 'Microsoft Edge', 'Brave Browser', 'Arc', 'Opera')

CONFIG_FOLDER = 'config'
LOG_FOLDER = 'logs'
WEB_FOLDER = 'web'
# the settings this build was made with, inside the app's own files (package_app.py)
DEFAULTS_FOLDER = 'defaults'

# set to anything to start without opening a browser - for the build's own smoke test
ENV_NO_BROWSER = 'AO3DOWNLOADER_NO_BROWSER'

# how long to wait for the helper to answer before opening the browser anyway
HELPER_WAIT_SECONDS = 15


def app_folder() -> str:
    """The folder the program is in - or, run as plain python, the current folder."""

    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.getcwd())


def web_folder() -> str:
    """The prebuilt page. Packed inside the exe's own files, not beside it: nothing in it is
    for the user to change."""

    bundled = getattr(sys, '_MEIPASS', None)
    return os.path.join(bundled or app_folder(), WEB_FOLDER)


def defaults_file() -> str:
    """The settings.ini this build was made with - its deployment's - packed inside it."""

    bundled = getattr(sys, '_MEIPASS', None)
    return os.path.join(bundled or app_folder(), DEFAULTS_FOLDER, strings.INI_FILE_NAME)


def settings_up_to_date(root: str) -> None:
    """Create config/settings.ini from this build's settings the first time, and bring it up
    to date every time after: a setting this version added is appended with this build's
    value, one it dropped is commented out and marked deprecated, and nothing the user set is
    changed. The zip holds no config/ at all, so an update - from the button or unzipped by
    hand - can never replace the file itself; this is how it catches up instead.

    Run as plain python there are no packed defaults, and the helper completes the file from
    the package's own template when it starts, as it always has.
    """

    defaults = defaults_file()
    if not os.path.isfile(defaults): return
    with open(defaults, encoding='utf-8') as f:
        template = f.read()
    server.bring_settings_up_to_date(os.path.join(root, CONFIG_FOLDER, strings.INI_FILE_NAME),
                                     template)


def build_info(web: str) -> tuple[str, str]:
    """This build's version and the repository its releases come from, read from the page's
    own config - so the helper and the page can never disagree about what this is."""

    try:
        with open(os.path.join(web, 'app-config.json'), encoding='utf-8') as f:
            config = json.load(f)
    except (OSError, ValueError):
        return '', ''
    return str(config.get('version') or ''), str(config.get('releasesRepo') or '')


def make_updater(root: str, web: str) -> 'updates.Updater | None':
    """An updater for this app, when it can update itself: the packaged app on Windows or a Mac
    (only a packaged app is a folder to swap), built with a version and a repository to look for
    a newer one in."""

    kind = updates.kind_for()
    if not kind or not getattr(sys, 'frozen', False): return None
    version, repository = build_info(web)
    if not version or not repository: return None
    return updates.Updater(root, version, repository, kind=kind)


def restarted_by_update(root: str) -> bool:
    """Whether a Mac update's swap just started this app - it leaves a marker, since a window
    opened in Terminal gets none of its environment. Read once and removed: the page is still
    open and reloads itself, so no second tab, this time only."""

    marker = os.path.join(root, updates.UPDATE_FOLDER, updates.RESTARTED_MARKER)
    if not os.path.exists(marker): return False
    try:
        os.remove(marker)
    except OSError:
        pass
    return True


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


def where_to_go(platform: str | None = None) -> str:
    """What the window tells people to open."""

    return OPEN_THIS_ON_A_MAC if (platform or sys.platform) == 'darwin' else OPEN_THIS


def open_page(platform: str | None = None, run=subprocess.run) -> None:
    """Point a browser at the page - on a Mac, one that can open a folder for it."""

    if os.environ.get(ENV_NO_BROWSER): return
    if (platform or sys.platform) == 'darwin':
        for browser in MAC_BROWSERS:
            try:
                # `open -a` fails when there is no such application installed
                if run(['open', '-a', browser, PAGE_URL], capture_output=True).returncode == 0:
                    return
            except OSError:
                break
    webbrowser.open(PAGE_URL)


def open_browser_when_ready(port: int) -> None:
    """Open the page once the helper answers, so the first thing it does - asking the helper
    for its settings - does not fail. Opened anyway after a while: the page can still browse
    a library without the helper."""

    deadline = time.monotonic() + HELPER_WAIT_SECONDS
    while time.monotonic() < deadline and not server.already_listening(server.HOST, port):
        time.sleep(0.25)
    print()
    print(where_to_go())
    print()
    open_page()


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
    if restarted_by_update(root): os.environ[ENV_NO_BROWSER] = '1'
    settings_up_to_date(root)
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
        print(where_to_go())
        open_page()
        return stop('if the page does not work, close every ao3downloader window and start it again.')

    server.Handler.updater = make_updater(root, web)
    if server.Handler.updater and server.Handler.updater.state.get('state') == 'failed':
        print(f"the last update did not finish: {server.Handler.updater.state.get('error')}")
        print(f'this is still version {server.Handler.updater.version}. the log is in '
              f'{os.path.join(root, updates.UPDATE_FOLDER, updates.LOG_NAME)}')
        print()

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
