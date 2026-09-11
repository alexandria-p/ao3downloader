"""Tests for ao3downloader.actions.shared — folder input and file discovery."""

import os
from unittest.mock import MagicMock

import pytest

from source_code import parse_text, strings
from source_code.actions import shared
from source_code.fileio import FileOps


# region get_files_of_type

def test_get_files_of_type_returns_matching_files(tmp_path, capsys) -> None:
    (tmp_path / 'work1.epub').write_bytes(b'')
    (tmp_path / 'work2.EPUB').write_bytes(b'')
    (tmp_path / 'work3.mobi').write_bytes(b'')
    (tmp_path / 'readme.txt').write_bytes(b'')
    sub = tmp_path / 'nested'
    sub.mkdir()
    (sub / 'work4.epub').write_bytes(b'')

    results = shared.get_files_of_type(str(tmp_path), ['EPUB'])

    paths = sorted(os.path.basename(r['path']) for r in results)
    assert paths == ['work1.epub', 'work2.EPUB', 'work4.epub']
    assert all(r['filetype'] == 'EPUB' for r in results)


def test_get_files_of_type_nonexistent_folder_returns_empty(capsys) -> None:
    bogus = '/definitely/does/not/exist/anywhere'
    results = shared.get_files_of_type(bogus, ['EPUB'])

    assert results == []
    out = capsys.readouterr().out
    assert bogus in out


def test_get_files_of_type_quoted_path_returns_empty(capsys) -> None:
    results = shared.get_files_of_type('"/tmp"', ['EPUB'])

    assert results == []
    out = capsys.readouterr().out
    assert strings.INFO_NO_FOLDER.split('{')[0] in out

# endregion


# region update_folder

def _fake_fileops() -> MagicMock:
    fo = MagicMock(spec=FileOps)
    fo._settings = {}
    fo.get_setting.side_effect = lambda key: fo._settings.get(key, '')
    def _save(key: str, value) -> None:
        if value is None:
            fo._settings.pop(key, None)
        else:
            fo._settings[key] = value
    fo.save_setting.side_effect = _save
    return fo


def test_update_folder_accepts_quoted_paste(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    quoted = f'"{tmp_path}"'
    monkeypatch.setattr('builtins.input', lambda: quoted)

    result = shared.update_folder(fo)

    assert result == str(tmp_path)
    # normalized value is saved
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(tmp_path)


def test_update_folder_reprompts_on_invalid_then_accepts(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    inputs = iter(['/nope/not/a/real/path', str(tmp_path)])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))

    result = shared.update_folder(fo)

    assert result == str(tmp_path)


def test_update_folder_detects_stale_saved_path(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = '/stale/path/gone'
    monkeypatch.setattr('builtins.input', lambda: str(tmp_path))

    result = shared.update_folder(fo)

    # stale path was cleared, user was reprompted, new path saved
    assert result == str(tmp_path)
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(tmp_path)


def test_update_folder_normalizes_quoted_saved_path(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = f'"{tmp_path}"'
    monkeypatch.setattr('builtins.input', lambda: strings.PROMPT_YES)

    result = shared.update_folder(fo)

    assert result == str(tmp_path)
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(f'"{tmp_path}"')


def test_update_folder_reuses_valid_saved_path(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = str(tmp_path)
    monkeypatch.setattr('builtins.input', lambda: strings.PROMPT_YES)

    result = shared.update_folder(fo)

    assert result == str(tmp_path)


def test_update_folder_says_no_to_saved_then_prompts(tmp_path, monkeypatch) -> None:
    fo = _fake_fileops()
    other = tmp_path / 'other'
    other.mkdir()
    fo._settings[strings.SETTING_UPDATE_FOLDER] = str(tmp_path)
    inputs = iter([strings.PROMPT_NO, str(other)])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))

    result = shared.update_folder(fo)

    assert result == str(other)
    assert fo._settings[strings.SETTING_UPDATE_FOLDER] == str(other)

# endregion


# region redownload_folder

def test_redownload_folder_accepts_quoted_paste(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('builtins.input', lambda: f'"{tmp_path}"')
    assert shared.redownload_folder() == str(tmp_path)


def test_redownload_folder_reprompts_on_invalid(tmp_path, monkeypatch) -> None:
    inputs = iter(['/nope/not/a/real/path', str(tmp_path)])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))
    assert shared.redownload_folder() == str(tmp_path)

# endregion


# region yes/no prompts

@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
    ('', False),
])
def test_series_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.series() is expected


@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
])
def test_images_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.images() is expected


@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
])
def test_metadata_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.metadata() is expected


@pytest.mark.parametrize('answer, expected', [
    (strings.PROMPT_YES, True),
    (strings.PROMPT_NO, False),
])
def test_metadata_work_dates_returns_expected_bool(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.metadata_work_dates() is expected


@pytest.mark.parametrize('answer, expected_exclude', [
    # pinboard_exclude has inverted logic — 'yes include unread' means don't exclude
    (strings.PROMPT_YES, False),
    (strings.PROMPT_NO, True),
])
def test_pinboard_exclude_inverts_input(answer, expected_exclude, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.pinboard_exclude() is expected_exclude

# endregion


# region download_types

def _answers(monkeypatch, *answers: str) -> None:
    responses = iter(answers)
    monkeypatch.setattr('builtins.input', lambda: next(responses))


def test_download_types_rejects_metadata_type_by_default(monkeypatch, capsys) -> None:
    fileops = MagicMock()
    fileops.get_setting.return_value = ''
    # JSON is not offered outside the ao3 download action, so it re-prompts
    _answers(monkeypatch, strings.AO3_DOWNLOAD_TYPE_METADATA, 'EPUB', strings.PROMPT_YES)

    assert shared.download_types(fileops) == ['EPUB']


def test_download_types_accepts_metadata_type_when_allowed(monkeypatch, capsys) -> None:
    fileops = MagicMock()
    fileops.get_setting.return_value = ''
    _answers(monkeypatch, strings.AO3_DOWNLOAD_TYPE_METADATA, strings.PROMPT_YES)

    result = shared.download_types(fileops, allow_metadata=True)

    assert result == [strings.AO3_DOWNLOAD_TYPE_METADATA]
    fileops.save_setting.assert_called_once_with(
        strings.SETTING_FILETYPES, [strings.AO3_DOWNLOAD_TYPE_METADATA])


def test_download_types_reuses_saved_list(monkeypatch, capsys) -> None:
    fileops = MagicMock()
    fileops.get_setting.return_value = ['EPUB', strings.AO3_DOWNLOAD_TYPE_METADATA]
    _answers(monkeypatch, strings.PROMPT_YES)

    result = shared.download_types(fileops, allow_metadata=True)

    assert result == ['EPUB', strings.AO3_DOWNLOAD_TYPE_METADATA]


def test_download_types_drops_saved_metadata_type_for_other_actions(monkeypatch, capsys) -> None:
    # the saved list is shared between actions; one that can't export metadata
    # must not be handed a JSON entry it would try to download as a file
    fileops = MagicMock()
    fileops.get_setting.return_value = ['EPUB', strings.AO3_DOWNLOAD_TYPE_METADATA]
    _answers(monkeypatch, strings.PROMPT_YES)

    assert shared.download_types(fileops) == ['EPUB']


def test_download_types_prompts_when_saved_list_has_nothing_usable(monkeypatch, capsys) -> None:
    fileops = MagicMock()
    fileops.get_setting.return_value = [strings.AO3_DOWNLOAD_TYPE_METADATA]
    # nothing usable survives the filter, so the saved-list prompt is skipped entirely
    _answers(monkeypatch, 'PDF', strings.PROMPT_YES)

    assert shared.download_types(fileops) == ['PDF']

# endregion


# region pages

@pytest.mark.parametrize('answer, expected', [
    ('5', 5),
    ('0', None),
    ('-1', None),
    ('abc', None),
    ('', None),
])
def test_pages_parses_int_with_fallback(answer, expected, monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: answer)
    assert shared.pages() == expected

# endregion


# region pinboard_date

def test_pinboard_date_returns_none_when_no(monkeypatch, capsys) -> None:
    monkeypatch.setattr('builtins.input', lambda: strings.PROMPT_NO)
    assert shared.pinboard_date() is None


def test_pinboard_date_parses_entered_date(monkeypatch, capsys) -> None:
    import datetime
    inputs = iter([strings.PROMPT_YES, '03/15/2024'])
    monkeypatch.setattr('builtins.input', lambda: next(inputs))

    result = shared.pinboard_date()

    assert result == datetime.datetime(2024, 3, 15)

# endregion


# region visited

def _prepare_fileops(tmp_path):
    from source_code.fileio import FileOps

    fo = FileOps()
    fo.logfile = str(tmp_path / 'log.jsonl')
    fo.inifile = str(tmp_path / 'settings.ini')
    fo.settingsfile = str(tmp_path / 'data.json')
    fo.downloadfolder = str(tmp_path / 'downloads')
    os.makedirs(fo.downloadfolder, exist_ok=True)
    return fo


def test_visited_returns_files_from_log_that_exist_on_disk(tmp_path, monkeypatch) -> None:
    """visited should return only work ids whose files exist on disk."""
    fo = _prepare_fileops(tmp_path)

    # write two works to the log
    fo.write_log({'link': 'https://a/works/1', 'title': 'one'})
    fo.write_log({'link': 'https://a/works/2', 'title': 'two'})

    # only create the file for work 1
    with open(os.path.join(fo.downloadfolder, 'one.epub'), 'wb') as f:
        f.write(b'')

    monkeypatch.chdir(tmp_path)  # IGNORELIST_FILE_NAME uses relative path

    result = shared.visited(fo, ['EPUB'])

    assert 'https://a/works/1' in result
    assert 'https://a/works/2' not in result


def test_visited_returns_empty_when_no_log_and_no_ignorelist(tmp_path, monkeypatch) -> None:
    fo = _prepare_fileops(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert shared.visited(fo, ['EPUB']) == []

# endregion


# region scan_downloaded_works

def make_file(folder, name: str) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x')
    return str(path)


def test_scan_finds_works_by_the_number_their_name_starts_with(tmp_path):
    make_file(tmp_path, '34816549 No Paths - Cal 2024-12-14.html')
    make_file(tmp_path, '99 Red Balloons 2020-01-02.epub')

    found = shared.scan_downloaded_works(str(tmp_path), ['HTML', 'EPUB'])

    assert sorted(found) == ['34816549', '99']
    assert found['34816549']['HTML']['date'] == '2024-12-14'
    assert found['99']['EPUB']['date'] == '2020-01-02'


def test_scan_reports_an_undated_file_as_having_no_date(tmp_path):
    make_file(tmp_path, '34816549 No Paths - Cal.html')

    found = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    assert found['34816549']['HTML']['date'] is None


def test_scan_keeps_each_file_type_apart(tmp_path):
    make_file(tmp_path, '34816549 A 2024-12-14.html')
    make_file(tmp_path, '34816549 A 2024-12-14.epub')

    found = shared.scan_downloaded_works(str(tmp_path), ['HTML', 'EPUB'])

    assert sorted(found['34816549']) == ['EPUB', 'HTML']


def test_scan_prefers_the_newest_when_a_work_has_two_copies_of_a_type(tmp_path):
    make_file(tmp_path, '34816549 A 2023-01-01.html')
    make_file(tmp_path, '34816549 A 2024-12-14.html')

    found = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    assert found['34816549']['HTML']['date'] == '2024-12-14'


def test_scan_treats_an_undated_copy_as_older_than_a_dated_one(tmp_path):
    make_file(tmp_path, '34816549 A.html')
    make_file(tmp_path, '34816549 A 2024-12-14.html')

    found = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    assert found['34816549']['HTML']['date'] == '2024-12-14'


def test_scan_ignores_the_metadata_folders(tmp_path):
    # an index or collection file is not a downloaded work and carries no date by design
    make_file(tmp_path, os.path.join(strings.INDEXING_FOLDER_NAME, '34816549 A.json'))
    make_file(tmp_path, os.path.join(strings.COLLECTIONS_FOLDER_NAME, '111 c.json'))
    make_file(tmp_path, os.path.join(strings.IMAGE_FOLDER_NAME, '34816549 A img000.png'))
    make_file(tmp_path, '34816549 A 2024-12-14.html')

    found = shared.scan_downloaded_works(str(tmp_path), ['HTML', 'JSON', 'PNG'])

    assert list(found) == ['34816549']
    assert list(found['34816549']) == ['HTML']


def test_scan_ignores_files_that_do_not_start_with_a_work_number(tmp_path):
    make_file(tmp_path, 'No Paths Are Bound.html')
    make_file(tmp_path, '99Red Balloons.html')

    assert shared.scan_downloaded_works(str(tmp_path), ['HTML']) == {}


def test_scan_of_a_folder_that_is_not_there_is_empty(tmp_path):
    assert shared.scan_downloaded_works(str(tmp_path / 'nope'), ['HTML']) == {}

# endregion


# region stamp_undated_works

def real_fileops():
    """A FileOps whose renaming is real, with nothing else wired up."""
    fo = MagicMock()
    fo.rename_file.side_effect = lambda a, b: FileOps.rename_file(fo, a, b)
    return fo


def test_dating_an_undated_file_renames_it_where_it_sits(tmp_path):
    make_file(tmp_path, '34816549 No Paths - Cal.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    result = shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    assert result == {'renamed': 1, 'skipped': 0}
    assert (tmp_path / '34816549 No Paths - Cal 2024-06-01.html').exists()
    assert not (tmp_path / '34816549 No Paths - Cal.html').exists()


def test_dating_updates_what_the_caller_holds_so_it_can_plan_straight_after(tmp_path):
    make_file(tmp_path, '34816549 No Paths - Cal.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    entry = existing['34816549']['HTML']
    assert entry['date'] == '2024-06-01'
    assert entry['path'].endswith('2024-06-01.html')


def test_a_file_that_already_has_a_date_is_left_alone(tmp_path):
    make_file(tmp_path, '34816549 No Paths - Cal 2020-01-01.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    result = shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    assert result == {'renamed': 0, 'skipped': 0}
    assert (tmp_path / '34816549 No Paths - Cal 2020-01-01.html').exists()


def test_dating_never_writes_over_a_file_that_is_already_there(tmp_path):
    make_file(tmp_path, '34816549 A.html')
    make_file(tmp_path, '34816549 A 2024-06-01.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])
    # the undated one is the older of the two, so it is not what the scan kept
    existing['34816549']['HTML'] = {'path': str(tmp_path / '34816549 A.html'), 'date': None}

    result = shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    assert result == {'renamed': 0, 'skipped': 1}
    assert (tmp_path / '34816549 A.html').exists()
    assert (tmp_path / '34816549 A 2024-06-01.html').read_bytes() == b'x'


def test_a_long_name_is_cut_to_leave_room_for_the_date(tmp_path):
    long_name = '34816549 No Paths Are Bound And Nothing Is Simple - Cal.html'
    make_file(tmp_path, long_name)
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])

    shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    written = os.path.basename(existing['34816549']['HTML']['path'])
    assert len(os.path.splitext(written)[0]) == 50
    assert written.endswith(' 2024-06-01.html')
    # still matchable and still readable as dated
    assert parse_text.get_work_number_from_filename(written) == '34816549'
    assert parse_text.get_date_from_filename(written) == '2024-06-01'


def test_dating_keeps_each_file_type_separate(tmp_path):
    make_file(tmp_path, '34816549 A.html')
    make_file(tmp_path, '34816549 A.epub')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML', 'EPUB'])

    result = shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    assert result['renamed'] == 2
    assert (tmp_path / '34816549 A 2024-06-01.html').exists()
    assert (tmp_path / '34816549 A 2024-06-01.epub').exists()


def test_a_rename_that_fails_is_counted_rather_than_raised(tmp_path):
    make_file(tmp_path, '34816549 A.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])
    fo = MagicMock()
    fo.rename_file.return_value = False

    result = shared.stamp_undated_works(fo, existing, '2024-06-01', 50)

    assert result == {'renamed': 0, 'skipped': 1}
    assert existing['34816549']['HTML']['date'] is None


def test_a_dated_file_is_then_judged_by_the_ordinary_rule(tmp_path):
    # the whole point: once it has a date, staleness needs no special case
    make_file(tmp_path, '34816549 A.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])
    shared.stamp_undated_works(real_fileops(), existing, '2024-06-01', 50)

    records = [{'id': '34816549', 'link': 'https://ao3/works/34816549',
                'date_updated': '20 Dec 2024'}]
    plan = shared.plan_downloads(records, existing, ['HTML'])

    assert plan['stale'] == ['https://ao3/works/34816549']
    assert plan['undated'] == []


def test_a_file_dated_later_than_ao3_is_not_fetched_again(tmp_path):
    make_file(tmp_path, '34816549 A.html')
    existing = shared.scan_downloaded_works(str(tmp_path), ['HTML'])
    shared.stamp_undated_works(real_fileops(), existing, '2025-01-01', 50)

    records = [{'id': '34816549', 'link': 'https://ao3/works/34816549',
                'date_updated': '20 Dec 2024'}]
    plan = shared.plan_downloads(records, existing, ['HTML'])

    assert plan['stale'] == []

# endregion


# region plan_downloads

def record(work: str, updated: str) -> dict:
    return {'id': work, 'link': f'https://archiveofourown.org/works/{work}',
            'date_updated': updated}


def held(date, path='old.html') -> dict:
    return {'HTML': {'path': path, 'date': date}}


def test_a_work_updated_since_it_was_saved_is_fetched_again():
    plan = shared.plan_downloads(
        [record('1', '20 Dec 2024')], {'1': held('2024-12-14')}, ['HTML'])

    assert plan['stale'] == ['https://archiveofourown.org/works/1']
    assert plan['superseded']['https://archiveofourown.org/works/1']['HTML'] == 'old.html'


def test_a_work_that_has_not_changed_is_left_alone():
    plan = shared.plan_downloads(
        [record('1', '14 Dec 2024')], {'1': held('2024-12-14')}, ['HTML'])

    assert plan['stale'] == []
    assert plan['superseded'] == {}


def test_a_local_copy_newer_than_ao3_is_not_refetched():
    plan = shared.plan_downloads(
        [record('1', '01 Jan 2024')], {'1': held('2024-12-14')}, ['HTML'])

    assert plan['stale'] == []


def test_a_work_with_no_local_copy_is_not_listed_here():
    # nothing to replace: it is downloaded by the ordinary 'not done yet' route
    plan = shared.plan_downloads([record('1', '20 Dec 2024')], {}, ['HTML'])

    assert plan['stale'] == []
    assert plan['undated'] == []


def test_an_undated_copy_is_counted_but_left_alone():
    plan = shared.plan_downloads(
        [record('1', '20 Dec 2024')], {'1': held(None)}, ['HTML'])

    assert plan['stale'] == []
    assert plan['undated'] == ['https://archiveofourown.org/works/1']
    assert plan['superseded'] == {}


def test_an_undated_copy_is_refetched_when_the_run_asks_for_it():
    plan = shared.plan_downloads(
        [record('1', '20 Dec 2024')], {'1': held(None)}, ['HTML'], refresh_undated=True)

    assert plan['stale'] == ['https://archiveofourown.org/works/1']
    assert plan['superseded']['https://archiveofourown.org/works/1']['HTML'] == 'old.html'


def test_only_the_file_types_that_are_out_of_date_are_replaced():
    # re-downloading the html must not mark the epub for removal
    existing = {'1': {'HTML': {'path': 'old.html', 'date': '2024-01-01'},
                      'EPUB': {'path': 'new.epub', 'date': '2024-12-20'}}}

    plan = shared.plan_downloads([record('1', '20 Dec 2024')], existing, ['HTML', 'EPUB'])

    replacing = plan['superseded']['https://archiveofourown.org/works/1']
    assert replacing == {'HTML': 'old.html'}


def test_a_file_type_this_run_did_not_ask_for_is_never_touched():
    existing = {'1': {'HTML': {'path': 'old.html', 'date': '2024-01-01'},
                      'EPUB': {'path': 'old.epub', 'date': '2024-01-01'}}}

    plan = shared.plan_downloads([record('1', '20 Dec 2024')], existing, ['HTML'])

    assert plan['superseded']['https://archiveofourown.org/works/1'] == {'HTML': 'old.html'}


def test_a_work_whose_updated_date_cannot_be_read_is_left_alone():
    plan = shared.plan_downloads(
        [record('1', 'sometime')], {'1': held('2024-12-14')}, ['HTML'])

    assert plan['stale'] == []


def test_records_without_an_id_or_link_are_skipped():
    plan = shared.plan_downloads(
        [{'id': None, 'link': None, 'date_updated': '20 Dec 2024'}],
        {'1': held('2024-01-01')}, ['HTML'])

    assert plan == {'stale': [], 'undated': [], 'superseded': {}}

# endregion
