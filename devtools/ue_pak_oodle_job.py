#!/usr/bin/env python3
"""An Oodle job for the files of an Unreal pak: the game decodes them with its own OodleLZ_Decompress (DM_OODLE_JOB, dm/host/hle_oodle.c).

Unreal paks store their files in blocks, each one Oodle-compressed (It Takes Two: 75,637 files that way). The game's own decoder is the only one that can read them, so they
go to it as a job file: "DMOJ" (u32 count, then per record the compressed length, the raw length and the compressed bytes), and the answer comes back as "DMOR" (u32 count, then per
record the decoded length and the bytes).

    python3 devtools/ue_pak_oodle_job.py <pak> <job file> <file> [<file> ...] [--manifest <file>]

The manifest (JSON) says which file each record belongs to, in which order, so the answer can be put back into the files. The files are given as they are named in the pak (the
mount point is not part of them).

On the phone app the job is decoded by the host built as a tool (porter/pipeline.py, the game's own modules beside it):
    DM_OODLE_JOB=<job file> dmhost <the rewritten modules>   → the answer beside the job file
"""
import argparse, json, struct, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'nxnative' / 'dm' / 'gfx' / 'tools'))
import uepak   # noqa: E402

JOB_MAGIC = 0x4a4f4d44   # "DMOJ"

def build(pak, names):
    """(the job file's bytes, the manifest): every block of every file, in the order they are decoded"""
    pk = uepak.Pak(str(pak))
    job, manifest = bytearray(), []
    for name in names:
        e = pk.entry(name)
        left = e['raw']
        for i, (start, n) in enumerate(e['blocks']):
            raw = min(left, e['block_size']); left -= raw
            with open(pak, 'rb') as f:
                f.seek(e['off'] + start); comp = f.read(n)
            if len(comp) != n: raise ValueError(f'{name}: the pak is short of block {i}')
            manifest.append(dict(file=name, block=i, raw=raw, stored=n))
            job += struct.pack('<II', n, raw) + comp
    return struct.pack('<II', JOB_MAGIC, len(manifest)) + bytes(job), manifest

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('pak')
    ap.add_argument('job')
    ap.add_argument('file', nargs='+')
    ap.add_argument('--manifest', help='where to write the manifest (default: the job file with .json)')
    a = ap.parse_args()
    job, manifest = build(a.pak, a.file)
    Path(a.job).write_bytes(job)
    m = Path(a.manifest) if a.manifest else Path(a.job).with_suffix('.json')
    m.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    print(f'{a.job}: {len(manifest)} records, {len(job):,} bytes; manifest {m}')

if __name__ == '__main__': main()
