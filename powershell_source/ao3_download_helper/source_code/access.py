"""Who may use this helper, and how an ao3 login reaches it.

A helper on this computer, listening on the loopback interface, needs none of this: nothing
off the machine can reach it. A **hosted** helper - one run on a server so a page on GitHub
Pages can use it - can be reached by anyone who finds its address, and it holds an ao3 login
for as long as a run takes. Two things make that safe enough for one person's own instance:

- **a passcode**, required on every request once `RequirePasscode` is on. It is the helper's
  secret, read from an environment variable and never from settings.ini: settings.ini is
  baked into the image and copied into bundles, so anything in it is as good as public.
- **an encrypted login.** The page encrypts the ao3 username and password with the helper's
  public key before sending them, so they are unreadable to anything between the two that
  sees the request after https has been taken off it - a proxy, a host's logs. Only the
  private key, another environment variable, can read them. The page carries the public key
  from its own build rather than asking the helper for one, so a helper at the wrong address
  cannot hand the page a key of its own and be sent the login.

This is not salting. A salted hash cannot be turned back into the password, and the helper
has to type the real password into ao3's login form.

Each encrypted login carries the time it was sealed and a random nonce, and is refused if
it is old or has been seen before, so one copied out of a log cannot be sent again later.
"""

import base64
import binascii
import hmac
import json
import os
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from source_code import strings


# the passcode the page must send, and the private key its logins are sealed with. secrets,
# so environment variables - never settings.ini, which ships in images and bundles
ENV_PASSCODE = 'AO3DOWNLOADER_PASSCODE'
ENV_PRIVATE_KEY = 'AO3DOWNLOADER_PRIVATE_KEY'

# how old a sealed login may be. long enough for a slow connection and a clock a little out
# of step, short enough that one lifted from a log has gone stale before anyone could use it
LOGIN_MAX_AGE_SECONDS = 5 * 60

# the scheme the page names its passcode with, in the Authorization header
BEARER = 'Bearer '


class AccessError(Exception):
    """A request the helper will not act on, with the reason to give back."""


# region settings

def passcode_required(fileops) -> bool:
    return fileops.get_ini_value_boolean(strings.INI_REQUIRE_PASSCODE, False)


def page_origin(fileops) -> str:
    """The one non-loopback origin allowed to call this helper, or '' for none.

    A trailing slash is dropped because a browser's Origin header never has one, and the
    comparison is exact.
    """

    return (fileops.get_ini_value(strings.INI_PAGE_ORIGIN, '') or '').strip().rstrip('/')


def configured_passcode() -> str:
    return os.environ.get(ENV_PASSCODE, '')


def configured_private_key() -> str:
    # a multi-line PEM pasted into a single-line field often arrives with literal '\n's
    return os.environ.get(ENV_PRIVATE_KEY, '').replace('\\n', '\n').strip()

# endregion


# region the passcode

def passcode_matches(header: str | None, expected: str) -> bool:
    """Whether an Authorization header carries the passcode.

    Compared in constant time, so how long a wrong guess takes to refuse says nothing about
    how much of it was right. An empty expected passcode matches nothing: a helper told to
    require one and not given one must refuse everybody rather than accept an empty guess.
    """

    if not expected or not header or not header.startswith(BEARER): return False
    return hmac.compare_digest(header[len(BEARER):].encode('utf-8'), expected.encode('utf-8'))

# endregion


# region the sealed login

def load_private_key(pem: str):
    """The key a sealed login is opened with. Raises ValueError for anything unusable."""

    try:
        key = serialization.load_pem_private_key(pem.encode('utf-8'), password=None)
    except Exception as e:
        raise ValueError(f'{ENV_PRIVATE_KEY} is not a PEM private key: {e}') from e
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError(f'{ENV_PRIVATE_KEY} has to be an RSA key')
    if key.key_size < 2048:
        raise ValueError(f'{ENV_PRIVATE_KEY} is only {key.key_size} bits; use 2048 or more')
    return key


_KEYS: dict[str, object] = {}


def private_key():
    """The configured private key, loaded once, or None when logins arrive unsealed."""

    pem = configured_private_key()
    if not pem: return None
    if pem not in _KEYS: _KEYS[pem] = load_private_key(pem)
    return _KEYS[pem]


def login_from(body: dict) -> tuple[str, str]:
    """The ao3 username and password a start request carries.

    With a private key configured, **only a sealed login is accepted**. A page built without
    the public key would otherwise send the password in the clear to a helper that was set
    up precisely so it would not be, and nothing would say so.
    """

    key = private_key()
    if key is None:
        return (body.get('username') or '').strip(), body.get('password') or ''

    sealed = body.get('credentials')
    if not isinstance(sealed, str) or not sealed:
        raise AccessError('this helper only accepts an encrypted login, and the page sent '
                          'a plain one - the page was built without the public key')
    username, password = open_login(sealed, key)
    return username.strip(), password


def public_key_pem(key) -> str:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode('ascii')


class Seen:
    """The nonces of logins already opened, kept only as long as a login could be valid."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.nonces: dict[str, float] = {}

    def first_time(self, nonce: str, now: float) -> bool:
        with self.lock:
            # anything older than the oldest acceptable login can never be offered again
            for old in [n for n, at in self.nonces.items() if now - at > 2 * LOGIN_MAX_AGE_SECONDS]:
                del self.nonces[old]
            if nonce in self.nonces: return False
            self.nonces[nonce] = now
            return True


SEEN = Seen()


def open_login(sealed: str, key, now: float | None = None,
               seen: Seen = SEEN) -> tuple[str, str]:
    """The username and password out of a login the page sealed.

    The page encrypts `{"username", "password", "sent", "nonce"}` - `sent` in milliseconds
    since the epoch - with RSA-OAEP over SHA-256, and sends it base64 encoded. Everything
    that can be wrong with one is an AccessError, with a reason that names no part of it.
    """

    now = time.time() if now is None else now
    try:
        blob = base64.b64decode(sealed, validate=True)
    except (binascii.Error, ValueError, TypeError) as e:
        raise AccessError('the login could not be read') from e

    try:
        plain = key.decrypt(blob, padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
        login = json.loads(plain.decode('utf-8'))
    except Exception as e:
        # the usual cause is a page built with a different public key from this helper's
        raise AccessError('the login could not be opened - the page and the helper may '
                          'have been set up with different keys') from e

    if not isinstance(login, dict): raise AccessError('the login could not be read')
    username = login.get('username')
    password = login.get('password')
    sent = login.get('sent')
    nonce = login.get('nonce')
    if not isinstance(username, str) or not isinstance(password, str):
        raise AccessError('the login could not be read')
    if not isinstance(sent, (int, float)) or not isinstance(nonce, str) or not nonce:
        raise AccessError('the login could not be read')

    # a little allowance the other way too, for a page whose clock runs ahead
    age = now - sent / 1000
    if age > LOGIN_MAX_AGE_SECONDS or age < -LOGIN_MAX_AGE_SECONDS:
        raise AccessError('the login is too old to use - check this computer\'s clock and '
                          'start the run again')
    if not seen.first_time(nonce, now):
        raise AccessError('that login has already been used - start the run again')

    return username, password

# endregion
