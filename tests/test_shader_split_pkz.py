"""A synthetic PlatinumGames PKZ archive: the split's reader, and what it does with the Oodle entries when nothing decodes them."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'nxnative/dm/gfx/tools'
sys.path.insert(0, str(TOOLS))


class PkzShaders(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('DM_GAME', '0100000000010000')
        spec = importlib.util.spec_from_file_location('split_pkz_under_test', TOOLS / 'shader_split.py')
        cls.split = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.split)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nx2a-pkz-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.host = os.environ.pop('DM_OODLE_HOST', None)
        self.addCleanup(self._restore_host)
        os.environ.pop('DM_OODLE_HOST', None)

    def _restore_host(self):
        if self.host is None: os.environ.pop('DM_OODLE_HOST', None)
        else: os.environ['DM_OODLE_HOST'] = self.host

    def archive(self, name, entries):
        """entries: [(name, compression, bytes)] → a PKZ file the split's reader takes ('pkzl', u32 version, u64 length, u32 count, u32 entry table, u32 name table, u32 alignment)"""
        names, offs = b'', []
        for entry, comp, _ in entries:
            offs.append((len(names), len(names) + len(entry) + 1))
            names += entry.encode() + b'\0' + comp.encode() + b'\0'
        data_at = 0x20 + 0x20 * len(entries) + len(names)
        table, body = b'', b''
        for (entry, comp, data), (no, co) in zip(entries, offs):
            table += struct.pack('<IIQQQ', no, co, len(data), data_at + len(body), len(data))
            body += data
        head = struct.pack('<4sIQIIII', b'pkzl', 0x20000, data_at + len(body), len(entries), 0x20, len(names), 0x1000)
        path = self.root / name
        path.write_bytes(head + table + names + body)
        return path

    def test_the_reader_names_the_entries_and_their_compression(self):
        path = self.archive('root_000.pkz', [('shader.dat', 'None', b'DAT\0'), ('movie.dat', 'OodleKraken', b'\x01\x02')])
        ents = self.split.pkz_entries(path)
        self.assertEqual([(n, c) for n, c, _, _, _ in ents], [('shader.dat', 'None'), ('movie.dat', 'OodleKraken')])

    def test_without_a_decoder_the_oodle_entries_are_counted_and_left_out(self):
        path = self.archive('root_000.pkz', [('shader.dat', 'None', b'DAT\0'), ('movie.dat', 'OodleKraken', b'\x01\x02')])
        ents = self.split.pkz_entries(path)
        out, said = [], io.StringIO()
        with contextlib.redirect_stdout(said):
            self.split.pkz_shaders(path, '/root_000.pkz', ents, out)   # no DM_OODLE_HOST: it must not stop the split
        self.assertIn('1 of 2 entries are Oodle Kraken', said.getvalue())
        self.assertIn('[RED]', said.getvalue())

    def test_with_a_decoder_the_oodle_entry_is_decoded(self):
        path = self.archive('root_000.pkz', [('movie.dat', 'OodleKraken', b'\x01\x02')])
        ents = self.split.pkz_entries(path)
        os.environ['DM_OODLE_HOST'] = '/nonexistent/dmhost'
        seen = []
        self.split.oodle = lambda comp, n: (seen.append((comp, n)) or comp)
        out = []
        with contextlib.redirect_stdout(io.StringIO()):
            self.split.pkz_shaders(path, '/root_000.pkz', ents, out)
        self.assertEqual(seen, [(b'\x01\x02', 2)])


if __name__ == '__main__':
    unittest.main()
