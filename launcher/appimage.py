"""Running inside an AppImage.

The package is mounted read-only, and the pipeline writes beside its sources (the host
build, the .NET tools), so the engine tree is copied to the player's own folder once and
the pipeline is pointed at that copy.  The game profiles are not copied: they are read
only, so the copy links to them where the package has them.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

ENV_ENGINE = 'NX2A_NXNATIVE'      # the engine tree the pipeline may write in
PROFILES = 'dm/games'              # the profiles, inside the engine tree


def inside_appimage() -> bool:
    """Whether this launcher runs from an AppImage (a read-only mount)."""
    return bool(os.environ.get('APPIMAGE'))


def _source(repo: Path) -> Path:
    return repo / 'nxnative'


def prepare(repo: Path, user_dir: Path) -> str | None:
    """Make the engine tree writable and point the pipeline at it.

    Returns the copy's path, or None when there is nothing to do (a normal checkout).
    """
    if not inside_appimage():
        return None
    source = _source(repo)
    if not source.is_dir():
        return None
    target = user_dir / 'engine' / 'nxnative'
    key = target.parent / 'KEY'
    stamp = f'{source.stat().st_size}\n{source.stat().st_mtime_ns}\n'
    if not (key.is_file() and key.read_text(encoding='utf-8') == stamp):
        partial = target.parent.with_name(f'engine.{os.getpid()}.partial')
        shutil.rmtree(partial, ignore_errors=True)
        partial.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, partial / 'nxnative', symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
        # The profiles are read only: the copy links to the ones in the package.
        profiles = partial / 'nxnative' / PROFILES
        if profiles.is_dir():
            shutil.rmtree(profiles)
            (partial / 'nxnative' / PROFILES).symlink_to(source / PROFILES)
        shutil.rmtree(target.parent, ignore_errors=True)
        partial.rename(target.parent)
        key.write_text(stamp, encoding='utf-8')
    else:
        # The package is mounted at a new path every run: the link has to follow it.
        profiles = target / PROFILES
        if profiles.is_symlink():
            profiles.unlink()
            profiles.symlink_to(source / PROFILES)
    os.environ[ENV_ENGINE] = str(target)
    return str(target)
