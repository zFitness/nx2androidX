package com.nx.android.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The export of a port as a game of its own: the names, the directory the exported game reads, and the env.txt
 * the data folder carries (the rows that pointed inside the pack follow the folder, the shared font travels
 * with it, the row that pointed at the exporting phone's workspace is gone).
 */
class GameApkExportTest {

    private val gameDir = "/storage/emulated/0/Android/data/org.nx2a.t0100bb8017f24000/files"

    @Test
    fun `the exported game reads its own directory`() {
        assertEquals(gameDir, GameApkExport.gameFilesDir("org.nx2a.t0100bb8017f24000"))
    }

    @Test
    fun `the rows that point inside the pack follow the game's own directory`() {
        val env = """
            # the porter's rows
            DM_AOC_DIR=/data/user/0/com.nx.android/files/ports/Game-data/aoc
            DM_SYSDATA=/data/user/0/com.nx.android/files/ports/Game-data/sysdata
            DM_SHARED_FONT_EXT=/data/user/0/com.nx.android/files/ports/Game-data/nintendo_ext.ttf
            DM_LANG=zh-Hans
        """.trimIndent()
        val out = GameApkExport.envForGameDir(env, gameDir)
        assertTrue(out.contains("DM_AOC_DIR=$gameDir/aoc"))
        assertTrue(out.contains("DM_SYSDATA=$gameDir/sysdata"))
        assertTrue(out.contains("DM_SHARED_FONT_EXT=$gameDir/nintendo_ext.ttf"))
        assertTrue(out.contains("DM_LANG=zh-Hans"))
        assertFalse(out.contains("/data/user/0/com.nx.android"))
    }

    @Test
    fun `the shared font travels with the folder`() {
        val env = "DM_SHARED_FONT=/data/user/0/com.nx.android/files/tool/nxnative/dm/tools/shared_cjk.ttf\n"
        val out = GameApkExport.envForGameDir(env, gameDir)
        assertTrue(out.contains("DM_SHARED_FONT=$gameDir/standard.ttf"))
        assertFalse(out.contains("shared_cjk.ttf"))
    }

    @Test
    fun `the row that pointed at the exporting phone's workspace is gone`() {
        val env = "DM_ROMFS=/data/user/0/com.nx.android/files/work/0100_build/extract/v0/RomFS\nDM_LANG=en\n"
        val out = GameApkExport.envForGameDir(env, gameDir)
        assertFalse(out.contains("DM_ROMFS"))
        // the game's files are inside the folder: the front reads <its own directory>/RomFS
        assertTrue(out.contains("DM_LANG=en"))
    }

    @Test
    fun `a row that points nowhere in the pack stays as it is`() {
        val env = "DM_VK_DRIVER=libvulkan_freedreno.so\nDM_MENU_BUTTON=0\n"
        val out = GameApkExport.envForGameDir(env, gameDir)
        assertTrue(out.contains("DM_VK_DRIVER=libvulkan_freedreno.so"))
        assertTrue(out.contains("DM_MENU_BUTTON=0"))
    }

    @Test
    fun `a value is read out of the rows`() {
        val env = "# a comment\nDM_LANG=zh-Hans\nDM_VK_DRIVER=libvulkan_freedreno.so\n"
        assertEquals("zh-Hans", GameApkExport.envValue(env, "DM_LANG"))
        assertEquals("libvulkan_freedreno.so", GameApkExport.envValue(env, "DM_VK_DRIVER"))
        assertEquals(null, GameApkExport.envValue(env, "DM_ROMFS"))
    }

    @Test
    fun `the size of a tree is counted without reading it`() {
        val root = java.io.File.createTempFile("nx2a-tree", ".dir")
        root.delete()
        val sub = java.io.File(root, "mods")
        sub.mkdirs()
        java.io.File(sub, "main.nso").writeBytes(ByteArray(100))
        java.io.File(root, "env.txt").writeText("x")
        assertEquals(101L, GameApkExport.treeBytes(root))
        root.deleteRecursively()
    }
}
