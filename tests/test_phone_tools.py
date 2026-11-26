"""The phone's tools: what each one says about a game, a log, a build, a card and a frame.

The tools are scripts in phone_tools/ that the assistant runs on the phone; here they are run the
same way (as a program, with its arguments), against folders built for the test.
"""
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'phone_tools'
sys.path.insert(0, str(TOOLS))


def run(tool, *args, env=None):
    """A tool, run as the assistant runs it."""
    environment = dict(os.environ, PYTHONUTF8='1')
    environment.update(env or {})
    return subprocess.run([sys.executable, str(TOOLS / tool), *[str(a) for a in args]],
                          capture_output=True, text=True, encoding='utf-8', env=environment)


class MemLayout(unittest.TestCase):
    PROFILE = """# a profile
name\tTest Game

# ---- Memory ----
mem_reserve\t0x100000000
mem_alias\t0x10000000
mem_stack\t0x10000000
app_pool\t0xCD500000
"""

    def profile(self, text=None, folder=None):
        folder = folder or tempfile.mkdtemp(prefix='nx2a_profile_')
        path = Path(folder) / 'game.tsv'
        path.write_text(text if text is not None else self.PROFILE)
        return path

    def test_the_layout_is_computed(self):
        path = self.profile()
        result = run('mem_layout.py', '--profile', path, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['reserve'], 0x100000000)
        self.assertEqual(out['alias'], 0x10000000)
        self.assertEqual(out['stack'], 0x10000000)
        # the heap is what is left of the block after the node area, the alias window and the stack
        self.assertEqual(out['heap'], 0x100000000 - (0x10000000 + 0x10000000 + 0x10000000))

    def test_both_notations_are_shown(self):
        result = run('mem_layout.py', '--profile', self.profile())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0x10000000', result.stdout)
        self.assertIn('268,435,456', result.stdout)

    def test_a_layout_that_does_not_fit_is_an_error(self):
        text = self.PROFILE.replace('mem_alias\t0x10000000', 'mem_alias\t0xF0000000')
        result = run('mem_layout.py', '--profile', self.profile(text))
        self.assertEqual(result.returncode, 2)
        self.assertIn('does not fit', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_a_profile_without_the_rows_is_an_error(self):
        result = run('mem_layout.py', '--profile', self.profile('name\tX\n'))
        self.assertEqual(result.returncode, 2)
        self.assertIn('mem_reserve', result.stderr)


class LogTriage(unittest.TestCase):
    def test_the_crash_is_found_in_the_previous_log(self):
        folder = Path(tempfile.mkdtemp(prefix='nx2a_log_'))
        (folder / 'log.txt').write_text('[dm] guest AS 0x7f0000\n[perf] frame 12, 16.6 ms\n')
        (folder / 'log.prev.txt').write_text('[dm] CRASH sig=11\n  backtrace:\n    main+0x1234\n')
        result = run('log_triage.py', '--port', folder, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertIn('log.prev.txt', out['verdict'])
        crashes = out['logs'][1]['crashes']
        self.assertTrue(crashes)
        self.assertEqual(crashes[0]['kind'], 'crash')

    def test_a_run_without_a_crash_says_so(self):
        folder = Path(tempfile.mkdtemp(prefix='nx2a_log_'))
        (folder / 'log.txt').write_text('[dm] guest AS 0x7f0000\n')
        result = run('log_triage.py', '--port', folder)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no crash signature', result.stdout)

    def test_a_missing_pack_is_an_error(self):
        result = run('log_triage.py', '--port', '/nonexistent/pack')
        self.assertEqual(result.returncode, 2)
        self.assertIn('no data pack', result.stderr)


class Builds(unittest.TestCase):
    def test_the_builds_are_listed(self):
        home = Path(tempfile.mkdtemp(prefix='nx2a_home_'))
        folder = home / 'builds' / 'abc'
        folder.mkdir(parents=True)
        (folder / 'record.json').write_text(json.dumps(
            {'id': 'abc', 'game': 'Game.nsp', 'phase': 'FAILED', 'stage': 'shader split',
             'seconds': 42, 'startedAt': 1732300000000}))
        (folder / 'log.txt').write_text('working\n[RED] the shader table does not match\n')
        result = run('builds.py', '--json', env={'NX2A_HOME': str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(len(out['builds']), 1)
        self.assertEqual(out['builds'][0]['game'], 'Game.nsp')

    def test_the_first_error_is_shown(self):
        home = Path(tempfile.mkdtemp(prefix='nx2a_home_'))
        folder = home / 'builds' / 'abc'
        folder.mkdir(parents=True)
        (folder / 'record.json').write_text(json.dumps(
            {'id': 'abc', 'game': 'Game.nsp', 'phase': 'FAILED', 'stage': 'shader split', 'seconds': 42}))
        (folder / 'log.txt').write_text('working\n[RED] the shader table does not match\n')
        result = run('builds.py', '--errors', env={'NX2A_HOME': str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('the shader table does not match', result.stdout)


class PortStatus(unittest.TestCase):
    def snapshot(self, games):
        home = Path(tempfile.mkdtemp(prefix='nx2a_home_'))
        (home / 'library.json').write_text(json.dumps(
            {'schema': 'nx2a.library.v1', 'generatedAt': 1, 'count': len(games), 'games': games}))
        return home

    def test_every_game_is_listed(self):
        games = [{'name': f'Game {i}', 'titleId': f'{i:016X}', 'status': 'ported', 'pack': ''}
                 for i in range(12)]
        home = self.snapshot(games)
        result = run('port_status.py', '--json', env={'NX2A_HOME': str(home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['count'], 12)   # not the first ten

    def test_a_crashed_pack_is_marked(self):
        pack = Path(tempfile.mkdtemp(prefix='nx2a_pack_'))
        (pack / 'log.txt').write_text('[dm] CRASH sig=11\n')
        home = self.snapshot([{'name': 'Game', 'titleId': '0100000000000000', 'status': 'ported',
                               'pack': str(pack)}])
        result = run('port_status.py', '--json', env={'NX2A_HOME': str(home)})
        out = json.loads(result.stdout)
        self.assertEqual(out['games'][0]['run'], 'crashed')

    def test_a_missing_snapshot_says_where_it_should_be(self):
        home = Path(tempfile.mkdtemp(prefix='nx2a_home_'))
        result = run('port_status.py', env={'NX2A_HOME': str(home)})
        self.assertEqual(result.returncode, 2)
        self.assertIn('library.json', result.stderr)


class Shot(unittest.TestCase):
    def frame(self, width=4, height=2, color=(0, 0, 0)):
        pixels = bytes(color) * (width * height)
        header = f'P6\n{width} {height}\n255\n'.encode()
        path = Path(tempfile.mkdtemp(prefix='nx2a_frame_')) / 'frame_000001.ppm'
        path.write_bytes(header + pixels)
        return path

    def test_the_statistics_are_computed(self):
        path = self.frame(color=(10, 20, 30))
        result = run('shot.py', 'stats', path, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(out['frames'][0]['mean'], [10.0, 20.0, 30.0])
        self.assertEqual(out['frames'][0]['black_share'], 0.0)

    def test_a_black_frame_is_black(self):
        path = self.frame()
        result = run('shot.py', 'stats', path, '--json')
        out = json.loads(result.stdout)
        self.assertEqual(out['frames'][0]['black_share'], 1.0)

    def test_a_png_is_written(self):
        path = self.frame()
        result = run('shot.py', 'png', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        png = path.with_suffix('.png')
        self.assertTrue(png.is_file())
        self.assertTrue(png.read_bytes().startswith(b'\x89PNG'))

    def test_two_frames_are_compared(self):
        folder = Path(tempfile.mkdtemp(prefix='nx2a_frames_'))
        first = folder / 'frame_1.ppm'
        second = folder / 'frame_2.ppm'
        first.write_bytes(b'P6\n2 1\n255\n' + bytes((0, 0, 0)) * 2)
        second.write_bytes(b'P6\n2 1\n255\n' + bytes((255, 255, 255)) * 2)
        result = run('shot.py', 'diff', first, second, '--json')
        out = json.loads(result.stdout)
        self.assertEqual(out['changed_share'], 1.0)
        self.assertEqual(out['mean_abs_difference'], 255.0)

    def test_a_file_that_is_not_a_frame_is_an_error(self):
        path = Path(tempfile.mkdtemp(prefix='nx2a_frame_')) / 'x.ppm'
        path.write_bytes(b'not a ppm')
        result = run('shot.py', 'stats', path)
        self.assertEqual(result.returncode, 2)
        self.assertIn('not a PPM', result.stderr)


class Card(unittest.TestCase):
    """A card dump with tickets: the titles are named by the tickets' file names."""

    def dump(self, name, titles):
        sys.path.insert(0, str(ROOT))
        from porter import dumps
        files = [(f'{t:016x}{i:016x}.tik', bytes(16)) for i, t in enumerate(titles)]
        data = (dumps._pfs0_header([n for n, _ in files], [len(d) for _, d in files])
                + b''.join(d for _, d in files))
        path = Path(tempfile.mkdtemp(prefix='nx2a_card_')) / name
        path.write_bytes(data)
        return path

    def test_the_titles_are_listed(self):
        base = 0x0100000000AAA000
        path = self.dump('Merged.nsp', [base, base + 0x800, base + 0x1001])
        result = run('card.py', path, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(len(out['titles']), 3)
        self.assertIn(f'{base:016X}', out['titles'])
        self.assertIn(f'{base + 0x800:016X}', out['titles'])

    def test_a_file_that_is_not_a_dump_is_an_error(self):
        path = Path(tempfile.mkdtemp(prefix='nx2a_card_')) / 'x.nsp'
        path.write_bytes(b'not a dump')
        result = run('card.py', path)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_the_dlc_is_told_apart(self):
        """A DLC sits one 0x1000 above the base game's high part - it has to be read as a DLC."""
        base = 0x0100000000AAA000
        path = self.dump('Merged.nsp', [base, base + 0x800, base + 0x1001])
        result = run('card.py', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DLC', result.stdout)
        self.assertIn('update', result.stdout)


class CardSplit(unittest.TestCase):
    """A card cut into one NSP per title: the base game, its update, its DLCs."""

    BASE = 0x0100000000010000
    KEY = bytes(range(32))

    def keys(self):
        """A prod.keys that carries the header key the fixture's NCA headers are encrypted with."""
        path = Path(tempfile.mkdtemp(prefix='nx2a_keys_')) / 'prod.keys'
        path.write_text(f'header_key = {self.KEY.hex()}\n')
        return path

    def sector(self, title, content_type):
        """The NCA header sector: the magic, the content type and the title ID, as the header holds them."""
        plain = bytearray(0x200)
        plain[0:4] = b'NCA3'
        plain[5] = content_type
        struct.pack_into('<Q', plain, 0x10, title)
        return bytes(plain)

    def nca(self, title, content_type):
        """An NCA file: its first sector plain, its second one (the header) encrypted with the header key."""
        from Crypto.Cipher import AES
        data = AES.new(self.KEY[:16], AES.MODE_ECB)
        tweak = AES.new(self.KEY[16:], AES.MODE_ECB)
        plain = self.sector(title, content_type)
        t = int.from_bytes(tweak.encrypt((1).to_bytes(16, 'big')), 'little')
        mask = (1 << 128) - 1
        encrypted = b''
        for i in range(0, len(plain), 16):
            tb = t.to_bytes(16, 'little')
            block = plain[i:i + 16]
            mixed = bytes(a ^ b for a, b in zip(block, tb))
            encrypted += bytes(a ^ b for a, b in zip(data.encrypt(mixed), tb))
            t = (t << 1 & mask) ^ (0x87 if t >> 127 else 0)
        return b'\0' * 0x200 + encrypted

    def card(self):
        """A card dump holding three titles: the base game, its update and a DLC."""
        sys.path.insert(0, str(ROOT))
        from porter import dumps
        titles = [(self.BASE, 'program'), (self.BASE, 'meta'),
                  (self.BASE + 0x800, 'program'), (self.BASE + 0x800, 'meta'),
                  (self.BASE + 0x1001, 'program'), (self.BASE + 0x1001, 'meta')]
        files = [(f'{i:016x}{i:016x}.nca', self.nca(title, 1 if what == 'meta' else 0))
                 for i, (title, what) in enumerate(titles)]
        data = (dumps._pfs0_header([n for n, _ in files], [len(d) for _, d in files])
                + b''.join(d for _, d in files))
        path = Path(tempfile.mkdtemp(prefix='nx2a_split_')) / 'Card.nsp'
        path.write_bytes(data)
        return path

    @unittest.skipUnless(importlib.util.find_spec('Crypto'), 'no pycryptodome')
    def test_every_title_becomes_its_own_nsp(self):
        card = self.card()
        out = Path(tempfile.mkdtemp(prefix='nx2a_split_out_'))
        result = run('card_split.py', card, out, '--keys', self.keys())
        self.assertEqual(result.returncode, 0, result.stderr)
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, [f'{self.BASE:016X}_base.nsp', f'{self.BASE + 0x800:016X}_update.nsp',
                                 f'{self.BASE + 0x1001:016X}_dlc.nsp'])

    @unittest.skipUnless(importlib.util.find_spec('Crypto'), 'no pycryptodome')
    def test_an_nsp_holds_the_files_of_its_title(self):
        sys.path.insert(0, str(ROOT))
        from porter import dumps
        card = self.card()
        out = Path(tempfile.mkdtemp(prefix='nx2a_split_out_'))
        result = run('card_split.py', card, out, '--keys', self.keys())
        self.assertEqual(result.returncode, 0, result.stderr)
        nsp = out / f'{self.BASE:016X}_base.nsp'
        names = [name for name, _, _ in dumps.entries(nsp)]
        self.assertEqual(len(names), 2)          # the base game's program NCA and its content meta NCA
        self.assertTrue(all(name.endswith('.nca') for name in names))

    @unittest.skipUnless(importlib.util.find_spec('Crypto'), 'no pycryptodome')
    def test_the_result_is_json(self):
        card = self.card()
        out = Path(tempfile.mkdtemp(prefix='nx2a_split_out_'))
        result = run('card_split.py', card, out, '--keys', self.keys(), '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out_json = json.loads(result.stdout)
        self.assertEqual(len(out_json['titles']), 3)
        self.assertEqual(out_json['titles'][0]['kind'], 'base')
        self.assertTrue(out_json['titles'][0]['bytes'] > 0)

    @unittest.skipUnless(importlib.util.find_spec('Crypto'), 'no pycryptodome')
    def test_the_nsps_land_next_to_the_card(self):
        card = self.card()
        result = run('card_split.py', card, '--keys', self.keys())
        self.assertEqual(result.returncode, 0, result.stderr)
        out = card.parent / f'Card-{self.BASE:016X}'
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, [f'{self.BASE:016X}_base.nsp', f'{self.BASE + 0x800:016X}_update.nsp',
                                 f'{self.BASE + 0x1001:016X}_dlc.nsp'])

    def test_a_file_that_is_not_a_dump_is_an_error(self):
        path = Path(tempfile.mkdtemp(prefix='nx2a_split_')) / 'x.nsp'
        path.write_bytes(b'not a dump')
        result = run('card_split.py', path, tempfile.mkdtemp(prefix='nx2a_split_out_'), '--keys', self.keys())
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)

    def test_a_missing_keys_file_is_an_error(self):
        path = Path(tempfile.mkdtemp(prefix='nx2a_split_')) / 'x.nsp'
        path.write_bytes(b'not a dump')
        missing = Path(tempfile.mkdtemp(prefix='nx2a_keys_')) / 'prod.keys'
        result = run('card_split.py', path, tempfile.mkdtemp(prefix='nx2a_split_out_'), '--keys', missing)
        self.assertEqual(result.returncode, 2)
        self.assertIn('prod.keys', result.stderr)
        self.assertNotIn('Traceback', result.stderr)


class UpstreamDiff(unittest.TestCase):
    def test_the_three_groups_are_told_apart(self):
        import upstream_diff
        mine = {'porter/a.py': '1', 'porter/b.py': '2', 'porter/only-mine.py': '3'}
        theirs = {'porter/a.py': '1', 'porter/b.py': '9', 'porter/only-upstream.py': '4'}
        only_mine, only_theirs, different = upstream_diff.compare(mine, theirs)
        self.assertEqual(only_mine, ['porter/only-mine.py'])
        self.assertEqual(only_theirs, ['porter/only-upstream.py'])
        self.assertEqual(different, ['porter/b.py'])


class UpstreamPr(unittest.TestCase):
    """The upstream's PRs: the fix may already exist, and GitHub may not answer at all."""

    def test_the_search_url_asks_for_pull_requests(self):
        import upstream_pr
        url = upstream_pr.search_url('shirai91/nx2android', 'cross chunk copy', include_issues=False)
        self.assertIn('repo:shirai91%2Fnx2android', url)
        self.assertIn('is:pr', url)

    def test_the_search_url_can_ask_for_issues(self):
        import upstream_pr
        url = upstream_pr.search_url('seedds/nxnative', 'vk_buf_at', include_issues=True)
        self.assertIn('is:issue', url)

    def test_the_hits_are_shortlisted(self):
        import upstream_pr
        answer = {'items': [
            {'number': 179, 'title': 'cross-chunk buffer copies', 'state': 'closed',
             'pull_request': {'merged_at': '2026-01-02T00:00:00Z'},
             'html_url': 'https://github.com/shirai91/nx2android/pull/179',
             'created_at': '2026-01-01T00:00:00Z', 'body': 'fixes the copy'},
            {'number': 20, 'title': 'something else', 'state': 'open',
             'html_url': 'https://github.com/shirai91/nx2android/pull/20',
             'created_at': '2026-01-01T00:00:00Z', 'body': ''},
        ]}
        hits = upstream_pr.results_of(answer)
        self.assertEqual(2, len(hits))
        self.assertTrue(hits[0]['merged'])
        self.assertEqual(179, hits[0]['number'])
        self.assertFalse(hits[1]['merged'])

    def test_a_search_that_does_not_answer_is_one_line(self):
        # 网络不通不是崩溃：工具说清了就停，调用方继续走自己的诊断
        import upstream_pr

        def broken(url):
            raise upstream_pr.FetchError('network', 'the host name could not be resolved', 2)

        original = upstream_pr.ask
        upstream_pr.ask = broken
        try:
            results, unreachable = upstream_pr.collect(('shirai91/nx2android',), 'x', False)
        finally:
            upstream_pr.ask = original
        self.assertEqual([], results)
        self.assertEqual(1, len(unreachable))
        self.assertEqual('network', unreachable[0]['kind'])


class MemorySearch(unittest.TestCase):
    """The knowledge search: the upstream cases, the knowledge documents, the closed issues and
    the phone's own cases, in one index.

    The tool is the one that ships with the App (it lives in the tool tree), and it is run the
    way the assistant runs it.
    """

    TOOL = ROOT / 'phone_tools' / 'memory_search.py'

    DOC = """# A document

## The crash
A crash at the start with `x1 = 0x25a1` is the shared font: it has no glyph for the
fallback character and the lookup dereferenced a null.

## The build
The port stops at a stage when the shader split finds too few shaders.
"""

    # The blind spots of a keyword search: the words a player uses and the words
    # the corpus uses for the same thing. Each row is a question that used to
    # find nothing (or the wrong thing), and the word that carries it over.
    BLIND_SPOTS = (
        ('the game freezes after the intro', 'freeze'),
        ('it hangs on the loading screen', 'hang'),
        ('it stutters every few seconds', 'stutter'),
        ('laggy gameplay', 'stutter'),
        ('the controls do not respond', 'controller'),
        ('gamepad not detected', 'controller'),
        ('gyro aiming does not work', 'gyroscope'),
        ('the game is capped at 30 fps', 'pin'),
        ('the game will not start', 'boot'),
        ('the screen is garbled', 'garbled'),
    )

    def search(self, *args, **kwargs):
        """The search, run as the assistant runs it."""
        env = dict(kwargs.pop('env', {}), PYTHONUTF8='1')
        kwargs.setdefault('encoding', 'utf-8')
        return subprocess.run([sys.executable, str(self.TOOL), *args],
                              capture_output=True, text=True, env=env, **kwargs)

    def docs(self, text=None, name='runtime-symptoms.md'):
        """A folder with one knowledge document in it."""
        folder = Path(tempfile.mkdtemp(prefix='nx2a_docs_'))
        (folder / name).write_text(text if text is not None else self.DOC)
        return folder

    def index(self, rows=('shirai91\t419\tMERGED\tprofile\tcrash\thost\tcore\tyes\t\t\t\t\t'
                          'fix(host): readable zero slack behind each module\tA read past the end of a module\t'
                          'https://github.com/shirai91/nx2android/pull/419',)):
        """A case index with a header and a few rows."""
        folder = Path(tempfile.mkdtemp(prefix='nx2a_index_'))
        header = 'source\tref\tstate\tarea\tsymptom\tlayer\tkind\tfork\tgame\tids\tswitches\tpaths\ttitle\tsummary\turl'
        (folder / 'case-index.tsv').write_text('\n'.join([header, *rows]))
        return folder

    def build(self, public=None, player=None, issues=None, extra=()):
        """An index built from the given folders, and its directory."""
        index_dir = Path(tempfile.mkdtemp(prefix='nx2a_search_')) / 'index'
        args = ['build', '--index', str(index_dir)]
        if public:
            args += ['--public', str(public)]
        if player:
            args += ['--player', str(player)]
        if issues:
            args += ['--issues', ','.join(str(i) for i in issues)]
        result = self.search(*args, *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return index_dir

    def test_a_document_is_found_by_section(self):
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir), 'shared font glyph')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('The crash', result.stdout)
        self.assertIn('lines', result.stdout)          # where the section is
        self.assertIn('0x25a1', result.stdout)         # a snippet of it

    def test_a_section_is_printed_as_it_is(self):
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir), '--section', 'The crash')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('The crash', result.stdout)
        self.assertIn('it has no glyph for the', result.stdout)

    def test_a_section_that_is_not_there_says_so(self):
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir), '--section', 'Nothing')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('no section titled', result.stdout)

    def test_nothing_found_points_at_the_other_corpus(self):
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir), 'qwertyuiop')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('nothing found', result.stdout)
        self.assertIn('rewrite the question in english', result.stdout)

    def test_the_answer_stays_small(self):
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir), 'font')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(len(result.stdout), 4000)

    def test_a_case_carries_its_number(self):
        index_dir = self.build(public=self.index())
        result = self.search('search', '--index', str(index_dir), 'zero slack')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('shirai91#419', result.stdout)   # the pull request number
        self.assertIn('[pr]', result.stdout)           # which corpus it came from

    def test_a_case_entry_with_a_stage_keeps_its_fields(self):
        """An entry that carries the stage of the port's life is still an entry: the case corpus
        has to hand out its status, cause and fix (the entry format grew the stage in 2026-11-25
        and the search lost every field of the new format)."""
        folder = Path(tempfile.mkdtemp(prefix='nx2a_player_'))
        case = folder / '010078D000F88000'
        case.mkdir(parents=True)
        (case / 'spec.md').write_text(
            '# DRAGON BALL XENOVERSE 2 (010078D000F88000) case file\n\n'
            '## Runtime problems\n\n'
            '### 2026-11-25 the guest crashes with SIGSEGV (status: pending approval) [stage 2]\n'
            'Symptom: the game is gone five seconds in\n'
            'Cause: a null this pointer in the guest NVN client library\n'
            'Proposed fix: the movie module needs the queue before the texture\n'
            'Evidence: the crash line in log.txt\n'
            'Plan:\n- [ ] 1. one change - verify: a run that lasts\n')
        index_dir = self.build(player=folder)
        result = self.search('search', '--index', str(index_dir), '--corpus', 'case', 'SIGSEGV')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('status: pending approval', result.stdout)
        self.assertIn('a null this pointer', result.stdout)
        self.assertIn('the movie module needs the queue', result.stdout)

    def test_the_cases_are_capped(self):
        rows = tuple(f'shirai91\t{n}\tMERGED\tprofile\tcrash\thost\tcore\tyes\t\t\t\t\t'
                     f'fix(host): case {n}\tsummary {n}\thttps://example/{n}' for n in range(40))
        index_dir = self.build(public=self.index(rows))
        result = self.search('search', '--index', str(index_dir), '--corpus', 'pr', 'crash')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('40 matched', result.stdout)
        self.assertIn('12 shown', result.stdout)

    def test_the_json_gives_the_same_count_as_the_text(self):
        rows = tuple(f'shirai91\t{n}\tMERGED\tprofile\tcrash\thost\tcore\tyes\t\t\t\t\t'
                     f'fix(host): case {n}\tsummary {n}\thttps://example/{n}' for n in range(40))
        index_dir = self.build(public=self.index(rows))
        text = self.search('search', '--index', str(index_dir), '--corpus', 'pr', 'crash')
        out = json.loads(self.search('search', '--index', str(index_dir), '--corpus', 'pr',
                                      'crash', '--json').stdout)
        self.assertEqual(40, out['count'])
        self.assertEqual(12, out['shown'])
        self.assertEqual(12, len(out['hits']))
        self.assertIn('40 matched', text.stdout)

    def test_the_shipped_documents_are_searchable(self):
        index_dir = self.build(public=(ROOT / 'android/app/src/main/assets/nx2a/agent/'
                                       'dot-agents/skills/port-failures/references'))
        result = self.search('search', '--index', str(index_dir), '--corpus', 'doc',
                             'shared font')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('shared fonts', result.stdout.lower())

    def test_the_phone_own_cases_are_searched(self):
        home = Path(tempfile.mkdtemp(prefix='nx2a_home_'))
        case = home / 'gamespec' / '0100A3501946E000'
        case.mkdir(parents=True)
        (case / 'spec.md').write_text(
            '# Super Game (0100A3501946E000) case file\n\n'
            '## Problems\n\n'
            '### 2026-11-23 the black screen (status: fixed)\n\n'
            'Symptom: the screen stays black after the logo.\n\n'
            'Cause: the shaders were not in the bundle.\n\n'
            'Fix: capture them and port again.\n')
        index_dir = self.build(player=home)
        result = self.search('search', '--index', str(index_dir), '--corpus', 'case',
                             'black screen')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0100A3501946E000', result.stdout)   # the title id
        self.assertIn('shaders', result.stdout)             # the cause and the fix
        self.assertIn('fixed', result.stdout)               # the status

    def test_a_chinese_question_is_bridged(self):
        home = Path(tempfile.mkdtemp(prefix='nx2a_home_'))
        case = home / 'gamespec' / '0100A3501946E000'
        case.mkdir(parents=True)
        (case / 'spec.md').write_text(
            '# Super Game (0100A3501946E000) case file\n\n'
            '## Problems\n\n'
            '### 2026-11-23 the black screen (status: fixed)\n\n'
            'Symptom: the screen stays black after the logo.\n\n'
            'Cause: the shaders were not in the bundle.\n\n'
            'Fix: capture them and port again.\n')
        index_dir = self.build(player=home)
        result = self.search('search', '--index', str(index_dir), '--corpus', 'case', '黑屏')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('0100A3501946E000', result.stdout)

    def test_the_filter_picks_the_field(self):
        index_dir = self.build(public=self.index())
        result = self.search('search', '--index', str(index_dir), '--corpus', 'pr',
                             '--symptom', 'crash', 'slack')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('shirai91#419', result.stdout)
        result = self.search('search', '--index', str(index_dir), '--corpus', 'pr',
                             '--symptom', 'memory', 'slack')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('shirai91#419', result.stdout)

    def test_an_index_is_built_when_there_is_none(self):
        index_dir = Path(tempfile.mkdtemp(prefix='nx2a_search_')) / 'index'
        result = self.search('search', '--index', str(index_dir), '--public',
                             str(self.docs()), 'shared font')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('building it', result.stdout)
        self.assertIn('The crash', result.stdout)

    def test_the_command_the_documents_show_works(self):
        """The assistant writes the command it was told to write.

        The first real session on the phone failed every search with a usage
        error: the documents showed "memory_search.py --corpus case 'black
        screen'" and the tool wanted the verb "search" in front. The verb is
        optional now, and this test keeps the documented form working.
        """
        index_dir = self.build(public=self.docs())
        result = self.search('--index', str(index_dir), 'shared font')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('The crash', result.stdout)
        self.assertNotIn('invalid choice', result.stderr)

    def test_the_verb_is_still_accepted(self):
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir), 'shared font')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('The crash', result.stdout)

    def test_a_one_word_the_corpus_spell_with_a_space_is_found(self):
        """'framerate' in the question, 'frame rate' in the corpus.

        The alias table carries the bridge between the two spellings; without
        it the query found nothing at all (the corpus never writes "framerate").
        """
        folder = self.docs(text="""# A document

## The pacing
The frame rate is the wrong number for a driver comparison: the pacing and the
frame rate pin both move with the driver.
""")
        index_dir = self.build(public=folder)
        result = self.search('search', '--index', str(index_dir), 'framerate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('The pacing', result.stdout)

    def test_the_questions_a_player_asks_are_found(self):
        """The words a player uses and the words the corpus uses.

        Each question here found nothing before: the corpus writes "freeze",
        "stutter", "controller", "boot" and the player writes "freezes",
        "stutters", "controls", "will not start". The alias tables carry the
        question over. The document below holds the base forms only, so a
        question that matched directly would not prove anything.
        """
        text = """# A document

## The frozen game
The game can freeze when the present wait is counted as the frame work.

## The stutter
A stutter of one second each time an asset loads, and the audio is missing.

## The controller
A controller that is not read: the gyroscope of the pad is ignored, and the
aiming follows the phone instead.

## The frame rate
The rate is capped by the pin of the profile, and the game will not start
without the boot stage.

## The garbled picture
A garbled picture on the screen.
"""
        index_dir = self.build(public=self.docs(text=text))
        for query, expected in self.BLIND_SPOTS:
            result = self.search('search', '--index', str(index_dir), query)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('(nothing found)', result.stdout, query)
            self.assertIn(expected.lower(), result.stdout.lower(), query)

    def test_the_chinese_words_a_player_uses_are_found(self):
        """The same, from the player's side of the language.

        The corpus is in english; these are the words the player writes and the
        words the corpus writes instead.
        """
        text = """# A document

## The stutter
A stutter of one second each time an asset loads, and the audio is missing.

## The frame rate
The rate is capped by the pin of the profile.

## The garbled picture
A garbled picture on the screen.
"""
        index_dir = self.build(public=self.docs(text=text))
        for query, expected in (('花屏', 'garbled'), ('锁帧', 'pin'),
                                ('没有声音', 'audio'), ('很卡', 'stutter')):
            result = self.search('search', '--index', str(index_dir), query)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('(nothing found)', result.stdout, query)
            self.assertIn(expected.lower(), result.stdout.lower(), query)

    def test_a_filter_without_a_question_lists_what_it_matches(self):
        """'Every upstream PR about performance' is a question the filter answers.

        The assistant asked for it exactly this way (search --symptom perf)
        and got nothing back - a filter without a question is a browse, not a
        failed search.
        """
        index_dir = self.build(public=self.index())
        result = self.search('search', '--index', str(index_dir), '--corpus', 'pr',
                             '--symptom', 'crash')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('readable zero slack', result.stdout)
        self.assertNotIn('nothing to search for', result.stdout)

    def test_the_nothing_to_search_notice_is_readable(self):
        """The notice goes to stdout: the caller pipes the output."""
        index_dir = self.build(public=self.docs())
        result = self.search('search', '--index', str(index_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('nothing to search for', result.stdout)
        self.assertNotIn('nothing to search for', result.stderr)

    def test_a_stale_index_is_rebuilt_and_says_so(self):
        """The sources changed (the app updated, a case was closed).

        Searching a stale index answers from the old documents, so the index is
        rebuilt - and the notice goes to stdout, because the caller pipes the
        output and a warning on stderr is a warning nobody reads.
        """
        folder = self.docs()
        index_dir = self.build(public=folder)
        time.sleep(1.1)
        (folder / 'runtime-symptoms.md').write_text('# A document\n\n## The crash\nchanged\n')
        result = self.search('search', '--index', str(index_dir), '--public', str(folder),
                             'changed')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('rebuilding it', result.stdout)
        self.assertIn('changed', result.stdout)


class GamespecPack(unittest.TestCase):
    """The case file of one game, packed into a zip the player hands to the upstream."""

    GAME = '0100A3501946E000'

    def case(self, files=None, manifest=None, spec=True, orig=None):
        """A case file: the document, the manifest and the files it lists (with their originals)."""
        home = Path(tempfile.mkdtemp(prefix='nx2a_gamespec_'))
        case = home / 'gamespec' / self.GAME
        (case / 'files').mkdir(parents=True)
        if spec:
            (case / 'spec.md').write_text('# 攻关档案\n\n## 现状\n卡在着色器解码。\n', encoding='utf-8', newline='\n')
        for path, text in (files or {}).items():
            target = case / 'files' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8', newline='\n')
        for path, text in (orig or {}).items():
            target = case / 'orig' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8', newline='\n')
        (case / 'fix.md').write_text('\n'.join(manifest if manifest is not None else list((files or {}).keys())),
                                     encoding='utf-8', newline='\n')
        return home, case

    def pack(self, home, *args):
        return run('gamespec_pack.py', '--game', self.GAME, *args, env={'NX2A_HOME': str(home)})

    def test_the_case_file_is_packed(self):
        home, case = self.case(files={
            'nxnative/dm/android/gfx_vk_present.c': '// fixed\n',
            'porter/pipeline.py': '# fixed\n',
        })
        result = self.pack(home, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertTrue(out['zip'].endswith('.zip'))

        import zipfile
        with zipfile.ZipFile(out['zip']) as zf:
            names = zf.namelist()
            self.assertIn('spec.md', names)
            self.assertIn('fix.md', names)
            self.assertIn('files/nxnative/dm/android/gfx_vk_present.c', names)
            self.assertIn('files/porter/pipeline.py', names)
            self.assertEqual(zf.read('files/porter/pipeline.py'), b'# fixed\n')

    def test_a_game_file_in_the_manifest_is_refused(self):
        home, case = self.case(files={'game.nsp': 'x'}, manifest=['game.nsp'])
        result = self.pack(home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('游戏文件', result.stderr)
        self.assertFalse((case.parent / f'{self.GAME}-gamespec.zip').exists())

    def test_a_key_in_the_manifest_is_refused(self):
        home, case = self.case(files={'prod.keys': 'x'}, manifest=['prod.keys'])
        result = self.pack(home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('密钥', result.stderr)

    def test_a_path_out_of_the_tree_is_refused(self):
        home, case = self.case(files={}, manifest=['../secrets.txt'])
        result = self.pack(home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('往上走', result.stderr)

    def test_a_listed_file_that_is_missing_is_refused(self):
        home, case = self.case(files={}, manifest=['porter/pipeline.py'])
        result = self.pack(home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('files/', result.stderr)

    def test_a_game_without_a_case_file_says_so(self):
        home = Path(tempfile.mkdtemp(prefix='nx2a_gamespec_'))
        result = self.pack(home)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('没有攻关档案', result.stderr)

    def test_a_diff_is_packed_when_the_original_is_there(self):
        # 原件在档案里，包里就多一份 diff：上游拿到就能 git apply，不用自己比
        home, case = self.case(
            files={'nxnative/dm/android/gfx_vk_present.c': '// fixed\n'},
            orig={'nxnative/dm/android/gfx_vk_present.c': '// before\n'},
        )
        result = self.pack(home, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(['nxnative/dm/android/gfx_vk_present.c'], out['diffed'])

        import zipfile
        with zipfile.ZipFile(out['zip']) as zf:
            names = zf.namelist()
            self.assertIn('diff.patch', names)
            self.assertIn('orig/nxnative/dm/android/gfx_vk_present.c', names)
            patch = zf.read('diff.patch').decode('utf-8')
            self.assertIn('--- a/nxnative/dm/android/gfx_vk_present.c', patch)
            self.assertIn('+++ b/nxnative/dm/android/gfx_vk_present.c', patch)
            self.assertIn('-// before', patch)
            self.assertIn('+// fixed', patch)

    def test_a_case_without_originals_is_packed_as_it_was(self):
        # 老档案没有原件：照旧打包（整份文件），没有 diff，也不报错
        home, case = self.case(files={'porter/pipeline.py': '# fixed\n'})
        result = self.pack(home, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual([], out['diffed'])

        import zipfile
        with zipfile.ZipFile(out['zip']) as zf:
            names = zf.namelist()
            self.assertNotIn('diff.patch', names)
            self.assertIn('files/porter/pipeline.py', names)

    def test_a_comment_line_in_the_manifest_is_not_a_path(self):
        # fix.md 顶上的那行「基于哪个版本」是注释：不是路径
        home, case = self.case(files={'porter/pipeline.py': '# fixed\n'})
        (case / 'fix.md').write_text(
            '# based on: app 0.4.0-alpha03, porter 0.3.0, fixed 2026-11-24\nporter/pipeline.py\n',
            encoding='utf-8', newline='\n',
        )
        result = self.pack(home, '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual(['porter/pipeline.py'], out['files'])


class ToolHousekeeping(unittest.TestCase):
    def test_every_tool_has_a_help_and_a_json_flag(self):
        for tool in sorted(TOOLS.glob('*.py')):
            if tool.name.startswith('nx2a_common'): continue
            with self.subTest(tool=tool.name):
                result = run(tool.name, '--help')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('--json', result.stdout)

    def test_the_readme_lists_every_tool(self):
        readme = (TOOLS / 'README.md').read_text()
        for tool in sorted(TOOLS.glob('*.py')):
            if tool.name.startswith('nx2a_common'): continue
            self.assertIn(tool.name, readme, f'{tool.name} is not in the README')


if __name__ == '__main__':
    unittest.main()
