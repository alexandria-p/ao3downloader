"""Structured progress reporting.

The console UI learns what is happening from print statements. The local gui server needs
the same information as data - page counts for a progress bar, rate limit pauses to show
as a warning - so the pieces that know about those emit an event as well as printing one.

Callers that pass nothing (the whole command line app) get exactly the old behaviour.
"""

from collections.abc import Callable
from typing import Any

ProgressCallback = Callable[[dict[str, Any]], None]

# event types
STARTED = 'started'
PHASE = 'phase'
AUTHENTICATED = 'authenticated'
PAGE = 'page'
WORK = 'work'
MESSAGE = 'message'
# how many downloaded works ao3 has updated since they were saved, and how many were saved
# before file names carried a date and so cannot be judged either way
REFRESH = 'refresh'
# works the run could not download, sent once at the end so the gaps can be named
FAILURES = 'failures'
PAUSED = 'paused'
RESUMED = 'resumed'
FINISHED = 'finished'
FAILED = 'failed'

# phase names, reported alongside PHASE. a run does these in order, and only the ones
# the chosen file types call for.
AUTHENTICATING = 'authenticating'
INDEXING = 'indexing'
COLLECTIONS = 'collections'
SCANNING = 'scanning'
DOWNLOADING = 'downloading'


def report(callback: ProgressCallback | None, kind: str, **fields: Any) -> None:
    """Send one progress event.

    A listener that raises must never take a download down with it, so anything thrown
    by the consumer is swallowed here.
    """

    if callback is None: return
    try:
        callback({'type': kind, **fields})
    except Exception:
        pass
