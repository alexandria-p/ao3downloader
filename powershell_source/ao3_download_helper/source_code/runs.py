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
                 printed: list[str] | None = None) -> None:
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
            # everything the run printed, in order - the same account the modal shows,
            # kept because the modal is gone once the tab is closed
            'log': list(printed or []),
            # how many lines had to be dropped to stay under the ceiling, so a trimmed log
            # says so rather than silently beginning in the middle
            'logTrimmed': 0,
            'error': '',
        }
        self.save()

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
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

    def collect(self, ao3) -> None:
        """Take the fic lists off the downloader that has been gathering them."""

        if ao3 is None: return
        self.data['reindexed'] = sorted(ao3.reindexed)
        self.data['downloaded'] = sorted(ao3.downloaded)
        self.data['updated'] = sorted(ao3.updated)
        self.data['failures'] = list(ao3.failures)
        self.data['skipped'] = list(ao3.skipped_works)

    def finish(self, status: str, error: str = '') -> None:
        self.data['status'] = status
        self.data['error'] = error
        self.data['finished'] = now()
        self.save()


def read_runs(fileops, limit: int = 100) -> list[dict]:
    """Every run on record, newest first.

    A file that cannot be read is skipped rather than ending the listing - one damaged
    record should not hide the history around it.
    """

    folder = fileops.runsfolder
    if not os.path.isdir(folder): return []

    found: list[dict] = []
    for name in sorted(os.listdir(folder), reverse=True):
        if not name.lower().endswith('.json'): continue
        try:
            with open(os.path.join(folder, name), encoding='utf-8') as f:
                record = json.load(f)
            if isinstance(record, dict):
                record['file'] = name
                found.append(record)
        except Exception:
            continue
        if len(found) >= limit: break
    return found


def last_successful(fileops) -> dict | None:
    """The most recent run that actually finished, or None if there has never been one.

    What 'up to the last run' means for a quick scan. A run that failed, was stopped, or
    was interrupted is **not** a floor to index down to: it may have stopped before
    reaching fics that were updated before it started, and trusting it would leave exactly
    those unseen.
    """

    for record in read_runs(fileops):
        if record.get('status') == STATUS_SUCCESS: return record
    return None
