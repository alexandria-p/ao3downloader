"""Where the downloads folder actually lives: on this computer, or in Dropbox.

Everything that reads or writes the library goes through one of these. The rest of the
helper still builds paths the way it always has - `os.path.join(fileops.downloadfolder,
...)` - and hands them here, so a run does not know or care which of the two it is writing
to. That is the point: all the rules about what is outdated, what may be replaced and what
counts as saved stay exactly where they are, and only the last step changes.

**A Dropbox path is a local-looking path under a root that says so.** `DropboxStorage.root`
is `dropbox:` followed by the chosen folder's Dropbox path, so `os.path.join` builds
`dropbox:/Fics\\indexing\\123 A Fic.json` on Windows as happily as it builds a real path,
and `remote` turns that back into `/Fics/indexing/123 A Fic.json`. The prefix also means a
Dropbox path can never be mistaken for a real one and opened on disk by accident - there is
no drive or folder called `dropbox:`.

The request log and settings.ini stay on this computer either way. They belong to the
helper, not to the library.
"""

import json
import os
import time
from typing import Callable, Iterable

import requests

from source_code import strings


class LocalStorage:
    """The downloads folder as a folder on this computer - exactly what the helper always did."""

    def __init__(self, root: str) -> None:
        self.root = root

    def describe(self, path: str) -> str:
        return os.path.abspath(path)

    def ensure_root(self) -> None:
        os.makedirs(self.root, exist_ok=True)

    def make_dirs(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)

    def read_bytes(self, path: str) -> bytes:
        with open(path, 'rb') as f:
            return f.read()

    def write_bytes(self, path: str, content: bytes) -> None:
        folder = os.path.dirname(path)
        if folder: os.makedirs(folder, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(content)

    def size(self, path: str) -> int | None:
        """A file's length, or None when there is no file there."""

        try:
            return os.path.getsize(path) if os.path.isfile(path) else None
        except OSError:
            return None

    def is_file(self, path: str) -> bool:
        return os.path.isfile(path)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def list_files(self, folder: str) -> list[str]:
        """The names of the files directly inside `folder`; none when it is not there."""

        if not os.path.isdir(folder): return []
        return [x for x in os.listdir(folder) if os.path.isfile(os.path.join(folder, x))]

    def files_under(self, folder: str, skip: set[str] = frozenset()) -> list[str]:
        """Every file below `folder`, as a path, leaving out any folder named in `skip`."""

        found = []
        if not folder or not os.path.isdir(folder): return found
        for subdir, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in skip]
            found.extend(os.path.join(subdir, f) for f in files)
        return found

    def delete(self, path: str) -> bool:
        """Remove a file, reporting whether it went. A file already gone counts as done."""

        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def rename(self, old: str, new: str) -> bool:
        """Rename a file, refusing to write over anything already at the new name."""

        try:
            if os.path.exists(new): return False
            os.rename(old, new)
            return True
        except OSError:
            return False

    def same_file(self, a: str, b: str) -> bool:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


# region Dropbox

TOKEN_URL = 'https://api.dropboxapi.com/oauth2/token'
API_URL = 'https://api.dropboxapi.com/2/'
CONTENT_URL = 'https://content.dropboxapi.com/2/'

ROOT_PREFIX = 'dropbox:'

# a busy Dropbox asks for a pause rather than failing outright. these are its waits, not a
# retry budget for real errors - those are raised straight away
MAX_BUSY_RETRIES = 6
MAX_BUSY_WAIT_SECONDS = 60
# refresh a little before the access token runs out, so none expires in the middle of a call
EXPIRY_MARGIN_SECONDS = 60
TIMEOUT_SECONDS = 120


class DropboxError(Exception):
    """A Dropbox call that failed, with Dropbox's own `error_summary` when it gave one."""

    def __init__(self, message: str, status: int = 0, summary: str = '') -> None:
        super().__init__(message)
        self.status = status
        self.summary = summary


def api_arg(value: dict) -> str:
    """The `Dropbox-API-Arg` header for a content call.

    A header has to be plain ascii, and fic titles are anything but, so every other
    character goes as a `\\uXXXX` escape - which Dropbox reads back as json. `ensure_ascii`
    does all of that except DEL, which Dropbox also asks to be escaped.
    """

    return json.dumps(value, ensure_ascii=True).replace('\x7f', '\\u007f')


class DropboxClient:
    """Authenticated calls to Dropbox, refreshing the access token as it runs out.

    Built from the refresh token the web page signed in for, and the app's key - a PKCE
    sign-in needs no secret to refresh, which is why there is none here. The refresh token
    is held in memory for the run and never written anywhere by the helper.
    """

    def __init__(self, app_key: str, refresh_token: str,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.app_key = app_key
        self.refresh_token = refresh_token
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.access_token = ''
        self.expires_at = 0.0

    def rpc(self, endpoint: str, args: dict | None = None) -> dict:
        """One call to an api endpoint that takes json and answers json."""

        response = self.send(API_URL + endpoint, lambda token: {
            'headers': {'Authorization': f'Bearer {token}',
                        **({'Content-Type': 'application/json'} if args is not None else {})},
            'data': json.dumps(args).encode('utf-8') if args is not None else None,
        })
        return response.json() if response.content else {}

    def upload(self, path: str, content: bytes) -> dict:
        """Write one file, replacing whatever is at that path. Answers its metadata."""

        arg = api_arg({'path': path, 'mode': 'overwrite', 'autorename': False, 'mute': True})
        response = self.send(CONTENT_URL + 'files/upload', lambda token: {
            'headers': {'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/octet-stream',
                        'Dropbox-API-Arg': arg},
            'data': content,
        })
        return response.json()

    def download(self, path: str) -> bytes:
        arg = api_arg({'path': path})
        response = self.send(CONTENT_URL + 'files/download', lambda token: {
            'headers': {'Authorization': f'Bearer {token}', 'Dropbox-API-Arg': arg},
            'data': None,
        })
        return response.content

    def send(self, url: str, build: Callable[[str], dict]) -> requests.Response:
        """Make a call, dealing with the two things Dropbox asks callers to deal with.

        An expired access token is refreshed and the call made once more. A 429 - too many
        requests, or too many writes to the same folder at once - is waited out for as long
        as Dropbox says and tried again. Anything else is raised as a `DropboxError`.
        """

        refreshed = False
        busy = 0
        while True:
            request = build(self.token(force=False))
            response = self.session.post(url, headers=request['headers'],
                                         data=request['data'], timeout=TIMEOUT_SECONDS)
            if response.status_code == 401 and not refreshed:
                refreshed = True
                self.token(force=True)
                continue
            if response.status_code == 429 and busy < MAX_BUSY_RETRIES:
                busy += 1
                self.sleep(retry_after(response, busy))
                continue
            if response.status_code >= 500 and busy < MAX_BUSY_RETRIES:
                busy += 1
                self.sleep(min(2 ** busy, MAX_BUSY_WAIT_SECONDS))
                continue
            if response.ok: return response
            raise error_from(response)

    def token(self, force: bool) -> str:
        if not force and self.access_token and self.clock() < self.expires_at - EXPIRY_MARGIN_SECONDS:
            return self.access_token
        response = self.session.post(TOKEN_URL, data={
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.app_key,
        }, timeout=TIMEOUT_SECONDS)
        if not response.ok:
            error = error_from(response)
            raise DropboxError(strings.ERROR_DROPBOX_SIGNED_OUT.format(error), response.status_code,
                               error.summary)
        body = response.json()
        self.access_token = body['access_token']
        self.expires_at = self.clock() + float(body.get('expires_in', 14400))
        return self.access_token


def retry_after(response: requests.Response, attempt: int) -> float:
    try:
        wait = float(response.headers.get('Retry-After', ''))
    except ValueError:
        wait = 2 ** attempt
    return max(0.0, min(wait, MAX_BUSY_WAIT_SECONDS))


def error_from(response: requests.Response) -> DropboxError:
    summary = ''
    detail = ''
    try:
        body = response.json()
        summary = body.get('error_summary') or (body.get('error') if isinstance(body.get('error'), str) else '') or ''
        detail = body.get('error_description') or summary
    except ValueError:
        detail = (response.text or '').strip()
    return DropboxError(detail or f'Dropbox answered {response.status_code}',
                        response.status_code, summary)


def not_found(error: DropboxError) -> bool:
    """Whether Dropbox said there is nothing at that path, which several calls treat as an answer."""

    return error.status == 409 and 'not_found' in error.summary


class DropboxStorage:
    """The downloads folder as a folder in Dropbox, inside the app's own folder.

    `folder_path` is the chosen folder as Dropbox names it, `''` being the app folder
    itself. Sizes Dropbox reported for files this run uploaded are kept, so confirming that
    a download arrived intact does not cost a second request per file - the upload's own
    answer *is* Dropbox saying what it stored.
    """

    def __init__(self, client: DropboxClient, folder_path: str) -> None:
        self.client = client
        self.folder_path = folder_path.rstrip('/')
        self.root = ROOT_PREFIX + self.folder_path
        self.sizes: dict[str, int] = {}
        # every file in the library, lower-cased, read in one listing the first time anything
        # asks whether a file is there. `shared.visited` asks that of every work in the log,
        # in every format - a request each would be thousands per run. kept current as this
        # run writes, deletes and renames; a change made elsewhere mid-run goes unseen, which
        # is the same as a local folder changed behind a run's back
        self.known: set[str] | None = None

    @classmethod
    def connect(cls, client: DropboxClient, folder_id: str, folder_path: str) -> 'DropboxStorage':
        """Open the folder the page chose, finding it by id when there is one.

        The id is what survives the folder being renamed or moved since the page last
        looked, so it wins over the path. A folder that is gone altogether is an error
        naming it, raised before a run has done anything.
        """

        path = folder_path
        if folder_id:
            try:
                meta = client.rpc('files/get_metadata', {'path': folder_id})
            except DropboxError as e:
                if not_found(e):
                    raise DropboxError(strings.ERROR_DROPBOX_FOLDER_GONE.format(folder_path or '/'),
                                       e.status, e.summary) from e
                raise
            if meta.get('.tag') != 'folder':
                raise DropboxError(strings.ERROR_DROPBOX_FOLDER_GONE.format(folder_path or '/'))
            path = meta.get('path_display', folder_path)
        return cls(client, path)

    # region paths

    def remote(self, path: str) -> str:
        """The Dropbox path for one of ours. Anything outside the chosen folder is refused."""

        normal = str(path).replace('\\', '/')
        # dropbox paths ignore case, so the check does too
        inside = normal.lower()
        root = self.root.lower()
        if inside != root and not inside.startswith(root + '/'):
            raise ValueError(f'{path} is not inside the Dropbox folder {self.root}')
        rest = normal[len(self.root):].rstrip('/')
        # collapse any doubled separators os.path.join may have left
        while '//' in rest: rest = rest.replace('//', '/')
        return self.folder_path + rest

    def local(self, remote: str) -> str:
        """One of ours, for a Dropbox path inside the chosen folder."""

        return self.root + remote[len(self.folder_path):]

    def describe(self, path: str) -> str:
        # the app folder is the library, and its name is the App Console's business, so it
        # is called what it is - the page says it the same way
        return 'Dropbox app folder' + self.remote(path)

    def same_file(self, a: str, b: str) -> bool:
        # dropbox paths are case-insensitive, so two spellings of one name are one file
        return self.remote(a).lower() == self.remote(b).lower()

    # endregion

    def ensure_root(self) -> None:
        """Check the folder is still there. The app folder itself always is."""

        if not self.folder_path: return
        try:
            meta = self.client.rpc('files/get_metadata', {'path': self.folder_path})
        except DropboxError as e:
            if not_found(e):
                raise DropboxError(strings.ERROR_DROPBOX_FOLDER_GONE.format(self.folder_path),
                                   e.status, e.summary) from e
            raise
        if meta.get('.tag') != 'folder':
            raise DropboxError(strings.ERROR_DROPBOX_FOLDER_GONE.format(self.folder_path))

    def make_dirs(self, path: str) -> None:
        # dropbox creates the folders above a file as it writes one, and an empty folder
        # made ahead of time would only be clutter if the run never writes into it
        pass

    def read_bytes(self, path: str) -> bytes:
        try:
            return self.client.download(self.remote(path))
        except DropboxError as e:
            if not_found(e): raise FileNotFoundError(path) from e
            raise

    def write_bytes(self, path: str, content: bytes) -> None:
        remote = self.remote(path)
        meta = self.client.upload(remote, content)
        self.sizes[remote.lower()] = int(meta.get('size', -1))
        if self.known is not None: self.known.add(remote.lower())

    def listing(self) -> set[str]:
        if self.known is None:
            self.known = {self.remote(x).lower() for x in self.files_under(self.root)}
        return self.known

    def metadata(self, path: str) -> dict | None:
        try:
            return self.client.rpc('files/get_metadata', {'path': self.remote(path)})
        except DropboxError as e:
            if not_found(e): return None
            raise

    def size(self, path: str) -> int | None:
        remote = self.remote(path)
        if remote.lower() in self.sizes: return self.sizes[remote.lower()]
        meta = self.metadata(path)
        if not meta or meta.get('.tag') != 'file': return None
        return int(meta.get('size', 0))

    def is_file(self, path: str) -> bool:
        return self.remote(path).lower() in self.listing()

    def exists(self, path: str) -> bool:
        # only files are ever asked about - whether a download or a rename target is there
        return self.is_file(path)

    def entries(self, folder: str, recursive: bool) -> Iterable[dict]:
        try:
            page = self.client.rpc('files/list_folder', {
                'path': self.remote(folder), 'recursive': recursive,
                'include_deleted': False, 'limit': 2000})
        except DropboxError as e:
            if not_found(e): return
            raise
        while True:
            yield from page.get('entries', [])
            if not page.get('has_more'): return
            page = self.client.rpc('files/list_folder/continue', {'cursor': page['cursor']})

    def list_files(self, folder: str) -> list[str]:
        return [x['name'] for x in self.entries(folder, recursive=False) if x.get('.tag') == 'file']

    def files_under(self, folder: str, skip: set[str] = frozenset()) -> list[str]:
        """Every file below `folder` in one recursive listing - a page per 2,000 entries,
        rather than a call per folder - leaving out anything under a folder named in `skip`."""

        base = self.remote(folder)
        skipped = {x.lower() for x in skip}
        found = []
        for entry in self.entries(folder, recursive=True):
            if entry.get('.tag') != 'file': continue
            remote = entry.get('path_display') or entry.get('path_lower', '')
            inside = remote[len(base):].strip('/').split('/')
            if any(part.lower() in skipped for part in inside[:-1]): continue
            found.append(self.local(base + '/' + '/'.join(inside)))
        return found

    def delete(self, path: str) -> bool:
        """Move a file to the Dropbox trash. A file already gone counts as done.

        Deleted files stay restorable from dropbox.com for a while, so a copy removed here
        is recoverable in a way a local delete is not.
        """

        remote = self.remote(path)
        try:
            self.client.rpc('files/delete_v2', {'path': remote})
        except DropboxError as e:
            if not not_found(e): return False
        self.sizes.pop(remote.lower(), None)
        if self.known is not None: self.known.discard(remote.lower())
        return True

    def rename(self, old: str, new: str) -> bool:
        """Rename a file, refusing to write over anything already at the new name."""

        try:
            self.client.rpc('files/move_v2', {'from_path': self.remote(old),
                                              'to_path': self.remote(new),
                                              'autorename': False})
        except (DropboxError, ValueError):
            return False
        size = self.sizes.pop(self.remote(old).lower(), None)
        if size is not None: self.sizes[self.remote(new).lower()] = size
        if self.known is not None:
            self.known.discard(self.remote(old).lower())
            self.known.add(self.remote(new).lower())
        return True

# endregion
