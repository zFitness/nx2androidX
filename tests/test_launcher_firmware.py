"""The firmware import: a zip unpacked flat into the data folder, the porter's config
pointing at it, and the way back out (clear)."""
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from launcher import firmware, settings   # noqa: E402
from porter import config as porter_config   # noqa: E402


def make_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


class Firmware(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        # The launcher's settings and data folder, and the porter's own config, all
        # private to the test: the player's real ones are never read or written.
        original_file = settings.SETTINGS_FILE
        settings.SETTINGS_FILE = root / 'config' / 'launcher.json'
        self.addCleanup(lambda: setattr(settings, 'SETTINGS_FILE', original_file))
        original_config = settings.CONFIG_DIR
        settings.CONFIG_DIR = root / 'config'
        self.addCleanup(lambda: setattr(settings, 'CONFIG_DIR', original_config))
        original_data = settings.DATA_DIR
        settings.DATA_DIR = root / 'data'
        self.addCleanup(lambda: setattr(settings, 'DATA_DIR', original_data))
        original_home = os.environ.get('NX2A_HOME')
        os.environ['NX2A_HOME'] = str(root / 'nx2a')
        self.addCleanup(lambda: (os.environ.pop('NX2A_HOME', None) if original_home is None
                                 else os.environ.__setitem__('NX2A_HOME', original_home)))

    def test_an_import_unpacks_flat_and_points_the_porter_at_it(self):
        zip_path = make_zip(Path(self.folder.name) / 'fw.zip', {
            'registered/aa.nca': b'one', 'registered/sub/bb.nca': b'two',
            '../evil.nca': b'no', '/abs.nca': b'no', 'readme.txt': b'x'})
        count = firmware.import_zip(zip_path)
        self.assertEqual(count, 3)   # the two nca files and the readme; the escapes dropped
        target = firmware.folder()
        self.assertEqual(sorted(f.name for f in target.iterdir()),
                         ['aa.nca', 'bb.nca', 'readme.txt'])   # flat, one level
        self.assertEqual(firmware.imported_name(), 'fw.zip')
        self.assertEqual(firmware.nca_folder(), target)
        self.assertEqual(porter_config.load()['firmware'], str(target))

    def test_a_zip_without_nca_is_refused_and_leaves_nothing(self):
        zip_path = make_zip(Path(self.folder.name) / 'notfw.zip', {'readme.txt': b'x'})
        with self.assertRaises(ValueError):
            firmware.import_zip(zip_path)
        self.assertIsNone(firmware.nca_folder())
        self.assertEqual(firmware.imported_name(), '')
        self.assertEqual(porter_config.load().get('firmware') or '', '')

    def test_a_reimport_replaces_and_a_clear_forgets(self):
        first = make_zip(Path(self.folder.name) / 'one.zip', {'a.nca': b'1'})
        second = make_zip(Path(self.folder.name) / 'two.zip', {'b.nca': b'2', 'c.nca': b'3'})
        firmware.import_zip(first)
        firmware.import_zip(second)
        target = firmware.folder()
        self.assertEqual(sorted(f.name for f in target.iterdir()), ['b.nca', 'c.nca'])
        self.assertEqual(firmware.imported_name(), 'two.zip')
        firmware.clear()
        self.assertIsNone(firmware.nca_folder())
        self.assertEqual(firmware.imported_name(), '')
        self.assertEqual(porter_config.load().get('firmware') or '', '')


if __name__ == '__main__':
    unittest.main()
