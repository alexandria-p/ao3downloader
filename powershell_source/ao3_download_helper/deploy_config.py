"""The files a hosted deployment is built from, written by the GitHub Actions pipeline.

    python deploy_config.py settings --out hosted-settings.ini
    python deploy_config.py page-config --settings hosted-settings.ini --out app-config.json

`settings` starts from the settings.ini template and sets **every key in it** from a GitHub
variable of the same name in upper snake case - `ExtraWaitTime` from `EXTRA_WAIT_TIME`,
`HelperUrl` from `HELPER_URL`, and so on (`variable_for`). The names are worked out from the
template rather than listed here, so a key added to settings.ini later can be set from a
variable the moment it exists, without anyone remembering to wire it up. The workflow hands
over all its variables at once (`DEPLOY_VARIABLES`, which is `toJSON(vars)`) for the same
reason.

A variable that is not set leaves the template's default, except where a hosted copy needs
something else (`HOSTED_DEFAULTS`): `RequirePasscode` is on, and `PageOrigin` is the GitHub
Pages address the workflow passes in. The log says which value came from where.
`SavePassword` is left out altogether (`LEFT_OUT`), as the bundle leaves it out: the web page
never stores a password, so the setting would only invite confusion.

Values are checked against the kind the template's default is - `true`/`false`, or a whole
number - so a typo fails the build instead of the helper.

The result is baked into the helper's image **and** read back by `page-config`, so the page
and the helper are built from one settings.ini and cannot disagree about where the helper is
or whether it wants a passcode.

`page-config` writes the page's `app-config.json`: the helper url, the passcode flag, and the
public key, which it derives from `AO3DOWNLOADER_PRIVATE_KEY` rather than taking as a second
setting - a public key typed in separately is one that can stop matching.

**Neither file ever holds a secret.** The passcode and the private key stay GitHub secrets,
handed to the host as environment variables. settings.ini goes into a public image and
app-config.json onto a public website.

Everything that would make a deployment that cannot work is refused here, at build time,
rather than discovered by the page afterwards.
"""

import argparse
import configparser
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization

from build_artifacts import strip_setting

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'source_code' / 'settings' / 'settings.ini'

SECTION = 'settings'
HELPER_URL = 'HelperUrl'
REQUIRE_PASSCODE = 'RequirePasscode'
PAGE_ORIGIN = 'PageOrigin'

ENV_PRIVATE_KEY = 'AO3DOWNLOADER_PRIVATE_KEY'
# every GitHub variable, as json - the workflow passes `toJSON(vars)`
ENV_VARIABLES = 'DEPLOY_VARIABLES'
# the page's own address, worked out by the workflow, for when PAGE_ORIGIN is not set
ENV_DEFAULT_PAGE_ORIGIN = 'DEFAULT_PAGE_ORIGIN'

# the web page never stores a password, so a hosted copy has no use for this; the bundle
# strips it for the same reason
LEFT_OUT = ('SavePassword',)
# where a hosted copy needs something other than the template's default. a hosted helper
# refuses to start without a passcode, so asking for one is the only default that can work
HOSTED_DEFAULTS = {REQUIRE_PASSCODE: 'true'}

KEY_LINE = re.compile(r'^([A-Za-z][A-Za-z0-9]*)\s*=(.*)$', re.MULTILINE)


class DeployError(Exception):
    """A deployment that could not work, and why."""


def is_loopback(host: str) -> bool:
    return host == 'localhost' or host == '::1' or host.startswith('127.')


def boolean(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ('true', 'yes', '1', 'on'): return True
    if lowered in ('false', 'no', '0', 'off', ''): return False
    raise DeployError(f"'{value}' is not true or false")


def variable_for(key: str) -> str:
    """The GitHub variable a settings.ini key is set from: `ExtraWaitTime` -> `EXTRA_WAIT_TIME`."""

    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', '_', key).upper()


def template_keys(template: str) -> dict[str, str]:
    """Every key in the template, in order, with its default value."""

    return {m.group(1): m.group(2).strip() for m in KEY_LINE.finditer(template)}


def checked(key: str, value: str, default: str) -> str:
    """A value of the kind the template's default is, or a DeployError saying what is wrong."""

    variable = variable_for(key)
    if default.lower() in ('true', 'false'):
        try:
            return str(boolean(value)).lower()
        except DeployError:
            raise DeployError(f"{variable} is '{value}', but {key} is true or false") from None
    if default.isdigit():
        if not value.strip().isdigit():
            raise DeployError(f"{variable} is '{value}', but {key} is a whole number")
        return str(int(value))
    return value.strip()


def set_key(text: str, key: str, value: str) -> str:
    """Set one key in settings.ini's text, keeping every comment the template carries.

    configparser would lose the comments, and they are the only documentation someone
    opening the file in the image will have.
    """

    pattern = re.compile(rf'^{re.escape(key)}\s*=.*$', re.MULTILINE)
    if pattern.search(text): return pattern.sub(lambda _: f'{key}={value}', text, count=1)
    return text.rstrip('\n') + f'\n\n{key}={value}\n'


def check(helper_url: str, require_passcode: bool, page_origin: str) -> None:
    """Refuse a combination that would build a page unable to use its helper."""

    url = urlparse(helper_url)
    if url.scheme not in ('http', 'https') or not url.hostname:
        raise DeployError(f"{HELPER_URL} '{helper_url}' is not an http(s) address")
    if url.path not in ('', '/') or url.query:
        raise DeployError(f'{HELPER_URL} is the address of the helper itself, with no path')
    hosted = not is_loopback(url.hostname)
    # a page on https is not allowed to call plain http anywhere but this computer
    if hosted and url.scheme != 'https':
        raise DeployError(f'{HELPER_URL} has to be https:// for a hosted helper - the page on '
                          'GitHub Pages is https, and browsers block it calling plain http')
    if hosted and not require_passcode:
        raise DeployError(f'a hosted helper needs {REQUIRE_PASSCODE}=true - it will refuse to '
                          'start without it')
    if page_origin:
        origin = urlparse(page_origin)
        if origin.scheme not in ('http', 'https') or not origin.hostname \
                or origin.path not in ('', '/') or origin.query:
            raise DeployError(f"{PAGE_ORIGIN} '{page_origin}' should be just the scheme and "
                              'host, e.g. https://someone.github.io')
    elif hosted:
        raise DeployError(f'a hosted helper needs {PAGE_ORIGIN}, or the browser will not let '
                          'the page read its answers')


def resolve(variables: dict, template: str, default_page_origin: str = '') -> dict:
    """Every key the hosted settings.ini will hold: `{key: (value, where it came from)}`."""

    defaults = dict(HOSTED_DEFAULTS)
    if default_page_origin: defaults[PAGE_ORIGIN] = default_page_origin
    resolved = {}
    for key, template_default in template_keys(template).items():
        if key in LEFT_OUT: continue
        given = str(variables.get(variable_for(key)) or '').strip()
        if given:
            value, source = given, f'variable {variable_for(key)}'
        elif key in defaults:
            value, source = defaults[key], 'hosted default'
        else:
            value, source = template_default, 'template default'
        value = checked(key, value, template_default)
        if key == PAGE_ORIGIN: value = value.rstrip('/')
        resolved[key] = (value, source)
    return resolved


def write_settings(variables: dict, template: str, default_page_origin: str = '') -> str:
    """settings.ini for a hosted helper: the template, every key set from `variables`."""

    text = template
    # the bundler's own stripping, so a setting left out goes the same way in both
    for key in LEFT_OUT: text = strip_setting(text, key)
    for key, (value, _) in resolve(variables, template, default_page_origin).items():
        text = set_key(text, key, value)

    config = read_settings(text)
    check(config[HELPER_URL], config[REQUIRE_PASSCODE], config[PAGE_ORIGIN])
    return text


def deploy_variables(environ: dict) -> dict:
    """The GitHub variables, from `DEPLOY_VARIABLES`, over any set directly in the environment.

    The environment is read too so the script can be run by hand with ordinary variables.
    """

    try:
        given = json.loads(environ.get(ENV_VARIABLES) or '{}')
    except json.JSONDecodeError as e:
        raise DeployError(f'{ENV_VARIABLES} is not json') from e
    return {**environ, **(given if isinstance(given, dict) else {})}


def read_settings(text: str) -> dict:
    parser = configparser.ConfigParser()
    parser.read_string(text)
    section = parser[SECTION] if parser.has_section(SECTION) else {}
    return {
        HELPER_URL: (section.get(HELPER_URL) or 'http://127.0.0.1:4400').strip().rstrip('/'),
        REQUIRE_PASSCODE: boolean(section.get(REQUIRE_PASSCODE) or 'false'),
        PAGE_ORIGIN: (section.get(PAGE_ORIGIN) or '').strip().rstrip('/'),
    }


def public_key_from(private_pem: str) -> str:
    pem = private_pem.replace('\\n', '\n').strip()
    try:
        key = serialization.load_pem_private_key(pem.encode('utf-8'), password=None)
    except Exception as e:
        raise DeployError(f'{ENV_PRIVATE_KEY} is not a PEM private key') from e
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode('ascii')


def page_config(settings_text: str, environ: dict) -> dict:
    config = read_settings(settings_text)
    check(config[HELPER_URL], config[REQUIRE_PASSCODE], config[PAGE_ORIGIN])
    private = environ.get(ENV_PRIVATE_KEY, '')
    hosted = not is_loopback(urlparse(config[HELPER_URL]).hostname or '')
    if hosted and not private.strip():
        raise DeployError(f'a hosted helper only takes the login encrypted, so the page needs '
                          f'the public key - set the {ENV_PRIVATE_KEY} secret')
    return {
        'helperUrl': config[HELPER_URL],
        'requirePasscode': config[REQUIRE_PASSCODE],
        'publicKey': public_key_from(private) if private.strip() else '',
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    settings = commands.add_parser('settings', help='write settings.ini for a hosted helper')
    settings.add_argument('--out', required=True)
    page = commands.add_parser('page-config', help="write the page's app-config.json")
    page.add_argument('--settings', required=True)
    page.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == 'settings':
            template = TEMPLATE.read_text(encoding='utf-8')
            variables = deploy_variables(dict(os.environ))
            origin = os.environ.get(ENV_DEFAULT_PAGE_ORIGIN, '')
            text = write_settings(variables, template, origin)
            Path(args.out).write_text(text, encoding='utf-8')
            print(f'wrote {args.out}:')
            # nothing in settings.ini is secret, so every value can be shown
            for key, (value, source) in resolve(variables, template, origin).items():
                print(f'  {key}={value}  ({source})')
        else:
            config = page_config(Path(args.settings).read_text(encoding='utf-8'), dict(os.environ))
            Path(args.out).write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
            print(f"wrote {args.out}: helperUrl={config['helperUrl']}, "
                  f"requirePasscode={config['requirePasscode']}, "
                  f"publicKey={'set' if config['publicKey'] else 'none'}")
    except DeployError as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
