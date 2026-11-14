"""Conservative SPIR-V bounds: accept constant reads, reject unproven pointer uses."""
import ctypes
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ins(op, *args):
    return [(len(args) + 1) << 16 | op, *args]


def module(index=33, dynamic=False, offset=0, stride=16, escape=False, component=None):
    w = [0x07230203, 0x10000, 0, 100, 0]
    w += ins(71, 10, 33, 3) + ins(71, 10, 34, 0)
    w += ins(71, 6, 2) + ins(71, 5, 6, stride) + ins(72, 6, 0, 35, offset)
    w += ins(21, 1, 32, 0) + ins(22, 2, 32) + ins(23, 3, 2, 4)
    w += ins(43, 1, 4, 4096) + ins(28, 5, 3, 4) + ins(30, 6, 5)
    w += ins(32, 7, 2, 6) + ins(32, 8, 2, 3) + ins(32, 9, 2, 2)
    w += ins(59, 7, 10, 2) + ins(43, 1, 11, 0)
    w += ins(50 if dynamic else 43, 1, 12, index)
    w += ins(43, 1, 13, component or 0)
    w += ins(54, 20, 21, 0, 22)
    w += ins(65, 8 if component is None else 9, 30, 10, 11, 12, *([] if component is None else [13]))
    w += ins(61, 3 if component is None else 2, 31, 30)
    if escape:
        w += ins(57, 20, 32, 40, 30)
    w += ins(56)
    return w


def dynamic_module(mode='clamp', bad=False):
    w = module(); end = next(i for i in range(5,len(w)) if w[i] == (5<<16|54))
    w = w[:end]; w[3]=300
    # Extra scalar and local types; all synthetic, no game shader data.
    w += ins(21,40,32,1)+ins(32,41,7,40)+ins(20,42)
    w += ins(43,40,43,2)+ins(43,40,44,1)+ins(43,40,45,0xffffffff)
    w += ins(43,40,46,0)+ins(43,40,47,7)+ins(43,40,48,4)
    if mode=='clamp':
        import struct
        word=lambda v:struct.unpack('<I',struct.pack('<f',v))[0]
        w += ins(11,60,*struct.unpack('<4I',b'GLSL.std.450\0\0\0\0'))
        w += ins(43,2,61,word(0))+ins(43,2,62,word(1))+ins(43,2,63,word(7))
        w += ins(54,20,21,0,22)+ins(248,100)
        w += ins(12,2,70,60,43,99,61,62)+ins(133,2,71,70,63)
        w += ins(12,2,72,60,8,71)+ins(110,40,73,72)
        w += ins(196,40,74,73,48)+ins(128,40,75,74,43)
        idx=75
        if bad: w += ins(196,40,76,75,75); idx=76
    elif mode=='loop':
        w += ins(54,20,21,0,22)+ins(248,100)
        w += ins(59,41,50,7)+ins(59,41,51,7)
        w += ins(62,50,43)+ins(249,101)
        w += ins(248,101)+ins(246,106,105,0)+ins(249,102)
        w += ins(248,102)+ins(61,40,70,50)+ins(62,51,70)
        w += ins(250,99,103,104)
        w += ins(248,103)+ins(249,106)
        w += ins(248,104)+ins(61,40,71,51)+ins(128,40,72,71,44 if bad else 45)
        w += ins(62,50,72)+ins(249,105)
        w += ins(248,105)+ins(61,40,73,51)+ins(179,42,74,73,44)
        w += ins(168,42,75,74)+ins(250,75,101,106)
        w += ins(248,106)+ins(61,40,76,51)
        idx=76
    elif mode=='mask':
        w += ins(54,20,21,0,22)+ins(248,100)
        w += ins(199,40,70,99,47)+ins(128,40,71,70,43)
        idx=71
    w += ins(65,8,80,10,11,idx)+ins(61,3,81,80)+ins(253)+ins(56)
    return w


@unittest.skipUnless(shutil.which('cc'), 'a host C compiler is required')
class CbufExtent(unittest.TestCase):
    def test_bounds_and_conservative_fallback(self):
        with tempfile.TemporaryDirectory(prefix='vk-extent-test-') as tmp:
            c = Path(tmp) / 'test.c'; so = Path(tmp) / 'test.so'
            c.write_text('#include "vk_cbuf_extent.h"\nuint32_t run(const uint32_t*w,uint32_t n,uint32_t b){return spv_cbuf_extent(w,n,b);}\n')
            subprocess.run(['cc', '-O2', '-shared', '-fPIC', '-I'+str(ROOT/'nxnative/dm/android'), str(c), '-o', str(so)], check=True)
            lib = ctypes.CDLL(str(so)); lib.run.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, ctypes.c_uint32]
            lib.run.restype = ctypes.c_uint32
            def extent(w, binding=3):
                return lib.run((ctypes.c_uint32*len(w))(*w), len(w), binding)
            self.assertEqual(extent(dynamic_module('clamp')), 115*16)
            self.assertEqual(extent(dynamic_module('clamp', True)), 0)
            self.assertEqual(extent(dynamic_module('mask')), 10*16)
            self.assertEqual(extent(dynamic_module('loop')), 3*16)
            self.assertEqual(extent(dynamic_module('loop', True)), 0)
            # Reject loops with an extra entry, unsafe threshold or escaped alias.
            def replace_instruction(words, old, new):
                for pos in range(5, len(words)):
                    if words[pos:pos+len(old)] == old:
                        return words[:pos] + new + words[pos+len(old):]
                raise AssertionError('instruction missing')
            base = dynamic_module('loop')
            for old, new in [
                (ins(249,106), ins(249,101)),
                (ins(179,42,74,73,44), ins(179,42,74,73,46)),
                (ins(62,50,43), ins(62,50,46)),
                (ins(250,75,101,106), ins(250,75,104,106)),
                (ins(61,40,76,51), ins(57,40,76,90,51)),
            ]:
                with self.subTest(rejected_loop=old):
                    self.assertEqual(extent(replace_instruction(base,old,new)), 0)

            self.assertEqual(extent(module()), 544)
            self.assertEqual(extent(module(index=0)), 16)
            self.assertEqual(extent(module(index=4095)), 65536)
            self.assertEqual(extent(module(component=3)), 544)
            for args in [dict(dynamic=True), dict(offset=16), dict(stride=32), dict(escape=True), dict(index=4096), dict(component=4)]:
                with self.subTest(args=args): self.assertEqual(extent(module(**args)), 0)
            self.assertEqual(extent(module(), 9), 0)
            for n in [0, 4, 5, 20, len(module())-1]:
                self.assertEqual(extent(module()[:n]), 0)


if __name__ == '__main__':
    unittest.main()
