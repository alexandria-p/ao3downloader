"""A local helper that lets the web ui run downloads.

A browser cannot reach ao3 (no CORS headers), cannot hold an ao3 login session, and cannot
read the ebook files on disk that the update scan needs. So the page asks this instead, and
this calls the same code the console menu calls.

It listens on the loopback interface only, so nothing outside this machine can reach it,
and it holds the ao3 password just long enough to log in - it is never written anywhere.
"""

import contextlib
import io
import json
import os
import queue
import socket
import threading
import traceback
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from source_code import parse_text, progress, strings, update
from source_code.actions import shared
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


HOST = '127.0.0.1'
DEFAULT_PORT = 4400

ACTION_BOOKMARKS = 'bookmarks'
ACTION_UPDATE = 'update'
ACTION_COLLECTIONS = 'collections'

ACTION_COLLECTION = 'collection'

ACTIONS = (ACTION_BOOKMARKS, ACTION_UPDATE, ACTION_COLLECTIONS, ACTION_COLLECTION)

# actions that need a link from the caller rather than working it out from the username
ACTIONS_NEEDING_URL = (ACTION_COLLECTION,)

# json is always produced, so the ui shows it ticked and locked. it is what the web page
# reads, and it costs nothing extra: the metadata comes off the listing page that has to be
# fetched anyway, rather than one request per work.
FORCED_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA]

# ticked when the dialog opens, but free to untick. html is here rather than above because
# it costs a request per work on top of the indexing, so a metadata-only refresh - which is
# a great deal lighter on the rate limit - has to be possible.
DEFAULT_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML']


def resolve_filetypes(requested) -> list[str]:
    """Keep the recognised types the caller asked for, and add the ones we always produce.

    The ui shows the forced types ticked and locked, but a request is not to be trusted to
    have honoured that, so they are re-added here.
    """

    filetypes: list[str] = []
    for filetype in (requested or []):
        # a repeat would download the same work twice, for nothing but rate limit
        if filetype in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA \
                and filetype not in filetypes:
            filetypes.append(filetype)
    for forced in FORCED_FILETYPES:
        if forced not in filetypes: filetypes.append(forced)
    return filetypes


def resolve_options(requested) -> dict:
    """The questions the console menu asks after the file types, with the same defaults.

    'pages' is the page to stop on, where 0 means all of them - the wording the console
    uses. Ao3 wants None for that, which is done at the point of use.
    """

    given = requested or {}

    try:
        pages = int(given.get('pages') or 0)
    except (TypeError, ValueError):
        pages = 0
    if pages < 0: pages = 0

    try:
        start = int(given.get('start') or 1)
    except (TypeError, ValueError):
        start = 1
    if start < 1: start = 1
    # a stop before the start would fetch nothing at all; treat it as no stop instead
    if pages and pages < start: pages = 0

    return {
        'start': start,
        'pages': pages,
        'series': bool(given.get('series')),
        'images': bool(given.get('images')),
        'workdates': bool(given.get('workdates')),
        # fetch again the works whose files predate names carrying a date. off by default:
        # they cannot be judged out of date, and refetching a whole library is expensive.
        'refreshUndated': bool(given.get('refreshUndated')),
        # instead of refetching those, write this date onto them and carry on. anything ao3
        # has updated since it is then fetched by the ordinary rule. '' means don't.
        'stampUndated': parse_text.get_date_stamp(given.get('stampUndated') or ''),
    }


def example_file_name(maximum: int) -> str:
    """The naming rule shown as an actual name.

    Built through the same truncation a real download goes through, so the example shows
    what the configured length really does rather than claiming something tidier.
    """

    worknum, title, author, date = strings.FILE_NAME_EXAMPLE_PARTS
    name = (strings.FILE_NAME_PATTERN
            .replace('{worknum}', worknum)
            .replace('{title}', title)
            .replace('{author}', author))
    return parse_text.get_valid_filename([name], maximum, ' ' + date) + '.html'


def read_settings(fileops: FileOps) -> dict:
    """The settings.ini values a run will actually use, for the ui to show back.

    The path is included on purpose. Which settings.ini is in force is not obvious - it
    depends on where the helper was started from - and a helper left running from an
    earlier session is the usual explanation for settings that appear to be ignored.
    """

    return {
        'file': os.path.abspath(fileops.inifile),
        'downloadFolder': os.path.abspath(fileops.downloadfolder),
        'extraWaitTime': fileops.get_ini_value_integer(strings.INI_WAIT_TIME, 0),
        # not a setting any more, but still worth showing: it is how every file is named,
        # and the date on the end is what later runs read to spot an outdated copy
        'fileNamePattern': strings.FILE_NAME_PATTERN + ' ' + strings.DATE_STAMP_PLACEHOLDER,
        'fileNameLength': fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH),
        'fileNameExample': example_file_name(
            fileops.get_ini_value_integer(strings.INI_NAME_LENGTH,
                                          strings.INI_DEFAULT_NAME_LENGTH)),
        'maxRetries': fileops.get_ini_value_integer(strings.INI_MAX_RETRIES, 0),
        'maxTimeouts': fileops.get_ini_value_integer(strings.INI_MAX_TIMEOUTS, 3),
        'debugLogging': fileops.get_ini_value_boolean(strings.INI_DEBUG_LOGGING, False),
    }


class Job:
    """One download run, executing on its own thread and publishing progress events."""

    def __init__(self, action: str, filetypes: list[str], username: str,
                 options: dict | None = None, url: str = '') -> None:
        self.id = uuid.uuid4().hex
        self.action = action
        self.filetypes = filetypes
        self.username = username
        # only the actions in ACTIONS_NEEDING_URL use this; the rest build their own link
        self.url = url
        self.options = options or resolve_options(None)
        self.events: queue.Queue = queue.Queue()
        self.done = threading.Event()
        self.cancel = threading.Event()
        self.history: list[dict] = []
        self.lock = threading.Lock()

    def emit(self, event: dict) -> None:
        with self.lock:
            self.history.append(event)
        self.events.put(event)

    def finish(self) -> None:
        self.done.set()
        self.events.put(None)


class LineStream(io.TextIOBase):
    """Turns the console output of the existing code into progress messages."""

    def __init__(self, emit: Callable[[str], None]) -> None:
        self.emit = emit
        self.buffer_text = ''

    def write(self, text: str) -> int:
        self.buffer_text += text
        while '\n' in self.buffer_text:
            line, self.buffer_text = self.buffer_text.split('\n', 1)
            line = line.strip()
            if line: self.emit(line)
        return len(text)


def run_job(job: Job, password: str) -> None:
    """Execute a job. Mirrors the console actions, minus the prompts."""

    def report(event: dict) -> None:
        job.emit(event)

    stream = LineStream(lambda line: job.emit({'type': progress.MESSAGE, 'text': line}))

    try:
        fileops = FileOps()
        fileops.initialize()
        with contextlib.redirect_stdout(stream):
            with Repository(fileops, progress=report, cancelled=job.cancel.is_set) as repo:
                job.emit({'type': progress.STARTED, 'action': job.action,
                          'folder': fileops.downloadfolder,
                          'filetypes': job.filetypes, 'options': job.options})
                # announced separately so the ui can show it is waiting, and say whether
                # the credentials worked before anything else starts
                progress.report(report, progress.PHASE, name=progress.AUTHENTICATING)
                repo.login(job.username, password)
                progress.report(report, progress.AUTHENTICATED, username=job.username)
                if job.action == ACTION_BOOKMARKS:
                    run_bookmarks(job, fileops, repo, report)
                elif job.action == ACTION_COLLECTIONS:
                    run_collections(job, fileops, repo, report)
                elif job.action == ACTION_COLLECTION:
                    run_collection(job, fileops, repo, report)
                else:
                    run_update(job, fileops, repo, report)
        job.emit({'type': progress.FINISHED, 'cancelled': job.cancel.is_set()})
    except Exception as e:
        job.emit({'type': progress.FAILED, 'error': str(e),
                  'detail': traceback.format_exc()})
    finally:
        job.finish()


def run_bookmarks(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """The 'download from ao3 link' action, pointed at the user's own bookmarks.

    Works already in the downloads folder are skipped, so a second run only picks up
    bookmarks added since the last one.
    """

    link = f'{strings.AO3_BASE_URL}/users/{job.username}/bookmarks'
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]

    # 0 means every page, which Ao3 expects as None
    pages = job.options['pages'] or None

    start = job.options['start']

    ao3 = Ao3(repo, fileops, downloadtypes, pages, job.options['series'],
              job.options['images'], progress=report, cancelled=job.cancel.is_set,
              start=start)

    # indexing first: every bookmark gets its json before any work is downloaded, so an
    # interrupted run still leaves a complete index of what is bookmarked.
    records: list[dict] = []
    if metadata:
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)
        records = ao3.get_metadata(link, job.options['workdates'])

    if downloadtypes and not job.cancel.is_set():
        visited = shared.visited(fileops, downloadtypes)
        # the index is what says how recently each work was updated, so this can only be
        # judged once indexing has run
        plan = plan_refresh(job, fileops, records, downloadtypes, report)
        # an out-of-date copy is not 'already downloaded', so it must not be skipped
        visited = [x for x in visited if x not in set(plan['stale'])]
        ao3.superseded = plan['superseded']

        progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
        print(strings.AO3_INFO_DOWNLOADING)

        if can_use_index(job, records):
            # the index already knows every work number, so neither the listing nor each
            # work's page has to be read again
            ao3.download_indexed(records, visited)
        else:
            # the download walks the same listing, so it begins on the same page
            ao3.download(parse_text.set_page_number(link, start), visited)

        # a run that leaves gaps should say which works they were, rather than leaving it
        # to be worked out from the log afterwards
        if ao3.failures:
            print(strings.AO3_INFO_FAILED_WORKS.format(len(ao3.failures)))
            progress.report(report, progress.FAILURES, failures=ao3.failures)


def can_use_index(job: Job, records: list[dict]) -> bool:
    """Whether the download phase can work from the index instead of crawling ao3 again.

    It needs an index to work from, and none of the things only a work page can give:
    embedded images are found on it, marking as read posts from it, and series links are
    discovered through it. Asking for any of those means going the long way round.
    """

    if not records: return False
    if job.options['images']: return False
    if job.options['series']: return False
    return True


def plan_refresh(job: Job, fileops: FileOps, records: list[dict],
                 downloadtypes: list[str], report) -> dict:
    """Which downloaded works ao3 has updated since they were saved.

    Reports both counts to the ui: the works that are out of date and will be fetched
    again, and the ones saved before file names carried a date, which cannot be judged and
    so are left alone unless the run was asked to refresh them.
    """

    if not records:
        return {'stale': [], 'undated': [], 'superseded': {}}

    existing = shared.scan_downloaded_works(fileops.downloadfolder, downloadtypes)

    # dating the undated files first means the ordinary rule can judge them from here on,
    # so nothing below has to treat them as a special case
    stamped = 0
    stamp = job.options['stampUndated']
    if stamp:
        maximum = fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        result = shared.stamp_undated_works(fileops, existing, stamp, maximum)
        stamped = result['renamed']
        print(strings.AO3_INFO_STAMPED.format(stamped, stamp))
        if result['skipped']:
            print(strings.AO3_INFO_STAMP_SKIPPED.format(result['skipped']))

    plan = shared.plan_downloads(records, existing, downloadtypes,
                                 refresh_undated=job.options['refreshUndated'])

    if plan['stale']:
        print(strings.AO3_INFO_OUT_OF_DATE.format(len(plan['stale'])))
    if plan['undated']:
        print(strings.AO3_INFO_UNDATED.format(len(plan['undated'])))

    progress.report(report, progress.REFRESH, stale=len(plan['stale']),
                    undated=len(plan['undated']), stamped=stamped)
    return plan


def run_collections(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Save a json file for every collection the user has, under downloads/collections.

    Only work ids are recorded for the items in a collection: the works themselves are
    described by the index, so repeating their metadata here would only go stale.
    """

    link = f'{strings.AO3_BASE_URL}/users/{job.username}/collections'
    pages = job.options['pages'] or None

    progress.report(report, progress.PHASE, name=progress.COLLECTIONS)
    print(strings.AO3_INFO_COLLECTIONS)

    ao3 = Ao3(repo, fileops, [], pages, False, False,
              progress=report, cancelled=job.cancel.is_set)
    records = ao3.get_collections(link)

    if records:
        print(strings.AO3_INFO_COLLECTIONS_DONE.format(
            len(records), os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME)))
    else:
        print(strings.AO3_INFO_COLLECTIONS_NONE)


def run_collection(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index one collection from a link, which need not be one of the user's own.

    Written to the same downloads/collections folder, in the same shape, as the
    collections you own - so an indexed collection is an indexed collection either way.
    """

    progress.report(report, progress.PHASE, name=progress.COLLECTIONS)

    ao3 = Ao3(repo, fileops, [], None, False, False,
              progress=report, cancelled=job.cancel.is_set)
    records = ao3.get_collection(job.url)

    if records:
        print(strings.AO3_INFO_COLLECTIONS_DONE.format(
            len(records), os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME)))


def run_update(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """The 'download latest version of incomplete fics' action."""

    folder = fileops.downloadfolder
    # only ebook formats can be parsed for a chapter count; JSON is metadata, not a work
    scan_types = [x for x in job.filetypes if x in strings.UPDATE_ACCEPTABLE_FILE_TYPES]
    if not scan_types: scan_types = ['HTML']
    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]

    files = shared.get_files_of_type(folder, scan_types)

    progress.report(report, progress.PHASE, name=progress.SCANNING)
    print(strings.UPDATE_INFO_URLS)
    works: dict[str, int] = {}
    for index, item in enumerate(files, start=1):
        if job.cancel.is_set(): break
        try:
            work = update.process_file(item['path'], item['filetype'])
            if work:
                link = work['link']
                # the same work can be on disk in several formats; keep the least complete
                if link not in works or work['chapters'] < works[link]:
                    works[link] = work['chapters']
        except Exception as e:
            fileops.write_log({'message': strings.ERROR_INCOMPLETE_FIC, 'path': item['path'],
                               'error': str(e), 'stacktrace': traceback.format_exc()})
        report({'type': progress.WORK, 'done': index, 'total': len(files),
                'phase': 'scanning'})
    print(strings.UPDATE_INFO_URLS_DONE)

    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)

    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
    print(strings.UPDATE_INFO_DOWNLOADING)
    for index, (link, chapters) in enumerate(works.items(), start=1):
        if job.cancel.is_set(): break
        ao3.update(link, str(chapters))
        report({'type': progress.WORK, 'done': index, 'total': len(works),
                'phase': 'downloading'})


class Handler(BaseHTTPRequestHandler):
    jobs: dict[str, Job] = {}
    jobs_lock = threading.Lock()

    server_version = 'ao3downloader-local'

    def log_message(self, format: str, *args) -> None:
        pass # the console belongs to the download output

    # region plumbing

    def cors(self) -> None:
        origin = self.headers.get('Origin', '')
        # the angular dev server is a different port, so it counts as another origin.
        # only ever reflect a loopback origin back.
        if origin.startswith('http://localhost:') or origin.startswith('http://127.0.0.1:'):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')

    def send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.cors()
        self.end_headers()
        self.wfile.write(payload)

    def read_json(self) -> dict:
        length = int(self.headers.get('Content-Length') or 0)
        if not length: return {}
        return json.loads(self.rfile.read(length).decode('utf-8'))

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.cors()
        self.end_headers()

    # endregion

    def do_GET(self) -> None:
        if self.path == '/api/config':
            fileops = FileOps()
            self.send_json(200, {
                'downloadFolder': fileops.downloadfolder,
                'username': fileops.get_setting(strings.SETTING_USERNAME) or '',
                'filetypes': strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA,
                'forced': FORCED_FILETYPES,
                'defaults': DEFAULT_FILETYPES,
                'settings': read_settings(fileops),
            })
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/events'):
            self.stream_events(self.path.split('/')[3])
            return

        self.send_json(404, {'error': 'not found'})

    def do_POST(self) -> None:
        if self.path.startswith('/api/jobs/') and self.path.endswith('/cancel'):
            self.cancel_job(self.path.split('/')[3])
            return

        if self.path != '/api/jobs':
            self.send_json(404, {'error': 'not found'})
            return

        try:
            body = self.read_json()
        except Exception:
            self.send_json(400, {'error': 'invalid json'})
            return

        action = body.get('action')
        if action not in ACTIONS:
            # naming both sides matters: the usual cause is not a bad request but a helper
            # left running from an earlier session, which predates the action being added
            self.send_json(400, {'error':
                f"this helper does not know the action '{action}'. It understands "
                f"{', '.join(ACTIONS)}. If the button you pressed is newer than the helper, "
                'it is running older code - close its window and start the application again.'})
            return

        username = (body.get('username') or '').strip()
        password = body.get('password') or ''
        if not username or not password:
            self.send_json(400, {'error': 'username and password are required'})
            return

        filetypes = resolve_filetypes(body.get('filetypes'))
        options = resolve_options(body.get('options'))

        url = (body.get('url') or '').strip()
        if action in ACTIONS_NEEDING_URL:
            # checked here rather than on the thread, so a bad link is a straight answer to
            # the request instead of a job that starts and immediately fails
            if strings.AO3_BASE_URL not in url or not parse_text.get_collection_name(url):
                self.send_json(400, {'error': strings.ERROR_NOT_A_COLLECTION})
                return

        job = Job(action, filetypes, username, options, url)
        with Handler.jobs_lock:
            Handler.jobs[job.id] = job

        thread = threading.Thread(target=run_job, args=(job, password), daemon=True)
        thread.start()

        self.send_json(202, {'jobId': job.id, 'filetypes': filetypes, 'options': options})

    def cancel_job(self, job_id: str) -> None:
        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        # the run notices at its next checkpoint and unwinds, keeping what it has saved
        job.cancel.set()
        self.send_json(202, {'cancelling': True})

    def stream_events(self, job_id: str) -> None:
        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.cors()
        self.end_headers()

        # anything that happened before this connection opened
        with job.lock:
            backlog = list(job.history)
        try:
            for event in backlog:
                self.write_event(event)
            while True:
                event = job.events.get()
                if event is None: break
                if event in backlog: continue
                self.write_event(event)
        except (BrokenPipeError, ConnectionResetError):
            pass # the page navigated away

    def write_event(self, event: dict) -> None:
        self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode('utf-8'))
        self.wfile.flush()


def already_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    """Whether a helper is already answering on this port.

    This asks by connecting, rather than by trying to bind and seeing what happens, because
    the two questions have different answers. On Windows SO_REUSEADDR - which HTTPServer
    turns on by default - lets a second process bind a port another one is already
    listening on: both 'start', and which of them answers any given request is undefined.
    The result is a helper that is silently the wrong one, an older build from a previous
    session answering the new page with its own settings.ini and its own code, which looks
    exactly like the new build ignoring its config.

    Turning SO_REUSEADDR off would stop that, but it also makes the port unbindable for
    minutes after a normal shutdown, while closed connections sit in TIME_WAIT - so
    stopping the application and starting it again would fail for no good reason. Probing
    for a live listener separates the two: a helper that is actually there is refused, and
    a port merely remembered by the operating system is not.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(timeout)
        return probe.connect_ex((host, port)) == 0


def serve(port: int = DEFAULT_PORT) -> None:
    if already_listening(HOST, port):
        print(f'could not start: something is already listening on {HOST}:{port}.')
        print('that is almost always an ao3downloader helper left running from an earlier')
        print('session. close its window, or stop it with:')
        print(f'    powershell -c "Get-NetTCPConnection -LocalPort {port} -State Listen | '
              'ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"')
        print('then start this again. carrying on would leave the page talking to the old')
        print('helper, which has its own settings and may be running older code.')
        raise SystemExit(1)

    httpd = ThreadingHTTPServer((HOST, port), Handler)
    print(f'ao3downloader local api listening on http://{HOST}:{port}')
    print('this window has to stay open while the web ui is running.')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nstopping')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    serve()
