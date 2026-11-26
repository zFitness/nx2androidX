# The engine's sub-agent extension: get_subagent_result must not hold a session. The build patches the
# engine's own file when it stages it (packaging/android-apk/build_assets.py).
import importlib.util, shutil, subprocess, tempfile, unittest, zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / 'packaging' / 'android-apk' / 'build_assets.py'
spec = importlib.util.spec_from_file_location('build_assets', SCRIPT)
build_assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_assets)

# The three places the patch touches, as they are in the engine's own file. They are read from the patch
# itself, so a patch that changes is a patch that is tested.
WAIT_OPTION, WAIT_BLOCK, RUNNING_TEXT = (old for old, _ in build_assets.SUBAGENT_PATCHES)

# The engine package the build takes, in the build's cache. The file inside it is the original one: the
# staged tree holds the patched copy, and patching that again is what the build refuses to do.
CACHE = Path(__file__).resolve().parent.parent / 'packaging' / 'android-apk' / '.cache' / 'pi-respack'
ENGINE_FILE = 'extensions/pi-subagents/dist/index.js'


def engine_package() -> Path | None:
    """The newest engine package in the cache, if there is one."""
    packages = sorted(CACHE.glob('pi-agent-r*.zip'))
    return packages[-1] if packages else None


class EngineSubagentPatch(unittest.TestCase):
    def setUp(self):
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.file = self.dir / 'extensions' / 'pi-subagents' / 'dist' / 'index.js'
        self.file.parent.mkdir(parents=True)
        self.file.write_text('\n'.join([
            'function defineTool(o) { return o; }',
            'const agent_id = Type.String();',
            WAIT_OPTION,
            WAIT_BLOCK,
            RUNNING_TEXT,
        ]), encoding='utf-8')

    def patch(self):
        build_assets.patch_engine_subagents(self.dir)
        return self.file.read_text(encoding='utf-8')

    def test_the_wait_is_gone(self):
        got = self.patch()
        self.assertNotIn('params.wait', got)
        self.assertNotIn('wait: Type.Optional', got)
        self.assertNotIn('await abortable(record.promise', got)

    def test_the_running_answer_does_not_teach_the_wait_anymore(self):
        got = self.patch()
        self.assertIn('Do not wait for it', got)
        self.assertNotIn('Use wait: true or check back later', got)

    def test_a_file_that_moved_stops_the_build(self):
        self.file.write_text('something else entirely\n', encoding='utf-8')
        with self.assertRaises(SystemExit) as e:
            build_assets.patch_engine_subagents(self.dir)
        self.assertIn('does not look the way the patch expects', str(e.exception))

    def test_an_engine_without_the_extension_stops_the_build(self):
        shutil.rmtree(self.file.parent.parent)
        with self.assertRaises(SystemExit) as e:
            build_assets.patch_engine_subagents(self.dir)
        self.assertIn('carries no sub-agent extension', str(e.exception))

    @unittest.skipUnless(engine_package() is not None, 'the engine package is not in the cache')
    def test_the_real_engine_file(self):
        """The engine's own file, out of the package: every patch matches once, and it is still a program."""
        work = self.dir / 'real'
        (work / 'extensions' / 'pi-subagents' / 'dist').mkdir(parents=True)
        with zipfile.ZipFile(engine_package()) as z:
            with z.open(ENGINE_FILE) as src, (work / ENGINE_FILE).open('wb') as dst:
                shutil.copyfileobj(src, dst)
        build_assets.patch_engine_subagents(work)
        got = (work / ENGINE_FILE).read_text(encoding='utf-8')
        self.assertNotIn('params.wait', got)
        self.assertIn('Do not wait for it', got)

    @unittest.skipUnless(engine_package() is not None and shutil.which('node'),
                         'the engine package is not in the cache (or node is missing)')
    def test_the_patched_file_is_still_a_program(self):
        """The patched file has to parse: a patch that breaks the extension breaks the assistant."""
        work = self.dir / 'real'
        (work / 'extensions' / 'pi-subagents' / 'dist').mkdir(parents=True)
        with zipfile.ZipFile(engine_package()) as z:
            with z.open(ENGINE_FILE) as src, (work / ENGINE_FILE).open('wb') as dst:
                shutil.copyfileobj(src, dst)
        build_assets.patch_engine_subagents(work)
        as_module = work / 'index.mjs'   # the file is a module: node checks it as one
        as_module.write_bytes((work / ENGINE_FILE).read_bytes())
        check = subprocess.run(['node', '--check', str(as_module)], capture_output=True, text=True)
        self.assertEqual(0, check.returncode, check.stderr)


if __name__ == '__main__':
    unittest.main()
