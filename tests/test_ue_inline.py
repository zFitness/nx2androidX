# nxnative/dm/gfx/tools/ue_inline.py: the shader records an Unreal package keeps inline (It Takes Two's shape: Unreal Engine 4.27 for the Switch, no shader code
# archive, every shader in the cooked package that needs it). The layout below is the one measured on It Takes Two's real records (010092A0172E4000): a material package
# holds 199 of them (84 vertex, 111 pixel, 4 geometry) and the global shader cache 1,488 (79 vertex, 791 pixel, 615 compute, 3 geometry). The old layout, which keeps the
# shaders in an archive, is a different format (uepak.lslg) and must keep reading as it did.
import os, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'nxnative' / 'dm' / 'gfx' / 'tools'))
import ue_inline   # noqa: E402
import uepak   # noqa: E402


def record(tag=b'SP', names=b'in_texcoord6\x00', header=b'\x00\x01\x00\xfe\x07\x02\x00\x00\x00', code=b'\x78\x56\x34\x12\x00\x01\x00\x18',
           ctl=b'\x1b\x01\xf3\x02', source=b'!!NVfp5.0\nOPTION NV_internal;', tail=b''):
    """A record as It Takes Two's packages hold them: 'LSLG', the stage tag, a 9-byte header, the parameter names (their length is a u32 in front of them), the
    parameters, the code area (it starts with the NVN program's magic), the control section (its own magic), the source (it starts with the version line) and a
    24-byte tail (the last bytes of the source, as the game's own writer leaves them)"""
    body = b'LSLG' + tag + header
    if names: body += len(names).to_bytes(4, 'little') + names
    body += code + ue_inline.MAGIC + ctl + source + (tail or source[-ue_inline.TAIL:])
    return body


class Inline(unittest.TestCase):
    def test_a_record_is_read(self):
        data = record()
        recs = ue_inline.records(data)
        self.assertEqual(len(recs), 1)
        tag, names, params, code, ctl, source, tail = ue_inline.parts(data, recs[0])
        self.assertEqual(tag, 'SP')
        self.assertEqual(names, b'in_texcoord6\x00')
        self.assertEqual(code[:4], b'xV4\x12')          # the code area starts with the NVN program's magic
        self.assertEqual(ctl[:4], ue_inline.MAGIC)       # the control section starts with its own
        self.assertTrue(source.startswith(b'!!NVfp5.0\n'))
        self.assertEqual(tail, source[-ue_inline.TAIL:])  # the tail repeats the end of the source

    def test_the_names_are_where_the_record_puts_them(self):
        # the names' length sits at +15 in most records and further in the others (measured: +15 in 139 of 199 records of a material package, +26 in the others)
        for header in (b'\x00\x01\x00\xfe\x07\x02\x00\x00\x00', b'\x00\x00\x00\x00\x01\x00\x00\x00\x10\x00\x75\x04\x0c\x00\xf0\x06\x02\x00\x00\x00'):
            data = record(header=header)
            recs = ue_inline.records(data)
            self.assertEqual(len(recs), 1, header)
            self.assertEqual(ue_inline.parts(data, recs[0])[1], b'in_texcoord6\x00')

    def test_a_global_shader_has_no_names(self):
        data = record(names=b'')
        recs = ue_inline.records(data)
        self.assertEqual(len(recs), 1)
        self.assertEqual(ue_inline.parts(data, recs[0])[1], b'')

    def test_bytes_that_are_not_a_record_are_skipped(self):
        data = b'LSLG' + b'\x00' * 64 + record() + b'LSLG' + b'\x00' * 64
        self.assertEqual(len(ue_inline.records(data)), 1)

    def test_a_record_that_does_not_read_is_reported(self):
        # a program but no control section: a record of a shape this reader does not know
        data = b'LSLG' + b'SP' + b'\x00\x01\x00\xfe\x07\x02\x00\x00\x00' + (13).to_bytes(4, 'little') + b'in_texcoord6\x00' + b'xV4\x12\x00\x01\x00\x18'
        seen = []
        self.assertEqual(len(ue_inline.records(data, warn=lambda at, why: seen.append((at, why)))), 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], 0)
        self.assertIn('no control section', seen[0][1])

    def test_the_old_layout_is_untouched(self):
        import uepak
        ctl = bytearray(0x880)
        ctl[0:4] = ue_inline.MAGIC
        code = b'xV4\x12' + b'\x00' * 0x7e
        ctl[0x704:0x708] = len(code).to_bytes(4, 'little')   # the old control section holds the code area's length
        old = b'LSLG' + b'SP' + b'\x00' * 6 + len(code).to_bytes(4, 'little') + code + len(ctl).to_bytes(4, 'little') + bytes(ctl) + b'\x00' * 24
        tag, control, area = uepak.lslg(old)
        self.assertEqual((tag, len(control), len(area)), ('SP', 0x880, len(code)))
        self.assertEqual(ue_inline.records(old), [])   # the old layout is not this one's


class Programs(unittest.TestCase):
    """The programs the game hands the NVN driver (the host's DM_NVN_SHDUMP dump): the 0x880-byte control section the driver reads, then the code area. This is the form the
    translation chain takes, so a game whose engine expands its inline records at run time (Unreal Engine 4.27) is built from these"""

    @staticmethod
    def dump(code, ctl_len=0x880, code_len=None):
        ctl = bytearray(ctl_len)
        ctl[0:4] = ue_inline.MAGIC
        ctl[0x704:0x708] = (len(code) if code_len is None else code_len).to_bytes(4, 'little')
        return bytes(ctl) + code

    @staticmethod
    def graphics(sph=b'\x62\x54\x06\x00'):
        # the old layout: the magic, a 0x30-byte header, the 0x50-byte SPH, the instructions at +0x80
        return b'xV4\x12' + b'\x00' * 0x2c + sph + b'\x00' * 0x4e + b'\xf0\x07\xc0\xe2' + b'\x00' * 0x7e

    def test_a_pixel_program_is_read(self):
        code = self.graphics()
        st, ctl, area = ue_inline.program(self.dump(code))
        self.assertEqual(st, 'ps')
        self.assertEqual(ctl[:4], ue_inline.MAGIC)
        self.assertEqual(len(ctl), 0x880)
        self.assertEqual(area, code)

    def test_a_vertex_program_is_read(self):
        st, ctl, area = ue_inline.program(self.dump(self.graphics(b'\x61\x04\x06\x02')))
        self.assertEqual(st, 'vs')

    def test_a_geometry_program_is_read(self):
        # the SPH's type bits tell the stages apart: 1 vertex, 4 geometry, 5 pixel (the first byte alone does not: vertex and geometry share it)
        st, ctl, area = ue_inline.program(self.dump(self.graphics(b'\x61\x10\x06\x10')))
        self.assertEqual(st, 'gs')

    def test_a_compute_program_is_read(self):
        # a compute program has its own magic (0x12345679) and its instructions at +0x100
        code = b'yV4\x12' + b'\x00' * 0xfe + b'\xf0\x07\xc0\xe2'
        st, ctl, area = ue_inline.program(self.dump(code))
        self.assertEqual(st, 'cs')
        self.assertEqual(area, code)

    def test_a_dump_that_does_not_read_is_refused(self):
        code = self.graphics()
        self.assertIsNone(ue_inline.program(self.dump(code, code_len=len(code) + 4)))   # the control's length does not match
        self.assertIsNone(ue_inline.program(b'\x00' * 16))                              # too short
        self.assertIsNone(ue_inline.program(self.dump(b'zzzz' + code[4:])))              # the code area's magic is not a program's

    def test_the_programs_of_a_folder_are_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'program_0123456789abcdef_0.bin'), 'wb') as f: f.write(self.dump(self.graphics()))
            with open(os.path.join(d, 'program_0123456789abcdef_1.bin'), 'wb') as f: f.write(self.dump(self.graphics(b'\x61\x04\x06\x02')))
            with open(os.path.join(d, 'notes.txt'), 'wb') as f: f.write(b'not a program')
            got = list(ue_inline.programs(d))
        self.assertEqual([g[0] for g in got], ['program_0123456789abcdef_0.bin', 'program_0123456789abcdef_1.bin'])
        self.assertEqual([g[1] for g in got], ['ps', 'vs'])


class InlineJob(unittest.TestCase):
    """The Oodle job of the blocks of the cooked packages (uepak.inline_job): the game decodes the blocks one at a time, so the job's records are the blocks in the order they
    are read, and the manifest says which file and block each record belongs to"""

    class Pak:   # the parts of a pak the job needs: the file's entry
        def __init__(self, entries): self.entries = entries
        def entry(self, name): return self.entries[name]

    def test_the_blocks_are_in_order(self):
        import struct, tempfile
        with tempfile.TemporaryDirectory() as d:
            pak = Path(d) / 'x.pak'
            pak.write_bytes(b'\x00' * 100 + b'0123456789' + b'abcdefg')   # two blocks, 10 and 7 bytes
            e = dict(off=100, raw=20, block_size=16, blocks=[(0, 10), (10, 7)])
            job, manifest = uepak.inline_job(str(pak), self.Pak({'a.uexp': e}), ['a.uexp'])
        magic, n = struct.unpack_from('<2I', job)
        self.assertEqual((magic, n), (uepak.JOB_MAGIC, 2))
        stored, raw = struct.unpack_from('<2I', job, 8)
        self.assertEqual((stored, raw), (10, 16))            # the first block holds block_size raw bytes
        self.assertEqual(job[16:26], b'0123456789')
        stored, raw = struct.unpack_from('<2I', job, 26)
        self.assertEqual((stored, raw), (7, 4))              # the last block holds the rest
        self.assertEqual(job[34:41], b'abcdefg')
        self.assertEqual(manifest, [dict(file='a.uexp', block=0, raw=16, stored=10),
                                    dict(file='a.uexp', block=1, raw=4, stored=7)])

    def test_the_files_that_can_hold_records(self):
        pk = self.Pak({'Engine/GlobalShaderCache-GLSL_SWITCH.bin': 0, 'Nuts/Content/A.uexp': 0, 'Nuts/Content/B.uasset': 0})
        pk.files = {'Engine/GlobalShaderCache-GLSL_SWITCH.bin': 0, 'Nuts/Content/A.uexp': 0, 'Nuts/Content/B.uasset': 0}
        self.assertEqual(uepak.inline_files(pk), ['Engine/GlobalShaderCache-GLSL_SWITCH.bin', 'Nuts/Content/A.uexp'])

    def test_the_form_of_the_shaders(self):
        self.assertEqual(uepak.form([]), 'inline')   # no archive and no library: the records sit in the cooked packages
        self.assertEqual(uepak.form([dict(name='a.ushaderbytecode', compression='')]), 'archive')
        self.assertEqual(uepak.form([dict(name='a.ushaderbytecode', compression='Oodle')]), 'archive')
        self.assertEqual(uepak.form([dict(name='a.ushaderbytecode', compression='IoStore, decoded')]), 'iostream')

    def test_the_decoded_blocks_go_back_into_their_files(self):
        import struct, tempfile
        with tempfile.TemporaryDirectory() as d:
            # a job of two blocks of two files, and the answer the game's decoder wrote for it
            answer = Path(d) / 'job.out'
            out = Path(d) / 'out'
            manifest = [dict(file='a.uexp', block=0, raw=4, stored=4), dict(file='a.uexp', block=1, raw=4, stored=4),
                        dict(file='b.uexp', block=0, raw=8, stored=8)]
            body = b''.join(struct.pack('<I', n) + b for n, b in ((4, b'LSLG'), (4, b'aaaa'), (8, b'no record')))
            answer.write_bytes(struct.pack('<2I', uepak.OUT_MAGIC, len(manifest)) + body)
            kept = uepak.inline_finish(str(answer), manifest, str(out))
            self.assertEqual(kept, ['a.uexp'])   # only the file with a record in it is kept
            self.assertEqual((out / 'a.uexp').read_bytes(), b'LSLGaaaa')
            self.assertFalse((out / 'b.uexp').exists())


if __name__ == '__main__': unittest.main()
