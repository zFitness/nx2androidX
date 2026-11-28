"""How a game is started.

Every game has its own executable, in its own folder in the data directory (the game's
profile is compiled into it).  The runtime takes its data root from the environment and
reads the pack's own `env.txt` and `settings.txt` from there, so a game is started by
running that executable with the pack's folder as its working directory.

The script in the pack's folder does that, and the desktop entry and the Steam entry
both point at it: they behave the same way, and they keep working when the folder is
moved.

The host applies the pack's ``env.txt`` itself (``DM_ROMFS``, the shared fonts, the
rest — read from ``DM_ROOT``), so the launcher's job is the working directory, the
environment, the mods folder as argv[1], and a log file — one per run, under the data
directory: a launch that fails says so in there, nothing goes to /dev/null.

One game runs at a time (the first version's rule): a second Run of a live pack is
refused with a clear message, and the launcher keeps the process handle so it can hide
itself while the game is up and come back when the game exits.  Games start in a session
of their own, so quitting the launcher never kills one.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

from launcher import settings
from launcher.library import Game, WRAPPER

MODS = 'mods'   # where the porter's data pack keeps the rewritten modules (porter/datapack.py); the host loads them from its argv[1]
LOGS = 'logs'   # under the data directory: one file per game run, kept (a failed launch says so in there)

_RUNNING: dict[str, tuple[subprocess.Popen, object]] = {}   # pack path → (process, log file); one game at a time


class NoExecutable(Exception):
    """The game has no executable of its own yet."""


class AlreadyRunning(Exception):
    """The same pack is already running (one game at a time)."""

    def __init__(self, game: Game):
        self.game = game
        super().__init__(f'{game.name} is already running')


def is_running(game: Game) -> bool:
    """The game's process from this launcher is still alive."""
    entry = _RUNNING.get(str(game.path))
    return bool(entry and entry[0].poll() is None)


def running_process(game: Game) -> subprocess.Popen | None:
    """The live process for this pack, or None."""
    entry = _RUNNING.get(str(game.path))
    return entry[0] if entry else None


def script_path(game: Game) -> Path:
    return game.path / WRAPPER


def modules_path(game: Game) -> Path:
    """The folder the host loads the rewritten modules from: its argv[1].  DM_ROOT stays the pack's folder."""
    return game.path / MODS


def executable_in_pack(game: Game, exe: Path) -> str:
    """The executable's path from the pack's root (the manifest's ``host/dmhost`` keeps its folder)."""
    try:
        return exe.relative_to(game.path).as_posix()
    except ValueError:
        raise NoExecutable(f'{game.name}: {exe} is not inside {game.path}') from None


def write_script(game: Game) -> Path:
    """The script that starts this game.  It knows the game's own executable by its path in the pack."""
    exe = game.exe_path
    if not exe:
        raise NoExecutable(f'{game.name}: no executable in {game.path}')
    if not os.access(exe, os.X_OK):
        try:
            exe.chmod(0o755)   # an earlier porter wrote the pack's executable without the bit; the script's check would turn it away
        except OSError:
            pass   # a pack the player cannot write: the script says so when it is run
    rel = executable_in_pack(game, exe)
    path = script_path(game)
    path.write_text(
        '#!/bin/sh\n'
        '# Written by the launcher: it starts this game with its data root.\n'
        'dir=$(cd "$(dirname "$0")" && pwd)\n'
        f'exe="$dir"/{shlex.quote(rel)}\n'
        '[ -x "$exe" ] || { echo "this game has no executable" >&2; exit 1; }\n'
        f'[ -d "$dir/{MODS}" ] || {{ echo "this game has no {MODS} folder" >&2; exit 1; }}\n'
        'cd "$dir" || exit 1\n'
        f'DM_ROOT="$dir" exec "$exe" "$dir/{MODS}"\n',   # the host's argv[1] is the folder with the rewritten modules
        encoding='utf-8',
    )
    path.chmod(0o755)
    return path


def environment(game: Game) -> dict:
    """The environment the runtime is started with."""
    env = dict(os.environ)
    env['DM_ROOT'] = str(game.path)
    return env


def start(game: Game) -> subprocess.Popen:
    """Start the game.  One per pack: a second run of a live game raises AlreadyRunning.
    stdout+stderr go to a log file under the data directory (one per run, kept — a launch
    that failed says so in there)."""
    if is_running(game):
        raise AlreadyRunning(game)
    exe = game.exe_path
    if not exe:
        raise NoExecutable(f'{game.name}: no executable in {game.path}')
    log_dir = settings.STATE_DIR / 'logs' / 'games'   # XDG state: logs are reproducible run records, not data
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    safe = ''.join(c if c.isalnum() or c in '-_.' else '_' for c in game.name) or game.title_id
    log = (log_dir / f'{game.title_id}-{safe}-{stamp}.log').open('wb')
    process = subprocess.Popen(
        [str(exe), str(modules_path(game))],   # the host's argv[1] is the folder with the rewritten modules; DM_ROOT (in the environment) is the pack
        cwd=str(game.path), env=environment(game),
        stdout=log, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    _RUNNING[str(game.path)] = (process, log)
    return process
