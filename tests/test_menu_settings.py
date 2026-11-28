# Targeted checks for the pause-menu settings storage (menu/dm_menu.c / dm_settings_store.c).
# Focus: >4KB long lines and unknown keys must survive a set; a failed save must never
# overwrite the player's file and must report failure; the hot settings (fps, sr, sharpness)
# are cached with range clamping and reloaded on demand.
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / 'tests' / 'menu_settings_harness.c'


def compile_harness(tmp: Path) -> str | None:
    """Compile the standalone harness; returns its path, or None when no compiler exists."""
    for cc in ('clang', 'gcc', 'cc'):
        if shutil.which(cc):
            out = tmp / 'harness'
            r = subprocess.run([cc, '-std=gnu11', '-O2', '-D_DEFAULT_SOURCE', str(HARNESS), '-o', str(out)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return out
            raise AssertionError(f'{cc} failed: {r.stderr[:2000]}')
    return None


class MenuSettingsStorage(unittest.TestCase):
    """menu/dm_settings_store.c: safe whole-file rewrite semantics."""

    @classmethod
    def setUpClass(cls):
        cls._builddir = Path(tempfile.mkdtemp(prefix='menu-settings-test-'))
        cls.harness = compile_harness(cls._builddir)
        if cls.harness is None:
            shutil.rmtree(cls._builddir, ignore_errors=True)
            raise unittest.SkipTest('no C compiler available')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._builddir, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='menu-settings-dir-'))
        self.env = {**os.environ, 'DM_ROOT': str(self.dir)}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_harness(self, *args):
        return subprocess.run([str(self.harness), *args], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def set_key(self, key: str, value: int):
        return self.run_harness('set', key, str(value))

    def test_long_lines_and_unknown_keys_survive_a_set(self):
        long_line = 'bar=' + 'x' * 5000 + '\n'   # far past any fixed-size body buffer
        (self.dir / 'settings.txt').write_text(f'foo=1\n{long_line}custom=0\nbaz=2\n')
        r = self.set_key('custom', 3)   # a cold key: the rewrite is generic, no range clamp
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.dir / 'settings.txt').read_text(),
                         f'foo=1\n{long_line}custom=3\nbaz=2\n')

    def test_missing_trailing_newline_is_repaired_when_appending(self):
        (self.dir / 'settings.txt').write_text('foo=1')
        self.assertEqual(self.set_key('custom', 5).returncode, 0)
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'foo=1\ncustom=5\n')

    def test_no_leftover_temp_file_after_success(self):
        (self.dir / 'settings.txt').write_text('fps=0\n')
        self.assertEqual(self.set_key('fps', 1).returncode, 0)
        self.assertFalse((self.dir / 'settings.txt.new').exists())
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'fps=1\n')

    def test_failed_write_keeps_original(self):
        """The temp path occupied -> fopen(tmp) fails -> the original stays byte-identical."""
        file_path = self.dir / 'settings.txt'
        original = 'foo=1\ncustom=7\nlong=' + 'y' * 6000 + '\n'
        file_path.write_text(original)
        (self.dir / 'settings.txt.new').mkdir()
        r = self.set_key('custom', 9)
        self.assertNotEqual(r.returncode, 0, 'a failed save must report failure')   # the menu must not show it saved
        self.assertEqual(file_path.read_text(), original)   # nothing truncated or lost
        self.assertNotIn('custom=9', file_path.read_text())

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores file permissions')
    def test_unreadable_file_is_never_overwritten(self):
        file_path = self.dir / 'settings.txt'
        original = 'custom=2\nkeepme=1\n'
        file_path.write_text(original)
        file_path.chmod(0o000)
        try:
            r = self.set_key('custom', 9)
            self.assertNotEqual(r.returncode, 0, 'an unreadable file must report failure')
        finally:
            file_path.chmod(0o644)
        self.assertEqual(file_path.read_text(), original)

    def test_value_persists_to_a_fresh_process(self):
        self.assertEqual(self.set_key('fps', 1).returncode, 0)
        self.assertEqual(self.run_harness('get', 'fps').stdout.strip(), '1')

    def test_cache_is_refreshed_by_a_successful_save(self):
        (self.dir / 'settings.txt').write_text('fps=0\n')
        r = self.run_harness('cycle', 'fps', '1')   # set 1 then get in the same process
        self.assertEqual(r.stdout.strip(), '0 1')   # rc 0, and the cache published the save immediately
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'fps=1\n')


class MenuSettingsCache(unittest.TestCase):
    """The hot settings (fps, sr, sharpness): defaults, range clamping, reload."""

    @classmethod
    def setUpClass(cls):
        cls._builddir = Path(tempfile.mkdtemp(prefix='menu-settings-test-'))
        cls.harness = compile_harness(cls._builddir)
        if cls.harness is None:
            shutil.rmtree(cls._builddir, ignore_errors=True)
            raise unittest.SkipTest('no C compiler available')

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._builddir, ignore_errors=True)

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='menu-settings-dir-'))
        self.env = {**os.environ, 'DM_ROOT': str(self.dir)}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_harness(self, *args):
        return subprocess.run([str(self.harness), *args], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def test_missing_keys_read_their_defaults(self):
        self.assertEqual(self.run_harness('get', 'fps').stdout.strip(), '0')
        self.assertEqual(self.run_harness('get', 'sr').stdout.strip(), '0')
        self.assertEqual(self.run_harness('get', 'sharpness').stdout.strip(), '0')

    def test_counter_option_defaults_and_ranges(self):
        # the FPSO_* defaults (dm_fps_opts.h): fps_rows = FPS|SOC|BAT = 7, fps_size = FPSO_NORMAL = 1
        self.assertEqual(self.run_harness('get', 'fps_rows').stdout.strip(), '7')
        self.assertEqual(self.run_harness('get', 'fps_pos').stdout.strip(), '0')
        self.assertEqual(self.run_harness('get', 'fps_size').stdout.strip(), '1')
        # ranges: fps_rows [0,31], fps_pos [0,3], fps_colour/outline [0,4], fps_size [0,3]
        self.assertEqual(self.run_harness('cycle', 'fps_rows', '40').stdout.strip(), '0 31')
        self.assertEqual(self.run_harness('cycle', 'fps_pos', '9').stdout.strip(), '0 3')
        self.assertEqual(self.run_harness('cycle', 'fps_size', '-2').stdout.strip(), '0 0')

    def test_set_clamps_to_the_legal_range(self):
        self.assertEqual(self.run_harness('set', 'sharpness', '150').returncode, 0)
        self.assertIn('sharpness=100\n', (self.dir / 'settings.txt').read_text())   # clamped to the max
        self.assertEqual(self.run_harness('set', 'sharpness', '-5').returncode, 0)
        self.assertIn('sharpness=0\n', (self.dir / 'settings.txt').read_text())   # clamped to the min
        self.assertEqual(self.run_harness('set', 'sr', '2').returncode, 0)
        self.assertIn('sr=1\n', (self.dir / 'settings.txt').read_text())   # a bool clamps to 1

    def test_out_of_range_file_value_reads_clamped(self):
        (self.dir / 'settings.txt').write_text('sharpness=250\nsr=3\n')
        self.assertEqual(self.run_harness('get', 'sharpness').stdout.strip(), '100')
        self.assertEqual(self.run_harness('get', 'sr').stdout.strip(), '1')

    def test_malformed_value_reads_the_default(self):
        (self.dir / 'settings.txt').write_text('fps=abc\nsharpness=\n')
        self.assertEqual(self.run_harness('get', 'fps').stdout.strip(), '0')   # not a number -> default
        self.assertEqual(self.run_harness('get', 'sharpness').stdout.strip(), '0')

    def test_reload_picks_up_an_external_edit(self):
        (self.dir / 'settings.txt').write_text('sr=0\n')
        self.assertEqual(self.run_harness('get', 'sr').stdout.strip(), '0')
        (self.dir / 'settings.txt').write_text('sr=1\n')   # an outside edit (another process, the player)
        self.assertEqual(self.run_harness('reload', 'sr').stdout.strip(), '1')   # reload re-reads the file

    def test_set_returns_failure_and_keeps_original(self):
        (self.dir / 'settings.txt').write_text('sr=0\n')
        (self.dir / 'settings.txt.new').mkdir()   # the temp path occupied: the save must fail
        r = self.run_harness('set', 'sr', '1')
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'sr=0\n')


if __name__ == '__main__':
    unittest.main()
