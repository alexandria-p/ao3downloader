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

A setting the template **no longer has** - one a later version stopped using - is not deleted
either (`deprecate_settings`): its line is commented out where it stands, with a note above it
saying it is deprecated, so the file stops setting something nothing reads while still showing
what it said. Nothing else about the file changes.
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


DEPRECATED_NOTE = ('# DEPRECATED: {key} is no longer used by this version of ao3downloader, and '
                   'has no effect. Commented out rather than deleted, so you can see what it said.')


def deprecate_settings(existing: str, template: str) -> tuple[str, list[str]]:
    """`existing` with every setting the template no longer has commented out and marked
    deprecated, and the names of those.

    Only an active setting line is touched, and only by putting `# ` in front of it and the
    note above it - its value, the comments around it and everything else stay as they were.
    A line already commented out is left alone, so doing this twice changes nothing.
    `LEFT_OUT` settings are never deprecated: they still exist, a page build only leaves them
    out of the files it writes.
    """

    known = keys_in(template) | {key.lower() for key in LEFT_OUT}
    lines = existing.split('\n')
    deprecated: list[str] = []
    out: list[str] = []
    for line in lines:
        match = KEY_LINE.match(line)
        if match and match.group(1).lower() not in known:
            key = match.group(1)
            deprecated.append(key)
            out.append(DEPRECATED_NOTE.format(key=key))
            out.append('# ' + line.lstrip())
            continue
        out.append(line)
    return '\n'.join(out), deprecated


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


def ensure_settings_file(path: str, template: str | None = None
                         ) -> tuple[bool, list[str], list[str]]:
    """Make sure the settings.ini at `path` exists and has every setting - and none that
    this version no longer reads, uncommented.

    Returns (created, the settings added to an existing one, the settings it commented out as
    deprecated). Writes nothing when there is nothing to write, so a settings.ini that is
    complete and current is never touched.
    """

    template = template_text() if template is None else template
    if not os.path.exists(path):
        folder = os.path.dirname(path)
        if folder: os.makedirs(folder, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(fresh_settings(template))
        return True, [], []

    # newline='' reads and writes the file's own line endings as they are - a settings.ini
    # edited in Notepad keeps its CRLFs rather than being rewritten with a different ending
    with open(path, encoding='utf-8', newline='') as f:
        existing = f.read()
    ending = '\r\n' if '\r\n' in existing else '\n'
    text = existing.replace('\r\n', '\n')
    text, deprecated = deprecate_settings(text, template)
    text, added = complete_settings(text, template)
    if added or deprecated:
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text.replace('\n', ending))
    return False, added, deprecated


# region editing from the page

# settings the page offers to edit. Not the password one (the page never stores a password),
# and not the three that say where the helper is and who may call it: changed by hand on a
# helper the page is talking to, they can stop it answering the page at all - RequirePasscode
# on with no passcode set refuses to start - so they stay a thing to edit in the file itself
NOT_EDITABLE = LEFT_OUT + (strings.INI_HELPER_URL, strings.INI_REQUIRE_PASSCODE,
                           strings.INI_PAGE_ORIGIN)
BOOLEAN = 'boolean'
INTEGER = 'integer'
TEXT = 'text'
VALUE_LINE = re.compile(r'^(\s*)([A-Za-z][A-Za-z0-9]*)(\s*=\s*)(.*?)(\s*)$')


def kind_of(default: str) -> str:
    """What sort of value a setting takes, judged by its default in the template."""

    if default.strip().lower() in ('true', 'false'): return BOOLEAN
    if re.fullmatch(r'\d+', default.strip()): return INTEGER
    return TEXT


def about(block: str) -> str:
    """A setting's explanation: its comment block, without the comment marks."""

    lines = [line.lstrip()[1:] for line in block.split('\n')[:-1]
             if line.lstrip().startswith(('#', ';'))]
    lines = [line[1:] if line.startswith(' ') else line for line in lines]
    # the file wraps its comments to fit an editor; the page wraps its own. So a paragraph's
    # lines are joined, while a blank line still ends one and an indented line (the naming
    # example) keeps a line to itself
    paragraphs: list[str] = []
    joining = False
    for line in lines:
        if not line.strip():
            if paragraphs and paragraphs[-1] != '': paragraphs.append('')
            joining = False
        elif line.startswith(' ') or not joining:
            paragraphs.append(line.rstrip())
            joining = not line.startswith(' ')
        else:
            paragraphs[-1] += ' ' + line.strip()
    return '\n'.join(paragraphs).strip()


def values_in(text: str) -> dict[str, str]:
    """Each active setting's value as written, by its name in lower case."""

    found: dict[str, str] = {}
    for line in text.replace('\r\n', '\n').split('\n'):
        match = VALUE_LINE.match(line)
        if match and not line.lstrip().startswith(('#', ';')):
            found.setdefault(match.group(2).lower(), match.group(4))
    return found


def editable_settings(text: str, template: str | None = None) -> list[dict]:
    """The settings the page may edit, in the template's order: the name, the value the file
    has (or the template's default where it has none), what kind of value it takes, the
    default, and the explanation from the template."""

    template = template_text() if template is None else template
    have = values_in(text)
    settings = []
    for key, block in blocks_of(template):
        if key in NOT_EDITABLE: continue
        default = VALUE_LINE.match(block.split('\n')[-1]).group(4)
        settings.append({
            'key': key,
            'value': have.get(key.lower(), default),
            'default': default,
            'kind': kind_of(default),
            'about': about(block),
        })
    return settings


def checked_value(setting: dict, value) -> str:
    """`value` as it would be written for `setting`, or ValueError when it is not one it
    takes: true or false, or a whole number of zero or more - the same kinds the deploy
    checks a variable against, so the page cannot write what the helper would misread."""

    if setting['kind'] == BOOLEAN:
        if isinstance(value, bool): return 'true' if value else 'false'
        text = str(value).strip().lower()
        if text in ('true', 'false'): return text
        raise ValueError(f'{setting["key"]} takes true or false')
    if setting['kind'] == INTEGER:
        text = str(value).strip()
        if isinstance(value, bool) or not re.fullmatch(r'\d+', text):
            raise ValueError(f'{setting["key"]} takes a whole number of 0 or more')
        return str(int(text))
    text = str(value)
    if '\n' in text or '\r' in text: raise ValueError(f'{setting["key"]} takes one line')
    return text.strip()


def set_values(text: str, values: dict[str, str]) -> str:
    """`text` with each named setting's value replaced where it stands.

    Only the value after the `=` changes - the comments, the order, the spacing and every
    other line stay exactly as they were, which is what lets a settings.ini edited from the
    page still read as the file its owner wrote. A setting the file does not have yet is
    appended with its explanation, as `complete_settings` would have.
    """

    wanted = {key.lower(): value for key, value in values.items()}
    done: set[str] = set()
    lines = text.split('\n')
    for at, line in enumerate(lines):
        if line.lstrip().startswith(('#', ';')): continue
        match = VALUE_LINE.match(line)
        if not match: continue
        key = match.group(2).lower()
        if key in wanted and key not in done:
            lines[at] = match.group(1) + match.group(2) + match.group(3) + wanted[key] + match.group(5)
            done.add(key)
    text = '\n'.join(lines)
    missing = {key: value for key, value in wanted.items() if key not in done}
    if missing:
        # once only: a name the template does not have is not added, so it cannot loop
        completed, added = complete_settings(text, template_text())
        if added:
            return set_values(completed, {key: value for key, value in missing.items()
                                          if key in {name.lower() for name in added}})
    return text


def update_settings_file(path: str, values: dict) -> list[dict]:
    """Write the page's edits into the settings.ini at `path`, and return the settings as
    they now stand. Raises ValueError, naming the setting, for a name the page may not edit
    or a value it does not take - and then writes nothing at all."""

    with open(path, encoding='utf-8', newline='') as f:
        existing = f.read()
    settings = {setting['key'].lower(): setting for setting in editable_settings(existing)}
    written: dict[str, str] = {}
    for key, value in values.items():
        setting = settings.get(str(key).lower())
        if setting is None: raise ValueError(f'{key} cannot be changed from the page')
        written[setting['key']] = checked_value(setting, value)

    ending = '\r\n' if '\r\n' in existing else '\n'
    text = set_values(existing.replace('\r\n', '\n'), written)
    if text != existing.replace('\r\n', '\n'):
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(text.replace('\n', ending))
    return editable_settings(text)

# endregion

