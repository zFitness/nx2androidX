"""The library: the folders under the data directory, each one a ported game.

A game is a data pack: the manifest that says what it is, the icon, the files, and the
executable the Linux runtime builds for it.  The pack is the truth; there is no index
beside it, so a game the player deleted by hand is simply gone from the library and a
pack that was copied in from elsewhere shows up on its own.

The pack is born here: the porter writes it straight into its final place (the porter
env var NX2A_PACK_DIR, an atomic rename), so what appears in the data directory is
always a whole pack, never a half-built one.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

MANIFEST = 'nx2a-data.json'
ICON = 'icon.png'
WRAPPER = 'run.sh'         # the script the launcher writes; not the game itself


@dataclass(frozen=True)
class Game:
    """One ported game in the library."""
    title_id: str
    name: str
    version: str
    path: Path
    package: str = ''
    exe_name: str = ''      # the manifest's own name for the executable, when it says

    @property
    def icon_path(self) -> Path:
        return self.path / ICON

    @property
    def label(self) -> str:
        """The name with the version, when there is one."""
        return f'{self.name}  {self.version}' if self.version else self.name

    @property
    def exe_path(self) -> Path | None:
        """This game's own executable, when it has one.

        The manifest names it when it knows; otherwise it is the one executable file in
        the game's own folder (the script the launcher writes is not one)."""
        if self.exe_name:
            named = self.path / self.exe_name
            return named if named.is_file() else None
        try:
            entries = sorted(self.path.iterdir())
        except OSError:
            return None
        for entry in entries:
            if entry.name == WRAPPER or entry.name.startswith('.'):
                continue
            if entry.is_file() and os.access(entry, os.X_OK):
                return entry
        return None


def read_manifest(pack: Path) -> dict | None:
    """The manifest of a data pack, or None when it is missing or unreadable."""
    try:
        data = json.loads((pack / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def game_of(pack: Path) -> Game | None:
    """The game a data pack holds, or None when the pack is not one."""
    manifest = read_manifest(pack)
    if not manifest:
        return None
    title_id = str(manifest.get('title_id') or '').strip().upper()
    if not title_id:
        return None
    return Game(
        title_id=title_id,
        name=str(manifest.get('name') or title_id),
        version=str(manifest.get('version') or ''),
        path=pack,
        package=str(manifest.get('package') or ''),
        exe_name=str(manifest.get('exe') or ''),
    )


def scan(library: Path) -> list[Game]:
    """Every game in the library, ordered by name and then by version."""
    games = []
    try:
        entries = sorted(library.iterdir())
    except OSError:
        return games
    for entry in entries:
        if not entry.is_dir() or entry.name.startswith('.'):
            continue
        game = game_of(entry)
        if game:
            games.append(game)
    games.sort(key=lambda g: (g.name.lower(), g.version))
    return games
