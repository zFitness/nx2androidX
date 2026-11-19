#!/usr/bin/env python3
"""What this generation's shader records hold (It Takes Two's shape): the control sections, the code areas, and the table at the head of the file.

The records of a cooked package (or of the global shader cache) are read by the tool the shader split uses (nxnative/dm/gfx/tools/ue_inline.py). This
looks at what is inside them, which is how the layout of this generation was measured: the control section is only 111 to 158 bytes (the old layout has 0x880), so what it
holds has to be found out before the translation chain can be taught to take it.

    python3 devtools/ue_inline_analyze.py <file> [<file> ...]

For every file: the table at its head, the control sections (how many records share one, which bytes are the same in every record of a stage), and the code areas (where the
per-shader bytes start).
"""
import collections, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'nxnative' / 'dm' / 'gfx' / 'tools'))
import ue_inline   # noqa: E402

def constancy(parts, tag):
    """How many of the bytes at each position are the same in every part of that stage: the positions that are the same in all of them are the header, the rest is the
    shader's own data → (the positions that never change, the positions that always change)"""
    if not parts: return [], []
    n = min(len(p) for p in parts)
    same, diff = [], []
    for i in range(n):
        vals = {p[i] for p in parts if len(p) > i}
        (same if len(vals) == 1 else diff).append(i)
    return same, diff

SPH_TYPE = {'SV': (1,), 'SP': (5,), 'SG': (4,), 'SC': ()}   # the stage types the SPH word 0 carries (the old layout's shader_stage.py)

def sph_at(data, recs):
    """Where the SPH (the shader program header, the first word of which holds the stage type) is, in the code area: the offset whose word carries the stage of every
    record of that stage (the old layout has it at +0x30, after a 0x30-byte header) → (the offset, the hits, the records)"""
    out = {}
    for tag, want in SPH_TYPE.items():
        rs = [r for r in recs if r['tag'].decode() == tag]
        if not rs or not want: continue
        hits = collections.Counter()
        for r in rs:
            c0 = r['code'][0]
            # the magic is at +0 and its own bits look like a stage type; the SPH is never there.
            # Every byte offset is tried: this generation's header is 9 bytes, so the SPH is not 4-aligned
            for off in range(4, min(0x100, r['code'][1] - c0 - 4)):
                w = int.from_bytes(data[c0 + off:c0 + off + 4], 'little')
                if (w >> 10) & 0xf in want: hits[off] += 1
        if not hits: continue
        off, n = hits.most_common(1)[0]
        out[tag] = (off, n, len(rs))
    return out

def report(path):
    data = open(path, 'rb').read()
    recs = ue_inline.records(data)
    print(f'\n== {Path(path).name}: {len(data):,} bytes, {len(recs)} records')
    print('  the table at the head (u32):')
    head = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, min(128, len(data)), 4)]
    for i in range(0, len(head), 8):
        print('    ' + ' '.join(f'{v:10d}' for v in head[i:i + 8]))
    stages = collections.defaultdict(list)
    for r in recs: stages[r['tag'].decode()].append(r)
    print(f'  stages: { {k: len(v) for k, v in stages.items()} }')
    print('  the SPH: the offset in the code area whose word carries the stage of every record of that stage')
    for tag, (off, n, total) in sph_at(data, recs).items():
        print(f'    {tag}: +{off:#04x} ({n}/{total} records)')
    ctl_by_bytes = collections.defaultdict(list)
    for r in recs: ctl_by_bytes[data[r['control'][0]:r['control'][1]]].append(r['start'])
    shared = {k: v for k, v in ctl_by_bytes.items() if len(v) > 1}
    print(f'  control sections: {len(ctl_by_bytes)} different ones for {len(recs)} records; {len(shared)} of them are shared by more than one record')
    for k, v in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:3]:
        print(f'    {len(v)} records share one of {len(k)} bytes (at {", ".join(hex(x) for x in v[:4])})')
    for tag, rs in sorted(stages.items()):
        parts = [data[r['control'][0]:r['control'][1]] for r in rs]
        lens = sorted(len(p) for p in parts)
        same, diff = constancy(parts, tag)
        print(f'  {tag}: {len(rs)} records, control {lens[0]}..{lens[-1]} bytes (median {lens[len(lens) // 2]})')
        print(f'     the same in every record: the bytes {same[:24]}{" …" if len(same) > 24 else ""} ({len(same)} of {lens[0]})')
        print(f'     different in some record: {len(diff)} bytes')
    for tag, rs in sorted(stages.items()):
        parts = [data[r['code'][0]:r['code'][1]] for r in rs]
        lens = sorted(len(p) for p in parts)
        same, diff = constancy(parts, tag)
        head = same[:same.index(len(same))] if len(same) and same.index(len(same)) else same
        print(f'  {tag}: code {lens[0]}..{lens[-1]} bytes; the first {len(head)} bytes are the same in every record of the stage')

def main():
    for p in sys.argv[1:]: report(p)

if __name__ == '__main__': main()
