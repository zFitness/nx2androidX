#!/usr/bin/env python3
"""Walk the shader records of a cooked Unreal package (It Takes Two's shape).

Unreal Engine 4.27 for the Switch (It Takes Two) keeps no shader code archive: every shader sits in the cooked package that needs it, and the engine's global shaders in
the global shader cache. The records are read by the tool that the shader split uses (nxnative/dm/gfx/tools/ue_inline.py); this walks them and prints their boundaries,
which is how the layout was measured.

    python3 devtools/ue_shader_record.py <file> [--records N] [--names]

The file must be decoded already (the game's own OodleLZ_Decompress does that: devtools/ue_pak_oodle_job.py).
"""
import argparse, collections, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'nxnative' / 'dm' / 'gfx' / 'tools'))
import ue_inline   # noqa: E402

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('file')
    ap.add_argument('--records', type=int, default=10, help='how many records to print')
    ap.add_argument('--names', action='store_true', help='print the parameter names')
    a = ap.parse_args()
    data = open(a.file, 'rb').read()
    recs = ue_inline.records(data)
    print(f'{a.file}: {len(data):,} bytes, {len(recs)} records')
    print(f'  stages: {dict(collections.Counter(r["tag"].decode() for r in recs))}')
    for r in recs[:a.records]:
        tag, names, params, code, ctl, source, tail = ue_inline.parts(data, r)
        print(f'  @{r["start"]:,} {tag} code {len(code):,}  control {len(ctl):,}  source {len(source):,}  tail {len(tail):,}')
        if a.names: print(f'      names: {names!r}')

if __name__ == '__main__': main()
