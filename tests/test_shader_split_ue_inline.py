"""shader_split.py: the shader records an Unreal package keeps inline (It Takes Two's shape: no shader code archive, the records sit in the cooked packages). The split reads
them with ue_inline.py and says how many it read; the translation chain does not take this generation's records yet, so the build stops with that said."""
import importlib.util, os, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / 'nxnative' / 'dm' / 'gfx' / 'tools'
os.environ.setdefault('DM_GAME', '01005270232F2000')   # the split's tools ask for a profile when they are imported


def record(tag=b'SP', names=b'in_texcoord6\x00', code=b'xV4\x12\x00\x01\x00\x18', ctl=b'\x1b\x01\xf3\x02', source=b'!!NVfp5.0\nOPTION NV_internal;'):
    """A record as It Takes Two's packages hold them: 'LSLG', the stage tag, a 9-byte header, the parameter names (their length is a u32 in front of them), the parameters, the
    code area (it starts with the NVN program's magic), the control section (its own magic) and the source (it starts with the version line)"""
    body = b'LSLG' + tag + b'\x00\x01\x00\xfe\x07\x02\x00\x00\x00'
    if names: body += len(names).to_bytes(4, 'little') + names
    return body + code + bytes.fromhex('34127698') + ctl + source + source[-24:]


class Inline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TOOLS))
        spec = importlib.util.spec_from_file_location('shader_split_ueinline', TOOLS / 'shader_split.py')
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)

    def test_the_records_are_read(self):
        found = []
        sizes = self.m.ue_records(record(), '/ue_inline/Nuts/Content/Materials/A.uexp', found)
        self.assertEqual(len(found), 1)
        name, stage, ctl, code = found[0]
        self.assertEqual(stage, 'ps')          # the tag 'SP' is the pixel stage
        self.assertEqual(name, '/ue_inline/Nuts/Content/Materials/A.uexp#UE0')
        self.assertEqual(ctl[:4], bytes.fromhex('34127698'))
        self.assertEqual(code[:4], b'xV4\x12')
        self.assertEqual(sizes, [8])   # the control section: its magic and the bytes after it

    def test_a_record_that_does_not_read_stops_the_build(self):
        # a program but no control section: a record of a shape the reader does not know
        data = b'LSLG' + b'SP' + b'\x00\x01\x00\xfe\x07\x02\x00\x00\x00' + (13).to_bytes(4, 'little') + b'in_texcoord6\x00' + b'xV4\x12\x00\x01\x00\x18'
        with self.assertRaises(SystemExit) as e:
            self.m.ue_records(data, '/ue_inline/A.uexp', [])
        self.assertIn('[RED]', str(e.exception))
        self.assertIn('no control section', str(e.exception))


class Programs(unittest.TestCase):
    """The programs the game hands the NVN driver at run time (the host's DM_NVN_SHDUMP dump): the 0x880-byte control section the driver reads, then the code area. The engine
    expands this generation's inline records into this form, so the split takes the programs instead of the records (the records are the engine's own compact form)"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(TOOLS))
        spec = importlib.util.spec_from_file_location('shader_split_ueprogs', TOOLS / 'shader_split.py')
        cls.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.m)

    @staticmethod
    def dump(code):
        ctl = bytearray(0x880)
        ctl[0:4] = bytes.fromhex('34127698')
        ctl[0x704:0x708] = len(code).to_bytes(4, 'little')
        return bytes(ctl) + code

    def test_the_programs_are_read(self):
        import tempfile
        code = b'xV4\x12' + b'\x00' * 0x2c + b'\x62\x54\x06\x00' + b'\x00' * 0x4e + b'\xf0\x07\xc0\xe2' + b'\x00' * 0x7e
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'program_0123456789abcdef_0.bin'), 'wb') as f: f.write(self.dump(code))
            found = []
            n = self.m.ue_runtime_programs(d, found)
        self.assertEqual(n, 1)
        where, stage, ctl, area = found[0]
        self.assertEqual(stage, 'ps')
        self.assertEqual(where, '/ue_programs/program_0123456789abcdef_0.bin')
        self.assertEqual(len(ctl), 0x880)
        self.assertEqual(area, code)
        # the key the chain gives the program is the one the driver computes (sha256 of the control section and the code area)
        import hashlib
        self.assertEqual(self.m.skey(ctl, area), hashlib.sha256(ctl[:self.m.ctl_len(ctl)] + area).hexdigest()[:16])

    def test_a_dump_that_does_not_read_is_reported(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'program_0123456789abcdef_0.bin'), 'wb') as f: f.write(b'\x00' * 32)
            with self.assertRaises(SystemExit) as e:
                self.m.ue_runtime_programs(d, [])
        self.assertIn('[RED]', str(e.exception))


if __name__ == '__main__': unittest.main()
