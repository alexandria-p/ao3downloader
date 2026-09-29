"""A settings.ini kept in step with the settings the helper knows about - only ever added to."""

import os
from unittest.mock import patch

import pytest

from source_code import server, settings_file, strings


TEMPLATE = """[settings]

# seconds to wait after every request
ExtraWaitTime=15

# set this to 'true' to save your password
SavePassword=false

# a setting added in a later version
# over two lines of explanation
NewSetting=7
"""


# region completing one

def test_a_setting_the_file_lacks_is_added_with_its_explanation_and_default():
    existing = '[settings]\nExtraWaitTime=30\n'

    completed, added = settings_file.complete_settings(existing, TEMPLATE)

    assert added == ['NewSetting']
    assert completed.endswith('# a setting added in a later version\n'
                              '# over two lines of explanation\nNewSetting=7\n')


def test_what_the_user_wrote_is_left_exactly_as_it_was():
    existing = '[settings]\n# my own note\nExtraWaitTime=30\n'

    completed, _ = settings_file.complete_settings(existing, TEMPLATE)

    # only added to the end - nothing already there is rewritten or moved
    assert completed.startswith(existing.rstrip('\n'))
    assert 'ExtraWaitTime=30' in completed and 'ExtraWaitTime=15' not in completed


def test_a_setting_written_in_another_case_counts_as_there():
    # configparser reads names without case, so this one is already set
    completed, added = settings_file.complete_settings(
        '[settings]\nextrawaittime=30\nnewsetting=1\n', TEMPLATE)
    assert added == []


def test_the_password_setting_is_never_added():
    # the web page never stores a password
    _, added = settings_file.complete_settings('[settings]\n', TEMPLATE)
    assert strings.INI_PASSWORD_SAVE not in added


def test_a_file_with_nothing_in_it_gets_a_section_to_put_things_in():
    completed, added = settings_file.complete_settings('', TEMPLATE)
    assert completed.startswith('[settings]')
    assert added == ['ExtraWaitTime', 'NewSetting']


def test_the_real_template_has_every_setting_the_helper_reads():
    # the settings added since the web ui took over are all in it, so they reach old files
    names = [key for key, _ in settings_file.blocks_of(settings_file.template_text())]
    for key in (strings.INI_HELPER_URL, strings.INI_REQUIRE_PASSCODE, strings.INI_PAGE_ORIGIN,
                strings.INI_CONSOLE_LOGGING, strings.INI_PAUSED_RUN_TIMEOUT,
                strings.INI_WAIT_TIME, strings.INI_DEBUG_TOOLS):
        assert key in names, key

# endregion


# region the file on disk

def test_a_missing_file_is_written_from_the_template_without_the_password_setting(tmp_path):
    path = tmp_path / 'config' / 'settings.ini'

    created, added = settings_file.ensure_settings_file(str(path), TEMPLATE)

    assert (created, added) == (True, [])
    text = path.read_text(encoding='utf-8')
    assert 'ExtraWaitTime=15' in text and 'NewSetting=7' in text
    assert 'SavePassword' not in text


def test_an_old_file_gets_what_it_lacks(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=30\n', encoding='utf-8')

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, ['NewSetting'])
    assert 'NewSetting=7' in path.read_text(encoding='utf-8')


def test_a_complete_file_is_not_written_at_all(tmp_path):
    path = tmp_path / 'settings.ini'
    path.write_text('[settings]\nExtraWaitTime=30\nNewSetting=1\n', encoding='utf-8')
    os.utime(path, (1, 1))

    assert settings_file.ensure_settings_file(str(path), TEMPLATE) == (False, [])
    assert os.path.getmtime(path) == 1

# endregion


# region when the helper starts

def test_the_helper_writes_a_missing_settings_file_as_it_starts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer'):
        server.serve(port=4400)

    text = (tmp_path / strings.INI_FILE_NAME).read_text(encoding='utf-8')
    assert f'{strings.INI_PAUSED_RUN_TIMEOUT}=10' in text
    assert 'settings.ini: created' in capsys.readouterr().out


def test_the_helper_adds_what_an_older_settings_file_lacks_and_says_so(tmp_path, monkeypatch,
                                                                        capsys):
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, str(tmp_path))
    ini = tmp_path / strings.INI_FILE_NAME
    ini.write_text('[settings]\nExtraWaitTime=42\n', encoding='utf-8')

    with patch.object(server, 'already_listening', return_value=False), \
         patch.object(server, 'ThreadingHTTPServer'):
        server.serve(port=4400)

    text = ini.read_text(encoding='utf-8')
    assert 'ExtraWaitTime=42' in text
    assert f'{strings.INI_HELPER_URL}=http://127.0.0.1:4400' in text
    said = capsys.readouterr().out
    assert 'settings.ini: added' in said and strings.INI_PAUSED_RUN_TIMEOUT in said


def test_a_settings_file_that_cannot_be_written_does_not_stop_the_helper(tmp_path, capsys):
    with patch.object(settings_file, 'ensure_settings_file', side_effect=PermissionError('no')):
        server.bring_settings_up_to_date(str(tmp_path / 'settings.ini'))
    assert 'using the defaults' in capsys.readouterr().out

# endregion
