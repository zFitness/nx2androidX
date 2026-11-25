# --romfs-container's data pack (the PC install path): the pack holds no copy of the game; the manifest lists the player's
# own NSPs and keys for the installer to push, and env.txt points the host at them.
import os, shutil, sys, tempfile, unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault('NX2A_HOME', tempfile.mkdtemp(prefix='nx2a_test_home_'))

from porter import datapack, install, profiles   # noqa: E402

NEO = '010043B013C5C000'


class ContainerPack(unittest.TestCase):
    def test_container(self):
        t = Path(tempfile.mkdtemp(prefix='nx2a_test_pack_'))
        try:
            (t / 'patched').mkdir(); (t / 'patched/main.patched.bin').write_bytes(b'x' * 10)
            base, upd, dlc, keys, tkeys = t / 'game.nsp', t / 'upd.nsp', t / 'dlc.nsp', t / 'prod.keys', t / 'title.keys'
            for f, n in ((base, 100), (upd, 50), (dlc, 30)): f.write_bytes(b'n' * n)
            keys.write_text('master_key_00 = 00\n'); tkeys.write_text('00ff = 11\n')
            p = profiles.load(NEO)
            man = datapack.build(t / 'out-data', profile=p, version='v196608', display='1.03', patched=t / 'patched', romfs=None, shaders=None,
                                 containers=[(datapack.CONTAINER_BASE, base, 100), (datapack.CONTAINER_UPDATE, upd, 50), ('aoc/2.nsp', dlc, 30)],
                                 keys=[('prod.keys', keys, keys.stat().st_size), ('title.keys', tkeys, tkeys.stat().st_size)])
            o = t / 'out-data'; ff = '/sdcard/Android/data/org.nx2a.neo/files'
            self.assertEqual(sorted(p.relative_to(o).as_posix() for p in o.rglob('*') if p.is_file()), ['env.txt', 'mods/main.patched.bin', 'nx2a-data.json', 'settings.txt'])   # no game data in the pack
            env = (o / 'env.txt').read_text()
            for row in (f'DM_PROD_KEYS={ff}/prod.keys', f'DM_ROMFS_CONTAINER={ff}/container/{datapack.CONTAINER_BASE}',
                        f'DM_ROMFS_UPDATE={ff}/container/{datapack.CONTAINER_UPDATE}', f'DM_AOC_DIR={ff}/container/aoc'):
                self.assertIn(row, env)
            self.assertEqual((man['files'], man['dlc']), (1, [2])); self.assertFalse(man.get('parts')); self.assertTrue(man['container'])
            self.assertEqual(man['push']['container'], [dict(dst=datapack.CONTAINER_BASE, src='game.nsp', bytes=100), dict(dst=datapack.CONTAINER_UPDATE, src='upd.nsp', bytes=50),
                                                        dict(dst='aoc/2.nsp', src='dlc.nsp', bytes=30)])   # beside the pack: named, not this PC's path
            self.assertEqual([e['dst'] for e in man['push']['keys']], ['prod.keys', 'title.keys'])
            xci = t / 'game.xci'; xci.write_bytes(b'x' * 70)   # a gamecard base keeps its format on the device: romfs.xci, and the host reads XCIs too
            man = datapack.build(t / 'xci-data', profile=p, version='v196608', display='1.03', patched=t / 'patched', romfs=None, shaders=None,
                                 containers=[('romfs.xci', xci, 70), (datapack.CONTAINER_UPDATE, upd, 50)], keys=[('prod.keys', keys, keys.stat().st_size)])
            self.assertIn(f'DM_ROMFS_CONTAINER={ff}/container/romfs.xci', (t / 'xci-data/env.txt').read_text())
            self.assertEqual(man['push']['container'][0], dict(dst='romfs.xci', src='game.xci', bytes=70))
        finally:
            shutil.rmtree(t, ignore_errors=True)

    def test_app_mode_container_lists_the_players_files(self):   # the phone: no push list, env.txt names the files where the player keeps them
        t = Path(tempfile.mkdtemp(prefix='nx2a_test_appcont_'))
        try:
            p = profiles.load(NEO)
            man = datapack.build(t / 'out-data', profile=p, version='v1', display='1.0', patched=None, romfs=None, shaders=None, container=True,
                                 env=['DM_ROMFS_CONTAINER=/sdcard/game.nsp', 'DM_PROD_KEYS=/sdcard/prod.keys'])
            self.assertTrue(man['container']); self.assertNotIn('push', man)
            env = (t / 'out-data/env.txt').read_text()
            for row in ('DM_ROMFS_CONTAINER=/sdcard/game.nsp', 'DM_PROD_KEYS=/sdcard/prod.keys'): self.assertIn(row, env)
        finally:
            shutil.rmtree(t, ignore_errors=True)

    def test_install_push_finds_the_game_beside_the_pack(self):   # the manifest names a game file beside the pack; the installer looked inside it instead (SRW30's 14 GB XCI)
        t = Path(tempfile.mkdtemp(prefix='nx2a_test_push_'))
        try:
            (t / 'game.xci').write_bytes(b'x' * 70); (t / 'out-data').mkdir()
            man = {'push': {'container': [dict(dst='romfs.xci', src='game.xci', bytes=70)]}}
            self.assertEqual(install.game_files(man, '/files', t / 'out-data')[0][0], (t / 'game.xci').resolve())
            (t / 'game.xci').write_bytes(b'x')   # the same name at another size is not the file the port listed
            with self.assertRaises(install.BuildError): install.game_files(man, '/files', t / 'out-data')
        finally:
            shutil.rmtree(t, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()