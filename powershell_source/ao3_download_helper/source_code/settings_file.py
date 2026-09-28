"""Keeping a settings.ini in step with the settings the helper knows about.

A settings.ini is written once - by the bundler, by the helper the first time it starts, or by
the deploy workflow - and then belongs to whoever edits it. So when a new setting is added to
the template, an existing file does not have it, and the helper quietly uses a default that
nobody can see or change without knowing the name.

`complete_settings` fixes that without touching anything already there: every setting the
template has and the file does not is **appended**, with the comment block that explains it
and its default value. The user's own values, comments and order are left exactly as they
were - nothing is rewritten, only added to the end. The helper does it every time it starts
(`server.serve`) and the bundler does it to `build/config/settings.ini`, so a build, a restart
after an update, and a first start all end up with every setting written down.
"""

import importlib.resources
import os
import re

from source_code import strings

# settings the web page never uses, left out of every settings.ini written for it - the page
# never stores a password, so offering the setting would only invite confusion
LEFT_OUT = (strings.INI_PASSWORD_SAVE,)

KEY_LINE = re.compile(r'^\s*([A-Za-z][A-Za-z0-9]*)\s*=', re.MULTILINE)
SECTION = f'[{strings.INI_SECTION_NAME}]'


def template_text() -> str:
    """The settings.ini the package ships, with every setting and its explanation."""

    return importlib.resources.files(strings.SETTINGS_FOLDER_NAME).joinpath(
        strings.INI_FILE_NAME).read_text(encoding='utf-8')


def keys_in(text: str) -> set[str]:
    """The setting names a settings.ini holds - compared without case, as configparser does."""

    return {match.group(1).lower() for match in KEY_LINE.finditer(text)}


def blocks_of(template: str) -> list[tuple[str, str]]:
    """Each setting in the template with its block: the comments right above it, and itself."""

    lines = template.split('\n')
    blocks = []
    for at, line in enumerate(lines):
        match = KEY_LINE.match(line)
        if not match: continue
        start = at
        while start > 0 and lines[start - 1].lstrip().startswith(('#', ';')): start -= 1
        blocks.append((match.group(1), '\n'.join(lines[start:at + 1])))
    return blocks


def strip_setting(content: str, key: str) -> str:
    """Remove one ini setting along with the comment block that documents it."""

    kept: list[str] = []
    for line in content.splitlines(keepends=True):
        if line.strip().lower().startswith(key.lower() + '='):
            # take the explanation with it, and the blank line that separated the pair
            # from whatever came before
            while kept and kept[-1].lstrip().startswith('#'):
                kept.pop()
            while kept and not kept[-1].strip():
                kept.pop()
            continue
        kept.append(line)
    return ''.join(kept)


def fresh_settings(template: str) -> str:
    """A new settings.ini: the template, less what the web page has no use for."""

    for key in LEFT_OUT: template = strip_setting(template, key)
    return template


def complete_settings(existing: str, template: str) -> tuple[str, list[str]]:
    """`existing` with every setting it lacks appended, and the names of those added.

    Only ever adds. A setting already there - whatever its value, however it is written - is
    left alone, as are the comments and the order around it. A file with no section header
    at all gets one, or configparser could not read it.
    """

    have = keys_in(existing)
    missing = [(key, block) for key, block in blocks_of(template)
               if key.lower() not in have and key not in LEFT_OUT]
    if not missing: return existing, []

    text = existing.rstrip('\n')
    if SECTION.lower() not in text.lower():
        text = SECTION + ('\n' + text if text.strip() else '')
    for _, block in missing:
        text += '\n\n' + block
    return text + '\n', [key for key, _ in missing]


def ensure_settings_file(path: str, template: str | None = None) -> tuple[bool, list[str]]:
    """Make sure the settings.ini at `path` exists and has every setting.

    Returns (created, the settings added to an existing one). Writes nothing when there is
    nothing to write, so a settings.ini that is complete is never touched.
    """

    template = template_text() if template is None else template
    if not os.path.exists(path):
        folder = os.path.dirname(path)
        if folder: os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(fresh_settings(template))
        return True, []

    with open(path, encoding='utf-8') as f:
        existing = f.read()
    completed, added = complete_settings(existing, template)
    if added:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(completed)
    return False, added
