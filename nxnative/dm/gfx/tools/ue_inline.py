#!/usr/bin/env python3
# The shader records an Unreal package keeps inline (It Takes Two's shape).
#
# Unreal Engine 4.27 for the Switch (It Takes Two) keeps no shader code archive: every shader sits in the cooked package that needs it, and the engine's global shaders in the
# global shader cache. A record is:
#
#   'LSLG' | the stage tag ('SV' vertex, 'SP' pixel, 'SG' geometry) | a 9-byte header | the parameter names | the parameters | the code area | the control section | the
#   shader's source | a 24-byte tail
#
# The code area starts with the NVN program's magic ('xV4\x12', 0x12345678), the control section with its own ('34127698', 0x98761234), and the source with the version line
# '!!NVvp5.0\n' ('v' vertex, 'p' pixel). The source holds the GLSL the shader was written in, interleaved with the binary of the program.
#
# The markers are what the reader walks on: where they sit varies from record to record (the names' length is at +15 in 139 of the 199 records of a material package and at
# +26 in the others, the code area's start with it), so nothing here is at a fixed offset. The old layout (uepak.lslg), which keeps the shaders in an archive, is a
# different format: a 0x880-byte control section and the code area at a fixed +0x38.
import os, re, struct

MAGIC = b'\x34\x12\x76\x98'              # the control section's magic (0x98761234)
PROGRAM = re.compile(rb'[xy]V4\x12')     # the code area's magic: 0x12345678 for graphics, 0x12345679 for compute
PROGRAM_MAGIC = b'\x78\x56\x34\x12'      # the code area's magic of a graphics program (0x12345678)
VERSION = re.compile(rb'!!NV(.)p5\.0\n')  # the source's version line: 'v' vertex, 'p' pixel
STAGES = (b'SV', b'SP', b'SC', b'SG')    # the stage tags: vertex, pixel, compute, geometry
HEADER = 15                              # the header is 9 bytes; the names' length (u32) follows at +15
TAIL = 24                                # the record's tail


def names(data, p, end):
    """The parameter names of the record at p: a blob whose length (u32) sits in the record's header, at an offset that varies with the record. The blob is the first one
    that holds text → (the offset of the length, the blob)"""
    for off in range(HEADER, min(end - p, 48) - 4):
        n = struct.unpack_from('<I', data, p + off)[0]
        if not 4 <= n <= 4096 or p + off + 4 + n > end: continue
        blob = data[p + off + 4:p + off + 4 + n]
        if not all(32 <= c < 127 for c in blob[:-1]): continue   # the text, the last byte may be the end of it
        if not any(65 <= c <= 90 or 97 <= c <= 122 for c in blob): continue
        return off, blob
    return None, None


def record(data, p, end):
    """The record at p: its parts as offsets in the data, or None if the bytes there are not a record"""
    if p + HEADER > len(data): return None
    tag = data[p + 4:p + 6]
    if tag not in STAGES: return None
    prog = PROGRAM.search(data, p + HEADER, end)
    if not prog: return None
    ctl = data.find(MAGIC, prog.end(), end)
    if ctl < 0: return None
    ver = VERSION.search(data, ctl, end)
    if not ver: return None
    off, blob = names(data, p, prog.start())
    if blob is None: off, blob = 0, b''   # a global shader has no parameters of its own
    return dict(start=p, end=end, tag=tag, names_off=off, names=blob, parameters=(p + off + 4 + len(blob), prog.start()),
                code=(prog.start(), ctl), control=(ctl, ver.start()), source=(ver.start(), end))


def records(data, warn=None):
    """Every shader record in the data: the parts of each, as offsets in the data. A record ends where the next one starts; the 'LSLG' of a record that does not read is
    skipped (the bytes of a code area can hold the marker by chance). The hits that hold a program but no control section are records of a shape this reader does not know:
    warn(offset, reason) is called for each, so a shader that is missing is visible"""
    hits = [m.start() for m in re.finditer(b'LSLG', data)]
    out = []
    for i, p in enumerate(hits):
        end = hits[i + 1] if i + 1 < len(hits) else len(data)
        rec = record(data, p, end)
        if rec: out.append(rec); continue
        if warn and p + HEADER <= len(data) and data[p + 4:p + 6] in STAGES and PROGRAM.search(data, p + HEADER, end):
            warn(p, 'the shader record has a program but no control section')
    return out


def parts(data, rec):
    """The bytes of the record's parts: (the stage tag, the parameter names, the parameters, the code area, the control section, the source, the tail)"""
    a, b = rec['parameters']; c, d = rec['code']; e, f = rec['control']; g, h = rec['source']
    return (rec['tag'].decode('latin1'), rec['names'], data[a:b], data[c:d], data[e:f], data[g:h], data[h - TAIL:h])


# The programs the game hands the NVN driver: the host's dump (DM_NVN_SHDUMP) writes every program it is given as <folder>/program_<key>_<i>.bin, the 0x880-byte control section the
# driver reads followed by the code area (its length in the control's +0x704). Unreal Engine 4.27 keeps its shaders inline (the records above) and expands them into this form when it
# creates the program, so the expansion is the engine's own work and not something the chain can read from the records. The programs are the old layout the chain takes, so a game
# with them is built from the dump: the control section's key rule is the chain's own (sha256 of the control section and the code area), the code area is the old one (a 0x30 header,
# the 0x50-byte SPH, the instructions at +0x80; a compute program's instructions at +0x100), and the compute thread group sits at the control's +0x748 as in every other game.
CTL = 0x880              # the control section the driver reads
CS_MAGIC = b'\x79\x56\x34\x12'    # the code area's magic of a compute program (0x12345679)
SPH_TYPE = {1: 'vs', 4: 'gs', 5: 'ps'}   # the shader program header's type bits (10..13): vertex / geometry / pixel


def program(data):
    """A program of a dump: (the stage, the control section, the code area), or None when the bytes are not one. The stage is the code area's magic (compute) or the shader program
    header's type (vertex / geometry / pixel); the control section's +0x704 must be the code area's length, as the driver reads it that way"""
    if len(data) < CTL + 4 or data[:4] != MAGIC: return None
    ctl, code = data[:CTL], data[CTL:]
    if struct.unpack_from('<I', ctl, 0x704)[0] != len(code): return None
    if code[:4] == CS_MAGIC: st = 'cs'
    elif code[:4] == PROGRAM_MAGIC: st = SPH_TYPE.get((struct.unpack_from('<I', code, 0x30)[0] >> 10) & 0xf)
    else: return None
    return (st, ctl, code)


def programs(folder):
    """Every program in a folder of dumps: (the file name, the stage, the control section, the code area). The ones that do not read are reported, so a program that is missing is
    visible"""
    for name in sorted(os.listdir(folder)):
        if not (name.startswith('program_') and name.endswith('.bin')): continue
        with open(os.path.join(folder, name), 'rb') as f: data = f.read()
        r = program(data)
        if r: yield (name, *r)
        else: yield (name, None, None, None)
