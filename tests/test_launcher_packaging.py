"""The ARM64 Linux package: what goes into it, and what the launcher does inside it."""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import appimage   # noqa: E402


def load(name: str, path: Path):
    """A module that is not in a package (the packaging folder's name has a dash)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('nx2a_build_appimage', REPO / 'packaging/arm-linux/build_appimage.py')


class TheTree(unittest.TestCase):
    """What the package carries: a trimmed repository root."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.source = Path(self.folder.name) / 'nxnative'
        (self.source / 'dm/games/0100000000010000').mkdir(parents=True)
        (self.source / 'dm/games/0100000000010000/game.tsv').write_text('x', encoding='utf-8')
        (self.source / 'dm/ios').mkdir(parents=True)
        (self.source / 'dm/ios/notes.md').write_text('x', encoding='utf-8')
        (self.source / 'dm/android/apk').mkdir(parents=True)
        (self.source / 'dm/android/apk/mkapk.py').write_text('x', encoding='utf-8')
        (self.source / 'dm/tools').mkdir(parents=True)
        (self.source / 'dm/tools/patch_nso.py').write_text('x', encoding='utf-8')
        (self.source / 'dm/__pycache__').mkdir(parents=True)
        (self.source / 'dm/__pycache__/junk.pyc').write_text('x', encoding='utf-8')
        self.target = Path(self.folder.name) / 'out'

    def test_the_profiles_are_left_out_unless_asked_for(self):
        build.copy_tree(self.source, self.target, build.SKIP_TREE + ('dm/games',))
        self.assertFalse((self.target / 'dm/games').exists())
        self.assertTrue((self.target / 'dm/tools/patch_nso.py').is_file())

    def test_the_profiles_are_in_the_full_package(self):
        build.copy_tree(self.source, self.target, build.SKIP_TREE)
        self.assertTrue((self.target / 'dm/games/0100000000010000/game.tsv').is_file())

    def test_the_ios_line_and_the_phone_packager_stay_out(self):
        build.copy_tree(self.source, self.target, build.SKIP_TREE)
        self.assertFalse((self.target / 'dm/ios').exists())
        self.assertFalse((self.target / 'dm/android/apk').exists())

    def test_the_build_junk_stays_out(self):
        build.copy_tree(self.source, self.target, build.SKIP_TREE)
        self.assertFalse((self.target / 'dm/__pycache__').exists())


class ThePackage(unittest.TestCase):
    """The package itself: an ELF with the type-2 magic and a squashfs behind the runtime."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.out = Path(self.folder.name) / 'nx2androidX-arm64.AppImage'

    def make(self, runtime_size: int = 64, magic: bytes = b'AI\x02', squash: bytes = b'hsqs'):
        with open(self.out, 'wb') as handle:
            handle.write(b'\x7fELF' + b'\0' * 4 + magic)      # 11 bytes: the ELF magic and the type-2 magic
            handle.write(b'\0' * (runtime_size - 11))            # the rest of the runtime
            handle.write(squash)                                 # the squashfs superblock behind it

    def test_a_good_package_passes(self):
        self.make()
        build.check(self.out, 64)   # no exception: the package is what it says it is

    def test_a_file_that_is_not_an_elf_is_refused(self):
        self.out.write_bytes(b'not an elf at all')
        with self.assertRaises(SystemExit):
            build.check(self.out, 64)

    def test_a_package_without_the_magic_is_refused(self):
        self.make(magic=b'XX\x02')
        with self.assertRaises(SystemExit):
            build.check(self.out, 64)

    def test_a_package_without_a_squashfs_is_refused(self):
        self.make(squash=b'nope')
        with self.assertRaises(SystemExit):
            build.check(self.out, 64)


class InsideThePackage(unittest.TestCase):
    """The engine tree inside the package is read-only: the launcher copies it."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.repo = Path(self.folder.name) / 'repo'
        (self.repo / 'nxnative/dm/games/0100000000010000').mkdir(parents=True)
        (self.repo / 'nxnative/dm/games/0100000000010000/game.tsv').write_text('x', encoding='utf-8')
        (self.repo / 'nxnative/dm/tools').mkdir(parents=True)
        (self.repo / 'nxnative/dm/tools/patch_nso.py').write_text('x', encoding='utf-8')
        self.data = Path(self.folder.name) / 'data'
        self.original = os.environ.get(appimage.ENV_ENGINE)
        os.environ.pop(appimage.ENV_ENGINE, None)
        self.addCleanup(self._restore)

    def _restore(self):
        if self.original is None:
            os.environ.pop(appimage.ENV_ENGINE, None)
        else:
            os.environ[appimage.ENV_ENGINE] = self.original

    def test_outside_a_package_nothing_is_copied(self):
        os.environ.pop('APPIMAGE', None)
        self.assertIsNone(appimage.prepare(self.repo, self.data))
        self.assertFalse((self.data / 'engine').exists())

    def test_inside_a_package_the_tree_is_copied_and_pointed_at(self):
        os.environ['APPIMAGE'] = '/tmp/.mount_xyz'
        try:
            path = appimage.prepare(self.repo, self.data)
        finally:
            os.environ.pop('APPIMAGE', None)
        self.assertIsNotNone(path)
        self.assertTrue((Path(path) / 'dm/tools/patch_nso.py').is_file())
        self.assertEqual(os.environ[appimage.ENV_ENGINE], path)

    def test_the_profiles_are_linked_not_copied(self):
        os.environ['APPIMAGE'] = '/tmp/.mount_xyz'
        try:
            path = Path(appimage.prepare(self.repo, self.data))
        finally:
            os.environ.pop('APPIMAGE', None)
        profiles = path / 'dm/games'
        self.assertTrue(profiles.is_symlink())
        self.assertEqual((profiles / '0100000000010000/game.tsv').read_text(encoding='utf-8'), 'x')

    def test_a_second_run_does_not_copy_again(self):
        os.environ['APPIMAGE'] = '/tmp/.mount_xyz'
        try:
            first = appimage.prepare(self.repo, self.data)
            marker = Path(first) / 'dm/tools/marker.txt'
            marker.write_text('x', encoding='utf-8')
            second = appimage.prepare(self.repo, self.data)
        finally:
            os.environ.pop('APPIMAGE', None)
        self.assertEqual(first, second)
        self.assertTrue(marker.is_file(), 'the copy was made again')


class TheImport(unittest.TestCase):
    """The import of a profile package: the same command the phone app uses."""

    def test_the_command_is_the_porter_one(self):
        source = (REPO / 'launcher/ui/settings_page.py').read_text(encoding='utf-8')
        self.assertIn("['profiles', 'import', path]", source)

    def test_the_runner_answers_with_the_line_the_porter_printed(self):
        from launcher import runner
        self.assertTrue(callable(runner.run_text))


class TheSystemPython(unittest.TestCase):
    """The interface is GTK, so the package runs on the machine's own Python with
    PyGObject: the package carries the code, not the toolkit."""

    APPRUN = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')

    def test_apprun_runs_the_system_python(self):
        self.assertIn('PYTHON=/usr/bin/python3', self.APPRUN)
        self.assertIn('exec "$PYTHON" -m launcher', self.APPRUN)

    def test_the_package_carries_no_interpreter(self):
        self.assertNotIn('usr/python', self.APPRUN)
        self.assertNotIn('PYTHONHOME', self.APPRUN)

    def test_the_pipeline_finds_the_packages_own_code(self):
        self.assertIn('PYTHONPATH="$HERE/usr', self.APPRUN)

    def test_a_machine_without_the_bindings_is_told_what_to_install(self):
        entry = (REPO / 'launcher/__main__.py').read_text(encoding='utf-8')
        self.assertIn('python3-gi', entry)


class TheFonts(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.appdir = Path(self.folder.name) / 'AppDir'
        self.noto = Path(self.folder.name) / 'NotoSansSC-Regular.otf'
        self.noto.write_bytes(b'OTTO not a real font')
        self.license = Path(self.folder.name) / 'LICENSE.txt'
        self.license.write_text('the license', encoding='utf-8')
        self.dejavu = Path(self.folder.name) / 'dejavu.zip'
        import zipfile
        with zipfile.ZipFile(self.dejavu, 'w') as archive:
            archive.writestr('dejavu-fonts-ttf-2.37/ttf/DejaVuSansMono.ttf', 'mono')
            archive.writestr('dejavu-fonts-ttf-2.37/LICENSE', 'the license')

    def stage(self):
        build.stage_fonts(self.appdir, self.noto, self.license, self.dejavu)

    def test_the_chinese_font_is_in_the_package(self):
        self.stage()
        font = self.appdir / build.FONT_DIR / build.NOTO_FONT
        self.assertTrue(font.is_file())
        self.assertEqual(font.read_bytes(), b'OTTO not a real font')

    def test_the_monospace_font_is_in_the_package(self):
        self.stage()
        font = self.appdir / build.FONT_DIR / build.MONO_FONT
        self.assertTrue(font.is_file())
        self.assertEqual(font.read_bytes(), b'mono')

    def test_the_licenses_travel_with_the_fonts(self):
        self.stage()
        fonts = self.appdir / build.FONT_DIR
        self.assertTrue((fonts / 'NotoSansSC-LICENSE.txt').is_file())
        self.assertTrue((fonts / 'truetype/dejavu/LICENSE.txt').is_file())

    def test_the_font_directory_is_the_one_fontconfig_looks_in(self):
        self.assertEqual(build.FONT_DIR, 'usr/share/fonts')

    def test_apprun_points_fontconfig_at_the_package(self):
        apprun = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')
        self.assertIn('FONTCONFIG_FILE', apprun)
        self.assertIn('usr/share/fonts', apprun)
        self.assertIn('<dir>$FONTS</dir>', apprun)

    def test_apprun_keeps_the_fonts_of_the_machine_when_there_are_some(self):
        apprun = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')
        self.assertIn('/etc/fonts/fonts.conf', apprun)


if __name__ == '__main__':
    unittest.main()
