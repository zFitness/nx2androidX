"""The runner: the porter's stream of events, where the porter is, and how it is asked."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import runner   # noqa: E402


class TheChildren(unittest.TestCase):
    """Every porter child runs as the launcher's line: a Linux host, the machine its own device."""

    def test_the_environment_names_the_linux_line(self):
        env = runner.porter_env()
        self.assertEqual(env['NX2A_HOST_OS'], 'linux')
        self.assertEqual(env['NX2A_ON_DEVICE'], '1')   # the game's own decoder and compiler run here
        self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')


class TheLibrary(unittest.TestCase):
    """The pack goes straight into the library: the porter is told where that is
    (NX2A_PACK_DIR) and writes there itself — the launcher moves nothing."""

    def test_the_library_is_named_in_the_environment(self):
        env = runner.porter_env('/data/library')
        self.assertEqual(env['NX2A_PACK_DIR'], '/data/library')

    def test_the_library_can_come_as_a_path(self):
        env = runner.porter_env(Path('/data/library'))
        self.assertEqual(env['NX2A_PACK_DIR'], '/data/library')

    def test_without_a_library_the_porter_keeps_its_own_default(self):
        self.assertNotIn('NX2A_PACK_DIR', runner.porter_env())

    def test_the_porter_child_is_told_where_the_pack_goes(self):
        porter = runner.Porter(Path('/nowhere'), '/data/library')
        with mock.patch.object(runner.subprocess, 'Popen', side_effect=OSError('not started')) as popen:
            with self.assertRaises(OSError):
                porter.start([])
        self.assertEqual(popen.call_args.kwargs['env']['NX2A_PACK_DIR'], '/data/library')


class Events(unittest.TestCase):
    def test_a_json_line_is_an_event(self):
        event = runner._event('{"ev": "say", "msg": "hello"}')
        self.assertEqual(event, {'ev': 'say', 'msg': 'hello'})

    def test_a_line_that_is_not_json_is_a_message(self):
        event = runner._event('something went wrong')
        self.assertEqual(event, {'ev': 'say', 'msg': 'something went wrong'})

    def test_an_empty_line_is_nothing(self):
        self.assertEqual(runner._event('   '), {})

    def test_a_json_value_that_is_not_an_object_is_a_message(self):
        event = runner._event('[1, 2, 3]')
        self.assertEqual(event['ev'], 'say')


class Porter(unittest.TestCase):
    def test_the_checkout_next_to_the_launcher_is_found(self):
        found = runner.porter_root()
        self.assertIsNotNone(found)
        self.assertTrue((found / 'porter' / 'phone_cli.py').is_file())

    def test_a_folder_with_a_porter_is_found(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'porter').mkdir()
            (Path(root) / 'porter' / 'phone_cli.py').write_text('', encoding='utf-8')
            self.assertEqual(runner.porter_root(root), Path(root))

    def test_a_folder_without_a_porter_falls_back_to_the_checkout(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(runner.porter_root(root), REPO)


class OneDocument(unittest.TestCase):
    def test_a_command_that_answers_nothing_is_a_message(self):
        document, code, error = runner.run_json(REPO, ['nosuchcommand'])
        self.assertIsNone(document)
        self.assertNotEqual(code, 0)
        self.assertTrue(error)

    def test_a_command_that_answers_something_that_is_not_json_is_a_message(self):
        document, code, error = runner.run_json(REPO, ['--help'])
        self.assertIsNone(document)
        self.assertTrue(error)


class OffTheInterface(unittest.TestCase):
    """The interface's commands run on a thread of their own; the answer arrives on the
    idle loop, the only place the interface may be touched.  The idle hop is faked out:
    what the tests watch is that the work happens away from the caller and is delivered
    whole."""

    def delivery(self):
        seen = []
        original = runner._idle
        runner._idle = lambda callback, *args: seen.append(args)
        self.addCleanup(setattr, runner, '_idle', original)
        return seen

    def wait(self, seen):
        deadline = time.monotonic() + 30
        while not seen and time.monotonic() < deadline:
            time.sleep(0.05)
        return seen

    def test_a_json_answer_is_delivered_whole(self):
        seen = self.delivery()
        runner.run_json_async(REPO, ['nosuchcommand'], lambda *args: None)
        self.wait(seen)
        self.assertEqual(len(seen), 1)
        document, code, error = seen[0]
        self.assertIsNone(document)
        self.assertNotEqual(code, 0)
        self.assertTrue(error)

    def test_a_text_answer_is_delivered_whole(self):
        seen = self.delivery()
        runner.run_text_async(REPO, ['nosuchcommand'], lambda *args: None)
        self.wait(seen)
        self.assertEqual(len(seen), 1)
        code, out, err = seen[0]
        self.assertNotEqual(code, 0)
        self.assertFalse(out)
        self.assertTrue(err)


class Cancel(unittest.TestCase):
    """A port runs the rewriter and a compiler as children of its own, so a cancel has
    to reach the whole group."""

    def test_a_cancel_stops_the_process_and_its_children(self):
        with tempfile.TemporaryDirectory() as root:
            package = Path(root) / 'porter'
            package.mkdir()
            (package / '__init__.py').write_text('', encoding='utf-8')
            (package / 'phone_cli.py').write_text(
                'import sys, time\n'
                'print(\'{"ev": "say", "msg": "working"}\', flush=True)\n'
                'time.sleep(120)\n', encoding='utf-8')
            porter = runner.Porter(Path(root))
            porter.start([])
            for _ in range(50):
                if not porter.events.empty():
                    break
                time.sleep(0.05)
            self.assertTrue(porter.running)
            porter.cancel()
            for _ in range(100):
                if not porter.running:
                    break
                time.sleep(0.05)
            self.assertFalse(porter.running, 'the cancel did not stop the process')


class TheHome(unittest.TestCase):
    """One porter config for the launcher itself and its children: the package names
    NX2A_HOME before anything asks the porter for its settings (prod.keys among them)."""

    def test_the_package_names_the_porters_home(self):
        from launcher import settings as launcher_settings
        original = os.environ.get('NX2A_HOME')
        os.environ.pop('NX2A_HOME', None)
        try:
            import importlib
            import launcher
            importlib.reload(launcher)   # a fresh import, as a process that just started
            self.assertEqual(os.environ.get('NX2A_HOME'),
                             str(launcher_settings.CONFIG_DIR / 'porter'))
        finally:
            if original is None:
                os.environ.pop('NX2A_HOME', None)
            else:
                os.environ['NX2A_HOME'] = original

    def test_an_named_home_is_kept(self):
        original = os.environ.get('NX2A_HOME')
        os.environ['NX2A_HOME'] = '/somewhere/else'
        try:
            import importlib
            import launcher
            importlib.reload(launcher)
            self.assertEqual(os.environ['NX2A_HOME'], '/somewhere/else')   # the player's own home wins
        finally:
            if original is None:
                os.environ.pop('NX2A_HOME', None)
            else:
                os.environ['NX2A_HOME'] = original


class TheGameEnvironment(unittest.TestCase):
    """The game runs on the machine's own loader and libraries: the launcher's payload
    path (its Qt, its ABI modules) never reaches the game's process."""

    def test_the_payloads_library_path_does_not_reach_the_game(self):
        from launcher import launch, library
        game = library.Game(title_id='0100000000010000', name='game', version='v0',
                            path=Path('/games/game-data'))
        original = dict(os.environ)
        os.environ.update(LD_LIBRARY_PATH='/opt/nx2a/pylibs', LD_PRELOAD='/hook.so',
                          PYTHONPATH='/opt/nx2a', WAYLAND_DISPLAY='wayland-0',
                          XDG_RUNTIME_DIR='/run/user/1000')
        try:
            env = launch.environment(game)
        finally:
            os.environ.clear()
            os.environ.update(original)
        self.assertNotIn('LD_LIBRARY_PATH', env)
        self.assertNotIn('LD_PRELOAD', env)
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['DM_ROOT'], '/games/game-data')
        self.assertEqual(env['WAYLAND_DISPLAY'], 'wayland-0')   # the game window comes up on the same screen
        self.assertEqual(env['XDG_RUNTIME_DIR'], '/run/user/1000')


if __name__ == '__main__':
    unittest.main()
