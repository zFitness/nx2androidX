"""The Steam library: a ported game as a game Steam knows.

Two files, both written by hand (no dependency for either):

  * the desktop entry in the user's applications folder - the game shows up in the
    system's menu, and it is what a player adds to Steam by hand when they want to;
  * Steam's own shortcuts file - the game shows up in Steam's library, with the same
    name and the same icon.

Both point at one small script in the game's own folder: the script sets the
environment and starts the runtime, so the two entries behave the same way.

Steam keeps its shortcuts file in memory and writes it back when it quits, so nothing
is written while Steam is running: the player is asked to close it first.
"""
from __future__ import annotations

import os
import shlex
import struct
import subprocess
import sys
import zlib
from pathlib import Path

TYPE_MAP = 0x00
TYPE_STRING = 0x01
TYPE_INT32 = 0x02
TYPE_UINT64 = 0x07
TYPE_END = 0x08

STEAM_ROOTS = (
    '~/.steam/steam',
    '~/.steam/root',
    '~/.local/share/Steam',
    '~/.var/app/com.valvesoftware.Steam/data/Steam',
    '~/.steam/debian-installation',
)
APPLICATIONS_DIR = Path(os.environ.get('XDG_DATA_HOME') or (Path.home() / '.local' / 'share')) / 'applications'


class Uint64(int):
    """A number Steam wants as an unsigned 64-bit one (the last play time)."""


# ---- the binary key-values format ------------------------------------------------------

def _encode(value) -> bytes:
    if isinstance(value, dict):
        out = bytearray()
        for key, item in value.items():
            out += _encode_entry(key, item)
        out.append(TYPE_END)
        return bytes(out)
    raise TypeError(f'not a map: {value!r}')


def _as_int32(value: int) -> int:
    """A number as the signed 32-bit one the format holds."""
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _encode_entry(key: str, value) -> bytes:
    name = key.encode('utf-8') + b'\0'
    if isinstance(value, dict):
        return bytes([TYPE_MAP]) + name + _encode(value)
    if isinstance(value, Uint64):
        return bytes([TYPE_UINT64]) + name + struct.pack('<Q', int(value))
    if isinstance(value, bool):
        return bytes([TYPE_INT32]) + name + struct.pack('<i', int(value))
    if isinstance(value, int):
        return bytes([TYPE_INT32]) + name + struct.pack('<i', _as_int32(value))
    return bytes([TYPE_STRING]) + name + str(value).encode('utf-8') + b'\0'


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError('the file ends in the middle of an entry')
        value = self.data[self.pos]
        self.pos += 1
        return value

    def raw(self, count: int) -> bytes:
        if self.pos + count > len(self.data):
            raise ValueError('the file ends in the middle of a value')
        value = self.data[self.pos:self.pos + count]
        self.pos += count
        return value

    def text(self) -> str:
        end = self.data.find(b'\0', self.pos)
        if end < 0:
            raise ValueError('the file ends in the middle of a name')
        value = self.data[self.pos:end].decode('utf-8', 'replace')
        self.pos = end + 1
        return value


def _decode(reader: _Reader) -> dict:
    out: dict = {}
    while True:
        kind = reader.byte()
        if kind == TYPE_END:
            return out
        if kind not in (TYPE_MAP, TYPE_STRING, TYPE_INT32, TYPE_UINT64):
            raise ValueError(f'unknown entry type {kind}')
        key = reader.text()
        if kind == TYPE_MAP:
            out[key] = _decode(reader)
        elif kind == TYPE_STRING:
            out[key] = reader.text()
        elif kind == TYPE_INT32:
            out[key] = struct.unpack('<i', reader.raw(4))[0]
        else:
            out[key] = Uint64(struct.unpack('<Q', reader.raw(8))[0])


def decode(data: bytes) -> dict:
    """The maps in a binary key-values file."""
    if not data:
        return {}
    return _decode(_Reader(data))


def encode(value: dict) -> bytes:
    """The bytes of a binary key-values file."""
    return _encode(value)


# ---- Steam's own files -----------------------------------------------------------------

def steam_root() -> Path | None:
    """Where Steam lives on this machine, if it does."""
    for raw in STEAM_ROOTS:
        root = Path(raw).expanduser()
        if root.is_dir():
            return root
    return None


def userdata_dir(root: Path | None = None) -> Path | None:
    """The user's folder inside Steam, the one that holds the shortcuts file."""
    root = root or steam_root()
    if not root:
        return None
    userdata = root / 'userdata'
    try:
        folders = sorted(p for p in userdata.iterdir() if p.is_dir() and p.name.isdigit())
    except OSError:
        return None
    for folder in folders:
        if (folder / 'config').is_dir():
            return folder
    return folders[0] if folders else None


def shortcuts_file(root: Path | None = None) -> Path | None:
    """The shortcuts file, where the library entries live."""
    userdata = userdata_dir(root)
    return userdata / 'config' / 'shortcuts.vdf' if userdata else None


def read_shortcuts(path: Path) -> dict:
    """The shortcuts file's contents.  A file that cannot be read raises; the caller
    must not write over it, because it holds entries that are not ours."""
    return decode(path.read_bytes())


def write_shortcuts(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.vdf.tmp')
    tmp.write_bytes(encode(data))
    tmp.replace(path)


def list_shortcuts(path: Path | None = None) -> list[dict]:
    """Every entry in the shortcuts file, in the order they are in it."""
    path = path or shortcuts_file()
    if not path or not path.is_file():
        return []
    try:
        data = read_shortcuts(path)
    except (OSError, ValueError):
        return []
    shortcuts = data.get('shortcuts')
    if not isinstance(shortcuts, dict):
        return []
    return [entry for _, entry in sorted(shortcuts.items()) if isinstance(entry, dict)]


def app_id_for(name: str, exe: str) -> int:
    """The number Steam knows a non-Steam game by.  The same game always gets the same
    number, so adding it twice does not make two entries.  It stays inside the signed
    32-bit range the format holds."""
    return (zlib.crc32(f'{name}\0{exe}'.encode('utf-8')) & 0x7FFFFFFF) or 1


def shortcut_entry(name: str, exe: str, start_dir: str, icon: str = '', launch_options: str = '',
                   tags: tuple[str, ...] = ()) -> dict:
    """One entry, the way Steam writes it."""
    return {
        'appid': app_id_for(name, exe),
        'AppName': name,
        'Exe': exe,
        'StartDir': start_dir,
        'icon': icon,
        'ShortcutPath': '',
        'LaunchOptions': launch_options,
        'IsHidden': 0,
        'AllowDesktopConfig': 1,
        'AllowOverlay': 1,
        'OpenVR': 0,
        'Devkit': 0,
        'DevkitGameID': '',
        'DevkitOverrideAppID': 0,
        'LastPlayTime': Uint64(0),
        'tags': {str(i): tag for i, tag in enumerate(tags)},
    }


def find_shortcut(name: str, path: Path | None = None) -> dict | None:
    """The entry with this name, if the library has one."""
    for entry in list_shortcuts(path):
        if entry.get('AppName') == name:
            return entry
    return None


def add_shortcut(entry: dict, path: Path | None = None) -> int:
    """Add an entry to the library, replacing an older one with the same name."""
    path = path or shortcuts_file()
    if not path:
        raise FileNotFoundError('Steam is not installed on this machine')
    data = read_shortcuts(path) if path.is_file() else {}
    shortcuts = data.get('shortcuts')
    if not isinstance(shortcuts, dict):
        shortcuts = {}
    name = entry.get('AppName')
    for key, old in list(shortcuts.items()):
        if isinstance(old, dict) and old.get('AppName') == name:
            del shortcuts[key]
    # the next free index: len() would reuse an index that a deletion left occupied,
    # and the entry written there would silently replace another game's shortcut
    next_key = max([int(k) for k in shortcuts if str(k).isdigit()] + [-1]) + 1
    shortcuts[str(next_key)] = entry
    data['shortcuts'] = shortcuts
    write_shortcuts(path, data)
    return int(entry.get('appid') or 0)


def remove_shortcut(name: str, path: Path | None = None) -> bool:
    """Take an entry out of the library.  True when there was one."""
    path = path or shortcuts_file()
    if not path or not path.is_file():
        return False
    data = read_shortcuts(path)
    shortcuts = data.get('shortcuts')
    if not isinstance(shortcuts, dict):
        return False
    removed = False
    for key, old in list(shortcuts.items()):
        if isinstance(old, dict) and old.get('AppName') == name:
            del shortcuts[key]
            removed = True
    if removed:
        write_shortcuts(path, data)
    return removed


# ---- the desktop entry -----------------------------------------------------------------

def desktop_entry_path(title_id: str) -> Path:
    return APPLICATIONS_DIR / f'nx2a-{title_id}.desktop'


def write_desktop_entry(title_id: str, name: str, script: Path, icon: Path | None = None) -> Path:
    """The desktop entry: the game shows up in the system's menu."""
    path = desktop_entry_path(title_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        '[Desktop Entry]',
        'Type=Application',
        f'Name={name}',
        f'Exec={shlex.quote(str(script))}',   # a library path with spaces stays one argument
        'Terminal=false',
        'Categories=Game;',
    ]
    if icon and Path(icon).is_file():
        lines.append(f'Icon={icon}')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def remove_desktop_entry(title_id: str) -> bool:
    path = desktop_entry_path(title_id)
    try:
        path.unlink()
    except OSError:
        return False
    return True


# ---- Steam's state ---------------------------------------------------------------------

def steam_running() -> bool:
    """Whether Steam is running right now."""
    if sys.platform.startswith('linux'):
        try:
            pids = [p for p in os.listdir('/proc') if p.isdigit()]
        except OSError:
            pids = []
        for pid in pids:
            try:
                name = Path(f'/proc/{pid}/comm').read_text(encoding='utf-8', errors='replace').strip()
            except OSError:
                continue
            if name in ('steam', 'steamwebhelper'):
                return True
        return False
    try:
        done = subprocess.run(['pgrep', '-x', 'steam'], capture_output=True)
    except OSError:
        return False
    return done.returncode == 0
