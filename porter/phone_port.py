# The phone app's porter: the port runs on the phone itself — this machine IS the device. Every step that
# upstream's pipeline does over adb (the game's own Oodle decoder, the shader capture, the UE decode) runs here
# directly, the host is built with the phone's own clang (NX2A_ARM_HOST), the pack carries the host, the drivers and
# the icon instead of an APK, and the app runs the game. The base flow is upstream's pipeline.Port verbatim
# (porter/pipeline.py carries no fork code): the app mode's behaviour lives in the overrides below, so upstream's
# file stays untouched and every upstream improvement lands here with a plain sync.
#
# The CLI is phone_cli.py (the app calls `python -m porter.phone_cli`): port (the app mode), rebuild-runtime (the
# app's rebuild button), profiles (list/import — the imported profiles layer is this fork's), inspect (the app's card).
import collections, hashlib, importlib.util, json, mmap, os, re, shlex, shutil, socket, struct, subprocess, sys, time, traceback
from dataclasses import dataclass, field
from pathlib import Path

from porter import pipeline
from porter import config, datapack, dumps, fpslocker, install, memory, paths, product_cache, profiles, profiles_layer, romfs_pack, toolchain
from porter.pipeline import *   # the shared helpers and constants; the app mode's own constants shadow theirs below
from porter.revision import PLAYER_API_REVISION
from porter.adb import NO_ADB, Adb, AdbError
from porter.paths import DM, NXNATIVE
from porter.upstream import BuildError, PROG, android_profile, game, nacp, nsp, profile_guess, say, trinity, uepak

PY = sys.executable
# The shared font the tools ship: the game's Chinese and Korean text (the console's own shared fonts 1-4; dm/tools/cjk_font.py builds it)
SHARED_CJK = DM / 'tools/shared_cjk.ttf'

# A progress line of the shader export (shader_vk.py): "progress: <step>: <done>/<total> shaders (<tail>)". The step is the name of the pass (translating, compressing),
# the tail is what the tool has to add (the batch and the time). The porter turns it into the stage's own count, so the build shows how far the export has come.
SHADER_PROGRESS_RX = re.compile(r'^progress: (.+): (\d+)/(\d+) shaders(?: \((.*)\))?$')


def shader_progress(line):
    """A shader export's progress line → (step, done, total, note), or None for any other line.
    The note carries the count (the app shows the fraction of the stage, not the numbers) and the tool's own tail"""
    m = SHADER_PROGRESS_RX.match(line)
    if not m: return None
    step, done, total, tail = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    note = f'{done:,} of {total:,} shaders' + (f' ({tail})' if tail else '')
    return step, done, total, note
# The Vulkan driver loader and its four hooks: the host loads a driver through libadrenotools (dm/android/gfx_vk_core.c,
# DM_VK_DRIVER). The loader is the app's own: the host dlopens it by name, and the Android linker looks a bare name up in
# LD_LIBRARY_PATH, in the caller's DT_RUNPATH and in the namespace's default library paths — the app's native library
# folder is the only one of those the app controls (the app's private host folder, where the host itself lives, is none
# of them, so a loader copied there is never found). The hooks travel with the host: it hands the loader the folder it
# sits in, and the loader looks the hooks up there.
# The phone has no C++ compiler, so the loader is built for it here (packaging/android-apk/build_adrenotools.py) and
# shipped in the app's assets; on a computer the host builds it (dm/android/build.py --adrenotools).
ADRENOTOOLS_LOADER = 'libadrenotools.so'
ADRENOTOOLS_HOOKS = ('libhook_impl.so', 'libmain_hook.so', 'libfile_redirect_hook.so', 'libgsl_alloc_hook.so')
ADRENOTOOLS_LIBS = (ADRENOTOOLS_LOADER,) + ADRENOTOOLS_HOOKS
LETTER_FONTS = [f'{os.environ.get("WINDIR", "C:/Windows")}/Fonts/{f}' for f in ('ARLRDBD.TTF', 'arialbd.ttf')] + [
    '/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
    # Android's own bold fonts (a phone has no Arial): the letters are knocked out of a solid plate, so any bold font does
    '/system/fonts/Roboto-Bold.ttf', '/system/fonts/DroidSans-Bold.ttf', '/system/fonts/SourceSansPro-Bold.ttf',
    '/usr/share/fonts/liberation/LiberationSans-Bold.ttf', '/usr/share/fonts/noto/NotoSans-Bold.ttf']   # after DejaVu: a machine that has both keeps the font (and its cache key) it had
# Android's own bold fonts (a phone has no Arial): the letters are knocked out of a solid plate, so any bold font does
_LETTER_FONTS_ANDROID = ['/system/fonts/Roboto-Bold.ttf', '/system/fonts/DroidSans-Bold.ttf', '/system/fonts/SourceSansPro-Bold.ttf']


def prebuilt_loader():
    """The driver loader built for the phone (the tool tree's tools/adrenotools), when it is there"""
    d = DM.parent.parent / 'tools' / 'adrenotools'
    return sorted(d.glob('*.so')) if d.is_dir() else []

def launcher_dex():
    """The launcher's dex (the APK's launcher activity, the page the player picks the language and the driver on): built on the computer
    (packaging/android-apk/build_launcher.py) and shipped in the tool tree; None when it was not built (the APK's game is then the entry)"""
    for p in (DM.parent.parent / 'tools' / 'launcher.dex',                                    # the tool tree (the phone, the bundle)
              NXNATIVE.parent / 'packaging/android-apk/.cache/launcher.dex',                 # a developer's checkout
              NXNATIVE.parent / 'packaging/android-apk/.cache/assets/tool/tools/launcher.dex'):  # the built assets
        if p.is_file(): return p
    return None

def _has_network(host='api.nuget.org', port=443, timeout=3):
    """Whether the packages can be fetched: a restore that waits for a name server that never answers looks like
    a build that never ends"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

def _packages_cached():
    """The NuGet packages the shader translator needs, already in the cache: the restore does not need the network
    then"""
    root = Path(os.environ.get('NUGET_PACKAGES', str(Path.home() / '.nuget' / 'packages')))
    return all((root / p).is_dir() for p in
               ('humanizer', 'msgpack.cli', 'gommon', 'microsoft.io.recyclablememorystream'))

def on_android():
    """The porter running on an Android phone (the phone app's own port): the device is this machine, so the game's own code runs here, with no adb and no second device.
    NX2A_ON_DEVICE forces the answer (1 yes, 0 no), to try the other path on a computer"""
    v = os.environ.get('NX2A_ON_DEVICE')
    if v is not None: return v not in ('0', '', 'no', 'false')
    return Path('/system/build.prop').is_file() or os.environ.get('ANDROID_ROOT') == '/system'


def on_linux():
    """NX2A_HOST_OS=linux: the launcher's line — the host builds as a Linux ELF with the machine's own compiler (build.py --os linux), no NDK, and the pack carries it (the manifest's exe)."""
    return os.environ.get('NX2A_HOST_OS') == 'linux'

def volume_of(path):
    """The filesystem a path is on, as the device number of its nearest existing folder (None when it cannot be told: Windows).
    Two paths on the same volume can be written in place (a rename), two on different ones cannot"""
    p = Path(path)
    while not p.exists() and p.parent != p: p = p.parent
    try: dev = os.stat(p).st_dev
    except OSError: return None
    return dev or None

def oodle_where(tools):
    """Where the game's own Oodle decoder runs: 'local' when the porter is on the phone app (the device is this machine), 'device' when adb and a device are there, else None"""
    if on_android(): return 'local'
    return 'device' if tools.get('adb') else None

def oodle_job(roms, tmp):
    """Every Oodle entry of the GFPAKs and of the Trinity packs in one job file (DMOJ: u32 count, then per record u32 compressed length, u32 raw length and the compressed bytes).
    → the records (label, archive size, entry index) in order, and the job file. A Trinity file's index is (pack offset, index in the pack)"""
    recs, job = [], tmp / 'job.bin'
    with open(job, 'wb') as jf:
        jf.write(b'DMOJ' + struct.pack('<I', 0))
        for rom in roms:
            for p in sorted(rom.rglob('*.gfpak')):
                d = p.read_bytes()
                if d[:8] != b'GFLXPACK': continue
                n, _, fo = struct.unpack_from('<IIQ', d, 0x10); label = '/' + p.relative_to(rom).as_posix()
                for i in range(n):
                    ct, usz, csz, off = struct.unpack_from('<2xHII4xQ', d, fo + 0x18 * i)
                    if ct == 3: jf.write(struct.pack('<II', csz, usz) + d[off:off + csz]); recs.append((label, len(d), i))
            for p in sorted(rom.rglob('*.trpfs')):
                if (packs := trinity.packs(str(p))) is None: continue
                label = '/' + p.relative_to(rom).as_posix()
                with open(p, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as d:
                    for off, _, _ in packs:
                        for k, _, comp, n, st, sz in trinity.pack_files(d, off):
                            if comp == 3: jf.write(struct.pack('<II', sz, n)); jf.write(d[st:st + sz]); recs.append((label, len(d), (off, k)))
        jf.seek(4); jf.write(struct.pack('<I', len(recs)))
    return recs, job

def oodle_result(tmp, recs, why='', where=''):
    """The decoder's answer (DMOR: u32 count, then per record u32 decoded length — 0 failed, 0xffffffff left out, no BNSH in it — and the decoded bytes): the entries that hold a
    BNSH shader, written back as the split's decoded folders (shader_split.py gfpak_decoded, trpfs_decoded) → the folder. The answer is read in ranges, not as one buffer: a
    4.4 GB job's decoded payloads never all sit in RAM"""
    by = {}   # label → (archive size, {index: (offset in job.out, length)})
    with (tmp / 'job.out').open('rb') as result:
        total = os.fstat(result.fileno()).st_size; head = result.read(8)
        if len(head) != 8 or head[:4] != b'DMOR' or struct.unpack_from('<I', head, 4)[0] != len(recs):
            raise BuildError(f"the game's Oodle decoder {where} answered for other entries than it was given")
        for label, size, i in recs:
            word = result.read(4)
            if len(word) != 4: raise BuildError(f"the game's Oodle decoder {where} returned a truncated result for {label} entry {i}")
            n = struct.unpack('<I', word)[0]
            ent = by.setdefault(label, (size, {}))[1]
            if n == 0xffffffff: continue
            if n == 0: raise BuildError(f"the game's Oodle decoder {where} failed on {label} entry {i}")
            off = result.tell()
            if n > total - off: raise BuildError(f"the game's Oodle decoder {where} returned a truncated result for {label} entry {i}")
            ent[i] = (off, n); result.seek(n, os.SEEK_CUR)
        dec = tmp / 'decoded'; dec.mkdir()
        for label, (size, ent) in by.items():
            trpfs = label.endswith('.trpfs')
            with (dec / (label.lstrip('/').replace('/', '__') + '.dec')).open('wb') as out:
                out.write((b'DTPD' if trpfs else b'DGFD') + struct.pack('<QI', size, len(ent)))
                for i, (off, n) in sorted(ent.items()):
                    out.write(struct.pack('<QII', *i, n) if trpfs else struct.pack('<II', i, n))
                    result.seek(off)
                    while n:
                        chunk = result.read(min(n, 1 << 20))
                        if not chunk: raise BuildError(f"the game's Oodle decoder {where} returned a truncated result for {label} entry {i}")
                        out.write(chunk); n -= len(chunk)
    nsp.rmtree(tmp / 'job.out')
    say(f"shaders in Oodle-compressed archives ({why}): {len(recs):,} entries decoded by the game's own decoder {where}, "
        f"{sum(len(e) for _, e in by.values()):,} of them hold shaders")
    return dec

def _android(g):
    return android_profile.AndroidProfile(g) if (g.dir / 'android.tsv').is_file() else None


def entry(g, p):
    if p: return profiles.Entry(g.id, g.get('name', g.id), True, p.status, p.tested, p.package)
    return profiles.Entry(g.id, g.get('name', g.id), False, 'not ported', '', f'org.nx2a.t{g.id.lower()}')


def by_title(tid):
    """(game profile, Android profile or None) of a title id: the tree's profiles first (upstream's by_title), then the
    player's imported ones (the layer) — the app's game card and the profiles list answer for imported games too"""
    if isinstance(tid, str) and re.fullmatch(r'[0-9A-Fa-f]{16}', tid): tid = int(tid, 16)
    g, p = profiles.by_title(tid)
    if g: return g, p
    d = profiles_layer.layer_profile(tid)
    g = game.Game(d) if d else None
    return (g, _android(g)) if g else (None, None)


def all_profiles():
    """(game profile, Android profile or None) of every game the tool knows: the repository's own profiles first, then the ones the player imported"""
    out, seen = [], set()
    for g in list(game.all_games()) + [game.Game(d) for d in profiles_layer.layer_profiles()]:
        if g.id in seen: continue
        seen.add(g.id); out.append((g, _android(g)))
    return out


def all_entries(android_only=True):
    rows = [entry(g, p) for g, p in all_profiles()]
    return [r for r in rows if r.android or not android_only]




def inspect(folder, keys=None):
    """What a game folder holds, without extracting anything: the GUI's game card and `porter inspect`. keys: prod.keys (default: the configured one), which reads the title ID
    of a dump with neither a ticket nor a [title ID] tag (an untagged cartridge dump) from its NCA headers"""
    p = Path(folder).expanduser()
    base = p if p.is_file() else None
    if base is not None: p = p.parent
    app, fam = nsp.scan_nsps(p, dumps.EXTS, keys or config.load().get('keys'), base)
    g, ap = by_title(app)
    files = [fam['base'], *(p for _, p in fam['updates']), *(p for _, _, p in fam['dlc'])]

    def where(f):   # the subfolder it was found in ('' when it sits next to the picked file): the GUI's card and the app say where each file came from
        return f.parent.name if f.parent != p else ''

    info = dict(title_id=f'{app:016X}', base=fam['base'].name, updates=[{'version': f'v{v}' if v is not None else None, 'file': f.name, 'folder': where(f)} for v, f in fam['updates']],
                dlc=[{'title_id': f'{t:016X}', 'version': f'v{v}' if v is not None else None, 'file': f.name, 'folder': where(f)} for t, v, f in fam['dlc']], profile=None, android=None, versions=[], pack=None, supported=False, reason='',
                compressed=[p.name for p in files if dumps.compressed(p)])   # NSZ / XCZ: decompressed during the port into the build folder's tmp/, deleted once extracted
    info['experimental'] = not (g and ap)   # a port can still be tried: porter port --experimental
    if not g:
        info['reason'] = f'no game profile for {app:016X}: this game is not supported yet (an experimental port surveys it and guesses a profile; it may not start)'
        return info
    builds = g.builds()
    have = nsp.nsp_versions(fam, builds)
    pack = max(have, key=nsp.vnum)
    info.update(profile=g.id, name=g.get('name', g.id), versions=sorted(have, key=nsp.vnum), pack=pack,
                registered={v: b.get('display', '') for v, b in builds.items()}, derived=pack not in builds)
    if not ap:
        info['reason'] = f'{g.get("name", g.id)} has a game profile (iOS) but is not ported to Android yet (an experimental port tries it with that profile)'
        return info
    info.update(android=entry(g, ap).as_dict(), supported=True)
    if ap.status == 'wip': info['reason'] = f'{g.get("name", g.id)} is a work in progress: it plays, but parts of it are missing (its row in docs/PORT_CHECKLIST.md says which)'
    if pack not in builds:
        info['reason'] = (info['reason'] + '; ' if info['reason'] else '') + f'{pack} is not a version the profile was brought up on ({", ".join(builds)}): it is packed from a derived profile, without that version\'s fixes'
    return info


@dataclass
class Options(pipeline.Options):
    app: bool = False                  # the nx2android app's mode: no APK and no install — the pack carries the host, the drivers and the icon; the app runs the game itself
    low_mem: bool = False               # a phone with little memory free: the shader translation runs with at most two workers (the number follows the memory the device has free anyway; this caps it): slower, but a phone with little memory free survives the build
    vulkan_driver_dir: Path = None     # a folder of arm64 Vulkan drivers: the pack carries them all and the game's configuration panel lets the player pick one


def linux_host_args(game, out, jobs, release=True):
    """build.py's line for the launcher's host: the Linux ELF with the machine's own compiler
    and dm/linux's front (SDL3's window, the Vulkan backend — the shape the machine runs the
    games in). One command for a port's host and a runtime rebuild, so the two cannot build
    different shapes; the headless tools pass their own --gfx null through build_cmd."""
    return [PY, DM / 'android/build.py', '--game', game, '--out', out, '--jobs', str(jobs),
            '--os', 'linux', '--gfx', 'vk', '--exe'] + (['--release'] if release else [])


class PhonePort(pipeline.Port):
    def sync_profile(self, tid):
        """The player's imported profile into the tool tree's dm/games (profiles_layer.copy_to_games): the rewriter's patches.py and the host's profile header are looked up
        there, and not in the folder the player imported them into. The copy goes when the port is done (drop_profile)"""
        try:
            dst = profiles_layer.copy_to_games(tid)
        except OSError as e:
            say(f'[RED] the imported profile of {tid} could not be copied into dm/games ({e}): the rewriter applies none of its patches'); return
        self.synced_profile = dst
        if dst: say(f'game profile {tid}: copied into dm/games ({dst}), so the rewriter applies its patches')

    def drop_profile(self):
        """The copy of the imported profile goes when the port is done: dm/games holds the tree's own profiles only"""
        dst = getattr(self, 'synced_profile', None)
        if not dst: return
        self.synced_profile = None
        nsp.rmtree(dst)

    def glslc_host(self):
        """The headless host with null graphics (dm/android/gfx_null.c): the game's own modules and the game's own compiler, run without a window"""
        out = self.aw / ('host-glslc-debug' if self.o.debug else 'host-glslc')
        PROG.set(step='building the headless host')
        nsp.run(self.build_cmd(out, ['--exe', '--gfx', 'null']) + ([] if self.o.debug else ['--release']),
                self.logs / 'android_glslc_host.log', env=self.env)
        return out / 'dmhost'

    def build_cmd(self, out, extra):
        """build.py's command line: --os linux on the launcher's line (the machine's own compiler, no NDK), the NDK's clang on Android"""
        cmd = [PY, DM / 'android/build.py', '--game', self.g.id, '--out', out, '--jobs', str(self.o.jobs)]
        if on_linux():
            cmd += ['--os', 'linux']
            if '--gfx' not in extra: cmd += ['--gfx', 'null']   # the headless line: the tools' hosts (the shader capture, the Oodle decoder); the real host passes --gfx itself
            return cmd + extra
        return cmd + ['--ndk', str(self.tools['ndk'])] + extra

    def glslc_capture(self):
        """The run-time shader capture, where the game can boot: the phone app's porter IS the device (the game's own compiler runs here, with no adb and no second device),
        a porter on a desktop pushes the host to the Android device and boots the game there (device_glslc)"""
        if on_android(): return self.local_glslc()
        return self.device_glslc()

    def local_glslc(self):
        """The capture, run here: the phone app's porter IS the device (Android, arm64), so the game's own compiler runs on this machine — no adb, no second device. The host boots
        the game with DM_GLSLC_CAPTURE (dm/host/hle_glslc.c), which writes every output it compiles to a folder the split reads like any other GLSLC source. The outputs are the same on
        every run, so a capture that is already there is reused"""
        want, todo = self.glslc_todo()
        if not todo:
            say('reusing the captured run-time shaders'); return
        PROG.add(1); PROG.stage('GLSLC capture', step='building the headless host')
        dmhost = self.glslc_host()
        d = self.dirs[self.pkg_ver]
        cap, rd, log = d / 'glslc_capture.partial', self.work / 'tmp/glslc_run', self.logs / 'android_glslc.log'
        nsp.rmtree(cap); nsp.rmtree(rd)
        for s in ('save', 'temp'): (rd / s).mkdir(parents=True)
        os.chmod(dmhost, 0o755)   # a file the App unpacked is not executable: the phone's own exec bit
        env = dict(self.env, DM_ROOT=str(rd), DM_ROMFS=str(d / 'RomFS'), DM_SAVE=str(rd / 'save'), DM_TEMP=str(rd / 'temp'), DM_GLSLC_CAPTURE=str(cap))
        env.pop('LD_LIBRARY_PATH', None)   # the guest's glibc libraries are none of the bionic host's business: its own are in /system/lib64
        shmap = self.g.dir / 'shader_map.tsv'
        if shmap.is_file(): env['DM_NVN_SHMAP'] = str(shmap)
        say(f"booting {self.app_name} here to capture the shaders it compiles at run time (up to {self.GLSLC_SECS} s)")
        t0 = time.time()
        with open(log, 'w') as f:
            p = subprocess.Popen([str(dmhost), str(self.patched)], env=env, stdout=f, stderr=subprocess.STDOUT)
            try:
                while p.poll() is None and time.time() - t0 < self.GLSLC_SECS:
                    got = nsp.glslc_done(cap)
                    if want and got >= want: break
                    time.sleep(0.25)
            finally:
                if p.poll() is None:   # the host's graceful exit (SIGTERM), a kill 5 s later
                    p.terminate()
                    try: p.wait(5)
                    except subprocess.TimeoutExpired: p.kill(); p.wait()
        got = nsp.glslc_done(cap)
        if not got or (want and not got >= want):
            tail = ''.join(collections.deque(open(log, errors='replace'), maxlen=30)).rstrip('\n')
            PROG.end(ok=False)
            raise BuildError(f'captured only {len(got)} run-time shaders' + (f', the profile needs {len(want)}' if want else '') + f' (host output: {log})\n{tail}')
        dst = d / 'glslc_capture'
        old = d / 'glslc_capture.old'
        nsp.rmtree(old)
        if dst.exists(): dst.rename(old)
        cap.rename(dst); nsp.rmtree(old)
        PROG.end(f'{len(got)} run-time shader outputs in {time.time() - t0:.0f} s')

    def oodle_host(self):
        """The host built as a tool (build.py --exe): the game's own modules and the game's own OodleLZ_Decompress, run without a window. It lands in the host stage's own
        folder, so its objects serve both → the executable"""
        out = self.aw / ('host-debug' if self.o.debug else 'host')   # the host stage's own folder: its objects serve both
        PROG.set(step="building the host as a tool for the game's Oodle decoder")
        nsp.run(self.build_cmd(out, ['--exe']) + ([] if self.o.debug else ['--release'])
               ,
                self.logs / 'android_oodle_host.log', env=self.env)
        return out / 'dmhost'

    def oodle_job(self, job, out, bnsh=False):
        """One Oodle job file (hle_oodle.c: "DMOJ" records) decoded into out ("DMOR"); the job file is removed. On the device the host runs as an executable and the rewritten
        modules go there once a port (device_oodle_end removes them); here it runs on this machine (the phone app's porter IS the device).
        bnsh: only the entries that hold a BNSH shader come back (DM_OODLE_JOB_BNSH)"""
        if getattr(self, 'oodle_local', False): return self.local_oodle_job(job, out, bnsh)
        return self.device_oodle_job(job, out, bnsh)

    def local_oodle_job(self, job, out, bnsh=False):
        """The same job, decoded here: the phone app's porter IS the device (Android, arm64), so the game's own code runs on this machine — no adb, no second device. The host
        built as an executable (build.py --exe) takes the job file and the rewritten modules, decodes with the game's own OodleLZ_Decompress (the same ARM64 code the Switch
        runs) and writes the answer beside the job file → out"""
        dmhost = getattr(self, 'oodle_host_path', None)
        if not dmhost:
            dmhost = self.oodle_host(); self.oodle_host_path = dmhost
        os.chmod(dmhost, 0o755)   # a file the App unpacked is not executable: the phone's own exec bit
        env = dict(self.env, DM_OODLE_JOB=str(job))
        if bnsh: env['DM_OODLE_JOB_BNSH'] = '1'
        env.pop('LD_LIBRARY_PATH', None)   # the guest's glibc libraries are none of the bionic host's business: its own are in /system/lib64
        try:
            r = subprocess.run([str(dmhost), str(self.patched)], env=env, capture_output=True, text=True, errors='replace', timeout=3600)
        except subprocess.TimeoutExpired:
            raise BuildError(f"the game's Oodle decoder took more than an hour and was stopped (see {self.logs / 'android_oodle_job.log'})")
        (self.logs / 'android_oodle_job.log').write_text((r.stdout or '') + (r.stderr or ''), encoding='utf-8')
        if r.returncode != 0: raise BuildError(f"the game's Oodle decoder failed (see {self.logs / 'android_oodle_job.log'})")
        answer = job.with_name(job.name + '.out')   # the host writes the answer beside the job file
        if not answer.is_file(): raise BuildError(f"the game's Oodle decoder wrote no answer (see {self.logs / 'android_oodle_job.log'})")
        shutil.move(str(answer), str(out))
        nsp.rmtree(job)   # the job file is up to 4.4 GB: the phone has no room to keep it

    def theme_files(self):
        """The theme's files ({name in the pack: source}, overlay/ of the pack), or None without them. The APK carries them as assets/overlay/
        (theme()); the player's app has no APK assets, and its pack carries them as plain files (overlay_theme.c falls back to the pack)"""
        pack = android_profile.theme(self.g.id)
        files = [pack / 'theme.tsv'] + [pack / f'{lay}.png' for lay in android_profile.LAYOUTS]
        if missing := [f.name for f in files if not f.is_file()]:
            say(f'[RED] the gamepad theme {pack.name} has no {", ".join(missing)}: the app draws its gamepad without a theme'); return None
        return {f'overlay/{f.name}': f for f in files}

    def icon_png(self):   # the game's icon as a plain 256 px PNG (the app's data pack carries it); None without Pillow or an icon
        self.icon()   # it writes the plain PNG (and the adaptive icon's layers)
        p = self.aw / 'icon.png'
        return p if p.is_file() else None

    def drivers(self):
        """The Vulkan drivers the APK carries: --vulkan-driver first, then the folder's (the launcher's list)"""
        out = [self.o.vulkan_driver] if self.o.vulkan_driver else []
        if self.o.vulkan_driver_dir:
            out += sorted(f for f in self.o.vulkan_driver_dir.glob('*.so') if f.is_file())
        return out

    def loader_libs(self):
        """The hooks the data pack carries: the loader itself is the app's own (its native library folder, where the
        linker finds it by name), the hooks travel with the host (the host hands the loader the folder it sits in, and
        the loader looks the hooks up there). A pack with no driver of its own still carries them: the player may
        install one in the app and pick it for this game"""
        pre = [p for p in prebuilt_loader() if p.name in ADRENOTOOLS_HOOKS]
        if pre: return pre
        return [self.so.parent / n for n in ADRENOTOOLS_HOOKS]

    def loader_so(self):
        """The loader itself, for the per-game APK: its own lib folder is where the linker finds it by name"""
        pre = [p for p in prebuilt_loader() if p.name == ADRENOTOOLS_LOADER]
        if pre: return pre
        f = self.so.parent / ADRENOTOOLS_LOADER
        return [f] if f.is_file() else []

    def pack_dir_root(self):
        """The folder that will hold the data pack. The app may put it on the removable card (NX2A_PACK_DIR);
        without it the pack goes beside the build folders, on the phone's own storage"""
        given = os.environ.get('NX2A_PACK_DIR', '').strip()
        if given: return Path(given).expanduser()
        return self.work_root.parent / 'ports'

    def data_dir(self):
        """Where the data pack goes (and where the game reads its files from): the pack's own name in the output folder.
        The app's mode: the pack goes to the app's own folder, beside the build folders (the same volume, so the pack is written next to the build's files).
        The shared storage cannot hard link them (another volume), so a pack there is a copy of the whole game: minutes, and it breaks.
        The app may put the pack on the removable card (NX2A_PACK_DIR): there it is a copy all the same (Android's SELinux never lets an app link),
        and the build's own folder stays on the phone's storage, where the programs that run during the build can live"""
        stem = f'{app_stem(self.g, self.app_name)}-data'
        if self.o.app: return self.pack_dir_root() / stem
        return self.o.out / stem

    def lists(self):
        """The launcher's lists: the languages the game supports (languages.txt) and the drivers the APK carries (drivers.txt).
        The device's own driver is the first choice: a driver in the folder is only used when the player picks it (the page)"""
        langs = []
        for code in self.languages:
            name = next((n for c, n in nacp.LANGUAGES if c == code), '')
            langs.append(f'{code}\t{name}')
        return {'languages.txt': '\n'.join(langs) + ('\n' if langs else ''),
                'drivers.txt': ''.join(f'{d.name}\n' for d in self.drivers())}

    def shared_font(self):
        """The font the game's shared font is: the player's own (--shared-font) or the one the tools ship
        (dm/tools/shared_cjk.ttf: the Latin base with the CJK glyphs merged in, the shape a game that parses the
        shared font expects, dm/tools/cjk_font.py builds it). The host has none of the console's own fonts, and
        the system's Latin one has no CJK glyphs, so a game in Chinese drew its menus as "?" (dm/host/hle_sdk16.c).
        The app's mode points at the shipped font where it lies (the payload), so the pack does not carry it and
        the path does not change when the pack moves; the desktop's mode puts it in the pack, which the install
        copies into the app's files folder on the device.
        Returns (env.txt rows, pack files); none without a font"""
        if self.o.shared_font:   # the player's own font: it goes in the pack, the install puts it where the host reads it
            dest = self.data_dir() if self.o.app else datapack.files_folder(self.package)
            return [f'DM_SHARED_FONT={dest}/standard.ttf'], {'standard.ttf': self.o.shared_font}
        if not SHARED_CJK.is_file():
            say('[RED] the shared font is missing (dm/tools/shared_cjk.ttf): the game\'s Chinese text will draw as "?"')
            return [], {}
        if self.o.app: return [f'DM_SHARED_FONT={SHARED_CJK}'], {}
        dest = datapack.files_folder(self.package)
        return [f'DM_SHARED_FONT={dest}/standard.ttf'], {'standard.ttf': SHARED_CJK}

    def _run(self):
        o = self.o
        expected = os.environ.get('NX2A_PLAYER_API_REVISION')
        if expected is not None and expected != str(PLAYER_API_REVISION):
            raise BuildError('The porting environment does not match this app. Refresh the environment before porting.')
        o.folder = Path(o.folder).expanduser().resolve()
        o.game = None
        if o.folder.is_file():    # the game file that was picked: its folder holds the updates and the DLC
            o.game = o.folder
            o.folder = o.folder.parent
        if not o.folder.is_dir(): raise BuildError(f'not a folder: {o.folder}')
        version_code('v0', o.vercode_offset); alias_headroom_gb(o.alias_headroom)   # an offset or headroom out of range fails now, not after the shaders
        self.driver_system = str(o.vulkan_driver) == 'system'   # --vulkan-driver system: the device's driver even when the profile asks for Turnip
        if self.driver_system: o.vulkan_driver = None
        if o.vulkan_driver:
            o.vulkan_driver = Path(o.vulkan_driver).expanduser().resolve()
            if not o.vulkan_driver.is_file() or o.vulkan_driver.suffix != '.so': raise BuildError(f'--vulkan-driver: not a .so library: {o.vulkan_driver}')
        if o.vulkan_driver_dir:
            o.vulkan_driver_dir = Path(o.vulkan_driver_dir).expanduser().resolve()
            if not o.vulkan_driver_dir.is_dir(): raise BuildError(f'--vulkan-driver-dir: not a folder: {o.vulkan_driver_dir}')
            if not self.drivers(): raise BuildError(f'--vulkan-driver-dir: no .so library in {o.vulkan_driver_dir}')
        if o.shared_font:
            o.shared_font = Path(o.shared_font).expanduser().resolve()
            if not o.shared_font.is_file() or o.shared_font.suffix.lower() != '.ttf': raise BuildError(f'--shared-font: not a .ttf font: {o.shared_font}')
        if fw := o.firmware or self.cfg.get('firmware'):
            o.firmware = Path(fw).expanduser().resolve()
            if not o.firmware.is_dir(): raise BuildError(f'--firmware: not a folder: {o.firmware}')
        keys = o.keys or self.cfg.get('keys')
        if not keys: raise BuildError('no prod.keys: give -k / --keys, or set it once with `porter config keys <path>`')
        o.keys = Path(keys).expanduser().resolve()
        try: self.tools = toolchain.require(self.cfg, str(o.keys), adb=o.install)
        except toolchain.ToolError as e: raise BuildError(str(e)) from e
        o.out = Path(o.out or self.cfg.get('out') or o.folder).expanduser().resolve()
        # the chosen dotnet first on PATH, in this process too: Windows finds a program by the parent's PATH, not the one passed to the child (upstream runs `dotnet` by name)
        os.environ['PATH'] = os.pathsep.join([str(self.tools['dotnet'].parent), os.environ.get('PATH', '')])
        os.environ['DOTNET_ROOT'] = str(toolchain.dotnet_root(self.tools['dotnet']))   # where nx_extract.exe's apphost looks for the runtime (else the system's, which may lack .NET 10)
        # PYTHONUTF8: the engine's tools write their tables with open() and no encoding, which is the ANSI code page on Windows (shader_split.py's "→" failed)
        self.env = dict(os.environ, J=str(o.jobs), PYTHONIOENCODING='utf-8', PYTHONUTF8='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
        # The build tools' own libraries (the toolchain's libshaderc for glslc): the tools are run with the environment the
        # guest has, whose library path holds the rootfs's libraries only, and the tools' own RPATH may point elsewhere
        for lib in toolchain.toolchain_lib_dirs():
            self.env['LD_LIBRARY_PATH'] = os.pathsep.join([str(lib), self.env.get('LD_LIBRARY_PATH', '')]).rstrip(os.pathsep)
            break

        try:
            try:
                self.inputs()
                PROG.plan(1 + len(self.versions) + bool(self.fam['dlc']) + bool(o.firmware and self.ap.sysdata) + bool(o.fps60) + (5 if o.app else 6) + bool(o.install))   # nx_extract, the versions, the DLC, the system data, 60 fps, rewrite / split / Vulkan shaders / host / data (the app's mode makes no APK), install (unpack adds its own)
                self.extract()
            finally: self.drop_unpacked()   # a failed run leaves no decompressed dumps behind either
            self.check_graphics()
            self.fps_unlock()
            self.rewrite()
            # captures are pulled whatever --install says: the app reads its own files folder, a PC pulls them over adb
            self.pull_captures()
            self.shaders()
            self.host()
            self.apk()
            self.data()
            if o.install: self.install()
            nsp.rmtree(self.work / 'tmp')
            self.result.update(title_id=self.g.id, name=self.app_name, package=self.package, version=self.pkg_ver, display=self.display, language=self.lang,
                               status=self.ap.status, derived=bool(self.derived), installed=bool(o.install))
            say(f'done: {self.result.get("apk", "no APK (the app runs it)") + ", " if "apk" in self.result else ""}{self.result["data"]}')
            if self.derived: say(f'[RED] {self.derived}: the port is built from a derived profile and may not run as the profile\'s tested version does'
                                 + (f'; {self.derived_mem}' if self.derived_mem else ''))
            for x in self.lost: say(f'[RED] {x}')
            return self.result
        finally: self.drop_profile()   # the copy of the imported profile goes when the port is done

    def inputs(self):
        o = self.o
        say(f'game folder: {o.folder}' + (f' (game: {o.game.name})' if o.game else ''))
        self.app, self.fam = nsp.scan_nsps(o.folder, dumps.EXTS, o.keys, o.game)
        tid = f'{self.app:016X}'
        self.sync_profile(tid)   # the player's imported profile into dm/games, before the profile is read (a copy of an older import would hide the newer one)
        # the build folder: where the port's own programs run and where the game is unpacked. On a phone it
        # cannot be next to the game (Android does not let an app run a program on the shared storage), so
        # NX2A_WORK points at the app's own folder.
        root = Path(os.environ.get('NX2A_WORK', '')).expanduser() if os.environ.get('NX2A_WORK') else o.folder
        self.work_root = root
        self.work = root / f'{tid}_build'
        g, ap = profiles.by_title(self.app)
        self.provisional = False
        self.check_space()      # before the survey, which unpacks the game
        if not (g and ap):
            what = f'no game profile for {tid}' if not g else f'{g.get("name", g.id)} ({g.id}) has a game profile but is not ported to Android yet (no android.tsv in {g.dir})'
            if not o.experimental: raise BuildError(f'{what}: --experimental tries it anyway (profiles: `porter profiles`)')
            g, ap = self.experimental_profile(g, tid)
        self.g, self.ap = g, ap
        self.package = o.package or ap.package
        if not re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+', self.package): raise BuildError(f'not a package name: {self.package}')
        say(f'game profile: {g.id} {g.get("name", "")} (Android: {ap.status}' + (f', tested on {ap.tested}' if ap.tested else '') + ')')
        if ap.vulkan_driver == 'turnip' and not o.vulkan_driver and not self.driver_system:   # android.tsv vulkan_driver turnip: the driver the profile was tested with
            lib = toolchain.find_turnip(self.cfg)
            if lib: o.vulkan_driver = lib.resolve(); say(f"the profile asks for Mesa's Turnip driver (vulkan_driver turnip): {lib} is packed (--vulkan-driver system: the device's driver)")
            else: say("[RED] the profile asks for Mesa's Turnip driver (vulkan_driver turnip), and none was found: the device's own driver is used. "
                      "Give one with --vulkan-driver <libvulkan_freedreno.so>, or porter config turnip <path>")
        builds, need = g.builds(), g.words('shader_versions')
        have = nsp.nsp_versions(self.fam, builds)
        self.derived, self.derived_mem, self.lost = '', '', []
        if self.provisional:   # the version the survey saw
            self.pkg_ver = o.version or g.get('package')
            if self.pkg_ver not in builds: raise BuildError(f'the version to pack must be one the provisional profile registers: {", ".join(builds)}')
        else:
            self.pkg_ver = o.version or max(have, key=nsp.vnum)
            if self.pkg_ver not in have: raise BuildError(f'the version to pack ({self.pkg_ver}) is not in the folder, which holds {", ".join(sorted(have, key=nsp.vnum))}')
            if self.pkg_ver not in builds: self.derived = f'{self.pkg_ver} is not a version game profile {g.id} registers ({", ".join(f"{v} {b["display"]}" for v, b in builds.items())})'
            elif not all(v in have for v in need): self.derived = f'the folder has no {", ".join(v for v in need if v not in have)}, whose files the profile\'s shader tables were made from'
            if self.derived: say(f'{self.derived}: packing {self.pkg_ver} from a profile derived from it')
        self.versions = [self.pkg_ver] if self.derived else need + ([self.pkg_ver] if self.pkg_ver not in need else [])
        self.have = have
        self.aw = self.work / 'android'; self.logs = self.work / 'logs'
        for d in (self.aw, self.logs, self.work / 'tmp'): d.mkdir(parents=True, exist_ok=True)
        # DM_GAME picks the profile for every tool; WORK keeps their temporary folders inside the build folder (the shader translator writes thousands of files)
        self.env.update(DM_GAME=g.id, DM_ROOT=str(self.work), WORK=str(self.work / 'tmp'))

    def check_space(self):
        """Stop before extracting when the game folder's drive cannot hold the port: a build folder takes about 1 to 2 times the game files (NEO 7.0 GB of 6.8,
        Viractal 2.7 of 1.4), less what an earlier port left there, plus a margin; an NSZ / XCZ counts as decompressed, and once more for its NSP while it is extracted.
        Only the picked game's files count (its base, its updates, its DLC): the folder may hold other games, which this port never reads.
        The pack is a copy of the game's files (Android's SELinux never lets an app link), so the port needs room for the build's files and for the pack.
        The app's mode copies no RomFS into the pack (the pack points at the build folder's own), so there the build's files are the only copy and the room is half.
        When the pack goes to another volume (the app may put it on the removable card), each volume is asked for its own share"""
        fam = self.fam
        files = list(dict.fromkeys([fam['base'], *[p for _, p in fam['updates']], *[p for _, _, p in fam['dlc']]]))   # a merged dump is one file in several places: it counts once
        game, temp = sum(dumps.size(f) for f in files), sum(dumps.size(f) for f in files if dumps.compressed(f))
        dlc = sum(dumps.size(p) for _, _, p in fam['dlc'])
        built = sum(f.stat().st_size for f in self.work.rglob('*') if f.is_file()) if self.work.is_dir() else 0
        # the work folder may not be there yet: the space is the one of the folder that will hold it
        where = self.work
        while not where.exists() and where.parent != where: where = where.parent
        margin = 2**30
        copies = 1 if self.o.app else 2   # the app's pack holds no RomFS (it points at the build folder's own): one copy of the game's files, not two
        pack = None
        getter = getattr(self, 'pack_dir_root', None)   # the space check runs before the profile is known
        if getter is not None:
            try: pack = getter()
            except Exception: pack = None
        if pack is not None and volume_of(pack) not in (None, volume_of(where)):
            # the pack goes to another volume (the removable card): the build's files stay here, the pack's copy goes there
            need, free = max(0, game + temp - built) + margin, shutil.disk_usage(where).free
            if free < need: raise BuildError(f'not enough disk space on {where.anchor} for the build folder: the port needs about {need / 2**30:.1f} GB more, {free / 2**30:.1f} GB is free')
            need, free = (dlc if self.o.app else game) + margin, shutil.disk_usage(pack).free
            if free < need: raise BuildError(f'not enough disk space for the data pack in {pack}: the port needs about {need / 2**30:.1f} GB more, {free / 2**30:.1f} GB is free')
            return
        need, free = max(0, copies * game + temp - built) + margin, shutil.disk_usage(where).free
        if free < need: raise BuildError(f'not enough disk space on {where.anchor}: the port needs about {need / 2**30:.1f} GB more, {free / 2**30:.1f} GB is free')

    def experimental_profile(self, g, tid):
        """A profile for a game not ported to Android, in <build folder>/profile/<id>/ (outside the repository): upstream's survey and provisional profile when the game has
        none (scripts/build_ipa_from_nsp.py survey / write_profile, dm/games/profile_guess.py), or a copy of its iOS profile; plus an android.tsv with status experimental.
        A game brought up this way gets its profile into dm/games by hand (docs/ARCHITECTURE.md "Adding a game")"""
        pdir = self.work / 'profile'; d = pdir / tid
        if g is None:
            if (d / 'game.tsv').is_file():
                nsp.require_64bit(self.o.folder / f'{tid}_survey/extract/ExeFS', f'{tid}')   # a provisional profile an older porter wrote for a 32-bit game (issue #161)
                say(f'no game profile for {tid}: reusing the provisional profile from the last run ({d}; delete it to survey again)')
            else:
                ups = [p for _, p in sorted(self.fam['updates'], key=lambda u: u[0] or 0)[-1:]]   # the survey reads the base game and the newest update
                m = self.unpack([self.fam['base'], *ups])
                fam = dict(self.fam, base=m[self.fam['base']], updates=[(v, m.get(p, p)) for v, p in self.fam['updates']])
                # the survey's scratch is in the port's own folder: the shared storage cannot run programs
                facts = nsp.survey(self.o.folder, self.app, fam, self.o.keys, NXNATIVE, PY, self.env, work_root=self.work)
                facts['survey'] = str(self.work / f'{tid}_survey/survey.md')
                nsp.write_profile(d, self.app, facts)
            self.provisional = True
            say('[RED] provisional game profile: values guessed from the survey, the game may not start')
        elif not (d / 'game.tsv').is_file() or (g.dir / 'game.tsv').stat().st_mtime > (d / 'game.tsv').stat().st_mtime:   # the iOS profile as it is now
            nsp.rmtree(d); shutil.copytree(g.dir, d, ignore=shutil.ignore_patterns('patches.py', '__pycache__'))   # patches.py stays in dm/games, where patch_nso.py finds it (the imported profile's copy is there: sync_profile)
        if not (d / 'android.tsv').is_file():
            (d / 'android.tsv').write_text(f'# Written by porter for an experimental port: the game has not been brought up on Android\nstatus\texperimental\n'
                                          f'package\torg.nx2a.t{tid.lower()}\norientation\tlandscape\n', encoding='utf-8')
        self.use_profile_dir(pdir, first=True)
        g = game.load(tid)
        return g, android_profile.AndroidProfile(g)

    def extract(self):
        o, g = self.o, self.g
        picks = nsp.pick_nsps(self.fam, self.have, self.versions)
        ex = self.work / 'extract'; ex.mkdir(parents=True, exist_ok=True)
        need = sum(dumps.size(p) * (2 if dumps.compressed(p) else 1) for p in {p for b, u in picks.values() for p in (b, u) if p}) / 2**30 + 6
        if nsp.free_gb(self.work) < need and not all((ex / v).exists() for v in self.versions): raise BuildError(f'less than {need:.0f} GB free on the volume of {self.work}')
        # NSZ / XCZ: only what a stage will read is decompressed, all in one stage before nx_extract runs (a version nsp.extract reuses reads nothing)
        fresh = lambda v: (ex / v / 'ExeFS/main').exists() and (ex / v / 'RomFS' / g.get('romfs_marker')).exists()   # nsp.extract's reuse test
        zdlc = [p for _, _, p in self.fam['dlc'] if dumps.compressed(p)]
        # extract_aoc keys its reuse on the names, sizes and times of the NSPs it reads, decompressed ones here: with NSZ / XCZ DLC, porter keys it on those files instead
        dkey = nsp.fingerprint(sorted((t, p.name, p.stat().st_size, p.stat().st_mtime_ns) for t, _, p in self.fam['dlc']),
                               ('files', [NXNATIVE / 'dm/tools/nx_extract' / f for f in ('Program.cs', 'nx_extract.csproj')]))
        dkf = self.work / 'aoc.dumps.key'
        dlc_reused = bool(zdlc) and (self.work / 'aoc').is_dir() and nsp.reused(dkf, dkey) is not None
        m = self.unpack([p for v in self.versions if not fresh(v) for p in picks[v] if p] + ([] if dlc_reused else zdlc)
                        + ([self.fam['base']] if not dlc_reused and self.fam['base'] in zdlc else []))   # the merged dump is its DLC's source: extract_aoc compares its paths against the base's, so the base is decompressed too — even when every version's extraction is reused
        picks = {v: tuple(m.get(p, p) if p else None for p in bu) for v, bu in picks.items()}
        PROG.stage('build nx_extract')
        nx = nsp.build_nx_extract(NXNATIVE, self.work, self.logs, self.env)
        PROG.end()
        self.dirs = {ver: nsp.extract(nx, o.keys, ex, ver, *picks[ver], None, self.logs, g) for ver in self.versions}
        for d in self.dirs.values(): nsp.require_64bit(d / 'ExeFS', f'{g.get("name", g.id)} ({g.id})')
        bad = [] if self.derived else [f'{v}: {x}' for v in self.versions for x in nsp.build_mismatch(self.dirs[v], v, g)]
        if bad and self.provisional: raise BuildError(f'not the builds the provisional profile registers: {"; ".join(bad)}')
        if bad:
            self.derived = f'not the builds game profile {g.id} registers: {"; ".join(bad)}'
            say(f'{self.derived}: packing {self.pkg_ver} from a profile derived from it')
            self.versions, self.dirs = [self.pkg_ver], {self.pkg_ver: self.dirs[self.pkg_ver]}
        self.game = self.dirs[self.pkg_ver]
        nsp.rmtree(self.work / 'profile-mem')   # an earlier run's --alias-headroom copy (mem_profile)
        if self.derived:   # the derived profile (android.tsv included) goes into the build folder, and every tool takes it first
            pdir = self.work / 'profile-derived'   # not profile/: an experimental port's copy there is the profile it derives from
            disp = nsp.derive_profile(g, pdir / g.id, self.pkg_ver, self.game, g.words('modules'))
            # automatic headroom only for another build: a registered one, derived because the folder lacks a shader version, keeps the layout it was tested with
            other = self.pkg_ver not in g.builds() or bool(nsp.build_mismatch(self.game, self.pkg_ver, g))
            gb = self.o.alias_headroom if self.o.alias_headroom is not None else (ALIAS_HEADROOM >> 30 if other else 0)
            if grown := alias_headroom(pdir / g.id / 'game.tsv', gb):
                self.derived_mem = f'its alias region has {gb} GB of headroom over the tested build\'s (mem_alias {grown[0]:#x} → {grown[1]:#x}); {ALIAS_HINT}'
                say(f'derived game profile: {self.derived_mem}' + ('' if self.o.alias_headroom is None else ' (--alias-headroom)'))
            self.use_profile_dir(pdir, first=True)
            self.g = game.load(g.id); self.ap = android_profile.AndroidProfile(self.g)
            say(f'derived game profile for {self.pkg_ver} ({disp}): {self.g.dir}')
            self.lost = lost_patches(g.builds(), self.game / 'ExeFS', g.words('modules'))
            for x in self.lost:
                say(f'[RED] {x}: the port may fail where they are needed; register them for this build (dm/tools/nso_fnmap.py carries addresses over) or port a version the '
                    f'profile registers')
        else: self.mem_profile()
        if dlc_reused:
            PROG.stage('extract DLC'); self.aoc = self.work / 'aoc'; PROG.end(f'{len(self.fam["dlc"])} DLC, reused (inputs unchanged)')
        else:
            self.aoc = nsp.extract_aoc(nx, o.keys, NXNATIVE, self.work, self.app,
                                       dict(self.fam, base=m.get(self.fam['base'], self.fam['base']),   # with compressed DLC, extract_aoc tells a merged dump from a DLC NSP by comparing its paths against the base's: hand it the decompressed ones
                                           dlc=[(t, v, m.get(p, p)) for t, v, p in self.fam['dlc']]), self.logs)
            if zdlc: dkf.write_text(f'{dkey}\n')
            else: nsp.rmtree(dkf)
        self.sysdata = self.extract_sysdata(nx)
        self.drop_unpacked()   # everything that reads them has run, and the shader stages that follow need the room
        self.base = next((self.dirs[v] for v in self.versions if picks[v][1] is None), self.dirs[self.versions[0]])
        self.app_name = o.app_name or nacp.name(self.base / 'control.nacp') or self.g.get('name', self.g.id)
        self.display = nacp.version(self.game / 'control.nacp') or nacp.version(self.base / 'control.nacp') or '1.0'
        lang_in = o.language or self.cfg.get('language')
        self.languages = nacp.languages(self.game / 'control.nacp') or nacp.languages(self.base / 'control.nacp')
        if lang_in and lang_in.strip().lower() == 'system':
            self.lang = 'system'   # the pack lists the game's languages (DM_LANG_SUPPORTED) and the front picks one at launch (the device's locale)
        else:
            want = nsp.language_code(lang_in) if lang_in else 'en-US'
            if not want: raise BuildError(f'unknown game language {lang_in!r}')
            self.lang = nsp.game_language(want, bool(lang_in), self.languages)
        say(f'app: {self.app_name} {self.display} ({self.package}), game language {self.lang}')

    def mem_profile(self):
        """The player's --alias-headroom on a version the profile was brought up on (or a provisional or experimental profile): a copy of the profile in
        <build folder>/profile-mem/ with the bigger guest block, which every tool takes first. patches.py stays in dm/games, where patch_nso.py finds it (the imported
        profile's copy is there: sync_profile). extract() removes
        an earlier run's copy before it, so the build folder keeps none without the option"""
        pdir = self.work / 'profile-mem'
        if not self.o.alias_headroom: return
        d = pdir / self.g.id; shutil.copytree(self.g.dir, d, ignore=shutil.ignore_patterns('patches.py', '__pycache__'))
        grown = alias_headroom(d / 'game.tsv', self.o.alias_headroom)
        if not grown:
            nsp.rmtree(pdir); say(f'--alias-headroom {self.o.alias_headroom}: {self.g.get("name", self.g.id)} declares no virtual address memory (sys_resource): its layout stays as it is'); return
        self.use_profile_dir(pdir, first=True)
        self.g = game.load(self.g.id); self.ap = android_profile.AndroidProfile(self.g)
        say(f'alias region: mem_alias {grown[0]:#x} → {grown[1]:#x} (+{self.o.alias_headroom} GB, --alias-headroom): {self.g.dir}')

    def check_graphics(self):
        """Check graphics support and device requirements for shader preparation before rewriting or compiling."""
        src = profile_guess.build_sources(self.game / 'ExeFS', self.game / 'RomFS', self.g.words('modules'))
        gfx = src['graphics'][0]
        # OpenGL ES: the device's own GL driver runs it (dm/android/gl_android.c); no shaders to translate, the game compiles its GLSL ES at run time
        self.gl = gfx == 'gl'
        if self.gl: say(f"{self.app_name} renders with OpenGL ({src['graphics'][1]}): the Android host hands its GL calls to the device's OpenGL ES driver"); return
        if gfx != 'nvn': raise BuildError(f'{self.app_name} renders with {gfx} ({src["graphics"][1]}): the Android host replays NVN or OpenGL ES only so far')
        # Game Freak's GFPAKs and Trinity packs with Oodle entries: decoded by the game's own decoder on the Android device (device_oodle), or on this machine when the porter
        # runs on the phone app (local_oodle); PKZ packs still need the Mac host
        self.oodle_why = src['oodle_packs'][1] if src['oodle_packs'][0] and ('GFPAK' in src['oodle_packs'][1] or 'Trinity' in src['oodle_packs'][1]) else ''
        # Unreal paks (version 11) and IoStore containers: their shader code archives are decoded with the game's own Oodle too (device_ue)
        self.ue_why = src['ue_decode'][1] if src['ue_decode'][0] else ''
        # Legacy Unreal paks with LZ5 blocks (DRAGON QUEST XI S): the files decoded by the game's own LZ5 on the device (device_ue_legacy), for a profile that opts in (ue_legacy_decode device)
        uld = self.g.get('ue_legacy_decode', '')
        if uld not in ('', 'device'): raise BuildError(f'{self.g.id}: ue_legacy_decode must be device or absent: {uld}')
        self.uel_why = src['ue_legacy'][1] if src['ue_legacy'][0] and uld == 'device' else ''
        uel_cached = self.uel_why and all(self.uel_stamp_ok(v) for v in self.versions)
        # Already decoded UE archives need no device: rebuilding an APK's keyboard or host must also work after the player disconnects adb.
        ue_cached = self.ue_why and all((self.dirs[v] / 'ue_shaders/stamp').is_file() and
                                      (self.dirs[v] / 'ue_shaders/stamp').read_text() == nsp.ue_stamp(self.dirs[v]) for v in self.versions)
        why = self.oodle_why or ('' if ue_cached else self.ue_why)
        # The game's own decoder runs the game's own code (it boots the game's modules): the patches the profile registers for the tested build are needed there, and the rewriter applies
        # them by build ID only. A dump of another build runs without them and the decoder crashes in the game's initialization, so the port stops here, before it starts.
        if why and getattr(self, 'lost', None):
            vers = ', '.join(b.get('display', v) for v, b in self.g.builds().items() if 'main' in b)
            raise BuildError(f"{self.app_name}: this dump is not the build the game profile registers, and the game's own decoder (its shaders are Oodle-compressed) needs the patches of "
                             f"the tested build: {'; '.join(self.lost)}. Port the version the profile registers ({vers}), or register the patches for this build "
                             f"(dm/tools/nso_fnmap.py carries the addresses over)")
        self.oodle_run, self.oodle_local, self.oodle_where = None, False, ''
        if why:
            where = oodle_where(self.tools)
            if where == 'local':   # the phone app's porter IS the device: the game's own decoder runs here, with no adb and no second device
                self.oodle_local, self.oodle_where = True, 'here'
            elif where == 'device':
                try: Adb(self.tools['adb'], self.o.device or self.cfg.get('device'), log=say).pick()
                except (AdbError, KeyError) as e: raise BuildError(f"{self.app_name}'s shaders are in Oodle-compressed archives ({why}): the port decodes them with the game's own decoder on "
                                                                   f'the Android device, so connect it (adb) and port again ({e})') from e
                self.oodle_where = 'on the device'
            else:
                raise BuildError(f"{self.app_name}'s shaders are in Oodle-compressed archives ({why}): the port decodes them with the game's own decoder on the Android "
                                 f'device, so it needs adb and the device even without installing. {NO_ADB}; then connect the device (USB debugging on) and port again')
            # The split needs the game's own decoder only for the Oodle entries of GFPAK / Trinity packs. A pure Unreal game's shader code archives are decoded by device_ue (its own
            # rounds), so the split gets no decoder: it would boot the game for a job of zero entries (and crash on a dump whose build the profile does not register).
            self.oodle_run = self.device_oodle if self.oodle_why else None
        # A game that compiles shaders with its own GLSLC at boot (Fire Emblem: Three Houses, Catherine: Full Body): the outputs are in no game file, so the port runs the game's own
        # compiler to get them, the way it runs the game's own decoder for the Oodle entries
        self.glslc_why = src['glslc_capture'][1] if src['glslc_capture'][0] else ''
        # The capture runs only when the profile's shader map still names an output that is not there yet: a complete capture is reused, with no device
        capture_needed = self.glslc_why and self.glslc_todo()[1]
        if capture_needed:
            # The capture runs where the game can boot: the phone app's porter IS the device (the game's own compiler runs here, with no adb and no second device), a porter on a
            # desktop pushes the host to the Android device and boots the game there
            if not on_android():
                if not self.tools.get('adb'):
                    raise BuildError(f"{self.app_name} compiles some shaders at run time ({self.glslc_why}): the port boots the game on the Android device to capture them, so it needs adb "
                                     f'and the device even without installing. {NO_ADB}; then connect the device (USB debugging on) and port again')
                try: Adb(self.tools['adb'], self.o.device or self.cfg.get('device'), log=say).pick()
                except (AdbError, KeyError) as e: raise BuildError(f"{self.app_name} compiles some shaders at run time ({self.glslc_why}): the port boots the game on the Android device to "
                                                                   f'capture them, so connect it (adb) and port again ({e})') from e
        for k in ('ue_legacy',) + (() if self.ue_why else ('ue_decode',)) + (() if self.oodle_why else ('oodle_packs',)):
            if src[k][0]: raise BuildError(f'{self.app_name} needs a step that boots the game in the Mac host ({src[k][1]}), which the Android port cannot run yet')

    def glslc_todo(self):
        """The run-time shader captures this port still needs: the profile's shader map names the capture files it was built from (column 5), a provisional profile names none"""
        want = nsp.glslc_wanted(self.g)
        todo = []
        for v in self.versions:
            got = nsp.glslc_done(self.dirs[v] / 'glslc_capture')
            if not (got >= want if want else got): todo.append(v)
        if todo and todo != [self.pkg_ver]:
            missing = ', '.join(v for v in todo if v != self.pkg_ver)
            raise BuildError(f"the run-time shader capture runs the packed version {self.pkg_ver}'s code; {missing} needs a capture of its own")
        return want, todo

    def device_oodle(self):
        """The game's own Oodle decoder decodes the Oodle entries of the GFPAKs and of the Trinity packs (Pokémon Legends: Arceus, Pokémon Legends: Z-A): on the Android device
        (adb), or on this machine when the porter runs on the phone app (the device is this machine). Every entry goes in one job file (1.6 GB for Pokémon Legends: Arceus,
        4.4 GB for Pokémon Legends: Z-A's 223,018 files), decoded in one run; only the entries that hold a BNSH shader come back (DM_OODLE_JOB_BNSH), written as the split's
        decoded folder (shader_split.py gfpak_decoded, trpfs_decoded). Streaming the entries through an adb forward instead reset the connection whenever both directions
        were busy.
        → the split's environment"""
        PROG.set(step="the game's Oodle entries in a job file")
        where = getattr(self, 'oodle_where', '') or 'on the device'
        tmp = self.work / 'tmp/oodle'; nsp.rmtree(tmp); tmp.mkdir(parents=True)
        recs, job = oodle_job([self.dirs[v] / 'RomFS' for v in self.versions], tmp)
        PROG.set(step=f"the game's Oodle decoder {where}: {len(recs):,} entries, {job.stat().st_size / 2**30:.1f} GB")
        self.oodle_job(job, tmp / 'job.out', bnsh=True)
        return {'DM_GFPAK_DECODED': str(oodle_result(tmp, recs, self.oodle_why, where))}

    def device_oodle_job(self, job, out, bnsh=False):
        """The job, decoded on the device: the host as an executable and the rewritten modules go to the device once a port (device_oodle_end removes them)"""
        adb = getattr(self, 'oodle_adb', None)
        if not adb:
            adb = Adb(self.tools['adb'], self.o.device or self.cfg.get('device'), log=say); adb.pick()
            host = self.aw / ('host-debug' if self.o.debug else 'host')   # the host stage's own folder: its objects serve both
            PROG.set(step="building the host as a tool for the game's Oodle decoder")
            nsp.run(self.build_cmd(host, ['--exe']) + ([] if self.o.debug else ['--release']),
                    self.logs / 'android_oodle_host.log', env=self.env)
            adb.shell(f'rm -rf {self.ODEV}; mkdir -p {self.ODEV}/mods', check=False)
            adb.push_file(host / 'dmhost', f'{self.ODEV}/dmhost'); adb.push_tree(self.patched, f'{self.ODEV}/mods')
            self.oodle_adb = adb
        adb.push_file(job, f'{self.ODEV}/job.bin'); nsp.rmtree(job)
        # (the device's timeout ends the decoder before adb gives up, so no decoder is left running and holding memory on the device)
        r = adb.shell(f'chmod 755 {self.ODEV}/dmhost; cd {self.ODEV} && rm -f job.bin.out && DM_OODLE_JOB={self.ODEV}/job.bin{" DM_OODLE_JOB_BNSH=1" if bnsh else ""} timeout 3300 ./dmhost mods '
                      f'> job.log 2>&1; echo "exit $?"; grep -a -e DM_OODLE_JOB -e RED job.log | tail -5', timeout=3600)
        (self.logs / 'android_oodle_job.log').write_text(r, encoding='utf-8')
        if 'exit 0' not in r: raise BuildError(f"the game's Oodle decoder on the device failed (see {self.logs / 'android_oodle_job.log'})")
        adb.run('pull', f'{self.ODEV}/job.bin.out', str(out), timeout=1800)
        adb.shell(f'rm -f {self.ODEV}/job.bin {self.ODEV}/job.bin.out', check=False)

    def device_ue(self):
        """Unreal Engine keeps its shaders in shader code archives that only the game's own Oodle decodes: in its paks (version 11; each shader Oodle-compressed, Octopath Traveler 0), or
        in IoStore containers (Unreal Engine 5.6, FINAL FANTASY RESONANCE: shader libraries whose shader groups are Oodle-compressed as wholes, 5,919 groups in 64 KB container blocks
        that are stored). uepak.job reads both through a decoder it calls one stream at a time; on the Mac that is the host over a pipe (OodleHost), which adb cannot carry (its stdin is
        not binary-safe on Windows, and a forward reset when both directions were busy). Here it runs in rounds instead: uepak.job runs with a decoder that answers from the
        streams decoded so far and notes the others (answering zeros, so a stream that depends on one noted is noted only in a later round, with its real bytes, and a read that
        fails on the zeros ends the round); the noted ones go to the device as one job (oodle_job), and the next round runs. A round that notes nothing has decoded everything;
        its per-shader Oodle job (paks) goes to the device as well, and the decoded archives land in <version dir>/ue_shaders, where the split reads them, with the NSP script's stamp.
        The streams a round decoded are written to <version dir>/ue_streams/<the paks' digest>, one file each, so a run that stops (the phone's memory, the app killed) continues with
        the streams it has and asks the decoder for the rest only"""
        import hashlib
        import struct
        todo = {v: self.dirs[v] for v in self.versions if not ((self.dirs[v] / 'ue_shaders/stamp').exists() and (self.dirs[v] / 'ue_shaders/stamp').read_text() == nsp.ue_stamp(self.dirs[v]))}
        if not todo: return
        PROG.add(1); PROG.stage('UE shader decode', step='the shader code archives')
        tmp = self.work / 'tmp/ue'; total = 0
        for v, d in todo.items():
            jd = tmp / f'job_{v}'
            sdir = d / 'ue_streams' / hashlib.sha1(nsp.ue_stamp(d).encode()).hexdigest()[:16]   # the streams decoded so far, on disk
            sdir.mkdir(parents=True, exist_ok=True)
            for old in (d / 'ue_streams').iterdir():
                if old != sdir: nsp.rmtree(old)   # another pak set's streams are of no use
            for rnd in range(self.UE_ROUNDS):
                want = {}
                def dec(comp, n):
                    k = (hashlib.sha1(comp).digest(), n)
                    f = sdir / f'{k[0].hex()}-{k[1]}'
                    if f.is_file():
                        b = f.read_bytes()
                        if len(b) == n: return b   # decoded in an earlier run
                    want.setdefault(k, bytes(comp)); return bytes(n)
                nsp.rmtree(jd); PROG.set(step=f'{v}: the shader code archives (round {rnd + 1})')
                try: listing, n = uepak.job(str(d / 'RomFS'), str(d / 'ExeFS/main'), str(jd), decode=dec)
                except (ValueError, struct.error, IndexError) as e:
                    if not want: raise BuildError(f'{v}: the Unreal shader code archives do not read: {e}') from e
                if not want: break
                job, out = tmp / 'round.job', tmp / 'round.out'
                with open(job, 'wb') as f:
                    f.write(b'DMOJ' + struct.pack('<I', len(want)))
                    for (_, raw), comp in want.items(): f.write(struct.pack('<II', len(comp), raw) + comp)
                PROG.set(step=f"{v}: {len(want):,} Oodle streams with the game's decoder {self.oodle_where} (round {rnd + 1})")
                self.oodle_job(job, out)
                b = out.read_bytes(); nsp.rmtree(out)
                if b[:4] != b'DMOR' or struct.unpack_from('<I', b, 4)[0] != len(want): raise BuildError("the game's Oodle decoder answered for other streams than it was given")
                o, got = 8, 0
                for k in want:
                    ln = struct.unpack_from('<I', b, o)[0]; o += 4
                    if ln == k[1]: (sdir / f'{k[0].hex()}-{k[1]}').write_bytes(b[o:o + ln]); got += 1   # a stream decoded from zeros fails (0) and is asked for again with its real bytes
                    o += ln if ln != 0xffffffff else 0
                say(f'{v}: round {rnd + 1}: {got:,} of {len(want):,} Oodle streams decoded {self.oodle_where}')
                if not got: raise BuildError(f"{v}: the game's Oodle decoder decoded none of {len(want):,} streams (see {self.logs / 'android_oodle_job.log'})")
            else: raise BuildError(f'{v}: the Unreal shader code archives still need Oodle streams after {self.UE_ROUNDS} rounds')
            if not listing: raise BuildError(f'the RomFS has Unreal paks, but none under {d / "RomFS"} holds a shader code archive: where the shaders are has to be found first')
            if n:   # Oodle-compressed shaders in the paks' archives (Octopath Traveler 0): uepak.job's own job file
                PROG.set(step=f"{v}: {n:,} shaders with the game's decoder {self.oodle_where}")
                self.oodle_job(jd / 'oodle.job', jd / 'oodle.job.out')   # (finish reads job.json and the output only)
            out = d / 'ue_shaders.partial'; nsp.rmtree(out)
            uepak.finish(str(jd), str(out)); (out / 'stamp').write_text(nsp.ue_stamp(d))
            nsp.swap_in(out, d / 'ue_shaders'); nsp.rmtree(jd)
            nsp.rmtree(d / 'ue_streams')   # the decode is done: the streams on disk are of no use
            say(f'{v}: ' + '; '.join(f'{x["name"]} {x["shaders"]:,} shaders' + (f' ({x["compression"]})' if x.get('compression') else '') for x in listing))
            total += n + sum(x['shaders'] for x in listing if x['compression'] == 'IoStore, decoded')
        nsp.rmtree(tmp)
        PROG.end(f'{total:,} shaders decoded {self.oodle_where}')

    def device_oodle_end(self):
        adb = getattr(self, 'oodle_adb', None)
        if adb:
            self.oodle_adb = None
            try: adb.shell(f'rm -rf {self.ODEV}', check=False)
            except AdbError as e: say(f'the Oodle decoder left on the device ({e}): {self.ODEV}')
        if getattr(self, 'oodle_local', False): nsp.rmtree(self.work / 'tmp/oodle')

    def translation_workers(self):
        """The translation processes to run: as many as the device's free memory affords, capped by --jobs and by the low-memory mode.
        The memory is read again when the workers start: the split in front of them may have taken some.
        No room at all (0) raises: the stage stops with a clear error instead of being killed by the system"""
        avail = memory.available_mb()
        n = memory.jobs(avail, os.cpu_count() or 8, forced=self.o.low_mem)
        if self.o.jobs > 0: n = min(n, self.o.jobs)   # --jobs (a maintenance knob) still caps it
        if n <= 0:
            raise BuildError(f'the device has only {avail:.0f} MB of memory free: the shader translation has no room to run; close the other apps and start it again')
        return n, avail

    def shaders(self):
        if getattr(self, 'gl', False):   # an OpenGL ES game: the driver compiles its shaders on the device
            self.dmsv = None
            for st in ('shader split', 'Vulkan shaders'): PROG.stage(st); PROG.end('none: the game renders with OpenGL ES')
            return
        self.translation_workers()   # no room to translate: say so now, not after the long split
        sv = self.versions
        pkg = self.work / 'shader' / 'pkg'
        try:
            if getattr(self, 'glslc_why', ''): self.glslc_capture()   # shaders the game compiles at boot with its own GLSLC: the game's own compiler, here on the phone app or on the device
            if getattr(self, "ue_why", ""): self.device_ue()   # Unreal's shader code archives, decoded with the game's own Oodle (on the device, or here on the phone app) into <version dir>/ue_shaders before the split reads them
            nsp.split_shaders(PY, NXNATIVE, [self.dirs[v] / 'RomFS' for v in sv], [self.dirs[v] / 'ExeFS/main' for v in sv], pkg, self.env, self.logs, self.g, bool(self.derived or self.provisional),
                               oodle=getattr(self, 'oodle_run', None),   # Oodle-compressed archives: the game's own decoder (on the device, or here on the phone app)
                               aoc=self.aoc)   # DLC with shaders of its own (Xenoblade Chronicles 3's archives)
        finally: self.device_oodle_end()
        self.dmsv = self.aw / 'shaders.dmsv'; kf = self.aw / 'shaders.dmsv.key'; cap = self.aw / 'captured_shaders'
        PROG.stage('Vulkan shaders', step='building the translator')
        xlate, xkey = self.translator()
        PROG.set(step='checking the inputs')
        def input_key():
            # The translator's own inputs, found by following its imports (the bundle's readers are none of
            # them): a change to the split's readers must not cost a port the whole translation again.
            # The three helpers the export runs are named as well, so the key follows the tree this build
            # reads from (a checkout of another tree is a change of the tree). The numeric pass sources (the
            # SPIR-V helpers the translator imports) are named too: the walk finds them in the real tree, but a
            # tree that holds only them by name (the tests') must follow their changes as well.
            helpers = [DM / 'android/tools' / name for name in ('shader_vk.py', 'dmsv.py', 'shader_products.py',
                                                                 'spv_module.py', 'spv_builder.py', 'spv_half.py', 'spv_precise.py', 'spv_texture_offsets.py')]
            return nsp.fingerprint(nsp.package_key(pkg), ('files', sorted(set(nsp.vulkan_files(NXNATIVE) + helpers))),
                                   ('files', nsp.profile_files(self.g)), xkey, product_cache.inventory(Path(xlate).parent),
                                   ('files', sorted(cap.glob('*.bin'))))
        key = input_key()
        published_report = Path(str(self.dmsv) + '.report.json')
        if (note := product_cache.reused(kf, key, self.dmsv, companions=(published_report,))) is not None:
            PROG.end(f'{note}, reused (inputs unchanged)'); return
        tmp = self.dmsv.with_name('shaders.dmsv.partial'); nsp.rmtree(tmp)
        report = Path(str(tmp) + '.report.json'); nsp.rmtree(report)
        def line(s):
            if p := shader_progress(s): PROG.set(step=p[0], done=p[1], total=p[2], note=p[3])   # the export's own count: the stage shows how far it has come
            elif m := re.match(r'(translating|compressing) (\d+) shaders', s): PROG.set(step=f'{m.group(1)} {int(m.group(2)):,} shaders')   # compressing: the bundle's SPIR-V (dmsv.py)
            elif s.startswith('[RED] '): say(s)
        workers, avail = self.translation_workers()   # read again: the split in front may have taken some memory
        free = 'the device reports no memory' if avail is None else f'{avail:.0f} MB free'
        say(f'shader translation: {workers} worker(s) ({memory.basis(avail, self.o.low_mem)}; {free})')
        nsp.run([PY, DM / 'android/tools/shader_vk.py', pkg, tmp, '--jobs', str(workers), '--dotnet', self.tools['dotnet'], '--xlate', xlate, '--capture', cap, '--report', report],
                self.logs / 'android_shaders.log', env=self.env, on_line=line)
        import shader_products
        try:
            count, expected, complete = shader_products.check_bundle(tmp, json.loads(report.read_text(encoding='utf-8')))
            if input_key() != key: raise ValueError('shader inputs changed during export; port again')
        except (OSError, ValueError, TypeError, KeyError) as e:
            raise BuildError(f'invalid shader export: {e} (see {self.logs / "android_shaders.log"})') from e
        if count == 0: raise BuildError(f'no shader translated (see {self.logs / "android_shaders.log"})')
        note = f'{count:,} of {expected:,} shaders, {tmp.stat().st_size / 2**20:,.0f} MB'
        # Unsupported shaders are deterministic for these inputs; retain their report on reuse.
        if not complete:
            note += f', {expected - count:,} failed (see shaders.dmsv.report.json)'
            say('[RED] ' + note)
        nsp.swap_in(tmp, self.dmsv)
        report.replace(published_report)
        product_cache.stamp(kf, key, self.dmsv, note, complete=complete, companions=(published_report,))
        PROG.end(note)
        for d in (self.work / 'tmp').glob('shvk_*'): nsp.rmtree(d)   # the translator's work folders

    def translator(self):
        """The shader translator (dm/gfx/tools/dmsh_xlate over dm/third_party/ryujinx) built from the repository's source with the player's .NET SDK, once for every game,
        in <user dir>/tools/dmsh_xlate: (dmsh_xlate.dll, the source's key). Not the iOS chain's prebuilt dm/gfx/tools/dmsh_xlate_bin, which only a Mac can rebuild
        (its lock fingerprints Apple's Metal compiler): Android takes a translator fix as soon as it is in the source.
        A build made for the phone (NX2A_DMSH_XLATE) is used as it is: the phone has no SDK to restore the packages with (no network) and its NuGet settings
        read never ends, so the phone does not build the translator but runs one that was built for it"""
        pre = os.environ.get('NX2A_DMSH_XLATE') or (NXNATIVE.parent / 'tools' / 'dmsh_xlate')   # the build shipped with the phone
        if not Path(pre).is_dir() and not _has_network() and not _packages_cached():
            # without the prebuilt the translator has to be built here, and the restore needs the network: on the
            # phone that is a wait of minutes for a name server that never answers
            raise BuildError('the prebuilt shader translator is missing and the packages cannot be restored '
                             '(no network): the app was built without the C# tools (build_nx_extract.py needs '
                             'the .NET SDK)')
        if Path(pre).is_dir():
            src = Path(pre)
            if not (src / 'dmsh_xlate.dll').is_file(): raise BuildError(f'NX2A_DMSH_XLATE has no dmsh_xlate.dll: {src}')
            out = paths.user_dir() / 'tools/dmsh_xlate'; nsp.rmtree(out); shutil.copytree(src, out)
            # The bytes, not their times: installing a new APK re-extracts the shipped translator with fresh mtimes,
            # and a stat key would then translate every shader again (FINAL FANTASY RESONANCE: 73,512 shaders).
            key = nsp.fingerprint(product_cache.inventory(out), ('cmd', ['dmsh_xlate', 'prebuilt']), env=self.env)
            return out / 'dmsh_xlate.dll', key
        return build_translator(self.tools['dotnet'], self.env, self.logs)

    def host(self):
        out = self.aw / ('host-debug' if self.o.debug else 'host')
        if on_linux():   # the launcher's line: a Linux ELF the launcher runs itself (dm/linux/'s front, the machine's compiler), no NDK anywhere
            PROG.stage('host', step="the machine's own compiler")
            nsp.run(linux_host_args(self.g.id, out, self.o.jobs, release=not self.o.debug),
                    self.logs / 'linux_host.log', env=self.env)
            self.so = out / 'dmhost'
        else:
            PROG.stage('host', step=f'NDK {self.tools["ndk"].name}')
            nsp.run(self.build_cmd(out, ['--play' if self.o.app else '--lib']
                                   + (['--adrenotools'] if not prebuilt_loader() else []))
                    + ([] if self.o.debug else ['--release']), self.logs / 'android_host.log', env=self.env)
            self.so = out / 'libdmhost.so'   # --play (the app's :play runtime, with the app's JNI entry) and --lib (the APK's front) both produce this name
        if not self.so.is_file(): raise BuildError(f'build.py made no {self.so}')
        ph = out / 'gen' / self.g.id / 'game_profile.h'   # the profile the host was built from, for the data pack (porter host compares it with its checkout's)
        self.profile_h = hashlib.sha256(ph.read_bytes()).hexdigest() if ph.is_file() else None
        PROG.end(f'{self.so.stat().st_size / 2**20:.1f} MB')

    def apk(self):
        if self.o.app:   # the app's mode: the pack is the only artifact, the app runs the game itself
            self.result['mode'] = 'app'
            return
        PROG.stage('APK')
        stem = app_stem(self.g, self.app_name)
        self.apk_path = self.o.out / f'{stem}.apk'; self.o.out.mkdir(parents=True, exist_ok=True)
        icon = self.icon()
        code = version_code(self.pkg_ver, self.o.vercode_offset)
        if self.o.vercode_offset: say(f'versionCode {code} ({self.pkg_ver} + 1 + offset {self.o.vercode_offset})')
        external = self.external_activity() if self.o.external_display or self.o.native_keyboard else []
        driver = self.o.vulkan_driver
        if driver and driver.name != driver_lib_name(driver):   # packed under a lib*.so name (driver_lib_name), copied beside the host library
            driver = self.so.parent / driver_lib_name(driver); shutil.copyfile(self.o.vulkan_driver, driver)
            say(f'--vulkan-driver: {self.o.vulkan_driver.name} is packed as {driver.name} (Android extracts only lib*.so libraries)')
        nsp.run([PY, DM / 'android/apk/mkapk.py', self.so, self.apk_path, paths.signing_key(), '--package', self.package, '--label', self.app_name, '--lib', 'dmhost',
                 '--version-code', str(code), '--version-name', self.display]
                + (['--landscape'] if self.ap.landscape else []) + icon + self.theme() + self.ui_font() + external + ([] if self.o.debug else ['--release'])
                + (['--game-mode-performance'] if getattr(self, 'gl', None) is False else [])   # only NVN implements the mode's pacing policy; GL keeps OEM interventions
                + [a for f in dict.fromkeys(str(f) for f in (self.drivers() + self.loader_libs() + self.loader_so()
                                                             + ([driver] + [self.so.parent / n for n in ADRENOTOOLS_LIBS] if driver else []))) for a in ('--extra-so', f)]
                + (['--dex', str(dex)] if (dex := launcher_dex()) else []),
                self.logs / 'android_apk.log', env=self.env)
        self.result['apk'] = str(self.apk_path)
        PROG.end(f'{self.apk_path.name}, {self.apk_path.stat().st_size / 2**20:.1f} MB')

    def theme(self):
        """The on-screen gamepad's theme: only the game's own pack goes in the APK (dm/android/themes/themes.tsv maps title IDs to packs; a game with no row
        gets the ergo pack), as assets/overlay/ (theme.tsv and an atlas per layout), which the app reads at its first frame (dm/android/overlay_theme.c)"""
        files = self.theme_files()
        if not files: return []
        self.result['theme'] = android_profile.theme(self.g.id).name; say(f'gamepad theme: {self.result["theme"]}')
        return [a for name, src in files.items() for a in ('--asset', f'{name}={src}')]

    def data(self):
        PROG.stage('data pack', step='button-icon font')
        font_env, font_files = self.button_font()
        shared_env, shared_files = self.shared_font()
        font_env, font_files = font_env + shared_env, {**font_files, **shared_files}
        dst = self.data_dir()
        files = {**self.fps_files, **font_files}
        host = icon = None; drivers = []
        romfs, romfs_at, zenv = self.game / 'RomFS', None, []
        if getattr(self.ap, 'romfs_zstd', False) and romfs.is_dir():   # android.tsv romfs zstd: packed copies of the files that compress, made once into the build folder; the rest stay links to the extraction
            PROG.set(step='compressing the RomFS', done=0, total=1, unit='B')
            nf, npk, raw, out = romfs_pack.pack_tree(romfs, self.aw / 'romfs_zstd' / self.pkg_ver, self.o.jobs, progress=lambda d, t: PROG.set(step='compressing the RomFS', done=d, total=t, unit='B'))
            say(f'RomFS compressed: {npk:,} of {nf:,} files packed, {raw / 2**30:.1f} GB -> {out / 2**30:.1f} GB on the device')
            romfs, zenv = self.aw / 'romfs_zstd' / self.pkg_ver, ['DM_ROMFS_ZSTD=1']
        if self.o.app:   # the app runs the game itself: the pack carries what the APK used to (the host with the player's entry, the drivers, the icon, the gamepad's theme)
            # the app's mode: the pack points at the build folder's own RomFS instead of copying it (the same game twice on the phone is too much).
            # The pack's env.txt says where the host reads it from, and the manifest says the same, so the app knows the pack needs that folder.
            # A game without a RomFS (an OpenGL ES one) has none to point at: the pack keeps no RomFS, as before.
            # With the RomFS compressed (android.tsv romfs zstd) it points at the packed folder in the build workspace, which is where the packer wrote it.
            if romfs.is_dir():
                romfs_at, romfs = str(romfs), None
            # The runtime does not go into the pack when the app gave a runtimes folder (NX2A_RUNTIMES):
            # the host and the loader's hooks go to the app's private folder instead, one folder per title
            # ID (the build options are compiled into the host, so every game carries its own), with the
            # build marker (build.json) beside them. The pack keeps the game's data and the icon and the
            # gamepad's theme; a manifest without a 'host' key reads as this layout. Without the folder
            # (the desktop tool, the upstream engine) the runtime stays in the pack, as before.
            runtimes = os.environ.get('NX2A_RUNTIMES', '').strip()
            if runtimes:
                from porter.runtime_update import build_marker, write_marker
                target = Path(runtimes) / self.g.id.lower()

                def copy_into(src, name):
                    # 拷贝语义（原子写）：宿主、钩子与驱动在构建树/工具树里还有正本，
                    # 移走会让之后的移植与重建找不到它们。
                    target.mkdir(parents=True, exist_ok=True)
                    pending = target / (name + '.part')
                    with src.open('rb') as f, pending.open('wb') as dst:
                        shutil.copyfileobj(f, dst)
                        dst.flush()
                        os.fsync(dst.fileno())
                    os.replace(pending, target / name)

                copy_into(self.so, 'libdmhost.so')
                for lib in self.loader_libs():   # the loader's four hooks, the only managed parts beside the host
                    copy_into(lib, lib.name)
                if self.o.vulkan_driver:   # a driver the player picked for this port loads from the same folder
                    copy_into(self.o.vulkan_driver, driver_lib_name(self.o.vulkan_driver))
                write_marker(target / 'build.json', build_marker(getattr(self, 'profile_h', None), romfs_at or ''))   # the RomFS is not in the pack: the marker says where the host reads it from
            else:
                host = 'host/dmhost' if on_linux() else 'host/libdmhost.so'
                files[host] = self.so
                if not on_linux():   # the loader's four hooks travel with the host on Android; Linux runs the system's Vulkan driver
                    for d in self.loader_libs(): files[f'drivers/{d.name}'] = d
                drivers = sorted({f'drivers/{d.name}' for d in self.loader_libs()}) if not on_linux() else []
            # 档案随包走：构建这份宿主实际用的**整个档案目录**（实验性是派生/扩容后的副本，含
            # shader_map 等数据表——指纹按目录整体计算，缺文件会让重建误判漂移）写进包内
            # profile/<title ID>/，重建运行库时它是第一候选——导出、导入与 PC 的包因此自给自足。
            for src in sorted(self.g.dir.iterdir()):
                if src.is_file():
                    files[f'profile/{self.g.id}/{src.name}'] = src
            if theme := self.theme_files(): files.update(theme)
            if src := self.icon_png(): icon = 'icon.png'; files[icon] = src
            for d in self.drivers(): files[f'drivers/{d.name}'] = d
            if self.drivers(): drivers = sorted({f'drivers/{d.name}' for d in self.drivers()})
        man = datapack.build(dst, profile=self.ap, version=self.pkg_ver, display=self.display, patched=self.patched, romfs=romfs, romfs_at=romfs_at, shaders=self.dmsv,
                             aoc=self.aoc, sysdata=self.sysdata, language=self.lang, languages=getattr(self, 'languages', ()), package=self.package, env=self.fps_env + font_env + zenv + (['DM_VK_MT_REPLAY=1'] if self.o.mt_replay else [])                             + (['DM_MENU_BUTTON=0'] if self.o.no_menu_button else [])
                             + ([f'DM_VK_DRIVER={driver_lib_name(self.o.vulkan_driver)}'] if self.o.vulkan_driver else []), settings=TOUCH_SETTINGS if self.o.touch else None,
                             files=files, text=self.lists(), icon=icon, drivers=drivers, profile_h=getattr(self, 'profile_h', None),
                             exe=host if on_linux() else None,   # the launcher's line: the manifest names the ELF the launcher runs
                             pack_base=str(dst) if self.o.app else None,   # the app's mode: the pack lives in the app's own folder, not in the app's files folder
                             progress=lambda what, done, total: PROG.set(step=f'linking {what}', done=done, total=total, unit='B'))
        self.data_path = dst; self.result['data'] = str(dst)
        PROG.end(f'{man["files"]:,} files, {man["bytes"] / 2**30:.1f} GB')

    def button_font(self):
        """The stand-in for the system's Nintendo extension shared font: the controller-button icons in game text (U+E0E0 = A; Super Mario Bros. Wonder's menus showed '?' without it), which
        the host serves for shared-font type 5 (hle_sdk16.c, DM_SHARED_FONT_EXT). make_ext_font.py draws it, as the Mac and iOS builds do, made again when the tool or the letters change.
        Returns (env.txt rows, pack files); none without fontTools or a letter font, and the icons draw as '?'"""
        letters = next((Path(p) for p in LETTER_FONTS if Path(p).is_file()), None)
        try: import fontTools   # noqa: F401 (make_ext_font.py runs with this Python)
        except ImportError: letters, why = None, 'no fontTools (pip install fonttools)'
        else: why = 'no bold system font for the letters'
        if not letters: say(f'[RED] {why}: the button icons in the game\'s text draw as "?"'); return [], {}
        d = self.aw / 'font'; ttf, kf = d / 'nintendo_ext.ttf', d / 'nintendo_ext.key'
        key = nsp.fingerprint(('files', [DM / 'tools/make_ext_font.py', letters]))
        if not (ttf.is_file() and nsp.reused(kf, key) is not None):
            nsp.rmtree(kf); d.mkdir(parents=True, exist_ok=True)
            nsp.run([PY, DM / 'tools/make_ext_font.py', ttf, letters], self.logs / 'make_ext_font.log', env=self.env)
            kf.write_text(f'{key}\n')
        return [f'DM_SHARED_FONT_EXT={self.data_dir()}/nintendo_ext.ttf'], {'nintendo_ext.ttf': ttf}

    def install(self):
        if self.o.app: return   # the app's mode: no APK, the app runs the game itself
        install.install(self.apk_path, self.data_path, self.tools['adb'], self.o.device or self.cfg.get('device'), replace_signer=self.o.replace_signer,
                        romfs_at=self.o.romfs_at, romfs_push=self.o.romfs_push)

