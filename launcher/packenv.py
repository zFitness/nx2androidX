"""A pack's run options: the game's language, as the env.txt row the host reads at its
start (DM_LANG). The choices come from the pack's own list (languages.txt, written by the
porter from the game's NACP); writing replaces that one row in place — everything else in
env.txt (the profile's rows, the comments) stays. The file is replaced atomically
(env.txt.new + rename), so a crash mid-write never leaves half a file.

'DM_LANG=system' is the porter's own default: the pack lists the game's languages
(DM_LANG_SUPPORTED) and the front picks one at launch (the device's locale).
"""
from __future__ import annotations

from pathlib import Path

SYSTEM = 'system'   # DM_LANG's value for "the front picks at launch"


def languages(pack: Path) -> list[tuple[str, str]]:
    """The pack's languages (languages.txt rows of `code<TAB>name`), code first."""
    try:
        lines = (pack / 'languages.txt').read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        if not line.strip() or line.startswith('#'):
            continue
        code, _, name = line.partition('\t')
        code = code.strip()
        if code:
            out.append((code, name.strip() or code))
    return out


def current_language(pack: Path) -> str | None:
    """The DM_LANG row's value (None when the row is absent)."""
    try:
        lines = (pack / 'env.txt').read_text(encoding='utf-8').splitlines()
    except OSError:
        return None
    for line in lines:
        key, sep, value = line.partition('=')
        if sep and key.strip() == 'DM_LANG':
            return value.strip()
    return None


def set_language(pack: Path, code: str | None) -> None:
    """Set the DM_LANG row (None removes it: the front falls back to the device's locale).
    The file's other lines keep their places; the replace is atomic."""
    env = pack / 'env.txt'
    try:
        lines = env.read_text(encoding='utf-8').splitlines()
    except OSError:
        lines = []
    rest = [line for line in lines
            if line.partition('=')[0].strip() != 'DM_LANG' or '=' not in line]
    if code:
        rest.append(f'DM_LANG={code}')
    tmp = pack / 'env.txt.new'
    tmp.write_text('\n'.join(rest) + '\n', encoding='utf-8', newline='\n')
    tmp.replace(env)
