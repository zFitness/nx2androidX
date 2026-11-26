package com.nx.android.agent.env

import java.io.File
import java.io.RandomAccessFile
import org.json.JSONObject

/** How much of a transcript's tail is read: enough to see what it is doing. */
private const val CHUNK = 128 * 1024

/** The marker of a user message in a transcript: one per run. */
private const val USER_MARK = "\"type\":\"user\""

/** The marker of a tool call in a transcript: how much work the run has done. */
private const val TOOL_MARK = "\"type\":\"toolCall\""

/**
 * The transcripts of the sub-agents that are running right now.
 *
 * The engine's extension streams every sub-agent's conversation into a JSONL file under the
 * scratch folder — one file per sub-agent, named after its id. The lines carry the engine's own
 * messages, so the app reads them with the same mapper the main conversation uses.
 *
 * The scratch folder's own shape (the uid, the encoded working directory) belongs to the engine;
 * the app only looks for the folder named after the parent session's id.
 */
object SubagentTranscripts {

    /** The scratch folders the engine writes into, under the app's tmp. */
    private const val ROOT = "pi-subagents-"

    /** How many lines of the tail are kept. */
    const val MAX_LINES = 200

    /** How much of the head is read to find the task the agent was given. */
    private const val HEAD_CHUNK = 64 * 1024

    /** One running sub-agent's transcript. */
    data class Transcript(
        /** The sub-agent's id (the file's own name). */
        val agentId: String,
        /** The task it was given: its first message. */
        val prompt: String,
        /** The engine's messages, as they came in. */
        val messages: List<JSONObject>,
        /** When this transcript was last written: the sub-agent's own clock. */
        val lastWriteAt: Long = 0L,
        /** When this run started (the caller remembers it: the file keeps changing). */
        val startedAt: Long = 0L,
        /** How many runs this agent has started (the transcript holds one user message per run). */
        val runIndex: Int = 0,
        /** How many tool calls this run has made: the work it has done so far. */
        val toolUses: Int = 0,
        /** The file it lives in: the whole conversation is in it (the tail is only the end of it). */
        val file: File? = null,
        /** The run was cut off: the app (and the engine with it) died while it was working. */
        val interrupted: Boolean = false,
    )

    /**
     * The tasks folder of one parent session, or null when there is none.
     */
    fun taskDir(scratch: File, parentSessionId: String): File? {
        if (!scratch.isDirectory || parentSessionId.isBlank()) return null
        val roots = scratch.listFiles { f -> f.isDirectory && f.name.startsWith(ROOT) } ?: return null
        for (root in roots) {
            // <root>/<the encoded working directory>/<the session's id>/tasks
            val dirs = root.listFiles { f -> f.isDirectory } ?: continue
            for (dir in dirs) {
                val hit = File(dir, parentSessionId)
                val tasks = File(hit, "tasks")
                if (tasks.isDirectory) return tasks
            }
        }
        return null
    }

    /**
     * 某个 agent 的 transcript 在哪儿：它跑过的那些对话都在这个文件里。
     *
     * 被掐断的那一次运行没有自己的会话文件（引擎来不及写），它的对话与用量在这儿。
     */
    fun fileOf(scratch: File, parentSessionId: String, agentId: String): File? {
        if (agentId.isBlank()) return null
        val dir = taskDir(scratch, parentSessionId) ?: return null
        val file = File(dir, "$agentId.output")
        return if (file.isFile) file else null
    }

    /** The transcripts of one parent session, in the order the sub-agents were spawned. */
    fun of(scratch: File, parentSessionId: String, counter: RunCounter = RunCounter()): List<Transcript> {
        val dir = taskDir(scratch, parentSessionId) ?: return emptyList()
        val files = dir.listFiles { f -> f.isFile && f.name.endsWith(".output") } ?: return emptyList()
        return files.mapNotNull { file ->
            val messages = tail(file, MAX_LINES)
            if (messages.isEmpty()) return@mapNotNull null
            val counts = counter.count(file)
            Transcript(
                agentId = file.name.removeSuffix(".output"),
                // 最初那条任务（文件开头）：续跑时文件里留着上一轮的任务，头部才是这个 agent 的第一件事
                prompt = headPrompt(file) ?: textOf(messages.first()),
                messages = messages,
                lastWriteAt = file.lastModified(),
                runIndex = counts.runs,
                toolUses = counts.toolUses,
                file = file,
            )
        }.sortedBy { it.lastWriteAt }
    }

    /**
     * 文件开头那条任务：这个 agent 最初被派的那件事。
     *
     * 尾巴里没有它——一次长活干下来，尾部早就滚过去了；而续跑时文件里还留着上一轮的任务，
     * 所以只能从头找。
     */
    fun headPrompt(file: File): String? {
        if (!file.isFile) return null
        return runCatching {
            val size = file.length()
            if (size <= 0L) return null
            val want = minOf(size, HEAD_CHUNK.toLong()).toInt()
            val buffer = ByteArray(want)
            RandomAccessFile(file, "r").use { raf ->
                raf.seek(0)
                raf.readFully(buffer)
            }
            val line = String(buffer, Charsets.UTF_8).lineSequence().firstOrNull { it.isNotBlank() }
                ?: return null
            val entry = JSONObject(line)
            if (entry.optString("type") != "user") return null
            val message = entry.optJSONObject("message") ?: return null
            textOf(message).takeIf { it.isNotBlank() }
        }.getOrNull()
    }

    /**
     * The tail of a transcript: the last whole lines of the file.
     *
     * Only whole lines count — the first one may be cut in half when the file is bigger than the
     * chunk that was read. A line that does not parse is skipped: the file is being written while
     * it is read.
     */
    fun tail(file: File, maxLines: Int): List<JSONObject> {
        if (!file.isFile) return emptyList()
        val size = file.length()
        if (size <= 0L) return emptyList()
        val want = minOf(size, CHUNK.toLong()).toInt()
        val buffer = ByteArray(want)
        runCatching {
            RandomAccessFile(file, "r").use { raf ->
                raf.seek(size - want)
                raf.readFully(buffer)
            }
        }.onFailure { return emptyList() }
        val text = String(buffer, Charsets.UTF_8)
        val lines = text.split('\n')
        // a chunk that did not start at the file's beginning cut the first line in half
        val whole = if (want < size) lines.drop(1) else lines
        val parsed = whole.filter { it.isNotBlank() }.mapNotNull { line ->
            val entry = runCatching { JSONObject(line) }.getOrNull() ?: return@mapNotNull null
            entry.optJSONObject("message")
        }
        return if (parsed.size > maxLines) parsed.subList(parsed.size - maxLines, parsed.size) else parsed
    }

    /** Every message of a session file, in order. */
    fun messages(file: File): List<JSONObject> {
        if (!file.isFile) return emptyList()
        val out = mutableListOf<JSONObject>()
        runCatching {
            file.forEachLine { line ->
                val entry = runCatching { JSONObject(line) }.getOrNull() ?: return@forEachLine
                entry.optJSONObject("message")?.let { out.add(it) }
            }
        }
        return out
    }

    /**
     * 一个正在跑的子 Agent 当前这一步：它最后调的那个工具。
     *
     * 面板上要看得见它在干啥——「正在跑 log_triage.py」比「正在跑」有信息。
     */
    fun lastStep(messages: List<JSONObject>): String? {
        for (index in messages.indices.reversed()) {
            val parts = messages[index].optJSONArray("content") ?: continue
            for (i in parts.length() - 1 downTo 0) {
                val part = parts.optJSONObject(i) ?: continue
                if (part.optString("type") != "toolCall") continue
                val name = part.optString("name").ifBlank { "tool" }
                val args = part.optJSONObject("arguments")
                val hint = when (name) {
                    "bash" -> args?.optString("command")?.trim()?.lineSequence()?.firstOrNull()
                        ?.trim()?.take(40).orEmpty()
                    "read", "edit", "write" -> args?.optString("path")?.trim()
                        ?.substringAfterLast('/')?.take(40).orEmpty()
                    "grep" -> args?.optString("pattern")?.take(40).orEmpty()
                    else -> ""
                }
                return if (hint.isBlank()) name else "$name · $hint"
            }
        }
        return null
    }

    /** The words of one message, whichever shape its content has. */
    fun textOf(message: JSONObject): String {
        val content = message.opt("content")
        if (content is String) return content
        val parts = message.optJSONArray("content") ?: return ""
        val out = StringBuilder()
        for (i in 0 until parts.length()) {
            val part = parts.optJSONObject(i) ?: continue
            if (part.optString("type") == "text") out.append(part.optString("text"))
        }
        return out.toString()
    }
}

/**
 * 数一个 transcript 里有几轮、几次工具调用：user 消息一条 = 跑过一次。
 *
 * 增量读——文件长了才多读那一段。两秒一次的轮询不会把整份 transcript 重读一遍。
 *
 * 这个数是判断「有没有一次运行正在进行」的准数：跑完的每一次都留下一条记录，
 * 记录数比它少的那一次，就是还在跑的那一次。
 */
class RunCounter {

    /** 读到的位置：轮数、工具调用数、读过的字节、上一段末尾（跨段的记号靠它接上）。 */
    private data class State(
        val runs: Int,
        val toolCalls: Int,
        val read: Long,
        val carry: String,
        /** 每轮开始时的工具调用数：这一轮自己的调用数 = 总数 - 它前面那一轮的起点 */
        val boundaries: List<Int>,
    )

    /** What a transcript holds: the runs it started, and the tool calls of the newest one. */
    data class Counts(val runs: Int, val toolUses: Int)

    private val states = mutableMapOf<String, State>()

    /** 那个 agent 跑过几轮，这一轮用了多少次工具。 */
    fun count(file: File): Counts {
        if (!file.isFile) return Counts(0, 0)
        val state = states[file.path] ?: State(0, 0, 0L, "", emptyList())
        val length = file.length()
        // 文件被重写了（比读过的还短）：从头数
        if (length < state.read) {
            states[file.path] = State(0, 0, 0L, "", emptyList())
            return count(file)
        }
        var runs = state.runs
        var tools = state.toolCalls
        var read = state.read
        var carry = state.carry
        var boundaries = state.boundaries
        runCatching {
            RandomAccessFile(file, "r").use { raf ->
                raf.seek(read)
                val buffer = ByteArray(CHUNK)
                while (true) {
                    val n = raf.read(buffer)
                    if (n <= 0) break
                    val text = carry + String(buffer, 0, n, Charsets.UTF_8)
                    var i = 0
                    while (i < text.length) {
                        val user = text.indexOf(USER_MARK, i)
                        val tool = text.indexOf(TOOL_MARK, i)
                        if (user < 0 && tool < 0) break
                        if (tool < 0 || (user >= 0 && user < tool)) {
                            // 一轮开始：记下它从第几次工具调用起算
                            runs++
                            boundaries = boundaries + tools
                            i = user + USER_MARK.length
                        } else {
                            tools++
                            i = tool + TOOL_MARK.length
                        }
                    }
                    carry = text.takeLast(maxOf(USER_MARK.length, TOOL_MARK.length) - 1)
                    read += n
                }
            }
        }
        states[file.path] = State(runs, tools, read, carry, boundaries)
        val own = boundaries.getOrNull(runs - 1) ?: 0
        return Counts(runs, (tools - own).coerceAtLeast(0))
    }
}
