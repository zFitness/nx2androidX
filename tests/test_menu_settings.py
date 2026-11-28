# Targeted checks for the pause-menu settings storage (menu/dm_menu.c / dm_settings_store.c).
# Focus: >4KB long lines and unknown keys must survive a set; a failed save must never
# overwrite the player's file; in-process cache must stay consistent after a save.
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

    def set_fps(self, value: int):
        return self.run_harness('set', str(value))

    def test_long_lines_and_unknown_keys_survive_a_set(self):
        long_line = 'bar=' + 'x' * 5000 + '\n'   # far past any fixed-size body buffer
        (self.dir / 'settings.txt').write_text(f'foo=1\n{long_line}fps=0\nbaz=2\n')
        r = self.set_fps(3)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.dir / 'settings.txt').read_text(),
                         f'foo=1\n{long_line}fps=3\nbaz=2\n')

    def test_missing_trailing_newline_is_repaired_when_appending(self):
        (self.dir / 'settings.txt').write_text('foo=1')
        self.assertEqual(self.set_fps(5).returncode, 0)
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'foo=1\nfps=5\n')

    def test_no_leftover_temp_file_after_success(self):
        (self.dir / 'settings.txt').write_text('fps=0\n')
        self.assertEqual(self.set_fps(1).returncode, 0)
        self.assertFalse((self.dir / 'settings.txt.new').exists())
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'fps=1\n')

    def test_failed_write_keeps_original(self):
        """The temp path occupied -> fopen(tmp) fails -> the original stays byte-identical."""
        file_path = self.dir / 'settings.txt'
        original = 'foo=1\nfps=7\nlong=' + 'y' * 6000 + '\n'
        file_path.write_text(original)
        (self.dir / 'settings.txt.new').mkdir()
        self.set_fps(9)
        self.assertEqual(file_path.read_text(), original)   # nothing truncated or lost
        self.assertNotIn('fps=9', file_path.read_text())

    @unittest.skipIf(hasattr(os, 'geteuid') and os.geteuid() == 0, 'root ignores file permissions')
    def test_unreadable_file_is_never_overwritten(self):
        file_path = self.dir / 'settings.txt'
        original = 'fps=2\nkeepme=1\n'
        file_path.write_text(original)
        file_path.chmod(0o000)
        try:
            self.set_fps(9)
        finally:
            file_path.chmod(0o644)
        self.assertEqual(file_path.read_text(), original)

    def test_value_persists_to_a_fresh_process(self):
        self.assertEqual(self.set_fps(1).returncode, 0)
        self.assertEqual(self.run_harness('get').stdout.strip(), '1')

    def test_cache_is_refreshed_by_a_successful_save(self):
        (self.dir / 'settings.txt').write_text('fps=0\n')
        r = self.run_harness('cycle', '4')   # set 4 then get in the same process
        self.assertEqual(r.stdout.strip(), '4')   # the cache published the save immediately
        self.assertEqual((self.dir / 'settings.txt').read_text(), 'fps=4\n')


if __name__ == '__main__':
    unittest.main()
