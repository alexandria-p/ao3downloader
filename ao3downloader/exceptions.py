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
