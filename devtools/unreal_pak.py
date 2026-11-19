#!/usr/bin/env python3
"""What is in an Unreal pak: its version, how many files it holds, how they are compressed, where their data starts.

The shader tools read Unreal paks (nxnative/dm/gfx/tools/uepak.py). This tells what a pak holds before the tools are pointed at it: how many files it has, how
they are stored (plain, Oodle-compressed, zlib), where the data of each starts, and how much has to be decoded when the shaders sit inline in the cooked packages.

    python3 devtools/unreal_pak.py <pak> [<pak> ...] [--entries N] [--grep <pattern>] [--summary] [--largest N]

The paks of a game's RomFS are under the game's own folder (the RomFS of the extraction), e.g. the file
Nuts/Content/Paks/Nuts-Switch.pak of It Takes Two (010092A0172E4000).
"""
import argparse, collections, re, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'nxnative' / 'dm' / 'gfx' / 'tools'))
import uepak   # noqa: E402

def report(path, entries, pattern, summary, largest):
    p = Path(path)
    print(f'\n== {p.name} ({p.stat().st_size:,} bytes)')
    try:
        pk = uepak.Pak(str(p))
    except ValueError as e:
        print(f'   does not read: {e}'); return
    print(f'   version {pk.version}, mount {pk.mount!r}, {len(pk.files):,} files, compression {pk.methods}')
    methods = collections.Counter()
    rows = []
    per_ext = collections.defaultdict(collections.Counter)
    per_raw = collections.Counter()
    uexp = collections.Counter(); uexp_bytes = collections.Counter()
    rx = re.compile(pattern) if pattern else None
    biggest = []
    for name in sorted(pk.files):
        e = pk.entry(name)
        methods[e['method'] or 'stored'] += 1
        ext = name.rsplit('.', 1)[-1].lower() if '.' in name else '(none)'
        per_ext[ext][e['method'] or 'stored'] += 1
        if e['method'] == 'Oodle': per_raw[ext] += e['raw']
        if ext == 'uexp':
            uexp[min(e['raw'] >> 20, 64)] += 1; uexp_bytes[min(e['raw'] >> 20, 64)] += e['raw']
        if largest: biggest.append((e['raw'], name, e))
        elif rx and rx.search(name): rows.append((name, e))
        elif not rx and len(rows) < entries: rows.append((name, e))
    if largest: rows = [(n, e) for _, n, e in sorted(biggest, reverse=True)[:largest]]
    print(f'   stored/compressed: {dict(methods)}')
    if summary:
        print('   by extension:')
        for ext, c in sorted(per_ext.items(), key=lambda kv: -sum(kv[1].values()))[:20]:
            print(f'     {ext:10s} {sum(c.values()):8,}  {dict(c)}')
        print('   bytes to decode (the Oodle files), by extension:')
        for ext, n in sorted(per_raw.items(), key=lambda kv: -kv[1])[:12]:
            if n: print(f'     {ext:10s} {n:14,}')
        print('   .uexp files by size:')
        for mb in sorted(uexp):
            print(f'     {mb:3d} MB+  {uexp[mb]:7,} files  {uexp_bytes[mb]:14,} bytes')
        print(f'   .uexp under 16 MB: {sum(uexp[m] for m in uexp if m < 16):,} files, {sum(uexp_bytes[m] for m in uexp if m < 16):,} bytes')
        print(f'   .uexp 16 MB and up: {sum(uexp[m] for m in uexp if m >= 16):,} files, {sum(uexp_bytes[m] for m in uexp if m >= 16):,} bytes')
    print(f'   {len(rows)} file(s) listed:')
    for name, e in rows:
        data = e['off'] + (53 + (4 + 16 * len(e['blocks'])) if e['method'] else 53)
        print(f'     {name}  raw {e["raw"]:,}  stored {e["size"]:,}  {e["method"] or "stored"}  blocks {len(e["blocks"])}  data at {data:,}')

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('pak', nargs='+')
    ap.add_argument('--entries', type=int, default=10, help='how many files to list per pak')
    ap.add_argument('--grep', help='list the files whose name matches this pattern')
    ap.add_argument('--summary', action='store_true', help='also count the files by extension, compression and size')
    ap.add_argument('--largest', type=int, help='list the N largest files instead of the first ones')
    a = ap.parse_args()
    for p in a.pak: report(p, a.entries, a.grep, a.summary, a.largest)

if __name__ == '__main__': main()
