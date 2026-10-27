"""Check the README's `<!--CHECK-->value<!--CONSTANT_NAME-->` markers against strings.py.

A marker ties a string the README quotes - a folder name, a setting, a prompt - to the constant
in `source_code/strings.py` that the code really uses, so the README cannot go on naming
something the code has renamed or dropped. A marker is wrong when its constant no longer exists,
or when its value is not part of the constant's (braces aside - a constant can be a format
string, and the README quotes the words around the `{}`).

Run from the helper's folder, as the `validate readme` workflow does:

    uv run --no-sync python dev/readme.py [path/to/README.md]

Prints every wrong marker and exits 1, or exits 0 when they all hold. The README defaults to
the one at the repository root, two folders up.
"""

import re
import sys
from pathlib import Path

from source_code import strings

# the repository root, from powershell_source/ao3_download_helper/dev/
DEFAULT_README = Path(__file__).resolve().parents[3] / 'README.md'

MARKER = re.compile(r'<!--CHECK-->(.*?)<!--([A-Za-z0-9_]+)-->', re.DOTALL)


def problems(text: str, constants=strings) -> list[str]:
    """Every marker in `text` that does not match its constant, said in a line each."""

    found = []
    for match in MARKER.finditer(text):
        value, name = match.group(1), match.group(2)
        line = text.count('\n', 0, match.start()) + 1
        if not hasattr(constants, name):
            found.append(f'line {line}: no constant {name} in strings.py (README says {value!r})')
            continue
        real = str(getattr(constants, name)).replace('{', '').replace('}', '')
        if value not in real:
            found.append(f'line {line}: {name} is {real!r}, but the README says {value!r}')
    return found


def main(argv: list[str]) -> int:
    readme = Path(argv[0]) if argv else DEFAULT_README
    text = readme.read_text(encoding='utf-8')
    found = problems(text)
    for problem in found:
        print(problem)
    print(f'{len(MARKER.findall(text))} markers checked, {len(found)} wrong')
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
