#!/usr/bin/env python3
"""The container-side half of devtools/droidspaces_dev.py.

droidspaces_dev.py pushes this file to the tablet's shared folder and runs it inside the DroidSpaces container with the system python3:

    /data/local/Droidspaces/bin/droidspaces run -- python3 <this file> <command> <plain arguments...>

One command per invocation. The arguments are plain words (checked: no spaces, quotes or dollars), so no shell string is built up from
pieces; the only thing ever run through a shell is the one launch script of a run, and that is written to a file first -- the file is the
record of what was started. The answer is one JSON object, the last line on stdout; "ok": false means the command did not do what was asked.

The places, all under the tool's own folder in the container (DEV, /opt/nx2a-data/dev: the container's disk, never /tmp):

    src/nxnative/dm      the one source tree the host is built from -- a mirror of the checkout's nxnative/dm (droidspaces_dev.py sync)
                        The tree's place has nothing to do with the libraries anything runs on: the build environment and the run
                        environment are the two defined below, and neither names this tree
    src/manifest.json    what was synced: every file's size and sha256, and the digest of the whole set
    out/<game>-<gfx>/    the build directory; build.py keeps its objects there, so a build takes up where the last one ended
    runs/<test id>/      what a build or a run left: build.sh (the build's command and environment), build.log, build-request.json,
                        build-result.json; for a run under it: launch.sh, header.txt, run.log, exit, run.json, stop.json
    env.sh, build-env.sh   the two environments as given to a run and to a build (written from the definitions below)
    A build, like a run, is started detached and watched by short calls: a lost adb connection costs nothing -- the answer is written
    in the container, and the next call reads it. Parameters travel as files, never as a long command line.
"""
import hashlib, json, os, re, shlex, shutil, signal, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

# ---- the two environments, kept apart ----------------------------------------------------------------
# Build: the payload's toolchain and nothing else of the payload -- its clang (which brings its own libraries by its RUNPATH) and its
# glslc, both found through PATH; NX2A_TOOLCHAIN is what build.py reads for the same two, for the glibc sysroot it compiles against, and
# for the toolchain's libshaderc (build.py puts the toolchain's lib/ first for glslc itself). python3, the linker and every -l library
# are the container's own (build.py's -L/usr/lib/aarch64-linux-gnu). No LD_LIBRARY_PATH of this tool's: the payload's pylibs are for the
# porter's python, which the host build does not run. DM_TARGET=linux is build.py's host-TLS variant for this line.
TOOLCHAIN = '/opt/nx2a/toolchain'   # beside /opt/nx2a/bin/nx2a-env.sh, the payload written for the host's libraries (not the APK line's rootfs)
ENV_BUILD = {'PATH': TOOLCHAIN + '/clang/bin:' + TOOLCHAIN + '/bin:/usr/bin:/bin', 'HOME': '/root', 'NX2A_TOOLCHAIN': TOOLCHAIN,
             'DM_TARGET': 'linux'}
# Run: the container's own loader, libc, SDL3, Vulkan and Wayland, and nothing added. readelf names libz.so.1, libm.so.6, libvulkan.so.1,
# libSDL3.so.0 and libc.so.6, the interpreter /lib/ld-linux-aarch64.so.1, and no RPATH; /proc/<pid>/maps of a running host lists
# /usr/lib/aarch64-linux-gnu alone, and the test card comes up in exactly this environment (2026-11-27). With the APK line's rootfs in
# LD_LIBRARY_PATH the same host loaded a second libc from it, beside the system's SDL3 and Vulkan: not needed, and wrong. The pack's run.sh
# hands over the data root (DM_ROOT); the host reads the pack's env.txt itself. XDG_RUNTIME_DIR names the desktop session's folder, whose
# Wayland socket has the default name; no WAYLAND_DISPLAY or DISPLAY is passed on
ENV_RUN = {'PATH': '/usr/bin:/bin', 'HOME': '/root', 'XDG_RUNTIME_DIR': '/run/user/1000'}

PLAIN = re.compile(r'^[A-Za-z0-9._/+=,:@%\-]+$')
SOURCES = ('.c', '.S', '.cpp', '.cc', '.cxx')


def word(tok, what='argument'):
    """A plain word as an argument: nothing in it that a shell, or a path, would read differently."""
    tok = str(tok)
    if not PLAIN.match(tok) or '..' in tok.split('/') or tok.startswith('/../'):
        raise SystemExit(f'{what} is not a plain word: {tok!r}')
    return tok


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def fident(p, hash_it=True):
    """What a file is: its size, its time, and (unless told otherwise) its sha256 -- None when there is no such file."""
    p = Path(p)
    if not p.is_file():
        return None
    st = p.stat()
    return {'path': str(p), 'size': st.st_size, 'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
            'sha256': sha256(p) if hash_it else None}


def save(p, obj):
    """A JSON file written whole or not at all (a temporary name, then renamed over)."""
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + '\n')
    os.replace(tmp, p)


def load(p):
    p = Path(p)
    return json.loads(p.read_text()) if p.is_file() else None


def say(res):
    print(json.dumps(res, sort_keys=True))
    return 0 if res.get('ok') else 1


def proc_stat(pid):
    """(state, start time, parent) of a pid from /proc, or None. The start time tells a pid from a later process that got the same number."""
    try:
        s = Path(f'/proc/{pid}/stat').read_text()
    except OSError:
        return None
    rest = s[s.rfind(')') + 2:].split()
    return rest[0], rest[19], int(rest[1])


def alive(rec):
    st = proc_stat(rec['pid'])
    return bool(st) and st[1] == str(rec['starttime']) and st[0] != 'Z'


def descendants(root):
    """The pids below root, nearest first, from the parent ids in /proc."""
    kids = {}
    for d in os.listdir('/proc'):
        if d.isdigit():
            st = proc_stat(int(d))
            if st:
                kids.setdefault(st[2], []).append(int(d))
    out, todo = [], [root]
    while todo:
        for k in sorted(kids.get(todo.pop(0), [])):
            out.append(k)
            todo.append(k)
    return out


def exit_of(rd):
    p = Path(rd) / 'exit'
    return p.read_text().strip() if p.is_file() else None


# ---- sync ---------------------------------------------------------------------------------------
def cmd_apply(a):
    """apply <archive.tar.gz> <manifest.json> <src>: make the container tree equal to the manifest, touching only what changed."""
    tgz, manifest_path, src = Path(word(a[0])), Path(word(a[1])), Path(word(a[2]))
    whole = json.loads(manifest_path.read_text())
    files = whole['files']
    src.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.incoming-', dir=str(src.parent.parent)))   # unpacked beside the tree: the same disk
    copied, members = [], []
    try:
        with tarfile.open(tgz, 'r:gz') as tf:
            members = [m for m in tf.getmembers() if m.isfile()]
            unknown = [m.name for m in members if m.name not in files]
            if unknown:
                return say({'ok': False, 'error': 'the archive holds files the manifest does not name', 'files': unknown[:10]})
            tf.extractall(stage, filter='data')
            for m in members:
                dst = src / m.name
                if dst.is_file() and dst.stat().st_size == files[m.name]['size'] and sha256(dst) == files[m.name]['sha256']:
                    continue   # there already, byte for byte: left alone, time and all -- and so is the object made from it
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(stage / m.name, dst)
                os.chmod(dst, m.mode & 0o777)
                os.utime(dst, None)   # newer than any object, whatever the two machines' clocks say: the build sees the change
                copied.append(m.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    old = load(src.parent / 'manifest.json') or {'files': {}}
    removed = [n for n in old['files'] if n not in files]
    for n in removed:
        (src / n).unlink(missing_ok=True)
    save(src.parent / 'manifest.json', {'digest': whole['digest'], 'files': files})
    return say({'ok': True, 'src': str(src), 'files': len(files), 'shipped': len(members), 'copied': copied, 'removed': removed,
                'digest': whole['digest']})


def mismatched(src, files, limit=40):
    bad = []
    for n, f in sorted(files.items()):
        p = src / n
        if not p.is_file():
            bad.append(n + ' (missing)')
        elif p.stat().st_size != f['size'] or sha256(p) != f['sha256']:
            bad.append(n + ' (differs)')
        if len(bad) >= limit:
            bad.append('...')
            break
    return bad


def cmd_verify(a):
    """verify <src>: is the container tree still, file for file, what was synced."""
    src = Path(word(a[0]))
    man = load(src.parent / 'manifest.json')
    if not man:
        return say({'ok': False, 'src': str(src), 'error': 'never synced: no manifest beside the tree'})
    bad = mismatched(src, man['files'])
    return say({'ok': not bad, 'src': str(src), 'files': len(man['files']), 'digest': man['digest'], 'mismatched': bad})


# ---- build and install --------------------------------------------------------------------------
def build_request(path):
    """What the other side asked for, as one JSON file (never a long command line)."""
    rq = json.loads(Path(path).read_text())
    for k in ('dev', 'src', 'out', 'run_dir', 'game', 'gfx'):
        word(rq[k], 'the build request\'s ' + k)
    rq['since'] = [word(w, 'a changed source') for w in rq.get('since', [])]
    return rq


def build_cmd(rq):
    """build.py's command line from the request."""
    return ([sys.executable, rq['src'] + '/android/build.py', '--game', rq['game'], '--out', rq['out'], '--jobs', str(int(rq['jobs'])),
             '--os', 'linux', '--gfx', rq['gfx']] + (['--release'] if rq.get('release') else []) + ['--exe'])


def cmd_build_start(a):
    """build-start <request.json>: checks the container tree against what was synced, writes the build's launch script (the record of
    what is started: the command, the build environment) and starts it detached. The answer comes later, from build-state."""
    rq = build_request(word(a[0]))
    src, out, run_dir, dev = Path(rq['src']), Path(rq['out']), Path(rq['run_dir']), Path(rq['dev'])
    if rq.get('clean'):
        shutil.rmtree(out, ignore_errors=True)
    man = load(src.parent / 'manifest.json')
    if not man:
        return say({'ok': False, 'error': 'the container tree was never synced: no manifest beside it', 'run_dir': str(run_dir)})
    bad = mismatched(src, man['files'])
    if bad:
        return say({'ok': False, 'error': 'the container tree is not what was synced (changed by hand, or not synced yet)', 'mismatched': bad,
                    'run_dir': str(run_dir)})
    # Which sources changed since the objects in the build directory were made: read there, from the manifest of the sources of the last
    # whole build (source-manifest.json, written by build-finish) -- not from anyone's memory of an earlier build. Objects with no such
    # record are not trusted: the directory is started over
    objs = out / 'obj'
    built = load(out / 'source-manifest.json')
    if not rq.get('clean') and objs.is_dir() and any(objs.iterdir()) and not built:
        shutil.rmtree(out, ignore_errors=True)
        rq['restarted'] = True
    since = [] if not built else sorted(n for n in set(man['files']) | set(built['files'])
                                        if man['files'].get(n, {}).get('sha256') != built['files'].get(n, {}).get('sha256'))
    out.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)
    for n in ('build-result.json', 'build.rc', 'build.started', 'build.log', 'build-process.json'):   # no earlier attempt's answer
        (run_dir / n).unlink(missing_ok=True)
    rq['since'], rq['t0'], rq['source_digest'] = since, time.time(), man['digest']
    save(run_dir / 'build-request.json', rq)
    (dev / 'build-env.sh').write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in ENV_BUILD.items()))
    cmd = build_cmd(rq)
    me = str(Path(__file__).resolve())
    lines = ['#!/bin/sh',
             f'# nx2a-dev build {run_dir.name}: build.py on the container tree, in the build environment of {dev}/build-env.sh.',
             '# Written and started by droidspaces_dev_remote.py; this file is the record of what was started.',
             f'. "{dev}/build-env.sh"',
             f'cd "{src.parent.parent}"',
             f'date +%s > "{run_dir}/build.started"',
             ' '.join(shlex.quote(c) for c in cmd) + f' > "{run_dir}/build.log" 2>&1 < /dev/null',
             f'echo "exit $?" > "{run_dir}/build.rc.tmp"; mv -f "{run_dir}/build.rc.tmp" "{run_dir}/build.rc"',
             f'exec {shlex.quote(sys.executable)} {shlex.quote(me)} build-finish "{run_dir}/build-request.json"']
    (run_dir / 'build.sh').write_text('\n'.join(lines) + '\n')
    ignored = signal.signal(signal.SIGHUP, signal.SIG_IGN)   # inherited: the build outlives the call that started it
    try:
        p = subprocess.Popen(['sh', str(run_dir / 'build.sh')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, env={'PATH': '/usr/bin:/bin'})
    finally:
        signal.signal(signal.SIGHUP, ignored)
    time.sleep(0.3)
    st = proc_stat(p.pid)
    rec = {'pid': p.pid, 'starttime': st[1] if st else None, 'launch': lines}
    save(run_dir / 'build-process.json', rec)
    return say({'ok': True, 'run_dir': str(run_dir), 'pid': p.pid, 'running': bool(st) and st[0] != 'Z', 'launch': lines, 'cmd': cmd,
                'since': since, 'restarted': bool(rq.get('restarted'))})


def cmd_build_state(a):
    """build-state <run dir>: is the build going, is its answer there, what has build.py written so far."""
    run_dir = Path(word(a[0]))
    rec = load(run_dir / 'build-process.json')
    rc = run_dir / 'build.rc'
    log = run_dir / 'build.log'
    return say({'ok': True, 'run_dir': str(run_dir), 'exists': run_dir.is_dir(), 'running': bool(rec) and alive(rec),
                'result': load(run_dir / 'build-result.json'), 'rc': rc.read_text().strip() if rc.is_file() else None,
                'log_bytes': log.stat().st_size if log.is_file() else 0, 'pid': rec['pid'] if rec else None})


def cmd_build_finish(a):
    """build-finish <request.json>: the build's answer from what build.py left -- run by the build's launch script once build.py has
    exited (and by build-state's caller if that script was lost). ok only when build.py exited 0, linked an ELF newer than the build's
    start, and every changed source's object was made again."""
    rq = build_request(word(a[0]))
    src, out, run_dir = Path(rq['src']), Path(rq['out']), Path(rq['run_dir'])
    game, gfx = rq['game'], rq['gfx']
    res = {'ok': False, 'game': game, 'gfx': gfx, 'release': bool(rq.get('release')), 'clean': bool(rq.get('clean')), 'src': str(src),
           'out': str(out), 'run_dir': str(run_dir), 'cmd': build_cmd(rq), 'env': ENV_BUILD}
    rc_file = run_dir / 'build.rc'
    if not rc_file.is_file():
        return say(dict(res, error='build.py has not exited: no exit status was written'))
    rc = int(rc_file.read_text().strip().split()[-1])
    t0 = float(rq['t0'])
    lines = (run_dir / 'build.log').read_text(errors='replace').splitlines() if (run_dir / 'build.log').is_file() else []
    errs, seen = [], set()
    for l in lines:
        if ('error:' in l or 'undefined symbol' in l or l.startswith('--- ')) and l not in seen:
            seen.add(l)
            errs.append(l[:300])
    objs = out / 'obj'
    rebuilt = sorted(o.name for o in objs.glob('*.o') if o.stat().st_mtime >= t0 - 1) if objs.is_dir() else []
    stale, no_object = [], []
    for c in rq.get('since', []):
        if os.path.splitext(c)[1] not in SOURCES:
            continue
        o = objs / (c.replace('/', '_') + '.o')
        s = src / c
        if not o.is_file():
            no_object.append(c)        # not in what build.py compiles for this platform -- or a new source it does not know of
        elif not s.is_file() or o.stat().st_mtime < s.stat().st_mtime:
            stale.append(c)            # the object is older than its source: the binary cannot hold this change (the same test
                                       # build.py's dependency check makes -- an object from an earlier build of the same source is fine)
    binary = out / 'dmhost'
    linked = False
    if binary.is_file():
        with open(binary, 'rb') as f:
            linked = binary.stat().st_mtime >= t0 - 1 and f.read(4) == b'\x7fELF'
    res.update(rc=rc, linked=linked, seconds=round(time.time() - t0, 1), log_lines=len(lines), log_tail=lines[-2:],
               objects_total=len(list(objs.glob('*.o'))) if objs.is_dir() else 0, objects_rebuilt=len(rebuilt), rebuilt=rebuilt[:80],
               stale_sources=stale, sources_without_object=no_object, errors=errs[:15], source_digest=rq.get('source_digest'))
    if linked:
        res['binary'] = fident(binary)
    res['ok'] = rc == 0 and linked and not stale
    res['since'], res['restarted'] = rq.get('since', []), bool(rq.get('restarted'))   # from the start, for the record
    if res['ok']:   # the objects in the build directory are now made of exactly these sources: the next build's "changed since" reads it here
        built = load(src.parent / 'manifest.json')
        if built and built['digest'] == rq.get('source_digest'):
            save(out / 'source-manifest.json', built)
    save(run_dir / 'build-result.json', res)
    return say(res)


def cmd_install(a):
    """install <out> <pack> <run dir>: the built host becomes the pack's host/dmhost -- what its run.sh starts -- copied to a temporary
    name beside it and renamed over it, so the pack never holds a half of a binary. Nothing else in the pack is touched."""
    out, pack, run_dir = Path(word(a[0])), Path(word(a[1])), Path(word(a[2]))
    src, dst = out / 'dmhost', pack / 'host/dmhost'
    res = {'ok': False, 'built': str(src), 'installed': str(dst)}
    if not src.is_file():
        return say(dict(res, error='nothing built to install'))
    before = fident(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name('.dmhost.installing')
    with open(src, 'rb') as i, open(tmp, 'wb') as o:
        shutil.copyfileobj(i, o)
        o.flush()
        os.fsync(o.fileno())
    os.chmod(tmp, 0o755)
    os.replace(tmp, dst)
    after, built = fident(dst), fident(src)
    if not after or after['sha256'] != built['sha256']:
        return say(dict(res, error='the installed host does not read back as the built one'))
    res.update(ok=True, host=after, previous=before)
    save(run_dir / 'install-result.json', res)
    return say(res)


# ---- what is there ------------------------------------------------------------------------------
LIBRARY = '/opt/nx2a-data/library'   # the packs, one folder each: <App>-data


def cmd_info(a):
    """info <dev>: the tool's places in the container, the packs, and the environment every build and run gets."""
    dev = Path(word(a[0]))
    packs = []
    for p in sorted(Path(LIBRARY).glob('*-data')) if Path(LIBRARY).is_dir() else []:
        env = p / 'env.txt'
        first = env.read_text(errors='replace').splitlines()[0].strip() if env.is_file() else ''
        packs.append({'pack': str(p), 'app': p.name[:-5], 'env_first_line': first, 'run_sh': (p / 'run.sh').is_file(),
                      'host': fident(p / 'host/dmhost')})
    return say({'ok': True, 'dev': str(dev), 'src': str(dev / 'src/nxnative/dm'), 'packs': packs, 'toolchain': TOOLCHAIN,
                'toolchain_clang': fident(TOOLCHAIN + '/clang/bin/clang'), 'toolchain_glslc': fident(TOOLCHAIN + '/bin/glslc'),
                'env_build': ENV_BUILD, 'env_run': ENV_RUN, 'python': sys.version.split()[0],
                'remote_sha256': fident(__file__)['sha256']})


def cmd_ident(a):
    """ident <pack> <out>: what each part is -- the installed host, the built one, the rewritten modules, the profile, env.txt, run.sh."""
    pack, out = Path(word(a[0])), Path(word(a[1]))
    r = {'pack': str(pack), 'installed_host': fident(pack / 'host/dmhost'), 'built_host': fident(out / 'dmhost')}
    mods = pack / 'mods'
    r['mods'] = {p.name: fident(p) for p in sorted(mods.iterdir()) if p.is_file()} if mods.is_dir() else None
    bs = mods / 'build_src.sha256'
    r['mods_build_src'] = bs.read_text(errors='replace').strip().splitlines()[:30] if bs.is_file() else None
    prof = pack / 'profile'
    r['profile'] = ({str(p.relative_to(prof)): fident(p, p.stat().st_size < (64 << 20)) for p in sorted(prof.rglob('*')) if p.is_file()}
                    if prof.is_dir() else None)
    env = pack / 'env.txt'
    r['env_txt'] = env.read_text(errors='replace').splitlines() if env.is_file() else None
    rs = pack / 'run.sh'
    r['run_sh'] = rs.read_text(errors='replace') if rs.is_file() else None
    return say(dict(r, ok=True))


def cmd_sha(a):
    """sha <file>: one file's sha256."""
    f = fident(word(a[0]))
    return say({'ok': bool(f), 'file': f})


def cmd_rmtree(a):
    """rmtree <folder>: removes a folder of this tool's -- only one under /opt/nx2a-data/ whose name says selftest."""
    p = Path(word(a[0]))
    if not str(p).startswith('/opt/nx2a-data/') or 'selftest' not in p.name or str(p) == '/opt/nx2a-data/':
        return say({'ok': False, 'error': f'{p} is not a selftest folder under /opt/nx2a-data/: left alone'})
    shutil.rmtree(p, ignore_errors=True)
    return say({'ok': not p.exists(), 'removed': str(p)})


# ---- a run --------------------------------------------------------------------------------------
def cmd_launch(a):
    """launch <dev> <run id> <pack> <seconds> <mode> <header file> [KEY=VALUE...]: the pack's own run.sh, detached, under timeout, with
    the session environment and KEY=VALUE added; the header file's lines go first in run.log. Writes run dir/launch.sh (the record of what
    was started) and run.json (the process's identity)."""
    dev, run_id, pack = Path(word(a[0])), word(a[1]), Path(word(a[2]))
    seconds, mode, header = int(a[3]), word(a[4]), Path(word(a[5]))
    extra = {}
    for kv in a[6:]:
        k, sep, v = str(kv).partition('=')
        if not sep or not re.match(r'^[A-Z][A-Z0-9_]*$', k):
            raise SystemExit(f'not KEY=VALUE with KEY an upper-case name: {kv!r}')
        extra[k] = word(v, 'the value of ' + k)
    cur = load(dev / 'current.json')
    if cur and alive(cur):
        return say({'ok': False, 'error': f"run {cur['run_id']} is still going (pid {cur['pid']}): stop it first",
                    'run_id': cur['run_id'], 'pid': cur['pid']})
    rd = dev / 'runs' / run_id
    rd.mkdir(parents=True, exist_ok=True)
    for n in ('exit', 'stop.json', 'started'):
        (rd / n).unlink(missing_ok=True)
    if not header.is_file():
        return say({'ok': False, 'error': f'the run header {header} was not sent', 'run_dir': str(rd)})
    (rd / 'header.txt').write_text(header.read_text())
    (dev / 'env.sh').write_text(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in ENV_RUN.items()))
    lines = ['#!/bin/sh',
             f'# nx2a-dev run {run_id}: the pack\'s own entry (run.sh) under timeout, in the session environment of env.sh.',
             '# Written and started by droidspaces_dev_remote.py; this file is the record of what was started.',
             f'. "{dev}/env.sh"']
    lines += [f'export {k}={shlex.quote(v)}' for k, v in extra.items()]
    lines += [f'cat "{rd}/header.txt" > "{rd}/run.log"',
              f'date +%s > "{rd}/started"',
              f'timeout -k 5 {seconds} sh "{pack}/run.sh" >> "{rd}/run.log" 2>&1 < /dev/null',
              f'echo "exit $?" > "{rd}/exit.tmp"; mv -f "{rd}/exit.tmp" "{rd}/exit"']
    (rd / 'launch.sh').write_text('\n'.join(lines) + '\n')
    (rd / 'run.log').unlink(missing_ok=True)
    ignored = signal.signal(signal.SIGHUP, signal.SIG_IGN)   # inherited by the run: no hang-up reaches it when the adb side is gone
    try:
        p = subprocess.Popen(['sh', str(rd / 'launch.sh')], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
                             env={'PATH': '/usr/bin:/bin'})   # nothing else reaches the launch script: env.sh is the whole environment
    finally:
        signal.signal(signal.SIGHUP, ignored)
    time.sleep(0.3)
    st = proc_stat(p.pid)
    if not st:
        return say({'ok': False, 'error': 'the run ended at once, or did not start', 'run_dir': str(rd), 'launch': lines,
                    'run_log': (rd / 'run.log').read_text(errors='replace')[-1500:] if (rd / 'run.log').is_file() else None})
    rec = {'run_id': run_id, 'pid': p.pid, 'starttime': st[1], 'started': time.time(), 'mode': mode, 'seconds': seconds,
           'pack': str(pack), 'run_dir': str(rd), 'binary': fident(pack / 'host/dmhost'), 'extra_env': extra, 'launch': lines}
    save(rd / 'run.json', rec)
    save(dev / 'current.json', rec)
    return say(dict(rec, ok=True, alive=alive(rec)))


def run_state(dev, run_id):
    rd = Path(dev) / 'runs' / run_id
    rec = load(rd / 'run.json')
    log = rd / 'run.log'
    return {'ok': True, 'run_id': run_id, 'run_dir': str(rd), 'exists': rd.is_dir(), 'alive': bool(rec) and alive(rec),
            'exit': exit_of(rd), 'stopped': (rd / 'stop.json').is_file(), 'log_bytes': log.stat().st_size if log.is_file() else 0,
            'pid': rec['pid'] if rec else None, 'seconds': rec['seconds'] if rec else None}


def cmd_status(a):
    """status <dev> <run id>: is the run going, how did it end."""
    return say(run_state(word(a[0]), word(a[1])))


def cmd_stop(a):
    """stop <dev> <run id> <wait seconds>: ends one run -- the one whose process identity is on record. Its pid and start time are
    checked again, then its descendants are sent SIGTERM (SIGKILL if they outlast the wait). The launch script itself is left alone, so
    that it writes the exit status down. No other process is looked at."""
    dev, run_id, wait_s = Path(word(a[0])), word(a[1]), float(a[2])
    rd = dev / 'runs' / run_id
    rec = load(rd / 'run.json')
    if not rec:
        return say({'ok': True, 'run_id': run_id, 'alive': False, 'note': 'no run of that name here: nothing to stop'})
    if not alive(rec):
        return say({'ok': True, 'run_id': run_id, 'alive': False, 'note': 'it had already ended', 'exit': exit_of(rd)})
    t0 = time.time()
    term = descendants(rec['pid'])
    for p in term:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    while time.time() - t0 < wait_s and alive(rec):
        time.sleep(0.25)
    kill = []
    if alive(rec):
        kill = descendants(rec['pid'])
        for p in kill:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        while alive(rec) and time.time() - t0 < wait_s + 5:
            time.sleep(0.25)
    res = {'ok': not alive(rec), 'run_id': run_id, 'pid': rec['pid'], 'signalled_term': term, 'signalled_kill': kill,
           'seconds': round(time.time() - t0, 1), 'still_alive': alive(rec), 'exit': exit_of(rd), 'time': time.strftime('%Y-%m-%d %H:%M:%S')}
    save(rd / 'stop.json', res)
    return say(res)


def cmd_pack(a):
    """pack <run dir> <archive.tar.gz>: a run's folder as one archive, for the other side to pull."""
    rd, out = Path(word(a[0])), Path(word(a[1]))
    if not rd.is_dir():
        return say({'ok': False, 'error': f'{rd} is not a run folder'})
    out.unlink(missing_ok=True)
    with tarfile.open(out, 'w:gz') as tf:
        tf.add(rd, arcname=rd.name)
    return say({'ok': True, 'archive': str(out), 'bytes': out.stat().st_size, 'sha256': sha256(out)})


COMMANDS = {'apply': cmd_apply, 'verify': cmd_verify, 'build-start': cmd_build_start, 'build-state': cmd_build_state,
            'build-finish': cmd_build_finish, 'install': cmd_install, 'info': cmd_info, 'ident': cmd_ident,
            'sha': cmd_sha, 'rmtree': cmd_rmtree, 'launch': cmd_launch, 'status': cmd_status, 'stop': cmd_stop, 'pack': cmd_pack}


def main(argv):
    if not argv or argv[0] not in COMMANDS or '--help' in argv:
        print(json.dumps({'ok': False, 'error': 'commands: ' + ', '.join(sorted(COMMANDS)), 'usage': {k: v.__doc__.splitlines()[0].strip()
                        for k, v in sorted(COMMANDS.items())}}, sort_keys=True))
        return 2
    try:
        return COMMANDS[argv[0]](argv[1:])
    except (SystemExit, IndexError, ValueError) as e:
        return say({'ok': False, 'error': f'{argv[0]}: {e or "an argument is missing"}'})
    except Exception as e:   # a failure is an answer too: the other side must learn it, not guess from silence
        return say({'ok': False, 'error': f'{argv[0]}: {type(e).__name__}: {e}'})


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
