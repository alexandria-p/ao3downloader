"""The README's `<!--CHECK-->` markers, checked against strings.py by `dev/readme.py` - here
over the real README, so a rename that leaves it quoting a string the code no longer has fails
the ordinary test run - which CI runs on every pull request and
push to main. This is the whole check now: the
`validate readme` workflow that ran the script on its own was removed as a repeat of it."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('readme_check', HERE / 'dev' / 'readme.py')
readme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readme)

STRINGS = SimpleNamespace(WORKS_FOLDER_NAME='works', AO3_INFO_LOGGING_IN='logging in as {}')


def test_every_marker_in_the_readme_still_matches_its_constant():
    text = readme.DEFAULT_README.read_text(encoding='utf-8')
    assert readme.MARKER.search(text), 'found no markers - is DEFAULT_README the root README?'
    assert readme.problems(text) == []


def test_a_marker_naming_a_constant_that_is_gone_is_wrong():
    found = readme.problems('one\nkept in <!--CHECK-->downloads<!--DOWNLOAD_FOLDER_NAME-->', STRINGS)
    assert found == ["line 2: no constant DOWNLOAD_FOLDER_NAME in strings.py (README says 'downloads')"]


def test_a_marker_quoting_something_its_constant_no_longer_says_is_wrong():
    found = readme.problems('the <!--CHECK-->downloads<!--WORKS_FOLDER_NAME--> folder', STRINGS)
    assert found == ["line 1: WORKS_FOLDER_NAME is 'works', but the README says 'downloads'"]


def test_a_marker_may_quote_the_words_around_a_format_strings_braces():
    assert readme.problems('<!--CHECK-->logging in as<!--AO3_INFO_LOGGING_IN-->', STRINGS) == []


def test_the_script_fails_naming_each_wrong_marker(tmp_path, capsys):
    bad = tmp_path / 'README.md'
    bad.write_text('<!--CHECK-->downloads<!--NOT_A_CONSTANT--> and <!--CHECK-->works<!--WORKS_FOLDER_NAME-->',
                   encoding='utf-8')

    assert readme.main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert 'NOT_A_CONSTANT' in out
    assert '2 markers checked, 1 wrong' in out
