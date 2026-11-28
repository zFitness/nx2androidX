#!/usr/bin/env python3
"""The fixed pieces the ARM64 Linux package is made of.

Every download is pinned to a version and a SHA-256, and kept in .cache/ for the next
run:

  * the AppImage runtime (the ELF stub the squashfs is appended to);
  * the fonts (a Chinese one and a monospace one): a machine may have no fonts at all,
    and then the interface is unreadable.

The Python and the PySide6 (Qt) wheels are the system's own or bundled per the
--with-toolchain flag (the launcher's interface is PySide6), so nothing of them is
downloaded here.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parent / '.cache'

RUNTIME = (
    'https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-aarch64',
    '00cbdfcf917cc6c0ff6d3347d59e0ca1f7f45a6df1a428a0d6d8a78664d87444',
)
# The fonts: Noto Sans SC (Latin and Simplified Chinese, SIL Open Font License) and
# DejaVu Sans Mono for the log pane (the DejaVu license, in the same archive).
NOTO = (
    'https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf',
    'faa6c9df652116dde789d351359f3d7e5d2285a2b2a1f04a2d7244df706d5ea9',
)
NOTO_LICENSE = (
    'https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/LICENSE',
    '6a73f9541c2de74158c0e7cf6b0a58ef774f5a780bf191f2d7ec9cc53efe2bf2',
)
DEJAVU = (
    'https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/'
    'dejavu-fonts-ttf-2.37.zip',
    '7576310b219e04159d35ff61dd4a4ec4cdba4f35c00e002a136f00e96a908b0a',
)


def fetch(url: str, sha: str, name: str | None = None) -> Path:
    """One pinned download, kept in the cache for the next run."""
    name = name or url.rsplit('/', 1)[1]
    path = CACHE / name
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
        return path
    print(f'downloading {url}', flush=True)
    with urllib.request.urlopen(url, timeout=300) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != sha:
        sys.exit(f'{url}: sha256 differs from the pinned one')
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def runtime() -> Path:
    return fetch(RUNTIME[0], RUNTIME[1])


def noto_font() -> Path:
    return fetch(NOTO[0], NOTO[1])


def noto_license() -> Path:
    return fetch(NOTO_LICENSE[0], NOTO_LICENSE[1], 'NotoSansSC-LICENSE.txt')


def dejavu_archive() -> Path:
    return fetch(DEJAVU[0], DEJAVU[1])


if __name__ == '__main__':
    for path in (runtime(), noto_font(), noto_license(), dejavu_archive()):
        print(path)
