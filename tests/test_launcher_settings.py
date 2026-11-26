"""The settings: what they are, and that a broken file does not stop the launcher."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import settings   # noqa: E402


class Settings(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.original = settings.SETTINGS_FILE
        settings.SETTINGS_FILE = Path(self.folder.name) / 'launcher.json'
        self.addCleanup(lambda: setattr(settings, 'SETTINGS_FILE', self.original))

    def test_without_a_file_the_defaults_are_used(self):
        current = settings.load()
        self.assertEqual(current['library'], str(settings.DEFAULT_LIBRARY))
        self.assertEqual(current['language'], 'zh')
        self.assertEqual(current['ui_scale'], 1.0)

    def test_what_was_saved_is_read_back(self):
        settings.save({'library': '/tmp/games', 'language': 'en', 'ui_scale': 1.25})
        current = settings.load()
        self.assertEqual(current['library'], '/tmp/games')
        self.assertEqual(current['language'], 'en')
        self.assertEqual(current['ui_scale'], 1.25)

    def test_a_broken_file_does_not_stop_the_launcher(self):
        settings.SETTINGS_FILE.write_text('{not json', encoding='utf-8')
        self.assertEqual(settings.load()['language'], 'zh')

    def test_a_key_that_is_not_ours_is_ignored(self):
        settings.SETTINGS_FILE.write_text(json.dumps({'language': 'en', 'nonsense': 1}), encoding='utf-8')
        current = settings.load()
        self.assertEqual(current['language'], 'en')
        self.assertNotIn('nonsense', current)

    def test_a_language_that_does_not_exist_falls_back(self):
        settings.SETTINGS_FILE.write_text(json.dumps({'language': 'kl'}), encoding='utf-8')
        self.assertEqual(settings.load()['language'], 'zh')

    def test_a_broken_scale_falls_back(self):
        settings.SETTINGS_FILE.write_text(json.dumps({'ui_scale': 'big'}), encoding='utf-8')
        self.assertEqual(settings.load()['ui_scale'], 1.0)

    def test_an_empty_library_path_is_the_default_one(self):
        self.assertEqual(settings.library_dir({'library': ''}), settings.DEFAULT_LIBRARY)

    def test_the_data_directory_is_only_set_when_the_player_named_it(self):
        self.assertFalse(settings.library_set({'library': ''}))
        self.assertTrue(settings.library_set({'library': '/tmp/games'}))


if __name__ == '__main__':
    unittest.main()
