"""The Steam library: the file's format, and what a player adds to it."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import steam   # noqa: E402


class Format(unittest.TestCase):
    def test_a_map_survives_the_round_trip(self):
        data = {'shortcuts': {'0': {'appid': 42, 'AppName': 'Mario', 'icon': ''}}}
        self.assertEqual(steam.decode(steam.encode(data)), data)

    def test_the_kinds_of_value_steam_uses(self):
        data = {
            'shortcuts': {'0': {
                'appid': 1234, 'AppName': 'Mario', 'Exe': '/tmp/run.sh', 'StartDir': '/tmp',
                'IsHidden': 0, 'LastPlayTime': steam.Uint64(0),
                'tags': {'0': 'Switch'},
            }},
        }
        back = steam.decode(steam.encode(data))
        self.assertEqual(back['shortcuts']['0']['appid'], 1234)
        self.assertEqual(back['shortcuts']['0']['AppName'], 'Mario')
        self.assertEqual(int(back['shortcuts']['0']['LastPlayTime']), 0)
        self.assertEqual(back['shortcuts']['0']['tags'], {'0': 'Switch'})

    def test_an_empty_file_is_an_empty_map(self):
        self.assertEqual(steam.decode(b''), {})

    def test_a_file_that_is_cut_in_the_middle_raises(self):
        with self.assertRaises(ValueError):
            steam.decode(steam.encode({'shortcuts': {'0': {'AppName': 'Mario'}}})[:-3])

    def test_a_file_with_an_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            steam.decode(bytes([0x42]) + b'key\x00')

    def test_the_app_id_is_the_same_for_the_same_game(self):
        first = steam.app_id_for('Mario', '/tmp/run.sh')
        self.assertEqual(first, steam.app_id_for('Mario', '/tmp/run.sh'))
        self.assertNotEqual(first, steam.app_id_for('Zelda', '/tmp/run.sh'))
        self.assertNotEqual(0, first)


class Library(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'shortcuts.vdf'
        self.addCleanup(self.folder.cleanup)

    def entry(self, name='Mario', exe='/tmp/run.sh'):
        return steam.shortcut_entry(name, exe, '/tmp', icon='/tmp/icon.png')

    def test_an_added_game_is_in_the_library(self):
        steam.add_shortcut(self.entry(), self.path)
        self.assertTrue(self.path.is_file())
        found = steam.list_shortcuts(self.path)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['AppName'], 'Mario')
        self.assertEqual(found[0]['Exe'], '/tmp/run.sh')

    def test_the_same_game_twice_is_one_entry(self):
        steam.add_shortcut(self.entry(), self.path)
        steam.add_shortcut(self.entry(), self.path)
        self.assertEqual(len(steam.list_shortcuts(self.path)), 1)

    def test_removing_takes_out_that_game_only(self):
        steam.add_shortcut(self.entry('Mario'), self.path)
        steam.add_shortcut(self.entry('Zelda', '/tmp/zelda.sh'), self.path)
        self.assertTrue(steam.remove_shortcut('Mario', self.path))
        left = steam.list_shortcuts(self.path)
        self.assertEqual([e['AppName'] for e in left], ['Zelda'])

    def test_removing_a_game_that_is_not_there_does_nothing(self):
        steam.add_shortcut(self.entry(), self.path)
        self.assertFalse(steam.remove_shortcut('Zelda', self.path))
        self.assertEqual(len(steam.list_shortcuts(self.path)), 1)

    def test_a_file_that_cannot_be_read_is_not_written_over(self):
        self.path.write_bytes(bytes([0x42]) + b'key\x00')
        with self.assertRaises(ValueError):
            steam.add_shortcut(self.entry(), self.path)
        self.assertEqual(self.path.read_bytes(), bytes([0x42]) + b'key\x00')


class DesktopEntry(unittest.TestCase):
    def test_the_entry_names_the_game_and_its_script(self):
        with tempfile.TemporaryDirectory() as root:
            script = Path(root) / 'run.sh'
            script.write_text('#!/bin/sh\n', encoding='utf-8')
            original = steam.APPLICATIONS_DIR
            steam.APPLICATIONS_DIR = Path(root) / 'applications'
            try:
                path = steam.write_desktop_entry('0100000000010000', 'Mario', script)
                text = path.read_text(encoding='utf-8')
                self.assertIn('Name=Mario', text)
                self.assertIn(f'Exec={script}', text)
                self.assertIn('Type=Application', text)
            finally:
                steam.APPLICATIONS_DIR = original

    def test_the_entry_can_be_taken_away(self):
        with tempfile.TemporaryDirectory() as root:
            script = Path(root) / 'run.sh'
            script.write_text('#!/bin/sh\n', encoding='utf-8')
            original = steam.APPLICATIONS_DIR
            steam.APPLICATIONS_DIR = Path(root) / 'applications'
            try:
                steam.write_desktop_entry('0100000000010000', 'Mario', script)
                self.assertTrue(steam.remove_desktop_entry('0100000000010000'))
                self.assertFalse(steam.desktop_entry_path('0100000000010000').exists())
            finally:
                steam.APPLICATIONS_DIR = original


if __name__ == '__main__':
    unittest.main()
