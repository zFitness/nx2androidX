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
import hashlib
import importlib.util
import json
import lzma
import os
import urllib.request
import shutil
import stat
import subprocess
import sys
import tarfile
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
# The phone's Debian deb fetcher, reused for the Ubuntu packages (its helpers only run
# when main() is called, so importing it by another name is safe).
fetch_debs = _load('nx2a_android_fetch_debs', ROOT / 'packaging/android-apk/fetch_debs.py')

# What the package does not carry: the upstream's iOS line, the phone's APK writer,
# and the build junk.
SKIP_TREE = (
    'dm/ios',
    'dm/android/apk',
    'dm/android/out',
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
        if path.is_symlink():
            link = os.readlink(path)
            if link.startswith('/'):
                continue   # an absolute link names the host machine's files (Debian's sitecustomize.py -> /etc/...): meaningless in the pack
            if target_path.is_symlink() or target_path.exists():
                target_path.unlink()
            target_path.symlink_to(link)   # keep relative links as links (libvulkan.so -> .so.1 -> real): the linker resolves them inside the prefix
            count += 1
            continue
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


PYSIDE_VERSION = '6.12.0'
PYSIDE_WHEELS = (
    ('PySide6', f'pyside6-{PYSIDE_VERSION}-cp310-abi3-manylinux_2_39_aarch64.whl'),
    ('shiboken6', f'shiboken6-{PYSIDE_VERSION}-cp310-abi3-manylinux_2_39_aarch64.whl'),
    ('PySide6-Essentials', f'pyside6_essentials-{PYSIDE_VERSION}-cp310-abi3-manylinux_2_39_aarch64.whl'),
)


def fetch_pyside_wheels(cache: Path) -> list[Path]:
    """The PySide6 wheels for the target machine (aarch64 Linux, the stable ABI -- runs
    on any python >= 3.10): the UI toolkit ships with the --with-toolchain package, so
    the machine needs no Qt and no pip. SHA-256 comes from the PyPI release index."""
    cache.mkdir(parents=True, exist_ok=True)
    wheels = []
    for project, name in PYSIDE_WHEELS:
        dest = cache / name
        if dest.is_file():
            wheels.append(dest)
            continue
        with urllib.request.urlopen(f'https://pypi.org/pypi/{project}/{PYSIDE_VERSION}/json') as r:
            release = json.load(r)
        record = next(f for f in release['urls'] if f['filename'] == name)
        digest = hashlib.sha256()
        part = dest.with_name(dest.name + '.part')
        with urllib.request.urlopen(record['url']) as r, open(part, 'wb') as out:
            while chunk := r.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != record['digests']['sha256']:
            part.unlink(missing_ok=True)
            raise SystemExit(f'sha256 mismatch: {name}')
        part.replace(dest)
        wheels.append(dest)
    return wheels


def stage_pyside(appdir: Path, wheels: list[Path]) -> int:
    """Unpack the wheels into usr/pylibs: PySide6/ (with the Qt libraries, which resolve
    their own loader paths), shiboken6/, beside the payload's lz4/capstone modules."""
    pylibs = appdir / 'usr' / 'pylibs'
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as z:
            z.extractall(pylibs)
    for want in (pylibs / 'PySide6/__init__.py', pylibs / 'PySide6/Qt/lib',
                 pylibs / 'shiboken6/__init__.py'):
        if not want.exists():
            raise SystemExit(f'the PySide6 bundle is incomplete: {want} is missing')
    return sum(1 for f in pylibs.rglob('*') if f.is_file())


def stage_toolchain(appdir: Path, src: Path, debs: Path) -> int:
    """The build toolchain, for a machine with no compiler (the DroidDeck tablet): the
    same linux-aarch64 clang and glslc the phone's payload ships, the .NET runtime with
    the prebuilt C# tools beside it (the phone ships no SDK either). The glibc prefix
    (headers, crt, the compiler's resource dir, gcc's link pieces -- crtbegin/crtend and
    libgcc -- and Vulkan's dev symlink) comes from one Debian suite's debs -- the same
    libc the target machine runs. Self-contained: the host link works with nothing
    installed on the machine (verified on the tablet: dmhost linked, a game ported end
    to end).

    src: the android-apk payload cache (assets/); debs: the fetched Debian arm64 tree.
    """
    for have in (src / 'toolchain/clang/bin/clang', src / 'toolchain/bin/glslc',
                 src / 'dotnet.pkg', src / 'tool/pylibs/lz4/__init__.py',
                 src / 'tool/tools/nx_extract/nx_extract',
                 src / 'tool/tools/dmsh_xlate/dmsh_xlate.dll'):
        if not have.is_file():
            raise SystemExit(f'the toolchain source is incomplete: {have} is missing')
    usr = appdir / 'usr'
    count = 0
    toolchain = usr / 'toolchain'
    for name in ('clang', 'bin', 'lib'):   # clang/, bin/glslc, lib/libshaderc.so.1; Linux ELF 构建（--os linux）不需要 NDK/bionic
        count += copy_tree(src / 'toolchain' / name, toolchain / name)
    for name in ('nx_extract', 'dmsh_xlate'):
        count += copy_tree(src / 'tool' / 'tools' / name, usr / 'cs-tools' / name)
    count += copy_tree(debs, toolchain / 'glibc')
    _lib = toolchain / 'glibc' / 'lib'
    if not _lib.is_symlink() and not _lib.exists():
        _lib.symlink_to('usr/lib')   # usrmerge: glibc's own linker scripts name absolute /lib/... paths (libm.so: GROUP ( /lib/aarch64-linux-gnu/libm.so.6 ...)), and lld answers them under the sysroot
    with tarfile.open(src / 'dotnet.pkg') as t:
        t.extractall(usr / 'dotnet', filter='tar')
        count += sum(1 for _ in (usr / 'dotnet').rglob('*') if _.is_file())
    for want in (toolchain / 'clang/bin/clang', toolchain / 'bin/glslc',
                 toolchain / 'glibc/usr/include/stdio.h', usr / 'dotnet/dotnet',
                 toolchain / 'glibc/usr/lib/gcc/aarch64-linux-gnu/14/crtbegin.o',
                 toolchain / 'glibc/usr/lib/aarch64-linux-gnu/libvulkan.so',
                 usr / 'cs-tools/nx_extract/nx_extract', usr / 'cs-tools/dmsh_xlate/dmsh_xlate.dll'):
        if not want.is_file():
            raise SystemExit(f'the toolchain bundle is incomplete: {want} is missing')
    return count


def stage_pylibs(appdir: Path, src: Path, work: Path) -> int:
    """The Python modules the porter imports, in the target machine's own CPython ABI.

    The phone payload's pylibs are built for its rootfs's python: most of them are the
    stable ABI (abi3 -- those travel as they are), but lz4, yaml and PIL carry
    cpython-313 extensions, and the DroidDeck tablet runs python 3.14. Those four come
    from the target distribution's own arm64 packages instead (main + universe are both
    read), unpacked over the payload's tree -- a python ignores an extension module whose
    ABI tag names another version, so the merge is safe. capstone's shared library
    (libcapstone) lands beside the modules, where LD_LIBRARY_PATH finds it.
    """
    usr = appdir / 'usr'
    count = copy_tree(src / 'tool' / 'pylibs', usr / 'pylibs')
    mirror = os.environ.get('NX2A_UBUNTU_MIRROR', 'https://mirrors.tuna.tsinghua.edu.cn/ubuntu')
    index = {}
    for component in ('main', 'universe'):
        raw = fetch_debs.get(f'{mirror}/dists/resolute/{component}/binary-arm64/Packages.xz')
        index.update(fetch_debs.parse_packages(lzma.decompress(raw).decode()))
    staged = work / 'pylibs-debs'
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    names, missing = fetch_debs.resolve(index, ['python3-lz4', 'python3-capstone', 'python3-pil', 'python3-yaml'])
    if missing:
        raise SystemExit(f'ubuntu packages not found: {", ".join(missing)}')
    for name in names:
        record = index[name]
        data = fetch_debs.get(f'{mirror}/{record["filename"]}')
        if record['sha256'] and hashlib.sha256(data).hexdigest() != record['sha256']:
            raise SystemExit(f'SHA-256 mismatch: {name}')
        fetch_debs.extract_deb(data, staged)
        print(f'   {name} {record.get("Version", "")}')
        count += 1
    dist = staged / 'usr/lib/python3/dist-packages'
    if dist.is_dir():
        count += copy_tree(dist, usr / 'pylibs')
    lib = staged / 'usr/lib/aarch64-linux-gnu'
    if lib.is_dir():
        for path in lib.iterdir():
            # every shared library the ABI extensions need (liblz4, libyaml, libjpeg,
            # libtiff, ... and libcapstone): LD_LIBRARY_PATH points at this directory
            if path.name.startswith('lib') and '.so' in path.name:
                shutil.copy2(path, usr / 'pylibs' / path.name)
                count += 1
    return count


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
    parser.add_argument('--with-toolchain', action='store_true',
                        help='put the build toolchain in the package (the phone payload\'s linux-aarch64 clang, glslc, '
                             'the .NET runtime, the prebuilt C# tools, the porter\'s Python modules, and a Debian '
                             'glibc prefix), for a machine with no compiler')
    parser.add_argument('--toolchain-src', default=str(ROOT / 'packaging/android-apk/.cache/assets'),
                        help='the android-apk payload cache the toolchain comes from')
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
    stats['extra'] = 0
    if args.with_toolchain:
        debs = work / 'debs'
        mirror = os.environ.get('NX2A_DEB_MIRROR', 'https://mirrors.tuna.tsinghua.edu.cn/debian')
        subprocess.run([sys.executable, str(ROOT / 'packaging/android-apk/fetch_debs.py'),
                        '--out', str(debs), '--mirror', mirror,
                        'libc6-dev', 'linux-libc-dev', 'zlib1g-dev',
                        'libclang-common-18-dev', 'libclang-rt-18-dev',
                        # the link pieces the launcher's ELF needs on a machine with no compiler
                        # (the DroidDeck tablet): clang compiles everything itself, but on a gnu
                        # triple it still asks gcc's crtbegin/crtend for the link and libgcc for
                        # its runtime, and -lvulkan wants the dev symlink. Staged inside the
                        # sysroot, clang's own GCC detection finds them -- no build.py change.
                        'gcc-14', 'libgcc-14-dev', 'libgcc-s1', 'libvulkan-dev', 'libvulkan1'],
                       check=True)
        stats['extra'] += stage_toolchain(appdir, Path(args.toolchain_src), debs)
        stats['extra'] += stage_pylibs(appdir, Path(args.toolchain_src), work)
        print('>> fetching PySide6 (the UI toolkit for the target)')
        pyside_wheels = fetch_pyside_wheels(work / 'pyside')
        stats['extra'] += stage_pyside(appdir, pyside_wheels)
    print(f'   {stats["files"]} files, profiles: {"in" if stats["profiles"] else "not in"} the package'
          + (f', toolchain+pylibs: {stats["extra"]} more files' if args.with_toolchain else ''))

    name = ('nx2androidX-arm64' + ('-toolchain' if args.with_toolchain else '')
            + ('-full' if args.with_profiles else '') + '.AppImage')
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
