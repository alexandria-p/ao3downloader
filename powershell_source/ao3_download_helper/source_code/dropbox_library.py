"""The library in Dropbox, reached by the helper itself - for a run in the background.

An ordinary run reads and writes the library through the page (`storage.PageStorage` asking
the page, which asks Dropbox), so the helper never holds a Dropbox token. A **background run**
is one the page is not there for: it is started, the tab is closed, and the run carries on
for hours. So the page hands over what it signed in with - the refresh token and the app key,
nothing else - and this answers the same requests the page would have, in the same shapes
(`library-store.ts`, `answerStorage`). `PageStorage` is put in front of it unchanged, so its
caches, and every rule behind it about what may be written or deleted, stay exactly as they
are for a run through the page.

**Only for a Dropbox library.** A folder on the user's computer can only be reached through
the page, which is why the option is not offered for one.

The token lives in this object and nowhere else: it is not written to disk, logged, or put
in the run's history, and it goes when the run does. The Dropbox app is scoped to its own
app folder, so that is all it can reach.
"""

import json
import time

import requests


TOKEN_URL = 'https://api.dropboxapi.com/oauth2/token'
API_URL = 'https://api.dropboxapi.com/2/'
CONTENT_URL = 'https://content.dropboxapi.com/2/'

# refresh this long before the access token runs out, so none expires in the middle of a call
EXPIRY_MARGIN_SECONDS = 5 * 60
# how long one request may take. a fic is small, but Dropbox can be slow to answer
TIMEOUT_SECONDS = 120
# Dropbox answers 429 when it wants requests to slow down, and 5xx when it is struggling;
# both are worth waiting out a few times before a run gives up on a file
RETRIES = 5
DEFAULT_RETRY_AFTER_SECONDS = 5


class DropboxError(Exception):
    """A request Dropbox refused, with the summary it gave (`path/not_found/..`)."""

    def __init__(self, summary: str, status: int) -> None:
        super().__init__(f'Dropbox refused the request: {summary or status}')
        self.summary = summary
        self.status = status


def remote(path: str) -> str:
    """A library path as the Dropbox api names it: `''` for the app folder, `/works/x` below."""

    clean = '/'.join(part for part in str(path or '').replace('\\', '/').split('/') if part)
    return f'/{clean}' if clean else ''


class DropboxChannel:
    """Answers `PageStorage`'s requests by talking to Dropbox directly."""

    def __init__(self, refresh_token: str, app_key: str, session=None,
                 sleep=time.sleep, clock=time.monotonic) -> None:
        self.refresh_token = refresh_token
        self.app_key = app_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.access_token = ''
        self.expires_at = 0.0

    # region what PageStorage asks

    def storage_call(self, op: str, args: dict, content: bytes | None = None) -> dict:
        """One request, answered as the page answers it: every failure is `{error}`."""

        path = remote(args.get('path') or '')
        try:
            if op == 'check':
                # the page checks it is still signed in; here that is whether a token comes
                self.token()
                return {}
            if op == 'mkdir':
                self.make_folder(path)
                return {}
            if op == 'list':
                return {'files': self.list_files(path, bool(args.get('recursive')))}
            if op == 'read':
                text = self.read(path)
                return {'missing': True} if text is None else {'text': text}
            if op == 'write':
                return {'size': self.upload(path, content or b'')}
            if op == 'size':
                return {'size': self.file_size(path)}
            if op == 'delete':
                self.delete(path)
                return {}
            if op == 'rename':
                self.call('files/move_v2', {'from_path': path, 'to_path': remote(args.get('to')),
                                            'autorename': False})
                return {}
            return {'error': f'the helper does not know how to {op} in Dropbox'}
        except Exception as e:
            return {'error': str(e)}

    # endregion

    # region Dropbox

    def list_files(self, path: str, recursive: bool) -> list[str]:
        """Every file below `path`, as library paths. A folder that is not there is empty."""

        try:
            page = self.call('files/list_folder', {'path': path, 'recursive': recursive,
                                                   'limit': 2000})
        except DropboxError as e:
            if e.summary.startswith('path/not_found'): return []
            raise
        files = []
        while True:
            for entry in page.get('entries') or []:
                if entry.get('.tag') == 'file':
                    files.append(str(entry.get('path_display') or '').lstrip('/'))
            if not page.get('has_more'): break
            page = self.call('files/list_folder/continue', {'cursor': page.get('cursor')})
        return files

    def read(self, path: str) -> str | None:
        try:
            response = self.send(CONTENT_URL + 'files/download',
                                 headers={'Dropbox-API-Arg': api_arg({'path': path})})
        except DropboxError as e:
            if 'not_found' in e.summary: return None
            raise
        return response.content.decode('utf-8')

    def upload(self, path: str, content: bytes) -> int:
        """Put one file in place, replacing what is there, and say the size Dropbox stored."""

        response = self.send(CONTENT_URL + 'files/upload', data=content, headers={
            'Content-Type': 'application/octet-stream',
            'Dropbox-API-Arg': api_arg({'path': path, 'mode': 'overwrite',
                                        'autorename': False, 'mute': True}),
        })
        return int((response.json() or {}).get('size', len(content)))

    def file_size(self, path: str) -> int | None:
        try:
            meta = self.call('files/get_metadata', {'path': path})
        except DropboxError as e:
            if 'not_found' in e.summary: return None
            raise
        return int(meta.get('size') or 0) if meta.get('.tag') == 'file' else None

    def delete(self, path: str) -> None:
        """Into the Dropbox trash, where it can still be restored. One already gone is fine."""

        try:
            self.call('files/delete_v2', {'path': path})
        except DropboxError as e:
            if 'not_found' in e.summary: return
            raise

    def make_folder(self, path: str) -> None:
        if not path: return
        try:
            self.call('files/create_folder_v2', {'path': path, 'autorename': False})
        except DropboxError as e:
            if e.summary.startswith('path/conflict'): return
            raise

    # endregion

    # region calls

    def call(self, endpoint: str, args: dict) -> dict:
        response = self.send(API_URL + endpoint, data=json.dumps(args).encode('utf-8'),
                             headers={'Content-Type': 'application/json'})
        return response.json() if response.content else {}

    def send(self, url: str, data: bytes | None = None, headers: dict | None = None):
        """POST with a current token. An expired one is refreshed and the call made once more;
        a request to slow down, or a server error, is waited out a few times."""

        refreshed = False
        for attempt in range(RETRIES + 1):
            response = self.session.post(
                url, data=data, timeout=TIMEOUT_SECONDS,
                headers={**(headers or {}), 'Authorization': f'Bearer {self.token()}'})
            if response.status_code == 401 and not refreshed:
                self.expires_at = 0
                refreshed = True
                continue
            if (response.status_code == 429 or response.status_code >= 500) and attempt < RETRIES:
                self.sleep(retry_after(response))
                continue
            if response.ok: return response
            raise error_from(response)
        raise error_from(response)

    def token(self) -> str:
        if self.access_token and self.clock() < self.expires_at - EXPIRY_MARGIN_SECONDS:
            return self.access_token
        response = self.session.post(TOKEN_URL, timeout=TIMEOUT_SECONDS, data={
            'grant_type': 'refresh_token', 'refresh_token': self.refresh_token,
            'client_id': self.app_key})
        if not response.ok:
            # a refused refresh token means the app was disconnected on Dropbox's side, and
            # no retry will change that
            raise DropboxError('the Dropbox sign-in has ended - sign in to Dropbox again '
                               'and start the run again', response.status_code)
        tokens = response.json()
        self.access_token = tokens['access_token']
        self.expires_at = self.clock() + float(tokens.get('expires_in') or 0)
        return self.access_token

    # endregion


def api_arg(value: dict) -> str:
    """The `Dropbox-API-Arg` header: json, with anything outside ascii escaped, as it requires."""

    return json.dumps(value, ensure_ascii=True)


def retry_after(response) -> float:
    try:
        return max(1.0, float(response.headers.get('Retry-After') or DEFAULT_RETRY_AFTER_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_RETRY_AFTER_SECONDS


def error_from(response) -> DropboxError:
    try:
        summary = str((response.json() or {}).get('error_summary') or '')
    except ValueError:
        summary = ''
    return DropboxError(summary or (response.text or '')[:200], response.status_code)
