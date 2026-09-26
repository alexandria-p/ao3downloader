"""Where the downloads folder actually lives.

Everything that reads or writes the library goes through one of these. The rest of the
helper still builds paths the way it always has - `os.path.join(fileops.downloadfolder,
...)` - and hands them here, so a run does not know or care where it is writing. That is
the point: all the rules about what is outdated, what may be replaced and what counts as
saved stay exactly where they are, and only the last step changes.

A run's library is always the one the web page has open (`PageStorage`), on this computer
or in Dropbox. `LocalStorage` is a plain folder, for code handed a path directly - the
tests, and anything reading a folder it was given.

The request log and settings.ini stay beside the helper either way. They belong to the
helper, not to the library.
"""

import os
from typing import Protocol


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


# region the web page

ROOT_PREFIX = 'library:'


class PageChannel(Protocol):
    """How a run reaches the web page: one request, one answer."""

    def storage_call(self, op: str, args: dict, content: bytes | None = None) -> dict: ...


class PageStorage:
    """The downloads folder as the web page holds it - on this computer or in Dropbox.

    **The page owns the library; the helper only asks it.** A page picks a folder with the
    File System Access API, which gives it a handle and never a path, so the helper cannot
    open that folder itself - and a Dropbox library is the page's to reach too, with the
    session it signed in for. So every read and write a run makes is sent to the page as a
    request (`op` plus arguments), the page carries it out in whichever library is open,
    and answers. The helper never learns where the folder is, and never holds a Dropbox
    token.

    **A path is a local-looking path under a root that says so.** `root` is `library:`, so
    `os.path.join` builds `library:\\indexing\\123 A Fic.json` as happily as a real path,
    and `relative` turns that back into `indexing/123 A Fic.json` for the page. Nothing
    called `library:` exists on disk, so one can never be opened there by accident.

    Two caches keep the requests down, the same two a remote folder needs:

    - **every file in the library, read in one listing** the first time anything asks
      whether a file is there. `shared.already_downloaded` and the renaming of undated
      files ask that of many files; a request each would be thousands per run. Kept current
      as this run writes, deletes and renames. A change made elsewhere mid-run goes unseen,
      as it would in a local folder changed behind a run's back.
    - **the size the page reported for each file this run wrote**, so confirming that a
      download arrived whole costs nothing more: that answer *is* the page saying what it
      stored.

    A request the page answers with an error raises `OSError`, so every path that already
    handles a folder refusing - a damaged index file skipped, a download recorded as failed
    - handles the page refusing the same way.
    """

    def __init__(self, channel: PageChannel) -> None:
        self.channel = channel
        self.root = ROOT_PREFIX
        self.sizes: dict[str, int] = {}
        self.known: set[str] | None = None

    # region paths

    def relative(self, path: str) -> str:
        """Where a path of ours sits in the library, as the page names it - `indexing/x.json`.

        Anything outside the library is refused. Compared without case, since both Dropbox
        and Windows would treat two spellings as one file.
        """

        normal = str(path).replace('\\', '/')
        if not normal.lower().startswith(self.root):
            raise ValueError(f'{path} is not inside the library')
        return '/'.join(part for part in normal[len(self.root):].split('/') if part)

    def local(self, relative: str) -> str:
        return self.root + '/' + relative

    def describe(self, path: str) -> str:
        return self.relative(path) or 'your library'

    def same_file(self, a: str, b: str) -> bool:
        return self.relative(a).lower() == self.relative(b).lower()

    # endregion

    def call(self, op: str, content: bytes | None = None, **args) -> dict:
        answer = self.channel.storage_call(op, args, content)
        if answer.get('error'): raise OSError(answer['error'])
        return answer

    def ensure_root(self) -> None:
        # the page set the library up when it was opened; this makes sure it is still open
        self.call('check')

    def make_dirs(self, path: str) -> None:
        self.call('mkdir', path=self.relative(path))

    def read_bytes(self, path: str) -> bytes:
        answer = self.call('read', path=self.relative(path))
        if answer.get('missing'): raise FileNotFoundError(path)
        return str(answer.get('text') or '').encode('utf-8')

    def write_bytes(self, path: str, content: bytes) -> None:
        relative = self.relative(path)
        answer = self.call('write', content, path=relative, size=len(content))
        self.sizes[relative.lower()] = int(answer.get('size', -1))
        if self.known is not None: self.known.add(relative.lower())

    def listing(self) -> set[str]:
        if self.known is None:
            files = self.call('list', path='', recursive=True).get('files') or []
            self.known = {str(x).lower() for x in files}
        return self.known

    def size(self, path: str) -> int | None:
        relative = self.relative(path)
        if relative.lower() in self.sizes: return self.sizes[relative.lower()]
        answer = self.call('size', path=relative)
        return None if answer.get('size') is None else int(answer['size'])

    def is_file(self, path: str) -> bool:
        return self.relative(path).lower() in self.listing()

    def exists(self, path: str) -> bool:
        # only files are ever asked about - whether a download or a rename target is there
        return self.is_file(path)

    def list_files(self, folder: str) -> list[str]:
        files = self.call('list', path=self.relative(folder), recursive=False).get('files') or []
        return [str(x).rsplit('/', 1)[-1] for x in files]

    def files_under(self, folder: str, skip: set[str] = frozenset()) -> list[str]:
        """Every file below `folder` in one listing, leaving out any folder named in `skip`."""

        base = self.relative(folder)
        skipped = {x.lower() for x in skip}
        found = []
        for file in self.call('list', path=base, recursive=True).get('files') or []:
            inside = str(file)[len(base):].strip('/').split('/') if base else str(file).split('/')
            if any(part.lower() in skipped for part in inside[:-1]): continue
            found.append(self.local(str(file)))
        return found

    def delete(self, path: str) -> bool:
        """Remove a file, reporting whether it went. A file already gone counts as done."""

        relative = self.relative(path)
        try:
            self.call('delete', path=relative)
        except OSError:
            return False
        self.sizes.pop(relative.lower(), None)
        if self.known is not None: self.known.discard(relative.lower())
        return True

    def rename(self, old: str, new: str) -> bool:
        """Rename a file, refusing to write over anything already at the new name."""

        before, after = self.relative(old), self.relative(new)
        try:
            self.call('rename', path=before, to=after)
        except OSError:
            return False
        size = self.sizes.pop(before.lower(), None)
        if size is not None: self.sizes[after.lower()] = size
        if self.known is not None:
            self.known.discard(before.lower())
            self.known.add(after.lower())
        return True

# endregion
