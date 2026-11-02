"""The time limits and default answers settings.ini now holds.

Every question a run stops to ask takes a default when nobody answers it - on a timeout and
on a background run that was not told - and how long it waits is `QuestionTimeoutMinutes`.
The waits on ao3 (`RequestTimeoutSeconds` and the rest) and on the page
(`LibraryTimeoutMinutes`, `PageGoneSeconds`) are settings too. The template's values are
exactly what the code did before they were settings, so Reset to defaults puts them back.
"""

import os
from unittest.mock import MagicMock

import pytest

import deploy_config
from source_code import server, settings_file, strings
from source_code.fileio import FileOps
from source_code.repo import Repository

QUESTION = {'name': server.FICHUB_QUESTION, 'count': 1, 'choices': ['yes', 'no']}


def settings(**values) -> None:
    """A settings.ini holding just these values, where the helper reads it."""

    lines = '\n'.join(f'{key}={value}' for key, value in values.items())
    with open(FileOps().inifile, 'w', encoding='utf-8') as f:
        f.write(f'[settings]\n{lines}\n')


def a_job() -> server.Job:
    return server.Job(server.ACTION_BOOKMARKS, ['JSON'], 'Someone')


# region the template's defaults are what the code did before

def template() -> dict[str, str]:
    return {x['key']: x['default'] for x in settings_file.editable_settings(
        settings_file.template_text())}


def test_the_template_keeps_todays_answers_and_time_limits():
    assert {key: template()[key] for key in strings.INI_ANSWER_CHOICES} == {
        strings.INI_UNDATED_ANSWER: server.UNDATED_SKIP,
        strings.INI_QUICK_FLOOR_ANSWER: server.QUICK_FULL,
        strings.INI_DUPLICATES_ANSWER: server.DUPLICATES_LEAVE,
        strings.INI_FICHUB_ANSWER: 'yes',
        strings.INI_FICHUB_OUTDATED_ANSWER: 'yes',
        strings.INI_OVERWRITE_OLDER_ANSWER: 'no',
    }
    assert template()[strings.INI_QUESTION_TIMEOUT] == str(server.ANSWER_TIMEOUT_SECONDS // 60)
    assert template()[strings.INI_REQUEST_TIMEOUT] == str(Repository.timeout)
    assert template()[strings.INI_STILL_WAITING] == str(Repository.waiting_note)
    assert template()[strings.INI_MAINTENANCE_RETRIES] == str(Repository.maintenance_retries)
    assert template()[strings.INI_MAINTENANCE_DELAY] == str(Repository.maintenance_delay)
    assert template()[strings.INI_RETRY_MAX_DELAY] == str(Repository.retry_max_delay)
    assert template()[strings.INI_LIBRARY_TIMEOUT] == str(server.STORAGE_TIMEOUT_SECONDS // 60)
    assert template()[strings.INI_PAGE_GONE] == str(server.PAGE_GRACE_SECONDS)


def test_every_answer_setting_offers_only_answers_its_question_has():
    for name, key in server.ANSWER_SETTING_FOR.items():
        assert set(strings.INI_ANSWER_CHOICES[key]) <= set(server.CHOICES_FOR[name])
        # the built-in default comes first, and is the template's
        assert strings.INI_ANSWER_CHOICES[key][0] == template()[key]

# endregion


# region a question nobody answers

def test_a_question_nobody_answers_takes_the_answer_settings_ini_gives(monkeypatch):
    settings(QuestionTimeoutMinutes=1, FicHubAnswer='no')
    monkeypatch.setattr(server, 'question_timeout_seconds', lambda: 0.01)

    assert a_job().ask(QUESTION, {'choice': 'yes'}) == {'choice': 'no'}


def test_a_timeout_of_0_takes_the_default_without_asking():
    settings(QuestionTimeoutMinutes=0, OverwriteNewerCopyAnswer='yes')
    job = a_job()
    job.emit = MagicMock()

    answer = job.ask({'name': server.OVERWRITE_OLDER_QUESTION}, {'choice': 'no'})

    assert answer == {'choice': 'yes'}
    job.emit.assert_not_called()


def test_a_background_run_not_told_takes_settings_ini_s_answer():
    settings(DuplicateCopiesAnswer='newest')
    job = a_job()
    job.background = True

    assert job.ask({'name': server.DUPLICATES_QUESTION}, {'choice': 'leave'}) == {'choice': 'newest'}


def test_a_stop_still_takes_the_answer_that_changes_nothing():
    settings(UndatedFilesAnswer='refresh')
    job = a_job()
    job.cancel.set()

    assert job.ask({'name': server.UNDATED_QUESTION}, {'choice': 'skip', 'date': ''}) == \
        {'choice': 'skip', 'date': ''}


def test_a_misspelt_answer_leaves_the_built_in_default():
    settings(FicHubAnswer='maybe')
    assert server.configured_answer(server.FICHUB_QUESTION, {'choice': 'yes'}) == {'choice': 'yes'}


def test_the_question_tells_the_page_its_default_and_how_long_it_waits(monkeypatch):
    settings(QuestionTimeoutMinutes=5, FicHubAnswer='no')
    job = a_job()
    sent = []
    job.emit = sent.append
    job.cancel.set()

    job.ask(QUESTION, {'choice': 'yes'})

    assert sent[0]['default'] == 'no' and sent[0]['timeoutMinutes'] == 5


def test_the_page_is_told_each_question_s_default():
    settings(QuickScanFloorAnswer='since')
    answers = server.read_settings(FileOps())['answerDefaults']
    assert answers[server.QUICK_QUESTION] == 'since'
    assert answers[server.FICHUB_QUESTION] == 'yes'

# endregion


# region the waits on ao3 and on the page

def test_a_run_s_requests_take_their_time_limits_from_settings_ini():
    settings(RequestTimeoutSeconds=120, StillWaitingSeconds=30, MaintenanceRetries=5,
             MaintenanceRetrySeconds=90, RetryMaxWaitSeconds=10)
    repo = Repository(FileOps())
    assert (repo.timeout, repo.waiting_note, repo.maintenance_retries, repo.maintenance_delay,
            repo.retry_max_delay) == (120, 30, 5, 90, 10)


def test_a_request_time_limit_of_0_is_read_as_1_second():
    settings(RequestTimeoutSeconds=0)
    assert Repository(FileOps()).timeout == 1


def test_without_settings_the_time_limits_are_as_they_were():
    repo = Repository(MagicMock())
    assert (repo.timeout, repo.waiting_note, repo.maintenance_retries) == (60, 15, 2)


def test_a_page_gone_for_longer_than_settings_ini_allows_ends_the_wait(monkeypatch):
    settings(PageGoneSeconds=0)
    job = a_job()
    job.last_listener = 0

    with pytest.raises(OSError):
        job.storage_call('read', {})

# endregion


# region editing them

def test_an_answer_setting_is_offered_as_a_choice_and_refuses_anything_else():
    [setting] = [x for x in settings_file.editable_settings(settings_file.template_text())
                 if x['key'] == strings.INI_FICHUB_ANSWER]
    assert setting['kind'] == settings_file.CHOICE and setting['choices'] == ['yes', 'no']
    assert settings_file.checked_value(setting, 'NO') == 'no'
    with pytest.raises(ValueError):
        settings_file.checked_value(setting, 'maybe')


def test_a_deploy_refuses_an_answer_the_question_does_not_have():
    with pytest.raises(deploy_config.DeployError):
        deploy_config.checked(strings.INI_FICHUB_ANSWER, 'maybe', 'yes')
    assert deploy_config.checked(strings.INI_FICHUB_ANSWER, 'No', 'yes') == 'no'

# endregion
