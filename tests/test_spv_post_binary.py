"""The SPIR-V patch framework of a profile's patches.py: the binary path (dm/android/tools/spv_post.py).

A profile's patch works on the SPIR-V words, so it runs where the shader stage runs (the phone) and needs no spirv-dis / spirv-as / spirv-val. A patch that is written for another
module raises ValueError, and the shader then stays as it was translated (shader_vk.py prints the [RED] line).
"""
import importlib.util
import struct
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / 'nxnative' / 'dm' / 'android' / 'tools'
GAMES = REPO / 'nxnative' / 'dm' / 'games'
sys.path.insert(0, str(TOOLS))

import spv_post  # noqa: E402
from spv_builder import instruction  # noqa: E402


def minimal_module():
    """A small SPIR-V module: the header, a capability, a memory model, an int type and a variable"""
    words = [0x07230203, 0x00010000, 0, 8, 0]
    for ins in (instruction(17, 1),          # OpCapability Shader
                instruction(14, 0, 1),       # OpMemoryModel Logical GLSL450
                instruction(19, 1, 32, 0),   # OpTypeInt %1 32 0
                instruction(59, 2, 1, 7)):   # OpVariable %2 %1 Function
        words.extend(ins)
    return struct.pack('<%dI' % len(words), *words)


def load_profile_patches(title_id):
    """The profile's patches.py, as the shader stage loads it (dm/android/tools on the path)"""
    path = GAMES / title_id / 'patches.py'
    spec = importlib.util.spec_from_file_location(f'profile_patches_{title_id}', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class BinaryPatchPath(unittest.TestCase):
    def test_a_module_survives_the_reader_and_the_writer(self):
        data = minimal_module()
        m = spv_post.Module(data)
        self.assertEqual(len(m.code), 4)
        self.assertEqual(m.op(0), 17)                       # OpCapability
        out = m.bytes()
        self.assertEqual(len(out), len(data))
        header, code = spv_post.spv_decode(out)
        self.assertEqual(header[:2], (0x07230203, 0x00010000))
        self.assertEqual([spv_post.spv_opcode(i) for i in code], [17, 14, 19, 59])

    def test_a_fresh_id_grows_the_bound(self):
        m = spv_post.Module(minimal_module())
        before = m.header[3]
        self.assertEqual(m.ident(), before)
        self.assertEqual(m.header[3], before + 1)

    def test_the_binary_path_needs_no_external_tool(self):
        @spv_post.binary
        def patch(m):
            m.replace(0, [instruction(17, 1)])
            return m
        out = spv_post.text_patch(minimal_module(), patch, None, '/tmp', 'test')
        self.assertEqual(out, minimal_module())              # the same module, no spirv-dis and no spirv-as

    def test_a_patch_that_is_written_for_another_module_raises(self):
        @spv_post.binary
        def patch(m):
            raise ValueError('not the module this patch was written for')
        with self.assertRaises(ValueError):
            spv_post.binary_patch(minimal_module(), patch)


class ProfileSpirvPatch(unittest.TestCase):
    """The 2nd Chapter's profile: the patch of the instance culling compute shader"""

    def setUp(self):
        self.patches = load_profile_patches('0100E8B028B54000')

    def test_the_profile_names_the_culling_shader(self):
        self.assertIn('37727c65c9440244', self.patches.SPIRV)
        self.assertTrue(getattr(self.patches.SPIRV['37727c65c9440244'], 'spv_binary', False))

    def test_the_patch_refuses_another_module(self):
        with self.assertRaises(ValueError):
            self.patches.SPIRV['37727c65c9440244'](spv_post.Module(minimal_module()))


if __name__ == '__main__':
    unittest.main()
