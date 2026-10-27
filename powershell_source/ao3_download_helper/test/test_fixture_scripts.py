"""The scripts for refreshing the fixtures from live ao3 by hand: `dev/refresh_fixtures.py`,
which downloads every fixture from live ao3 again, and `dev/archive_old_fixtures.py`, which
keeps the old copy of an ebook a new one broke.

Neither can reach ao3 here, so this holds what can go wrong without it: the list naming
fixtures the tests no longer have, or not naming ones they do; a login-only url left pointing
at somebody else's account; and the archive writing to the wrong place now the fixtures sit
below the repository root rather than at it - which is what the move into
powershell_source/ao3_download_helper broke.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
FIXTURES = HERE / 'test' / 'fixtures'


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / 'dev' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


refresh = load('refresh_fixtures')
archive = load('archive_old_fixtures')


def fixture_path(fixture: dict) -> Path:
    if fixture['type'] == 'page':
        return FIXTURES / fixture['name']
    return Path(refresh.ebook_current_path(str(FIXTURES), fixture))


# region what is refreshed

def test_every_fixture_the_refresh_writes_is_one_the_tests_have():
    # a name the tests no longer have would be added back on the next refresh
    missing = [f['name'] for f in refresh.FIXTURES if not fixture_path(f).is_file()]
    assert missing == []


def test_every_ebook_the_tests_read_is_refreshed():
    refreshed = {fixture_path(f) for f in refresh.FIXTURES if f['type'] == 'book'}
    on_disk = {p for p in (FIXTURES / 'ebook').glob('*/current/*') if p.is_file()}
    assert on_disk - refreshed == set()


def test_a_marked_for_later_list_is_read_from_the_account_that_logged_in():
    # nobody can read another account's list, so a fixed name would only ever fetch an error
    logged_in = [f for f in refresh.FIXTURES if f.get('login')]
    urls = {f['name']: f['url'] for f in refresh.for_account(logged_in, 'my_test_account')}
    assert urls['markedForLaterList.html'] == '/users/my_test_account/readings?show=to-read'
    assert all('{' not in url for url in urls.values())


def test_the_scripts_use_this_package_not_the_one_it_was_renamed_from():
    for name in ('refresh_fixtures', 'archive_old_fixtures'):
        source = (HERE / 'dev' / f'{name}.py').read_text(encoding='utf-8')
        assert 'from ao3downloader' not in source and 'import ao3downloader' not in source

# endregion


# region keeping an old ebook

def git(folder: Path, *args: str) -> str:
    return subprocess.run(['git', *args], cwd=folder, check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def helper_folder(tmp_path, monkeypatch):
    """A repository with the fixtures two folders down, as this one has them, and the
    archive run from that folder, as the workflow runs it."""

    repo = tmp_path / 'repo'
    helper = repo / 'powershell_source' / 'ao3_download_helper'
    current = helper / 'test' / 'fixtures' / 'ebook' / '218676' / 'current'
    current.mkdir(parents=True)
    (current / 'incompleteWork.epub').write_bytes(b'the old epub')
    git(repo, 'init', '-q')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'fixtures')
    monkeypatch.chdir(helper)
    return helper


def test_the_copy_before_the_refresh_is_kept_beside_it_in_archive(helper_folder):
    current = helper_folder / 'test' / 'fixtures' / 'ebook' / '218676' / 'current' / 'incompleteWork.epub'
    current.write_bytes(b'a new epub the parser cannot read')

    assert archive.main() == 0

    kept = list((helper_folder / 'test' / 'fixtures' / 'ebook' / '218676' / 'archive').iterdir())
    assert len(kept) == 1
    assert kept[0].name == f'incompleteWork-{archive.short_hash(b"the old epub")}.epub'
    assert kept[0].read_bytes() == b'the old epub'
    # nothing written anywhere else, the repository root included
    assert not (helper_folder / 'powershell_source').exists()


def test_a_copy_already_kept_is_not_kept_twice(helper_folder):
    current = helper_folder / 'test' / 'fixtures' / 'ebook' / '218676' / 'current' / 'incompleteWork.epub'
    current.write_bytes(b'a new epub')
    archive.main()
    archive.main()

    assert len(list((current.parent.parent / 'archive').iterdir())) == 1


def test_a_new_ebook_has_nothing_older_to_keep(helper_folder):
    added = helper_folder / 'test' / 'fixtures' / 'ebook' / '218676' / 'current' / 'incompleteWork.mobi'
    added.write_bytes(b'new')
    git(helper_folder, 'add', '.')

    assert archive.main() == 0
    assert not (added.parent.parent / 'archive').exists()

# endregion
