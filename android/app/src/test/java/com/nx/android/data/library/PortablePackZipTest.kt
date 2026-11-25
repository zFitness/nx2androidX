package com.nx.android.data.library

import com.nx.android.domain.PortablePack
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream

/** 直读包的备份：一个 zip，带走 mods / shader / 设置，不带游戏数据，也不带导出机自己的路径 */
class PortablePackZipTest {

    private fun tmpDir(name: String): File =
        File.createTempFile("nx2a-backup", "").let { f -> f.delete(); f.mkdirs(); f }

    /** 一个直读包：清单说 container，env 里是导出机自己的游戏文件和 DLC 拷贝 */
    private fun fakeContainerPack(root: File, name: String = "Test Game-data"): File {
        val pack = File(root, name).apply { mkdirs() }
        File(pack, "mods").mkdirs()
        File(pack, "mods/main.nso").writeBytes(ByteArray(512))
        File(pack, "shaders.dmsv").writeBytes(ByteArray(256))
        File(pack, "aoc").mkdirs()
        File(pack, "aoc/2.nsp").writeBytes(ByteArray(128))
        File(pack, "saves").mkdirs()
        File(pack, "saves/backup.zip").writeText("the player's own backup")
        File(pack, "icon.png").writeBytes(ByteArray(64))   // the cover the library shows
        val manifest = JSONObject()
            .put("title_id", "0100B8A026F14000")
            .put("name", "Test Game")
            .put("container", true)
            .put("files", 3)
            .put("bytes", 896)
            .put("parts", JSONObject().put("aoc", JSONObject().put("files", 1).put("bytes", 128)))
        File(pack, PortablePack.MANIFEST).writeText(manifest.toString())
        File(pack, PortablePack.ENV).writeText(
            "# Written by nx2android's porter\n" +
                "DM_LANG=ko\n" +
                "DM_ROMFS_CONTAINER=/storage/emulated/0/Roms/game.nsp\n" +
                "DM_ROMFS_UPDATE=/storage/emulated/0/Roms/update.nsp\n" +
                "DM_PROD_KEYS=/storage/emulated/0/keys/prod.keys\n" +
                "DM_AOC_DIR=${pack.absolutePath}/aoc\n"
        )
        return pack
    }

    private fun entries(zip: File): Map<String, ByteArray> = ZipFile(zip).use { zf ->
        zf.entries().toList().filter { !it.isDirectory }.associate { e ->
            e.name to zf.getInputStream(e).readBytes()
        }
    }

    @Test
    fun `the backup leaves out the game data, the DLC copies and the saves`() {
        val root = tmpDir("root"); val dst = tmpDir("dst")
        val pack = fakeContainerPack(root)

        val r = PortablePackZip.export(pack, dst, "Test Game")

        assertTrue(r.failure ?: "", r.ok)
        val zip = File(dst, "Test Game.zip")
        assertTrue(zip.isFile)
        val all = entries(zip)
        assertTrue(all.keys.any { it.endsWith("/mods/main.nso") })
        assertTrue(all.keys.any { it.endsWith("/shaders.dmsv") })
        assertTrue(all.keys.any { it.endsWith("/icon.png") })   // the library's cover travels
        assertFalse(all.keys.any { it.contains("/aoc/") })
        assertFalse(all.keys.any { it.contains("/saves/") })
        // the manifest no longer counts the DLC copy it left out
        val man = JSONObject(String(all.entries.first { it.key.endsWith("/${PortablePack.MANIFEST}") }.value))
        assertTrue(man.optBoolean("container"))
        assertNull(man.optJSONObject("parts"))
        // and the env names no file of the exporting phone
        val env = String(all.entries.first { it.key.endsWith("/${PortablePack.ENV}") }.value)
        assertFalse(env.contains("DM_ROMFS_CONTAINER"))
        assertFalse(env.contains("DM_ROMFS_UPDATE"))
        assertFalse(env.contains("DM_PROD_KEYS"))
        assertTrue(env.contains("DM_LANG=ko"))
        assertTrue(env.contains("DM_AOC_DIR="))   // the pack's own folder row stays, for the import to rebase
    }

    @Test
    fun `the import lands the pack under a partial name and points its rows at the new place`() {
        val root = tmpDir("root"); val dst = tmpDir("dst"); val ports = tmpDir("ports")
        PortablePackZip.export(fakeContainerPack(root), dst, "Test Game")

        val v = PortablePackZip.import(File(dst, "Test Game.zip"), ports)

        assertTrue(v.failure ?: "", v.ok)
        assertTrue(v.container)
        val landed = v.pack!!
        // the library only scans `*-data` folders: the plain name in the zip must not leave the game invisible
        assertEquals(File(ports, "Test Game-data").absolutePath, landed.absolutePath)
        assertTrue(landed.isDirectory)
        assertTrue(File(landed, "icon.png").isFile)
        val found = LibraryFileScanner.outIndex(ports)
        assertEquals(1, found.size)
        assertEquals(File(landed, "icon.png"), found.getValue("0100B8A026F14000").icon)
        assertFalse(ports.listFiles()!!.any { it.name.endsWith(".partial") })
        val env = File(landed, PortablePack.ENV).readText()
        assertTrue(env.contains("DM_AOC_DIR=${landed.absolutePath}/aoc"))
        // the game file comes from a relink on this phone: no row names another phone's
        assertFalse(PortablePack.containerLinked(landed))
    }

    @Test
    fun `a pack that carries its game files is refused`() {
        val dst = tmpDir("dst"); val ports = tmpDir("ports")
        val zip = File(dst, "folder.zip")
        ZipOutputStream(zip.outputStream()).use { out ->
            out.putNextEntry(ZipEntry("Old/"))
            out.closeEntry()
            out.putNextEntry(ZipEntry("Old/nx2a-data.json"))
            out.write(JSONObject().put("title_id", "0100B8A026F14000").put("name", "Old").toString().toByteArray())
            out.closeEntry()
        }
        val v = PortablePackZip.import(zip, ports)
        assertFalse(v.ok)
        assertEquals("not_container", v.failure)
        assertEquals(0, ports.listFiles()?.size ?: 0)
    }

    @Test
    fun `an entry that climbs out of the folder is refused`() {
        val dst = tmpDir("dst"); val ports = tmpDir("ports")
        val zip = File(dst, "evil.zip")
        ZipOutputStream(zip.outputStream()).use { out ->
            out.putNextEntry(ZipEntry("Evil/nx2a-data.json"))
            out.write(JSONObject().put("title_id", "0100B8A026F14000").put("name", "Evil").put("container", true).toString().toByteArray())
            out.closeEntry()
            out.putNextEntry(ZipEntry("Evil/../../escape.txt"))
            out.write(ByteArray(4))
            out.closeEntry()
        }
        val v = PortablePackZip.import(zip, ports)
        assertFalse(v.ok)
        assertEquals("bad_zip", v.failure)
        assertFalse(File(ports.parentFile, "escape.txt").exists())
    }

    @Test
    fun `a second import of the same name is refused`() {
        val root = tmpDir("root"); val dst = tmpDir("dst"); val ports = tmpDir("ports")
        PortablePackZip.export(fakeContainerPack(root), dst, "Test Game")
        assertTrue(PortablePackZip.import(File(dst, "Test Game.zip"), ports).ok)
        val again = PortablePackZip.import(File(dst, "Test Game.zip"), ports)
        assertFalse(again.ok)
        assertEquals("exists", again.failure)
    }

    @Test
    fun `a container manifest validates without a RomFS folder`() {
        val root = tmpDir("root")
        val pack = fakeContainerPack(root)
        val v = PortablePack.validateContainer(pack)
        assertTrue(v.ok)
        assertTrue(v.container)
        assertFalse(PortablePack.validate(pack).ok)   // the folder import still wants the game's files
    }
}