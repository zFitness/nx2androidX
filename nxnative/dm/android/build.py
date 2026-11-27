#!/usr/bin/env python3
# Android build of the host (the counterpart of dm/host/Makefile): the same host and graphics sources, the Darwin compatibility layer (dm/android/compat)
# and the Android front end / graphics backend (dm/android/*.c), built with the NDK's clang for arm64.
#   build.py --game <title ID> [--ndk <NDK dir>] [--out <dir>] [--jobs N] [--exe] [--lib] [--only-compile] [--release]
# --release: no debug information, the library stripped, DM_RELEASE defined (the app ignores DM_CTL), outputs in dm/android/out/<title ID>-release.
# Outputs in <out> (default dm/android/out/<title ID>): dmhost (an executable for adb shell runs: headless, no window) and libdmhost.so (the app's NativeActivity).
# The front end depends on the shape: --play (the app's :play process) and --exe link the player's front, --lib links the upstream's APK front
# (a standalone APK: a NativeActivity of its own). One front per build, never both.
# Objects are rebuilt when a source or a header it includes changed (clang -MMD dependency files).
import argparse, concurrent.futures as cf, os, platform, re, subprocess, sys
from pathlib import Path

DM = Path(__file__).resolve().parent.parent          # dm/
ap = argparse.ArgumentParser()
ap.add_argument('--game', required=True)
ap.add_argument('--ndk', default=os.environ.get('ANDROID_NDK_HOME') or str(DM.parent.parent / 'tools/android-ndk-r27c'))
ap.add_argument('--out')
ap.add_argument('--api', default='31')
ap.add_argument('--jobs', type=int, default=os.cpu_count() or 8)
ap.add_argument('--exe', action='store_true'); ap.add_argument('--lib', action='store_true')
ap.add_argument('--play', action='store_true', help="also libdmhost.so: the host statically linked with the app's JNI adapter (jni_android.c), one per game, for the app's :play process")
ap.add_argument('--only-compile', action='store_true', help='compile every source and report errors, no link')
ap.add_argument('--keep-going', action='store_true')
ap.add_argument('-O', default='2')
ap.add_argument('--gfx', default='vk', choices=('vk', 'null'), help='graphics backend: Vulkan or the null device')
ap.add_argument('--os', default='android', choices=('android', 'linux'), help='target system: Android (the NDK\'s bionic) or Linux (this machine\'s own compiler and libc: the launcher\'s ELF, dm/linux/\'s front)')
ap.add_argument('--release', action='store_true', help='a build to keep installed: no debug information, stripped, no DM_CTL')
ap.add_argument('--adrenotools', action='store_true', help='also libadrenotools.so and its hooks (third_party/libadrenotools), which the APK carries with a custom Vulkan driver')
a = ap.parse_args()
if not (a.exe or a.lib or a.play): a.exe = a.lib = True

import platform as _pf, shutil as _sh, stat as _st0

DM_LINUX = a.os == 'linux'   # DM_TARGET=apple（环境变量）：宿主 TLS 走 apple 模式（loader.c 的 DM_TSD_APPLE define）
DM_TSD_APPLE = DM_LINUX and os.environ.get('DM_TARGET') == 'apple'
DM_TSD_LINUX = DM_LINUX and os.environ.get('DM_TARGET') == 'linux'   # the launcher's ELF: cross-built with this machine's clang and a Debian arm64 sysroot, no NDK anywhere

def host_dir(base, tool):
    """The NDK's host folder for a tool under base. On arm64 Linux the NDK ships x86-64 host tools only, so a folder named linux-aarch64 with an arm64 build of the tool beside the NDK's sysroot
    (see docs/DEVELOPMENT_GUIDE.md) is used when it holds the tool; otherwise linux-x86_64, as before (an x86_64 machine, or arm64 with qemu-user / box64), so a missing folder fails as it did"""
    if os.name == 'nt': return 'windows-x86_64'
    if not sys.platform.startswith('linux'): return 'darwin-x86_64'
    if _pf.machine().lower() in ('aarch64', 'arm64') and (Path(a.ndk) / base / 'linux-aarch64' / tool).exists(): return 'linux-aarch64'
    return 'linux-x86_64'

host = host_dir('toolchains/llvm/prebuilt', 'bin/clang')
# An ARM64 phone (Linux, aarch64): Google's NDK ships host tools for x86-64 only, so the compiler is the
# phone's own clang (on PATH) and the NDK gives the Android sysroot and the compiler-rt runtime libs.
NX2A_ARM_HOST = sys.platform.startswith('linux') and _pf.machine().lower() in ('aarch64', 'arm64')
bin_ = Path(a.ndk) / 'toolchains/llvm/prebuilt' / host / 'bin'
CC = str(bin_ / ('clang.exe' if os.name == 'nt' else 'clang'))
if DM_LINUX:
    # The Linux build runs on the machine that hosts the game (the launcher's line): the
    # system's clang -- or the fat package's own (NX2A_TOOLCHAIN: the phone payload's
    # clang plus a glibc prefix -- headers, crt, builtins -- from one Debian suite),
    # targeting its own aarch64 Linux. No NDK anywhere.
    tc = os.environ.get('NX2A_TOOLCHAIN', '')
    _cc = _sh.which('clang') or _sh.which('gcc')
    if not _cc and tc and (Path(tc) / 'clang/bin/clang').is_file():
        _cc = str(Path(tc) / 'clang/bin/clang')
    if not _cc:
        sys.exit('linux build: no clang or gcc on PATH (a --with-toolchain package brings one)')
    CC, bin_ = _cc, Path(_cc).parent
    CC_EXTRA = []
    _glibc = Path(tc) / 'glibc' if tc else None
    if _glibc and (_glibc / 'usr/include/stdio.h').is_file():
        CC_EXTRA = [f'--sysroot={_glibc}']
        _res = sorted(_glibc.glob('usr/lib/llvm-*/lib/clang/*'))
        if _res: CC_EXTRA.append(f'-resource-dir={_res[-1]}')
    if tc:
        os.environ['LD_LIBRARY_PATH'] = str(Path(tc) / 'lib') + os.pathsep + os.environ.get('LD_LIBRARY_PATH', '')
elif NX2A_ARM_HOST:
    _sysroot = next(Path(a.ndk).glob('toolchains/llvm/prebuilt/*/sysroot'), None)
    _res = next(iter(sorted(Path(a.ndk).glob('toolchains/llvm/prebuilt/*/lib/clang/*'))), None)   # the NDK's resource dir: the builtin headers and the compiler-rt
    _sys_clang = _sh.which('clang')
    if not (_sysroot and _res and _sys_clang):
        sys.exit('aarch64 host: need the NDK (its sysroot and runtime libs) and clang on PATH')
    # The flags go on the command line, not into a wrapper script: the wrapper's #!/bin/sh is the phone's own shell, which
    # cannot load the rootfs's libraries (the guest's LD_LIBRARY_PATH names them) and dies before the compiler runs
    CC = _sys_clang
    CC_EXTRA = [f'--sysroot={_sysroot}', f'-resource-dir={_res}', '-rtlib=compiler-rt']
else:
    CC_EXTRA = []
# The target as flags (a list, since gcc targets the machine it runs on and takes no --target)
TARGET = (['--target=aarch64-linux-gnu'] if Path(CC).name.startswith('clang') else []) if DM_LINUX \
    else [f'--target=aarch64-linux-android{a.api}']
out = Path(a.out) if a.out else DM / 'android/out' / (a.game + ('-release' if a.release else ''))
DBG = [] if a.release else ['-g']
obj = out / 'obj'; gen = out / 'gen'; obj.mkdir(parents=True, exist_ok=True); (gen / a.game).mkdir(parents=True, exist_ok=True)

# the game profile header, as the Makefile makes it
subprocess.run([sys.executable, str(DM / 'games/game.py'), 'header', a.game, str(gen / a.game / 'game_profile.h')], check=True)
# and its Android keys (android.tsv): the on-screen gamepad's layout
subprocess.run([sys.executable, str(DM / 'android/tools/android_profile.py'), 'header', a.game, str(gen / a.game / 'android_profile.h')], check=True)
# the settings registry's names (nxnative/dm/settings.tsv) for dm_settings.c: a setting outside it is logged as a typo
def _settings_names():
    names = sorted(l.split('\t', 1)[0] for l in (DM / 'settings.tsv').read_text(encoding='utf-8').splitlines() if l.startswith('DM_'))
    text = '// generated by build.py from nxnative/dm/settings.tsv\nstatic const char *const dm_settings_names[] = {\n' + ''.join(f'    "{n}",\n' for n in names) + '};\n'
    p = gen / a.game / 'dm_settings_names.h'
    if not p.exists() or p.read_text(encoding='utf-8') != text: p.write_text(text, encoding='utf-8', newline='\n')
_settings_names()

# the backend's own small shaders (dm/android/shaders): compiled with the NDK's glslc, embedded as gen/<name>_<stage>.spv.h
GL_SRC = sorted(p for p in (DM / 'android/shaders').iterdir() if p.suffix in ('.vert', '.frag', '.comp'))   # (the folder also keeps a third-party shader's license)
GLSLC = Path(a.ndk) / 'shader-tools' / host_dir('shader-tools', 'glslc') / ('glslc.exe' if os.name == 'nt' else 'glslc')
if DM_LINUX or (NX2A_ARM_HOST and host_dir('shader-tools', 'glslc') != 'linux-aarch64'):   # no NDK (Linux), or the NDK's shader-tools are x86-64 host binaries: the system's glslc
    _glslc = _sh.which('glslc') or (str(Path(tc) / 'bin/glslc') if tc and (Path(tc) / 'bin/glslc').is_file() else '')
    if not _glslc: sys.exit('glslc not found (apt install glslc, or a --with-toolchain package)')
    GLSLC = Path(_glslc)
for sh in GL_SRC:
    hdr = gen / a.game / f'{sh.stem}_{sh.suffix[1:]}.spv.h'
    if hdr.exists() and hdr.stat().st_mtime >= sh.stat().st_mtime: continue
    spv = gen / f'{sh.name}.spv'
    subprocess.run([str(GLSLC), '--target-env=vulkan1.1', '-O', str(sh), '-o', str(spv)], check=True)
    words = spv.read_bytes(); n = len(words) // 4
    import struct as _st
    body = ', '.join(f'{w:#010x}' for w in _st.unpack(f'<{n}I', words))
    hdr.write_text(f'// generated from dm/android/shaders/{sh.name} by build.py (glslc)\nstatic const uint32_t {sh.stem}_{sh.suffix[1:]}_spv[] = {{{body}}};\n')

def srcs(*globs): return [p for g in globs for p in sorted(DM.glob(g))]
HOST = [p for p in srcs('host/*.c') if p.name not in ('hle_movie_avc.c',)]   # VideoToolbox: dm/android/movie_avc.c instead
GFX = srcs('gfx/*.c', 'gfx/nvn/*.c', 'gfx/tex/*.c')
ASM = srcs('host/entry.S', 'gfx/nvn/nvn_entry.S', 'gfx/nvn/nvn_thunks.S')
VPX = srcs('third_party/libvpx/**/*.c')
ZSTD = srcs('third_party/zstd/zstddeclib.c')   # zstd's decompressor: the shader bundle's SPIR-V (gfx_vk_shader.c bundle_spv)

# One front (front_android.c: the upstream's, abstracted into a neutral core and an Android shell — a shell's
# entry is what a NativeActivity APK runs; the app's :play process drives the core's plain-data inputs through
# the adapter jni_android.c instead). frame generation and the player's own front are gone with this line's
# convergence: the host has no lsfg/ or vka/ code, and front_player.c is deleted.
def port_files():
    if DM_LINUX:
        # The Linux front (dm/linux/: the headless front, the audio and movie stand-ins),
        # the portable compat shims (the Android audio stack's two files excluded), and the
        # Android folder's platform-neutral pieces the core shares (the settings registry,
        # the common gfx helpers, and the null device the tools build with).
        out = list(srcs('linux/*.c'))
        out += [p for p in srcs('android/compat/*.c')
                if p.name not in ('audiotoolbox_aaudio.c', 'audioconverter_mediacodec.c')]
        out += [DM / 'android/dm_settings.c', DM / 'android/gfx_common.c']
        if a.gfx == 'null': out.append(DM / 'android/gfx_null.c')
        else: out += srcs('android/gfx_vk*.c')   # --gfx vk: the Vulkan backend the Android app runs (the NVN HLE's mtl_* interface), on SDL3's Wayland window
        return out
    out = []
    for p in srcs('android/compat/*.c', 'android/*.c'):
        if p.name == 'gfx_null.c' and a.gfx != 'null': continue   # one graphics backend
        if (p.name.startswith('gfx_vk') or p.name == 'gl_android.c') and a.gfx != 'vk': continue   # GLES presents through Vulkan and is not part of a null NVN tool
        if p.name in ('jni_android.c',): continue   # jni_android.c goes into --play's link (its list below)
        out.append(p)
    return out

INC = ['-include', str(DM / 'android/compat/include/darwin_compat.h'), '-include', str(DM / 'android/dm_settings.h'), f'-I{DM / "android/compat/include"}', f'-I{DM / "host"}', f'-I{DM / "gfx/nvn"}', f'-I{DM / "gfx/tex"}', f'-I{DM / "gfx/nvn/include"}',
       f'-I{DM / "third_party/vulkan-headers/include"}', f'-I{gen / a.game}', '-I/usr/include/SDL3', f'-I{DM / "third_party/libvpx"}', f'-I{DM / "third_party/stb_vorbis"}', f'-I{DM / "third_party/zstd"}', f'-I{DM / "android"}']
CFLAGS = TARGET + [f'-O{a.O}'] + DBG + ['-fPIC', '-fno-omit-frame-pointer', '-ffixed-x18', '-Wall', '-Wno-unused-function', '-Wno-unused-variable', '-Wno-unused-but-set-variable',
          '-Wno-format', '-Wno-deprecated-declarations', '-Wno-gnu-folding-constant', '-Werror=implicit-function-declaration', '-Werror=return-type',
          '-Werror=incompatible-pointer-types', '-Werror=int-conversion', '-D_GNU_SOURCE', '-DDM_LINUX=1' if DM_LINUX else '-DDM_ANDROID=1', *(['-DDM_TSD_APPLE=1'] if DM_TSD_APPLE else []), *(['-DDM_TSD_LINUX=1'] if DM_TSD_LINUX else []), '-fno-strict-aliasing', '-fvisibility=hidden'] + (['-DDM_RELEASE=1'] if a.release else [])
VPX_FLAGS = TARGET + ['-O2'] + DBG + ['-fPIC', f'-I{DM / "third_party/libvpx"}', f'-I{DM / "third_party/libvpx/config"}', '-w']
ZSTD_FLAGS = TARGET + ['-O2'] + DBG + ['-fPIC', '-fvisibility=hidden', '-DZSTDLIB_VISIBLE=', '-DZSTDERRORLIB_VISIBLE=', '-w']   # its API stays inside libdmhost.so

import hashlib, shutil
_stamp = obj / 'flags.stamp'; _flags = hashlib.sha256(repr((CFLAGS, INC, VPX_FLAGS, ZSTD_FLAGS, CC)).encode()).hexdigest()
if not _stamp.exists() or _stamp.read_text() != _flags:   # compiler flags changed: every object is rebuilt
    shutil.rmtree(obj, ignore_errors=True); obj.mkdir(parents=True, exist_ok=True); _stamp.write_text(_flags)

def dep_stale(o, d, s):
    if not o.exists() or o.stat().st_mtime < s.stat().st_mtime: return True
    if not d.exists(): return True
    t = o.stat().st_mtime
    txt = d.read_text(errors='replace').replace('\\\n', ' ')
    for f in re.split(r'(?<!\\)\s+', txt.split(':', 1)[1] if ':' in txt else ''):
        f = f.replace('\\ ', ' ').strip()
        if f and Path(f).exists() and Path(f).stat().st_mtime > t: return True
    return False

def compile_one(s):
    rel = s.relative_to(DM); o = obj / (str(rel).replace(os.sep, '_').replace('/', '_') + '.o'); d = o.with_suffix('.d')
    src = s
    if s.suffix == '.S':   # Mach-O assembly → ELF
        src = gen / (s.stem + '.elf.S')
        if not src.exists() or src.stat().st_mtime < s.stat().st_mtime:
            subprocess.run([sys.executable, str(DM / 'android/tools/darwin2elf.py'), str(s), str(src)], check=True)
    if not dep_stale(o, d, src): return s, o, 0, ''
    flags = VPX_FLAGS if 'third_party/libvpx' in str(rel).replace(os.sep, '/') else ZSTD_FLAGS if 'third_party/zstd' in str(rel).replace(os.sep, '/') else TARGET + DBG if s.suffix == '.S' else CFLAGS + INC
    r = subprocess.run([CC] + CC_EXTRA + flags + ['-MMD', '-MF', str(d), '-c', str(src), '-o', str(o)], capture_output=True, text=True, errors='replace')
    return s, o, r.returncode, r.stderr

def build(files):
    objs, failed = [], []
    with cf.ThreadPoolExecutor(a.jobs) as ex:
        for s, o, rc, err in ex.map(compile_one, files):
            objs.append(o)
            if rc: failed.append(s); print(f'--- {s.relative_to(DM)}\n{err.strip()}\n', file=sys.stderr)
            elif err.strip() and '--verbose' in sys.argv: print(err, file=sys.stderr)
    return objs, failed

# the sources of every shape: the host, the graphics, the one front. Frame generation is gone (the
# convergence: the fork's own lsfg/ chain deleted), so there is no --no-lsfg and no NX_LSFG define.
def shape_files():
    """The sources of one shape: the host, the graphics, the front."""
    return HOST + GFX + port_files() + ASM
FILES = shape_files()
PLAYS = srcs('android/jni_android.c')   # the app's JNI adapter: compiled always (the errors surface here too), linked only for --play
objs, failed = build(FILES)
if not DM_LINUX: pobjs, pfailed = build(PLAYS)   # jni_android.c: the app's adapter, Android only (the Linux link never takes it)
else: pobjs, pfailed = [], []
vobjs, vfailed = build(VPX + ZSTD)
failed += pfailed + vfailed
print(f'compiled {len(FILES) + len(PLAYS) + len(VPX) + len(ZSTD)} sources, {len(failed)} failed' + (': ' + ', '.join(str(f.relative_to(DM)) for f in failed) if failed else ''))
if failed and not a.keep_going: sys.exit(1)
if a.only_compile: sys.exit(1 if failed else 0)

LIBS = (['-lz', '-lm', '-ldl', '-lpthread'] + (['-lvulkan'] if a.gfx == 'vk' else []) + (['-lSDL3'] if DM_LINUX else []) if DM_LINUX else
        ['-landroid', '-llog', '-lvulkan', '-laaudio', '-lnativewindow', '-lmediandk', '-lz', '-lm', '-ldl'])   # -lz: the gamepad theme's PNGs (overlay_theme.c)
LDFLAGS = TARGET + ['-Wl,-z,max-page-size=16384', '-Wl,--build-id']
if not DM_LINUX: LDFLAGS += ['-fuse-ld=lld', '-Wl,--error-limit=0', '-Wl,-z,nostart-stop-gc']
elif _sh.which('ld.lld'): LDFLAGS += ['-fuse-ld=lld']   # brew llvm's linker; the system's default when there is none
if DM_LINUX: LDFLAGS += ['-L/usr/lib/aarch64-linux-gnu']   # 宿主 lib 目录：payload clang 驱动的搜索路径不含它（-lSDL3 等宿主库）
def link(args, name):
    # The 192 object paths under a long checkout exceed Windows' command-line limit (WinError 206).
    # Clang reads Windows-quoted arguments from a UTF-8 response file, including paths with spaces.
    if os.name == 'nt':
        rsp = out / f'{name}.rsp'; rsp.write_text(subprocess.list2cmdline(args), encoding='utf-8')
        args = ['--rsp-quoting=windows', '@' + str(rsp)]
    return subprocess.run([CC] + CC_EXTRA + args, capture_output=True, text=True, errors='replace')   # CC_EXTRA: the on-device toolchain's sysroot and runtime

if a.play:   # libdmhost.so: the whole host + the app's JNI adapter, statically linked (jni_android.c) — the app's :play runtime, the same front the exported APK carries
    r = link(LDFLAGS + ['-shared', '-Wl,-soname,libdmhost.so', '-o', str(out / 'libdmhost.so')] + [str(o) for o in objs + pobjs + vobjs] + LIBS, 'libdmhost-play')
    print(r.stderr.strip() if r.returncode else f'linked {out / "libdmhost.so"}', file=sys.stderr if r.returncode else sys.stdout)
    if r.returncode: sys.exit(1)
    if a.release:   # the static symbol table goes too (the dynamic one stays: the JNI surface)
        _strip = (bin_ / ('llvm-strip.exe' if os.name == 'nt' else 'llvm-strip'))
        if NX2A_ARM_HOST:
            _strip = Path(_sh.which('llvm-strip') or _sh.which('llvm-strip-18') or _sh.which('strip') or _strip)
        subprocess.run([str(_strip), '--strip-unneeded', str(out / 'libdmhost.so')], check=True)
        print(f'stripped {out / "libdmhost.so"}: {(out / "libdmhost.so").stat().st_size // 1024} KB')
if a.exe:
    r = link(LDFLAGS + ['-pie', '-o', str(out / 'dmhost')] + [str(o) for o in objs + vobjs] + LIBS, 'dmhost')
    print(r.stderr.strip() if r.returncode else f'linked {out / "dmhost"}', file=sys.stderr if r.returncode else sys.stdout)
    if r.returncode: sys.exit(1)
if a.lib:
    r = link(LDFLAGS + ['-shared', '-Wl,-soname,libdmhost.so', '-o', str(out / 'libdmhost.so')] + [str(o) for o in objs + vobjs] + LIBS, 'libdmhost')
    print(r.stderr.strip() if r.returncode else f'linked {out / "libdmhost.so"}', file=sys.stderr if r.returncode else sys.stdout)
    if r.returncode: sys.exit(1)
    if a.release:   # the static symbol table goes too (the dynamic one stays: ANativeActivity_onCreate)
        _strip = (bin_ / ('llvm-strip.exe' if os.name == 'nt' else 'llvm-strip'))
        if NX2A_ARM_HOST:   # the NDK's llvm-strip is an x86-64 binary: the phone's own
            _strip = Path(_sh.which('llvm-strip') or _sh.which('llvm-strip-18') or _sh.which('strip') or _strip)
        subprocess.run([str(_strip), '--strip-unneeded', str(out / 'libdmhost.so')], check=True)
        print(f'stripped {out / "libdmhost.so"}: {(out / "libdmhost.so").stat().st_size // 1024} KB')

# --adrenotools: libadrenotools.so (gfx_vk_core.c vk_init loads a custom Vulkan driver through it, DM_VK_DRIVER) and the hooks it loads from the APK's library folder,
# as its CMake files build them: linkernsbypass inside libadrenotools and libhook_impl, the three small hooks over libhook_impl with -z global
if a.adrenotools:
    AT = DM / 'third_party/libadrenotools'; LN = AT / 'lib/linkernsbypass'
    ATF = TARGET + ['-O2'] + DBG + ['-fPIC', '-w', f'-I{AT / "include"}', f'-I{AT}', f'-I{LN}']
    ATL = ['-fuse-ld=lld', '-shared', '-Wl,-z,max-page-size=16384', '-static-libstdc++', '-landroid', '-llog', '-ldl']
    CXX = str(bin_ / ('clang++.exe' if os.name == 'nt' else 'clang++'))
    libs = [('libadrenotools.so', [AT / 'src/driver.cpp', AT / 'src/bcenabler.cpp', LN / 'android_linker_ns.cpp', LN / 'elf_soname_patcher.cpp'], []),
            ('libhook_impl.so', [AT / 'src/hook/hook_impl.cpp', LN / 'android_linker_ns.cpp', LN / 'elf_soname_patcher.cpp'], ['-fvisibility=hidden'])]
    libs += [(f'lib{h}.so', [AT / f'src/hook/{h}.c'], ['-Wl,-z,global', f'-L{out}', '-lhook_impl']) for h in ('main_hook', 'file_redirect_hook', 'gsl_alloc_hook')]
    newest = max(p.stat().st_mtime for p in AT.rglob('*') if p.is_file())
    for name, files, extra in libs:
        o = out / name
        if o.exists() and o.stat().st_mtime >= newest: continue
        r = subprocess.run([CXX if any(f.suffix == '.cpp' for f in files) else CC] + CC_EXTRA + ATF + [str(f) for f in files] + ['-o', str(o), f'-Wl,-soname,{name}'] + ATL + extra,
                           capture_output=True, text=True, errors='replace')
        print(r.stderr.strip() if r.returncode else f'linked {o}', file=sys.stderr if r.returncode else sys.stdout)
        if r.returncode: sys.exit(1)
