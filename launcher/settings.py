"""Where the launcher keeps its own settings.

The settings are a small JSON file in the user's config directory; a broken or missing
file means the defaults, never an error: a launcher that cannot start is worse than one
that starts with the wrong library path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_DIR = Path(os.environ.get('XDG_CONFIG_HOME') or (Path.home() / '.config')) / 'nx2a'
SETTINGS_FILE = CONFIG_DIR / 'launcher.json'
DATA_DIR = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share')) / 'nx2a'
DEFAULT_LIBRARY = DATA_DIR / 'library'
DEFAULT_WORK = DATA_DIR / 'work'        # porter's unpacked resources; the games' RomFS lives here (referenced, not copied)
STATE_DIR = Path(os.environ.get('XDG_STATE_HOME') or (Path.home() / '.local' / 'state')) / 'nx2a'   # logs

LANGUAGES = ('zh', 'en')

DEFAULTS = {
    'library': str(DEFAULT_LIBRARY),   # where the ported games live, one folder each
    'work': str(DEFAULT_WORK),         # porter's unpacked resources; a pack's env.txt points here (DM_ROMFS)
    'language': 'zh',
    'ui_scale': 1.0,        # the player's own multiplier on top of the automatic one
    'porter_dir': '',       # where the porter package is; empty = the checkout next to this launcher
}


def load() -> dict:
    """The settings, with the defaults filled in for whatever is missing or broken."""
    settings = dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return settings
    if isinstance(data, dict):
        for key, value in data.items():
            if key in DEFAULTS:
                settings[key] = value
    settings['language'] = settings['language'] if settings['language'] in LANGUAGES else DEFAULTS['language']
    try:
        settings['ui_scale'] = float(settings['ui_scale'])
    except (TypeError, ValueError):
        settings['ui_scale'] = DEFAULTS['ui_scale']
    if not settings['ui_scale'] > 0:
        settings['ui_scale'] = DEFAULTS['ui_scale']
    return settings


def save(settings: dict) -> None:
    """Write the settings; the file is replaced atomically, so a crash cannot leave half of it."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    keep = {k: settings[k] for k in DEFAULTS if k in settings}
    tmp = SETTINGS_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(SETTINGS_FILE)


def library_dir(settings: dict) -> Path:
    """The data directory, with the default when the setting is empty."""
    raw = str(settings.get('library') or '').strip()
    return Path(raw).expanduser() if raw else DEFAULT_LIBRARY


def library_set(settings: dict) -> bool:
    """Whether the player has named the data directory themselves."""
    return bool(str(settings.get('library') or '').strip())
