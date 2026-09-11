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

from source_code import exceptions, parse_text, progress, strings
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

# how long a run waits between checks for an answer to a question it has asked. short
# enough that a stop is noticed quickly, long enough not to spin.
ANSWER_POLL_SECONDS = 0.25

# how long a question waits altogether before giving up and taking its default. a browser
# tab closed without stopping the run would otherwise leave this thread waiting for an
# answer that can never arrive. Long enough that nobody who stepped away loses their place.
ANSWER_TIMEOUT_SECONDS = 30 * 60

# what to do about downloaded files that carry no date. asked before anything is fetched,
# because the answer decides which works count as outdated.
UNDATED_QUESTION = 'undated'
UNDATED_STAMP = 'stamp'
UNDATED_REFRESH = 'refresh'
UNDATED_SKIP = 'skip'
UNDATED_CHOICES = (UNDATED_STAMP, UNDATED_REFRESH, UNDATED_SKIP)

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
        # set while the user has the run paused. it is only ever read at the one safe
        # point in the request loop, so setting it here cannot interrupt anything.
        self.held = threading.Event()
        # a run can stop and put a question to the ui; these carry the reply back
        self.answered = threading.Event()
        self.answer: dict = {}
        self.history: list[dict] = []
        self.lock = threading.Lock()

    def emit(self, event: dict) -> None:
        with self.lock:
            self.history.append(event)
        self.events.put(event)

    def ask(self, question: dict, default: dict) -> dict:
        """Put a question to the ui and wait for the answer.

        The wait is in slices rather than one long block so that a stop releases it: a run
        paused on a question the user has walked away from must still be stoppable, and a
        closed tab must not leave a thread waiting for an answer that can never come. A
        stop, or an answer that says nothing, both give back the default - which is always
        the option that changes nothing.
        """

        self.answer = {}
        self.answered.clear()
        self.emit({'type': progress.QUESTION, **question})

        waited = 0.0
        while not self.answered.is_set():
            if self.cancel.is_set(): return default
            if waited >= ANSWER_TIMEOUT_SECONDS: return default
            self.answered.wait(timeout=ANSWER_POLL_SECONDS)
            waited += ANSWER_POLL_SECONDS

        return self.answer or default


    def reply(self, answer: dict) -> None:
        """Hand an answer back to whatever asked."""

        self.answer = answer or {}
        self.answered.set()


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
            with Repository(fileops, progress=report, cancelled=job.cancel.is_set,
                            held=job.held.is_set) as repo:
                job.emit({'type': progress.STARTED, 'action': job.action,
                          'folder': fileops.downloadfolder,
                          'filetypes': job.filetypes, 'options': job.options})
                # announced separately so the ui can show it is waiting, and say whether
                # the credentials worked before anything else starts
                progress.report(report, progress.PHASE, name=progress.AUTHENTICATING)
                print(strings.AO3_INFO_LOGGING_IN.format(job.username))
                repo.login(job.username, password)
                print(strings.AO3_INFO_LOGGED_IN)
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
        report_failures(ao3, report)


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


def settle_undated(job: Job, fileops: FileOps, records: list[dict], existing: dict,
                   filetypes: list[str]) -> tuple[bool, int]:
    """Ask what to do about downloaded files that carry no date, before anything is fetched.

    An undated file cannot be judged against ao3's version - there is nothing to compare it
    with - so the run stops and asks rather than guessing. It is asked here, and not after
    the downloads, because the answer decides which works count as out of date and there is
    no acting on it once they have been fetched.

    `existing` is updated in place when the files are dated, so the caller can plan from it
    straight afterwards. Returns whether undated works should now count as out of date, and
    how many files were given a date.
    """

    undated = shared.plan_downloads(records, existing, filetypes)['undated']
    if not undated: return False, 0

    print(strings.AO3_INFO_UNDATED.format(len(undated)))
    print(strings.AO3_INFO_UNDATED_WAITING)

    answer = job.ask(
        {'name': UNDATED_QUESTION, 'count': len(undated), 'choices': list(UNDATED_CHOICES)},
        # a stop, or a closed tab, leaves them exactly as they are
        {'choice': UNDATED_SKIP, 'date': ''})
    choice = answer.get('choice')

    if choice == UNDATED_STAMP and answer.get('date'):
        maximum = fileops.get_ini_value_integer(
            strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
        # exactly the works the question was asked about, and no others. `existing` is the
        # whole downloads folder; `undated` is the handful of it this run is dealing with
        links = set(undated)
        works = {str(x['id']) for x in records
                 if x.get('id') and x.get('link') in links}
        result = shared.stamp_undated_works(fileops, existing, works, answer['date'],
                                            maximum)
        print(strings.AO3_INFO_STAMPED.format(result['renamed'], answer['date']))
        if result['skipped']:
            print(strings.AO3_INFO_STAMP_SKIPPED.format(result['skipped']))
        # they carry a date now, so the ordinary rule judges them from here on
        return False, result['renamed']

    if choice == UNDATED_REFRESH:
        print(strings.AO3_INFO_UNDATED_REFRESH.format(len(undated)))
        return True, 0

    print(strings.AO3_INFO_UNDATED_SKIPPED.format(len(undated)))
    return False, 0


def plan_refresh(job: Job, fileops: FileOps, records: list[dict],
                 downloadtypes: list[str], report) -> dict:
    """What the downloads folder already holds, and which of it ao3 has moved past.

    Says what it is doing at each step, because from the outside 'checking what you have'
    and 'checking what is out of date' look the same as a stall.
    """

    if not records:
        return {'stale': [], 'undated': [], 'superseded': {}, 'existing': {}}

    progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
    print(strings.AO3_INFO_CHECKING_FILES)
    existing = shared.scan_downloaded_works(fileops.downloadfolder, downloadtypes)

    refresh_undated, stamped = settle_undated(job, fileops, records, existing, downloadtypes)

    progress.report(report, progress.PHASE, name=progress.CHECKING_VERSIONS)
    print(strings.AO3_INFO_CHECKING_VERSIONS)
    plan = shared.plan_downloads(records, existing, downloadtypes,
                                 refresh_undated=refresh_undated)
    plan['existing'] = existing

    if plan['stale']:
        print(strings.AO3_INFO_OUT_OF_DATE.format(len(plan['stale'])))
    else:
        print(strings.AO3_INFO_UP_TO_DATE)

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
    """The 'update bookmarks marked as incomplete' action.

    Driven by the index rather than by the files on disk. The index already records which
    works were unfinished when they were last read and holds a link to each, so nothing has
    to be parsed out of an ebook to find a chapter count, and no listing has to be walked to
    rediscover where the works are.

    The limitation that carries is stated in the ui, and has to be acknowledged before the
    run starts: a fic that had already finished when it was last indexed is not in this
    list, however much has been added to it since.

    Unlike a bookmarks run, this does **not** index everything before downloading anything.
    It cannot: a bookmarks run reads the whole listing in a handful of requests and so knows
    every work's current state up front, while here each fic has to be opened individually
    before there is anything new to say about it. So it works one fic at a time - re-read
    it, write its entry, fetch it if the copy is behind - which also means a run stopped
    partway has finished every fic it touched rather than half-finishing all of them.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]

    # 1. the index, off disk. no requests at all.
    progress.report(report, progress.PHASE, name=progress.SCANNING)
    print(strings.AO3_INFO_READING_INDEX)
    incomplete = shared.incomplete_works(shared.read_index(fileops))

    if not incomplete:
        print(strings.AO3_INFO_INCOMPLETE_NONE)
        return

    print(strings.AO3_INFO_INCOMPLETE_FOUND.format(len(incomplete)))

    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)

    # 2 and 3. what is already downloaded for those works, and what to do about any of it
    # that carries no date. asked now, before a single request, because the answer decides
    # which copies count as behind.
    existing: dict = {}
    refresh_undated = False
    if downloadtypes:
        progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
        print(strings.AO3_INFO_CHECKING_FILES)
        existing = shared.scan_downloaded_works(fileops.downloadfolder, downloadtypes)
        refresh_undated, stamped = settle_undated(
            job, fileops, incomplete, existing, downloadtypes)
        if stamped:
            progress.report(report, progress.REFRESH, stale=0, undated=0, stamped=stamped)

    # 4. one fic at a time: re-read it, then fetch it if the copy is behind
    progress.report(report, progress.PHASE, name=progress.UPDATING)
    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)

    checked = 0
    fetched = 0
    for record in incomplete:
        if job.cancel.is_set(): break
        checked += 1
        try:
            fetched += update_one_work(ao3, record, existing, downloadtypes, maximum,
                                       refresh_undated, checked, len(incomplete), report)
        except exceptions.CancelledException:
            # a stop is not a failed run; what has been written so far stays written
            break

    print(strings.AO3_INFO_UPDATE_DONE.format(checked, fetched))
    report_failures(ao3, report)


def update_one_work(ao3: Ao3, record: dict, existing: dict, filetypes: list[str],
                    maximum: int, refresh_undated: bool, done: int, total: int,
                    report) -> int:
    """Bring one fic's entry up to date, and fetch it again if the copy is behind.

    Says what it is doing at each step rather than only at the end, because this is the
    slow part of the run and a line per fic is the only sign it is still moving.

    Returns 1 if the fic was downloaded, 0 if only its entry changed. A fic that cannot be
    read is recorded as a failure and skipped - it keeps the entry it already had.
    """

    link = record.get('link') or ''
    log: dict = {'link': link}

    try:
        ao3.check_cancelled()
        title = record.get('title') or link
        print(strings.AO3_INFO_UPDATE_WORK.format(done, total, title))
        progress.report(ao3.progress, progress.WORK, title=title, link=link,
                        done=done, total=total, phase=progress.UPDATING)

        print(strings.AO3_INFO_UPDATE_READING)
        fresh = ao3.refresh_one(record)
        print(strings.AO3_INFO_UPDATE_INDEXED)

        if not filetypes:
            print(strings.AO3_INFO_UPDATE_NOTHING)
            return 0

        # the same rule a bookmarks run uses, asked about one work rather than all of them
        plan = shared.plan_downloads([fresh], existing, filetypes,
                                     refresh_undated=refresh_undated)
        have = existing.get(str(fresh.get('id') or ''), {})
        missing = [x for x in filetypes if x.upper() not in have]

        if missing:
            print(strings.AO3_INFO_UPDATE_MISSING)
        elif plan['stale']:
            print(strings.AO3_INFO_UPDATE_BEHIND)
        else:
            print(strings.AO3_INFO_UPDATE_CURRENT)
            return 0

        ao3.superseded = plan['superseded']
        ao3.download_one_indexed(fresh, maximum, log, done, total)
        return 1

    except exceptions.CancelledException:
        print(strings.INFO_CANCELLED)
        raise
    except Exception as e:
        ao3.record_failure(link, e)
        ao3.log_error(log, e)
        return 0


def report_failures(ao3: Ao3, report) -> None:
    """Name the works a run could not fetch, rather than leaving them to the log."""

    if not ao3.failures: return
    print(strings.AO3_INFO_FAILED_WORKS.format(len(ao3.failures)))
    progress.report(report, progress.FAILURES, failures=ao3.failures)


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

        if self.path.startswith('/api/jobs/') and self.path.endswith('/answer'):
            self.answer_job(self.path.split('/')[3])
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/pause'):
            self.hold_job(self.path.split('/')[3], True)
            return

        if self.path.startswith('/api/jobs/') and self.path.endswith('/resume'):
            self.hold_job(self.path.split('/')[3], False)
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

    def hold_job(self, job_id: str, hold: bool) -> None:
        """Pause or resume a run.

        Setting the flag is all this does; the run itself decides when to act on it, at the
        one point where stopping is safe. So this answers immediately and a run midway
        through a file keeps going until that file is written.

        A stop is never blocked by a pause, and resuming a run nobody paused does nothing,
        so the two buttons cannot be used to wedge each other.
        """

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        if hold:
            job.held.set()
        else:
            job.held.clear()
        self.send_json(202, {'paused': hold})

    def answer_job(self, job_id: str) -> None:
        """Hand a run the answer to the question it is waiting on."""

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        try:
            body = self.read_json()
        except Exception:
            self.send_json(400, {'error': 'invalid json'})
            return

        choice = body.get('choice')
        if choice not in UNDATED_CHOICES:
            # a run waiting on an answer must not be sent something it cannot act on
            self.send_json(400, {'error':
                f"'{choice}' is not one of {', '.join(UNDATED_CHOICES)}"})
            return

        job.reply({'choice': choice, 'date': parse_text.get_date_stamp(body.get('date') or '')})
        self.send_json(202, {'answered': True})


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
