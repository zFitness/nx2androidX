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
    """The interface is Qt (PySide6), so the package runs on the machine's own Python
    with the system's PySide6: the package carries the code, not the toolkit."""

    APPRUN = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')

    def test_apprun_runs_the_system_python(self):
        self.assertIn('PYTHON="${NX2A_PYTHON:-/usr/bin/python3}"', self.APPRUN)
        self.assertIn('exec "$PYTHON" -m launcher', self.APPRUN)

    def test_the_package_carries_no_interpreter(self):
        self.assertNotIn('usr/python', self.APPRUN)
        self.assertNotIn('PYTHONHOME=', self.APPRUN)
        self.assertIn('unset PYTHONHOME', self.APPRUN)

    def test_the_pipeline_finds_the_packages_own_code(self):
        self.assertIn('PYTHONPATH="$HERE/usr', self.APPRUN)

    def test_a_machine_without_the_bindings_is_told_what_to_install(self):
        entry = (REPO / 'launcher/__main__.py').read_text(encoding='utf-8')
        self.assertIn('python3-pyside6', entry)


class TheWindowFrame(unittest.TestCase):
    """The frame follows the machine: inside a gamescope container the container
    itself draws the only title bar, on an ordinary desktop the window keeps its
    own."""

    ENV = appimage.ENV_GAMESCOPE

    def setUp(self):
        self.had = os.environ.get(self.ENV)
        self.addCleanup(self._restore)

    def _restore(self):
        if self.had is None:
            os.environ.pop(self.ENV, None)
        else:
            os.environ[self.ENV] = self.had

    def test_inside_gamescope_the_container_frames_the_window(self):
        os.environ[self.ENV] = 'wayland-1'
        self.assertFalse(appimage.wants_frame())

    def test_on_a_desktop_the_window_frames_itself(self):
        os.environ.pop(self.ENV, None)
        self.assertTrue(appimage.wants_frame())

    def test_an_empty_variable_is_no_gamescope(self):
        os.environ[self.ENV] = ''
        self.assertTrue(appimage.wants_frame())


class ThePlainEntry(unittest.TestCase):
    """The entry script stays an entry script: the package runs where it is
    clicked, the way every other AppImage on the machine does -- no self-install,
    no menu writing, no copy to the player's home."""

    APPRUN = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')

    def test_no_install_or_menu_logic_is_in_it(self):
        self.assertNotIn('selfinstall', self.APPRUN)
        self.assertNotIn('.local/share/applications', self.APPRUN)
        self.assertNotIn('nx2a/app', self.APPRUN)

    def test_the_exports_and_the_exec_stay(self):
        self.assertIn('export NX2A_TOOLCHAIN="$HERE/usr/toolchain"', self.APPRUN)
        self.assertIn('export LD_LIBRARY_PATH="$HERE/usr/pylibs', self.APPRUN)
        self.assertIn('exec "$PYTHON" -m launcher', self.APPRUN)


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


class TheToolchainBundle(unittest.TestCase):
    """--with-toolchain: the phone payload's clang and glslc, the .NET runtime with the
    prebuilt C# tools, the porter's Python modules, and a Debian glibc prefix -- staged
    into usr/, so a machine with no compiler builds anyway."""

    ASSETS = REPO / 'packaging/android-apk/.cache/assets'
    DEBS = REPO / 'packaging/arm-linux/.cache/debs'

    def setUp(self):
        if not self.ASSETS.is_dir():
            self.skipTest('no android-apk payload cache on this machine')

    def test_staging_is_complete(self):
        with tempfile.TemporaryDirectory() as root:
            appdir = Path(root)
            debs = self.DEBS if self.DEBS.is_dir() else self.ASSETS.parent / 'debs'
            if not debs.is_dir():
                self.skipTest('no fetched glibc debs on this machine')
            build.stage_toolchain(appdir, self.ASSETS, debs)
            usr = appdir / 'usr'
            for want in (usr / 'toolchain/clang/bin/clang', usr / 'toolchain/bin/glslc',
                         usr / 'toolchain/lib/libshaderc.so.1',
                         usr / 'toolchain/glibc/usr/include/stdio.h',
                         usr / 'toolchain/glibc/usr/lib/llvm-18/lib/clang/18/include/stdarg.h',
                         usr / 'dotnet/dotnet',
                         usr / 'cs-tools/nx_extract/nx_extract',
                         usr / 'cs-tools/dmsh_xlate/dmsh_xlate.dll'):
                self.assertTrue(want.is_file(), f'{want} missing')
            self.assertFalse((usr / 'toolchain/ndk').exists(), 'the bionic NDK does not travel')

    def test_pylibs_carry_the_target_abi(self):
        """lz4 and friends must exist in the tablet's own CPython ABI (cpython-314): the
        payload's copies are cpython-313 and a python ignores those."""
        with tempfile.TemporaryDirectory() as root:
            appdir = Path(root)
            build.stage_pylibs(appdir, self.ASSETS, Path(root))
            pylibs = appdir / 'usr' / 'pylibs'
            exts = list(pylibs.rglob('*.so'))
            self.assertTrue(any('cpython-314' in f.name for f in exts),
                            'no cpython-314 extension module in the staged pylibs')
            self.assertTrue((pylibs / 'lz4').is_dir())
            self.assertTrue((pylibs / 'capstone').is_dir())
            self.assertTrue(list(pylibs.glob('libcapstone.so.*')), 'libcapstone is not staged')

    def test_staging_rejects_an_incomplete_payload(self):
        with tempfile.TemporaryDirectory() as root:
            empty = Path(root) / 'assets'
            (empty / 'toolchain').mkdir(parents=True)
            with self.assertRaises(SystemExit):
                build.stage_toolchain(appdir=Path(root), src=empty, debs=empty)

    def test_apprun_exports_the_toolchain(self):
        apprun = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')
        for line in ('NX2A_TOOLCHAIN="$HERE/usr/toolchain"', 'DOTNET_ROOT="$HERE/usr/dotnet"',
                     'NX2A_NX_EXTRACT="$HERE/usr/cs-tools/nx_extract"',
                     'NX2A_DMSH_XLATE="$HERE/usr/cs-tools/dmsh_xlate"',
                     'PYTHONPATH="$HERE/usr/pylibs:$HERE/usr'):
            self.assertIn(line, apprun)

    def test_apprun_puts_the_toolchain_on_the_path(self):
        apprun = (REPO / 'packaging/arm-linux/AppRun').read_text(encoding='utf-8')
        self.assertIn('export PATH="$HERE/usr/toolchain/clang/bin:$HERE/usr/toolchain/bin:$PATH"', apprun)
        self.assertIn('export PATH="$HERE/usr/dotnet:$PATH"', apprun)

    def test_minimal_thin_layout_passes_without_toolchain(self):
        """--with-toolchain is opt-in: a complete thin layout (no toolchain bundle)
        passes the layout check, and only the bundled-piece check refuses it."""
        with tempfile.TemporaryDirectory() as root:
            appdir = Path(root) / 'AppDir'
            for sub in ('usr/launcher', 'usr/porter', 'usr/phone_tools', 'usr/share/fonts'):
                (appdir / sub).mkdir(parents=True)
            (appdir / 'usr/launcher/__init__.py').write_text('')
            (appdir / 'usr/porter/__init__.py').write_text('')
            (appdir / 'usr/phone_tools/__init__.py').write_text('')
            (appdir / 'usr/nxnative/dm').mkdir(parents=True)
            shutil.copy2(REPO / 'packaging/arm-linux/AppRun', appdir / 'AppRun')
            (appdir / 'AppRun').chmod(0o755)
            shutil.copy2(REPO / 'packaging/arm-linux/nx2androidX.desktop',
                         appdir / 'nx2androidX.desktop')
            build.assert_package_layout(appdir, False)   # thin: no raise expected
        with tempfile.TemporaryDirectory() as root:
            appdir = Path(root) / 'AppDir'
            (appdir / 'usr').mkdir(parents=True)
            with self.assertRaises(SystemExit):           # bundled pieces are absent
                build.assert_package_layout(appdir, True)


if __name__ == '__main__':
    unittest.main()
