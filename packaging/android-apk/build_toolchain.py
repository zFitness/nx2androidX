#!/usr/bin/env python3
"""Assemble the toolchain the phone builds with: the Android NDK's sysroot, an ARM64 clang, and glslc.

Google's NDK ships host tools for x86-64 only, so a phone cannot run the NDK's own compiler. The NDK's sysroot
and compiler-rt are host-independent, though, so they are taken from the official NDK and the compiler comes from
an ARM64 Linux build of LLVM (zhuwanhong/android-sdk-linux-arm64, Apache-2.0 with LLVM exceptions).

    python3 build_toolchain.py --out <dir> [--ndk-zip ...] [--llvm-tar ...] [--debs <dir>]

The result is what the porter sees as the NDK (NX2A_NDK) plus the compilers on PATH:

    <out>/ndk/source.properties
    <out>/ndk/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/{include,lib/aarch64-linux-android/31}
    <out>/ndk/toolchains/llvm/prebuilt/linux-x86_64/lib/clang/18/{include,lib/linux}
    <out>/clang/bin/{clang,lld,llvm-strip,llvm-ar,llvm-ranlib,llvm-nm,llvm-objcopy}
    <out>/bin/glslc  <out>/lib/libshaderc.so.1
"""
import argparse, os, shutil, stat, subprocess, sys, tarfile, zipfile
from pathlib import Path

NDK_URL = 'https://dl.google.com/android/repository/android-ndk-r27c-linux.zip'
NDK_SHA1 = '090e8083a715fdb1a3e402d0763c388abb03fb4e'   # Google's index (repository2-3.xml)
LLVM_URL = ('https://github.com/zhuwanhong/android-sdk-linux-arm64/releases/download/v1.0.0/'
            'android-ndk-27.1.12297006-linux-aarch64-ours.tar.gz')
LLVM_SHA256 = '218286f50194da7470e20b4fad261cf05d7923cc8b81613ad09e118052595bb1'
# The API level the game's host is built for (build.py's default) and the LLVM tools that are kept:
# the compiler, the linker and the stripper (llvm-strip is a link to llvm-objcopy). The other tools (objdump, nm,
# ar) are not used by a C build and are a third of the size.
API = '31'
LLVM_TOOLS = ['clang-18', 'lld', 'llvm-objcopy', 'llvm-strip']


def sha1(path):
    import hashlib
    h = hashlib.sha1()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 20): h.update(chunk)
    return h.hexdigest()


def sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while chunk := f.read(1 << 20): h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, digest, algo):
    import urllib.request
    if dest.exists():
        got = sha1(dest) if algo == 'sha1' else sha256(dest)
        if got == digest: return dest
        dest.unlink()
    print(f'>> downloading {url}')
    req = urllib.request.Request(url, headers={'User-Agent': 'nx2android-android-apk'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest.with_suffix(dest.suffix + '.part'), 'wb') as f:
        shutil.copyfileobj(r, f, 1 << 20)
    part = dest.with_suffix(dest.suffix + '.part')
    got = sha1(part) if algo == 'sha1' else sha256(part)
    if got != digest:
        part.unlink(missing_ok=True)
        raise SystemExit(f'{url}: the {algo} is not the one the release gives ({got} != {digest})')
    part.replace(dest)
    return dest


def ndk_parts(zip_path, out):
    """The NDK's sysroot and compiler-rt: what a phone needs from the official NDK"""
    prebuilt = 'android-ndk-r27c/toolchains/llvm/prebuilt/linux-x86_64'

    def keep(name):
        if name.startswith(f'{prebuilt}/sysroot/usr/include/'): return True
        if name.startswith(f'{prebuilt}/sysroot/usr/lib/aarch64-linux-android/{API}/'): return True
        if name.startswith(f'{prebuilt}/lib/clang/18/include/'): return True
        if name.startswith(f'{prebuilt}/lib/clang/18/lib/linux/'):
            rest = name[len(f'{prebuilt}/lib/clang/18/lib/linux/'):]
            return rest.startswith('aarch64/') or 'aarch64' in rest   # the other ABIs' runtime libs are not ours
        return False

    print(f'>> the NDK out of {zip_path.name}')
    with zipfile.ZipFile(zip_path) as z:
        for name in z.namelist():
            if not keep(name) or name.endswith('/'): continue
            target = out / 'ndk' / name[len('android-ndk-r27c/'):]
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, open(target, 'wb') as dst: shutil.copyfileobj(src, dst)
            mode = z.getinfo(name).external_attr >> 16
            if mode & 0o111: target.chmod(mode & 0o755)
        # the version the doctor reads
        with z.open('android-ndk-r27c/source.properties') as src:
            (out / 'ndk' / 'source.properties').write_bytes(src.read())


def llvm_tools(tar_path, out):
    """The ARM64 clang and the linker, out of the community build"""
    print(f'>> the ARM64 LLVM out of {tar_path.name}')
    root = 'ndk/27.1.12297006/toolchains/llvm/prebuilt/linux-aarch64'
    wanted = {f'{root}/bin/{t}' for t in LLVM_TOOLS}
    wanted |= {f'{root}/bin/clang', f'{root}/bin/ld.lld'}
    links = {}
    with tarfile.open(tar_path) as t:
        for m in t.getmembers():
            name = m.name.lstrip('./')
            if name not in wanted: continue
            target = out / 'clang' / 'bin' / Path(name).name
            target.parent.mkdir(parents=True, exist_ok=True)
            if m.issym():
                links[target] = m.linkname
                continue
            if not m.isfile(): continue
            src = t.extractfile(m)
            with open(target, 'wb') as dst: shutil.copyfileobj(src, dst)
            target.chmod(0o755)
    # the tools that are links to another one (clang -> clang-18, ld.lld -> lld, llvm-strip -> llvm-objcopy):
    # the phone's assets cannot hold a link, so the tool keeps the name and the other copy goes
    for target, link in links.items():
        other = target.parent / link
        if not other.exists(): continue
        shutil.copy2(other, target)
        target.chmod(0o755)
        other.unlink()
        print(f'   {target.name} (was {link})')


def debs_tools(debs_dir, out):
    """glslc and the library it needs, out of Debian's arm64 packages"""
    print('>> glslc out of the Debian packages')
    for src, rel in ((debs_dir / 'usr/bin/glslc', 'bin/glslc'), (debs_dir / 'usr/lib/aarch64-linux-gnu/libshaderc.so.1', 'lib/libshaderc.so.1')):
        if not src.exists(): raise SystemExit(f'{src} is missing (run fetch_debs.py glslc first)')
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        target.chmod(0o755)


def strip(paths):
    """The tools are stripped: the debug info is half their size"""
    strip_bin = shutil.which('llvm-strip') or shutil.which('strip')
    if not strip_bin: return
    for p in paths:
        if p.is_symlink(): continue   # stripping a link would replace it with a copy of its target
        subprocess.run([strip_bin, '--strip-unneeded', str(p)], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--cache', default='')
    ap.add_argument('--ndk-zip', default='')
    ap.add_argument('--llvm-tar', default='')
    ap.add_argument('--debs', default='')
    a = ap.parse_args()
    out = Path(a.out); cache = Path(a.cache or (out.parent / '.cache'))
    cache.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    ndk_zip = Path(a.ndk_zip) if a.ndk_zip else fetch(NDK_URL, cache / 'android-ndk-r27c-linux.zip', NDK_SHA1, 'sha1')
    llvm_tar = Path(a.llvm_tar) if a.llvm_tar else fetch(LLVM_URL, cache / 'android-ndk-27.1.12297006-linux-aarch64-ours.tar.gz', LLVM_SHA256, 'sha256')
    debs = Path(a.debs) if a.debs else cache / 'debs'
    ndk_parts(ndk_zip, out)
    llvm_tools(llvm_tar, out)
    debs_tools(debs, out)
    strip(list((out / 'clang' / 'bin').glob('*')))
    # the stripper rewrites the files in place and can drop the executable bit (notably on Windows)
    for p in (out / 'clang' / 'bin').glob('*'):
        if p.is_file(): p.chmod(0o755)
    for rel in ('bin/glslc', 'lib/libshaderc.so.1'):
        p = out / rel
        if p.is_file(): p.chmod(0o755)
    size = sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    print(f'>> the toolchain at {out}: {size / 2**20:.0f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
