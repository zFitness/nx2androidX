package com.nx.android.agent.env

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * 引擎会话目录的读法：枚举、按时间排序、标题（会话名优先，读不到退回时间）。
 */
class PiSessionCatalogTest {

    @get:Rule
    val folder = TemporaryFolder()

    /** 造一段会话文件：头部是会话头与若干条目，末尾可以带一条会话名。 */
    private fun session(dir: File, name: String, named: String? = null, userText: String = "为啥闪退"): File {
        dir.mkdirs()
        val f = File(dir, name)
        val sb = StringBuilder()
        sb.append("""{"type":"session","version":3,"id":"abc","timestamp":"2026-11-22T10:33:53.596Z","cwd":"/x"}""").append('\n')
        sb.append("""{"type":"message","id":"1","parentId":null,"message":{"role":"user","content":[{"type":"text","text":"$userText"}]}}""").append('\n')
        if (named != null) {
            sb.append("""{"type":"session_info","id":"2","parentId":"1","timestamp":"2026-11-22T13:51:33.513Z","name":"$named"}""").append('\n')
        }
        f.writeText(sb.toString())
        return f
    }

    /** 子 Agent 自己的会话：文件头里写着它的父会话。 */
    private fun subagentSession(dir: File, name: String, parent: String): File {
        dir.mkdirs()
        val f = File(dir, name)
        f.writeText(
            """{"type":"session","version":3,"id":"sub","timestamp":"2026-11-22T10:33:53.596Z","cwd":"/x","parentSession":"$parent"}""" +
                "\n" +
                """{"type":"message","id":"1","parentId":null,"message":{"role":"user","content":"task"}}""" + "\n",
        )
        return f
    }

    private fun catalog(): PiSessionCatalog = PiSessionCatalog(folder.newFolder("home"))

    @Test
    fun `no sessions is an empty list`() {
        assertTrue(catalog().list().isEmpty())
    }

    @Test
    fun `every session file becomes an entry`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--data-user-0-x--")
        session(dir, "2026-11-22T10-33-53-596Z_a.jsonl")
        session(dir, "2026-11-22T11-40-27-295Z_b.jsonl")
        val entries = PiSessionCatalog(home).list()
        assertEquals(2, entries.size)
        assertTrue(entries.all { it.path.endsWith(".jsonl") })
    }

    @Test
    fun `the newest session comes first`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        val older = session(dir, "2026-11-22T10-33-53-596Z_a.jsonl")
        val newer = session(dir, "2026-11-22T11-40-27-295Z_b.jsonl")
        older.setLastModified(1_000L)
        newer.setLastModified(2_000L)
        val entries = PiSessionCatalog(home).list()
        assertEquals(newer.absolutePath, entries[0].path)
        assertEquals(older.absolutePath, entries[1].path)
    }

    @Test
    fun `the session name is the title`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        session(dir, "2026-11-22T10-33-53-596Z_a.jsonl", named = "为啥这个游戏闪退")
        assertEquals("为啥这个游戏闪退", PiSessionCatalog(home).list().first().title)
    }

    @Test
    fun `a session without a name falls back to its time`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        session(dir, "2026-11-22T10-33-53-596Z_a.jsonl")
        val title = PiSessionCatalog(home).list().first().title
        assertTrue(title.contains("11-22"))
        assertTrue(title.contains("18:33"))   // 文件名里是 UTC，转成本地时间
    }

    @Test
    fun `a sub-agent's own session is not the player's`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        val mine = session(dir, "2026-11-22T10-33-53-596Z_a.jsonl", named = "我的会话")
        subagentSession(dir, "2026-11-22T11-40-27-295Z_b.jsonl", mine.absolutePath)

        val entries = PiSessionCatalog(home).list()
        assertEquals(1, entries.size)
        assertEquals("我的会话", entries[0].title)
    }

    @Test
    fun `a session whose parent is gone is still not the player's`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        session(dir, "2026-11-22T10-33-53-596Z_a.jsonl")
        subagentSession(dir, "2026-11-22T11-40-27-295Z_b.jsonl", "/gone/parent.jsonl")

        assertEquals(1, PiSessionCatalog(home).list().size)
    }

    @Test
    fun `the current session is the newest one of the player's`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        val older = session(dir, "2026-11-22T10-33-53-596Z_a.jsonl", named = "上一局")
        val newer = session(dir, "2026-11-22T11-40-27-295Z_b.jsonl", named = "这一局")
        older.setLastModified(1_000L)
        newer.setLastModified(2_000L)

        assertEquals(newer.absolutePath, PiSessionCatalog(home).current()?.path)
    }

    @Test
    fun `a sub-agent's session is never the current one`() {
        val home = folder.newFolder("home")
        val dir = File(home, ".pi/agent/sessions/--x--")
        val mine = session(dir, "2026-11-22T10-33-53-596Z_a.jsonl", named = "我的会话")
        // the sub-agent writes its own session at the same time, and it is the newer file
        val theirs = subagentSession(dir, "2026-11-22T11-40-27-295Z_b.jsonl", mine.absolutePath)
        mine.setLastModified(1_000L)
        theirs.setLastModified(2_000L)

        assertEquals(mine.absolutePath, PiSessionCatalog(home).current()?.path)
    }

    @Test
    fun `no session at all leaves the current one unknown`() {
        assertNull(PiSessionCatalog(folder.newFolder("home")).current())
    }
}
