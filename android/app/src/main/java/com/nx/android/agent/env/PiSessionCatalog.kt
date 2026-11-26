package com.nx.android.agent.env

import com.nx.android.agent.runtime.AgentEngineStore
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import javax.inject.Inject
import javax.inject.Singleton
import org.json.JSONObject

/**
 * 引擎会话目录的读法：一个 jsonl 文件就是一段会话，最新的在最上面。
 *
 * 引擎的 RPC 没有「列出会话」的命令——目录枚举是 App 必须自己做的少数几件事之一。
 * 耦合面控制在这里：只用文件名、时间与文件头部的会话名；消息正文一律走 RPC，不解析
 * 它的内部格式。
 */
@Singleton
class PiSessionCatalog internal constructor(private val home: File) {

    /** 注入用的那个：会话目录在引擎自己的 HOME 下面。 */
    @Inject
    constructor(engine: AgentEngineStore) : this(engine.home)

    /** 下拉列表的一行：会话文件的路径、标题、最后活动时间。 */
    data class Entry(val path: String, val title: String, val updatedAt: Long)

    /** 引擎的全部会话，最新的在最上面。目录不在（引擎没装/还没聊过）就是空列表。 */
    fun list(): List<Entry> {
        return sessionFiles().mapNotNull { f ->
            val head = headOf(f)
            // 子 Agent 自己的会话不是玩家的会话：它的头里写着是谁派它出来的
            if (head.isSubagent) return@mapNotNull null
            Entry(f.absolutePath, head.title, f.lastModified())
        }.sortedByDescending { it.updatedAt }
    }

    /**
     * 引擎此刻在答的那一局：最新的**玩家**会话文件。
     *
     * 引擎把这一轮写进它正在答的那个会话文件，所以最新的玩家文件就是当前这一局。子 Agent
     * 的会话文件同时在写，被跳过——它们不属于玩家的任何一局。
     *
     * 为什么需要它：引擎的 `_active` 指针只在一轮**结束**时才被写成真正的路径，而子 Agent
     * 恰恰是在那一轮里跑的。于是第一轮派出的子 Agent 找不到自己的 transcript（面板空着），
     * 第二轮才看得到。指针是「上一轮结束时的答案」，这里给的是「此刻的答案」。
     */
    fun current(): Entry? {
        for (f in sessionFiles().sortedByDescending { it.lastModified() }) {
            val head = headOf(f)
            if (head.isSubagent) continue
            return Entry(f.absolutePath, head.title, f.lastModified())
        }
        return null
    }

    /** 引擎的会话文件们（各个工作目录下的）。 */
    private fun sessionFiles(): List<File> {
        val sessions = File(home, ".pi/agent/sessions")
        return sessions.listFiles { f -> f.isDirectory }
            ?.flatMap { dir -> dir.listFiles { f -> f.isFile && f.extension == "jsonl" }?.toList() ?: emptyList() }
            .orEmpty()
    }

    /** The session's head: its name, and whether a sub-agent owns it. */
    private data class Head(val title: String, val isSubagent: Boolean)

    /**
     * 标题：会话名优先——我们自己建的会话在首轮就把名字写进了文件头部，读文件头一小段
     * 就够；没读到（别处来的老会话）退回文件名里的时间。
     *
     * 同一个文件头还回答了另一个问题：这个会话是谁的。子 Agent 的会话头里写着它的父会话，
     * 玩家的会话没有——所以子 Agent 的会话不进玩家的列表。
     */
    private fun headOf(f: File): Head {
        var name: String? = null
        var isSubagent = false
        runCatching {
            f.inputStream().use { stream ->
                val head = ByteArray(64 * 1024)
                val n = stream.read(head)
                val lines = String(head, 0, n, Charsets.UTF_8).split('\n')
                lines.firstOrNull()?.takeIf { it.isNotBlank() }?.let { first ->
                    val header = runCatching { JSONObject(first) }.getOrNull()
                    if (header != null && !header.optString("parentSession").isNullOrBlank()) {
                        isSubagent = true
                    }
                }
                for (line in lines) {
                    if (!line.contains("\"session_info\"")) continue
                    runCatching { JSONObject(line).optString("name") }.getOrNull()
                        ?.takeIf { it.isNotBlank() }?.let { name = it }
                }
            }
        }
        return Head(name ?: timeTitle(f.name), isSubagent)
    }

    /** 文件名里的时间戳（UTC）转成本地可读的样子。 */
    private fun timeTitle(name: String): String {
        val parsed = runCatching {
            SimpleDateFormat("yyyy-MM-dd'T'HH-mm-ss", Locale.US).apply {
                timeZone = TimeZone.getTimeZone("UTC")
            }.parse(name.take(19))
        }.getOrNull()
        return if (parsed != null) {
            SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(parsed)
        } else {
            "会话"
        }
    }
}
