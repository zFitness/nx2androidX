package com.nx.android.agent.env

import com.nx.android.agent.AgentSubagent
import com.nx.android.agent.AgentSubagentCall
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 跑完的和在跑的合成一份清单：谁压谁、类型和任务从哪儿来。
 *
 * 一条记录 = 一次运行。同一个 agent 跑第二次，id 不变、记录多一条——界面要分得清。
 */
class SubagentRunsTest {

    private fun finished(
        id: String,
        startedAt: Long,
        status: String = "completed",
        prompt: String? = null,
    ) = AgentSubagent(
        id = id,
        type = "general-purpose",
        description = "Run marker echo",
        status = status,
        startedAt = startedAt,
        completedAt = startedAt + 100,
        prompt = prompt,
    )

    private fun transcript(
        id: String,
        prompt: String,
        lastWriteAt: Long,
        runIndex: Int = 1,
        interrupted: Boolean = false,
        messages: List<org.json.JSONObject> = emptyList(),
    ) = SubagentTranscripts.Transcript(
        agentId = id,
        prompt = prompt,
        messages = messages,
        lastWriteAt = lastWriteAt,
        runIndex = runIndex,
        interrupted = interrupted,
    )

    @Test
    fun `a running run carries what it has spent so far`() {
        // 正在跑的那一次：尾巴里那些回答各自的用量加起来
        val usage = org.json.JSONObject()
            .put("input", 5)
            .put("output", 20)
            .put("cacheRead", 0)
            .put("cacheWrite", 0)
        val answer = org.json.JSONObject().put("role", "assistant").put("usage", usage)
        val merged = SubagentRuns.merge(
            finished = emptyList(),
            live = listOf(transcript("d", "run echo", 40L, messages = listOf(answer))),
            calls = emptyList(),
        )
        assertEquals(25L, merged.first().usage.total)
        assertEquals(20L, merged.first().usage.output)
    }

    @Test
    fun `a finished run wins over its transcript`() {
        val merged = SubagentRuns.merge(
            finished = listOf(finished("a", 10L)),
            live = listOf(transcript("a", "run echo", 10L)),
            calls = emptyList(),
        )
        assertEquals(1, merged.size)
        assertEquals("completed", merged.first().status)
    }

    @Test
    fun `a running run takes its type and its task from the call`() {
        val merged = SubagentRuns.merge(
            finished = emptyList(),
            live = listOf(transcript("b", "run echo MARKER_TEST", 20L)),
            calls = listOf(
                AgentSubagentCall("general-purpose", "Run marker echo", "run echo MARKER_TEST"),
            ),
        )
        assertEquals(1, merged.size)
        assertEquals("running", merged.first().status)
        assertEquals("general-purpose", merged.first().type)
        assertEquals("Run marker echo", merged.first().description)
    }

    @Test
    fun `a running run without a call falls back to its prompt`() {
        val merged = SubagentRuns.merge(
            finished = emptyList(),
            live = listOf(transcript("c", "check the log\nand tell me", 30L)),
            calls = emptyList(),
        )
        assertEquals("check the log", merged.first().description)
        assertEquals("", merged.first().type)
    }

    @Test
    fun `the runs come out oldest first`() {
        val merged = SubagentRuns.merge(
            finished = listOf(finished("a", 10L), finished("b", 40L)),
            live = listOf(transcript("c", "x", 20L)),
            calls = emptyList(),
        )
        assertEquals(listOf("a", "c", "b"), merged.map { it.id })
    }

    @Test
    fun `nothing at all is an empty list`() {
        assertTrue(SubagentRuns.merge(emptyList(), emptyList(), emptyList()).isEmpty())
    }

    @Test
    fun `a continued run is not swallowed by the finished one`() {
        // 同一个 agent：第一次跑完了（一条记录），第二次正在跑（transcript 里两条 user 消息）
        val merged = SubagentRuns.merge(
            finished = listOf(finished("a", 10L, prompt = "first task")),
            live = listOf(transcript("a", "first task", 200L, runIndex = 2)),
            calls = emptyList(),
        )
        assertEquals(2, merged.size)
        assertEquals("completed", merged[0].status)
        assertEquals("running", merged[1].status)
    }

    @Test
    fun `a continued run shows its own id of the run`() {
        val merged = SubagentRuns.merge(
            finished = listOf(finished("a", 10L)),
            live = listOf(transcript("a", "first task", 200L, runIndex = 2)),
            calls = emptyList(),
        )
        assertEquals(2, merged.map { it.runId }.distinct().size)
    }

    @Test
    fun `a transcript of a run that ended is not a running one`() {
        // 一条记录 = 跑完一次；transcript 里只有一条 user 消息 = 跑过一次 → 没有在跑的
        val merged = SubagentRuns.merge(
            finished = listOf(finished("a", 10L)),
            live = listOf(transcript("a", "first task", 20L, runIndex = 1)),
            calls = emptyList(),
        )
        assertEquals(1, merged.size)
        assertEquals("completed", merged.first().status)
    }

    @Test
    fun `the call that started a run is found by its task`() {
        val runs = listOf(finished("a", 10L, prompt = "first task"))
        val link = SubagentRuns.link(
            calls = listOf(
                AgentSubagentCall("gamespec", "Diagnose", "first task", toolCallId = "call-1"),
            ),
            runs = runs,
        )
        assertEquals("a#10", link.byCall["call-1"]?.runId)
    }

    @Test
    fun `the call that continued a run is found by the agent it points at`() {
        // 第一次运行（已完成）+ 第二次运行（续跑，正在跑）
        val runs = SubagentRuns.merge(
            finished = listOf(finished("a", 10L, prompt = "first task")),
            live = listOf(transcript("a", "first task", 200L, runIndex = 2)),
            calls = emptyList(),
        )
        val link = SubagentRuns.link(
            calls = listOf(
                AgentSubagentCall("gamespec", "Diagnose", "first task", toolCallId = "call-1"),
                AgentSubagentCall(
                    "gamespec", "Implement", "now implement it",
                    resumeId = "a", toolCallId = "call-2",
                ),
            ),
            runs = runs,
        )
        // 第一次的调用对上第一次的运行，续跑的调用对上续跑的那次
        assertEquals("completed", link.byCall["call-1"]?.status)
        assertEquals("running", link.byCall["call-2"]?.status)
        assertEquals("Implement", link.byRun[link.byCall["call-2"]!!.runId]?.description)
    }

    @Test
    fun `a call without a handle is not linked to anything`() {
        val link = SubagentRuns.link(
            calls = listOf(AgentSubagentCall("gamespec", "Diagnose", "first task")),
            runs = listOf(finished("a", 10L, prompt = "first task")),
        )
        assertTrue(link.byCall.isEmpty())
    }

    @Test
    fun `a run nobody called has no link`() {
        val link = SubagentRuns.link(
            calls = emptyList(),
            runs = listOf(finished("a", 10L)),
        )
        assertNull(link.byRun["a#10"])
    }

    @Test
    fun `a run the app killed is interrupted, not running`() {
        // App 死了，引擎跟着死了：transcript 停在那儿，永远不会再写一行
        val merged = SubagentRuns.merge(
            finished = emptyList(),
            live = listOf(transcript("d", "measure the crash", 40L, interrupted = true)),
            calls = emptyList(),
        )
        assertEquals("interrupted", merged.first().status)
        assertTrue(!merged.first().running)
    }

    @Test
    fun `a run the session switch cut off is interrupted, not running`() {
        // 切走会话，引擎把正在跑的子代理掐了：引擎那边补了一条「已中断」的记录，
        // 那条 transcript 就不再被当成在跑的那一次
        val merged = SubagentRuns.merge(
            finished = listOf(finished("e", 50L, status = "interrupted")),
            live = listOf(transcript("e", "fix the crash", 50L, runIndex = 1)),
            calls = emptyList(),
        )
        assertEquals(1, merged.size)
        assertEquals("interrupted", merged.first().status)
        assertTrue(!merged.first().running)
        // 中断不是失败：它不是跑砸了，只是没跑完
        assertTrue(!merged.first().failed)
    }

    @Test
    fun `a transcript older than the app process belongs to the last one`() {
        // 上一个进程留下的东西：进程起来之前写下的，就是上一个进程那次跑的
        assertTrue(SubagentRuns.interrupted(writtenAt = 1_000L, processStartedAt = 10_000L))
    }

    @Test
    fun `a transcript the running process wrote is not interrupted`() {
        assertTrue(!SubagentRuns.interrupted(writtenAt = 20_000L, processStartedAt = 10_000L))
        // 刚起来的那一秒：手劲
        assertTrue(!SubagentRuns.interrupted(writtenAt = 9_500L, processStartedAt = 10_000L))
        // 没有写过：不知道，不乱说
        assertTrue(!SubagentRuns.interrupted(writtenAt = 0L, processStartedAt = 10_000L))
    }
}
