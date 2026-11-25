#!/usr/bin/env python3
"""Build the Vulkan driver loader for the phone (arm64) and put it in the app's assets.

The host loads a Vulkan driver through libadrenotools (dm/android/gfx_vk_core.c, DM_VK_DRIVER). The loader itself has
to be in the app's own native library folder: the host dlopens it by name, and the Android linker looks a bare name up
in LD_LIBRARY_PATH, in the caller's DT_RUNPATH and in the namespace's default library paths — the app's native library
folder is the only one of those the app controls (the app's private host folder, where the host itself lives, is none
of them). The four hooks stay with the host: it hands the loader the folder it sits in, and the loader looks the hooks
up there.

The phone cannot build them (the NDK's clang++ is an x86_64 program, and the ARM64 LLVM the app ships has no C++
compiler), so it is built here, like nx_extract (build_nx_extract.py), and shipped: the loader in the app's native
library folder (--jni-out), the hooks in the app's assets, where the porter takes them for the data pack.

    python3 build_adrenotools.py [--out <dir>] [--jni-out <dir>] [--ndk <dir>]

The output is libadrenotools.so and its four hooks (libhook_impl.so, libmain_hook.so, libfile_redirect_hook.so,
libgsl_alloc_hook.so), built as dm/android/build.py --adrenotools builds them (the same sources, the same flags), so
the game APK carries them and any driver the player imports later can be loaded.
"""
import argparse, os, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
AT = REPO / 'nxnative' / 'dm' / 'third_party' / 'libadrenotools'
LN = AT / 'lib' / 'linkernsbypass'
DEFAULT_OUT = Path(__file__).resolve().parent / '.cache' / 'assets' / 'tool' / 'tools' / 'adrenotools'
DEFAULT_JNI_OUT = Path(__file__).resolve().parent / '.cache' / 'jniLibs' / 'arm64-v8a'
API = '31'                       # the API the host is built for (dm/android/build.py --api)
LOADER = 'libadrenotools.so'     # the one the host dlopens by name: it goes into the app's native library folder


def copy_prebuilt(src, out, jni):
    """Reuse the driver loader built on a machine that has the Android NDK.

    NX2A_ADRENOTOOLS_PREBUILT may be the tool folder itself or the app's files/ tree; an explicit
    variable keeps stale binaries from being used silently when the sources change.
    """
    src = Path(src)
    nested = src / 'files' / 'tool' / 'tools' / 'adrenotools'
    if not (src / LOADER).is_file() and (nested / LOADER).is_file():
        src = nested
    libs = sorted(src.glob('lib*.so'))
    if not (src / LOADER).is_file() or len(libs) != 5:
        return False
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    for lib in libs:
        shutil.copy2(lib, out / lib.name)
        (out / lib.name).chmod(0o755)
        print(f'   {lib.name:32} {lib.stat().st_size / 1024:8.0f} KB')
    jni.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out / LOADER, jni / LOADER)
    print(f'>> {LOADER} from {src} (no NDK needed)')
    return True


def find_ndk(given):
    """The NDK with the compiler: the one that was named, else the one in the environment, else the newest in the SDK.
    r27c is the one the repository's tools are built with (porter/config.py), so it is preferred when the SDK has it"""
    if given: return Path(given)
    for env in ('ANDROID_NDK_HOME', 'ANDROID_NDK_ROOT'):
        if os.environ.get(env) and Path(os.environ[env]).is_dir(): return Path(os.environ[env])
    for sdk in (os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'), str(Path.home() / 'Library' / 'Android' / 'sdk')):
        if not sdk: continue
        d = Path(sdk) / 'ndk'
        if not d.is_dir(): continue
        found = sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: [int(x) if x.isdigit() else x for x in p.name.replace('-', '.').split('.')])
        if not found: continue
        r27 = [p for p in found if p.name.startswith('27.')]
        return (r27 or found)[-1]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(DEFAULT_OUT))
    ap.add_argument('--jni-out', default=str(DEFAULT_JNI_OUT),
                    help='where the loader goes: the app\'s native library folder (the one the linker searches by name)')
    ap.add_argument('--ndk', default='', help='the Android NDK folder (r27c); found in the environment or in the SDK when not named')
    a = ap.parse_args()
    out = Path(a.out)
    jni = Path(a.jni_out)
    prebuilt = os.environ.get('NX2A_ADRENOTOOLS_PREBUILT', '')
    if prebuilt and copy_prebuilt(prebuilt, out, jni):
        return 0
    ndk = find_ndk(a.ndk)
    if ndk is None:
        print('>> no Android NDK: the driver loader is not built (a driver the player imports will not load)')
        return 1
    bin_ = ndk / 'toolchains' / 'llvm' / 'prebuilt' / ('darwin-x86_64' if sys.platform == 'darwin' else 'linux-x86_64') / 'bin'
    if not (bin_ / 'clang++').is_file():
        for host in sorted(p.name for p in (ndk / 'toolchains' / 'llvm' / 'prebuilt').iterdir()):
            if (ndk / 'toolchains' / 'llvm' / 'prebuilt' / host / 'bin' / 'clang++').is_file():
                bin_ = ndk / 'toolchains' / 'llvm' / 'prebuilt' / host / 'bin'; break
    cxx = str(bin_ / 'clang++')
    if not Path(cxx).is_file():
        print(f'>> no clang++ in {bin_}: the driver loader is not built (a driver the player imports will not load)')
        return 1
    print(f'>> the driver loader (the NDK at {ndk.name}, {cxx})')
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    flags = [f'--target=aarch64-linux-android{API}', '-O2', '-fPIC', '-w', f'-I{AT / "include"}', f'-I{AT}', f'-I{LN}']
    link = ['-fuse-ld=lld', '-shared', '-Wl,-z,max-page-size=16384', '-static-libstdc++', '-landroid', '-llog', '-ldl']
    libs = [('libadrenotools.so', [AT / 'src/driver.cpp', AT / 'src/bcenabler.cpp', LN / 'android_linker_ns.cpp', LN / 'elf_soname_patcher.cpp'], []),
            ('libhook_impl.so', [AT / 'src/hook/hook_impl.cpp', LN / 'android_linker_ns.cpp', LN / 'elf_soname_patcher.cpp'], ['-fvisibility=hidden'])]
    libs += [(f'lib{h}.so', [AT / f'src/hook/{h}.c'], ['-Wl,-z,global', f'-L{out}', '-lhook_impl']) for h in ('main_hook', 'file_redirect_hook', 'gsl_alloc_hook')]
    for name, files, extra in libs:
        o = out / name
        # C hooks must keep the unmangled symbol names the Android loader resolves.
        compiler = cxx if any(f.suffix == '.cpp' for f in files) else str(bin_ / 'clang')
        cmd = [compiler] + flags + [str(f) for f in files] + ['-o', str(o), f'-Wl,-soname,{name}'] + link + extra
        r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
        if r.returncode:
            print(r.stdout[-4000:]); print(r.stderr[-4000:])
            print(f'>> {name} did not build')
            return r.returncode
        # the symbols are of no use in the APK (the game's own page lists the libraries, not their symbols)
        strip = bin_ / 'llvm-strip'
        if strip.is_file():
            subprocess.run([str(strip), '--strip-unneeded', str(o)], capture_output=True, text=True)
        print(f'   {name:32} {o.stat().st_size / 1024:8.0f} KB')
    # the loader alone goes into the app's native library folder: the host dlopens it by name, and that folder is
    # the one the linker searches (the app's private host folder is not on any of its paths)
    jni.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out / LOADER, jni / LOADER)
    print(f'   {LOADER:32} -> {jni} ({((jni / LOADER).stat().st_size / 1024):.0f} KB, the app\'s native library folder)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
