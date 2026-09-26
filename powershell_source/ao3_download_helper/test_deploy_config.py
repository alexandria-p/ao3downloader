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

def test_the_template_as_it_is_is_a_valid_setup_for_this_computer():
    assert deploy_config.read_settings(deploy_config.write_settings({}, template())) == {
        'HelperUrl': 'http://127.0.0.1:4400', 'RequirePasscode': False, 'PageOrigin': ''}


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
    config = deploy_config.page_config(deploy_config.write_settings({}, template()), {})
    assert config == {'helperUrl': 'http://127.0.0.1:4400', 'requirePasscode': False,
                      'publicKey': ''}


def test_the_command_line_writes_both_files(tmp_path, monkeypatch, private_pem):
    for name, value in HOSTED.items(): monkeypatch.setenv(name, value)
    monkeypatch.setenv(deploy_config.ENV_PRIVATE_KEY, private_pem)
    settings = tmp_path / 'settings.ini'
    page = tmp_path / 'app-config.json'

    assert deploy_config.main(['settings', '--out', str(settings)]) == 0
    assert deploy_config.main(['page-config', '--settings', str(settings), '--out', str(page)]) == 0

    assert json.loads(page.read_text())['helperUrl'] == 'https://helper.example.com'


def test_the_command_line_fails_the_build_on_a_bad_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('HELPER_URL', 'http://helper.example.com')
    monkeypatch.setenv('REQUIRE_PASSCODE', 'true')
    monkeypatch.setenv('PAGE_ORIGIN', 'https://someone.github.io')

    assert deploy_config.main(['settings', '--out', str(tmp_path / 's.ini')]) == 1
    assert 'https' in capsys.readouterr().err

# endregion
