"""The machine's firmware: one zip the player imports (the emulator kind — a zip whose
root holds the console's .nca system content), unpacked flat into the data folder. It is
optional: only games that read the console's system data (Mii and friends) want it.

The import is persisted twice, on purpose: the zip's name in the launcher's settings (the
settings page shows it), and the unpacked folder in the porter's own config's 'firmware'
key (the porter picks it up from there, the same way it picks up prod.keys — so the CLI
and the desktop tool see the same firmware).
"""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from launcher import settings
from porter import config as porter_config


def folder() -> Path:
    """Where the firmware lives: the data folder's firmware/."""
    return settings.DATA_DIR / 'firmware'


def imported_name() -> str:
    """The imported zip's name ('' when nothing is imported)."""
    return str(settings.load().get('firmware_name') or '')


def nca_folder() -> Path | None:
    """The folder the porter reads: it exists and really holds .nca files (nx_extract
    scans one level, so the zip is unpacked flat)."""
    target = folder()
    try:
        if target.is_dir() and any(f.suffix == '.nca' for f in target.iterdir() if f.is_file()):
            return target
    except OSError:
        pass
    return None


def unpack_zip(zip_path: Path, target: Path) -> int:
    """Unpack the zip flat into target: every entry keeps only its last name segment
    (the porter scans one level), entries with '..' or a leading '/' are dropped (they
    can go nowhere). Returns the number of files written."""
    n = 0
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            raw = info.filename
            if raw.startswith('/') or '..' in raw.split('/'):
                continue
            name = raw.rsplit('/', 1)[-1]
            if name in ('', '.', '..'):
                continue
            with archive.open(info) as source, open(target / name, 'wb') as out:
                shutil.copyfileobj(source, out)
            n += 1
    return n


def import_zip(zip_path: Path) -> int:
    """Replace the imported firmware with this zip's contents; returns the file count.
    A zip without a single .nca is refused (and whatever it unpacked is removed)."""
    target = folder()
    shutil.rmtree(target, ignore_errors=True)
    count = unpack_zip(zip_path, target)
    if nca_folder() is None:
        shutil.rmtree(target, ignore_errors=True)
        raise ValueError(f'no .nca files in {zip_path.name}')
    current = settings.load()
    current['firmware_name'] = zip_path.name
    settings.save(current)
    porter_config.set_value('firmware', str(target))
    return count


def clear() -> None:
    """Forget the firmware: the unpacked folder goes, the settings row and the porter's
    key are cleared."""
    shutil.rmtree(folder(), ignore_errors=True)
    current = settings.load()
    current.pop('firmware_name', None)
    settings.save(current)
    porter_config.set_value('firmware', '')
