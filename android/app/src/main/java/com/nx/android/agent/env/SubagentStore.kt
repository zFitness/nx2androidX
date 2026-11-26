package com.nx.android.agent.env

import com.nx.android.agent.AgentSubagent
import com.nx.android.agent.AgentSubagentCall
import com.nx.android.agent.AgentTokenUsage
import com.nx.android.agent.usageOfMessages
import com.nx.android.agent.usageOfRunning
import com.nx.android.app.AppProcess
import com.nx.android.core.storage.AppPaths
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton
import org.json.JSONObject

/**
 * The sub-agents of one session: the runs that finished and the ones still going.
 *
 * Both come from the engine's own files — the records it writes into the session, and the
 * transcripts it streams while a sub-agent works. Nothing here talks to the engine.
 */
@Singleton
class SubagentStore @Inject constructor(
    private val paths: AppPaths,
) {

    /** What a finished run's own conversation said: the file's stamp and what was read out of it. */
    private val details = mutableMapOf<String, Pair<Long, Pair<String?, AgentTokenUsage>>>()

    /** 数 transcript 里有几轮：增量读，轮询时不会重读整份文件。 */
    private val counter = RunCounter()

    /** 正在跑的那一次从什么时候开始：第一次看见它的时候（文件一直在变，写入时刻不是开始）。 */
    private val liveSince = mutableMapOf<String, Long>()

    /** The finished runs of one session, oldest first. */
    fun records(sessionFile: String?): List<AgentSubagent> =
        if (sessionFile.isNullOrBlank()) emptyList() else SubagentRecords.of(File(sessionFile))

    /** The runs that are still going: their transcripts, as they are being written. */
    fun live(sessionFile: String?): List<SubagentTranscripts.Transcript> {
        val id = sessionIdOf(sessionFile) ?: return emptyList()
        return SubagentTranscripts.of(paths.tmp, id, counter).map { transcript ->
            val key = "${transcript.agentId}#${transcript.runIndex}"
            val since = liveSince.getOrPut(key) { transcript.lastWriteAt }
            transcript.copy(startedAt = since, interrupted = interrupted(transcript))
        }
    }

    /**
     * 这一次的运行是不是被掐断了。
     *
     * 掐断的样子：App 进程死了（被系统杀掉、玩家强制停止、App 升级），跟着一起死的还有
     * 引擎和它正在跑的那一次——transcript 停在那儿，永远不会再写一行，引擎也不会写记录
     * 收尾（记录是跑完时才写的）。
     *
     * 判据是「这份 transcript 最后一次写的时候，这个 App 进程还没起来」：比进程还老的东西
     * 是上一个进程留下的，活着的运行不会这样（引擎写的每一行都晚于进程起来的那一刻）。
     */
    private fun interrupted(transcript: SubagentTranscripts.Transcript): Boolean =
        SubagentRuns.interrupted(transcript.lastWriteAt, AppProcess.startedAt)

    /**
     * The list the player sees: the finished runs and the running ones, oldest first.
     *
     * The finished ones also carry what their own conversation says: the task they were given and
     * what they generated. That is how the run card in the conversation finds its run — the task
     * is the one thing both sides know.
     */
    fun list(sessionFile: String?, calls: List<AgentSubagentCall>): SubagentSnapshot {
        val records = records(sessionFile)
        val sessionId = sessionIdOf(sessionFile)
        // 同一个 agent 的第几次运行：记录按开始时刻排好，序号就是它
        val perAgent = records.groupBy { it.id }
        val finished = records.map { record ->
            val index = perAgent[record.id]?.indexOf(record) ?: 0
            val (prompt, usage) = detailsOf(record, index, sessionId)
            record.copy(prompt = prompt, usage = usage)
        }
        val runs = SubagentRuns.merge(finished, live(sessionFile), calls)
        val link = SubagentRuns.link(calls, runs)
        // 每一次运行显示它自己那次派生的任务描述：续跑那次说的是「实现」，不是上一轮的「诊断」
        val named = runs.map { run ->
            val call = link.byRun[run.runId] ?: return@map run
            run.copy(description = call.description.ifBlank { run.description })
        }
        return SubagentSnapshot(runs = named, byCall = link.byCall)
    }

    /**
     * A finished run's own words: the task it was given, what it generated, and what that cost.
     *
     * Read out of its own session file, and remembered: the file does not change once the run is
     * over, and the list is read again and again while the player watches it.
     *
     * A resumed agent has one session file for all its runs: the task is the file's first user
     * message, and what a run generated is what came after its own user message.
     *
     * 被掐断的那一次运行没有自己的会话文件（引擎来不及写）：它的对话与用量在 transcript 里。
     */
    private fun detailsOf(
        record: AgentSubagent,
        runIndex: Int,
        sessionId: String?,
    ): Pair<String?, AgentTokenUsage> {
        val path = record.sessionFile
            ?: sessionId?.let { SubagentTranscripts.fileOf(paths.tmp, it, record.id)?.path }
            ?: return null to AgentTokenUsage()
        val file = File(path)
        if (!file.isFile) return null to AgentTokenUsage()
        val stamp = file.lastModified()
        // 缓存按「第几次运行」分：同一个 agent 的两次运行共用一份会话文件，产出各不相同
        val key = "$path#$runIndex"
        val cached = details[key]
        if (cached != null && cached.first == stamp) return cached.second
        val messages = SubagentTranscripts.messages(file)
        val prompt = messages.firstOrNull { it.optString("role") == "user" }
            ?.let { SubagentTranscripts.textOf(it) }
            ?.takeIf { it.isNotBlank() }
        // 这一次运行自己的那些回答：它花了多少
        val usage = usageOfMessages(messages.drop(startOfRun(messages, runIndex)))
        val details = prompt to usage
        this.details[key] = stamp to details
        return details
    }

    /** Where a run's own messages start: after its user message (the file holds them all). */
    private fun startOfRun(messages: List<JSONObject>, runIndex: Int): Int {
        var seen = 0
        for (i in messages.indices) {
            if (messages[i].optString("role") != "user") continue
            if (seen == runIndex) return i + 1
            seen++
        }
        return 0
    }

    /**
     * The whole conversation of one sub-agent: its own session file when it has one, its
     * transcript while it is still running. Empty when neither can be read.
     *
     * A running agent's transcript is read **whole**: the tail of it is only the end (a long
     * run's task sits at the head, far outside the tail), and the conversation mapper needs
     * that first user message to make sense of the rest.
     */
    fun conversation(subagent: AgentSubagent, sessionFile: String?): List<JSONObject> {
        val own = subagent.sessionFile
        if (!own.isNullOrBlank()) {
            val messages = SubagentTranscripts.messages(File(own))
            if (messages.isNotEmpty()) return messages
        }
        val id = sessionIdOf(sessionFile) ?: return emptyList()
        val transcript = live(sessionFile).firstOrNull { it.agentId == subagent.id } ?: return emptyList()
        return SubagentConversations.ofRunning(transcript)
    }

    /** The session id in a session file's name: `<time>_<id>.jsonl`. */
    private fun sessionIdOf(path: String?): String? {
        if (path.isNullOrBlank()) return null
        val name = File(path).name.removeSuffix(".jsonl")
        val cut = name.lastIndexOf('_')
        if (cut < 0 || cut == name.length - 1) return null
        return name.substring(cut + 1)
    }
}

/**
 * How the finished runs and the running ones become one list, and which call started which run.
 *
 * A record is a **run**: the engine writes one when a run ends, and the same agent id shows up
 * once per run (a resumed agent runs again under the same id). So the runs of one agent are told
 * apart by their start, not by their id.
 *
 * A transcript is the agent's whole conversation so far — one user message per run. So the runs
 * that have *started* are the user messages, and the runs that have *ended* are the records:
 * whichever run has started but has no record yet is the one running right now.
 */
object SubagentRuns {

    /** 手劲：进程刚起来时那一秒写的东西不算「上一个进程留下的」。 */
    private const val STALE_SLACK_MS = 2_000L

    /**
     * 这一次的运行是不是被掐断了。
     *
     * App 进程死了（被系统杀掉、玩家强制停止、App 升级），跟着一起死的还有引擎和它正在跑
     * 的那一次：transcript 停在那儿，永远不会再写一行，引擎也不会写记录收尾。
     *
     * 判据：这份 transcript 最后一次写的时候，这个 App 进程还没起来——比进程还老的东西是
     * 上一个进程留下的，活着的运行不会这样。
     */
    fun interrupted(writtenAt: Long, processStartedAt: Long): Boolean {
        if (writtenAt <= 0L) return false
        return writtenAt < processStartedAt - STALE_SLACK_MS
    }

    /** The runs the player sees, oldest first. */
    fun merge(
        finished: List<AgentSubagent>,
        live: List<SubagentTranscripts.Transcript>,
        calls: List<AgentSubagentCall>,
    ): List<AgentSubagent> {
        val done = finished.sortedBy { it.startedAt }
        val running = live.mapNotNull { transcript ->
            val id = transcript.agentId
            val ended = done.count { it.id == id }
            // 跑过几轮 = transcript 里的 user 消息条数；跑完的每一次留下一条记录
            val started = transcript.runIndex
            // 跑过但还没记录的那一次，就是正在跑的那一次（续跑时它顶掉了上一轮的记录）
            if (started <= ended) return@mapNotNull null
            // 但 user 消息不只在一轮开始时才有：引擎在代理到达回合上限时注入一条让它收尾，
            // 中途 steer 也是一条——它们都属于已经跑完的那一轮，数数会多算一轮（2026-11-26
            // 一个已经跑完的代理在面板上转了六分钟的圈）。所以在跑的判据是时间：记录收尾
            // 之后 transcript 还在长，那一轮就还在跑。
            val lastEnd = done.filter { it.id == id }.mapNotNull { it.completedAt }.maxOrNull() ?: 0L
            if (lastEnd > 0L && transcript.lastWriteAt <= lastEnd) return@mapNotNull null
            val call = callFor(id, started, transcript, done, calls)
            AgentSubagent(
                id = id,
                runId = "$id#$started",
                type = call?.type.orEmpty(),
                description = call?.description?.takeIf { it.isNotBlank() }
                    ?: transcript.prompt.lineSequence().firstOrNull()?.trim().orEmpty(),
                // 被掐断的那一次不是「在跑」：它不会再动，也不会再有记录收尾
                status = if (transcript.interrupted) "interrupted" else "running",
                startedAt = transcript.startedAt.takeIf { it > 0 } ?: transcript.lastWriteAt,
                prompt = transcript.prompt,
                // 它当前这一步：面板上要看得见它在干啥
                step = SubagentTranscripts.lastStep(transcript.messages),
                // 它干了多少活：玩家不用发消息问「咋样」
                toolUses = transcript.toolUses,
                // 它到现在花了多少：尾巴里那些回答各自的用量
                usage = usageOfRunning(transcript.messages),
            )
        }
        return (done + running).sortedBy { it.startedAt }
    }

    /**
     * Which call started which run, both ways.
     *
     * The engine gives two handles: the tool call's own id, and — when a run continues an earlier
     * one — the agent id it continues. A first run is matched by its task (the one thing both
     * sides know); a continued run is matched by the call that pointed at its agent.
     */
    fun link(
        calls: List<AgentSubagentCall>,
        runs: List<AgentSubagent>,
    ): RunLink {
        val byCall = mutableMapOf<String, AgentSubagent>()
        val byRun = mutableMapOf<String, AgentSubagentCall>()
        val taken = mutableSetOf<String>()

        // 续跑的调用：那个 agent 的第 k 次运行对应第 k-1 个 resume 调用
        val resumes = calls.filter { !it.resumeId.isNullOrBlank() }
            .groupBy { it.resumeId!! }
        for ((agentId, agentCalls) in resumes) {
            val agentRuns = runs.filter { it.id == agentId }.sortedBy { it.startedAt }
            agentCalls.forEachIndexed { index, call ->
                // agentRuns[0] 是第一次运行——它没有 resume 调用，是第一次派生的
                val target = agentRuns.getOrNull(index + 1) ?: return@forEachIndexed
                if (target.runId in taken) return@forEachIndexed
                taken += target.runId
                call.toolCallId?.let { byCall[it] = target }
                byRun[target.runId] = call
            }
        }

        // 第一次运行的调用：任务那句话是它与调用之间唯一的联系
        for (call in calls) {
            if (!call.resumeId.isNullOrBlank()) continue
            val target = runs.firstOrNull {
                it.runId !in taken && !it.prompt.isNullOrBlank() && it.prompt == call.prompt
            } ?: continue
            taken += target.runId
            call.toolCallId?.let { byCall[it] = target }
            byRun[target.runId] = call
        }
        return RunLink(byCall, byRun)
    }

    /**
     * The call that started this run.
     *
     * A continued run (the second time an agent runs) is the one the resume call pointed at; the
     * first run is the one whose task matches the call's prompt.
     */
    private fun callFor(
        id: String,
        runIndex: Int,
        transcript: SubagentTranscripts.Transcript,
        done: List<AgentSubagent>,
        calls: List<AgentSubagentCall>,
    ): AgentSubagentCall? {
        if (runIndex > 1) {
            val resumes = calls.filter { it.resumeId == id }
            return resumes.getOrNull(runIndex - 2)
        }
        val head = transcript.prompt.takeIf { it.isNotBlank() }
            ?: done.firstOrNull { it.id == id }?.prompt
        return calls.firstOrNull { it.prompt.isNotBlank() && it.prompt == head }
    }
}

/** Which call started which run, both ways. */
data class RunLink(
    /** The tool call's id → the run it started. */
    val byCall: Map<String, AgentSubagent>,
    /** The run's id → the call that started it. */
    val byRun: Map<String, AgentSubagentCall>,
)

/**
 * The conversation of a sub-agent that is still running.
 *
 * Its transcript is read **whole**: the tail the app keeps for the panel is only the end of it,
 * and a long run's task sits at the head, far outside that tail. The mapper needs that first
 * user message — without it every later message is skipped and the view shows nothing.
 */
object SubagentConversations {

    /** Every message of a running agent's transcript, from the beginning. */
    fun ofRunning(transcript: SubagentTranscripts.Transcript): List<JSONObject> {
        val file = transcript.file ?: return transcript.messages
        val whole = SubagentTranscripts.messages(file)
        return if (whole.isNotEmpty()) whole else transcript.messages
    }
}

/** What the player sees of one session's sub-agents: the runs, and which call started which. */
data class SubagentSnapshot(
    /** Every run, oldest first: the finished ones and the ones still going. */
    val runs: List<AgentSubagent>,
    /** The tool call's id → the run it started (the card in the conversation looks itself up here). */
    val byCall: Map<String, AgentSubagent>,
)
