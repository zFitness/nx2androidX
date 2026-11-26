#!/usr/bin/env python3
"""What an upstream sync would touch, before it touches anything.

The upstream (shirai91/nx2android) is merged into this line whole, but only part of it is
ours to take: the engine's core (the host's system calls, the graphics replay, the shader
and NSO tools, the game profiles) is shared, while the porter's pipeline and the front
(the glue between the engine and an app) are two different worlds and are never synced
(2026-11-25). This script says which files a sync would touch and which of them need a
human's eye, so the merge starts with a list instead of a surprise.

    python3 devtools/upstream_conflict_surface.py                  # upstream/main vs android
    python3 devtools/upstream_conflict_surface.py --upstream upstream/main --ours android
    python3 devtools/upstream_conflict_surface.py --json
    python3 devtools/upstream_conflict_surface.py --skip-paths     # the paths we keep as ours
    python3 devtools/upstream_conflict_surface.py --apply-skip      # in a staged merge: keep ours

The classes:

    sync   the engine's core: taken by the merge, no decision to make
    skip   the two worlds: kept as ours, the merge never sees them
    ours   files of ours that the merge would overwrite (we changed them, upstream did not)
    theirs files of upstream the merge would bring that we do not have

    attention  the sync files both sides changed since the merge base: the only ones that
               can conflict, and the ones to look at after the merge
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# The paths the sync takes: the engine's core. Everything else is two worlds.
SYNC_PREFIXES = (
    'nxnative/dm/host/',
    'nxnative/dm/gfx/',
    'nxnative/dm/tools/',
    'nxnative/dm/games/',
    'nxnative/dm/third_party/',
    'nxnative/dm/android/',
    'tests/',
)
SYNC_FILES = (
    'nxnative/dm/settings.tsv',
)

# The paths the sync never takes: the porter's pipeline (this line runs the port on the
# phone), the player's own front (this line has its own), the APK packaging, the iOS
# line, and this line's app, tools and docs.
# The upstream's APK front (nxnative/dm/android/front_android.c) is not in this list: a
# standalone APK (a NativeActivity of its own) runs on it, so it comes with the engine's
# core like the rest of dm/android/.
SKIP_PREFIXES = (
    'porter/',
    'nxnative/dm/ios/',
    'nxnative/dm/android/apk/',
    'android/',
    'phone_tools/',
    'devtools/',
    'gui/',
    'launcher/',
    'packaging/',
    'docs/',
    'probes/',
)
SKIP_FILES = (
    'README.md',
    'README.zh.md',
    'AGENTS.md',
    'CLAUDE.md',
)

# Build junk nobody needs on either line.
SKIP_SUFFIXES = ('.pdb',)

# The upstream documents every profile in its own README; this line documents the profiles
# in docs/PORT_CHECKLIST.md, so the upstream's ones stay upstream's.
GAME_README = re.compile(r'^nxnative/dm/games/[^/]+/README\.md$')

# The player's front's own tests, read out of the files themselves: a test that names the
# player's front belongs to it, and that front is ours alone. The upstream's APK front
# comes with the engine's core, so a test of it is synced like the rest. The same for the
# porter's pipeline tests, and for a test that needs a module of the porter we do not have.
FRONT_MARKERS = ('front_player',)
PORTER_MODULE = re.compile(r'(?:from|import)\s+porter\.([A-Za-z0-9_.]+)')


def _is_skip_test(path: str, bodies: dict, ours_modules: set) -> bool:
    name = Path(path).name
    if 'porter' in name:
        return True
    body = bodies.get(path, '')
    if any(m in body for m in FRONT_MARKERS):
        return True
    if path.endswith('.c'):
        # a C fixture of the front's activity (the front is ours alone)
        return 'game_mode' in name or 'front' in body
    # a test that needs a module of the porter this line does not have: it is the
    # upstream's world (the pipeline is ours alone)
    needed = {m.split('.')[0] for m in PORTER_MODULE.findall(body)}
    return bool(needed - ours_modules)


def classify(path: str, bodies: dict, ours_modules: set) -> str:
    """Which class a path belongs to: 'sync' (the engine's core) or 'skip' (two worlds)."""
    if path in SKIP_FILES or path.endswith(SKIP_SUFFIXES):
        return 'skip'
    if GAME_README.match(path):
        return 'skip'
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return 'skip'
    if path.startswith('tests/') and _is_skip_test(path, bodies, ours_modules):
        return 'skip'
    if path in SYNC_FILES:
        return 'sync'
    if any(path.startswith(p) for p in SYNC_PREFIXES):
        return 'sync'
    return 'skip'


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'error: git {" ".join(args)} failed:\n{r.stderr.strip()}')
    return r.stdout


def git_ok(repo: Path, *args: str) -> bool:
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True).returncode == 0


def files(repo: Path, ref: str, *paths: str) -> list[str]:
    out = git(repo, 'ls-tree', '-r', '--name-only', ref, '--', *paths)
    return [line for line in out.split('\n') if line]


def changed(repo: Path, base: str, ref: str, *paths: str) -> list[str]:
    out = git(repo, 'diff', '--name-only', base, ref, '--', *paths)
    return sorted(line for line in out.split('\n') if line)


def bodies(repo: Path, ref: str, paths: list[str]) -> dict:
    """The files' text, for the rules that read what a file says."""
    out = {}
    for path in paths:
        if not path.startswith('tests/'):
            continue
        r = subprocess.run(['git', '-C', str(repo), 'show', f'{ref}:{path}'], capture_output=True, text=True)
        if r.returncode == 0:
            out[path] = r.stdout
    return out


def porter_modules(repo: Path, ref: str) -> set:
    """The porter's module names, as a path: the ones this line has."""
    out = set()
    for path in files(repo, ref, 'porter'):
        name = Path(path)
        if name.suffix == '.py':
            out.add(name.stem)
        elif name.is_dir():
            pass
    for path in files(repo, ref, 'porter'):
        parts = Path(path).parts
        if len(parts) > 1 and parts[1].endswith('.py'):
            out.add(parts[1][:-3])
    return out


def surface(repo: Path, upstream: str, ours: str) -> dict:
    base = git(repo, 'merge-base', ours, upstream).strip()
    if not base:
        raise SystemExit(f'error: {ours} and {upstream} have no common ancestor')
    upstream_files = set(files(repo, upstream))
    ours_files = set(files(repo, ours))
    ours_changed = changed(repo, base, ours)
    theirs_changed = changed(repo, base, upstream)
    both = sorted(set(ours_changed) & set(theirs_changed))

    texts = bodies(repo, upstream, list(upstream_files))
    texts.update(bodies(repo, ours, list(ours_files)))
    ours_modules = porter_modules(repo, ours)

    attention = {'sync': [], 'skip': []}
    for path in both:
        attention[classify(path, texts, ours_modules)].append(path)

    return {
        'merge_base': base,
        'upstream': upstream,
        'ours': ours,
        'behind': len(changed(repo, base, upstream)),
        'ahead': len(changed(repo, base, ours)),
        'attention': attention,
        'theirs_only': sorted(upstream_files - ours_files),
        'ours_only': sorted(ours_files - upstream_files),
    }


def skip_paths(repo: Path, ref: str, ours: str) -> list[str]:
    """Every path of the ref that belongs to a world of its own (never synced)."""
    every = files(repo, ref)
    texts = bodies(repo, ref, every)
    ours_modules = porter_modules(repo, ours)
    return [p for p in every if classify(p, texts, ours_modules) == 'skip']


def apply_skip(repo: Path, ref: str) -> int:
    """In a staged merge: keep ours on the paths of a world of its own.

    A path we have goes back to our version; a path the upstream added (we have none) goes
    away with the merge. The rules are the ones the report uses, so the two never disagree.
    """
    ours = git(repo, 'rev-parse', '--abbrev-ref', 'HEAD').strip()
    skip = set(skip_paths(repo, ref, ours))
    restored = removed = 0
    for path in sorted(skip):
        if git_ok(repo, 'cat-file', '-e', f'{ours}:{path}'):
            if git_ok(repo, 'checkout', ours, '--', path):
                restored += 1
        elif git_ok(repo, 'cat-file', '-e', f'{ref}:{path}'):
            # the upstream added it: it goes away with the merge (-f: the merge staged it)
            if git_ok(repo, 'rm', '-q', '-f', '--', path):
                removed += 1
    print(f'   kept ours on {restored} path(s), removed {removed} path(s) the upstream added')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--upstream', default='upstream/main', help='the upstream ref (default: upstream/main)')
    ap.add_argument('--ours', default='android', help='this line\'s ref (default: android)')
    ap.add_argument('--repo', default=str(REPO), help='the checkout to look at')
    ap.add_argument('--json', action='store_true', help='the report as JSON')
    ap.add_argument('--skip-paths', action='store_true', help='print the paths we keep as ours, one per line')
    ap.add_argument('--apply-skip', action='store_true', help='in a staged merge: keep ours on those paths')
    args = ap.parse_args()

    repo = Path(args.repo)

    if args.skip_paths:
        for path in skip_paths(repo, args.upstream, args.ours):
            print(path)
        return 0
    if args.apply_skip:
        return apply_skip(repo, args.upstream)

    report = surface(repo, args.upstream, args.ours)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print(f'upstream: {report["upstream"]}   ours: {report["ours"]}   merge base: {report["merge_base"][:9]}')
    print(f'upstream is {report["behind"]} file(s) ahead of the base, we are {report["ahead"]} ahead')
    print()
    print(f'attention: {len(report["attention"]["sync"])} sync file(s) both sides changed')
    for path in report["attention"]["sync"]:
        print(f'  {path}')
    if report['attention']['skip']:
        print(f'  ({len(report["attention"]["skip"])} file(s) of ours the upstream also changed, kept as ours: '
              f'{", ".join(report["attention"]["skip"][:6])}{" ..." if len(report["attention"]["skip"]) > 6 else ""})')
    print()
    print(f'upstream only: {len(report["theirs_only"])} file(s) we do not have (a merge leaves them deleted: '
          f'we removed them and the upstream did not touch them)')
    for path in report['theirs_only'][:10]:
        print(f'  {path}')
    if len(report['theirs_only']) > 10:
        print(f'  ... {len(report["theirs_only"]) - 10} more')
    return 0


if __name__ == '__main__':
    sys.exit(main())
