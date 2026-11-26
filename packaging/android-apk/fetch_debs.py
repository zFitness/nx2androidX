#!/usr/bin/env python3
"""Fetch Debian's arm64 packages (and what they need) into a folder.

The phone's build tools come from Debian: glslc (the shader compiler, the NDK's own is an x86-64 binary) and,
when the rootfs does not have them, OpenSSL and the C++ runtime. The distribution's index gives every package's
SHA-256, which is checked; nothing is installed on the build machine.

    python3 fetch_debs.py --out <dir> glslc libssl3
    python3 fetch_debs.py --out <dir> --list          # what the index has

The index (about 10 MB) is kept in --cache and reused on the next run; --refresh-index fetches it again.
"""
import argparse, hashlib, io, lzma, sys, tarfile, urllib.request
from pathlib import Path

MIRROR = 'https://deb.debian.org/debian'
SUITE = 'trixie'
ARCH = 'arm64'
# Documentation, translations and test data: they only make the tree bigger.
SKIP_FILES = ('/usr/share/doc/', '/usr/share/man/', '/usr/share/locale/', '/usr/share/info/', '/usr/share/bug/')


def get(url, timeout=120):
    req = urllib.request.Request(url, headers={'User-Agent': 'nx2android-android-apk'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()


def parse_packages(text):
    out = {}
    for block in text.split('\n\n'):
        fields, key = {}, None
        for line in block.split('\n'):
            if line[:1] in (' ', '\t') and key: fields[key] += '\n' + line.strip()
            elif ':' in line:
                key, _, value = line.partition(':'); key = key.strip(); fields[key] = value.strip()
        name = fields.get('Package')
        if not name or 'Filename' not in fields: continue
        out[name] = {'filename': fields['Filename'], 'sha256': fields.get('SHA256', ''), 'size': int(fields.get('Size', 0)),
                     'depends': fields.get('Depends', '')}
    return out


def dep_names(depends):
    out = []
    for group in depends.split(','):
        alt = group.split('|')[0].strip()
        name = alt.split(' ')[0].split(':')[0].strip()
        if name: out.append(name)
    return out


def resolve(index, wanted):
    seen, queue, missing = set(), list(wanted), []
    while queue:
        name = queue.pop(0)
        if name in seen: continue
        seen.add(name)
        p = index.get(name)
        if not p: missing.append(name); continue
        for d in dep_names(p['depends']):
            if d not in seen and d in index: queue.append(d)
    return sorted(seen), missing


def extract_deb(data, dest):
    """A .deb is an ar archive; its data.tar.* holds the files"""
    assert data[:8] == b'!<arch>\n', 'not a .deb'
    off = 8
    while off < len(data):
        header = data[off:off + 60]
        if len(header) < 60: break
        name = header[:16].decode('ascii', 'replace').strip()
        size = int(header[48:58].decode('ascii', 'replace').strip() or 0)
        body = data[off + 60:off + 60 + size]
        off += 60 + size + (size & 1)
        if not name.startswith('data.tar'): continue
        mode = 'r:gz' if name.endswith('.gz') else ('r:xz' if name.endswith('.xz') else ('r:bz2' if name.endswith('.bz2') else 'r:*'))
        with tarfile.open(fileobj=io.BytesIO(body), mode=mode) as t:
            for m in t.getmembers():
                n = m.name.lstrip('./')
                if not n or n.startswith('/'): continue
                if any(n.startswith(p) for p in SKIP_FILES): continue
                m.name = n
                # the filter keyword only exists from the release that carries tar_filter (3.12, backported);
                # a system python (macOS ships 3.9) rejects it even when the value is None
                t.extract(m, dest, **({'filter': 'tar'} if hasattr(tarfile, 'tar_filter') else {}))
        return
    raise RuntimeError('no data.tar in the .deb')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--suite', default=SUITE)
    ap.add_argument('--mirror', default=MIRROR)
    ap.add_argument('--cache', default='')
    ap.add_argument('--refresh-index', action='store_true', help='download the index again (it is kept in --cache)')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('packages', nargs='*')
    a = ap.parse_args()
    out = Path(a.out)
    cache = Path(a.cache or (out.parent / '.deb-cache')); cache.mkdir(parents=True, exist_ok=True)
    url = f'{a.mirror}/dists/{a.suite}/main/binary-{ARCH}/Packages.xz'
    index_file = cache / f'Packages-{a.suite}-{ARCH}.xz'
    if index_file.exists() and not a.refresh_index:
        print(f'>> the package index (cached): {index_file}')
        raw = index_file.read_bytes()
    else:
        print(f'>> the package index: {url}')
        raw = get(url)
        index_file.write_bytes(raw)
    index = parse_packages(lzma.decompress(raw).decode('utf-8', 'replace'))
    print(f'   {len(index)} packages in {a.suite}/main {ARCH}')
    if a.list:
        for n in sorted(index):
            if any(n.startswith(p) for p in (a.packages or [''])): print(f'   {n}')
        return 0
    if not a.packages: return 0
    names, missing = resolve(index, a.packages)
    if missing: print(f'   not in the index (skipped): {", ".join(sorted(missing))}')
    out.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names, 1):
        p = index[name]
        deb = cache / Path(p['filename']).name
        if not deb.exists(): deb.write_bytes(get(f'{a.mirror}/{p["filename"]}'))
        data = deb.read_bytes()
        if p['sha256']:
            got = hashlib.sha256(data).hexdigest()
            if got != p['sha256']: raise SystemExit(f'{name}: the SHA-256 is not the one the index gives')
        extract_deb(data, out)
        print(f'   [{i}/{len(names)}] {name}')
    size = sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    print(f'>> {out}: {len(names)} packages, {size / 2**20:.0f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
