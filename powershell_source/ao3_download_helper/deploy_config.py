"""The files a hosted deployment is built from, written by the GitHub Actions pipeline.

    python deploy_config.py settings --out hosted-settings.ini
    python deploy_config.py page-config --settings hosted-settings.ini --out app-config.json

`settings` starts from the settings.ini template and fills in the three keys a hosted setup
changes, from the workflow's variables:

    HELPER_URL        -> HelperUrl        where the page finds the helper
    REQUIRE_PASSCODE  -> RequirePasscode  true/false
    PAGE_ORIGIN       -> PageOrigin       the page's address, allowed through CORS

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

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'source_code' / 'settings' / 'settings.ini'

SECTION = 'settings'
HELPER_URL = 'HelperUrl'
REQUIRE_PASSCODE = 'RequirePasscode'
PAGE_ORIGIN = 'PageOrigin'

ENV_FOR = {HELPER_URL: 'HELPER_URL', REQUIRE_PASSCODE: 'REQUIRE_PASSCODE', PAGE_ORIGIN: 'PAGE_ORIGIN'}
ENV_PRIVATE_KEY = 'AO3DOWNLOADER_PRIVATE_KEY'


class DeployError(Exception):
    """A deployment that could not work, and why."""


def is_loopback(host: str) -> bool:
    return host == 'localhost' or host == '::1' or host.startswith('127.')


def boolean(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ('true', 'yes', '1', 'on'): return True
    if lowered in ('false', 'no', '0', 'off', ''): return False
    raise DeployError(f"'{value}' is not true or false")


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


def write_settings(environ: dict, template: str) -> str:
    text = template
    values = {key: environ.get(env, '').strip() for key, env in ENV_FOR.items()}
    if values[REQUIRE_PASSCODE]: values[REQUIRE_PASSCODE] = str(boolean(values[REQUIRE_PASSCODE])).lower()
    values[PAGE_ORIGIN] = values[PAGE_ORIGIN].rstrip('/')
    for key, value in values.items():
        if value: text = set_key(text, key, value)

    config = read_settings(text)
    check(config[HELPER_URL], config[REQUIRE_PASSCODE], config[PAGE_ORIGIN])
    return text


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
            text = write_settings(dict(os.environ), TEMPLATE.read_text(encoding='utf-8'))
            Path(args.out).write_text(text, encoding='utf-8')
            shown = read_settings(text)
            print(f'wrote {args.out}: ' + ', '.join(f'{k}={v}' for k, v in shown.items()))
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
