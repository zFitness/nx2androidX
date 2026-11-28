#!/usr/bin/env python3
"""The ARM64 Linux package: one file that runs on a supported ARM64 Linux.

    python packaging/arm-linux/build_appimage.py [--with-profiles] [--with-toolchain] [--out DIR]

The AppDir is a trimmed repository root (usr/{launcher,porter,nxnative,phone_tools}),
so the pipeline behaves inside the package exactly as it does in a checkout.

The interface is PySide6 (Qt), not GTK.  The package runs on the machine's own
python3: --with-toolchain packages bundle the PySide6 wheels (usr/pylibs), while
thin packages expect the machine to provide PySide6 itself (AppRun pre-flight
prints an actionable error when it cannot).  glibc, the X11/Wayland stack and the
Vulkan driver stay with the system, as they must.

The fonts are the one exception: a machine may have no fonts at all (a bare proot,
for instance), and then the interface shows random glyphs instead of Chinese.  The
package brings one Chinese font and one monospace face, and AppRun points fontconfig
at them.

The game profiles (600 MB of shader tables) are in the package only with
--with-profiles; without it the player imports the release's profile package
instead, the way the phone app does.

Build discipline (provenance + concurrency):

* Every run stages into its own AppDir (``.cache/build-<pid>/nx2androidX.AppDir``)
  and holds a flock on ``.cache/.build.lock``, so two concurrent builds cannot
  clobber a shared staging tree.
* After staging, every staged file is hashed and compared against the live source.
  When the comparison is clean, the package provably matches the source state it
  was staged from (recorded in the manifest by hash, not by claim).
* Every artifact gets a sibling ``<artifact>.manifest.json``: HEAD, branch, the git
  status of the working tree (which is what this parallel-session repo actually
  ships), a per-file sha256 inventory, resolved dependency versions + hashes, and
  the artifact's own bytes / SHA-256.
* The artifact is written atomically: to ``*.AppImage.part`` first and renamed only
  after the structural check passes, so a killed build leaves no half-written file.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import lzma
import os
import re
import shutil
import stat as stat_module
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

try:
    import fcntl        # POSIX flock: the build lock
except ImportError:     # non-POSIX hosts are not a build target; importing must not crash
    fcntl = None

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

# Build-machine junk that must never ride along into the package.
JUNK_PARTS = ('__pycache__', '.pytest_cache', '.DS_Store', '.localized', 'Thumbs.db')
# Player property that must never ride along either, no matter what the tree contains.
FORBIDDEN_NAMES = ('.gamedump', 'prod.keys')

BUILD_LOCK_NAME = '.build.lock'
RUN_STALE_AFTER = 86400   # a staging dir older than this belongs to a crashed build

EM_AARCH64 = 183          # ELF e_machine value for the runtime we ship

# The pinned Qt wheel set for the target (aarch64, glibc-2.39+).  Wheel filenames on
# PyPI are lowercase-normalized (separator runs folded to `_`) and are verified
# against PyPI's release index (including its sha256) at fetch time.
PYPI_WHEEL_TAGS = 'cp310-abi3-manylinux_2_39_aarch64'
PYSIDE_VERSION = '6.12.0'


def _wheel_name(project: str, version: str, tags: str = PYPI_WHEEL_TAGS) -> str:
    """The canonical PyPI wheel filename: lowercase, separators folded to `_`."""
    return f'{re.sub(r"[-_.]+", "_", project).lower()}-{version}-{tags}.whl'


PYSIDE_WHEELS = tuple(
    (project, _wheel_name(project, PYSIDE_VERSION))
    for project in ('PySide6', 'shiboken6', 'PySide6-Essentials')
)

UBUNTU_SUITE = 'resolute'   # the distro whose arm64 pylib debs go into --with-toolchain packages
PYLIB_PACKAGES = ('python3-lz4', 'python3-capstone', 'python3-pil', 'python3-yaml')
TOOLCHAIN_DEBS = (
    'libc6-dev', 'linux-libc-dev', 'zlib1g-dev',
    'libclang-common-18-dev', 'libclang-rt-18-dev',
    # the link pieces the launcher's ELF needs on a machine with no compiler
    # (the DroidDeck tablet): clang compiles everything itself, but on a gnu
    # triple it still asks gcc's crtbegin/crtend for the link and libgcc for
    # its runtime, and -lvulkan wants the dev symlink. Staged inside the
    # sysroot, clang's own GCC detection finds them -- no build.py change.
    'gcc-14', 'libgcc-14-dev', 'libgcc-s1', 'libvulkan-dev', 'libvulkan1',
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def url_version(url: str) -> str:
    """A best-effort version segment from a pinned release URL."""
    parts = [part for part in url.split('/') if part]
    if 'download' in parts:
        return parts[parts.index('download') + 1]
    return parts[-1]


def copy_tree(source: Path, target: Path, skip: tuple[str, ...] = ()) -> int:
    """A directory without the build junk and without the skipped parts."""
    count = 0
    for path in sorted(source.rglob('*')):
        relative = path.relative_to(source)
        if any(part in JUNK_PARTS for part in relative.parts):
            continue
        if any(relative.as_posix() == s or relative.as_posix().startswith(s + '/') for s in skip):
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


def _staging_targets(repo: Path, with_profiles: bool):
    """The (name, source, skip) triples that stage into usr/, whichever package variant."""
    engine_skip = SKIP_TREE if with_profiles else SKIP_TREE + ('dm/games',)
    return (
        ('launcher', repo / 'launcher', ()),
        ('porter', repo / 'porter', ()),
        ('phone_tools', repo / 'phone_tools', ()),
        ('nxnative', repo / 'nxnative', engine_skip),
    )


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
    extract_kwargs = {'filter': 'tar'} if hasattr(tarfile, 'tar_filter') else {}
    with tarfile.open(src / 'dotnet.pkg') as t:
        t.extractall(usr / 'dotnet', **extract_kwargs)
        count += sum(1 for _ in (usr / 'dotnet').rglob('*') if _.is_file())
    for want in (toolchain / 'clang/bin/clang', toolchain / 'bin/glslc',
                 toolchain / 'glibc/usr/include/stdio.h', usr / 'dotnet/dotnet',
                 toolchain / 'glibc/usr/lib/gcc/aarch64-linux-gnu/14/crtbegin.o',
                 toolchain / 'glibc/usr/lib/aarch64-linux-gnu/libvulkan.so',
                 usr / 'cs-tools/nx_extract/nx_extract', usr / 'cs-tools/dmsh_xlate/dmsh_xlate.dll'):
        if not want.is_file():
            raise SystemExit(f'the toolchain bundle is incomplete: {want} is missing')
    return count


UBUNTU_INDEX_CACHE = 'ubuntu-index'
UBUNTU_DEB_CACHE = 'ubuntu-debs'


def stage_pylibs(appdir: Path, src: Path, work: Path, records: list | None = None,
                 refresh_index: bool = False) -> int:
    """The Python modules the porter imports, in the target machine's own CPython ABI.

    The phone payload's pylibs are built for its rootfs's python: most of them are the
    stable ABI (abi3 -- those travel as they are), but lz4, yaml and PIL carry
    cpython-313 extensions, and the DroidDeck tablet runs python 3.14. Those four come
    from the target distribution's own arm64 packages instead (main + universe are both
    read), unpacked over the payload's tree -- a python ignores an extension module whose
    ABI tag names another version, so the merge is safe. capstone's shared library
    (libcapstone) lands beside the modules, where LD_LIBRARY_PATH finds it.

    Reproducibility: the Ubuntu Packages index is cached in `work/ubuntu-index` and
    reused between builds (a rolling suite re-resolves differently day to day -- the
    manifest records what was actually used).  The fetched deb files themselves are
    cached by sha in `work/ubuntu-debs`.

    records: when given, gets one {name, version, sha256} entry per deb that ended
    up staged (for the build manifest).

    Returns the number of staged files; when `records` is requested the resolved
    package info lands in that list too.
    """
    usr = appdir / 'usr'
    count = copy_tree(src / 'tool' / 'pylibs', usr / 'pylibs')
    mirror = os.environ.get('NX2A_UBUNTU_MIRROR', 'https://mirrors.tuna.tsinghua.edu.cn/ubuntu')
    index_cache = work / UBUNTU_INDEX_CACHE
    deb_cache = work / UBUNTU_DEB_CACHE
    index_cache.mkdir(parents=True, exist_ok=True)
    deb_cache.mkdir(parents=True, exist_ok=True)
    index = {}
    for component in ('main', 'universe'):
        index_file = index_cache / f'Packages-{UBUNTU_SUITE}-arm64-{component}.xz'
        if index_file.is_file() and not refresh_index:
            raw = index_file.read_bytes()
            print(f'>> the Ubuntu {UBUNTU_SUITE}/{component} index (cached)', flush=True)
        else:
            raw = fetch_debs.get(f'{mirror}/dists/{UBUNTU_SUITE}/{component}/binary-arm64/Packages.xz')
            index_file.write_bytes(raw)
        index.update(fetch_debs.parse_packages(lzma.decompress(raw).decode('utf-8', 'replace')))
    names, missing = fetch_debs.resolve(index, list(PYLIB_PACKAGES))
    if missing:
        raise SystemExit(f'ubuntu packages not found: {", ".join(missing)}')
    staged = work / 'pylibs-debs'
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    for name in names:
        record = index[name]
        deb_file = deb_cache / Path(record['filename']).name
        data = None
        if deb_file.is_file() and record['sha256']:
            cached = deb_file.read_bytes()
            if hashlib.sha256(cached).hexdigest() == record['sha256']:
                data = cached                                   # cached and verified
            else:
                deb_file.unlink()                               # stale cache entry: refetch below
        if data is None:
            data = fetch_debs.get(f'{mirror}/{record["filename"]}')
        if record['sha256'] and hashlib.sha256(data).hexdigest() != record['sha256']:
            raise SystemExit(f'SHA-256 mismatch: {name}')
        if not deb_file.is_file():
            deb_file.write_bytes(data)
        if records is not None:
            records.append({'name': name, 'version': record.get('Version', ''),
                            'sha256': hashlib.sha256(data).hexdigest()})
        fetch_debs.extract_deb(data, staged)
        print(f'   {name} {record.get("Version", "")}', flush=True)
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


def record_deb_suite(packages: list[str] | tuple[str, ...], suite: str, mirror: str,
                     cache_dir: Path) -> dict:
    """Resolve a deb closure from a cached Packages index and record versions plus the
    SHA-256 of the cached deb files.  Nothing is downloaded here: this is bookkeeping
    for the build manifest.  Returns {'available': False} when no cached index."""
    index_file = cache_dir / f'Packages-{suite}-arm64.xz'
    if not index_file.is_file():
        return {'available': False, 'suite': suite, 'mirror': mirror, 'packages': []}
    index = fetch_debs.parse_packages(lzma.decompress(index_file.read_bytes()).decode('utf-8', 'replace'))
    names, missing = fetch_debs.resolve(index, list(packages))
    entries = []
    for name in names:
        record = index.get(name, {})
        filename = record.get('filename', '')
        sha = ''
        deb = cache_dir / Path(filename).name
        if deb.is_file():
            sha = sha256_file(deb)
        entries.append({'name': name, 'version': record.get('Version', ''),
                        'filename': filename, 'sha256': sha})
    entry = {'available': True, 'suite': suite, 'mirror': mirror, 'dist': 'debian',
             'index': index_file.name, 'index_sha256': sha256_file(index_file),
             'packages': entries}
    if missing:
        entry['missing'] = sorted(missing)
    return entry


def stage(appdir: Path, repo: Path, with_profiles: bool, fonts: dict[str, Path]) -> dict:
    """The AppDir: usr/ is a trimmed repository root."""
    usr = appdir / 'usr'
    usr.mkdir(parents=True, exist_ok=True)

    stage_fonts(appdir, fonts['noto'], fonts['noto_license'], fonts['dejavu'])

    files = 0
    for name, source, skip in _staging_targets(repo, with_profiles):
        if not source.is_dir():
            raise SystemExit(f'the source tree is missing: {source}')
        files += copy_tree(source, usr / name, skip)

    shutil.copy2(HERE / 'AppRun', appdir / 'AppRun')
    (appdir / 'AppRun').chmod(0o755)
    shutil.copy2(HERE / 'nx2androidX.desktop', appdir / 'nx2androidX.desktop')
    icon = repo / 'gui' / 'icon.png'
    if icon.is_file():
        shutil.copy2(icon, appdir / 'nx2androidX.png')
        link = appdir / '.DirIcon'
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to('nx2androidX.png')
    return {'files': files, 'profiles': with_profiles}
def tree_listing(root: Path, skip: tuple[str, ...] = ()) -> dict:
    """rel path -> ('file', size, sha256) | ('link', target), skipping junk and skip
    paths.  Absolute symlinks are not recorded (copy_tree skips them the same way)."""
    listing = {}
    if not root.is_dir():
        return listing
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        rel = relative.as_posix()
        if any(part in JUNK_PARTS for part in relative.parts):
            continue
        if any(rel == s or rel.startswith(s + '/') for s in skip):
            continue
        if path.is_symlink():
            link = os.readlink(path)
            if link.startswith('/'):
                continue
            listing[rel] = ('link', link)
        elif path.is_file():
            st = path.stat()
            listing[rel] = ('file', st.st_size, sha256_file(path))
    return listing


def snapshot_check(appdir: Path, repo: Path, with_profiles: bool) -> list[str]:
    """After staging: every staged file has to byte-match the live source, and vice
    versa.  A list of problems; empty == a consistent snapshot, safe to pack."""
    problems = []
    for name, source, skip in _staging_targets(repo, with_profiles):
        if not source.is_dir():
            problems.append(f'{name}: the source tree is missing ({source})')
            continue
        staged = appdir / 'usr' / name
        live = tree_listing(source, skip)
        copy = tree_listing(staged)
        for rel in sorted(set(live) - set(copy)):
            problems.append(f'{name}: changed in the working tree, not in the staged copy: {rel}')
        for rel in sorted(set(copy) - set(live)):
            problems.append(f'{name}: staged file no longer exists in the source tree: {rel}')
        for rel in sorted(set(live) & set(copy)):
            if live[rel] != copy[rel]:
                problems.append(f'{name}: content changed during staging: {rel}')
    return problems


def repair_snapshot(appdir: Path, repo: Path, with_profiles: bool) -> list[str]:
    """One reconciliation pass against the current source: recopy changed/new files,
    drop files the source no longer has.  Returns what it touched; the caller then
    re-verifies with snapshot_check and aborts if it still does not line up."""
    touched = []
    for name, source, skip in _staging_targets(repo, with_profiles):
        if not source.is_dir():
            continue
        staged = appdir / 'usr' / name
        live = tree_listing(source, skip)
        copy = tree_listing(staged)
        for rel, info in live.items():
            if copy.get(rel) == info:
                continue
            target = staged / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if info[0] == 'link':
                if target.is_symlink() or target.exists():
                    target.unlink()
                target.symlink_to(info[1])
            else:
                shutil.copy2(source / rel, target)
            touched.append(f'{name}/{rel}')
        for rel in sorted(set(copy) - set(live)):
            path = staged / rel
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists() or path.is_symlink():
                path.unlink()
            touched.append(f'-{name}/{rel}')
    return touched


def assert_package_layout(appdir: Path, with_toolchain: bool) -> None:
    """Nothing gets packed until the staged tree holds exactly the parts a run needs."""
    basics = [
        (appdir / 'AppRun', 'the entry script'),
        (appdir / 'nx2androidX.desktop', 'the menu entry'),
        (appdir / 'usr/launcher/__init__.py', 'the launcher code'),
        (appdir / 'usr/porter/__init__.py', 'the pipeline code'),
        (appdir / 'usr/phone_tools', 'the phone tools'),
        (appdir / 'usr/nxnative', 'the engine tree'),
        (appdir / FONT_DIR, 'the bundled fonts'),
    ]
    for path, role in basics:
        if not path.exists():
            sys.exit(f'the staged package is missing {role}: {path}')
    phone_tools_dir = appdir / 'usr' / 'phone_tools'
    if not any(phone_tools_dir.glob('**/*.py')):
        sys.exit('the staged package carries no phone tools scripts:\n  '
                 + str(phone_tools_dir))
    if (appdir / 'AppRun').stat().st_mode & 0o111 == 0:
        sys.exit('AppRun staged without its executable bit')
    if with_toolchain:
        bundled = [
            (appdir / 'usr/pylibs/PySide6/__init__.py', 'the bundled interface (PySide6)'),
            (appdir / 'usr/pylibs/shiboken6/__init__.py', 'the bundled bindings helper (shiboken6)'),
            (appdir / 'usr/toolchain/clang/bin/clang', 'the bundled compiler'),
            (appdir / 'usr/toolchain/bin/glslc', 'the bundled shader compiler'),
            (appdir / 'usr/dotnet/dotnet', 'the bundled .NET runtime'),
        ]
        for path, role in bundled:
            if not path.exists():
                sys.exit(f'the --with-toolchain package is missing {role}: {path}')


def assert_no_forbidden(appdir: Path) -> None:
    """Player property never rides along: game dumps, keys, personal configs."""
    hits = []
    for path in appdir.rglob('*'):
        if not path.is_symlink() and path.name in FORBIDDEN_NAMES:
            hits.append(str(path.relative_to(appdir)))
    if hits:
        sys.exit('refusing to pack; these names must never be inside the package:\n  '
                 + '\n  '.join(hits))


def pack(appdir: Path, out: Path, runtime: Path, work: Path) -> None:
    """The AppImage: the squashfs image with the runtime in front of it.

    The image first lands in `out.name + '.part'` and is renamed only after the
    structural check passes, so a killed build leaves no half-written file pretending
    to be a full artifact, and concurrent runs never share a temp name.
    """
    if not shutil.which('mksquashfs'):
        sys.exit('mksquashfs not found (macOS: brew install squashfs; Debian: apt install squashfs-tools)')
    squash = work / f'squashfs-{os.getpid()}.img'
    squash.unlink(missing_ok=True)
    subprocess.run(['mksquashfs', str(appdir), str(squash), '-comp', 'gzip', '-root-owned',
                    '-noappend', '-no-xattrs', '-quiet'], check=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + '.part')
    part.unlink(missing_ok=True)
    with open(part, 'wb') as target:
        target.write(runtime.read_bytes())
        target.write(squash.read_bytes())
    with open(part, 'r+b') as target:      # the type-2 magic, at offset 8
        target.seek(8)
        target.write(b'AI\x02')
    part.chmod(part.stat().st_mode | stat_module.S_IXUSR | stat_module.S_IXGRP | stat_module.S_IXOTH)
    squash.unlink(missing_ok=True)
    part.replace(out)


def check(out: Path, runtime_size: int, expect_machine: int | None = None) -> None:
    """The package itself: an ELF with the type-2 magic and a squashfs right behind the
    runtime (the superblock's magic is 'hsqs').  With expect_machine given, the ELF's
    e_machine field must match too (we ship aarch64)."""
    with open(out, 'rb') as handle:
        head = handle.read(64)
        if head[:4] != b'\x7fELF':
            sys.exit('the output is not an ELF')
        if head[8:11] != b'AI\x02':
            sys.exit('the type-2 magic is missing at offset 8')
        if expect_machine is not None:
            if len(head) < 20:
                sys.exit('the ELF header is too short to read e_machine')
            machine = int.from_bytes(head[18:20], 'little')
            if machine != expect_machine:
                sys.exit(f'not the expected architecture: e_machine={machine} (expected {expect_machine})')
        handle.seek(runtime_size)
        if handle.read(4) != b'hsqs':
            sys.exit('no squashfs image behind the runtime')


class BuildLock:
    """A lock file guarding the whole stage+pack cycle.

    Two concurrent builds used to share one `.cache/nx2androidX.AppDir` and one
    squashfs temp: each would rmtree the other's staging tree mid-build.  Now a
    build holds `.cache/.build.lock` (flock) for its entire run; a second build
    exits immediately with the holder's pid instead of racing it.
    """

    def __init__(self, work: Path):
        self.path = work / BUILD_LOCK_NAME
        self._fd: int | None = None

    def acquire(self) -> None:
        if fcntl is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            holder = ''
            try:
                holder = os.read(fd, 64).decode('utf-8', 'replace').strip()
            except OSError:
                pass
            os.close(fd)
            raise SystemExit(
                'nx2androidX: another AppImage build is holding the lock'
                + (f' (pid {holder})' if holder else '')
                + f'; wait for it, or remove the stale lock if that build is dead: {self.path}')
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is None:
            return
        fd, self._fd = self._fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def sweep_stale_runs(work: Path, max_age_s: float = RUN_STALE_AFTER) -> list[str]:
    """Staging dirs from builds that died (only run while holding the lock)."""
    swept = []
    now = time.time()
    for child in sorted(work.glob('build-*')):
        try:
            if now - child.stat().st_mtime > max_age_s:
                shutil.rmtree(child, ignore_errors=True)
                swept.append(child.name)
        except OSError:
            pass
    return swept


def git_snapshot(repo: Path) -> dict:
    """Read-only git facts for the manifest: HEAD, branch, and the porcelain status of
    the working tree (a parallel worktree cannot be described by HEAD alone)."""
    def git(*args: str) -> str:
        done = subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True, text=True)
        return done.stdout
    try:
        return {'available': True,
                'head': git('rev-parse', 'HEAD').strip(),
                'branch': git('rev-parse', '--abbrev-ref', 'HEAD').strip(),
                'status': git('status', '--porcelain=v1').splitlines()}
    except (OSError, subprocess.SubprocessError):
        return {'available': False, 'head': None, 'branch': None, 'status': []}


def inventory(appdir: Path) -> dict[str, list[dict]]:
    """Every staged file, grouped into package sections (usr/<top>, root entries)."""
    sections: dict[str, list[dict]] = {}
    for path in sorted(appdir.rglob('*')):
        rel = path.relative_to(appdir).as_posix()
        parts = rel.split('/')
        if any(part in JUNK_PARTS for part in parts):
            continue
        key = 'usr/' + parts[1] if parts[0] == 'usr' and len(parts) > 1 else 'root'
        entry = {'path': rel}
        if path.is_symlink():
            entry['link'] = os.readlink(path)
        elif path.is_file():
            entry['bytes'] = path.stat().st_size
            entry['sha256'] = sha256_file(path)
        else:
            continue   # plain directories carry no content of their own
        sections.setdefault(key, []).append(entry)
    return sections


def component_digest(entries: list[dict]) -> str:
    """One digest over a section's per-file hashes (path + sha256 lines, sorted)."""
    payload = ''.join(sorted(f"{e['path']}\t{e['sha256']}\n" for e in entries if e.get('sha256')))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def make_manifest(out: Path, appdir: Path, variant: dict, git_info: dict,
                  staging: dict, deps: dict, created_utc: str) -> dict:
    """The provenance record shipped beside every artifact."""
    sections = inventory(appdir)
    components = {}
    for key in sorted(sections):
        entries = sections[key]
        hashed = [e for e in entries if e.get('sha256')]
        components[key] = {
            'files': len(hashed),
            'bytes': sum(e.get('bytes', 0) for e in hashed),
            'sha256': component_digest(hashed),
            'entries': entries,
        }
    return {
        'spec': 'nx2a-appimage-manifest/1',
        'created_utc': created_utc,
        'artifact': {'name': out.name, 'bytes': out.stat().st_size, 'sha256': sha256_file(out)},
        'variant': variant,
        'source': {'git': git_info, 'staging': staging},
        'components': components,
        'dependencies': deps,
        'contract': {
            'user_data': ['~/.config/nx2a', '~/.local/share/nx2a', '~/.local/state/nx2a'],
            'never_in_package': ['game dumps (.gamedump)', 'prod.keys', 'personal configs', 'romfs'],
        },
    }


def write_manifest(out: Path, manifest: dict) -> Path:
    path = out.with_name(out.name + '.manifest.json')
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    return path


def dependency_pins(runtime: Path, with_toolchain: bool, pyside_wheels: list[Path] = (),
                    ubuntu_records: list[dict] = ()) -> dict:
    """What the package is made of, resolved at build time: pinned downloads plus
    whatever the distro indexes resolved to on this day."""
    deps = {
        'runtime': {'url': fetch.RUNTIME[0], 'version': url_version(fetch.RUNTIME[0]),
                    'arch': 'aarch64', 'pinned_sha256': fetch.RUNTIME[1],
                    'sha256': sha256_file(runtime), 'bytes': runtime.stat().st_size},
        'fonts': {
            'noto_sans_sc': {'url': fetch.NOTO[0], 'pinned_sha256': fetch.NOTO[1],
                             'sha256': sha256_file(fetch.noto_font()), 'license': 'SIL OFL 1.1'},
            'noto_license': {'url': fetch.NOTO_LICENSE[0], 'pinned_sha256': fetch.NOTO_LICENSE[1],
                             'sha256': sha256_file(fetch.noto_license())},
            'dejavu': {'url': fetch.DEJAVU[0], 'version': url_version(fetch.DEJAVU[0]),
                       'pinned_sha256': fetch.DEJAVU[1], 'sha256': sha256_file(fetch.dejavu_archive()),
                       'license': 'Bitstream Vera + DejaVu'},
        },
        'licenses': {
            'project_code': "the repository's own LICENSE files (launcher/porter/nxnative)",
            'pyside6_wheels': 'LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only',
            'fonts': 'SIL OFL 1.1 (Noto Sans SC) / Bitstream Vera + DejaVu (DejaVu Sans Mono)',
            'appimage_runtime': 'upstream type2-runtime, see the pinned URL',
            'distro_debs': 'per-package licenses of the Debian/Ubuntu arm64 repositories',
        },
    }
    if with_toolchain:
        deps['pyside6'] = {'version': PYSIDE_VERSION, 'requires_python': '>=3.10,<3.16',
                           'glibc_min': '2.39 (manylinux_2_39 wheels)',
                           'wheels': [{'project': project, 'filename': wheel.name,
                                       'sha256': sha256_file(wheel)}
                                      for (project, _), wheel in zip(PYSIDE_WHEELS, pyside_wheels)]}
        deps['ubuntu_pylibs'] = {'suite': UBUNTU_SUITE, 'arch': 'arm64',
                                 'mirror': os.environ.get(
                                     'NX2A_UBUNTU_MIRROR',
                                     'https://mirrors.tuna.tsinghua.edu.cn/ubuntu'),
                                 'packages': list(ubuntu_records)}
        debian = record_deb_suite(TOOLCHAIN_DEBS, fetch_debs.SUITE, fetch_debs.MIRROR,
                                  work_deb_cache())
        if debian.get('available'):
            deps['debian_glibc_prefix'] = debian
    return deps


def work_deb_cache() -> Path:
    """Where fetch_debs.py (the shared fetcher) caches the Debian debs + index."""
    return HERE / '.cache' / '.deb-cache'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--with-profiles', action='store_true',
                        help='put the game profiles in the package (600 MB raw, ~100 MB packed)')
    parser.add_argument('--with-toolchain', action='store_true',
                        help='put the build toolchain in the package (the phone payload\'s linux-aarch64 clang, glslc, '
                             'the .NET runtime, the prebuilt C# tools, the porter\'s Python modules, the PySide6 wheels '
                             'and a Debian glibc prefix), for a machine with no compiler')
    parser.add_argument('--toolchain-src', default=str(ROOT / 'packaging/android-apk/.cache/assets'),
                        help='the android-apk payload cache the toolchain comes from')
    parser.add_argument('--out', default=str(HERE / 'dist'))
    parser.add_argument('--keep', action='store_true', help='keep the staged AppDir')
    parser.add_argument('--label', default='',
                        help='a suffix on the artifact name, e.g. candidate test packages')
    parser.add_argument('--no-manifest', action='store_true',
                        help='skip writing the provenance manifest next to the artifact')
    parser.add_argument('--refresh-ubuntu-index', action='store_true',
                        help='re-fetch the cached Ubuntu Packages index used for pylibs staging')
    args = parser.parse_args(argv)

    if fcntl is None:
        print('<< warning: no flock on this host; concurrent-build locking is disabled', file=sys.stderr)

    work = HERE / '.cache'
    work.mkdir(parents=True, exist_ok=True)
    lock = BuildLock(work)
    lock.acquire()
    try:
        for name in sweep_stale_runs(work):
            print(f'>> swept a stale staging dir from a dead build: {name}')

        run_dir = work / f'build-{os.getpid()}'
        shutil.rmtree(run_dir, ignore_errors=True)
        run_dir.mkdir(parents=True)
        appdir = run_dir / 'nx2androidX.AppDir'
        appdir.mkdir()

        print('>> fetching the pinned pieces', flush=True)
        runtime = fetch.runtime()
        fonts = {
            'noto': fetch.noto_font(),
            'noto_license': fetch.noto_license(),
            'dejavu': fetch.dejavu_archive(),
        }

        print('>> staging', flush=True)
        stats = stage(appdir, ROOT, args.with_profiles, fonts)
        stats['extra'] = 0
        pyside_wheels: list[Path] = []
        ubuntu_records: list[dict] = []
        if args.with_toolchain:
            debs = work / 'debs'
            mirror = os.environ.get('NX2A_DEB_MIRROR', 'https://mirrors.tuna.tsinghua.edu.cn/debian')
            subprocess.run([sys.executable, str(ROOT / 'packaging/android-apk/fetch_debs.py'),
                            '--out', str(debs), '--mirror', mirror, *TOOLCHAIN_DEBS],
                           check=True)
            stats['extra'] += stage_toolchain(appdir, Path(args.toolchain_src), debs)
            stats['extra'] += stage_pylibs(appdir, Path(args.toolchain_src), work,
                                           records=ubuntu_records,
                                           refresh_index=args.refresh_ubuntu_index)
            print('>> fetching PySide6 (the UI toolkit for the target)', flush=True)
            pyside_wheels = fetch_pyside_wheels(work / 'pyside')
            stats['extra'] += stage_pyside(appdir, pyside_wheels)

        # Snapshot consistency: every staged file must byte-match the live sources.
        problems = snapshot_check(appdir, ROOT, args.with_profiles)
        repaired: list[str] = []
        if problems:
            print('>> the working tree moved under us (parallel sessions?); reconciling once:', flush=True)
            for problem in problems[:20]:
                print(f'   {problem}')
            if len(problems) > 20:
                print(f'   ... and {len(problems) - 20} more')
            repaired = repair_snapshot(appdir, ROOT, args.with_profiles)
            problems = snapshot_check(appdir, ROOT, args.with_profiles)
            if problems:
                sys.exit('the working tree kept changing while staging; the snapshot is still not '
                         'consistent:\n  ' + '\n  '.join(problems[:20])
                         + '\npause the session(s) editing the repo for a checkpoint, then rerun the build.')

        assert_package_layout(appdir, args.with_toolchain)
        assert_no_forbidden(appdir)

        name = ('nx2androidX-arm64' + ('-toolchain' if args.with_toolchain else '')
                + ('-full' if args.with_profiles else '')
                + (f'-{args.label}' if args.label else '') + '.AppImage')
        out = Path(args.out) / name
        print('>> packing', flush=True)
        pack(appdir, out, runtime, run_dir)
        check(out, runtime.stat().st_size, expect_machine=EM_AARCH64)
        print(f'>> {out} ({out.stat().st_size / 2**20:.0f} MB)')

        if not args.no_manifest:
            git_info = git_snapshot(ROOT)
            deps = dependency_pins(runtime, args.with_toolchain, pyside_wheels, ubuntu_records)
            manifest = make_manifest(
                out, appdir,
                variant={'with_profiles': args.with_profiles, 'with_toolchain': args.with_toolchain,
                         'label': args.label, 'arch': 'aarch64'},
                git_info=git_info,
                staging={'stable': True, 'reconciled_files': repaired,
                         'per_file_check': 'every staged file byte-matches the source it was staged from'},
                deps=deps,
                created_utc=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            )
            manifest_path = write_manifest(out, manifest)
            head = git_info.get('head')
            print(f'>> manifest: {manifest_path}'
                  + (f' (source head {head})' if head else ' (outside a git checkout)'), flush=True)

        if args.keep:
            print(f'>> staged AppDir kept at: {appdir}')
        return 0
    finally:
        if not args.keep:
            shutil.rmtree(run_dir, ignore_errors=True)
        lock.release()


if __name__ == '__main__':
    sys.exit(main())
