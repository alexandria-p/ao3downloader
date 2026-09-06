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
import queue
import threading
import traceback
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ao3downloader import progress, strings, update
from ao3downloader.actions import shared
from ao3downloader.ao3 import Ao3
from ao3downloader.fileio import FileOps
from ao3downloader.repo import Repository


HOST = '127.0.0.1'
DEFAULT_PORT = 4400

ACTION_BOOKMARKS = 'bookmarks'
ACTION_UPDATE = 'update'

# these two are always produced, so the ui shows them ticked and locked
FORCED_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML']


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

    return {
        'pages': pages,
        'series': bool(given.get('series')),
        'images': bool(given.get('images')),
        'workdates': bool(given.get('workdates')),
    }


class Job:
    """One download run, executing on its own thread and publishing progress events."""

    def __init__(self, action: str, filetypes: list[str], username: str,
                 options: dict | None = None) -> None:
        self.id = uuid.uuid4().hex
        self.action = action
        self.filetypes = filetypes
        self.username = username
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
                repo.login(job.username, password)
                if job.action == ACTION_BOOKMARKS:
                    run_bookmarks(job, fileops, repo, report)
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

    visited = shared.visited(fileops, downloadtypes) if downloadtypes else []
    ao3 = Ao3(repo, fileops, downloadtypes, pages, job.options['series'],
              job.options['images'], progress=report, cancelled=job.cancel.is_set)

    if metadata:
        print(strings.AO3_INFO_METADATA)
        ao3.get_metadata(link, job.options['workdates'])
    if downloadtypes and not job.cancel.is_set():
        print(strings.AO3_INFO_DOWNLOADING)
        ao3.download(link, visited)


def run_update(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """The 'download latest version of incomplete fics' action."""

    folder = fileops.downloadfolder
    # only ebook formats can be parsed for a chapter count; JSON is metadata, not a work
    scan_types = [x for x in job.filetypes if x in strings.UPDATE_ACCEPTABLE_FILE_TYPES]
    if not scan_types: scan_types = ['HTML']
    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]

    files = shared.get_files_of_type(folder, scan_types)

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
        if action not in (ACTION_BOOKMARKS, ACTION_UPDATE):
            self.send_json(400, {'error': 'unknown action'})
            return

        username = (body.get('username') or '').strip()
        password = body.get('password') or ''
        if not username or not password:
            self.send_json(400, {'error': 'username and password are required'})
            return

        filetypes = resolve_filetypes(body.get('filetypes'))
        options = resolve_options(body.get('options'))

        job = Job(action, filetypes, username, options)
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


def serve(port: int = DEFAULT_PORT) -> None:
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
