#!/usr/bin/env python3
"""The runtime shader dumps of a game against its static shader records: how the record's fields become the control section the driver gets.

The driver (the host's NVN layer) is told to save every program it cannot find in the shader map (DM_NVN_SHDUMP): the file
<DM_ROOT>/shader_<key>.bin holds the 0x880-byte control section the game handed the driver, followed by the code area. The static
records (the cooked packages and the global shader cache) hold the same shader in a compact form: the code area's instructions sit
20 bytes after the program's magic, and the control section is a packed list of 16-bit fields.

This pairs the two: the instructions are the fingerprint (they are byte-identical), so a dump is matched with the record that holds
them, and the record's fields are then lined up with the runtime control section's.

    python3 devtools/ue_runtime_pair.py <dump folder> <static file> [<static file> ...]

It prints, for every pair, the record's field -> the runtime's offset table, and the fields the runtime has that the record does
not (the ones the game computes at run time).
"""
import collections, os, struct, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'nxnative' / 'dm' / 'gfx' / 'tools'))
import ue_inline   # noqa: E402

CTL = 0x880        # the control section the driver reads
INSN = 0x80       # the instructions' offset in the driver's code area
MAGIC = b'\x78\x56\x34\x12'


def dumps(folder):
    """The runtime dumps of a folder: (the file, the control section, the code area)"""
    for p in sorted(Path(folder).glob('program_*.bin')) + sorted(Path(folder).glob('shader_*.bin')):
        d = p.read_bytes()
        if len(d) < CTL: continue
        yield p, d[:CTL], d[CTL:]


def find_record(data, code):
    """The record of a code area: the instructions are the fingerprint (they are byte-identical in the file and at run time). The static
    code area keeps them 0x20 bytes after the program's magic; the driver's copy keeps them 0x80 bytes after it"""
    for off in (INSN, 0x20, 0x00):
        if len(code) <= off: continue
        p = data.find(code[off:off + 32])
        if p < 0: continue
        return p, off
    return -1, -1


def fields(data):
    """The 16-bit fields of a block: (the offset, the value), the non-zero ones"""
    return [(o, struct.unpack_from('<H', data, o)[0]) for o in range(0, len(data) - 1, 2) if struct.unpack_from('<H', data, o)[0]]


def pair(dump, ctl, code, static):
    """The record of a dump in a static file: (the file, the record, the control section's bytes)"""
    for name, data, recs in static:
        p, off = find_record(data, code)
        if p < 0: continue
        rec = next((r for r in recs if r['start'] <= p < r['end']), None)
        if not rec: continue
        return name, rec, data[rec['control'][0]:rec['control'][1]]
    return None, None, None


def load(static):
    """The static files and their records, read once"""
    out = []
    for path in static:
        data = Path(path).read_bytes()
        out.append((Path(path).name, data, ue_inline.records(data)))
    return out


def main():
    folder = sys.argv[1]
    static = load(sys.argv[2:])
    stats = collections.Counter()
    table = collections.Counter()
    missing = []
    for path, ctl, code in dumps(folder):
        name, rec, recctl = pair(path, ctl, code, static)
        if rec is None:
            missing.append(path.name)
            stats['not found'] += 1
            continue
        stats['paired'] += 1
        rt = dict((v, o) for o, v in fields(ctl))   # the value -> the runtime offset (the first one)
        for o, v in fields(recctl):
            if v in rt: table[(o, rt[v])] += 1
    print(f'the dumps: {stats["paired"] + stats["not found"]}, the paired: {stats["paired"]}, not found: {stats["not found"]}')
    print()
    print('=== the record\'s field -> the runtime\'s offset (how many samples agree) ===')
    for (ro, to), n in sorted(table.items(), key=lambda kv: -kv[1])[:40]:
        print(f'  the record +{ro:#05x} -> the runtime +{to:#05x}   ({n} samples)')
    print()
    print('=== the runtime\'s fields with no counterpart in the record (the ones the game computes) ===')
    gaps = collections.Counter()
    for path, ctl, code in dumps(folder):
        name, rec, recctl = pair(path, ctl, code, static)
        if rec is None: continue
        rv = {v for _, v in fields(recctl)}
        for o, v in fields(ctl):
            if v not in rv: gaps[(o, v)] += 1
    for (o, v), n in sorted(gaps.items())[:40]:
        print(f'  the runtime +{o:#05x} = {v:#06x}   ({n} samples)')


if __name__ == '__main__': main()
