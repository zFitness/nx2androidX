"""shader_split.py: a Monolith HCPS program whose code area has no graphics/compute magic is read as
compute when its control section's thread group (+0x748) is filled, as the shared glslc_stage rule says.
Xenoblade Chronicles 2's shd_effect.wishp has one, and its profile has no shader_loose_monolith key, so
the old stage-5-only fallback could not read it and the split stopped the port with a red line."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'nxnative/dm/gfx/tools'
sys.path.insert(0, str(TOOLS))


def load():
    os.environ.setdefault('DM_GAME', '0100000000010000')
    spec = importlib.util.spec_from_file_location('shader_split_headerless_under_test', TOOLS / 'shader_split.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sections(code_magic=None):
    """A control section and code area a headerless compute stage can pass check() with"""
    code = bytearray(0x100)
    if code_magic:
        code[:4] = code_magic
    control = bytearray(0x880)
    control[:4] = bytes.fromhex('34127698')   # CTL_MAGIC
    struct.pack_into('<I', control, 0x20, len(control))
    struct.pack_into('<I', control, 0x704, len(code))
    struct.pack_into('<3I', control, 0x748, 32, 32, 1)   # a filled thread group: headerless compute
    return control, code


class HeaderlessCompute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.S = load()

    def make_slct(self, control, code, stage=5):
        """A minimal SLCT: one program, one NVSD stage, the code/control areas at +0 of their sections"""
        nvsd = bytearray(0x40)
        struct.pack_into('<II', nvsd, 0x18, 0x20, 1)       # stage list at NVSD+0x20, one entry
        struct.pack_into('<5I', nvsd, 0x20, stage, 0, len(code), 0, len(control))
        slct = bytearray(0x100)
        slct[:4] = b'SLCT'
        struct.pack_into('<5I', slct, 4, 0, 0, 0, 1, 0x40)  # one program; its (offset, length) at +0x40
        struct.pack_into('<4I', slct, 0x28, 0, 0, 0, 0)     # control / code offsets 0
        struct.pack_into('<II', slct, 0x40, 0x80, len(nvsd))
        slct[0x80:0x80 + len(nvsd)] = nvsd
        return bytes(slct)

    def test_headerless_compute_is_read_without_a_loose_monolith_profile(self):
        self.assertEqual(self.S.LOOSE_MONO, (), 'this profile has no shader_loose_monolith key')
        control, code = sections()
        s = self.make_slct(control, code)
        out = self.S.slct_programs(s, bytes(code), 0, bytes(control), 0, 'x', strict=True)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], 'cs')

    def test_headerless_compute_of_another_stage_index_is_read(self):
        control, code = sections()
        s = self.make_slct(control, code, stage=3)   # not the old stage-5 special case
        out = self.S.slct_programs(s, bytes(code), 0, bytes(control), 0, 'x', strict=True)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][1], 'cs')

    def test_a_stage_with_no_magic_and_no_thread_group_is_still_refused(self):
        control, code = sections()
        struct.pack_into('<3I', control, 0x748, 0, 0, 0)   # no thread group: not compute
        s = self.make_slct(control, code)
        with self.assertRaises(SystemExit) as e:
            self.S.slct_programs(s, bytes(code), 0, bytes(control), 0, 'x', strict=True)
        self.assertIn('no code area header', str(e.exception))

    def test_a_graphics_code_area_still_gets_its_stage(self):
        control, code = sections(code_magic=self.S.GFX_MAGIC)
        struct.pack_into('<I', code, 0x30, 1 << 10)        # SPH stage 1 = vertex
        s = self.make_slct(control, code, stage=0)
        out = self.S.slct_programs(s, bytes(code), 0, bytes(control), 0, 'x', strict=True)
        self.assertEqual(out[0][1], 'vs')


if __name__ == '__main__':
    unittest.main()
