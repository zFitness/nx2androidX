"""How a game is started: the script, and the executable it runs."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import launch, library   # noqa: E402


def make_game(root, with_exe=True, exe_name='Mario'):
    """A data pack with (or without) its own executable."""
    pack = Path(root) / '0100000000010000'
    pack.mkdir(parents=True, exist_ok=True)
    (pack / 'nx2a-data.json').write_text(
        '{"title_id": "0100000000010000", "name": "Mario", "version": "1.0"}', encoding='utf-8')
    if with_exe:
        exe = pack / exe_name
        exe.write_text('#!/bin/sh\n', encoding='utf-8')
        exe.chmod(0o755)
    return library.game_of(pack)


class Script(unittest.TestCase):
    def test_the_script_runs_the_game_with_its_data_root(self):
        with tempfile.TemporaryDirectory() as root:
            game = make_game(root)
            script = launch.write_script(game)
            text = script.read_text(encoding='utf-8')
            self.assertIn('Mario', text)
            self.assertIn('DM_ROOT="$dir"', text)
            self.assertIn('cd "$dir"', text)
            self.assertTrue(os.access(script, os.X_OK))

    def test_a_game_without_an_executable_has_no_script(self):
        with tempfile.TemporaryDirectory() as root:
            game = make_game(root, with_exe=False)
            with self.assertRaises(launch.NoExecutable):
                launch.write_script(game)

    def test_the_environment_carries_the_data_root(self):
        with tempfile.TemporaryDirectory() as root:
            game = make_game(root)
            self.assertEqual(launch.environment(game)['DM_ROOT'], str(game.path))


class TheExecutable(unittest.TestCase):
    def test_the_game_finds_its_own_executable(self):
        with tempfile.TemporaryDirectory() as root:
            game = make_game(root)
            self.assertEqual(game.exe_path, game.path / 'Mario')

    def test_the_manifest_can_name_it(self):
        with tempfile.TemporaryDirectory() as root:
            pack = Path(root) / '0100000000020000'
            pack.mkdir()
            (pack / 'nx2a-data.json').write_text(
                '{"title_id": "0100000000020000", "name": "Zelda", "exe": "Game"}', encoding='utf-8')
            exe = pack / 'Game'
            exe.write_text('#!/bin/sh\n', encoding='utf-8')
            exe.chmod(0o755)
            game = library.game_of(pack)
            self.assertEqual(game.exe_path, exe)

    def test_the_script_the_launcher_writes_is_not_the_game(self):
        with tempfile.TemporaryDirectory() as root:
            game = make_game(root, with_exe=False)
            script = game.path / library.WRAPPER
            script.write_text('#!/bin/sh\n', encoding='utf-8')
            script.chmod(0o755)
            self.assertIsNone(game.exe_path)

    def test_a_game_without_an_executable_cannot_be_started(self):
        with tempfile.TemporaryDirectory() as root:
            game = make_game(root, with_exe=False)
            with self.assertRaises(launch.NoExecutable):
                launch.start(game)


if __name__ == '__main__':
    unittest.main()
