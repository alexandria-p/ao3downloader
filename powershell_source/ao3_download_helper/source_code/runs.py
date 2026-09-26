"""One json file per run: what it set out to do, and what became of it.

Separate from `logs/log.jsonl`, which records individual requests and is written for
debugging. This is the run as a whole - which button, which settings, which fics it touched
and how it ended - and is what the history page reads.

**The file is written when the run starts, not when it ends.** A record still saying
`running` after the helper has gone is how an interrupted run is recognised: a run killed
mid-flight cannot write its own epitaph, so the absence of an ending is the evidence.
"""

import datetime
import json
import os

from source_code import strings


# how a run ended. 'running' is also the state a run is left in when it never got to
# finish - see the module docstring.
STATUS_RUNNING = 'running'
STATUS_SUCCESS = 'success'
STATUS_FAILED = 'failed'
STATUS_STOPPED = 'stopped'
# a run that never wrote its ending - the page left, or the helper stopped - once the page
# has checked the helper is not still working on it. the helper never writes this itself
STATUS_INTERRUPTED = 'interrupted'

# How much of the console output one record keeps, and how often it reaches disk.
#
# The whole file is rewritten on every save, so saving per line would mean thousands of
# writes of a growing file over a long run. Batching keeps that to one write per batch,
# while still leaving an interrupted run's output nearly complete - which is exactly the
# run whose output is worth having.
LOG_FLUSH_EVERY = 25

# A run over a large library prints a line per fic per format, so this is a ceiling rather
# than an expectation; most runs never approach it. The **last** lines are kept when it is
# reached, because whatever went wrong is at the end.
LOG_MAX_LINES = 5000


def now() -> str:
    """The moment, to the second, in a form that sorts and survives a file name."""

    return datetime.datetime.now().replace(microsecond=0).isoformat()


class RunRecord:
    """What one run did, written as it happens.

    Every method swallows its own errors. A history file is a convenience, and a run that
    downloaded a library successfully must not be reported as failed because a note about
    it could not be written.
    """

    def __init__(self, fileops, job_id: str, action: str, action_name: str,
                 filetypes: list[str], options: dict,
                 printed: list[str] | None = None,
                 settings: dict | None = None) -> None:
        self.fileops = fileops
        # lines counted since the last write, not since the run began
        self.unsaved = 0
        self.path = os.path.join(
            fileops.runsfolder, f'{now().replace(":", "")}-{job_id[:8]}.json')
        self.data: dict = {
            'id': job_id,
            'action': action,
            'actionName': action_name,
            'started': now(),
            'finished': None,
            'status': STATUS_RUNNING,
            'filetypes': list(filetypes),
            'options': dict(options or {}),
            # what settings.ini said at the time. it decides pacing, file naming and
            # retries, so a run cannot be explained afterwards without it - and which
            # settings.ini was in force depends on where the helper was started from,
            # which is why the path it was read from is part of this
            'settings': dict(settings or {}),
            # the fics this run touched, and in which way. kept apart because they answer
            # different questions: what got a fresh index entry, what arrived as a file,
            # and what replaced a copy that was already there.
            'reindexed': [],
            'downloaded': [],
            'updated': [],
            # anything the run stopped to ask, and what was answered
            'choices': [],
            'failures': [],
            'skipped': [],
            # new copies downloaded while the older copy could not be safely deleted
            'keptCopies': [],
            # older copies of a work the run decided to remove, and what became of each:
            # `pending` until the cleanup step, then `removed`, or `kept` with the reason.
            # written the moment they are marked, so a run that dies first still says which
            'removals': [],
            # everything the run printed, in order - the same account the modal shows,
            # kept because the modal is gone once the tab is closed
            'log': list(printed or []),
            # how many lines had to be dropped to stay under the ceiling, so a trimmed log
            # says so rather than silently beginning in the middle
            'logTrimmed': 0,
            'error': '',
            # the moment the login succeeded - what a later quick scan measures back to. a
            # resumed run carries the first attempt's, since it is finishing that run's work
            'baseline': None,
            # the run this one picks up from, and the first attempt of the chain it belongs to
            'resumes': None,
            'resumesFirst': None,
            # how far the run got, written as it goes, so it can be resumed - see RESUMING.md
            'progress': {},
        }
        self.save()

    def logged_in(self, baseline: str, resumes: str | None = None,
                  first: str | None = None) -> None:
        self.data['baseline'] = baseline
        if resumes:
            self.data['resumes'] = resumes
            self.data['resumesFirst'] = first or resumes
        self.save()

    def checkpoint(self, **fields) -> None:
        """Record how far the run has got. Written straight away: a checkpoint that waits
        for a batch is one an interrupted run never gets to write."""

        try:
            self.data['progress'].update(fields)
        except Exception:
            return
        self.save()

    def save(self) -> None:
        try:
            # through the library's own storage, so a run writing to Dropbox keeps its
            # history there too, beside the works it describes
            self.fileops.write_text(self.path, json.dumps(self.data, indent=2))
            self.unsaved = 0
        except Exception:
            # a note about the run is not worth taking the run down for
            pass

    def line(self, text: str) -> None:
        """Keep one line of console output, writing to disk in batches.

        Not saved per line on purpose: `save` rewrites the whole file, so a run printing a
        line per fic per format would rewrite a growing file thousands of times. A batch
        loses at most the last few lines of a run that is killed outright, and everything
        else - a stop, a failure, a finish - goes through `save` anyway.
        """

        try:
            log = self.data['log']
            log.append(text)
            if len(log) > LOG_MAX_LINES:
                # the end is where whatever went wrong is, so the start is what gives way
                dropped = len(log) - LOG_MAX_LINES
                del log[:dropped]
                self.data['logTrimmed'] += dropped
            self.unsaved += 1
            if self.unsaved >= LOG_FLUSH_EVERY: self.save()
        except Exception:
            pass

    def choice(self, entry: dict) -> None:
        """Record something the run stopped to ask, and what came back."""

        self.data['choices'].append({'at': now(), **entry})
        self.save()

    def amend_choice(self, fields: dict) -> None:
        """Add what came of the last answer to it, once the run has acted on it.

        The choice itself is written the moment it is answered, so a run that dies while
        acting on it still shows what was decided; this fills in the outcome afterwards.
        """

        try:
            if not self.data['choices']: return
            self.data['choices'][-1].update(fields)
            self.save()
        except Exception:
            pass

    def removals(self, items: list[dict]) -> None:
        """Record the older copies marked for removal, or what has since become of them."""

        try:
            self.data['removals'] = [{k: v for k, v in x.items() if k != 'path'} for x in items]
            self.save()
        except Exception:
            pass

    def collect(self, ao3) -> None:
        """Take the fic lists off the downloader that has been gathering them."""

        if ao3 is None: return
        self.data['reindexed'] = sorted(ao3.reindexed)
        self.data['downloaded'] = sorted(ao3.downloaded)
        self.data['updated'] = sorted(ao3.updated)
        self.data['failures'] = list(ao3.failures)
        self.data['skipped'] = list(ao3.skipped_works)
        kept = getattr(ao3, 'kept_copies', None)
        self.data['keptCopies'] = list(kept) if isinstance(kept, list) else []

    def finish(self, status: str, error: str = '') -> None:
        self.data['status'] = status
        self.data['error'] = error
        self.data['finished'] = now()
        self.save()


def read_runs(fileops, limit: int = 100, with_log: bool = False) -> list[dict]:
    """Every run on record, newest first.

    A file that cannot be read is skipped rather than ending the listing - one damaged
    record should not hide the history around it.

    **The console log is left out by default.** A record can hold thousands of lines, and a
    hundred of them in one response would be tens of megabytes to build a page that does not
    show them. `logLines` says how many the file holds, so the listing can still mention it;
    the lines themselves are in the file.
    """

    folder = fileops.runsfolder
    try:
        names = fileops.list_files(folder)
    except Exception:
        return []

    found: list[dict] = []
    for name in sorted(names, reverse=True):
        if not name.lower().endswith('.json'): continue
        try:
            record = json.loads(fileops.read_text(os.path.join(folder, name)))
            if isinstance(record, dict):
                record['file'] = name
                if not with_log:
                    record['logLines'] = len(record.get('log') or [])
                    record.pop('log', None)
                found.append(record)
        except Exception:
            continue
        if len(found) >= limit: break
    return found


def baseline_of(record: dict) -> str:
    """When a run's reach begins: the moment its login succeeded, or - for a resumed run -
    the first attempt's. Older records have no baseline, and their start is the nearest."""

    return str(record.get('baseline') or record.get('started') or '')


def find_run(fileops, run_id: str) -> dict | None:
    """One run's record by its id, with the name of the file it is in."""

    if not run_id: return None
    for record in read_runs(fileops, limit=100000):
        if str(record.get('id') or '') == run_id: return record
    return None


def amend_run(fileops, name: str, fields: dict) -> None:
    """Add fields to another run's record - how a run it resumed is told so."""

    try:
        path = os.path.join(fileops.runsfolder, name)
        record = json.loads(fileops.read_text(path))
        record.update(fields)
        fileops.write_text(path, json.dumps(record, indent=2))
    except Exception:
        pass


def last_successful(fileops, match=None) -> dict | None:
    """The most recent run that actually finished, or None if there has never been one.

    What 'up to the last run' means for a quick scan. A run that failed, was stopped, or
    was interrupted is **not** a floor to index down to: it may have stopped before
    reaching fics that were updated before it started, and trusting it would leave exactly
    those unseen.

    `match` narrows it to the runs that are a floor at all. Finishing is not enough on its
    own: most runs cover only part of the listing, so a successful one says nothing about
    works it was never looking at. It takes a record and answers whether that run qualifies,
    rather than a list of action names, because whether a run covered everything can depend
    on the options it ran with and not only on which button it was. The caller decides -
    this module deliberately knows nothing about what any of that means.
    """

    for record in read_runs(fileops):
        if record.get('status') != STATUS_SUCCESS: continue
        if match is not None and not match(record): continue
        return record
    return None
