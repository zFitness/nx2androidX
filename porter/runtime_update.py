"""Rebuild only a game's player runtime. The fresh components go into the app's private runtimes folder
(NX2A_RUNTIMES, one folder per title ID, with a build.json marker beside them) — or, when that is not
set, back into the pack's own places as before (the desktop tool and the upstream engine keep that
layout)."""
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from porter import config, profiles_layer, toolchain
from porter.paths import DM
from porter.revision import PLAYER_API_REVISION

HOOKS = ('libhook_impl.so', 'libmain_hook.so', 'libfile_redirect_hook.so', 'libgsl_alloc_hook.so')

# Where the runtime lives in a pack: the host in its own folder, the managed hooks beside the drivers.
HOST = 'host/libdmhost.so'
HOOK_DIR = 'drivers'

# The files a runtime update owns and replaces in place.
RUNTIME_FILES = (HOST,) + tuple(f'{HOOK_DIR}/{name}' for name in HOOKS)


def install(source: Path, target: Path):
    """Put a staged component in its place. The rename is one atomic step: the file is never half there."""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError:
        # Another filesystem (a drivers folder on another volume): copy it in and rename it over.
        pending = target.with_name(target.name + '.part')
        with source.open('rb') as src, pending.open('wb') as dst:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(pending, target)


def runtimes_root():
    """The app's private runtimes folder (NX2A_RUNTIMES), or None when the caller did not give one:
    without it the runtime goes back into the pack, as the desktop tool's layout has it."""
    given = os.environ.get('NX2A_RUNTIMES', '').strip()
    return Path(given) if given else None


def build_marker(profile_h, romfs=''):
    """The build fingerprint the runtime was made with: the player interface it speaks, the profile it was
    built from (the game_profile.h's hash — the alias headroom is in there) and where the game's files live (the
    RomFS is not in the pack: the host reads it from there). The app compares this against what it expects before
    it loads the runtime, and checks the folder before it starts the game."""
    return {'player_api_revision': PLAYER_API_REVISION, 'profile_h': profile_h or '', 'romfs': romfs or ''}


def embed_profile(pack: Path, title_id: str, profile_dir: Path) -> bool:
    """Copy the profile a runtime was built from into the pack's own profile/<title ID>/ (the two tsv files,
    each one atomic rename; the source copy stays where it is - this is a copy, not a move). Best-effort: True
    when the pack carries them, False when they were already there or the write failed (an unmounted card, say)
    - the next rebuild simply falls back again."""
    target = pack / 'profile' / title_id
    if target == profile_dir: return False
    try:
        target.mkdir(parents=True, exist_ok=True)
        for src in sorted(profile_dir.iterdir()):
            if not src.is_file(): continue   # 子目录不属于档案本身
            pending = target / (src.name + '.part')
            with src.open('rb') as f, pending.open('wb') as dst:
                shutil.copyfileobj(f, dst)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(pending, target / src.name)
        return True
    except OSError:
        return False


def read_marker(target: Path) -> dict:
    """The build marker a runtime folder carries, or an empty dict without one"""
    try:
        return json.loads(target.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def write_marker(target: Path, marker: dict):
    """The build marker goes in last: a runtime without its marker is rebuilt, never loaded half-known."""
    target.parent.mkdir(parents=True, exist_ok=True)
    pending = target.with_name(target.name + '.part')
    with pending.open('w', encoding='utf-8') as stream:
        json.dump(marker, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(pending, target)


class ProfileDrift(ValueError):
    """The pack was built with a profile that no longer exists; the player may choose the profile the game has now."""


def build_args(title_id: str, output: Path, jobs=None) -> list[str]:
    """build.py's command line for the rebuilt runtime. The launcher's line (NX2A_HOST_OS=linux)
    builds the pack's Linux ELF — the very same command a full port builds its host with
    (phone_port.linux_host_args), no NDK and no loader hooks, for Linux runs the system's
    Vulkan driver. The app's line builds libdmhost.so with the NDK, statically linked with the
    app's JNI adapter."""
    jobs = jobs or os.cpu_count() or 8
    if os.environ.get('NX2A_HOST_OS') == 'linux':
        from porter.phone_port import linux_host_args
        return linux_host_args(title_id, output, jobs)
    ndk, _ = toolchain.find_ndk(config.load())
    if ndk is None:
        raise ValueError('The Android compiler is unavailable. Prepare the environment and retry.')
    args = [sys.executable, str(DM / 'android/build.py'), '--game', title_id,
            '--ndk', str(ndk), '--out', str(output), '--play', '--release', '--jobs', str(jobs)]
    if not all((DM.parent.parent / 'tools' / 'adrenotools' / name).is_file() for name in HOOKS):
        args.append('--adrenotools')
    return args


def profile_candidates(pack, title_id):
    """Where the profile this pack was built with may live: the pack's own copy first (the two tsv files travel
    with the pack, so a rebuild on another device - or after the workspace is gone - finds them), then the build
    workspace's own copies (the headroom copy, the derived one, the provisional one - older packs rely on them
    until their first successful rebuild writes the pack's copy), then the player's imported profiles."""
    yield Path(pack) / 'profile' / title_id
    build = Path(os.environ.get('NX2A_WORK') or tempfile.gettempdir()) / f'{title_id}_build'
    for name in ('profile-mem', 'profile-derived', 'profile'):
        yield build / name / title_id
    yield profiles_layer.layer_dir() / title_id


def profile_fingerprint(directory):
    """sha256 of the game_profile.h the profile in this folder makes (as the host build makes it), or None when the
    folder holds no usable profile"""
    if not (directory / 'game.tsv').is_file() or not (directory / 'android.tsv').is_file(): return None
    with tempfile.TemporaryDirectory(prefix='nx2a_profile_') as t:
        header = Path(t) / 'game_profile.h'
        env = dict(os.environ, DM_GAMES_DIR=str(directory.parent), DM_GAMES_FIRST='1')
        run = subprocess.run([sys.executable, str(DM / 'games/game.py'), 'header', str(directory), str(header)],
                             capture_output=True, text=True, errors='replace', env=env)
        if run.returncode or not header.is_file(): return None
        return hashlib.sha256(header.read_bytes()).hexdigest()


def find_profile(pack, title_id, expected, allow_drift=False):
    """(the profile to rebuild with, its fingerprint, whether any candidate was there at all)

    A pack that recorded no fingerprint (made before the profiles were fingerprinted) cannot be checked: it gets
    the first profile there is, and the fingerprint of that one is recorded when the runtime is rebuilt. The player
    is told to port the game again if it misbehaves afterwards."""
    found = False
    first = None
    for candidate in profile_candidates(pack, title_id):
        fingerprint = profile_fingerprint(candidate)
        if fingerprint is None: continue
        found = True
        if first is None: first = (candidate, fingerprint)
        if expected is None or fingerprint == expected: return candidate, fingerprint, True
    if allow_drift and first is not None:
        # 没有一份对得上，但玩家让 App 用当前档案继续：这份就是这个游戏现在在用的档案
        # （完整重新移植用的也是它），重建出来的运行库与重移植是同一个东西。
        # 导入层的那份优先：完整重移植用的就是它（pipeline.sync_profile 把导入的档案拷进 dm/games），
        # 而包里那份是上一次重建用过的快照，可能已经旧了。档案改了而包里那份没跟着改时，重建出来的
        # 运行库就少了那份改动（OCTOPATH TRAVELER II 的区域上限 game_args 就在 game.tsv 里：
        # 少了它，游戏在 nninitStartup 里要 62 GB 的引擎区域，手机的别名区域给不了，直接崩）。
        layer = profiles_layer.layer_dir() / title_id
        layer_fingerprint = profile_fingerprint(layer)
        if layer_fingerprint is not None: return layer, layer_fingerprint, True
        return first[0], first[1], True
    return None, None, found


# The per-build tables a profile header reads (the source of truth is BUILD_TABLES in
# nxnative/dm/games/game.py). Packs ported before those rows moved out of the host's hardcoded
# table (aa063adb, 2026-11-19) carry none of them in any copy of their profile: a rebuild has to
# fill them from the build workspace or the player's imported profiles layer, or the rebuilt UE
# runtime would install no allocator and the game would crash at boot.
BUILD_TABLE_FILES = ('ue_malloc.tsv', 'fps_locks.tsv')


def stage_profile(profile: Path, staged: Path, title_id: str, pack: Path, emit) -> list[str]:
    """Copy the whole profile into the build's scratch folder — the fingerprint then hashes exactly
    what the build compiles — and fill any per-build table the profile copy lacks from the other
    candidates: the pack's copy, the build workspace, the player's imported profiles layer. Emits
    the staged file list and returns it; a table that exists nowhere is reported and the rebuild
    carries on (the wide existing semantics: no new hard failure)."""
    staged.mkdir(parents=True)
    names = []
    for src in sorted(profile.iterdir()):
        if not src.is_file(): continue
        shutil.copyfile(src, staged / src.name)
        names.append(src.name)
    missing = []
    for name in BUILD_TABLE_FILES:
        if (staged / name).is_file(): continue
        source = next((c for c in profile_candidates(pack, title_id)
                       if c.resolve() != profile.resolve() and (c / name).is_file()), None)
        if source is None:
            missing.append(name); continue
        shutil.copyfile(source / name, staged / name)
        names.append(name)
        emit(f'Filled {name} into the staged profile from {source}.')
    if missing:
        # A UE game without ue_malloc.tsv loses its allocator in the rebuild (the crash this fixes);
        # a game that never had the table compiles fine without it, so only the UE case is [RED].
        unreal = 'unreal' in (staged / 'game.tsv').read_text(encoding='utf-8', errors='replace').lower()
        what = ' or '.join(missing)
        if 'ue_malloc.tsv' in missing and unreal:
            emit(f'[RED] The profile has no {what} anywhere (pack copy, build workspace, imported profiles): '
                 f'a rebuilt UE runtime would run without its allocator and crash at boot. Import a current profiles pack or port the game again.')
        else:
            emit(f'Note: the staged profile has no {what} (no pack copy, workspace or imported profile has it); '
                 f'the runtime compiles without those rows.')
    emit('Profile staged: ' + ', '.join(names))
    return names


def rebuild(pack, *, jobs=None, allow_profile_drift=False, emit=print):
    pack = Path(pack).resolve()
    expected = os.environ.get('NX2A_PLAYER_API_REVISION')
    if expected is not None and expected != str(PLAYER_API_REVISION):
        raise ValueError('The runtime tools do not match this app. Refresh the environment and retry.')
    manifest_path = pack / 'nx2a-data.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    title_id = manifest.get('title_id', '')
    if not isinstance(title_id, str) or not re.fullmatch(r'[0-9A-Fa-f]{16}', title_id):
        raise ValueError('Invalid game identity. Port the game again from its original files.')
    fingerprint = manifest.get('profile_h')
    if not isinstance(fingerprint, str) or not fingerprint: fingerprint = None   # an old pack: trusted, not checked
    profile, _, found = find_profile(pack, title_id, fingerprint, allow_drift=allow_profile_drift)
    if profile is None:
        if not found:
            raise ValueError('No game profile for this game. Port the game again from its original files.')
        raise ProfileDrift('The game profile changed since this pack was built.')
    root = Path(os.environ.get('NX2A_WORK') or tempfile.gettempdir()) / 'runtime'
    root.mkdir(parents=True, exist_ok=True)
    stage = None
    activated = False
    try:
        with tempfile.TemporaryDirectory(prefix=title_id + '-', dir=root) as scratch:
            scratch = Path(scratch)
            # Snapshot the whole profile (game.tsv, android.tsv and every table the header reads,
            # such as ue_malloc.tsv): the fingerprint then hashes exactly what the build compiles.
            # A two-file snapshot dropped the per-build rows and every rebuilt UE game lost its
            # allocator (the game crashed in nninitStartup on the zeroed FMallocBinned3 its cut
            # constructor had left). Old packs carry the tables in no copy of their own:
            # stage_profile fills them from the build workspace or the imported profiles layer.
            profile_root = scratch / 'profile'
            staged_profile = profile_root / title_id
            stage_profile(profile, staged_profile, title_id, pack, emit)
            chosen = profile_fingerprint(staged_profile)
            if fingerprint is not None and chosen != fingerprint:
                emit('The game profile changed since this pack was built. Rebuilding the runtime with the current profile.')
            output = scratch / 'host'
            android = os.environ.get('NX2A_HOST_OS') != 'linux'   # the launcher's line builds the pack's own Linux ELF
            args = build_args(title_id, output, jobs)
            env = dict(os.environ, DM_GAME=title_id, DM_GAMES_DIR=str(profile_root), DM_GAMES_FIRST='1')
            tc_lib = toolchain.toolchain_lib_dirs()
            if tc_lib: env['LD_LIBRARY_PATH'] = str(tc_lib[0]) + os.pathsep + env.get('LD_LIBRARY_PATH', '')
            emit('Building the player runtime')
            with subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace') as process:
                for line in process.stdout: emit(line.rstrip())
                if process.wait(): raise RuntimeError('Runtime compilation failed. Retry, or port the game again from its original files.')
            host = output / ('libdmhost.so' if android else 'dmhost')
            with host.open('rb') as stream: header = stream.read(20)
            if len(header) < 20 or header[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', header, 18)[0] != 183:
                raise ValueError('The compiler did not produce a' + ('n Android' if android else '') + ' ARM64 runtime.')
            stage = Path(tempfile.mkdtemp(prefix='.runtime-', dir=pack))
            components = [host]
            if android:
                prebuilt = DM.parent.parent / 'tools' / 'adrenotools'
                hooks = prebuilt if all((prebuilt / name).is_file() for name in HOOKS) else output
                for name in HOOKS:
                    if not (hooks / name).is_file(): raise ValueError(f'Missing runtime component: {name}')
                components += [hooks / name for name in HOOKS]
            for source in components:
                with source.open('rb') as src, (stage / source.name).open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                    dst.flush()
                    os.fsync(dst.fileno())
            target_root = runtimes_root() if android else None   # the managed runtimes folder is the app's layout
            if target_root is not None:
                # The runtime goes to the app's private folder, one folder per title ID, with its build
                # marker beside it (the marker is written last: a runtime without one is rebuilt, never
                # loaded half-known). The pack keeps only its game data; the manifest's 'host' key goes
                # (a pack without it reads as the new layout — the runtime is the folder's, not the pack's).
                # The manifest's own management fields (the profile this was built from, the interface
                # revision) still come back, so the pairing check keeps working the way it always has.
                target = target_root / title_id.lower()
                for name in HOOKS:
                    install(stage / name, target / name)
                install(stage / 'libdmhost.so', target / 'libdmhost.so')
                # where the game's files live moves from the manifest into the runtime's marker (the RomFS is
                # not in the pack): a rebuild keeps the folder it had, a first migration takes it from the manifest
                previous = read_marker(target / 'build.json') if (target / 'build.json').is_file() else None
                romfs = manifest.pop('romfs_at', '') or (previous.get('romfs') if previous else '')
                write_marker(target / 'build.json', build_marker(chosen, romfs))
                manifest.pop('host', None)
                manifest.pop('host_front', None)
                manifest['player_api_revision'] = PLAYER_API_REVISION
                manifest['profile_h'] = chosen
                embed_profile(pack, title_id, staged_profile)
            elif android:
                # No runtimes folder given (the desktop tool, the upstream engine): the runtime lives in
                # the pack's own places, the way it always has. The hooks go in first and the host last
                # (the host is the one that loads them); each one is a single rename, so a file is never
                # half in place.
                for name in HOOKS:
                    install(stage / name, pack / HOOK_DIR / name)
                install(stage / 'libdmhost.so', pack / HOST)
                manifest['host'] = HOST
                manifest['player_api_revision'] = PLAYER_API_REVISION
                manifest['profile_h'] = chosen   # the profile this runtime was built from (a pack without one gets it now)
                manifest.pop('host_front', None)
                embed_profile(pack, title_id, staged_profile)
            else:
                # The launcher's line: the runtime is the pack's own executable (the manifest's 'exe',
                # the file the launcher looks for with its exec bit) and nothing else — Linux runs the
                # system's Vulkan driver, so there are no loader hooks to refresh. The game data,
                # env.txt and saves are not touched; the profile a full re-port would use goes into
                # the pack for the next rebuild, as on the app's line.
                install(stage / 'dmhost', pack / 'host/dmhost')
                os.chmod(pack / 'host/dmhost', 0o755)   # the launcher runs it: a plain copy carries no exec bit
                manifest.pop('host', None)
                manifest.pop('host_front', None)
                manifest['exe'] = 'host/dmhost'
                manifest['player_api_revision'] = PLAYER_API_REVISION
                manifest['profile_h'] = chosen
                embed_profile(pack, title_id, staged_profile)
            pending = stage / 'manifest.json'
            with pending.open('w', encoding='utf-8') as stream:
                json.dump(manifest, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, manifest_path)
            activated = True
            # The staged copy and the folders older packs kept their runtime in are dead now: only the
            # manifest (or, in the new layout, the runtimes folder's marker) activates a runtime.
            for old in pack.glob('.runtime-*'):
                if old.is_dir(): shutil.rmtree(old, ignore_errors=True)
                else: old.unlink(missing_ok=True)
        return {'data': str(pack), 'title_id': title_id, 'name': manifest.get('name', title_id)}
    finally:
        if stage is not None and not activated:
            shutil.rmtree(stage, ignore_errors=True)
