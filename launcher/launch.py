"""How a game is started.

Every game has its own executable, in its own folder in the data directory (the Linux
runtime builds one per game, because the game's profile is compiled into it).  The
runtime takes its data root from the environment and reads the pack's own `env.txt` and
`settings.txt` from there, so a game is started by running that executable with the
pack's folder as its working directory.

The script in the pack's folder does that, and the desktop entry and the Steam entry
both point at it: they behave the same way, and they keep working when the folder is
moved.

The runtime does the rest of what the Android app does before it loads the host: it
applies the pack's ``env.txt`` (``DM_ROMFS``, the shared fonts, the rest; a variable
already set in the environment wins), checks that the RomFS holds files, and defaults
``DM_SAVE`` / ``DM_TEMP`` to ``save/`` and ``temp/`` in the pack's folder.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from launcher.library import Game, WRAPPER

MODS = 'mods'   # where the porter's data pack keeps the rewritten modules (porter/datapack.py); the host loads them from its argv[1]


class NoExecutable(Exception):
    """The game has no executable of its own yet."""


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
    """Start the game."""
    exe = game.exe_path
    if not exe:
        raise NoExecutable(f'{game.name}: no executable in {game.path}')
    return subprocess.Popen(
        [str(exe), str(modules_path(game))],   # the host's argv[1] is the folder with the rewritten modules; DM_ROOT (in the environment) is the pack
        cwd=str(game.path), env=environment(game),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
