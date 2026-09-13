"""Custom exceptions go here."""


class Ao3DownloaderException(Exception):
    pass


class TimeoutException(Ao3DownloaderException):
    pass


class LockedException(Ao3DownloaderException):
    pass


class DeletedException(Ao3DownloaderException):
    pass


class HiddenException(Ao3DownloaderException):
    pass


class ProceedException(Ao3DownloaderException):
    pass


class DownloadException(Ao3DownloaderException):
    pass


class LoginException(Ao3DownloaderException):
    pass


class InvalidLinkException(Ao3DownloaderException):
    pass


class InvalidStatusCodeException(Ao3DownloaderException):
    pass


class CloudflareException(Ao3DownloaderException):
    pass


class PdfParsingException(Ao3DownloaderException):
    pass


class SeriesLinkException(Ao3DownloaderException):
    pass


class CancelledException(Ao3DownloaderException):
    """Raised when a caller asks for a run to stop. Unwinds to the nearest handler,
    which keeps whatever was already written rather than discarding it."""
    pass


class SessionExpiredException(Ao3DownloaderException):
    """Raised when ao3 has stopped recognising the login this run started with.

    Ends the run rather than being recorded per work. Once the session is gone every
    restricted work fails for the same reason, and grinding through hundreds of them
    produces a failure list that says nothing and spends the rate limit saying it."""
    pass


class PausedException(Ao3DownloaderException):
    """Raised when a pause arrives while a response body is still coming down.

    Control flow, not an error. It never leaves `Repository.my_request`: the part-read body
    is thrown away, the run waits, and then the *same* request is made again from the start.
    Nothing has reached disk at that point, so there is nothing to undo."""
    pass
