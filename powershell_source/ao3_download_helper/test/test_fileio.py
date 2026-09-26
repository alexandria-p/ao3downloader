"""Tests for ao3downloader.fileio — log writing, byte saving, settings persistence, download folder resolution."""

import datetime
import json
import os

import pytest

from source_code import strings
from source_code.fileio import FileOps


# region write_log

def test_write_log_appends_two_json_lines_with_timestamp(fake_fileops):
    fake_fileops.write_log({'message': 'first'})
    fake_fileops.write_log({'message': 'second'})

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        lines = f.readlines()

    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first['message'] == 'first'
    assert second['message'] == 'second'
    # timestamp matches the expected format
    datetime.datetime.strptime(first['timestamp'], strings.TIMESTAMP_FORMAT)
    datetime.datetime.strptime(second['timestamp'], strings.TIMESTAMP_FORMAT)


def test_write_log_preserves_non_ascii(fake_fileops):
    fake_fileops.write_log({'title': 'これはテスト'})

    with open(fake_fileops.logfile, encoding='utf-8') as f:
        content = f.read()

    # ensure_ascii=False keeps the literal characters
    assert 'これはテスト' in content
    assert json.loads(content.strip())['title'] == 'これはテスト'

# endregion


# region save_bytes

def test_save_bytes_writes_content_and_creates_parent_dirs(fake_fileops):
    fake_fileops.save_bytes(os.path.join('sub', 'dir', 'work.epub'), b'epub-bytes')

    path = os.path.join(fake_fileops.downloadfolder, 'sub', 'dir', 'work.epub')
    assert os.path.exists(path)
    with open(path, 'rb') as f:
        assert f.read() == b'epub-bytes'


def test_save_bytes_overwrites_existing_file(fake_fileops):
    fake_fileops.save_bytes('work.epub', b'first')
    fake_fileops.save_bytes('work.epub', b'second')

    path = os.path.join(fake_fileops.downloadfolder, 'work.epub')
    with open(path, 'rb') as f:
        assert f.read() == b'second'

# endregion


# region config and log folder overrides

def test_paths_default_to_the_working_directory(tmp_path, monkeypatch):
    # the console app sets neither variable, and must behave exactly as it always has
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(strings.ENV_CONFIG_FOLDER, raising=False)
    monkeypatch.delenv(strings.ENV_LOG_FOLDER, raising=False)

    fileops = FileOps()

    assert fileops.inifile == strings.INI_FILE_NAME
    assert fileops.settingsfile == strings.SETTINGS_FILE_NAME
    assert fileops.logfile == os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)


def test_config_folder_moves_settings_and_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, 'config')
    monkeypatch.delenv(strings.ENV_LOG_FOLDER, raising=False)

    fileops = FileOps()

    assert fileops.inifile == os.path.join('config', strings.INI_FILE_NAME)
    assert fileops.settingsfile == os.path.join('config', strings.SETTINGS_FILE_NAME)
    # logs are unaffected by the config folder
    assert fileops.logfile == os.path.join(strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)


def test_log_folder_moves_logs_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(strings.ENV_CONFIG_FOLDER, raising=False)
    monkeypatch.setenv(strings.ENV_LOG_FOLDER, 'helper')

    fileops = FileOps()

    assert fileops.logfile == os.path.join('helper', strings.LOG_FOLDER_NAME, strings.LOG_FILE_NAME)
    assert fileops.inifile == strings.INI_FILE_NAME


def test_the_run_history_sits_inside_the_downloads_folder(tmp_path, monkeypatch):
    # with the library it describes, rather than beside the logs. everything that walks the
    # downloads folder has to skip it by name
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(strings.ENV_CONFIG_FOLDER, raising=False)
    monkeypatch.setenv(strings.ENV_LOG_FOLDER, 'helper')

    fileops = FileOps()

    assert fileops.runsfolder == os.path.join(
        fileops.downloadfolder, strings.RUNS_FOLDER_NAME)
    # the log folder moves the logs and nothing else
    assert 'helper' not in fileops.runsfolder


def test_the_run_history_follows_the_downloads_folder_setting(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, 'config')
    os.makedirs(tmp_path / 'config')
    (tmp_path / 'config' / strings.INI_FILE_NAME).write_text(
        f'[{strings.INI_SECTION_NAME}]\n{strings.INI_DOWNLOAD_FOLDER} = elsewhere\n',
        encoding='utf-8')

    fileops = FileOps()

    assert fileops.runsfolder == os.path.join('elsewhere', strings.RUNS_FOLDER_NAME)


def test_a_download_folder_elsewhere_takes_the_whole_library_with_it(tmp_path, monkeypatch):
    # the whole library hangs off this one setting, so pointing it at a folder of your own
    # has to move every part of it - not just the works, leaving the metadata behind
    elsewhere = tmp_path / 'My AO3 Fics'
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, 'config')
    monkeypatch.setenv(strings.ENV_LOG_FOLDER, 'helper')
    os.makedirs(tmp_path / 'config')
    (tmp_path / 'config' / strings.INI_FILE_NAME).write_text(
        f'[{strings.INI_SECTION_NAME}]\n{strings.INI_DOWNLOAD_FOLDER}={elsewhere}\n',
        encoding='utf-8')

    fileops = FileOps()
    fileops.initialize()
    # the three the run writes on demand, plus the work itself
    fileops.save_json(os.path.join(strings.INDEXING_FOLDER_NAME, '111 a.json'), {'id': '111'})
    fileops.save_json(os.path.join(strings.COLLECTIONS_FOLDER_NAME, 'c.json'), {'name': 'c'})
    fileops.save_bytes(os.path.join(strings.IMAGE_FOLDER_NAME, '111 img.png'), b'x')
    fileops.save_bytes('111 A Work - X 2026-01-01.html', b'<html>')

    for name in (strings.INDEXING_FOLDER_NAME, strings.COLLECTIONS_FOLDER_NAME,
                 strings.IMAGE_FOLDER_NAME, strings.RUNS_FOLDER_NAME):
        assert (elsewhere / name).is_dir(), name
    assert (elsewhere / '111 A Work - X 2026-01-01.html').is_file()
    # and nothing was left in the working directory under the default name
    assert not (tmp_path / strings.DOWNLOAD_FOLDER_NAME).exists()


def test_a_download_folder_path_in_quotes_is_taken_as_written(tmp_path, monkeypatch):
    # a path pasted from Explorer's "copy as path" arrives wrapped in quotes
    elsewhere = tmp_path / 'Fics'
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, 'config')
    os.makedirs(tmp_path / 'config')
    (tmp_path / 'config' / strings.INI_FILE_NAME).write_text(
        f'[{strings.INI_SECTION_NAME}]\n{strings.INI_DOWNLOAD_FOLDER}="{elsewhere}"\n',
        encoding='utf-8')

    fileops = FileOps()

    assert fileops.downloadfolder == str(elsewhere)
    assert fileops.runsfolder == os.path.join(str(elsewhere), strings.RUNS_FOLDER_NAME)


def test_initialize_creates_both_folders(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, 'config')
    monkeypatch.setenv(strings.ENV_LOG_FOLDER, 'helper')

    fileops = FileOps()
    fileops.initialize()

    # writing settings.ini into a folder that does not exist would fail
    assert (tmp_path / 'config' / strings.INI_FILE_NAME).exists()
    assert (tmp_path / 'helper' / strings.LOG_FOLDER_NAME).is_dir()
    # and the run history, which now hangs off the downloads folder
    assert (tmp_path / strings.DOWNLOAD_FOLDER_NAME / strings.RUNS_FOLDER_NAME).is_dir()


def test_settings_are_read_back_from_the_config_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(strings.ENV_CONFIG_FOLDER, 'config')

    fileops = FileOps()
    fileops.initialize()
    fileops.save_setting(strings.SETTING_USERNAME, 'Someone')

    assert FileOps().get_setting(strings.SETTING_USERNAME) == 'Someone'
    assert (tmp_path / 'config' / strings.SETTINGS_FILE_NAME).exists()

# endregion


# region save_json

def test_save_json_round_trips_a_metadata_document(fake_fileops):
    document = {
        'id': '111',
        'title': '天官赐福',
        'bookmark_notes': 'line one\nline two',
        'tags': {'additional': ['Hurt/Comfort']},
        'hits': None,
    }

    path = fake_fileops.save_json('111 A Work - Author.json', document)

    with open(path, encoding='utf-8') as f:
        assert json.load(f) == document


def test_save_json_creates_parent_dirs(fake_fileops):
    # a file name pattern containing '/' puts works in subfolders
    path = fake_fileops.save_json(os.path.join('A Fandom', '111 A Work.json'), {'id': '111'})

    assert os.path.exists(path)
    assert os.path.dirname(path).endswith('A Fandom')


def test_save_json_overwrites_existing_file(fake_fileops):
    # the file is rewritten once publication dates have been looked up
    fake_fileops.save_json('111.json', {'id': '111', 'date_created': None})
    path = fake_fileops.save_json('111.json', {'id': '111', 'date_created': '01 Jan 2019'})

    with open(path, encoding='utf-8') as f:
        assert json.load(f)['date_created'] == '01 Jan 2019'

# endregion


# region save_setting / get_setting

def test_save_setting_roundtrips_through_get_setting(fake_fileops):
    fake_fileops.save_setting('username', 'alice')
    assert fake_fileops.get_setting('username') == 'alice'


def test_save_setting_none_removes_key(fake_fileops):
    fake_fileops.save_setting('username', 'alice')
    fake_fileops.save_setting('username', None)
    assert fake_fileops.get_setting('username') == ''


def test_get_setting_returns_empty_string_when_missing(fake_fileops):
    assert fake_fileops.get_setting('nope') == ''


def test_clearing_a_setting_that_was_never_saved_creates_no_file(fake_fileops):
    # `initialize` clears the saved password on every start whenever SavePassword is off,
    # which in a bundle is always - the bundler strips that setting out. this used to write
    # a data.json holding {} to record the absence of a key that had never existed
    fake_fileops.save_setting(strings.SETTING_PASSWORD, None)

    assert not os.path.exists(fake_fileops.settingsfile)


def test_clearing_a_setting_that_was_saved_still_writes(fake_fileops):
    # the point of the call: a password on disk when it is no longer allowed must go
    fake_fileops.save_setting(strings.SETTING_PASSWORD, 'hunter2')

    fake_fileops.save_setting(strings.SETTING_PASSWORD, None)

    assert os.path.exists(fake_fileops.settingsfile)
    assert fake_fileops.get_setting(strings.SETTING_PASSWORD) == ''

# endregion


# region get_settings_json

def test_get_settings_json_returns_empty_dict_when_file_missing(fake_fileops):
    assert not os.path.exists(fake_fileops.settingsfile)

    result = fake_fileops.get_settings_json()

    assert result == {}


def test_reading_settings_does_not_create_the_file(fake_fileops):
    # the web ui asks for the saved username on every page load and stores nothing here,
    # so reading used to leave an empty data.json in a bundle meant not to have one
    fake_fileops.get_settings_json()
    fake_fileops.get_setting(strings.SETTING_USERNAME)

    assert not os.path.exists(fake_fileops.settingsfile)


def test_saving_a_setting_still_creates_the_file(fake_fileops):
    # the console menu depends on this: it is where saved answers live
    fake_fileops.save_setting(strings.SETTING_USERNAME, 'Someone')

    assert os.path.exists(fake_fileops.settingsfile)
    assert fake_fileops.get_setting(strings.SETTING_USERNAME) == 'Someone'


def test_get_settings_json_returns_empty_dict_when_file_malformed(fake_fileops):
    with open(fake_fileops.settingsfile, 'w', encoding='utf-8') as f:
        f.write('not json')

    assert fake_fileops.get_settings_json() == {}

# endregion


# region load_logfile

def test_load_logfile_returns_empty_list_when_file_missing(fake_fileops):
    assert not os.path.exists(fake_fileops.logfile)
    assert fake_fileops.load_logfile() == []


def test_load_logfile_parses_each_line_as_json_object(fake_fileops):
    fake_fileops.write_log({'message': 'one'})
    fake_fileops.write_log({'message': 'two'})

    logs = fake_fileops.load_logfile()

    assert len(logs) == 2
    assert logs[0]['message'] == 'one'
    assert logs[1]['message'] == 'two'


def test_load_logfile_loads_unicode_correctly(fake_fileops):
    fake_fileops.write_log({'title': 'これはテスト'})

    logs = fake_fileops.load_logfile()

    assert logs[0]['title'] == 'これはテスト'

# endregion


# region ini_differences_str

def test_ini_differences_str_returns_none_when_equal(fake_fileops):
    local = {'settings': {'a', 'b'}}
    remote = {'settings': {'a', 'b'}}

    assert fake_fileops.ini_differences_str(local, remote) is None


def test_ini_differences_str_reports_added_section(fake_fileops):
    local = {'settings': {'a'}}
    remote = {'settings': {'a'}, 'new_section': {'x'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_ADDED_SECTION.format('new_section') in msg


def test_ini_differences_str_reports_removed_section(fake_fileops):
    local = {'settings': {'a'}, 'gone': {'x'}}
    remote = {'settings': {'a'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_REMOVED_SECTION.format('gone') in msg


def test_ini_differences_str_reports_added_and_removed_keys_in_same_section(fake_fileops):
    local = {'settings': {'old_key', 'shared'}}
    remote = {'settings': {'new_key', 'shared'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_ADDED_KEY.format('new_key', 'settings') in msg
    assert strings.MESSAGE_INI_REMOVED_KEY.format('old_key', 'settings') in msg


def test_ini_differences_str_handles_multiple_sections(fake_fileops):
    local = {'a': {'k1'}, 'b': {'k2'}}
    remote = {'a': {'k1', 'k3'}, 'b': {'k2'}}

    msg = fake_fileops.ini_differences_str(local, remote)

    assert strings.MESSAGE_INI_ADDED_KEY.format('k3', 'a') in msg

# endregion


# region ini_differences

def test_ini_differences_parses_real_ini_strings(fake_fileops):
    local = '[settings]\na=1\nb=2\n'
    remote = '[settings]\na=1\nb=2\nc=3\n'

    msg = fake_fileops.ini_differences(local, remote)

    assert msg is not None
    assert strings.MESSAGE_INI_ADDED_KEY.format('c', 'settings') in msg


def test_ini_differences_returns_none_when_identical(fake_fileops):
    content = '[settings]\na=1\nb=2\n'

    assert fake_fileops.ini_differences(content, content) is None

# endregion


# region get_ini_value*

def _write_ini(fake_fileops, body: str) -> None:
    with open(fake_fileops.inifile, 'w', encoding='utf-8') as f:
        f.write(body)


def test_get_ini_value_reads_string(fake_fileops):
    _write_ini(fake_fileops, '[settings]\nFileNamePattern=custom\n')

    assert fake_fileops.get_ini_value('FileNamePattern', 'fallback') == 'custom'


def test_get_ini_value_returns_fallback_when_missing(fake_fileops):
    _write_ini(fake_fileops, '[settings]\n')

    assert fake_fileops.get_ini_value('Missing', 'default') == 'default'


def test_get_ini_value_boolean_reads_true_and_false(fake_fileops):
    _write_ini(fake_fileops,
               '[settings]\nFlagTrue=true\nFlagFalse=false\n')

    assert fake_fileops.get_ini_value_boolean('FlagTrue', False) is True
    assert fake_fileops.get_ini_value_boolean('FlagFalse', True) is False


def test_get_ini_value_boolean_returns_fallback_when_missing(fake_fileops):
    _write_ini(fake_fileops, '[settings]\n')

    assert fake_fileops.get_ini_value_boolean('Absent', True) is True
    assert fake_fileops.get_ini_value_boolean('Absent', False) is False


def test_get_ini_value_integer_reads_and_fallbacks(fake_fileops):
    _write_ini(fake_fileops, '[settings]\nMaxRetries=42\n')

    assert fake_fileops.get_ini_value_integer('MaxRetries', 0) == 42
    assert fake_fileops.get_ini_value_integer('Missing', 99) == 99


def test_get_ini_value_raw_tolerates_percent_signs(fake_fileops):
    _write_ini(fake_fileops, '[settings]\nSomeKey=%USERPROFILE%\\fics\n')

    assert fake_fileops.get_ini_value('SomeKey', 'fallback', raw=True) == '%USERPROFILE%\\fics'

# endregion


# region get_download_folder

def _write_download_folder(fake_fileops, value: str) -> None:
    _write_ini(fake_fileops, f'[settings]\n{strings.INI_DOWNLOAD_FOLDER}={value}\n')


def test_get_download_folder_returns_default_when_key_missing(fake_fileops):
    _write_ini(fake_fileops, '[settings]\n')

    assert fake_fileops.get_download_folder() == strings.DOWNLOAD_FOLDER_NAME


def test_get_download_folder_returns_default_when_value_blank(fake_fileops):
    _write_download_folder(fake_fileops, '')

    assert fake_fileops.get_download_folder() == strings.DOWNLOAD_FOLDER_NAME


def test_get_download_folder_returns_default_when_value_is_quotes_only(fake_fileops):
    _write_download_folder(fake_fileops, '""')

    assert fake_fileops.get_download_folder() == strings.DOWNLOAD_FOLDER_NAME


def test_get_download_folder_keeps_relative_path_relative(fake_fileops):
    _write_download_folder(fake_fileops, os.path.join('my fics', 'ao3'))

    assert fake_fileops.get_download_folder() == os.path.join('my fics', 'ao3')


def test_get_download_folder_returns_absolute_path_verbatim(fake_fileops, tmp_path):
    _write_download_folder(fake_fileops, str(tmp_path / 'elsewhere'))

    assert fake_fileops.get_download_folder() == str(tmp_path / 'elsewhere')


def test_get_download_folder_strips_enclosing_quotes(fake_fileops):
    _write_download_folder(fake_fileops, '"my fics"')

    assert fake_fileops.get_download_folder() == 'my fics'


def test_get_download_folder_tolerates_percent_signs(fake_fileops):
    _write_download_folder(fake_fileops, '50% fics')

    assert fake_fileops.get_download_folder() == '50% fics'


def test_get_download_folder_expands_home_directory(fake_fileops, tmp_path, monkeypatch):
    # cover both the posix (HOME) and windows (USERPROFILE) lookups
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    _write_download_folder(fake_fileops, '~/fics')

    assert fake_fileops.get_download_folder() == str(tmp_path) + '/fics'


def test_get_download_folder_expands_environment_variables(fake_fileops, tmp_path, monkeypatch):
    monkeypatch.setenv('AO3DL_TEST_FOLDER', str(tmp_path))
    _write_download_folder(fake_fileops, '$AO3DL_TEST_FOLDER/fics')

    assert fake_fileops.get_download_folder() == str(tmp_path) + '/fics'


def test_fileops_reads_download_folder_from_ini_on_construction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with open(strings.INI_FILE_NAME, 'w', encoding='utf-8') as f:
        f.write(f'[settings]\n{strings.INI_DOWNLOAD_FOLDER}=custom folder\n')

    assert FileOps().downloadfolder == 'custom folder'


def test_fileops_uses_default_download_folder_when_no_ini(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    assert FileOps().downloadfolder == strings.DOWNLOAD_FOLDER_NAME

# endregion


# region initialize

def test_initialize_creates_nested_download_folder(fake_fileops, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ini(fake_fileops, '[settings]\n')
    fake_fileops.downloadfolder = str(tmp_path / 'a' / 'b' / 'c')

    fake_fileops.initialize()

    assert os.path.isdir(fake_fileops.downloadfolder)


def test_initialize_succeeds_when_download_folder_already_exists(fake_fileops, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_ini(fake_fileops, '[settings]\n')
    assert os.path.isdir(fake_fileops.downloadfolder)

    fake_fileops.initialize()

    assert os.path.isdir(fake_fileops.downloadfolder)


def test_initialize_fails_with_message_when_download_folder_uncreatable(fake_fileops, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_ini(fake_fileops, '[settings]\n')
    blocker = tmp_path / 'blocker'
    blocker.write_bytes(b'')
    fake_fileops.downloadfolder = str(blocker / 'fics')

    with pytest.raises(OSError):
        fake_fileops.initialize()

    assert strings.MESSAGE_DOWNLOAD_FOLDER_ERROR.format(fake_fileops.downloadfolder) in capsys.readouterr().out

# endregion


# region saying what is wrong with a saved file

def test_a_missing_file_is_described_by_where_it_was_expected(fake_fileops, tmp_path):
    path = str(tmp_path / 'gone.pdf')
    assert fake_fileops.saved_problem(path, 10) == strings.SAVED_NOT_FOUND.format(path)


def test_a_short_file_is_described_by_both_sizes(fake_fileops, tmp_path):
    path = tmp_path / 'short.pdf'
    path.write_bytes(b'ab')
    assert fake_fileops.saved_problem(str(path), 10) == strings.SAVED_WRONG_SIZE.format(10, 2)

# endregion
