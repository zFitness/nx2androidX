"""The library: what the data directory holds, and how it is read."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import library   # noqa: E402


def make_pack(root, title_id, name, version='1.0', manifest=True, icon=False):
    """A data pack in a throwaway folder."""
    folder = Path(root) / title_id
    folder.mkdir(parents=True, exist_ok=True)
    if manifest:
        (folder / 'nx2a-data.json').write_text(json.dumps({
            'title_id': title_id, 'name': name, 'version': version,
            'package': f'org.nx2a.{title_id.lower()}',
        }), encoding='utf-8')
    if icon:
        (folder / 'icon.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    return folder


class Scan(unittest.TestCase):
    def test_finds_the_games_by_name(self):
        with tempfile.TemporaryDirectory() as root:
            make_pack(root, '0100000000010000', 'Zelda')
            make_pack(root, '0100000000020000', 'Mario')
            games = library.scan(Path(root))
            self.assertEqual([g.name for g in games], ['Mario', 'Zelda'])

    def test_the_version_sorts_after_the_name(self):
        with tempfile.TemporaryDirectory() as root:
            make_pack(root, '0100000000010000', 'Mario', version='2.0')
            make_pack(root, '0100000000020000', 'Mario', version='1.0')
            games = library.scan(Path(root))
            self.assertEqual([g.version for g in games], ['1.0', '2.0'])

    def test_a_folder_without_a_manifest_is_not_a_game(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'notes').mkdir()
            self.assertEqual(library.scan(Path(root)), [])

    def test_a_broken_manifest_is_not_a_game(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'broken'
            folder.mkdir()
            (folder / 'nx2a-data.json').write_text('{not json', encoding='utf-8')
            self.assertEqual(library.scan(Path(root)), [])

    def test_a_manifest_without_a_title_id_is_not_a_game(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'nameless'
            folder.mkdir()
            (folder / 'nx2a-data.json').write_text(json.dumps({'name': 'No ID'}), encoding='utf-8')
            self.assertEqual(library.scan(Path(root)), [])

    def test_a_library_that_is_not_there_is_empty(self):
        self.assertEqual(library.scan(Path('/nowhere/at/all')), [])

    def test_the_game_carries_its_folder_and_icon(self):
        with tempfile.TemporaryDirectory() as root:
            pack = make_pack(root, '0100000000010000', 'Mario', icon=True)
            game = library.game_of(pack)
            self.assertIsNotNone(game)
            self.assertEqual(game.title_id, '0100000000010000')
            self.assertEqual(game.path, pack)
            self.assertEqual(game.icon_path, pack / 'icon.png')
            self.assertEqual(game.label, 'Mario  1.0')

    def test_the_porters_own_leftovers_are_not_games(self):
        """A pack the porter is still writing (<name>.partial) has no manifest yet, so
        the library never shows a half-made game."""
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'Mario-data.partial').mkdir()
            (Path(root) / 'Mario-data.partial' / 'shaders.dmsv').write_bytes(b'')
            self.assertEqual(library.scan(Path(root)), [])


if __name__ == '__main__':
    unittest.main()
