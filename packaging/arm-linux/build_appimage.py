#!/usr/bin/env python3
"""The ARM64 Linux package: one file that runs on an ordinary ARM64 Linux.

    python packaging/arm-linux/build_appimage.py [--with-profiles] [--out DIR]

The AppDir is a trimmed repository root (usr/{launcher,porter,nxnative,phone_tools}),
so the pipeline behaves inside the package exactly as it does in a checkout.

The interface is GTK, so the package runs on the machine's own Python with PyGObject
(`python3-gi`): the package carries the code, not the toolkit.  That keeps it small and
it keeps GTK's own rendering — glibc, the X11/Wayland stack and the Vulkan driver all
stay with the system, as they must (a bundled glibc would not match the system's
driver anyway).

The fonts are the one exception: a machine may have no fonts at all (a bare proot, for
instance), and then the interface shows random glyphs instead of Chinese.  The package
brings one Chinese font and one monospace face, and AppRun points fontconfig at them.

The game profiles (600 MB of shader tables) are in the package only with --with-profiles;
without it the player imports the release's profile package instead, the way the phone
app does.
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def _load(name: str, path: Path):
    """A module of this folder, loaded by path.

    It is not imported by name: the phone's tools have a `fetch` module too, and one
    `sys.modules['fetch']` would be the wrong one.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = _load('nx2a_arm_linux_fetch', HERE / 'fetch.py')

# What the package does not carry: the upstream's iOS line, the phone's APK writer,
# and the build junk.
SKIP_TREE = (
    'dm/ios',
    'dm/android/apk',
)
# The fonts, in the directory fontconfig looks in by default.
FONT_DIR = 'usr/share/fonts'
NOTO_FONT = 'opentype/noto/NotoSansSC-Regular.otf'
MONO_FONT = 'truetype/dejavu/DejaVuSansMono.ttf'


def copy_tree(source: Path, target: Path, skip: tuple[str, ...] = ()) -> int:
    """A directory without the build junk and without the skipped parts."""
    count = 0
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part == '__pycache__' for part in relative.parts):
            continue
        if any(relative.as_posix() == skip or relative.as_posix().startswith(skip + '/') for skip in skip):
            continue
        target_path = target / relative
        if path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target_path)
        count += 1
    return count


def stage_fonts(appdir: Path, noto: Path, noto_license: Path, dejavu: Path) -> None:
    """The fonts the interface needs: a machine may have none at all, and then the
    Chinese text comes out as random glyphs."""
    fonts = appdir / FONT_DIR
    (fonts / 'opentype/noto').mkdir(parents=True, exist_ok=True)
    (fonts / 'truetype/dejavu').mkdir(parents=True, exist_ok=True)
    shutil.copy2(noto, fonts / NOTO_FONT)
    shutil.copy2(noto_license, fonts / 'NotoSansSC-LICENSE.txt')
    with zipfile.ZipFile(dejavu) as archive:
        for member, target in (('dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono.ttf', MONO_FONT),
                               ('dejavu-fonts-ttf-2.37/LICENSE', 'truetype/dejavu/LICENSE.txt')):
            with archive.open(member) as source:
                path = fonts / target
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, 'wb') as out:
                    shutil.copyfileobj(source, out)


def stage(appdir: Path, repo: Path, with_profiles: bool, fonts: dict[str, Path]) -> dict:
    """The AppDir: usr/ is a trimmed repository root."""
    usr = appdir / 'usr'
    usr.mkdir(parents=True, exist_ok=True)

    stage_fonts(appdir, fonts['noto'], fonts['noto_license'], fonts['dejavu'])

    files = 0
    files += copy_tree(repo / 'launcher', usr / 'launcher')
    files += copy_tree(repo / 'porter', usr / 'porter')
    files += copy_tree(repo / 'phone_tools', usr / 'phone_tools')
    skip = SKIP_TREE if with_profiles else SKIP_TREE + ('dm/games',)
    files += copy_tree(repo / 'nxnative', usr / 'nxnative', skip)

    shutil.copy2(HERE / 'AppRun', appdir / 'AppRun')
    (appdir / 'AppRun').chmod(0o755)
    shutil.copy2(HERE / 'nx2androidX.desktop', appdir / 'nx2androidX.desktop')
    icon = repo / 'gui/icon.png'
    if icon.is_file():
        shutil.copy2(icon, appdir / 'nx2androidX.png')
        link = appdir / '.DirIcon'
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to('nx2androidX.png')
    return {'files': files, 'profiles': with_profiles}


def pack(appdir: Path, out: Path, runtime: Path, work: Path) -> None:
    """The AppImage: the squashfs image with the runtime in front of it."""
    if not shutil.which('mksquashfs'):
        sys.exit('mksquashfs not found (macOS: brew install squashfs; Debian: apt install squashfs-tools)')
    squash = work / 'squashfs.img'
    squash.unlink(missing_ok=True)
    subprocess.run(['mksquashfs', str(appdir), str(squash), '-comp', 'gzip', '-root-owned',
                    '-noappend', '-no-xattrs', '-quiet'], check=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with open(out, 'wb') as target:
        target.write(runtime.read_bytes())
        target.write(squash.read_bytes())
    with open(out, 'r+b') as target:      # the type-2 magic, at offset 8
        target.seek(8)
        target.write(b'AI\x02')
    out.chmod(out.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def check(out: Path, runtime_size: int) -> None:
    """The package itself: an ELF with the type-2 magic and a squashfs right behind the
    runtime (the superblock's magic is 'hsqs')."""
    with open(out, 'rb') as handle:
        head = handle.read(64)
        if head[:4] != b'\x7fELF':
            sys.exit('the output is not an ELF')
        if head[8:11] != b'AI\x02':
            sys.exit('the type-2 magic is missing at offset 8')
        handle.seek(runtime_size)
        if handle.read(4) != b'hsqs':
            sys.exit('no squashfs image behind the runtime')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-profiles', action='store_true',
                        help='put the game profiles in the package (600 MB raw, ~100 MB packed)')
    parser.add_argument('--out', default=str(HERE / 'dist'))
    parser.add_argument('--keep', action='store_true', help='keep the staged AppDir')
    args = parser.parse_args(argv)

    work = HERE / '.cache'
    work.mkdir(parents=True, exist_ok=True)
    appdir = work / 'nx2androidX.AppDir'
    shutil.rmtree(appdir, ignore_errors=True)
    appdir.mkdir(parents=True)

    print('>> fetching the pinned pieces')
    runtime = fetch.runtime()
    fonts = {
        'noto': fetch.noto_font(),
        'noto_license': fetch.noto_license(),
        'dejavu': fetch.dejavu_archive(),
    }

    print('>> staging')
    stats = stage(appdir, ROOT, args.with_profiles, fonts)
    print(f'   {stats["files"]} files, profiles: {"in" if stats["profiles"] else "not in"} the package')

    name = 'nx2androidX-arm64-full.AppImage' if args.with_profiles else 'nx2androidX-arm64.AppImage'
    out = Path(args.out) / name
    print('>> packing')
    pack(appdir, out, runtime, work)
    check(out, runtime.stat().st_size)
    print(f'>> {out} ({out.stat().st_size / 2**20:.0f} MB)')
    if not args.keep:
        shutil.rmtree(appdir, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
