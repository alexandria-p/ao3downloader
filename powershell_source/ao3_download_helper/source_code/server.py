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

from source_code import exceptions, parse_text, progress, runs, strings
from source_code.actions import shared
from source_code.ao3 import Ao3
from source_code.fileio import FileOps
from source_code.repo import Repository


HOST = '127.0.0.1'
DEFAULT_PORT = 4400

# a full walk of the whole bookmarks listing. thorough and slow.
ACTION_BOOKMARKS = 'bookmarks'
ACTION_UPDATE = 'update'
ACTION_COLLECTIONS = 'collections'

ACTION_COLLECTION = 'collection'

# stops indexing at the first bookmark it already holds, so a routine run costs a request
# or two rather than a walk of the whole library
ACTION_NEW = 'new'
# the one to reach for: new bookmarks, then the unfinished ones, then the formats missing
# from everything else
ACTION_SYNC = 'sync'
# one fic, by link or work number
ACTION_WORK = 'work'
# the full scan with its parts made optional
ACTION_CUSTOM = 'custom'
# a full scan's shape, but stopping at the works ao3 has not touched since the last run
# that actually finished
ACTION_QUICK = 'quick'

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

ACTIONS = (ACTION_BOOKMARKS, ACTION_UPDATE, ACTION_COLLECTIONS, ACTION_COLLECTION,
           ACTION_NEW, ACTION_SYNC, ACTION_WORK, ACTION_CUSTOM, ACTION_QUICK)

# actions that need a link from the caller rather than working it out from the username
ACTIONS_NEEDING_URL = (ACTION_COLLECTION, ACTION_WORK)

# The runs whose overwrite choice is the caller's to make. Refetching a copy nothing says is
# out of date is the answer to a damaged file, and it costs a request per format per work -
# so it belongs to the two runs that are pointed at a library and told to spend more on it,
# and nowhere else. ACTION_WORK is absent on purpose: it always overwrites, and `run_work`
# sets that itself rather than taking it from the request.
OVERWRITE_ACTIONS = (ACTION_BOOKMARKS, ACTION_CUSTOM)

# json is always produced, so the ui shows it ticked and locked. it is what the web page
# reads, and it costs nothing extra: the metadata comes off the listing page that has to be
# fetched anyway, rather than one request per work.
FORCED_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA]

# ticked when the dialog opens, but free to untick. html is here rather than above because
# it costs a request per work on top of the indexing, so a metadata-only refresh - which is
# a great deal lighter on the rate limit - has to be possible.
DEFAULT_FILETYPES = [strings.AO3_DOWNLOAD_TYPE_METADATA, 'HTML']


def resolve_filetypes(requested, force: bool = True) -> list[str]:
    """Keep the recognised types the caller asked for, and add the ones we always produce.

    The ui shows the forced types ticked and locked, but a request is not to be trusted to
    have honoured that, so they are re-added here.

    `force` is the one exception: a run that is not going to index cannot produce json,
    because json *is* the index. Adding it back there would report a file type the run
    never writes, which is worse than not offering it.
    """

    filetypes: list[str] = []
    for filetype in (requested or []):
        # a repeat would download the same work twice, for nothing but rate limit
        if filetype in strings.AO3_ACCEPTABLE_DOWNLOAD_TYPES_WITH_METADATA \
                and filetype not in filetypes:
            filetypes.append(filetype)
    if force:
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
        # fetch every requested format again, however current the copy on disk looks. the
        # answer to a damaged or truncated file, which no version check can see: the name
        # and the date are both right and only the bytes are wrong.
        'overwrite': bool(given.get('overwrite')),
        # a custom run can work from what is already indexed rather than reading ao3's
        # listing again. it defaults to indexing, because a run that quietly skipped it
        # would judge everything against however stale the index happened to be.
        'reindex': given.get('reindex') is not False,
        # a custom run covers *either* a slice of the listing or a window of time, never
        # both: one picks works by where they sit in the listing and the other by when ao3
        # last touched them, and a run cannot be walking a listing and not walking it.
        'dates': bool(given.get('dates')),
        'dateFrom': parse_text.get_date_stamp(given.get('dateFrom') or ''),
        'dateTo': parse_text.get_date_stamp(given.get('dateTo') or ''),
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
        'debugTools': fileops.get_ini_value_boolean(strings.INI_DEBUG_TOOLS, False),
    }


def settings_for_record(fileops: FileOps) -> dict:
    """settings.ini as the history file should record it, or nothing if it cannot be read.

    Everything in `runs.py` swallows its own errors for one reason: a history file is a
    convenience, and a run that downloaded a library must not be reported as failed because
    a note about it could not be filled in. This is the same rule applied one step earlier -
    the values are gathered out here, so they have to be gathered safely too.
    """

    try:
        return read_settings(fileops)
    except Exception:
        return {}


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
        # a debug tool: abandon the step in progress and go on to the next one. read at the
        # same loop boundaries a stop is read at, and cleared by whichever pass consumes it,
        # so one press skips one step rather than every step after it.
        self.skip = threading.Event()
        # the checklist this run is working through. starts as one with nothing in it and
        # nowhere to report to, so every run function can mark its steps without first
        # checking whether anyone is listening - `run_job` swaps in the real one.
        self.steps: 'Steps' = Steps(None, [])
        # the downloader doing the work, once a runner has built one, and the history file
        # being written about this run. both are set as the run gets going.
        self.ao3 = None
        self.record = None
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


    def skipping(self) -> bool:
        """Whether the step in progress should be abandoned, consuming the request.

        Cleared as it is read, so one press skips one step rather than every step after it.
        """

        if not self.skip.is_set(): return False
        self.skip.clear()
        return True


    def reply(self, answer: dict) -> None:
        """Hand an answer back to whatever asked."""

        self.answer = answer or {}
        self.answered.set()


    def finish(self) -> None:
        self.done.set()
        self.events.put(None)


class Steps:
    """The steps a run intends to take, and where it has got to.

    A checklist rather than a log: it is sent once up front so the ui can show what is
    still to come, and then one event per change. That is why it cannot be built from
    `PHASE` events - a phase says what kind of work is happening and repeats (a combined
    run downloads twice, checks files twice), while a step is a place in a plan.

    A step that turns out to have nothing to do is **skipped, not failed**. A run with no
    unfinished fics has not gone wrong.
    """

    def __init__(self, report, plan: list[tuple[str, str]]) -> None:
        self.report = report
        self.plan = plan
        self.current: str | None = None
        progress.report(report, progress.STEPS,
                        steps=[{'id': i, 'label': label} for i, label in plan])

    def _set(self, step: str, status: str) -> None:
        progress.report(self.report, progress.STEP, id=step, status=status)

    def start(self, step: str) -> None:
        self.current = step
        self._set(step, progress.STEP_RUNNING)

    def done(self, step: str) -> None:
        if self.current == step: self.current = None
        self._set(step, progress.STEP_DONE)

    def skip(self, step: str) -> None:
        if self.current == step: self.current = None
        self._set(step, progress.STEP_SKIPPED)

    def fail_current(self) -> None:
        """Mark whatever was in progress as failed, when a run ends badly.

        Only the step actually running: the ones after it never started, and saying they
        failed would blame them for something that happened before they were reached.
        """

        if self.current: self._set(self.current, progress.STEP_FAILED)
        self.current = None


def action_name(action: str) -> str:
    """The button this action belongs to, for a history read months later.

    Kept on the helper rather than taken from the page, because a run's record has to make
    sense on its own - it is read back by the history tab, but it is also just a file.
    """

    return {
        ACTION_BOOKMARKS: strings.ACTION_NAME_BOOKMARKS,
        ACTION_UPDATE: strings.ACTION_NAME_UPDATE,
        ACTION_COLLECTIONS: strings.ACTION_NAME_COLLECTIONS,
        ACTION_COLLECTION: strings.ACTION_NAME_COLLECTION,
        ACTION_NEW: strings.ACTION_NAME_NEW,
        ACTION_SYNC: strings.ACTION_NAME_SYNC,
        ACTION_WORK: strings.ACTION_NAME_WORK,
        ACTION_CUSTOM: strings.ACTION_NAME_CUSTOM,
        ACTION_QUICK: strings.ACTION_NAME_QUICK,
    }.get(action, action)


def step_plan(job: Job) -> list[tuple[str, str]]:
    """What this particular run is going to do, in order.

    Built from the action and the options rather than written per action, so a step that
    depends on a choice - images, skipping the indexing - appears only when it will
    actually happen. A checklist that lists work the run will not do is worse than none.
    """

    downloads = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    plan: list[tuple[str, str]] = [('login', strings.STEP_LOGIN)]

    if job.action == ACTION_COLLECTIONS:
        plan.append(('collections', strings.STEP_INDEX_COLLECTIONS))
    elif job.action == ACTION_COLLECTION:
        plan.append(('collection', strings.STEP_INDEX_COLLECTION))
    elif job.action == ACTION_WORK:
        plan.append(('index', strings.STEP_INDEX_ONE))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD))
    elif job.action == ACTION_UPDATE:
        plan.append(('read', strings.STEP_READ_INDEX))
        if downloads: plan.append(('check', strings.STEP_CHECK_FILES))
        plan.append(('update', strings.STEP_UPDATE))
    elif job.action == ACTION_NEW:
        # the first pass of the combined run, on its own: it indexes what is new and
        # downloads that. no gap pass, because `run_new` does not run one
        plan.append(('index', strings.STEP_INDEX_NEW))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD_NEW))
    elif job.action == ACTION_SYNC:
        plan.append(('index', strings.STEP_INDEX_NEW))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD_NEW))
        plan.append(('update', strings.STEP_UPDATE))
        if downloads: plan.append(('gaps', strings.STEP_FILL_GAPS))
    else:
        # a full scan, a quick scan and a custom run differ only in where the walk stops
        indexing = job.action != ACTION_CUSTOM or job.options['reindex']
        if job.action in (ACTION_CUSTOM, ACTION_QUICK) and job.options['dates']:
            # a window of time chooses from the index and re-reads each one it picked -
            # the unfinished-fics shape rather than a scan. The walk that brings the index
            # up to date first is only there when the run was not told to skip indexing
            window = [('login', strings.STEP_LOGIN)]
            if job.options['reindex'] and metadata:
                window.append(('index', strings.STEP_INDEX_WINDOW))
            window.extend([('read', strings.STEP_READ_WINDOW),
                           ('check', strings.STEP_CHECK_FILES),
                           ('update', strings.STEP_UPDATE_WINDOW),
                           ('report', strings.STEP_REPORT)])
            return window
        if job.action == ACTION_QUICK:
            plan.append(('index', strings.STEP_INDEX_SINCE))
        elif indexing and metadata:
            plan.append(('index', strings.STEP_INDEX_ALL))
        else:
            plan.append(('index', strings.STEP_USE_INDEX))
        if downloads:
            plan.append(('check', strings.STEP_CHECK_FILES))
            plan.append(('download', strings.STEP_DOWNLOAD))
        if job.options['images'] and job.action == ACTION_CUSTOM:
            plan.append(('images', strings.STEP_IMAGES))

    plan.append(('report', strings.STEP_REPORT))
    return plan


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
                # the checklist goes out before anything happens, so the ui can show what
                # is still to come rather than only what has already been done
                job.steps = Steps(report, step_plan(job))

                # announced separately so the ui can show it is waiting, and say whether
                # the credentials worked before anything else starts
                job.steps.start('login')
                progress.report(report, progress.PHASE, name=progress.AUTHENTICATING)
                print(strings.AO3_INFO_LOGGING_IN.format(job.username))
                # written here rather than at the end: a run killed mid-flight cannot write
                # its own epitaph, so a record still saying 'running' is how the history
                # page recognises one that was interrupted.
                #
                # and here rather than a few lines earlier, so a history file always means
                # a run that got as far as trying to log in. everything before this point
                # is setup that cannot reach ao3, and a record for one of those would be a
                # history entry for something that never happened.
                job.record = runs.RunRecord(fileops, job.id, job.action,
                                            action_name(job.action), job.filetypes,
                                            job.options,
                                            settings=settings_for_record(fileops))
                repo.login(job.username, password)
                print(strings.AO3_INFO_LOGGED_IN)
                progress.report(report, progress.AUTHENTICATED, username=job.username)
                job.steps.done('login')

                runners()[job.action](job, fileops, repo, report)
                # every runner ends by calling report_failures, so by the time it returns
                # the reporting has happened. marked here rather than inside that function
                # so the step is ticked once per run and not once per place it is called.
                job.steps.done('report')
        close_record(job, runs.STATUS_STOPPED if job.cancel.is_set()
                     else runs.STATUS_SUCCESS)
        job.emit({'type': progress.FINISHED, 'cancelled': job.cancel.is_set()})
    except Exception as e:
        # the step that was running is the one that failed; the ones after it never started
        job.steps.fail_current()
        close_record(job, runs.STATUS_FAILED, str(e))
        # a lapsed login is not a crash and there is a specific thing to do about it, so it
        # is flagged rather than left to be recognised from the wording of an error
        expired = isinstance(e, exceptions.SessionExpiredException)
        job.emit({'type': progress.FAILED, 'error': str(e), 'sessionExpired': expired,
                  'detail': traceback.format_exc()})
    finally:
        job.finish()


def close_record(job: Job, status: str, error: str = '') -> None:
    """Finish this run's history file, whatever happened to the run.

    A stop is `stopped`, not `failed`: the user asked for it and everything written stays
    written. Anything thrown in here is swallowed - a run that downloaded a library
    successfully must not be reported as failed because a note about it could not be saved.
    """

    if not job.record: return
    try:
        job.record.collect(job.ao3)
        job.record.finish(status, error)
    except Exception:
        pass


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
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    # indexing first: every bookmark gets its json before any work is downloaded, so an
    # interrupted run still leaves a complete index of what is bookmarked.
    records: list[dict] = []
    if metadata:
        job.steps.start('index')
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)
        records = ao3.get_metadata(link, job.options['workdates'])
        job.steps.done('index')
    else:
        job.steps.skip('index')

    if downloadtypes and not job.cancel.is_set():
        job.steps.start('check')
        visited = shared.visited(fileops, downloadtypes)
        # the index is what says how recently each work was updated, so this can only be
        # judged once indexing has run
        plan = plan_refresh(job, fileops, records, downloadtypes, report)
        # an out-of-date copy is not 'already downloaded', so it must not be skipped
        visited = [x for x in visited if x not in set(plan['stale'])]
        ao3.superseded = plan['superseded']
        job.steps.done('check')

        job.steps.start('download')
        progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
        print(strings.AO3_INFO_DOWNLOADING)

        if can_use_index(job, records):
            # the index already knows every work number, so neither the listing nor each
            # work's page has to be read again. newest first, so a run that is stopped has
            # got through the fics most likely to be worth having
            ao3.download_indexed(newest_first(records), visited)
        else:
            # the download walks the same listing, so it begins on the same page
            ao3.download(parse_text.set_page_number(link, start), visited)
        job.steps.done('download')
    else:
        # a metadata-only run, or one stopped during indexing: these never start
        job.steps.skip('check')
        job.steps.skip('download')

    # a run that leaves gaps should say which works they were, rather than leaving it to be
    # worked out from the log afterwards. outside the download block on purpose: a
    # metadata-only run downloads nothing and can still skip bookmarks that are not works
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


def bookmarks_link(job: Job) -> str:
    return f'{strings.AO3_BASE_URL}/users/{job.username}/bookmarks'


def index_new_bookmarks(job: Job, fileops: FileOps, ao3: Ao3, report) -> list[dict]:
    """Index from the newest bookmark until one already held, and return what was new."""

    job.steps.start('index')
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print(strings.AO3_INFO_INDEXING_NEW)

    known = shared.indexed_work_ids(fileops)
    records = ao3.get_metadata(bookmarks_link(job), job.options['workdates'], known=known)

    print(strings.AO3_INFO_NEW_FOUND.format(len(records)) if records
          else strings.AO3_INFO_NEW_NONE)
    job.steps.done('index')
    return records


def download_planned(job: Job, fileops: FileOps, ao3: Ao3, records: list[dict],
                     downloadtypes: list[str], report) -> None:
    """Settle anything undated among these works, then download them.

    The same rule a full run downloads by, applied to whichever slice of the index the
    caller has in hand rather than to the whole listing.

    Works are fetched **newest first**. A long run then gets through the fics you are most
    likely to be waiting on before the ones that have not moved in years, which matters
    because a run can be stopped and where it got to should be the useful half.
    """

    if not records or not downloadtypes or job.cancel.is_set():
        job.steps.skip('check')
        job.steps.skip('download')
        return

    job.steps.start('check')
    plan = plan_refresh(job, fileops, records, downloadtypes, report)
    # an out-of-date copy is not 'already downloaded', so it must not be skipped
    visited = [x for x in shared.visited(fileops, downloadtypes)
               if x not in set(plan['stale'])]
    ao3.superseded = plan['superseded']
    job.steps.done('check')

    job.steps.start('download')
    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
    print(strings.AO3_INFO_DOWNLOADING)
    ao3.download_indexed(newest_first(records), visited)
    job.steps.done('download')


def fill_missing_formats(job: Job, fileops: FileOps, ao3: Ao3, skip: set[str],
                         downloadtypes: list[str], report, reindex: bool = True,
                         only: set[str] | None = None) -> None:
    """Finished works, already indexed, simply missing a format this run asked for.

    The case the other two passes leave behind: not new, so the newest-first walk never
    reached it, and not unfinished, so the update pass ignored it. A fic indexed and saved
    as html long ago, on a run that now asks for pdf as well, is only findable this way.

    A fic that needs fetching is **re-read first**, exactly as the update pass does, so the
    file about to be written is named for the version ao3 has now rather than for whatever
    the index last recorded. Getting that wrong would write a new file carrying an old date,
    which is the one thing every later run's idea of 'outdated' depends on.

    Only the missing formats are fetched, never the whole set. A work that has html and
    wants pdf costs its re-read plus one transfer here, not two transfers - rate limit is
    the scarce thing, and re-fetching a file already on disk spends it for nothing.
    """

    if not downloadtypes or job.cancel.is_set():
        job.steps.skip('gaps')
        return

    job.steps.start('gaps')
    progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
    print(strings.AO3_INFO_CHECKING_GAPS)

    index = shared.read_index(fileops)
    unfinished = {str(x.get('id') or '') for x in shared.incomplete_works(index)}
    existing = shared.scan_downloaded_works(fileops.downloadfolder, downloadtypes)

    gaps: list[tuple[dict, list[str]]] = []
    for record in newest_first(index):
        work = str(record.get('id') or '')
        if not work or not record.get('link'): continue
        if work in skip or work in unfinished: continue
        # `only` narrows this to the works a run actually covered. a full scan fills the
        # gaps in what it just walked, not in every fic the index has ever held - some of
        # those are no longer bookmarked, and fetching them would be a surprise
        if only is not None and work not in only: continue
        have = existing.get(work, {})
        missing = [x for x in downloadtypes if x.upper() not in have]
        if missing: gaps.append((record, missing))

    if not gaps:
        print(strings.AO3_INFO_GAPS_NONE)
        # nothing to fill is not a failure - it is the answer most runs get
        job.steps.done('gaps')
        return

    print(strings.AO3_INFO_GAPS_FOUND.format(len(gaps)))
    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)

    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
    wanted = ao3.filetypes
    abandoned = False
    try:
        for done, (record, missing) in enumerate(gaps, start=1):
            if job.cancel.is_set(): break
            if job.skipping():
                print(strings.AO3_INFO_STEP_SKIPPED)
                abandoned = True
                break
            log: dict = {'link': record['link']}
            try:
                ao3.check_cancelled()
                print(strings.AO3_INFO_GAP_WORK.format(
                    done, len(gaps), record.get('title') or record['link'],
                    ', '.join(missing)))
                progress.report(ao3.progress, progress.WORK,
                                title=record.get('title') or '', link=record['link'],
                                done=done, total=len(gaps), phase=progress.DOWNLOADING)
                # the entry first, then the file - so the name carries the version ao3 has
                # now rather than the one the index happened to be holding. skipped when
                # the caller has only just read the listing: the entry is already current,
                # and re-reading it would cost a request per fic to learn nothing.
                fresh = record
                if reindex:
                    fresh = ao3.refresh_one(record)
                    print(strings.AO3_INFO_GAP_INDEXED)
                ao3.filetypes = missing
                ao3.download_one_indexed(fresh, maximum, log, done, len(gaps))
            except exceptions.CancelledException:
                break
            except exceptions.SessionExpiredException:
                raise  # every fic after this one would fail the same way
            except Exception as e:
                ao3.record_failure(record['link'], e)
                ao3.log_error(log, e)
    finally:
        # the caller's Ao3 is borrowed, not ours to leave reconfigured
        ao3.filetypes = wanted
    job.steps.skip('gaps') if abandoned else job.steps.done('gaps')


def save_images(job: Job, fileops: FileOps, ao3: Ao3, records: list[dict], report) -> None:
    """Fetch each work's page, purely for the images embedded in it.

    Runs **after** the files themselves are down, never instead of them. The indexed path
    reads no work page, so this has to fetch one per fic - an extra request each, which is
    why only a custom run offers it and why it says so plainly before you start.

    A work page that will not load costs its images and nothing else. This is the last thing
    a run does, and losing a second copy of some pictures is not worth ending it over.
    """

    if not records or job.cancel.is_set():
        job.steps.skip('images')
        return

    job.steps.start('images')
    progress.report(report, progress.PHASE, name=progress.DOWNLOADING)
    print(strings.AO3_INFO_IMAGES_START)

    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)
    saved = 0
    done = 0

    abandoned = False
    for record in records:
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            abandoned = True
            break
        if not record.get('id'): continue
        done += 1
        try:
            ao3.check_cancelled()
            progress.report(ao3.progress, progress.WORK, title=record.get('title') or '',
                            link=record.get('link') or '', done=done, total=len(records),
                            phase=progress.DOWNLOADING)
            count = ao3.save_images_for(record, maximum)
            saved += count
            print(strings.AO3_INFO_IMAGE_WORK.format(
                done, len(records), record.get('title') or record.get('id'), count))
        except exceptions.CancelledException:
            break
        except exceptions.SessionExpiredException:
            raise  # every work page after this one would come back logged out
        except Exception as e:
            ao3.record_failure(record.get('link') or '', e)
            ao3.log_error({'link': record.get('link') or ''}, e)

    print(strings.AO3_INFO_IMAGES_DONE.format(saved, done))
    job.steps.skip('images') if abandoned else job.steps.done('images')


def run_new(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index only the bookmarks added since last time, then download them."""

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    records = index_new_bookmarks(job, fileops, ao3, report)
    download_planned(job, fileops, ao3, records, downloadtypes, report)
    report_failures(ao3, report)


def run_sync(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """New bookmarks, then the unfinished ones, then whatever formats are still missing.

    Three passes, each covering what the one before it cannot, and none of them walking the
    whole listing - which is what makes this the one to run routinely. What it gives up is
    stated in the ui and has to be acknowledged: a fic the index already calls finished is
    never re-read, so chapters added to it afterwards are not noticed, and a gap left in the
    index by an interrupted run stays a gap because the walk stops at the first fic it
    recognises. A full scan is the answer to both.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    # one Ao3 for all three passes, so every failure lands in the same list and the run
    # names them once at the end rather than three times over
    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    records = index_new_bookmarks(job, fileops, ao3, report)
    download_planned(job, fileops, ao3, records, downloadtypes, report)

    if not job.cancel.is_set():
        update_incomplete(job, fileops, ao3, downloadtypes, report)

    if not job.cancel.is_set():
        # the works the first two passes already dealt with are not gaps
        handled = {str(x.get('id') or '') for x in records}
        fill_missing_formats(job, fileops, ao3, handled, downloadtypes, report)

    report_failures(ao3, report)


def run_work(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index one fic and download it, from a link or a bare work number.

    **It always replaces whatever copy you already have.** Every other run is pointed at a
    library and has to be careful about what it spends, so it skips anything already on disk
    and current. This one is pointed at a single fic by hand: asking for it and being told
    nothing happened because the copy looked fine is not the answer anybody came for, and
    the whole cost of being wrong is one request per format, for one work.

    So the option is forced on rather than offered - the ui does not show the checkbox for
    this run, because a box that cannot be unticked is not a choice. Setting it on the job's
    own options is what makes the history file say what the run actually did.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    link = work_link(job.url)
    if not link:
        raise exceptions.InvalidLinkException(strings.ERROR_INVALID_LINK)

    job.options['overwrite'] = True

    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    work = parse_text.get_work_number(link) or ''
    job.steps.start('index')
    progress.report(report, progress.PHASE, name=progress.INDEXING)
    print(strings.AO3_INFO_ONE_WORK.format(work))

    # an entry it already has keeps everything the listing gave it; only the stats change
    existing = next((x for x in shared.read_index(fileops)
                     if str(x.get('id') or '') == work), None)
    record = ao3.index_one_work(link, existing)
    print(strings.AO3_INFO_ONE_WORK_INDEXED)
    job.steps.done('index')

    download_planned(job, fileops, ao3, [record], downloadtypes, report)
    print(strings.AO3_INFO_ONE_WORK_DONE.format(work))
    report_failures(ao3, report)


def run_quick(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """A full scan's shape, stopping where ao3 stopped changing things.

    It walks the bookmarks listing **sorted by when ao3 last updated each work** and stops
    at the first one older than the last run that actually finished. Everything past that
    point is, by definition, a work ao3 has not touched since we last looked.

    The sort is not optional. Verified against the live site: the default listing is
    ordered by when each work was *bookmarked* and jumps about by years, so this walk down
    an unsorted listing would stop after a fic or two and miss nearly everything.

    With no completed run on record there is no floor, so it reads the whole listing - the
    honest answer the first time, rather than a short walk from a date it invented.

    A date range replaces the floor it works out for itself with one the user gave, and from
    there it is the custom run's window in every respect - same walk, same stop, same per-fic
    pass. The two are alternatives because they are the same mechanism given a different
    number, and there is no sense in measuring back to both.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes

    ao3 = Ao3(repo, fileops, downloadtypes, None, False, False,
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    if job.options['dates']:
        run_custom_dates(job, fileops, ao3, downloadtypes, report)
        report_failures(ao3, report)
        return

    floor = quick_scan_floor(fileops)
    print(strings.AO3_INFO_QUICK_FLOOR.format(floor) if floor
          else strings.AO3_INFO_QUICK_NO_FLOOR)

    records: list[dict] = []
    if metadata:
        job.steps.start('index')
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)
        link = f'{bookmarks_link(job)}?{strings.AO3_SORT_BY_UPDATED}'
        records = ao3.get_metadata(link, job.options['workdates'], stop_before=floor)
        job.steps.done('index')
    else:
        job.steps.skip('index')

    download_planned(job, fileops, ao3, records, downloadtypes, report)
    report_failures(ao3, report)


def quick_scan_floor(fileops: FileOps) -> str:
    """The date a quick scan indexes back to, or '' when there is nothing to go on.

    The day the last successful **full scan or quick scan** started. Two conditions, and
    both matter:

    - it has to have **finished**. A run that failed, was stopped, or was interrupted may
      have given up before reaching works updated before it began, and treating it as a
      floor would leave exactly those unseen for ever after.
    - it has to be a run that **covered the whole listing down to its own floor**. A full
      scan reads everything; a quick scan reads everything since the previous floor, so a
      chain of them is unbroken back to a full scan. Nothing else qualifies: the combined
      run and 'just new bookmarks' stop at the first fic they recognise, an update run and
      a date window read no listing at all, and a custom run covers whatever slice it was
      told to. Any of those can finish perfectly while never looking at a fic ao3 updated
      that day, so measuring back to one would skip it permanently.
    """

    last = runs.last_successful(fileops, match=covered_the_whole_listing)
    if not last: return ''
    return str(last.get('started') or '')[:10]


def covered_the_whole_listing(record: dict) -> bool:
    """Whether a finished run reached every work ao3 had updated by the time it started.

    Only a full scan and a quick scan do. A quick scan given a **date range** does not: it
    stops at the date the user picked rather than at the previous floor, so anything older
    than that was never looked at - which is the same hole a half-covering run leaves, and
    the reason this is a question about the record rather than about the button.
    """

    if record.get('action') == ACTION_BOOKMARKS: return True
    if record.get('action') != ACTION_QUICK: return False
    return not (record.get('options') or {}).get('dates')


def run_custom(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """A full scan with its parts made optional.

    Indexing can be skipped, in which case the run works from whatever the index already
    holds - no listing is read at all, and every judgement about what is out of date is
    made against however old that index is. That is the point of the option and also its
    whole risk, which is why it is off by default.

    It can also cover a **window of time** instead of a slice of the listing. The two are
    alternatives rather than settings that combine: one picks works by where they sit in
    the listing and the other by when ao3 last touched them, and a run cannot both be
    walking a listing and not walking it.
    """

    downloadtypes = [x for x in job.filetypes if x != strings.AO3_DOWNLOAD_TYPE_METADATA]
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes
    pages = job.options['pages'] or None
    start = job.options['start']

    if job.options['dates']:
        # a window walks the sorted listing down to its own floor, so a page limit left
        # over from the other shape of this run would cut that walk short
        pages, start = None, 1

    ao3 = Ao3(repo, fileops, downloadtypes, pages, job.options['series'],
              job.options['images'], progress=report, cancelled=job.cancel.is_set,
              start=start)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    if job.options['dates']:
        run_custom_dates(job, fileops, ao3, downloadtypes, report)
        report_failures(ao3, report)
        return

    job.steps.start('index')
    if job.options['reindex'] and metadata:
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_INDEXING)
        records = ao3.get_metadata(bookmarks_link(job), job.options['workdates'])
    else:
        print(strings.AO3_INFO_USING_LAST_INDEX)
        records = shared.read_index(fileops)
        print(strings.AO3_INFO_INDEXED_COUNT.format(len(records)))
    job.steps.done('index')

    download_planned(job, fileops, ao3, records, downloadtypes, report)

    # last, and only when asked: it costs a work page per fic, which is exactly what the
    # rest of this run is built to avoid
    if job.options['images']:
        save_images(job, fileops, ao3, records, report)

    report_failures(ao3, report)


def work_link(value: str) -> str | None:
    """A work link from either a link or a bare work number.

    Pasting the number off the address bar is as natural as pasting the whole url, and both
    say the same thing. Anything else - a series, a collection, a listing, a typo - comes
    back as None so the caller refuses it before a run starts rather than after.
    """

    text = (value or '').strip()
    if not text: return None
    if text.isdigit(): return f'{strings.AO3_BASE_URL}/works/{text}'

    work = parse_text.get_work_number(text)
    if not work: return None
    if strings.AO3_DOMAIN not in text.lower(): return None
    return f'{strings.AO3_BASE_URL}/works/{work}'


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

    # whatever was decided goes into the run's history, so a library renamed months ago can
    # be explained by looking at what was asked and what was answered
    if job.record:
        job.record.choice({'question': UNDATED_QUESTION, 'count': len(undated),
                           'choice': choice, 'date': answer.get('date') or ''})

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
        return {'stale': [], 'undated': [], 'superseded': {}, 'existing': {},
                'overwrite': False}

    progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
    print(strings.AO3_INFO_CHECKING_FILES)
    existing = shared.scan_downloaded_works(fileops.downloadfolder, downloadtypes)

    overwrite = bool(job.options.get('overwrite'))

    # the undated question decides which copies count as behind, and overwriting has
    # already decided that for all of them. stopping to ask would be asking about works
    # this run is about to fetch again either way
    if overwrite:
        refresh_undated, stamped = False, 0
    else:
        refresh_undated, stamped = settle_undated(job, fileops, records, existing,
                                                  downloadtypes)

    progress.report(report, progress.PHASE, name=progress.CHECKING_VERSIONS)
    print(strings.AO3_INFO_CHECKING_VERSIONS)
    plan = shared.plan_downloads(records, existing, downloadtypes,
                                 refresh_undated=refresh_undated, overwrite=overwrite)
    plan['existing'] = existing
    # so the per-format lines can say why a current-looking copy is being fetched again
    plan['overwrite'] = overwrite

    if plan['stale'] and overwrite:
        # not 'out of date' - most of them are not, and saying so would be a lie the user
        # would reasonably act on
        print(strings.AO3_INFO_OVERWRITING.format(len(plan['stale'])))
    elif plan['stale']:
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
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3
    job.steps.start('collections')
    records = ao3.get_collections(link)
    job.steps.done('collections')

    if records:
        print(strings.AO3_INFO_COLLECTIONS_DONE.format(
            len(records), os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME)))
    else:
        print(strings.AO3_INFO_COLLECTIONS_NONE)

    # a collection crawl can leave gaps too, and used not to say so at all
    report_failures(ao3, report)


def run_collection(job: Job, fileops: FileOps, repo: Repository, report) -> None:
    """Index one collection from a link, which need not be one of the user's own.

    Written to the same downloads/collections folder, in the same shape, as the
    collections you own - so an indexed collection is an indexed collection either way.
    """

    progress.report(report, progress.PHASE, name=progress.COLLECTIONS)

    ao3 = Ao3(repo, fileops, [], None, False, False,
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3
    job.steps.start('collection')
    records = ao3.get_collection(job.url)
    job.steps.done('collection')

    if records:
        print(strings.AO3_INFO_COLLECTIONS_DONE.format(
            len(records), os.path.join(fileops.downloadfolder, strings.COLLECTIONS_FOLDER_NAME)))

    report_failures(ao3, report)


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
    ao3 = Ao3(repo, fileops, downloadtypes, None, False, job.options['images'],
              progress=report, cancelled=job.cancel.is_set)
    # the run record reads its fic lists off this when the run ends
    job.ao3 = ao3

    update_incomplete(job, fileops, ao3, downloadtypes, report)
    report_failures(ao3, report)


def update_incomplete(job: Job, fileops: FileOps, ao3: Ao3, downloadtypes: list[str],
                      report) -> None:
    """The unfinished-fics pass, on an Ao3 the caller owns.

    Split out from `run_update` so a combined run can put it after its own indexing pass
    and still report every failure from both together, on the one Ao3 that collected them.
    """

    # 1. the index, off disk. no requests at all.
    job.steps.start('read')
    progress.report(report, progress.PHASE, name=progress.SCANNING)
    print(strings.AO3_INFO_READING_INDEX)
    incomplete = newest_first(shared.incomplete_works(shared.read_index(fileops)))
    job.steps.done('read')

    if not incomplete:
        print(strings.AO3_INFO_INCOMPLETE_NONE)
        # nothing unfinished is a perfectly good answer, not a failure
        job.steps.skip('check')
        job.steps.skip('update')
        return

    print(strings.AO3_INFO_INCOMPLETE_FOUND.format(len(incomplete)))
    refresh_and_download(job, fileops, ao3, incomplete, downloadtypes, report)


def refresh_and_download(job: Job, fileops: FileOps, ao3: Ao3, records: list[dict],
                         downloadtypes: list[str], report) -> None:
    """Re-read each of these fics and fetch whatever the re-read says is needed.

    The one-fic-at-a-time pass, given a list rather than finding its own. The unfinished
    works are one way to choose that list; a window of dates is another, and both want
    exactly this afterwards - so it lives here rather than twice.

    Works are done newest first, because a run can be stopped and where it got to should be
    the half worth having.
    """

    # what is already downloaded for those works, and what to do about any of it that
    # carries no date. asked now, before a single request, because the answer decides which
    # copies count as behind.
    records = newest_first(records)
    existing: dict = {}
    refresh_undated = False
    overwrite = bool(job.options.get('overwrite'))
    # taken before this pass starts adding to it: whatever the run indexed off the listing
    # beforehand has an entry too new to be worth re-reading one fic at a time
    already_fresh = set(ao3.reindexed)
    if downloadtypes:
        job.steps.start('check')
        progress.report(report, progress.PHASE, name=progress.CHECKING_FILES)
        print(strings.AO3_INFO_CHECKING_FILES)
        existing = shared.scan_downloaded_works(fileops.downloadfolder, downloadtypes)
        # overwriting has already settled what happens to every copy, undated ones
        # included, so there is nothing left to ask about
        stamped = 0
        if not overwrite:
            refresh_undated, stamped = settle_undated(
                job, fileops, records, existing, downloadtypes)
        if stamped:
            progress.report(report, progress.REFRESH, stale=0, undated=0, stamped=stamped)
        job.steps.done('check')
    else:
        job.steps.skip('check')

    # one fic at a time: re-read it, then fetch it if the copy is behind
    job.steps.start('update')
    progress.report(report, progress.PHASE, name=progress.UPDATING)
    maximum = fileops.get_ini_value_integer(
        strings.INI_NAME_LENGTH, strings.INI_DEFAULT_NAME_LENGTH)

    checked = 0
    fetched = 0
    skipped_step = False
    for record in records:
        if job.cancel.is_set(): break
        if job.skipping():
            print(strings.AO3_INFO_STEP_SKIPPED)
            skipped_step = True
            break
        checked += 1
        try:
            fetched += update_one_work(ao3, record, existing, downloadtypes, maximum,
                                       refresh_undated, checked, len(records), report,
                                       overwrite=overwrite, already_fresh=already_fresh)
        except exceptions.CancelledException:
            # a stop is not a failed run; what has been written so far stays written
            break

    print(strings.AO3_INFO_UPDATE_DONE.format(checked, fetched))
    # a step that was abandoned must not claim to have finished
    job.steps.skip('update') if skipped_step else job.steps.done('update')


def run_custom_dates(job: Job, fileops: FileOps, ao3: Ao3, downloadtypes: list[str],
                     report) -> None:
    """The custom run's other shape: a window of time rather than a slice of the listing.

    Works are chosen from the index by when ao3 last updated them, then each is re-read and
    fetched if the copy is behind - the same per-fic pass the unfinished-fics run uses,
    given a different list.

    The index is brought up to date first, unless the run was told to skip indexing. That
    walk goes down the bookmarks listing **sorted by when ao3 last updated each work** and
    stops at the first fic older than the window's earliest date: everything past that point
    is, by definition, outside the window. The sort is what makes the stop sound - see
    `Ao3.get_metadata` - and with no earliest date there is no floor, so the walk runs to
    the end of the listing.

    It matters because the window is judged on what the index records. Skip the indexing and
    a fic whose entry is older than ao3's truth is chosen, or missed, on the strength of
    that entry. The per-fic re-read then corrects each entry it touches, which is why the
    pass re-reads before it decides what to download.
    """

    start = job.options['dateFrom']
    end = job.options['dateTo']
    metadata = strings.AO3_DOWNLOAD_TYPE_METADATA in job.filetypes

    if job.options['reindex'] and metadata:
        job.steps.start('index')
        progress.report(report, progress.PHASE, name=progress.INDEXING)
        print(strings.AO3_INFO_DATE_INDEXING.format(start) if start
              else strings.AO3_INFO_DATE_NO_FLOOR)
        # the whole index is read below rather than just what came back here: a fic in the
        # window that is no longer bookmarked is still one the window asked for
        ao3.get_metadata(f'{bookmarks_link(job)}?{strings.AO3_SORT_BY_UPDATED}',
                         job.options['workdates'], stop_before=start)
        job.steps.done('index')

    job.steps.start('read')
    progress.report(report, progress.PHASE, name=progress.SCANNING)
    print(strings.AO3_INFO_DATE_WINDOW.format(start or strings.AO3_INFO_DATE_ANY,
                                              end or strings.AO3_INFO_DATE_ANY))

    chosen = works_updated_between(shared.read_index(fileops), start, end)
    job.steps.done('read')

    if not chosen:
        print(strings.AO3_INFO_DATE_NONE)
        # an empty window is an answer, not a failure
        job.steps.skip('check')
        job.steps.skip('update')
        return

    print(strings.AO3_INFO_DATE_FOUND.format(len(chosen)))
    refresh_and_download(job, fileops, ao3, chosen, downloadtypes, report)


def works_updated_between(records: list[dict], start: str, end: str) -> list[dict]:
    """The indexed works ao3 last updated inside a window, newest first.

    Judged on the index's own `date_updated`, normalised through `get_date_stamp` so the
    two forms ao3 writes compare properly. **Both ends are inclusive**: a window of a single
    day is a real thing to ask for, and would otherwise select nothing.

    An empty bound means no limit at that end, so one date alone gives 'since then' or
    'up to then'. A work with no readable date is left out rather than guessed at - it
    cannot be placed in a window, and including it would make the window a lie.
    """

    chosen = []
    for record in records:
        updated = parse_text.get_date_stamp(record.get('date_updated') or '')
        if not updated: continue
        if start and updated < start: continue
        if end and updated > end: continue
        chosen.append(record)
    return newest_first(chosen)


def newest_first(records: list[dict]) -> list[dict]:
    """Records in the order ao3 last updated them, most recent first.

    A long run gets through the fics you are most likely to be waiting on before the ones
    that have not moved in years - which matters because a run can be stopped, and where it
    got to should be the useful half rather than an arbitrary one.

    Sorted on the normalised stamp rather than the raw field, because a listing writes
    '14 Dec 2024' and a work page writes '2024-12-14' for the same day. An entry with no
    usable date sorts last: it cannot be placed, and guessing would put it at the front.
    """

    return sorted(
        records,
        key=lambda x: parse_text.get_date_stamp(x.get('date_updated') or '') or '',
        reverse=True)


def say_what_each_format_needs(record: dict, existing: dict, filetypes: list[str],
                               plan: dict) -> list[str]:
    """Say what is going to happen to each requested format, and return the ones to fetch.

    Per format rather than per fic, because a run asking for html and pdf can want one and
    already have the other - and 'downloading it' said neither which nor why.

    The verdicts come straight out of `plan_downloads` rather than being worked out again
    here: `superseded` already names exactly the formats it decided to replace, so there is
    one definition of outdated (see **What "outdated" means, exactly**) and this only puts
    words to it.
    """

    have = existing.get(str(record.get('id') or ''), {})
    replacing = plan['superseded'].get(record.get('link') or '', {})

    wanted: list[str] = []
    for filetype in filetypes:
        copy = have.get(filetype.upper())
        if not copy:
            print(strings.AO3_INFO_FORMAT_MISSING.format(filetype))
            wanted.append(filetype)
        elif filetype in replacing:
            # a run told to overwrite replaces copies that are perfectly current, so the
            # line has to say which reason it is or it reads as a version check gone wrong
            print(strings.AO3_INFO_FORMAT_REPLACING.format(filetype) if plan.get('overwrite')
                  else strings.AO3_INFO_FORMAT_OUTDATED.format(filetype))
            wanted.append(filetype)
        elif copy['date'] is None:
            print(strings.AO3_INFO_FORMAT_UNDATED.format(filetype))
        else:
            print(strings.AO3_INFO_FORMAT_CURRENT.format(filetype))

    return wanted


def fetch_formats(ao3: Ao3, record: dict, wanted: list[str], maximum: int, log: dict,
                  done: int, total: int) -> int:
    """Download exactly the formats named, and leave the downloader as it was found.

    `download_one_indexed` fetches whatever `ao3.filetypes` holds, so asking it for one
    work used to mean asking for every format that work's run wanted - including the ones
    already on disk and current. That is a request each, spent for nothing, and rate limit
    is the scarce thing here.
    """

    keep = ao3.filetypes
    try:
        ao3.filetypes = wanted
        ao3.download_one_indexed(record, maximum, log, done, total)
    finally:
        ao3.filetypes = keep
    return 1


def update_one_work(ao3: Ao3, record: dict, existing: dict, filetypes: list[str],
                    maximum: int, refresh_undated: bool, done: int, total: int,
                    report, overwrite: bool = False,
                    already_fresh: set[str] | None = None) -> int:
    """Bring one fic's entry up to date, and fetch it again if the copy is behind.

    Says what it is doing at each step rather than only at the end, because this is the
    slow part of the run and a line per fic is the only sign it is still moving.

    `already_fresh` holds the works **this run has just indexed off the listing**. Their
    entries were written minutes ago from a blurb carrying the same `date_updated` a work
    page reports, so re-reading them costs a request each and learns nothing. On a date
    window that is the whole list - the run indexed exactly these fics moments earlier -
    so it is the difference between one request per fic and none.

    Anything *not* in that set is re-read as before. An entry from an earlier run cannot
    say whether ao3 has moved on since, and a fic in the window that is no longer
    bookmarked was never on the walk at all.

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

        if str(record.get('id') or '') in (already_fresh or set()):
            # this run wrote the entry from its own listing walk minutes ago, and a listing
            # blurb reports the same updated date a work page does. asking again would
            # spend a request to be told what we were just told
            print(strings.AO3_INFO_UPDATE_ALREADY_FRESH)
            fresh = record
        else:
            print(strings.AO3_INFO_UPDATE_READING)
            fresh = ao3.refresh_one(record)
            print(strings.AO3_INFO_UPDATE_INDEXED)

        if not filetypes:
            print(strings.AO3_INFO_UPDATE_NOTHING)
            return 0

        # the same rule a bookmarks run uses, asked about one work rather than all of them
        plan = shared.plan_downloads([fresh], existing, filetypes,
                                     refresh_undated=refresh_undated, overwrite=overwrite)
        plan['overwrite'] = overwrite
        wanted = say_what_each_format_needs(fresh, existing, filetypes, plan)

        if not wanted:
            return 0

        ao3.superseded = plan['superseded']
        return fetch_formats(ao3, fresh, wanted, maximum, log, done, total)

    except exceptions.CancelledException:
        print(strings.INFO_CANCELLED)
        raise
    except exceptions.SessionExpiredException:
        raise  # every fic after this one would fail the same way
    except Exception as e:
        ao3.record_failure(link, e)
        ao3.log_error(log, e)
        return 0


def report_failures(ao3: Ao3, report) -> None:
    """Name the works a run could not fetch, and the bookmarks that were never works.

    Both at the end, both as lists rather than counts, because either one leaves a gap
    between what was bookmarked and what is on disk - and a number alone gives nobody a way
    to find out which ones, or to go and look at them.

    They stay two separate lists on purpose. A failure is something that went wrong and
    might not next time; a skipped bookmark is a series, or a work hosted somewhere else,
    or one that has been deleted - nothing went wrong and no amount of retrying would
    change it. Putting them together would make the first look routine.
    """

    if ao3.skipped_works:
        print(strings.AO3_INFO_SKIPPED_WORKS.format(len(ao3.skipped_works)))
        progress.report(report, progress.SKIPPED, skipped=ao3.skipped_works)

    if not ao3.failures: return
    print(strings.AO3_INFO_FAILED_WORKS.format(len(ao3.failures)))
    progress.report(report, progress.FAILURES, failures=ao3.failures)


def runners() -> dict:
    """What each action actually runs.

    A table rather than a chain of elifs: that chain ended in a bare `else`, which quietly
    turned every unrecognised action into an update run, and `ACTIONS` is already the guard
    over which names are allowed.

    Built per call rather than held at module level on purpose - a module-level dict would
    capture these functions at import, so replacing one afterwards (which every test of the
    dispatch does) would change the name and not the table.
    """

    return {
        ACTION_BOOKMARKS: run_bookmarks,
        ACTION_UPDATE: run_update,
        ACTION_COLLECTIONS: run_collections,
        ACTION_COLLECTION: run_collection,
        ACTION_NEW: run_new,
        ACTION_SYNC: run_sync,
        ACTION_WORK: run_work,
        ACTION_CUSTOM: run_custom,
        ACTION_QUICK: run_quick,
    }


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

        if self.path == '/api/runs':
            # read off disk each time rather than kept in memory: the helper is restarted
            # far more often than the history is looked at, and the files are the record
            fileops = FileOps()
            self.send_json(200, {'runs': runs.read_runs(fileops)})
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

        if self.path.startswith('/api/jobs/') and self.path.endswith('/skip'):
            self.skip_step(self.path.split('/')[3])
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

        options = resolve_options(body.get('options'))
        # the option only means anything on the runs that offer it. the ui never sends it
        # otherwise, but the rule belongs here, where what arrives in a request is turned
        # into what a run may actually do - a stray flag must not make a routine run
        # re-fetch a whole library
        if action not in OVERWRITE_ACTIONS: options['overwrite'] = False
        # a custom run told to skip indexing writes no json, because json is the index
        indexing_run = options['reindex'] or action != ACTION_CUSTOM
        filetypes = resolve_filetypes(body.get('filetypes'), force=indexing_run)

        url = (body.get('url') or '').strip()
        # checked here rather than on the thread, so a bad link is a straight answer to the
        # request instead of a job that starts and immediately fails
        if action == ACTION_WORK:
            link = work_link(url)
            if not link:
                self.send_json(400, {'error': strings.ERROR_NOT_A_WORK_LINK})
                return
            # normalised now, so the run is handed a link rather than whatever was pasted
            url = link
        elif action in ACTIONS_NEEDING_URL:
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

    def skip_step(self, job_id: str) -> None:
        """Abandon the step a run is on and let it go to the next.

        A debug tool, offered only when settings.ini turns it on. It really does skip: what
        that step would have done does not happen, and the checklist marks it skipped rather
        than done so the run does not claim otherwise.
        """

        with Handler.jobs_lock:
            job = Handler.jobs.get(job_id)
        if not job:
            self.send_json(404, {'error': 'no such job'})
            return

        job.skip.set()
        self.send_json(202, {'skipping': True})

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
