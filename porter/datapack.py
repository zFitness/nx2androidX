# The data pack: everything the app reads from its files folder on the device (/sdcard/Android/data/<package>/files, front_player.c), as a folder beside the APK:
#   mods/          the rewritten code modules (patch_nso.py's outputs)
#   RomFS/         the game's files (the packed version's merged RomFS); the app's mode leaves it out: the pack points at the build folder's own RomFS (the manifest's romfs_at)
#   aoc/<index>/   the DLC the player has
#   sysdata/<title ID>/  system data from the player's firmware dump that the game reads (android.tsv sysdata, porter --firmware; env.txt's DM_SYSDATA)
#   shaders.dmsv   the Vulkan shaders (dm/android/tools/shader_vk.py)
#   nintendo_ext.ttf  the button-icon font, the stand-in for the Nintendo extension shared font (dm/tools/make_ext_font.py; env.txt's DM_SHARED_FONT_EXT)
#   standard.ttf   the player's font for the system's shared fonts, with --shared-font (env.txt's DM_SHARED_FONT)
#   env.txt        host switches: the game language, the DLC folder, the profile's env rows, then the port's (--fps60, --mt-replay, --no-menu-button); on the device the installer adds its
#                  DM_ROMFS row after them when the app reads its RomFS from another folder (porter/install.py, --romfs-at): that is a fact of one device, not of the pack
#   settings.txt   the pause menu's first-launch defaults (the profile's setting rows, then the port's: --touch); the installer never replaces the player's own
#   nx2a-data.json what the pack is: the game, the package, the version, the device features the profile requires (android.tsv requires), which the installer checks
# Big trees are hard links into the extraction when the volume allows, so the pack takes no extra space; the pack is rebuilt whole when anything in it changes.
# A port with --romfs-container packs neither RomFS/ nor aoc/: its manifest lists the player's own NSPs (files/' push below), which the installer pushes to the device
# as they are and the host reads the game's files out of (env.txt's DM_ROMFS_CONTAINER, dm/host/dm_romfs.c). The game's files stay in one place: the folder they came from.
import json, os, shutil, time
from pathlib import Path
from porter.revision import PLAYER_API_REVISION

from porter.upstream import settings_registry

MANIFEST = 'nx2a-data.json'
KEEP_ON_DEVICE = ('settings.txt',)          # the player's choices win over the pack's defaults
OWNED = ('mods', 'RomFS', 'aoc', 'sysdata')            # folders the pack owns on the device: files there that the pack lacks are stale (an older version's) and removed
ROMFS = 'RomFS'
CONTAINER = 'container'           # with --romfs-container: where the installer puts the player's own NSPs in the files folder (files/container/...)
CONTAINER_BASE = 'romfs.nsp'      # romfs_open_view (dm/host/hle_fs.c mount_rom_host): the base game's NSP (romfs.xci for a gamecard base), or its update's for a full update
CONTAINER_UPDATE = 'update.nsp'   # a BKTR update layered over the base RomFS, or a full one in its place


def link_or_copy(src, dst, progress=None):
    """A link where the filesystem allows it, else a copy; progress: called with the bytes written so far (the 1.2 GB
    shader bundle is one file, and a copy on the shared storage runs for a while with nothing else to report)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        if progress: progress(src.stat().st_size)
    except OSError:
        if progress is None:
            shutil.copy2(src, dst); return
        n = 0
        with src.open('rb') as fi, dst.open('wb') as fo:
            while chunk := fi.read(8 << 20):
                fo.write(chunk); n += len(chunk); progress(n)
        shutil.copystat(src, dst)


def link_tree(src, dst, progress=None):   # (files, bytes)
    n = b = 0
    for root, _, files in os.walk(src):
        for f in files:
            s = Path(root) / f
            link_or_copy(s, dst / s.relative_to(src), progress); n += 1; b += s.stat().st_size
    return n, b


def tree_files(src):   # every file under a tree: the pack asks for their sizes before the copy, to report its own progress
    return (Path(root) / f for root, _, files in os.walk(src) for f in files)


def files_folder(package): return f'/sdcard/Android/data/{package}/files'


SEEDABLE = ('RomFS', 'aoc')   # parts another port of the same game version on the device can give a new install (porter/install.py seed_from_sibling)


def part_key(d, part):
    """{'files', 'bytes', 'key'} of a pack part (RomFS, aoc): the key is a hash of its paths and sizes. Two packs of one game version have the same key for the same
    files (a RomFS is the game's own, the same in every port of that version; a packed RomFS has other sizes), which lets an install copy the part on the device
    from another port of the game instead of pushing it again. None when the part is not in the pack"""
    import hashlib
    r = Path(d) / part
    if not r.is_dir(): return None
    files = sorted((p.relative_to(r).as_posix(), p.stat().st_size) for p in r.rglob('*') if p.is_file())
    h = hashlib.sha256(''.join(f'{rel}\t{size}\n' for rel, size in files).encode('utf-8')).hexdigest()
    return {'files': len(files), 'bytes': sum(s for _, s in files), 'key': h}


def romfs_sizes(d):   # {path in the RomFS: size} of the pack in d, '/'-separated as the device lists them (install --romfs-at compares a folder on the device with it)
    r = Path(d) / ROMFS
    return {p.relative_to(r).as_posix(): p.stat().st_size for p in r.rglob('*') if p.is_file()} if r.is_dir() else {}


def build(dst, *, profile, version, display, patched, romfs, shaders, aoc=None, containers=None, keys=None, container=False, sysdata=None, language='en-US', package=None, env=(), settings=None, files=None, text=None,
          host=None, icon=None, drivers=None, profile_h=None, no_lsfg=None, pack_base=None, romfs_at=None, progress=None):
    """Write the pack to dst (replacing it). profile: the AndroidProfile; package: the app's, when not the profile's; env: more env.txt rows, after the profile's; settings: settings.txt values over the profile's;
    files: {name in the pack: source} (the 60 fps memory writes, fpslock.tsv; the button-icon font; subfolders for the app's mode: host/, drivers/, overlay/, icon.png);
    text: {name in the pack: its text} (the launcher's lists: languages.txt, drivers.txt); host/icon/drivers: the app's artifacts, named in the manifest;
    pack_base: where the pack lives on the device (the app's mode carries it in its own folder; else the app's files folder); profile_h: sha256 of the game_profile.h the host was built with (porter host);
    romfs_at: a folder on the device that holds the game's RomFS (the app's mode: the build folder's own RomFS). The pack does not carry the RomFS then: its env.txt says where the host reads it from,
    and the manifest says the same, so the app knows the pack needs that folder.
    containers: the player's own game files instead of a RomFS / DLC tree, [(path under files/container/, source on this PC, bytes)] (romfs.nsp, update.nsp, aoc/<index>.nsp), which
    the installer pushes to the device as they are and the host reads the game's files out of (the manifest's push; no copy in the pack). keys: [(name in the files folder, source, bytes)]
    for DM_PROD_KEYS, likewise pushed, not packed: they are the player's. container: the pack reads the game out of the player's own files without
    a push list (the phone's app mode: env.txt names the files where they are). Returns the manifest"""
    package = package or profile.package
    if romfs_at: romfs = None   # the RomFS is read from that folder, not from the pack
    tmp = dst.with_name(dst.name + '.partial')
    shutil.rmtree(tmp, ignore_errors=True)   # the half-made pack of a killed port: it may be gone already, and one that vanishes while it is removed must not stop the port
    tmp.mkdir(parents=True)
    n = b = 0
    trees = (('the rewritten modules', patched, 'mods'), ('the RomFS', romfs, ROMFS), ('the DLC', aoc, 'aoc'), ('the system data', sysdata, 'sysdata'))
    # The pack's own count: progress(what, bytes_done, bytes_total), so the bar moves while the bytes are written.
    total = sum(p.stat().st_size for _, src, _ in trees if src for p in tree_files(src))
    total += shaders.stat().st_size if shaders else 0
    total += sum(Path(src).stat().st_size for src in (files or {}).values())
    total += sum(len(body.encode('utf-8')) for body in (text or {}).values())
    written = 0

    def tick(k, what):
        nonlocal written
        written += k
        if progress: progress(what, written, total)

    for what, src, sub in trees:
        if not src: continue
        if progress: progress(what, written, total)
        dn, db = link_tree(src, tmp / sub, progress=lambda k, w=what: tick(k, w)); n += dn; b += db
    if shaders:
        if progress: progress('the shaders', written, total)
        link_or_copy(shaders, tmp / 'shaders.dmsv', progress=lambda k: tick(k, 'the shaders')); n += 1; b += shaders.stat().st_size   # none for an OpenGL ES game
    for name, src in (files or {}).items():
        f = tmp / name
        f.parent.mkdir(parents=True, exist_ok=True)   # the app's files live in subfolders (host/, drivers/, overlay/)
        shutil.copyfile(src, f); n += 1; b += Path(src).stat().st_size; tick(Path(src).stat().st_size, 'the runtime files')
    for name, body in (text or {}).items():
        (tmp / name).write_text(body, encoding='utf-8', newline='\n'); n += 1
        b += len(body.encode('utf-8')); tick(len(body.encode('utf-8')), 'the lists')
    base = pack_base or str(dst)   # where the pack lives on the device: its own folder (the app's mode); the PC tool's install puts it in the app's files folder
    rows = [f'# Written by nx2android\'s porter for {profile.name} ({profile.id}); KEY=VALUE per line, read by the app at launch',
            f'DM_LANG={language}']
    if romfs_at: rows.append(f'DM_ROMFS={romfs_at}')   # the game's RomFS is read from there, not from the pack (the app's mode: the build folder's own)
    if aoc: rows.append(f'DM_AOC_DIR={base}/aoc')   # the pack's own folder
    if sysdata: rows.append(f'DM_SYSDATA={base}/sysdata')
    ff = files_folder(package)   # the PC install's copy of the game's own files (containers; the phone's app mode passes its own env rows)
    if containers:
        rows.append(f'DM_PROD_KEYS={ff}/prod.keys')
        rows.append(f'DM_ROMFS_CONTAINER={ff}/{CONTAINER}/{containers[0][0]}')   # romfs.nsp, or romfs.xci for a gamecard base
        if upd := next((r for r, _, _ in containers if r.startswith('update.')), None): rows.append(f'DM_ROMFS_UPDATE={ff}/{CONTAINER}/{upd}')
        if any(dst_rel.startswith('aoc/') for dst_rel, _, _ in containers): rows.append(f'DM_AOC_DIR={ff}/{CONTAINER}/aoc')
    rows += profile.env + list(env)
    if bad := settings_registry.check_env(rows, ('profile', 'porter'), 'env.txt '): raise ValueError('; '.join(bad))   # nxnative/dm/settings.tsv
    (tmp / 'env.txt').write_text('\n'.join(rows) + '\n', encoding='utf-8', newline='\n')
    if sets := {**profile.settings, **(settings or {})}: (tmp / 'settings.txt').write_text(''.join(f'{k}={v}\n' for k, v in sets.items()), encoding='utf-8', newline='\n')
    dlc = sorted(int(p.name) for p in aoc.iterdir() if p.is_dir() and p.name.isdigit()) if aoc else \
          sorted(int(Path(r).stem) for r, _, _ in containers if r.startswith('aoc/') and Path(r).stem.isdigit()) if containers else []
    def entry(rel, s, z):   # a game file beside the pack (the usual out folder: the game's) is named, not given by this PC's path: the pack stays portable
        p = Path(s)
        try: beside = p.resolve().parent == Path(dst).resolve().parent
        except OSError: beside = False
        return dict(dst=rel, src=p.name if beside else str(s), bytes=z)
    push = {what: [entry(r, s, z) for r, s, z in lst] for what, lst in (('container', containers), ('keys', keys)) if lst}
    man = dict(title_id=profile.id, name=profile.name, package=package, version=version, display=display, language=language, requires=profile.requires,
               status=profile.status,   # the profile's own state (playable / wip / boots / experimental): the app tells the player what to expect
               graphics=profile.graphics, lan=profile.lan,   # what the game needs: its graphics API, and whether it plays over the local network
               files=n, bytes=b, dlc=dlc,
               sysdata=sorted(p.name for p in sysdata.iterdir() if p.is_dir()) if sysdata else [], made=time.strftime('%Y-%m-%d %H:%M:%S'))
    if push: man['push'] = push   # the installer pushes these to the device (files/container/..., files/...), from the game folder or from beside the pack
    if containers or container: man['container'] = True   # the game's files are read out of the player's own files: the installer compares no RomFS folder and removes no RomFS tree's files one by one
    if host: man['host'] = host         # the app's mode: the game's host (libdmplay.so) in the pack, the app copies it into its private folder to run the game
    if icon: man['icon'] = icon
    if drivers: man['drivers'] = list(drivers)
    if profile_h: man['profile_h'] = profile_h
    if no_lsfg is not None: man['no_lsfg'] = bool(no_lsfg)   # the runtime build's lsfg switch: part of the build fingerprint
    if romfs_at: man['romfs_at'] = romfs_at   # the folder the RomFS is read from: the pack does not carry it, so the app checks that folder before the game runs
    man['player_api_revision'] = PLAYER_API_REVISION   # the runtime interface the pack was built against: the app rebuilds the runtime when its own revision differs
    if parts := {p: k for p in SEEDABLE if (k := part_key(tmp, p))}: man['parts'] = parts   # the content keys install's seeding compares
    (tmp / MANIFEST).write_text(json.dumps(man, indent=2), encoding='utf-8')
    # the exported saves (the player's backups) are not the build's own: the pack is rebuilt whole, so they are put aside and put back
    keep = dst.with_name(dst.name + '.saves-keep')
    shutil.rmtree(keep, ignore_errors=True)
    exported = dst / 'saves'
    if exported.is_dir(): shutil.move(str(exported), str(keep))
    shutil.rmtree(dst, ignore_errors=True)   # the pack of the last port: it may be gone already (the player deleted it), and the files it holds are the build's own (hard links)
    for i in range(20):   # Windows: a folder just removed can stay delete-pending while another process (an indexer, a virus scan) holds it, and the rename is refused meanwhile
        try: tmp.rename(dst); break
        except PermissionError:
            if i == 19: raise
            time.sleep(0.5)
    if keep.is_dir():
        shutil.move(str(keep), str(dst / 'saves'))   # the backups are back where the save manager looks for them
    shutil.rmtree(keep, ignore_errors=True)
    return man


def read_manifest(d):
    try: return json.loads((Path(d) / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None
