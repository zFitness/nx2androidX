#!/usr/bin/env python3
"""The development loop of the Linux host on the DroidDeck tablet's DroidSpaces container: one entry for sync, build, run, collect, stop.

    python3 devtools/droidspaces_dev.py sync                                  # the checkout's nxnative/dm -> the container's source tree
    python3 devtools/droidspaces_dev.py build [--clean] [--gfx vk|null]       # build.py there, taking up where the last build ended
    python3 devtools/droidspaces_dev.py run --mode testcard --validate        # the pack's own run.sh, the window showing the test card
    python3 devtools/droidspaces_dev.py run --mode game [--seconds 120]       # the pack's own run.sh, the game
    python3 devtools/droidspaces_dev.py collect [--shot]                      # the run's log, exit status, validation lines, screenshots
    python3 devtools/droidspaces_dev.py stop                                  # ends the run this tool started, and no other process
    python3 devtools/droidspaces_dev.py status | selftest

Six things are told apart (and every command prints the places it uses):

    source set       the checkout's nxnative/dm as it is now: tracked files, modified or not, and new files that are not ignored. A
                     change is tested without a commit. Other games' profiles are left out: the host build reads this game's alone.
    container tree   DEV/src/nxnative/dm in the container, the one tree the host is built from: a mirror of the source set.
    profile          <pack>/profile/<title>/ -- the profile the rewritten module was made with (the patches.py there is what runs).
    module           <pack>/mods/ -- the rewritten modules with their fixups, made by the port. Not rebuilt here: a change in porter/
                     or in patches.py needs a new port, and this tool says so rather than pretending.
    host             DEV/out/<game>-<gfx>/dmhost, built from the container tree; installed as <pack>/host/dmhost once a build is whole.
    entry            <pack>/run.sh, written by the launcher. Both modes start through it, so the data root, the pack's env.txt (RomFS,
                     fonts), the saves and the module path are resolved by the launcher's script and by the host -- not by this tool.

Two environments, kept apart, both printed (they are defined once, in droidspaces_dev_remote.py):

    build            the payload's clang and glslc (/opt/nx2a/toolchain); python3, the linker and every library are the container's own.
    run              the container's own loader, libc, SDL3, Vulkan and Wayland; nothing else is added.

What keeps a run honest:

    * a build is whole only when build.py exited 0, linked a new ELF, and every source changed since the last build had its object made
      again; the host is copied into the pack under a temporary name and renamed over, so the pack never holds half of a binary;
    * a failed build installs nothing, and `run` then refuses to start the host that was installed before it (as does a source change
      made after the last build, or a host put into the pack by something else) unless --allow-stale says otherwise -- and then says so;
    * nothing is deleted by default: the build directory keeps build.py's objects and their dependency files (a changed header rebuilds
      what includes it, changed compile flags rebuild everything: build.py's own doing); a file whose content changed is touched in the
      container, so it is newer than any object whatever the two machines' clocks say. --clean is the whole build directory, removed;
    * the process of a run is on record with its pid and start time; `stop` signals its descendants alone.

The game runs fullscreen: the window is created fullscreen and nothing resizes, maximizes or drags it. The chain this tool is for:
fullscreen test card (updating, validation clean) -> fullscreen game -> background and back -> an orderly exit.

Every build gets a test id (B<UTC time>-<digest of the source set>); each run of it is run-NN under it. The evidence lives in the main
checkout, under .gamedump/<App>/linux-dev/<test id>/ (never only in the container's /tmp): manifest.json (commit, dirty files, source
digest, build parameters, game version, what each part is), sources.json, build.log, build-result.json, ident.json, and per run
launch.json, run.log, validation.log, issues.txt, exit.txt, summary.txt, shots/. `collect` prints the outcome from the exit status and
counts what the validation layer and the host reported -- a count is read as zero only when the log is there and the run has ended.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tarfile, tempfile, time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
from device import ADB  # noqa: E402  -- devtools/device.py: adb with its -s, from devtools/device.json (NX2A_DEVICE wins)

TOOL = 'droidspaces_dev 0.1'
REMOTE = HERE / 'droidspaces_dev_remote.py'
SRC_REL = 'nxnative/dm'
DS_RUN = '/data/local/Droidspaces/bin/droidspaces run --'    # into the running container: its own entry, and no other
BRIDGE_TABLET = '/sdcard/Download/nx2a-dev'                   # the tablet's shared folder, where adb pushes ...
BRIDGE_CONTAINER = '/storage/emulated/0/Download/nx2a-dev'    # ... seen like this from inside the container
LIBRARY = '/opt/nx2a-data/library'
SOURCES = ('.c', '.S', '.cpp', '.cc', '.cxx')
PLAIN = re.compile(r'^[A-Za-z0-9._/+=,:@%\-]+$')
SECRETISH = re.compile(r'(\.keys?$|\.key$|\.pem$|\.p12$|credentials|^config\.json$)', re.I)
SYNC_VALIDATION = 'VALIDATION_CHECK_ENABLE_SYNCHRONIZATION_VALIDATION_EXT'
ISSUE = re.compile(r'validation error|VUID|SYNC-|hazard|validation layer|\[RED\]|CRASH sig|FATAL', re.I)
# The one [RED] line that is a known, deliberate state (the copy-based memory pool, kept until measurement says otherwise) -- it must
# not make a run look broken, and it must not be hidden either: the result says KNOWN-ONLY and names it
KNOWN_RED = re.compile(r'could not be zero-copy .*a GPU copy is refreshed before each submission')


class Fail(Exception):
    """The command cannot do what was asked; the message says what stands in the way."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_json(p):
    p = Path(p)
    return json.loads(p.read_text()) if p.is_file() else None


def save_json(p, obj):
    """A JSON file written whole or not at all."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + '\n')
    os.replace(tmp, p)


def plain(tok, what):
    """A word that needs no quoting anywhere: the only kind sent to the tablet."""
    tok = str(tok)
    if not PLAIN.match(tok) or '..' in tok.split('/'):
        raise Fail(f'{what} is not a plain word: {tok!r}', code=2)
    return tok


def gamedump():
    """The main checkout's .gamedump (git-ignored), from a worktree too."""
    common = subprocess.run(['git', 'rev-parse', '--git-common-dir'], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    return (REPO / common).resolve().parent / '.gamedump'


class Ctx:
    """One working set of places: the source set, the container's tree and build dir, the pack, the evidence folder."""

    def __init__(self, game='0100B99019412000', gfx='vk', app=None, ctr_dev='/opt/nx2a-data/dev', source_root=None, ev_root=None):
        self.game, self.gfx, self.app = game, gfx, app
        self.source_root = Path(source_root).resolve() if source_root else REPO
        self.ctr_dev = ctr_dev.rstrip('/')
        self.ctr_src = f'{self.ctr_dev}/src/{SRC_REL}'
        self.ctr_out = f'{self.ctr_dev}/out/{game}-{gfx}'
        self._ev_root = Path(ev_root).resolve() if ev_root else None

    @property
    def pack(self):
        return f'{LIBRARY}/{self.app}-data'

    @property
    def last_run_id(self):
        return (state(self).get('runs') or {}).get('last') if self.ev_root.exists() else None

    @property
    def ev_root(self):
        if self._ev_root is None:
            self._ev_root = gamedump() / self.app / 'linux-dev'
        return self._ev_root

    def ctr_run(self, run_id):
        return f'{self.ctr_dev}/runs/{run_id}'

    def with_(self, **kw):
        """The same places with some changed: what the selftest runs in."""
        c = Ctx.__new__(Ctx)
        c.__dict__.update(self.__dict__)
        if 'source_root' in kw:
            c.source_root = Path(kw.pop('source_root')).resolve()
        if 'ev_root' in kw:
            c._ev_root = Path(kw.pop('ev_root')).resolve()
        for k, v in kw.items():
            setattr(c, k, v)
        c.ctr_src = f'{c.ctr_dev}/src/{SRC_REL}'
        c.ctr_out = f'{c.ctr_dev}/out/{c.game}-{c.gfx}'
        return c


# ---- the tablet ------------------------------------------------------------------------------------
_INFO = {}



_ADB_EXE, _ADB_SERIAL = ADB[0], (ADB[2] if len(ADB) > 2 else None)   # the serial changes with wireless debugging's mDNS names


def adb_run(args, **kw):
    """One adb command. If the configured serial does not answer, the other connected serials are tried -- they are the same tablet, and the
    one that worked is kept for the rest of the process (the skill's rule: never trust a serial to survive). check=True raises on the final
    failure, like subprocess.run."""
    global _ADB_SERIAL
    check = kw.pop('check', False)

    def one(serial):
        argv = [_ADB_EXE] + (['-s', serial] if serial else []) + args
        return subprocess.run(argv, **kw)

    r = one(_ADB_SERIAL)
    if r.returncode != 0:
        have = [l.split('\t')[0] for l in subprocess.run([_ADB_EXE, 'devices'], capture_output=True, text=True).stdout.splitlines() if '\tdevice' in l]
        for s in have:
            if s == _ADB_SERIAL:
                continue
            r = one(s)
            if r.returncode == 0:
                print(f'(adb: the configured serial did not answer; using {s})')
                _ADB_SERIAL = s
                break
    if check and r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, args[:1] + ['...'])
    return r


def remote(ctx, *args, must=True, timeout=900):
    """One command of the container-side script. The script is pushed, then run by the container's own entry with plain arguments."""
    args = [plain(a, 'an argument for the container side') for a in args]
    adb_run(['shell', 'mkdir', '-p', BRIDGE_TABLET], capture_output=True, timeout=60)
    adb_run(['push', str(REMOTE), f'{BRIDGE_TABLET}/{REMOTE.name}'], capture_output=True, check=True, timeout=120)
    cmd = f'{DS_RUN} python3 {BRIDGE_CONTAINER}/{REMOTE.name} ' + ' '.join(args)
    if len(cmd) > 4000:   # adb resets the connection on a command of many kilobytes: a list goes in a file, never on the line
        raise Fail(f'the command for the container side is {len(cmd)} characters: too long -- send a file instead', code=2)
    r = adb_run(['shell', cmd], capture_output=True, text=True, errors='replace', timeout=timeout)
    line = (r.stdout.strip().splitlines() or [''])[-1]
    try:
        obj = json.loads(line)
    except ValueError:
        raise Fail(f'the container side did not answer in JSON (adb exit {r.returncode}): {(r.stdout + r.stderr)[-700:].strip()!r}')
    if must and obj.get('ok') is not True:
        raise Fail(obj.get('error') or ('the container side answered without an ok: ' + json.dumps(obj, sort_keys=True)[:600]))
    return obj


def info(ctx):
    """What the container side reports about itself: its places, the packs, the two environments, the toolchain's files."""
    if ctx.ctr_dev not in _INFO:
        _INFO[ctx.ctr_dev] = remote(ctx, 'info', ctx.ctr_dev, timeout=120)
    return _INFO[ctx.ctr_dev]


def resolve_app(ctx):
    """The pack's name: the one pack whose env.txt names this game."""
    hits = [p for p in info(ctx)['packs'] if ctx.game in (p['env_first_line'] or '')]
    if len(hits) != 1:
        raise Fail('no pack in /opt/nx2a-data/library names the game ' + ctx.game + ': ' + str([p['pack'] for p in info(ctx)['packs']])
                   + ' (port it first, or name --app)', code=2)
    return hits[0]['app']


def push(local, name):
    adb_run(['push', str(local), f'{BRIDGE_TABLET}/{name}'], capture_output=True, check=True, timeout=900)


def pull(name, local):
    adb_run(['pull', f'{BRIDGE_TABLET}/{name}', str(local)], capture_output=True, check=True, timeout=900)


def bridge_rm(name):
    adb_run(['shell', 'rm', '-f', f'{BRIDGE_TABLET}/{name}'], capture_output=True, timeout=60)


def fetch_dir(ctx, ctr_dir, local):
    """A folder of the container's (a build's, a run's) copied into the evidence: tarred there, pulled over the shared folder."""
    name = f'{os.getpid()}-{int(time.time() * 1000)}-{Path(ctr_dir).name}.tgz'
    remote(ctx, 'pack', ctr_dir, f'{BRIDGE_CONTAINER}/{name}', timeout=300)
    tmp = local.parent / f'.{name}'
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        pull(name, tmp)
        bridge_rm(name)
        with tarfile.open(tmp, 'r:gz') as tf:
            tf.extractall(local.parent, filter='data')
    finally:
        tmp.unlink(missing_ok=True)


def screenshot(path):
    r = adb_run(['exec-out', 'screencap', '-p'], capture_output=True, timeout=60)
    if not r.stdout.startswith(b'\x89PNG'):
        raise Fail(f'screencap gave no PNG: {r.stderr[:200]!r}')
    path.write_bytes(r.stdout)
    return len(r.stdout)


# ---- the source set ---------------------------------------------------------------------------------
def in_set(rel, game):
    if not rel or rel.startswith('/') or '..' in rel.split('/'):
        return False
    if rel.startswith('games/'):                      # under games/: this game's profile, and what lies directly in games/
        rest = rel[len('games/'):]
        return '/' not in rest or rest.startswith(f'{game}/')
    return True


def source_set(ctx):
    """The files of the source set, relative to nxnative/dm: tracked and new, not ignored (in a copy: what is on disk)."""
    root = ctx.source_root
    if root == REPO:
        listed = set()
        for extra in (['ls-files', '-z', '--', SRC_REL], ['ls-files', '-z', '--others', '--exclude-standard', '--', SRC_REL]):
            r = subprocess.run(['git', *extra], cwd=REPO, capture_output=True, check=True)
            listed.update(p for p in r.stdout.decode('utf-8', 'replace').split('\0') if p)
        files = sorted(p[len(SRC_REL) + 1:] for p in listed if p.startswith(SRC_REL + '/') and in_set(p[len(SRC_REL) + 1:], ctx.game))
    else:
        base = root / SRC_REL
        files = sorted(str(p.relative_to(base)) for p in base.rglob('*') if p.is_file() and in_set(str(p.relative_to(base)), ctx.game))
    bad = [f for f in files if SECRETISH.search(os.path.basename(f))]
    if bad:
        raise Fail('not shipped, they look like credentials: ' + ', '.join(bad[:5]), code=2)
    links = [f for f in files if (root / SRC_REL / f).is_symlink()]
    if links:
        raise Fail('symbolic links are not shipped (the container tree is a plain copy): ' + ', '.join(links[:5]), code=2)
    return files


def manifest(ctx, files):
    root = ctx.source_root / SRC_REL
    return {f: {'sha256': sha256_file(root / f), 'size': (root / f).stat().st_size} for f in files}


def digest_of(man):
    return hashlib.sha256(''.join(f'{f}\0{v["sha256"]}\n' for f, v in sorted(man.items())).encode()).hexdigest()


def current(ctx):
    """(files, manifest, digest) of the source set as it is now."""
    files = source_set(ctx)
    man = manifest(ctx, files)
    return files, man, digest_of(man)


def commit_info(ctx):
    if ctx.source_root != REPO:
        return {'commit': None, 'branch': None, 'dirty': ['(a copy of the source set, not a checkout)']}
    g = lambda *a: subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return {'commit': g('rev-parse', 'HEAD').strip(), 'branch': g('rev-parse', '--abbrev-ref', 'HEAD').strip(),
            'dirty': [l for l in g('status', '--porcelain', '--', SRC_REL).splitlines() if l.strip()]}


def game_info(ctx):
    """The game's name and versions from its profile (games/<title>/game.tsv)."""
    rows = {}
    for l in (ctx.source_root / SRC_REL / 'games' / ctx.game / 'game.tsv').read_text(errors='replace').splitlines():
        if '\t' in l and not l.startswith('#'):
            k, v = l.split('\t', 1)
            rows[k] = v
    return {'title_id': ctx.game, 'name': rows.get('name'), 'versions': {k: v for k, v in rows.items() if 'version' in k.lower()}}


def write_tar(tgz, root, files):
    with tarfile.open(tgz, 'w:gz') as tf:
        for f in files:
            ti = tf.gettarinfo(str(root / f), arcname=f)
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = ''
            with open(root / f, 'rb') as fh:
                tf.addfile(ti, fh)


# ---- state and evidence ----------------------------------------------------------------------------
def state(ctx):
    return load_json(ctx.ev_root / 'state.json') or {}


def save_state(ctx, st):
    save_json(ctx.ev_root / 'state.json', st)


def print_places(ctx):
    inf = info(ctx)
    n = state(ctx).get('last_sync', {}).get('files', '?')
    print(f'source set    : {ctx.source_root / SRC_REL}   ({n} files as last synced; other games\' profiles left out)')
    print(f'container tree: {ctx.ctr_src}   (the one tree the host is built from)')
    print(f'build dir     : {ctx.ctr_out}')
    print(f'pack          : {ctx.pack}   (profile/, mods/ = the rewritten modules, run.sh = the launcher\'s entry, host/dmhost = the installed host)')
    print(f'build env     : {inf["env_build"]}')
    print(f'run env       : {inf["env_run"]}')
    print(f'evidence      : {ctx.ev_root}')


def do_sync(ctx):
    """Make the container tree equal to the source set; only what differs is sent."""
    files, man, digest = current(ctx)
    old = load_json(ctx.ev_root / 'synced.json')
    changed = [f for f in files if not old or f not in old['files'] or old['files'][f]['sha256'] != man[f]['sha256']]
    removed = [f for f in old['files'] if f not in man] if old else []
    tag = f'{os.getpid()}-{int(time.time() * 1000)}'
    tmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-'))
    try:
        tgz, manf = tmp / f'sync-{tag}.tar.gz', tmp / f'sync-{tag}.json'
        write_tar(tgz, ctx.source_root / SRC_REL, changed)
        save_json(manf, {'digest': digest, 'files': man})
        push(tgz, tgz.name)
        push(manf, manf.name)
        res = remote(ctx, 'apply', f'{BRIDGE_CONTAINER}/{tgz.name}', f'{BRIDGE_CONTAINER}/{manf.name}', ctx.ctr_src, timeout=900)
        bridge_rm(tgz.name)
        bridge_rm(manf.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ctx.ev_root.mkdir(parents=True, exist_ok=True)
    save_json(ctx.ev_root / 'synced.json', {'time': now_iso(), 'digest': digest, 'files': man})
    st = state(ctx)
    st['last_sync'] = {'time': now_iso(), 'digest': digest, 'files': len(files), 'bytes': sum(v['size'] for v in man.values()),
                       'shipped': len(changed), 'copied': res['copied'], 'removed': removed}
    save_state(ctx, st)
    return st['last_sync'], digest


def do_build(ctx, clean=False, install=True, jobs=8):
    """Build the host from the container tree; install it into the pack when it is whole. Returns (exit code, test id, result)."""
    files, man, digest = current(ctx)
    st = state(ctx)
    ls = st.get('last_sync')
    if not ls or ls['digest'] != digest:
        raise Fail('the sources are not what was synced last: run  sync  first' if ls else 'nothing was synced yet: run  sync  first', code=2)
    bid = f'B{stamp()}-{digest[:8]}'
    ev = ctx.ev_root / bid
    ev.mkdir(parents=True, exist_ok=False)
    ctr_run = ctx.ctr_run(bid)
    print_places(ctx)
    print(f'build {bid}: {len(files)} sources, digest {digest[:16]}')
    ci, gi = commit_info(ctx), game_info(ctx)
    rq = {'dev': ctx.ctr_dev, 'src': ctx.ctr_src, 'out': ctx.ctr_out, 'run_dir': ctr_run, 'game': ctx.game, 'gfx': ctx.gfx, 'jobs': jobs,
          'release': True, 'clean': clean, 'test_id': bid, 'commit': ci['commit'], 'dirty': ci['dirty']}
    name = f'{bid}.build-request.json'
    tmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-'))
    try:
        save_json(tmp / name, rq)
        push(tmp / name, name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        res = watch_build(ctx, ctr_run, f'{BRIDGE_CONTAINER}/{name}')
    finally:
        bridge_rm(name)
    since = res.get('since') or []
    if res.get('restarted'):
        print('  the build directory held objects with no record of their sources: started over (every source compiled again)')
    print(f'  changed since the last whole build: {len(since)}' + (': ' + ', '.join(since[:10]) + (' ...' if len(since) > 10 else '') if since else ''))
    if res.get('rc') is None:   # not as far as build.py: the tree was not what was synced, or the start failed
        save_json(ev / 'sources.json', {'digest': digest, 'files': man})
        save_json(ev / 'build-result.json', res)
        st['last_build'] = {'id': bid, 'time': now_iso(), 'ok': False, 'digest': digest, 'gfx': ctx.gfx, 'out': ctx.ctr_out,
                            'installed': False, 'error': res.get('error'), 'evidence': str(ev)}
        save_state(ctx, st)
        print(f"BUILD-FAILED {bid}: {res.get('error')}")
        for m in res.get('mismatched') or []:
            print('  ' + m)
        return 1, bid, res
    ins = remote(ctx, 'install', ctx.ctr_out, ctx.pack, ctr_run, must=False, timeout=300) if res.get('ok') and install else None
    fetch_dir(ctx, ctr_run, ev)
    ident = remote(ctx, 'ident', ctx.pack, ctx.ctr_out, timeout=600)
    save_json(ev / 'sources.json', {'digest': digest, 'files': man})
    save_json(ev / 'ident.json', ident)
    ok = bool(res.get('ok')) and (ins is None or bool(ins.get('ok')))
    record = {'tool': TOOL, 'test_id': bid, 'time': now_iso(), 'commit': ci, 'source_digest': digest, 'source_files': len(files),
              'changed_since_last_build': since, 'game': gi, 'build': {'cmd': res.get('cmd'), 'gfx': ctx.gfx, 'release': True, 'clean': clean,
              'jobs': jobs, 'container_out': ctx.ctr_out, 'container_src': ctx.ctr_src, 'env': info(ctx)['env_build'],
              'toolchain_clang': info(ctx).get('toolchain_clang')},
              'result': {k: res.get(k) for k in ('ok', 'rc', 'linked', 'seconds', 'objects_before', 'objects_total', 'objects_rebuilt',
                                                 'stale_sources', 'sources_without_object', 'errors', 'binary')},
              'install': {k: (ins or {}).get(k) for k in ('ok', 'host', 'previous', 'error')},
              'container': {'pack': ctx.pack, 'entry': ctx.pack + '/run.sh', 'profile': ctx.pack + '/profile/' + ctx.game,
                            'module': ctx.pack + '/mods', 'installed_host': ctx.pack + '/host/dmhost', 'run_dir': ctr_run},
              'parts': {k: ident.get(k) for k in ('installed_host', 'built_host', 'mods', 'mods_build_src', 'env_txt')},
              'scripts': {'droidspaces_dev.py': sha256_file(__file__), 'droidspaces_dev_remote.py': sha256_file(REMOTE)}}
    save_json(ev / 'manifest.json', record)
    st = state(ctx)
    st['last_build'] = {'id': bid, 'time': now_iso(), 'ok': ok, 'digest': digest, 'gfx': ctx.gfx, 'out': ctx.ctr_out,
                        'installed': bool(ins and ins.get('ok')), 'binary_sha256': (res.get('binary') or {}).get('sha256'),
                        'host_sha256': (ins.get('host') or {}).get('sha256') if ins else None, 'evidence': str(ev)}
    save_state(ctx, st)
    r = res
    print(f"  build.py: exit {r.get('rc')}, {r.get('seconds')} s; objects made again: {r.get('objects_rebuilt')} of {r.get('objects_total')}"
          + (f" (clean build)" if clean else ''))
    if r.get('rebuilt'):
        print('  ' + '\n  '.join(r['rebuilt'][:24]) + (f'\n  ... {len(r["rebuilt"]) - 24} more' if len(r['rebuilt']) > 24 else ''))
    if r.get('stale_sources'):
        print(f"  [STALE] changed sources whose object was not made again: {r['stale_sources']}")
    if r.get('sources_without_object'):
        print(f"  (not in what build.py compiles here: {r['sources_without_object']})")
    if ins:
        print(f"  installed as {ctx.pack}/host/dmhost: {ins['host']['sha256'][:16]} (was {(ins.get('previous') or {}).get('sha256', 'nothing')[:16]})" if ins.get('ok')
              else f"  [FAILED] not installed: {ins.get('error')}")
    if ok:
        b = r['binary']
        print(f"BUILD-OK {bid}: host {b['sha256'][:16]} ({b['size']} bytes), source {digest[:16]}"
              + ('' if not install else ', installed into the pack'))
        return 0, bid, res
    print(f"BUILD-FAILED {bid}: the previous host in the pack is untouched and will not be run as this build (run refuses until a build is whole)")
    for e in r.get('errors') or []:
        print('  ' + e)
    if not r.get('linked') and r.get('rc') == 0:
        print('  build.py exited 0 but linked no new ELF')
    print(f'  full log: {ev / "build.log"}')
    return 1, bid, res


def watch_build(ctx, ctr_run, request):
    """Start the build detached in the container, then ask short questions until its answer is there. A call that gets no answer is
    tried again: the build goes on in the container whatever happens to the adb connection."""
    start = remote(ctx, 'build-start', request, must=False, timeout=300)
    if not start.get('ok'):
        return dict(start, rc=None, linked=False)
    print(f"  build.py started in the container: pid {start['pid']}, log {ctr_run}/build.log")
    lost, waited, finished_here = 0, 0.0, False
    while True:
        try:
            st = remote(ctx, 'build-state', ctr_run, timeout=120)
            lost = 0
        except Fail as e:
            lost += 1
            if lost >= 10:
                raise Fail(f'no answer from the container during the build ({e}); the build goes on there: its log is {ctr_run}/build.log')
            time.sleep(3)
            continue
        if st.get('result'):
            return st['result']
        if not st.get('running') and st.get('rc') is not None and not finished_here:
            remote(ctx, 'build-finish', f'{ctr_run}/build-request.json', must=False, timeout=300)   # the launch script was lost after build.py
            finished_here = True
            continue
        if not st.get('running') and waited > 3:
            raise Fail(f"the build's process is gone and left no exit status (log: {ctr_run}/build.log, {st.get('log_bytes')} bytes)")
        time.sleep(2)
        waited += 2
        if waited > 5400:
            raise Fail(f'the build has been going for {waited / 60:.0f} minutes: given up watching (it goes on: {ctr_run}/build.log)')


def preconditions(ctx, allow_stale):
    """What must hold before a run: the last build is whole and installed, and it is made from the sources as they are now."""
    st = state(ctx)
    lb = st.get('last_build')
    if not lb:
        raise Fail('nothing was built yet: run  build  first', code=2)
    if not lb['ok']:
        raise Fail(f"the last build ({lb['id']}) failed: nothing was installed, and the host installed before it is not to be run as if "
                   'it were that build -- fix the sources and build again (--allow-stale starts what is installed, and says so)', code=2)
    if not lb.get('installed'):
        raise Fail(f"build {lb['id']} was made with --no-install: the pack's run.sh would start another host -- build again without it", code=2)
    _, _, digest = current(ctx)
    if digest != lb['digest'] and not allow_stale:
        raise Fail(f"the sources changed since build {lb['id']} was made: build first (--allow-stale starts that build anyway, and says so)", code=2)
    ident = remote(ctx, 'ident', ctx.pack, lb['out'], timeout=600)
    have = (ident.get('installed_host') or {}).get('sha256')
    if have != lb['host_sha256'] and not allow_stale:
        raise Fail(f"the pack's host/dmhost is not the host of build {lb['id']} -- something else installed one: build again", code=2)
    return st, lb, digest, ident


def remote_status(ctx, run_id):
    return remote(ctx, 'status', ctx.ctr_dev, run_id, timeout=120)


def do_run(ctx, a):
    """Start the pack's run.sh in the given mode, take the screenshots asked for, wait for the end, collect."""
    st, lb, digest, ident = preconditions(ctx, a.allow_stale)
    if a.allow_stale:
        print(f"WARNING --allow-stale: starting the host of build {lb['id']} whatever the sources are now"
              + ('' if digest == lb['digest'] else f' (they changed: {digest[:16]} against {lb["digest"][:16]})'))
    n = st.get('runs', {}).get('count', 0) + 1
    run_id = f"{lb['id']}/run-{n:02d}"
    ev_run = ctx.ev_root / lb['id'] / f'run-{n:02d}'
    (ev_run / 'shots').mkdir(parents=True, exist_ok=True)
    extra = {}
    for kv in a.env or []:
        k, sep, v = kv.partition('=')
        if not sep or not re.match(r'^[A-Z][A-Z0-9_]*$', k):
            raise Fail(f'--env takes KEY=VALUE with KEY an upper-case name: {kv!r}', code=2)
        extra[k] = plain(v, 'the value of ' + k)
    if a.mode == 'testcard':
        extra.setdefault('DM_VK_TESTCARD', str(a.testcard_ms))
        if a.script:
            extra['DM_VK_TESTCARD_SCRIPT'] = '1'
    if a.validate:
        extra['DM_VK_VALIDATE'] = '1'
    if a.sync_validation:
        extra['VK_LAYER_ENABLES'] = SYNC_VALIDATION
    if a.mode == 'game' and a.shot_frames:
        extra['DM_VK_SHOT'] = plain(a.shot_frames, '--shot-frames')
        extra['DM_VK_SHOT_DIR'] = ctx.ctr_run(run_id)
    host = ident['installed_host']
    ci = commit_info(ctx)
    commit = (ci['commit'] or 'none')[:12] + (' (with uncommitted changes)' if ci['dirty'] else '')
    header = [f'# nx2a-dev run {run_id}',
              f'# build {lb["id"]}: source {lb["digest"][:16]}, host {host["sha256"][:16]}, commit {commit}',
              f'# mode {a.mode}, {a.seconds} s limit; entry {ctx.pack}/run.sh; the environment: launch.sh beside this log',
              '# environment added: ' + ' '.join(f'{k}={v}' for k, v in sorted(extra.items()))]
    name = run_id.replace('/', '-') + '.header.txt'
    # The pad-state file starts empty BEFORE the launch: it is the pad's CURRENT state snapshot, and the init replay of a
    # leftover file would hold old buttons down from the first frame (a late reset cannot undo what the game already read)
    rtmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-'))
    try:
        (rtmp / 'reset.cmd').write_text('')
        push(rtmp / 'reset.cmd', 'reset.cmd')
        adb_run(['shell', f'{DS_RUN} bash -c "cat {BRIDGE_CONTAINER}/reset.cmd > {ctx.ctr_dev}/pad.cmd"'], capture_output=True, check=True, timeout=60)
        bridge_rm('reset.cmd')
    except (Fail, subprocess.SubprocessError, OSError) as e:
        print(f'  (pad-state reset failed: {e}; the run continues)')
    finally:
        shutil.rmtree(rtmp, ignore_errors=True)
    tmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-'))
    try:
        (tmp / name).write_text('\n'.join(header) + '\n')
        push(tmp / name, name)
        rec = remote(ctx, 'launch', ctx.ctr_dev, run_id, ctx.pack, str(a.seconds), a.mode, f'{BRIDGE_CONTAINER}/{name}',
                     *[f'{k}={v}' for k, v in sorted(extra.items())], timeout=180)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        bridge_rm(name)
    save_json(ev_run / 'launch.json', {'run_id': run_id, 'launched': now_iso(), 'remote': rec, 'extra_env': extra, 'commit': ci,
                                       'source_digest': lb['digest'], 'allow_stale': a.allow_stale, 'validate': bool(a.validate),
                                       'sync_validation': bool(a.sync_validation), 'mode': a.mode, 'seconds': a.seconds})
    st = state(ctx)
    st['runs'] = {'count': n, 'last': run_id}
    save_state(ctx, st)
    print(f'run {run_id}: started, pid {rec["pid"]}, {a.seconds} s limit, mode {a.mode}, host {host["sha256"][:16]} (build {lb["id"]})')
    print(f'  entry {ctx.pack}/run.sh; the launch record (environment and command): {rec["run_dir"]}/launch.sh')
    print(f'  log (in the container): {rec["run_dir"]}/run.log; evidence: {ev_run}')
    t0, over, polled = time.time(), None, -99.0
    for t in a.shots:                                   # each screenshot at its seconds after the launch
        while time.time() - t0 < t and over is None:
            if time.time() - polled >= 2.0:             # a run that ended early (a crash) is not worth waiting for
                polled = time.time()
                over = ended_state(remote_status(ctx, run_id))
            time.sleep(0.2)
        if over is not None:
            break
        p = ev_run / 'shots' / f't+{time.time() - t0:05.1f}s.png'
        print(f'  screenshot {p.name}: {screenshot(p)} bytes')
    deadline = time.time() + a.seconds + 40
    while over is None and a.wait and time.time() < deadline:
        over = ended_state(remote_status(ctx, run_id))
        if over is None:
            time.sleep(1.0)
    do_collect(ctx, run_id)


def ended_state(status):
    """The run's state once it has ended (not alive, and an exit status written); None while it goes on."""
    return None if status.get('alive') or status.get('exit') is None else status


def summarize(ev_run, status):
    """The facts of a run, from its exit status and its log: an outcome, counts with the evidence they rest on, a result word."""
    launch = load_json(ev_run / 'launch.json') or {}
    log = ev_run / 'run.log'
    text = log.read_text(errors='replace') if log.is_file() else ''
    lines = text.splitlines()
    c = {k: sum(1 for l in lines if p in l) for k, p in
         (('validation error', 'validation error'), ('VUID', 'VUID'), ('sync/hazard', 'SYNC-'), ('[RED]', '[RED]'), ('CRASH/FATAL', 'CRASH sig'))}
    c['sync/hazard'] += sum(1 for l in lines if 'hazard' in l.lower())
    c['CRASH/FATAL'] += sum(1 for l in lines if 'FATAL' in l)
    layer = next((l.strip() for l in lines if 'validation layer on' in l), None)
    asked = bool(launch.get('validate'))
    ended = (not status.get('alive')) and status.get('exit') is not None
    ex = status.get('exit')
    code = int(ex.split()[-1]) if ex and ex.split()[-1].isdigit() else None
    if not ended:
        outcome = 'still running (no exit status yet)'
    elif status.get('stopped'):
        outcome = f'ended by this tool\'s stop (the launch script recorded "{ex}")'
    elif code == 124:
        outcome = f'ran out of its time limit of {status.get("seconds")} s (exit 124)'
    elif code is not None and code >= 128:
        outcome = f'ended by signal {code - 128} (exit {code})'
    else:
        outcome = f'ended by itself ("{ex}")' + (', through the host\'s graceful exit' if any('graceful exit done' in l for l in lines) else '')
    frames = sum(1 for l in lines if 'presented (vkQueuePresentKHR' in l)
    if not ended:
        result = 'INCOMPLETE'
    elif asked and not layer:
        result = 'INCOMPLETE'
    elif not asked:
        result = 'ISSUES' if c['[RED]'] or c['CRASH/FATAL'] or (code is not None and code >= 128) else 'UNVALIDATED'
    else:
        result = 'CLEAN' if not any(c.values()) and not (code is not None and code >= 128) else 'ISSUES'
    if result == 'ISSUES' and c['CRASH/FATAL'] == 0 and not (code is not None and code >= 128):
        reds = [l for l in lines if '[RED]' in l]
        if reds and all(KNOWN_RED.search(l) for l in reds):
            result = 'KNOWN-ONLY'   # every [RED] is the copy-pool notice: expected in this build, said out loud, not counted as a defect
    issues = [l for l in lines if ISSUE.search(l)]
    (ev_run / 'validation.log').write_text(
        f'# run {launch.get("run_id")}: every line of run.log from the validation layer, with [RED], CRASH and FATAL lines\n'
        f'# validation asked for: {"yes" if asked else "no"}; the layer said it was on: {layer or "it did not"}\n'
        f'# run ended: {"yes" if ended else "NO -- the log is partial"}; exit status: {ex}\n'
        f'# counts: ' + ', '.join(f'{k} {v}' for k, v in c.items()) + '\n\n' + '\n'.join(issues) + ('\n' if issues else ''))
    (ev_run / 'issues.txt').write_text('\n'.join(l for l in issues if 'validation error' not in l and 'VUID' not in l) + '\n')
    (ev_run / 'exit.txt').write_text((ex or '(no exit status: the run has not ended)\n') + '\n')
    shots = sorted(p.name for p in (ev_run / 'shots').glob('*.png'))
    out = {'outcome': outcome, 'result': result, 'counts': c, 'layer': layer, 'asked': asked, 'ended': ended, 'exit': ex, 'lines': len(lines),
           'frames': frames, 'shots': shots, 'pid': status.get('pid')}
    text = (f"run {launch.get('run_id')}: {outcome}\n"
            f"  pid {out['pid']}; run.log {len(lines)} lines ({'complete: the process ended' if ended else 'PARTIAL: still running'})\n"
            f"  validation: {'asked for; the layer: ' + (layer or 'never said it was on') if asked else 'not asked for (the result is not called clean)'}\n"
            f"  counts: " + ', '.join(f'{k} {v}' for k, v in c.items()) + f"; frames reported presented: {frames}\n"
            f"  result: {result}\n"
            f"  screenshots: {len(shots)}" + (f' ({", ".join(shots)})' if shots else '') + '\n'
            f"  evidence: {ev_run}  (run.log, validation.log, issues.txt, exit.txt, summary.txt, launch.sh, shots/)\n")
    (ev_run / 'summary.txt').write_text(text)
    print(text, end='')
    return out


PAD_CODES = {'a': 304, 'b': 305, 'x': 306, 'y': 307, 'l': 310, 'r': 311, 'zl': 312, 'zr': 313,
             'minus': 314, 'plus': 315, 'l3': 317, 'r3': 318}


def do_press(ctx, a):
    """Append key lines for the named buttons to the running game's pad-command file, hold, release. The append goes through this
    tool's adb path (serial fallback, errors visible): a silent failure here would look exactly like 'the game ignored input'."""
    if not ctx.last_run_id:
        raise Fail('no run to press buttons for', code=2)
    names = [s.strip().lower() for s in (a.buttons or '').split(',') if s.strip()]
    codes = []
    for nm in names:
        if nm not in PAD_CODES:
            raise Fail(f'unknown button {nm!r} (known: {", ".join(sorted(PAD_CODES))})', code=2)
        codes.append(PAD_CODES[nm])
    if not codes:
        raise Fail('no buttons named', code=2)
    # The pad state file is a SNAPSHOT of the held buttons (the front re-reads the whole file on every change): write the
    # held state, wait the hold, write the all-released state
    hold = float(a.hold)
    rdir = f'{ctx.ctr_dev}/runs/{ctx.last_run_id}'
    st = remote(ctx, 'status', ctx.ctr_dev, ctx.last_run_id, timeout=60)
    if not st.get('exists'):
        raise Fail(f'run {ctx.last_run_id}: the run folder is gone', code=2)
    lines = ''.join(f'key {c} 1\n' for c in codes)
    tmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-'))
    try:
        (tmp / 'snap.cmd').write_text(lines)
        push(tmp / 'snap.cmd', 'snap.cmd')
        inner = f'cp {BRIDGE_CONTAINER}/snap.cmd {rdir}/pad.cmd'
        adb_run(['shell', f'{DS_RUN} bash -c "{inner}"'], capture_output=True, check=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        bridge_rm('snap.cmd')
    print(f'pressed {",".join(names)} for {hold} s (run {ctx.last_run_id})')
    time.sleep(hold)
    tmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-'))
    try:
        (tmp / 'snap.cmd').write_text('')
        push(tmp / 'snap.cmd', 'snap.cmd')
        inner = f'cp {BRIDGE_CONTAINER}/snap.cmd {rdir}/pad.cmd'
        adb_run(['shell', f'{DS_RUN} bash -c "{inner}"'], capture_output=True, check=True, timeout=120)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        bridge_rm('snap.cmd')
    print(f'released (pad state reset)')
    return 0


def last_run(ctx):
    """The run id of the last run this tool started."""
    return (state(ctx).get('runs') or {}).get('last') or state(ctx).get('last_run')


def do_collect(ctx, run_id, shot=False):
    if not run_id:
        run_id = last_run(ctx)
    if not run_id:
        raise Fail('no run was started by this tool yet: nothing to collect', code=2)
    run_id = plain(run_id, '--run')
    ev_run = ctx.ev_root / run_id
    if not ev_run.is_dir():
        raise Fail(f'{run_id} is not a run of this tool (no {ev_run})', code=2)
    status = remote_status(ctx, run_id)
    if shot:
        p = ev_run / 'shots' / f'now-{stamp()}.png'
        (ev_run / 'shots').mkdir(parents=True, exist_ok=True)
        print(f'  screenshot {p.name}: {screenshot(p)} bytes')
    fetch_dir(ctx, ctx.ctr_run(run_id), ev_run)
    save_json(ev_run / 'status.json', status)
    return summarize(ev_run, status)


def do_stop(ctx, wait=20):
    run_id = last_run(ctx)
    if not run_id:
        raise Fail('no run was started by this tool yet: nothing to stop', code=2)
    res = remote(ctx, 'stop', ctx.ctr_dev, run_id, str(wait), timeout=wait + 60)   # an error here is a failure, not a note
    if res.get('note'):
        print(f"run {run_id}: {res['note']}" + (f" (exit {res['exit']})" if res.get('exit') else ''))
    else:
        print(f"run {run_id}: pid {res['pid']}: SIGTERM to {res['signalled_term']}"
              + (f", then SIGKILL to {res['signalled_kill']}" if res.get('signalled_kill') else '')
              + f" -- {'ended' if res.get('ok') else 'STILL ALIVE'} in {res.get('seconds')} s")
    print('  (only the recorded run\'s own processes were signalled; the launch script was left to write the exit status)')
    time.sleep(0.5)
    do_collect(ctx, run_id)


def cmd_status(ctx):
    st = state(ctx)
    print_places(ctx)
    ls, lb, runs = st.get('last_sync'), st.get('last_build'), st.get('last_run')
    print(f"last sync  : {ls['time'] if ls else 'none'}" + (f", {ls['files']} files, digest {ls['digest'][:16]}" if ls else ''))
    if lb:
        print(f"last build : {lb['id']} {'ok' if lb['ok'] else 'FAILED'} at {lb['time']}, host {(lb.get('binary_sha256') or 'none')[:16]}"
              + (', installed into the pack' if lb.get('installed') else ', not installed'))
    else:
        print('last build : none')
    if runs:
        s = remote_status(ctx, runs)
        print(f"last run   : {runs}: {'running, pid ' + str(s['pid']) if s['alive'] else 'not running'}; exit {s['exit'] or '(none yet)'}"
              + ('; stopped by this tool' if s.get('stopped') else ''))
    _, _, digest = current(ctx)
    if lb and lb.get('digest') != digest:
        print(f"note: the sources differ from what the last build was made of ({digest[:16]} against {lb['digest'][:16]}): build before running")
    print(f'evidence   : {ctx.ev_root}')


def cmd_selftest(ctx, jobs=8):
    """A build that is made to fail, in places of its own: it must be reported failed, install nothing, touch nothing else, and be
    refused by run afterwards."""
    results = []

    def check(name, ok, detail=''):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  -- {detail}' if detail else ''))

    print_places(ctx)
    real_pack, real_out = ctx.pack, ctx.ctr_out
    before = remote(ctx, 'ident', real_pack, real_out, timeout=600)
    tree_before = remote(ctx, 'verify', ctx.ctr_src, must=False, timeout=300)
    files_bytes = {n: (Path(p).read_bytes() if Path(p).is_file() else None) for n, p in
                   (('state', ctx.ev_root / 'state.json'), ('synced', ctx.ev_root / 'synced.json'))}
    tmp = Path(tempfile.mkdtemp(prefix='nx2a-dev-selftest-'))
    iso = None
    try:
        files = source_set(ctx)
        root = tmp / 'src' / SRC_REL
        for f in files:
            (root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ctx.source_root / SRC_REL / f, root / f)
        victim = 'linux/front_linux.c'
        (root / victim).write_text('#error droidspaces_dev selftest: a deliberate compile error\n' + (root / victim).read_text())
        iso = ctx.with_(source_root=str(tmp / 'src'), ctr_dev='/opt/nx2a-data/dev-selftest', ev_root=str(tmp / 'state'))
        check('the selftest has places of its own', iso.ctr_src != ctx.ctr_src and iso.ctr_out != ctx.ctr_out and iso.ev_root != ctx.ev_root,
              f'{iso.ctr_dev}')
        do_sync(iso)
        print(f'synced the copy ({len(files)} files, one with a deliberate compile error) to {iso.ctr_src}')
        rc, bid, res = do_build(iso, clean=False, install=False, jobs=jobs)
        ev = iso.ev_root / bid
        errors = res.get('errors') or []
        check('a build that fails is reported as failed (exit code != 0, ok false)', rc != 0 and res.get('ok') is False and res.get('rc') != 0)
        check("the compiler's own words are on record", any('selftest' in e for e in errors) and (ev / 'build.log').is_file()
              and (ev / 'build.log').stat().st_size > 0, (errors[0][:110] if errors else 'no error line found'))
        check('no host came out of it', not res.get('linked') and not (load_json(ev / 'manifest.json') or {}).get('install', {}).get('ok'))
        after = remote(ctx, 'ident', real_pack, real_out, timeout=600)
        same = (before.get('installed_host') or {}).get('sha256') == (after.get('installed_host') or {}).get('sha256')
        check("the pack's installed host is the same file as before", same, (after.get('installed_host') or {}).get('sha256', 'none')[:16])
        tree_after = remote(ctx, 'verify', ctx.ctr_src, must=False, timeout=300)
        if tree_before.get('ok'):
            check('the real container tree is untouched (still what was synced, file for file)', tree_after.get('ok') is True, f"{tree_after.get('files')} files")
        else:
            print(f"SKIP  the real container tree was not in a synced state before the selftest ({tree_before.get('error')}): not compared")
        same_files = all((Path(p).read_bytes() if Path(p).is_file() else None) == b for b, p in
                         ((files_bytes['state'], ctx.ev_root / 'state.json'), (files_bytes['synced'], ctx.ev_root / 'synced.json')))
        check("the real workspace's state (last sync, last build) is untouched", same_files)
        check('the checkout is untouched (the copy carried the error, not the checkout)', 'selftest' not in (ctx.source_root / SRC_REL / victim).read_text())
        refused = None
        try:
            preconditions(iso, allow_stale=False)
        except Fail as e:
            refused = str(e)
        check('run refuses to start the previous host after a failed build', refused is not None and 'failed' in refused, (refused or 'it did not refuse')[:120])
    finally:
        if iso is not None:
            gone = remote(ctx, 'rmtree', iso.ctr_dev, must=False, timeout=300)
            print(f"removed the selftest's places in the container: {'yes' if gone.get('ok') else gone.get('error')}")
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"selftest: {sum(results)} of {len(results)} checks passed")
    return 0 if results and all(results) else 1


# ---- the entry -------------------------------------------------------------------------------------
def main(argv):
    ap = argparse.ArgumentParser(prog='devtools/droidspaces_dev.py', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p):
        p.add_argument('--game', default='0100B99019412000', help='the title ID (default %(default)s)')
        p.add_argument('--app', default=None, help="the pack's name without -data (default: the pack whose env.txt names the game)")
        p.add_argument('--ctr-dev', default='/opt/nx2a-data/dev', help='the tool\'s folder in the container (default %(default)s)')
        p.add_argument('--state-dir', default=None, help='where the state and evidence go (default .gamedump/<App>/linux-dev)')
        p.add_argument('--source-root', default=None, help='the checkout the source set is read from (default this one)')

    common(sub.add_parser('sync', help='make the container tree equal to the source set (only what differs is sent)'))
    p = sub.add_parser('build', help='build the host on the container tree, incrementally; install it into the pack when it is whole')
    common(p)
    p.add_argument('--clean', action='store_true', help='remove the build directory first: every source compiled again')
    p.add_argument('--gfx', choices=['vk', 'null'], default='vk', help='the graphics backend (default %(default)s; its own build directory)')
    p.add_argument('--jobs', type=int, default=8, help='compile at once (default %(default)s)')
    p.add_argument('--no-install', action='store_true', help='build only: the pack keeps the host it has (run will not start this build)')
    p = sub.add_parser('run', help='start the pack\'s run.sh: the test card or the game')
    common(p)
    p.add_argument('--mode', choices=['testcard', 'game'], required=True)
    p.add_argument('--seconds', type=int, default=30, help='the time limit; past it the run gets SIGTERM, then SIGKILL (default %(default)s)')
    p.add_argument('--validate', action='store_true', help='DM_VK_VALIDATE=1: the Vulkan validation layer (vulkan-validationlayers, apt)')
    p.add_argument('--sync-validation', action='store_true', help='the layer\'s synchronization validation too (with --validate)')
    p.add_argument('--script', action='store_true', help='test card: minimized at 6 s; the run waits for the compositor to bring the window back (its task bar entry, tapped from outside)')
    p.add_argument('--testcard-ms', type=int, default=100, help='test card: a frame every N ms (default %(default)s)')
    p.add_argument('--shots', default='', help='screenshots of the tablet\'s screen this many seconds after the launch, as 4,9,15')
    p.add_argument('--shot-frames', default='', help='game: the frames the backend writes before presenting, as DM_VK_SHOT=100,200')
    p.add_argument('--env', action='append', help='one more KEY=VALUE in the run\'s environment (repeatable)')
    p.add_argument('--no-wait', action='store_true', help='return once started; collect fetches the log later')
    p.add_argument('--allow-stale', action='store_true', help='start the installed host although the sources changed, or another host was installed')
    p = sub.add_parser('collect', help='fetch the run\'s log and status, count what was reported, take a screenshot if asked')
    common(p)
    p.add_argument('--run', default=None, help='which run (default: the last one)')
    p.add_argument('--shot', action='store_true', help='take a screenshot of the screen now')
    p = sub.add_parser('stop', help='end the run this tool started (its own processes alone), then collect')
    common(p)
    p.add_argument('--wait', type=int, default=20, help='seconds to let it end on SIGTERM (default %(default)s)')
    p = sub.add_parser('press', help='press buttons on the running game\'s virtual pad (l,r,a,b,x,y,plus,minus,zl,zr)')
    common(p)
    p.add_argument('buttons', help='comma-separated button names, e.g. l,r')
    p.add_argument('--hold', default='1.5', help='seconds to hold (default %(default)s)')
    common(sub.add_parser('status', help='the last sync, build and run'))
    p = sub.add_parser('selftest', help='a build made to fail in places of its own: reported failed, installs nothing, run refuses')
    common(p)
    p.add_argument('--jobs', type=int, default=8, help=argparse.SUPPRESS)

    a = ap.parse_args(argv)
    a.shots = [float(x) for x in a.shots.split(',') if x.strip()] if getattr(a, 'shots', '') else []
    if a.cmd == 'run':
        a.wait = not a.no_wait   # only the run has --no-wait; the stop subcommand's --wait is seconds and must stay one
    ctx = Ctx(game=a.game, gfx=getattr(a, 'gfx', 'vk'), ctr_dev=a.ctr_dev, source_root=a.source_root, ev_root=a.state_dir)
    ctx.app = a.app or resolve_app(ctx)
    def go_sync():
        print_places(ctx)
        ls, digest = do_sync(ctx)
        print(f"sync: {ls['files']} files in the set, digest {digest[:16]}; {ls['shipped']} sent, {len(ls['copied'])} new or changed in {ctx.ctr_src}"
              + (f"; removed {ls['removed']}" if ls['removed'] else ''))
        for f in ls['copied'][:20]:
            print('  changed ' + f)
        if len(ls['copied']) > 20:
            print(f'  ... {len(ls["copied"]) - 20} more')

    table = {'sync': lambda: go_sync() and 0,
             'build': lambda: do_build(ctx, clean=a.clean, install=not a.no_install, jobs=a.jobs)[0],
             'run': lambda: do_run(ctx, a) and 0,
             'collect': lambda: do_collect(ctx, a.run or state(ctx).get('last_run'), shot=a.shot) and 0,
             'status': lambda: cmd_status(ctx) and 0,
             'stop': lambda: do_stop(ctx, a.wait) and 0,
             'press': lambda: do_press(ctx, a) and 0,
             'selftest': lambda: cmd_selftest(ctx, a.jobs)}
    try:
        return table[a.cmd]()
    except Fail as e:
        print(f'{a.cmd}: {e}', file=sys.stderr)
        return e.code
    except (subprocess.SubprocessError, OSError) as e:
        print(f'{a.cmd}: {type(e).__name__}: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
