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
PAGE = 'page'
WORK = 'work'
MESSAGE = 'message'
PAUSED = 'paused'
RESUMED = 'resumed'
FINISHED = 'finished'
FAILED = 'failed'


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
