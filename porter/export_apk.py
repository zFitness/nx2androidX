#!/usr/bin/env python3
"""The game as a standalone APK: the host built for a NativeActivity of its own, and the APK that ties it to its data folder.

The app's mode runs the game itself: the host carries the player's JNI entry (libdmhost.so) and the app drives it. A
standalone APK has no app: the host is the upstream's APK front (libdmhost.so, dm/android/front_android.c) and the game
reads its files from its own external directory (/storage/emulated/0/Android/data/<package>/files), which is where the
data is put before the player installs the APK.

    python3 -m porter export-apk <data folder> --out <apk> --key <key.json> [--driver <library>]
                                         [--vercode-offset N]

The data folder is a self-sufficient export of the data pack (the app makes it: the pack's own files, the game's files
in RomFS/, and a manifest without this machine's paths). This command builds the host for it, packs the APK (mkapk.py:
the Python standard library only, no JDK and no Android SDK) and signs it with the key. Every exported game shares one
key (the app's own), so a rebuild of the same game installs over the one before it.

--driver is the Vulkan driver library the APK carries: the host loads it from the APK's own library folder (the row
DM_VK_DRIVER in the data folder's env.txt names it). Without one the game runs on the device's own driver, and the
row is removed from env.txt.
"""
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path

from porter import profiles_layer, toolchain
from porter.paths import DM
from porter.upstream import BuildError, say

# The loader and its hooks: the host loads a Vulkan driver through libadrenotools, which lives in the APK's own
# library folder (the linker finds it by name there). The hooks travel with the host: the host hands the loader the
# folder it sits in, and the loader looks the hooks up there.
ADRENOTOOLS_LOADER = 'libadrenotools.so'
ADRENOTOOLS_HOOKS = ('libhook_impl.so', 'libmain_hook.so', 'libfile_redirect_hook.so', 'libgsl_alloc_hook.so')


def manifest(data: Path) -> dict:
    """The data folder's manifest (nx2a-data.json): the game's title ID, its package name, its version and its icon"""
    f = data / 'nx2a-data.json'
    if not f.is_file(): raise BuildError(f'{data}: no nx2a-data.json in it (not a data pack)')
    try: man = json.loads(f.read_text(encoding='utf-8'))
    except ValueError as e: raise BuildError(f'{data}: the manifest does not read ({e})')
    if not isinstance(man, dict): raise BuildError(f'{data}: the manifest is not an object')
    for key in ('title_id', 'package'):
        if not man.get(key): raise BuildError(f'{data}: the manifest has no {key} (the pack is too old: export it again)')
    return man


def title_id_of(man: dict) -> str:
    """The game's title ID, in the upper case the profile folders use"""
    tid = str(man.get('title_id', '')).upper()
    if not tid or len(tid) != 16 or any(c not in '0123456789ABCDEF' for c in tid):
        raise BuildError(f'{man.get("title_id")!r} is not a title ID (16 hexadecimal digits)')
    return tid


def profile_gfx(tid: str) -> str:
    """The profile's graphics ('nvn', 'gl' or ''): the game mode's pacing policy is the NVN one only"""
    return _profile_value(tid, 'graphics')


def profile_landscape(tid: str) -> bool:
    """Whether the game is played in landscape (the profile's `orientation`: landscape by default, `any` for a
    game that turns with the device). The APK declares it, so the game is not shown in a portrait window."""
    return _profile_value(tid, 'orientation') != 'any'


def game_files_dir(package: str) -> str:
    """Where the exported game reads its files from: its own external directory, the one the system gives every
    app (the host's front takes it from the package's own path, so the APK carries nothing about it)."""
    return f'/storage/emulated/0/Android/data/{package}/files'


def _profile_value(tid: str, key: str) -> str:
    """One key of the profile's Android keys (android.tsv), '' when the profile has none"""
    try:
        sys.path.insert(0, str(DM / 'android' / 'tools'))
        try:
            import android_profile
            return str(android_profile.load(tid).get(key, '') or '')
        finally: sys.path.pop(0)
    except Exception: return ''


def with_profile(tid: str):
    """The player's imported profile of a game, copied into the tree's dm/games for the tools that look there (the
    host's profile header, the rewriter's patches). The copy goes when the caller is done with it."""
    return profiles_layer.copy_to_games(tid)


def build_host(tid: str, out: Path, jobs: int) -> Path:
    """The host of this game as a standalone APK: libdmhost.so, the upstream's APK front, built for the phone.

    The profile comes from the player's profile layer (the app does not carry the profiles): it is copied into the
    tree's dm/games for the build, the way the other tools find it."""
    ndk, _ = toolchain.find_ndk()
    if not ndk: raise BuildError('no Android NDK found: python -m porter tools --download')
    args = [sys.executable, str(DM / 'android/build.py'), '--game', tid, '--ndk', str(ndk), '--out', str(out),
            '--lib', '--release', '--jobs', str(jobs)]
    env = dict(os.environ, DM_GAME=tid)
    tc_lib = toolchain.toolchain_lib_dirs()
    if tc_lib: env['LD_LIBRARY_PATH'] = str(tc_lib[0]) + os.pathsep + env.get('LD_LIBRARY_PATH', '')
    r = subprocess.run(args, capture_output=True, text=True, errors='replace', env=env)
    so = out / 'libdmhost.so'
    if r.returncode or not so.is_file():
        tail = (r.stderr.strip() or r.stdout.strip()).splitlines()
        raise BuildError('the host did not build: ' + (tail[-1] if tail else 'no output'))
    return so


def loader_libs() -> list:
    """The loader and its hooks, from the tool tree (the app's build put them there)"""
    d = DM.parent.parent / 'tools' / 'adrenotools'
    if not d.is_dir(): return []
    out = []
    for name in (ADRENOTOOLS_LOADER,) + ADRENOTOOLS_HOOKS:
        f = d / name
        if f.is_file(): out.append(f)
    return out


def theme_assets(data: Path) -> list:
    """The gamepad's theme in the data folder (overlay/theme.tsv and the layouts' images), as mkapk's --asset pairs"""
    folder = data / 'overlay'
    if not folder.is_dir(): return []
    return [f'overlay/{f.name}={f}' for f in sorted(folder.iterdir()) if f.is_file()]


def font_assets() -> list:
    """The overlay's font and its licenses, as mkapk's --asset pairs"""
    from porter.pipeline import ui_font_assets
    return [f'{n}={f}' for n, f in ui_font_assets().items()]


def set_driver(data: Path, driver: Path = None) -> bool:
    """The data folder's env.txt says which driver the host loads (DM_VK_DRIVER): the one packed in the APK, or none
    at all (the device's own driver).

    A folder that cannot be written (a read-only card) still runs: the host then finds no driver there and
    says so in its log."""
    env = data / 'env.txt'
    try:
        lines = env.read_text(encoding='utf-8', errors='replace').splitlines() if env.is_file() else []
        kept = [l for l in lines if not l.startswith('DM_VK_DRIVER=')]
        if driver: kept.append(f'DM_VK_DRIVER={driver.name}')
        env.write_text('\n'.join(kept) + '\n', encoding='utf-8')
        return True
    except OSError: return False


def pack_apk(so: Path, out: Path, key: Path, man: dict, data: Path, driver: Path = None,
             version_code: int = 1, label: str = '', package: str = '', version_name: str = '') -> int:
    """The APK: the host, the data folder's theme and icon, the overlay's font, the loader and its hooks, and the
    driver when there is one. Signed with the key (the app's own). → the APK's size in bytes"""
    # the package the player picked travels as the manifest's own row: everything downstream (the APK's
    # identity, the game's own files folder) reads the manifest and follows
    if package: man['package'] = package
    from porter.pipeline import version_code as version_code_of
    # the versionName is display-only (the player can pick it); the versionCode keeps the Switch version + offset
    ver = version_name or str(man.get('version') or man.get('display') or '1.0')
    code = version_code if version_code else version_code_of(ver)
    args = [sys.executable, str(DM / 'android/apk/mkapk.py'), str(so), str(out), str(key),
            '--package', str(man['package']), '--label', label or str(man.get('name') or man['package']),
            '--lib', 'dmhost', '--version-code', str(code), '--version-name', ver, '--release']
    if profile_landscape(title_id_of(man)): args += ['--landscape']   # the game's own orientation (the profile's)
    icon = data / str(man.get('icon') or 'icon.png')
    if icon.is_file(): args += ['--icon', str(icon)]
    for pair in theme_assets(data) + font_assets(): args += ['--asset', pair]
    for lib in loader_libs(): args += ['--extra-so', str(lib)]
    if driver: args += ['--extra-so', str(driver)]
    if profile_gfx(title_id_of(man)) != 'gl': args += ['--game-mode-performance']   # the NVN pacing policy only
    r = subprocess.run(args, capture_output=True, text=True, errors='replace')
    if r.returncode:
        tail = (r.stderr.strip() or r.stdout.strip()).splitlines()
        raise BuildError('the APK did not build: ' + (tail[-1] if tail else 'no output'))
    return out.stat().st_size


def export(data: Path, out: Path, key: Path, driver: Path = None, vercode_offset: int = 0,
           package: str = None, version_name: str = None, jobs: int = 8, emit=print) -> dict:
    """The APK of a game whose data folder is ready: the host, the APK, the driver's line in env.txt.
    → {'apk', 'data', 'package', 'size', 'driver'}"""
    man = manifest(data)
    tid = title_id_of(man)
    copied = with_profile(tid)   # the profile the tools look for is in the tree's dm/games while the build runs
    try:
        emit(f'{man.get("name") or tid}: building the host for a standalone APK')
        with tempfile.TemporaryDirectory(prefix='nx2a_export_') as t:
            so = build_host(tid, Path(t), jobs)
            emit(f'{man.get("name") or tid}: the host is {so.stat().st_size / 2**20:.1f} MB')
            size = pack_apk(so, out, key, man, data, driver=driver,
                            version_code=version_code(str(man.get('version') or '1.0'), vercode_offset),
                            label=str(man.get('name') or man.get('display') or ''), package=package,
                            version_name=version_name or '')
        if not set_driver(data, driver):
            emit(f'[RED] {data}/env.txt could not be written: the game runs on the device\'s own driver')
    finally:
        if copied: shutil.rmtree(copied, ignore_errors=True)   # the copy of the imported profile goes when the host is built
    say(f'{out}: {size / 2**20:.1f} MB (the data: {game_files_dir(str(man["package"]))})')
    return {'apk': str(out), 'data': game_files_dir(str(man['package'])), 'package': str(man['package']), 'size': size,
            'driver': str(driver) if driver else ''}


def version_code(ver: str, offset: int = 0) -> int:
    """The APK's versionCode: the game's version number, so an update installs over the base game's port (the
    pipeline's rule), lifted by the offset when the same game is exported again (the app counts the exports)."""
    from porter.pipeline import version_code as version_code_of
    return version_code_of(ver, offset)
