"""The files the hosted deployment is built from - and the setups it refuses to build."""

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import deploy_config
from deploy_config import DeployError


HOSTED = {'HELPER_URL': 'https://helper.example.com', 'REQUIRE_PASSCODE': 'true',
          'PAGE_ORIGIN': 'https://someone.github.io'}


@pytest.fixture(scope='module')
def private_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode('ascii')


def template() -> str:
    return deploy_config.TEMPLATE.read_text(encoding='utf-8')


# region settings.ini

def test_with_no_variables_the_helper_stays_on_this_computer_and_still_wants_a_passcode():
    # a hosted helper refuses to start without one, so a hosted build asks for it by default
    assert deploy_config.read_settings(deploy_config.write_settings({}, template())) == {
        'HelperUrl': 'http://127.0.0.1:4400', 'RequirePasscode': True, 'PageOrigin': ''}


def test_a_hosted_setup_fills_in_the_three_keys():
    written = deploy_config.read_settings(deploy_config.write_settings(HOSTED, template()))
    assert written == {'HelperUrl': 'https://helper.example.com', 'RequirePasscode': True,
                       'PageOrigin': 'https://someone.github.io'}


def test_the_comments_in_the_template_survive():
    # they are the only documentation someone opening the file in the image will have
    written = deploy_config.write_settings(HOSTED, template())
    assert '# setting this to true makes the helper refuse every request' in written
    assert 'ExtraWaitTime=15' in written


def test_a_trailing_slash_on_the_page_origin_is_dropped():
    written = deploy_config.write_settings({**HOSTED, 'PAGE_ORIGIN': 'https://someone.github.io/'},
                                           template())
    assert 'PageOrigin=https://someone.github.io\n' in written


@pytest.mark.parametrize('change, reason', [
    ({'HELPER_URL': 'http://helper.example.com'}, 'https'),
    ({'REQUIRE_PASSCODE': 'false'}, 'RequirePasscode=true'),
    ({'PAGE_ORIGIN': ''}, 'PageOrigin'),
    ({'PAGE_ORIGIN': 'https://someone.github.io/ao3downloader'}, 'scheme and host'),
    ({'HELPER_URL': 'https://helper.example.com/api'}, 'no path'),
    ({'HELPER_URL': 'helper.example.com'}, 'http(s)'),
    ({'REQUIRE_PASSCODE': 'maybe'}, 'true or false'),
])
def test_a_setup_that_could_not_work_is_refused_at_build_time(change, reason):
    with pytest.raises(DeployError, match=reason.replace('(', r'\(').replace(')', r'\)')):
        deploy_config.write_settings({**HOSTED, **change}, template())

@pytest.mark.parametrize('key, variable', [
    ('ExtraWaitTime', 'EXTRA_WAIT_TIME'), ('MaxRetries', 'MAX_RETRIES'),
    ('MaxTimeouts', 'MAX_TIMEOUTS'), ('FileNameLength', 'FILE_NAME_LENGTH'),
    ('EnableDebugLogging', 'ENABLE_DEBUG_LOGGING'), ('EnableDebugTools', 'ENABLE_DEBUG_TOOLS'),
    ('HelperUrl', 'HELPER_URL'), ('RequirePasscode', 'REQUIRE_PASSCODE'),
    ('PageOrigin', 'PAGE_ORIGIN'),
])
def test_each_setting_is_named_for_its_key_in_upper_snake_case(key, variable):
    assert deploy_config.variable_for(key) == variable


def test_every_key_in_the_template_is_set_from_its_variable():
    # anything settings.ini holds has to be settable from the deployment
    keys = [k for k in deploy_config.template_keys(template()) if k not in deploy_config.LEFT_OUT]
    given = {**HOSTED}
    for key in keys:
        if deploy_config.variable_for(key) in given: continue
        default = deploy_config.template_keys(template())[key]
        given[deploy_config.variable_for(key)] = (
            'true' if default == 'false' else 'false' if default == 'true' else '7')

    resolved = deploy_config.resolve(given, template())

    assert sorted(resolved) == sorted(keys)
    for key in keys:
        assert resolved[key][1] == f'variable {deploy_config.variable_for(key)}', key


def test_a_key_added_to_the_template_later_is_settable_without_any_change_here():
    grown = template() + '\n# a setting nobody has thought of yet\nSomeNewSetting=5\n'
    written = deploy_config.write_settings({**HOSTED, 'SOME_NEW_SETTING': '9'}, grown)
    assert 'SomeNewSetting=9' in written


def test_a_variable_that_is_not_set_keeps_the_template_default():
    resolved = deploy_config.resolve(HOSTED, template())
    assert resolved['ExtraWaitTime'] == ('15', 'template default')


def test_the_page_origin_defaults_to_the_github_pages_address_given():
    without = {k: v for k, v in HOSTED.items() if k != 'PAGE_ORIGIN'}
    resolved = deploy_config.resolve(without, template(), 'https://someone.github.io')
    assert resolved['PageOrigin'] == ('https://someone.github.io', 'hosted default')


def test_a_page_origin_variable_wins_over_the_default():
    resolved = deploy_config.resolve({**HOSTED, 'PAGE_ORIGIN': 'https://mine.example'},
                                     template(), 'https://someone.github.io')
    assert resolved['PageOrigin'] == ('https://mine.example', 'variable PAGE_ORIGIN')


def test_the_password_setting_is_left_out_as_the_bundle_leaves_it_out():
    # the web page never stores a password
    written = deploy_config.write_settings({**HOSTED, 'SAVE_PASSWORD': 'true'}, template())
    assert 'SavePassword' not in written
    assert 'save your password' not in written


@pytest.mark.parametrize('variable, value, reason', [
    ('EXTRA_WAIT_TIME', 'fifteen', 'whole number'),
    ('MAX_RETRIES', '-1', 'whole number'),
    ('ENABLE_DEBUG_TOOLS', 'sometimes', 'true or false'),
])
def test_a_value_of_the_wrong_kind_fails_the_build_naming_the_variable(variable, value, reason):
    with pytest.raises(DeployError, match=variable) as refused:
        deploy_config.write_settings({**HOSTED, variable: value}, template())
    assert reason in str(refused.value)


def test_booleans_are_written_the_way_the_template_writes_them():
    written = deploy_config.write_settings({**HOSTED, 'ENABLE_DEBUG_TOOLS': 'Yes'}, template())
    assert 'EnableDebugTools=true' in written


def test_the_variables_arrive_as_json_from_the_workflow():
    got = deploy_config.deploy_variables({'DEPLOY_VARIABLES': json.dumps({'EXTRA_WAIT_TIME': '20'}),
                                          'EXTRA_WAIT_TIME': '5'})
    # the workflow's own variables win over anything else in the environment
    assert got['EXTRA_WAIT_TIME'] == '20'


def test_variables_that_are_not_json_fail_the_build():
    with pytest.raises(DeployError, match='DEPLOY_VARIABLES'):
        deploy_config.deploy_variables({'DEPLOY_VARIABLES': 'not json'})

# endregion


# region app-config.json

def test_the_page_config_carries_the_public_half_of_the_key_only(private_pem):
    settings = deploy_config.write_settings(HOSTED, template())

    config = deploy_config.page_config(settings, {deploy_config.ENV_PRIVATE_KEY: private_pem})

    assert config['helperUrl'] == 'https://helper.example.com'
    assert config['requirePasscode'] is True
    assert config['publicKey'].startswith('-----BEGIN PUBLIC KEY-----')
    # the whole file goes onto a public website
    assert 'PRIVATE' not in json.dumps(config)


def test_the_public_key_matches_the_private_one_the_helper_decrypts_with(private_pem):
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    expected = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    config = deploy_config.page_config(deploy_config.write_settings(HOSTED, template()),
                                       {deploy_config.ENV_PRIVATE_KEY: private_pem})

    assert config['publicKey'] == expected


def test_a_hosted_page_without_the_key_is_refused():
    with pytest.raises(DeployError, match=deploy_config.ENV_PRIVATE_KEY):
        deploy_config.page_config(deploy_config.write_settings(HOSTED, template()), {})


def test_the_page_for_this_computer_needs_no_key():
    settings = deploy_config.write_settings({'REQUIRE_PASSCODE': 'false'}, template())
    config = deploy_config.page_config(settings, {})
    assert config == {'helperUrl': 'http://127.0.0.1:4400', 'requirePasscode': False,
                      'publicKey': '', 'version': '', 'releasesRepo': ''}


def test_the_command_line_writes_both_files(tmp_path, monkeypatch, private_pem, capsys):
    # the way the workflow runs it: every variable as json, and the pages address beside it
    monkeypatch.setenv('DEPLOY_VARIABLES', json.dumps(
        {'HELPER_URL': 'https://helper.example.com', 'EXTRA_WAIT_TIME': '20'}))
    monkeypatch.setenv('DEFAULT_PAGE_ORIGIN', 'https://someone.github.io')
    monkeypatch.setenv(deploy_config.ENV_PRIVATE_KEY, private_pem)
    settings = tmp_path / 'settings.ini'
    page = tmp_path / 'app-config.json'

    assert deploy_config.main(['settings', '--out', str(settings)]) == 0
    assert deploy_config.main(['page-config', '--settings', str(settings), '--out', str(page)]) == 0

    assert json.loads(page.read_text())['helperUrl'] == 'https://helper.example.com'
    said = capsys.readouterr().out
    # every value is shown with where it came from, so a deploy can be read back from its log
    assert 'ExtraWaitTime=20  (variable EXTRA_WAIT_TIME)' in said
    assert 'MaxRetries=30  (template default)' in said
    assert 'PageOrigin=https://someone.github.io  (hosted default)' in said


def test_the_command_line_fails_the_build_on_a_bad_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HELPER_URL', 'http://helper.example.com')
    monkeypatch.setenv('REQUIRE_PASSCODE', 'true')
    monkeypatch.setenv('PAGE_ORIGIN', 'https://someone.github.io')

    assert deploy_config.main(['settings', '--out', str(tmp_path / 's.ini')]) == 1
    assert 'https' in capsys.readouterr().err

# endregion


# region the Windows app's settings.ini

RENDER = {'HELPER_URL': 'https://my-ao3-helper.onrender.com', 'REQUIRE_PASSCODE': 'true',
          'PAGE_ORIGIN': 'https://someone-else.github.io', 'EXTRA_WAIT_TIME': '30',
          'FILE_NAME_LENGTH': '80'}


def test_the_windows_app_takes_every_other_setting_from_the_variables():
    written = deploy_config.write_local_settings(RENDER, template())

    assert 'ExtraWaitTime=30\n' in written
    assert 'FileNameLength=80\n' in written


def test_the_windows_app_points_at_its_own_helper_whatever_the_variables_say():
    written = deploy_config.write_local_settings(RENDER, template())

    assert deploy_config.read_settings(written) == {
        'HelperUrl': 'http://127.0.0.1:4400', 'RequirePasscode': False, 'PageOrigin': ''}


def test_the_hosted_helper_and_page_are_named_nowhere_in_the_windows_apps_settings():
    written = deploy_config.write_local_settings(RENDER, template(), 'https://alexandria-p.github.io')

    assert 'my-ao3-helper.onrender.com' not in written
    assert 'someone-else.github.io' not in written
    assert 'alexandria-p.github.io' not in written


def test_a_hosted_address_carried_into_another_setting_fails_the_build():
    # a variable holding the hosted helper's address under some other name would put it in
    # the file all the same - the check is on the text, not only on the three keys
    smuggled = {**RENDER, 'EXTRA_WAIT_TIME': '30'}
    text = template().replace('ExtraWaitTime=15', 'ExtraWaitTime=15\nNote=')
    smuggled['NOTE'] = 'see https://my-ao3-helper.onrender.com'

    with pytest.raises(DeployError, match='my-ao3-helper.onrender.com'):
        deploy_config.write_local_settings(smuggled, text)


def test_the_windows_app_always_shows_what_it_is_doing_in_its_window():
    # its window is the only place anyone sees the requests and a run's lines - on whatever
    # the hosted copy is set to
    for given in ('false', 'true', ''):
        written = deploy_config.write_local_settings({**RENDER, 'ENABLE_CONSOLE_LOGGING': given},
                                                     template())
        assert 'EnableConsoleLogging=true\n' in written


def test_the_hosted_copy_still_takes_console_logging_from_its_variable():
    written = deploy_config.write_settings({**HOSTED, 'ENABLE_CONSOLE_LOGGING': 'false'}, template())

    assert 'EnableConsoleLogging=false\n' in written


def test_the_windows_app_leaves_out_the_password_setting_as_every_page_build_does():
    written = deploy_config.write_local_settings({}, template())

    assert 'SavePassword' not in written


def test_the_windows_app_adds_nothing_the_template_does_not_have():
    # only values change: the same keys and the same comments, in the same order
    written = deploy_config.write_local_settings(RENDER, template())
    keys = list(deploy_config.template_keys(written))
    expected = [k for k in deploy_config.template_keys(template()) if k not in deploy_config.LEFT_OUT]

    assert keys == expected
    comments = [line for line in written.splitlines() if line.startswith('#')]
    assert comments == [line for line in deploy_config.strip_setting(template(), 'SavePassword').splitlines()
                        if line.startswith('#')]


def test_the_command_line_writes_the_windows_apps_settings(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('DEPLOY_VARIABLES', json.dumps(RENDER))
    out = tmp_path / 'windows-settings.ini'

    assert deploy_config.main(['local-settings', '--out', str(out)]) == 0

    written = out.read_text(encoding='utf-8')
    assert 'HelperUrl=http://127.0.0.1:4400\n' in written
    assert 'my-ao3-helper.onrender.com' not in capsys.readouterr().out

# endregion


# region the version a deployment builds

@pytest.mark.parametrize('tags, expected', [
    ([], '1.0.0'),
    (['v1.8.2'], '1.8.3'),
    (['v1.8.2', 'v1.10.0', 'v1.9.7'], '1.10.1'),
    # anything that is not v and three numbers is not a release of this app
    (['v1.8.2', 'windows-app', 'v2', 'release-9.9.9', 'v1.9.x'], '1.8.3'),
])
def test_each_deployment_raises_the_last_number_of_the_latest_release(tags, expected):
    assert deploy_config.next_version(tags) == expected


def test_a_version_can_be_given_for_a_bigger_step():
    assert deploy_config.next_version(['v1.8.2'], '2.0.0') == '2.0.0'
    assert deploy_config.next_version(['v1.8.2'], 'v1.9.0') == '1.9.0'
    assert deploy_config.next_version([], '0.1.0') == '0.1.0'


@pytest.mark.parametrize('override', ['1.8.2', '1.8.1', '0.9.0'])
def test_a_given_version_already_released_or_older_fails_the_deploy(override):
    # two builds sharing a version would tell people with the first that they are up to date
    with pytest.raises(DeployError, match='not higher than 1.8.2'):
        deploy_config.next_version(['v1.8.2'], override)


@pytest.mark.parametrize('override', ['2', '2.0', 'two', '2.0.0-beta'])
def test_a_given_version_that_is_not_three_numbers_fails_the_deploy(override):
    with pytest.raises(DeployError, match='three numbers'):
        deploy_config.next_version(['v1.8.2'], override)


def test_the_command_line_prints_the_version(capsys):
    assert deploy_config.main(['next-version', '--tags', 'v1.8.2\nv1.8.1\n']) == 0
    assert capsys.readouterr().out.strip() == '1.8.3'


def test_the_page_config_carries_the_version_and_where_releases_are():
    config = deploy_config.page_config(deploy_config.write_settings({}, template()), {}, '1.8.3',
                                       'someone/ao3downloader')

    assert config['version'] == '1.8.3'
    assert config['releasesRepo'] == 'someone/ao3downloader'


@pytest.mark.parametrize('version, repo, reason', [
    ('1.8', 'someone/ao3downloader', 'three numbers'),
    ('1.8.3', 'https://evil.example', 'owner/name'),
])
def test_a_page_config_with_a_bad_version_or_repository_fails_the_build(version, repo, reason):
    with pytest.raises(DeployError, match=reason):
        deploy_config.page_config(deploy_config.write_settings({}, template()), {}, version, repo)

# endregion
