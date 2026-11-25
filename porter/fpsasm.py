# Assembler-backed pieces of FPSLocker-Warehouse configs (porter/fpslocker.py).
#
# A config can declare variables and constants and small AArch64 routines, and its MASTER_WRITE can
# replace instructions in main rather than just bytes. This module turns those declarations into
# CUTS for patch_nso.py (DM_PATCHES_EXTRA) and exposes variable storage to the generated fpslock.tsv.
#
# There is no assembler in Python here: the NDK's clang is already part of the port's toolchain (and
# ships inside the phone app). It assembles one file with .org at each real main offset, so ADRP and
# branches get their real, PC-relative encodings; the .text of the object is read back by hand (no
# objcopy on the phone). A unique marker after every site says where that site's bytes end.
import os, re, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

MAGIC = 0xDEADBEEF   # a word after each site in the object, so its code length is known


class AsmError(Exception):
    pass


def clang():
    """The AArch64 assembler: the app's toolchain first, then the NDK's, then one on PATH."""
    t = os.environ.get('NX2A_TOOLCHAIN')
    if t:
        p = Path(t) / 'clang/bin/clang'
        if p.is_file(): return str(p)
    ndk, _ = None, None
    try:
        from porter import toolchain
        ndk, _ = toolchain.find_ndk()
    except Exception:
        pass
    if ndk:
        for pre in sorted((Path(ndk) / 'toolchains/llvm/prebuilt').glob('*')):
            p = pre / 'bin/clang'
            if p.is_file(): return str(p)
    p = shutil.which('clang')
    if p: return p
    raise AsmError('no clang assembler: the NDK or the app toolchain is needed for this config')


def layout(path):
    """(image, build id, text range) of an NSO: text is the first segment's memory range."""
    from porter import fpslocker
    d = Path(path).read_bytes()
    if d[:4] != b'NSO0': raise AsmError(f'{path} is not an NSO')
    segs = [struct.unpack_from('<III', d, 0x10 + i * 0x10) for i in range(3)]
    img, bid = fpslocker.nso_image(path)
    return img, bid, (segs[0][1], segs[0][1] + segs[0][2])


def cave(image, need, forbidden=(), text=None):
    """A zero run of [offset, offset+need) in a function's alignment padding, free of [forbidden].
    Only padding right after a ret or an unconditional branch is used: other zeroes may be live
    game data the engine clears at boot, and a cave there would change the game's own state."""
    bad = set()
    for off in forbidden:
        bad.update(range(off - 8, off + 16))
    lo, hi = text or (0, len(image))
    n = len(image)
    i = lo
    while i < hi:
        if image[i] or i % 4:
            i += 1
            continue
        j = i
        while j < n and not image[j] and j - i < max(need + 16, 64):
            j += 1
        prev = image[max(0, i - 4):i]
        pad = prev == b'\xc0\x03\x5f\xd6' or prev[:1] == b'\x14'   # ret, or an unconditional b
        if pad and j - i >= need and not any(k in range(i, i + need) for k in bad):
            return i
        i = max(j, i + 1)
    raise AsmError(f'no {need}-byte run of zero padding after a ret or branch is free in main')


def assemble(sites):
    """[(main offset, assembly lines)] → {offset: bytes}. sites may be empty."""
    if not sites: return {}
    src = ['.section .text,"ax"']
    for off, lines in sorted(sites):
        src.append('.org 0x%X' % off)
        src.extend(lines)
        src.append('.word 0x%08X' % MAGIC)
    text = '\n'.join(src) + '\n'
    with tempfile.TemporaryDirectory(prefix='nx2a-fpsasm-') as td:
        s, o = Path(td) / 'patch.s', Path(td) / 'patch.o'
        s.write_text(text, encoding='utf-8')
        env = dict(os.environ)
        # The guest's clang is not a chroot program: it needs the rootfs's libraries.
        libs = env.get('LD_LIBRARY_PATH')
        if libs: env['LD_LIBRARY_PATH'] = libs
        r = subprocess.run([clang(), '-target', 'aarch64-linux-android', '-c', str(s), '-o', str(o)],
                           capture_output=True, text=True, env=env)
        if r.returncode:
            lines = [l for l in r.stderr.strip().splitlines() if l.strip()]
            raise AsmError('clang: ' + ' | '.join(lines[-6:]) if lines else 'clang failed on: ' + text)
        d = o.read_bytes()
    if d[:4] != b'\x7fELF' or d[4] != 2: raise AsmError('clang wrote no ELF64 object')
    shoff = struct.unpack_from('<Q', d, 0x28)[0]
    shentsize, shnum = struct.unpack_from('<H', d, 0x3a)[0], struct.unpack_from('<H', d, 0x3c)[0]
    sec = None
    for i in range(shnum):
        o = shoff + i * shentsize
        if struct.unpack_from('<I', d, o + 4)[0] == 1 and struct.unpack_from('<Q', d, o + 0x20)[0] > 0:
            sec = struct.unpack_from('<Q', d, o + 0x18)[0]   # .text offset
            break
    if sec is None: raise AsmError('the object has no .text')
    body = d[sec:]
    out = {}
    for off, _ in sites:
        pos = body.find(struct.pack('<I', MAGIC), off)
        if pos < 0: raise AsmError('the marker for 0x%X is missing' % off)
        code = body[off:pos]   # keep trailing zeroes: a label address may end in zero bytes
        if not code.strip(b'\0'): raise AsmError('clang emitted nothing for 0x%X' % off)
        out[off] = code
    return out
