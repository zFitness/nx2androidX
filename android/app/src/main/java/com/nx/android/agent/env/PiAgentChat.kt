package com.nx.android.agent.env

import android.util.Log
import com.nx.android.BuildConfig
import com.nx.android.agent.AgentChat
import com.nx.android.agent.AgentEngineMissingException
import com.nx.android.agent.AgentEvent
import com.nx.android.agent.AgentFailure
import com.nx.android.agent.AgentHistory
import com.nx.android.agent.AgentMessage
import com.nx.android.agent.AgentModelConfig
import com.nx.android.agent.AgentSubagentCallParser
import com.nx.android.agent.AgentTokenUsage
import com.nx.android.agent.AgentToolCard
import com.nx.android.agent.AgentToolState
import com.nx.android.agent.sessionUsageOf
import com.nx.android.agent.runtime.AgentEngineStore
import com.nx.android.agent.runtime.AgentExtensions
import com.nx.android.agent.runtime.AgentSessionStore
import com.nx.android.agent.runtime.AgentSettingsStore
import com.nx.android.agent.runtime.AgentWorkspace
import com.nx.android.agent.runtime.composeTurn
import com.nx.android.agent.runtime.deviceState
import com.nx.android.agent.tools.AgentTools
import com.nx.android.domain.environment.GuestProcessLauncher
import java.io.File
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * The assistant's strong tier: the panel's own [AgentChat] face on the pi process (ADR-009).
 *
 * pi lives in the guest as a long-lived `--mode rpc` subprocess speaking JSONL over stdio; this
 * class is only the adapter. The event stream maps straight onto the events the panel already
 * renders — text deltas stream, tool calls show as cards, `agent_settled` closes the turn — so
 * the UI treats the two tiers exactly alike.
 *
 * The session store is shared with the light tier: a conversation followed across engines keeps
 * one rendered history, though each engine only knows the turns it answered itself.
 */
@Singleton
class PiAgentChat @Inject constructor(
    private val guest: GuestProcessLauncher,
    private val proxy: GuestProxy,
    private val settings: AgentSettingsStore,
    private val tools: AgentTools,
    private val workspace: AgentWorkspace,
    private val sessionStore: AgentSessionStore,
    private val catalog: PiSessionCatalog,
    private val engine: AgentEngineStore,
) : AgentChat {

    private companion object {
        const val TAG = "nx2a-agent-pi"
        const val DEVICE_STATE_CHARS = 600
        /** 中止之后等引擎说它闲下来的上限：引擎回话之前，尾巴事件都还在路上。 */
        const val ABORT_ACK_TIMEOUT_MS = 3_000L

        /** 等分诊器把总线上的残留归位：它做完了才开新的一轮。 */
        const val BARRIER_TIMEOUT_MS = 2_000L

        /** 一条 RPC 命令等回话的上限。 */
        const val RPC_TIMEOUT_MS = 8_000L

        /** 新会话的标题：玩家第一句话的前几个字。 */
        const val TITLE_CHARS = 16
    }

    @Volatile private var process: Process? = null
    @Volatile private var lineBus: Channel<BusItem>? = null
    @Volatile private var rpcBus: Channel<String>? = null
    @Volatile private var builtFor: String? = null

    /** 往引擎写命令的锁：两条命令不许交错的半行。 */
    private val writeLock = Any()

    /** 请求号：命令与回话的关联标记。 */
    private var requestSeq: Long = 0L

    /** 上次读到的历史（接口要用），与最近一次确认的会话文件（给新会话起名用）。 */
    private var loadedMessages: List<AgentMessage> = emptyList()
    private var lastSessionFile: String? = null

    /** 有一笔中止在途：下一轮开始前要等引擎确认它闲下来了。 */
    @Volatile private var abortPending: Boolean = false

    /** 引擎进程刚重生过：它手里没有会话，发问之前要切回玩家那一局。 */
    @Volatile private var respawned: Boolean = false

    /** The session's context occupancy and its model's window; live from the engine, zeroed on switch/new. */
    private var sessionTokens: Long = 0L
    private var sessionWindow: Long = 0L

    /** 这一局的累计用量：引擎那本账上的数（读历史时取一次，面板打开时再取一次）。 */
    @Volatile private var sessionUsage: AgentTokenUsage = AgentTokenUsage()

    /** pi's own session jsonl (from get_state) — the anchor the active pointer holds. */
    private var piSessionFile: String? = null

    /**
     * 轮外的事件：子 Agent 跑完的通知、主 Agent 在轮外写下的下文、上下文占用。
     *
     * 引擎在两轮之间也会说话（后台子 Agent 完成后，它把通知注入会话，主 Agent 随即
     * 写一段总结）——这些事件到的时候没有轮在跑，App 照样得看得见。
     */
    private val background = MutableSharedFlow<AgentEvent>(extraBufferCapacity = 64)

    /** 中止的回话：等它的人在这里拿。 */
    @Volatile private var abortAck: CompletableDeferred<Unit>? = null

    /** 分诊协程：引擎总线的唯一消费者。 */
    private var demuxer: Job? = null

    /** 这一轮：轮内的事件进它的口，轮外的走后台流。 */
    @Volatile private var activeTurn: TurnState? = null

    /**
     * 分诊与发问之间的握手锁。
     *
     * 引擎一轮只跑一个；App 那一轮是「提示写出去之后的第一个引擎轮次」——
     * 这件事要跟分诊器商量好，不能各说各的。
     */
    private val routeLock = Any()

    /** 引擎这一轮正在跑。 */
    @Volatile private var engineTurnActive = false

    /** 引擎轮次的计数：每收尾一次加一（轮次从 0 数起）。 */
    @Volatile private var engineSettleCount = 0L

    /** 引擎正在跑的这一轮，是 App 的那一轮吗。 */
    @Volatile private var engineTurnIsApp = false

    /** App 那一轮排在第几个引擎轮次（-1 = 没有待着的）。 */
    @Volatile private var appTurnIndex = -1L

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    /** 总线上的一件东西：引擎的一行，或者一道栅栏（等分诊器把前面的行都处理完）。 */
    private sealed interface BusItem {
        data class Line(val text: String) : BusItem
        data class Barrier(val ack: CompletableDeferred<Unit>) : BusItem
    }

    /** 总线上的事件：要么是给 App 的，要么是「这一轮收尾了」。 */
    private sealed interface EngineEvent {
        data class For(val event: AgentEvent) : EngineEvent
        data class Settled(val tokens: Long) : EngineEvent
    }

    /** 一轮的状态：这一轮的事件口、这一轮的回答与账。 */
    private class TurnState {
        val events = Channel<EngineEvent>(Channel.UNLIMITED)
        val ledger = TurnLedger()
        val answer = StringBuilder()
        @Volatile var settled = false
    }

    /** 分诊器的账：这一轮占用了多少上下文、生成了多少 token。 */
    private class TurnLedger {
        var context: Long = 0L
        var output: Long = 0L
        var endOutput: Long = 0L
        fun reset() { context = 0L; output = 0L; endOutput = 0L }
        val tokens: Long get() = if (output > 0L) output else endOutput
    }

    init {
        workspace.ensure()
    }

    override val messages: List<AgentMessage> get() = loadedMessages

    override val backgroundEvents: Flow<AgentEvent> get() = background

    /** A hard reset is the new-session semantic: a fresh engine session, empty history, process stays. */
    override fun reset() {
        newSession()
    }

    /**
     * 中止当前这一轮：清掉排队的消息，再让引擎停下手里的活。
     *
     * 引擎进程留着——下一轮接着用同一段上下文。命令从后台线程写，不挡着界面。
     */
    override fun abort() {
        abortPending = true   // 先把「有中止在途」记上：下一轮开始前要等引擎的回话
        abortAck = CompletableDeferred()
        Thread({
            writeCommand(JSONObject().put("type", "clear_queue"))
            writeCommand(JSONObject().put("type", "abort"))
            Log.d(TAG, "abort sent")
        }, "pi-abort").apply { isDaemon = true }.start()
    }

    /** A fresh conversation: the engine's context resets; the file itself is created at the first prompt. */
    fun newSession(): String {
        if (process?.isAlive == true) {
            Thread({
                runCatching { writeCommand(JSONObject().put("id", "new-$$").put("type", "new_session")) }
            }, "pi-new-session").apply { isDaemon = true }.start()
        }
        sessionStore.clearActive()
        lastSessionFile = null
        piSessionFile = null
        loadedMessages = emptyList()
        sessionTokens = 0L
        sessionWindow = 0L
        sessionUsage = AgentTokenUsage()
        return ""
    }

    /**
     * 读历史（冷启动、切换、下拉选择共用）：引擎起来 → 切到目标会话（指针的，或指定的）→
     * 取回消息与状态。进程新起时若不先切，第一轮会开一个新会话文件——所以永远先切再读。
     */
    override suspend fun history(prefer: String?): Result<AgentHistory> = withContext(Dispatchers.IO) {
        val config = settings.config
        if (!config.configured) return@withContext Result.failure(IllegalStateException("模型还没有配置"))
        if (!engine.installed) return@withContext Result.failure(AgentEngineMissingException())

        val bus = try {
            ensureProcess(config)
        } catch (e: Exception) {
            return@withContext Result.failure(e)
        }
        // 目标：指定的（下拉选择）→ 指针的（还在盘上才算）→ 最新的一段
        val target = prefer
            ?: sessionStore.activePath()?.takeIf { File(it).isFile }
            ?: catalog.list().firstOrNull()?.path
        if (target != null) {
            val switched = rpc(JSONObject().put("type", "switch_session").put("sessionPath", target))
            Log.d(TAG, "switch: ${switched?.optBoolean("success")}")
            if (switched == null) return@withContext Result.failure(IllegalStateException("切换会话没有回话"))
        }

        val state = rpc(JSONObject().put("type", "get_state"))
            ?: return@withContext Result.failure(IllegalStateException("引擎没有回话"))
        val file = state.optJSONObject("data")?.optString("sessionFile").orEmpty()
        val title = state.optJSONObject("data")?.optString("sessionName").orEmpty()

        val stats = rpc(JSONObject().put("type", "get_session_stats"))
        val data = stats?.optJSONObject("data")
        val usage = data?.optJSONObject("contextUsage")
        sessionTokens = usage?.optLong("tokens", 0L) ?: 0L
        sessionWindow = usage?.optLong("contextWindow", 0L) ?: 0L
        // 这一局花了多少：引擎那本账上的累计（App 只把它显示出来）
        sessionUsage = sessionUsageOf(data)
        if (sessionWindow <= 0) {
            state.optJSONObject("data")?.optJSONObject("model")?.optLong("contextWindow")?.takeIf { it > 0 }
                ?.let { sessionWindow = it }
        }

        val raw = rpc(JSONObject().put("type", "get_messages"))
            ?.optJSONObject("data")?.optJSONArray("messages")
            ?: return@withContext Result.failure(IllegalStateException("取不到会话内容"))
        val history = ArrayList<JSONObject>(raw.length())
        for (i in 0 until raw.length()) raw.optJSONObject(i)?.let { history.add(it) }
        loadedMessages = PiHistoryMapper.map(history)
        Log.d(TAG, "messages: ${raw.length()} mapped: ${loadedMessages.size}")

        if (file.isNotBlank()) {
            piSessionFile = file
            lastSessionFile = file
            sessionStore.setActive(file)   // 指针跟着真实读取落到的地方
        }

        Result.success(
            AgentHistory(
                messages = loadedMessages,
                sessionFile = file,
                title = title,
                contextTokens = sessionTokens,
                contextWindow = sessionWindow,
                usage = sessionUsage,
            ),
        )
    }

    /**
     * 这一局到现在花了多少：引擎那本账上的累计（面板打开时拉一次，拿到的是当下的）。
     *
     * 不在 App 那边累加自己收到的事件——那样重开一次 App 就会少算（引擎的账本含已被
     * 压缩掉的历史）。
     */
    override suspend fun usage(): AgentTokenUsage {
        val stats = rpc(JSONObject().put("type", "get_session_stats")) ?: return AgentTokenUsage()
        val usage = sessionUsageOf(stats.optJSONObject("data"))
        sessionUsage = usage
        return usage
    }

    /**
     * 一问一答式的 RPC：带上请求号写命令，从回话通道等那条回应（其余的行不归它管）。
     * 回话与事件走两条通道，所以读历史与跑一轮可以同时发生。
     */
    private suspend fun rpc(cmd: JSONObject): JSONObject? {
        val id = "rpc-${++requestSeq}"
        cmd.put("id", id)
        withContext(Dispatchers.IO) { writeCommand(cmd) }
        val replies = rpcBus ?: return null
        return withTimeoutOrNull(RPC_TIMEOUT_MS) {
            for (line in replies) {
                val obj = runCatching { JSONObject(line) }.getOrNull() ?: continue
                if (obj.optString("id") == id) return@withTimeoutOrNull obj
            }
            null
        }
    }

    override suspend fun send(userText: String): Flow<AgentEvent> = channelFlow {
        val config = settings.config
        if (!config.configured) { send(AgentEvent.Failed(AgentFailure.NO_KEY)); return@channelFlow }

        val bus = try {
            ensureProcess(config)
        } catch (e: Exception) {
            send(AgentEvent.Failed(classify(e))); return@channelFlow
        }
        // The engine was just reborn (the player changed the model or the key, or it died): it
        // holds no session, and the prompt below would open a new one — the player would lose
        // the conversation (and the spawn results the interruption rules need) without a word.
        // So it goes back to the player's own session first.
        if (respawned) {
            respawned = false
            val back = sessionStore.activePath()?.takeIf { File(it).isFile }
                ?: lastSessionFile?.takeIf { File(it).isFile }
            if (back != null) {
                val switched = rpc(JSONObject().put("type", "switch_session").put("sessionPath", back))
                Log.d(TAG, "switch back after the engine restarted: ${switched?.optBoolean("success")}")
            }
        }
        // 中止在途：等引擎说它闲下来了，这一轮的尾巴才收干净
        awaitIdle()
        // 总线上还压着的行先归位：那是轮外的事（上一轮的后话），不能算成这一轮的
        drain(bus)
        // the state ride-along: the model's context window + pi's own session file, for free
        withContext(Dispatchers.IO) {
            writeCommand(JSONObject().put("id", "state-$$").put("type", "get_state"))
        }

        val composed = composeTurn(
            userText,
            workspace.readMemory(),
            deviceState = deviceState(
                BuildConfig.VERSION_NAME,
                tools.libraryStatus(),
                DEVICE_STATE_CHARS,
            ),
        )

        val turn = TurnState()
        synchronized(routeLock) {
            // 这一轮排在第几个引擎轮次：引擎正忙着就排它后面，空着就是下一个
            appTurnIndex = engineSettleCount + if (engineTurnActive) 1L else 0L
            activeTurn = turn
        }
        var died = false
        try {
            withContext(Dispatchers.IO) {
                writeCommand(
                    JSONObject()
                        .put("id", "req-${++requestSeq}")
                        .put("type", "prompt")
                        .put("message", composed),
                )
            }
            for (ev in turn.events) {
                when (ev) {
                    is EngineEvent.For -> send(ev.event)
                    is EngineEvent.Settled -> break
                }
            }
        } catch (e: CancellationException) {
            // 玩家按了停止：引擎自己把这一轮（含已写出的部分）收进它的会话，App 不用补
            throw e
        } catch (e: Exception) {
            Log.d(TAG, "turn failed: $e")
            if (!turn.settled && turn.answer.isEmpty()) {
                // the process died mid-turn: the next turn respawns it
                kill()
                send(AgentEvent.Failed(AgentFailure.LOOP_ERROR))
                died = true
            }
        } finally {
            synchronized(routeLock) {
                if (activeTurn === turn) activeTurn = null
            }
        }
        if (died) return@channelFlow

        sessionTokens = maxOf(sessionTokens, turn.ledger.context)
        // 轮次收尾，引擎闲下来了：问一次它现在在哪个会话文件（新会话的第一问会开新文件）。
        // 名字与指针都在这里落：新会话写上名字（玩家第一句话的前 16 字），指针指过去。
        withContext(Dispatchers.IO) {
            val state = rpc(JSONObject().put("type", "get_state"))
            val file = state?.optJSONObject("data")?.optString("sessionFile").orEmpty()
            if (file.isNotBlank() && file != lastSessionFile) {
                lastSessionFile = file
                piSessionFile = file
                sessionStore.setActive(file)
                writeCommand(
                    JSONObject().put("type", "set_session_name").put("name", userText.take(TITLE_CHARS)),
                )
            }
        }
        send(AgentEvent.TurnDone(turn.answer.toString().trim(), turn.ledger.tokens))
    }

    /**
     * 等引擎闲下来。
     *
     * 中止命令是引擎确认「这一轮停了、我闲了」才回话的：它回话之前，这一轮的尾巴事件
     * （最后几个字、收尾）都还在路上。不等它就开下一轮，那些尾巴会算到下一轮头上。
     *
     * 回话由分诊器认（总线的行只它读）：它认出来了，这边等着的人就醒了。
     */
    private suspend fun awaitIdle() {
        if (!abortPending) return
        abortPending = false
        val ack = abortAck
        abortAck = null
        if (ack != null) withTimeoutOrNull(ABORT_ACK_TIMEOUT_MS) { ack.await() }
    }

    /**
     * 总线上还压着的行先归位：分诊器把它们处理完（那是轮外的事），这一轮才算真的开始。
     *
     * 栅栏是排进总线里的，所以它一定排在那些行后面——分诊器做完它们才轮到栅栏。
     */
    private suspend fun drain(bus: Channel<BusItem>) {
        val ack = CompletableDeferred<Unit>()
        if (!bus.trySend(BusItem.Barrier(ack)).isSuccess) return
        withTimeoutOrNull(BARRIER_TIMEOUT_MS) { ack.await() }
    }

    /**
     * 分诊器：引擎总线的唯一消费者。
     *
     * 引擎在两轮之间也会说话：后台子 Agent 跑完了，它把通知注入会话，主 Agent 随即写一段
     * 总结。以前这些行没人读——下一轮开始时又被清掉，玩家只有重开才看得见。
     *
     * 现在总线的行只在这里读一次：轮内的进这一轮的口，轮外的进后台流。
     */
    private fun startDemuxer(bus: Channel<BusItem>) {
        demuxer?.cancel()
        demuxer = scope.launch {
            val backgroundAnswer = StringBuilder()
            val backgroundLedger = TurnLedger()
            for (item in bus) {
                when (item) {
                    is BusItem.Line -> route(item.text, backgroundAnswer, backgroundLedger)
                    is BusItem.Barrier -> {
                        // 总线上还压着的行：轮子开之前先归位（它们是轮外的事）
                        while (true) {
                            val extra = bus.tryReceive().getOrNull() ?: break
                            if (extra is BusItem.Line) {
                                route(extra.text, backgroundAnswer, backgroundLedger)
                            }
                        }
                        item.ack.complete(Unit)
                    }
                }
            }
        }
    }

    /**
     * 总线上一行：解析一次，然后按「轮内还是轮外」分家。
     *
     * 轮内的事件进这一轮的口（这一轮的回答与账都在那儿记）；轮外的进后台流——玩家在
     * 那一刻没有问，但引擎在说话（子 Agent 跑完了，主 Agent 接着讲），那也得看得见。
     *
     * 谁是谁：引擎一轮只跑一个，App 那一轮是「提示写出去之后的第一个引擎轮次」。
     * 分诊器数着引擎轮次（每收尾一次加一），App 在提示写出去的那一刻记下自己排在第几个，
     * 两者对上了，这一轮才是 App 的。对不上就是轮外——玩家的那段话照样看得见。
     */
    private fun route(
        line: String,
        backgroundAnswer: StringBuilder,
        backgroundLedger: TurnLedger,
    ) {
        val obj = runCatching { JSONObject(line) }.getOrNull() ?: return
        // 中止的回话：等它的人在那头拿
        if (obj.optString("type") == "response" && obj.optString("command") == "abort") {
            abortAck?.complete(Unit)
            return
        }
        val parsed = parse(obj)
        synchronized(routeLock) {
            // 一个引擎轮次开始了：它是 App 的那一轮吗
            if (parsed.turnStart && !engineTurnActive) {
                engineTurnActive = true
                engineTurnIsApp = appTurnIndex == engineSettleCount
                if (engineTurnIsApp) appTurnIndex = -1L
            }
            val turn = activeTurn
            val appTurn = engineTurnIsApp && turn != null && !turn.settled
            if (appTurn) {
                if (parsed.seen > turn.ledger.context) {
                    turn.ledger.context = parsed.seen
                    parsed.events.add(
                        0, AgentEvent.UsageUpdated(occupancy(turn.ledger.context), sessionWindow),
                    )
                }
                if (parsed.output > 0L) turn.ledger.output += parsed.output
                if (parsed.endOutput > 0L) turn.ledger.endOutput = parsed.endOutput
                for (e in parsed.events) {
                    if (e is AgentEvent.TextDelta) turn.answer.append(e.text)
                    turn.events.trySend(EngineEvent.For(e))
                }
            } else {
                // 轮外：主 Agent 在没有玩家提问的时候写下的下文
                if (parsed.seen > backgroundLedger.context) {
                    backgroundLedger.context = parsed.seen
                    parsed.events.add(
                        0, AgentEvent.UsageUpdated(occupancy(backgroundLedger.context), sessionWindow),
                    )
                }
                if (parsed.output > 0L) backgroundLedger.output += parsed.output
                if (parsed.endOutput > 0L) backgroundLedger.endOutput = parsed.endOutput
                for (e in parsed.events) {
                    if (e is AgentEvent.TextDelta) backgroundAnswer.append(e.text)
                    background.tryEmit(e)
                }
            }
            // 这一轮到此为止：App 的那一轮交给等它的人，轮外的收成一条消息
            if (parsed.settled || parsed.failed) {
                val wasAppTurn = engineTurnIsApp
                val claim = wasAppTurn || appTurnIndex == engineSettleCount
                if (claim) {
                    appTurnIndex = -1L
                    val t = activeTurn
                    if (t != null && !t.settled) {
                        t.settled = true
                        t.events.trySend(EngineEvent.Settled(t.ledger.tokens))
                    }
                }
                if (!wasAppTurn) {
                    // 轮外那一轮写完了：它自己是一条消息
                    background.tryEmit(
                        AgentEvent.FollowUp(backgroundAnswer.toString().trim(), backgroundLedger.tokens),
                    )
                    backgroundAnswer.setLength(0)
                    backgroundLedger.reset()
                }
                engineSettleCount++
                engineTurnActive = false
                engineTurnIsApp = false
            }
        }
    }

    /** 总线上一行解析出来的东西。 */
    private class Parsed {
        val events = ArrayList<AgentEvent>(2)
        /** 这一轮到此为止。 */
        var settled = false
        /** 引擎报了这个命令失败：这一轮也该收尾（不然它等不到收尾的话）。 */
        var failed = false
        /** 这一行是一个引擎轮次里的东西（不是命令的回话）。 */
        var turnStart = false
        /** 这一条消息看到的上下文占用（0 = 引擎没报）。 */
        var seen = 0L
        /** 这一条消息生成的 token。 */
        var output = 0L
        /** 整轮那一条生成的 token。 */
        var endOutput = 0L
    }

    /**
     * 会话占了多少上下文：同一个口径的两个读数，取大的那个。
     *
     * [sessionTokens] 是读历史时引擎报的占用，这一轮自己看到的 [seen]（input + cacheRead +
     * output）本来就把整段对话算在里面了——两个数相加是把会话数了两遍（读过历史再提问，
     * 面板头部显示的是真实占用的两倍）。取大的那个：占用只涨不跌（引擎压缩旧轮次时会掉，
     * 但那不值得在面板上抖一下）。
     */
    private fun occupancy(seen: Long): Long = maxOf(sessionTokens, seen)

    /** 总线上一行 -> App 看得懂的事。解析只做一次：轮内轮外共用这一份。 */
    private fun parse(obj: JSONObject): Parsed {
        val p = Parsed()
        when (obj.optString("type")) {
            "response" -> if (obj.optString("command") == "get_state") {
                val data = obj.optJSONObject("data")
                data?.optJSONObject("model")?.optLong("contextWindow")?.takeIf { it > 0 }?.let {
                    sessionWindow = it
                }
                data?.optString("sessionFile")?.takeIf { it.isNotBlank() }?.let {
                    piSessionFile = it
                }
            } else if (!obj.optBoolean("success", true)) {
                Log.d(TAG, "command failed: ${obj.optString("error").take(200)}")
                p.failed = true
                p.events.add(AgentEvent.Failed(classify(RuntimeException(obj.optString("error")))))
            }

            "message_update" -> {
                p.turnStart = true
                obj.optJSONObject("usage")?.let { usage ->
                    // the latest call saw the whole conversation: its input + produced output
                    // IS the current context occupancy — monotonic, never a zero snapshot
                    p.seen = usage.optLong("input") + usage.optLong("cacheRead") +
                        usage.optLong("output")
                }
                val ev = obj.optJSONObject("assistantMessageEvent") ?: return p
                when (ev.optString("type")) {
                    "text_delta" -> {
                        val delta = ev.optString("delta", "")
                        if (delta.isNotEmpty()) p.events.add(AgentEvent.TextDelta(delta))
                    }
                    // 思考过程：模型自己想的那一段（不是回答）。它照样流出来，
                    // 面板把它折起来——玩家想看就看，不想看就不占地方。
                    "thinking_delta" -> {
                        val delta = ev.optString("delta", "")
                        if (delta.isNotEmpty()) p.events.add(AgentEvent.ThinkingDelta(delta))
                    }
                }
            }

            "tool_execution_start" -> {
                p.turnStart = true
                val name = obj.optString("toolName")
                val args = obj.optJSONObject("args")
                val toolCallId = obj.optString("toolCallId")
                val call = AgentSubagentCallParser.of(name, args, toolCallId)
                p.events.add(
                    AgentEvent.ToolStarted(
                        AgentToolCard(
                            id = toolCallId,
                            name = name,
                            argsSummary = if (call != null) {
                                call.description.ifBlank { call.type }
                            } else {
                                args?.toString()?.take(60) ?: ""
                            },
                            state = AgentToolState.RUNNING,
                            subagent = call,
                        ),
                    ),
                )
            }

            "tool_execution_end" -> {
                p.turnStart = true
                val resultText = obj.optJSONObject("result")
                    ?.optJSONArray("content")?.optJSONObject(0)?.optString("text") ?: ""
                p.events.add(
                    AgentEvent.ToolFinished(
                        obj.optString("toolCallId"),
                        if (obj.optBoolean("isError")) AgentToolState.FAILED else AgentToolState.DONE,
                        resultText.take(80),
                    ),
                )
            }

            "message_end" -> {
                p.turnStart = true
                val message = obj.optJSONObject("message")
                // 子 Agent 跑完了：引擎发来一条自己的消息，正文是那份通知
                if (message != null &&
                    message.optString("role") == "custom" &&
                    message.optString("customType") == SubagentNotifications.MESSAGE_TYPE
                ) {
                    SubagentNotifications.parse(SubagentTranscripts.textOf(message))
                        ?.let { p.events.add(AgentEvent.Notification(it)) }
                }
                message?.optJSONObject("usage")?.let { usage ->
                    p.seen = usage.optLong("input") + usage.optLong("cacheRead") +
                        usage.optLong("output")
                    // 这一条消息生成了多少：这一轮的回答要报自己的消耗
                    p.output = usage.optLong("output")
                }
            }

            "turn_end" -> {
                p.turnStart = true
                obj.optJSONObject("message")?.optJSONObject("usage")?.let { usage ->
                    p.seen = usage.optLong("input") + usage.optLong("cacheRead") +
                        usage.optLong("output")
                    p.endOutput = usage.optLong("output")
                }
            }

            "agent_settled" -> p.settled = true
        }
        return p
    }

    /**
     * The long-lived rpc process; a config change respawns it on the next turn.
     *
     * A respawned process holds no session: its first prompt opens a new session file, and the
     * player would lose the conversation without noticing (the UI shows what it always shows).
     * The flag tells the caller to switch back to the player's session before that prompt.
     */
    @Synchronized
    private fun ensureProcess(config: AgentModelConfig): Channel<BusItem> {
        val fingerprint = "${config.baseUrl}|${config.modelName}|${config.apiKey.hashCode()}"
        if (process?.isAlive == true && builtFor == fingerprint) return checkNotNull(lineBus)
        kill()
        respawned = true

        val base = guest.guestEnv()
        val nx2a = File(requireNotNull(base["NX2A_HOME"]) { "NX2A_HOME is not set in the guest env" })
        val binary = engine.binary
        check(binary.isFile) { "pi 没有安装（nx2a/agent/runtime/pi 不存在）" }

        val port = proxy.ensure()

        // the providers pi does not know by itself (glm through bigmodel.cn, doubao, an endpoint
        // of the player's own) are declared in the engine's models.json
        PiCatalog.modelsJson(config)?.let { json ->
            val piHome = File(engine.home, ".pi/agent")
            piHome.mkdirs()
            File(piHome, "models.json").writeText(json)
        }

        // the extensions the installed package carries are pointed at before the engine starts:
        // it reads its settings when it comes up, not later
        AgentExtensions.enable(engine.home, engine.runtimeDir, engine.installedExtensions())
        // the material is planted before the engine starts too: it reads its agreement, its skills
        // and its agent definitions when it comes up
        workspace.ensure()

        val pb = ProcessBuilder(
            listOf(
                binary.absolutePath, "--mode", "rpc",
                "--model", PiCatalog.fullModelId(config),
            ),
        ).directory(nx2a)
        // stdout is the protocol, stderr is diagnostics; blending them would corrupt the stream
        pb.redirectErrorStream(false)
        pb.environment().putAll(base)
        // the engine's home is the assistant's own folder: its models.json, its sessions and its
        // state stay there, and the environment's reset does not touch them
        pb.environment()["HOME"] = engine.home.absolutePath
        pb.environment()["http_proxy"] = "http://127.0.0.1:$port"
        pb.environment()["https_proxy"] = pb.environment()["http_proxy"] ?: ""
        pb.environment()["TERM"] = "dumb"
        val (keyName, keyValue) = PiCatalog.keyEnv(config.providerId, config.apiKey)
        pb.environment()[keyName] = keyValue

        val p = pb.start()
        val bus = Channel<BusItem>(capacity = Channel.UNLIMITED)
        // 回话走自己那条通道（读历史时用），其余事件走事件总线：分开走，两边才不会
        // 互相抢对方的行（读历史与跑一轮可以同时发生）。
        val replies = Channel<String>(capacity = Channel.UNLIMITED)
        rpcBus = replies
        // 读引擎输出的两个线程：管道被拆的时候（进程被杀或重建）读会抛 IO 异常。
        // 那是正常收场，不是错误——让它逃出去就是 App 进程自杀。
        Thread({
            try {
                p.inputStream.use { stream ->
                    stream.reader(Charsets.UTF_8).buffered().useLines { lines ->
                        lines.forEach { line ->
                            if (isRpcReply(line)) replies.trySend(line) else bus.trySend(BusItem.Line(line))
                        }
                    }
                }
            } catch (e: IOException) {
                Log.d(TAG, "rpc stdout closed: ${e.message}")
            } finally {
                bus.close()
                replies.close()
            }
        }, "pi-rpc-reader").apply { isDaemon = true }.start()
        Thread({
            try {
                p.errorStream.use { stream ->
                    stream.reader(Charsets.UTF_8).forEachLine { Log.d(TAG, it.take(200)) }
                }
            } catch (e: IOException) {
                Log.d(TAG, "rpc stderr closed: ${e.message}")
            }
        }, "pi-rpc-stderr").apply { isDaemon = true }.start()

        process = p
        lineBus = bus
        builtFor = fingerprint
        // 总线的行只它读：轮内的进这一轮的口，轮外的进后台流
        startDemuxer(bus)
        return bus
    }

    /** 这一行是我们自己问出去的那条命令的回话吗（请求号以 rpc- 开头）。 */
    private fun isRpcReply(line: String): Boolean =
        runCatching { JSONObject(line).optString("id").startsWith("rpc-") }.getOrDefault(false)

    /**
     * 往引擎写一条命令。
     *
     * 写锁：两条命令不许交错的半行。写向已经走了的进程会抛 IO 异常——记一笔，不当错误。
     */
    private fun writeCommand(cmd: JSONObject) {
        val line = cmd.toString() + "\n"
        synchronized(writeLock) {
            val proc = process ?: return
            runCatching {
                proc.outputStream.write(line.toByteArray(Charsets.UTF_8))
                proc.outputStream.flush()
            }.onFailure { Log.d(TAG, "write failed: ${it.message}") }
        }
    }

    @Synchronized
    private fun kill() {
        process?.let { p ->
            runCatching { p.outputStream.close() }   // the orderly shutdown request
            runCatching { p.destroy() }
        }
        demuxer?.cancel()
        demuxer = null
        lineBus?.close()
        rpcBus?.close()
        process = null
        lineBus = null
        rpcBus = null
        builtFor = null
        abortPending = false   // 进程都没了，没有中止要等了
        abortAck?.cancel()
        abortAck = null
        synchronized(routeLock) {
            activeTurn = null
            appTurnIndex = -1L
            engineTurnActive = false
            engineTurnIsApp = false
        }
    }

    private fun classify(error: Exception): AgentFailure = when {
        error.message?.contains("401") == true || error.message?.contains("403") == true -> AgentFailure.BAD_KEY
        error is java.io.IOException -> AgentFailure.NETWORK
        else -> AgentFailure.LOOP_ERROR
    }
}

/** The provider facts both pi entry points share: the catalog's model id and the key's env var. */
internal object PiCatalog {

    /**
     * The context windows pi's own catalog reports for the models our presets offer — seeded from
     * `pi --list-models`. The runtime corrects them with pi's get_state once a process is up;
     * before that, the static value is what the head and the ring need to show a percent on
     * first open.
     */
    private val CONTEXT_WINDOWS: Map<String, Long> = mapOf(
        "minimax-cn/MiniMax-M3.1-Flash" to 1_048_576L,
        "minimax-cn/MiniMax-M3" to 1_048_576L,
        "minimax-cn/MiniMax-M2.7" to 204_800L,
        "minimax-cn/MiniMax-M2.1" to 204_800L,
        "minimax-cn/MiniMax-M2" to 204_800L,
        "deepseek/deepseek-chat" to 131_072L,
        "deepseek/deepseek-reasoner" to 131_072L,
        "moonshotai-cn/kimi-latest" to 262_144L,
        "zhipu/glm-4.6" to 204_800L,
        "zhipu/glm-4.5" to 131_072L,
    )

    fun contextWindowFor(fullModelId: String): Long = CONTEXT_WINDOWS[fullModelId] ?: 0L

    /**
     * The name the provider carries in the models.json and in the model id.
     *
     * These are the names pi's own catalog uses: a model is looked up by the pair (provider, id),
     * so a name of our own would not be found. Kimi's name is `moonshotai-cn`, not `moonshot`.
     */
    fun providerKey(providerId: String): String = when (providerId) {
        "glm" -> "zhipu"
        "minimax" -> "minimax-cn"
        "kimi" -> "moonshotai-cn"
        else -> providerId
    }

    /**
     * The providers pi knows by itself: the endpoint and the list of models are its business, and
     * the player only brings the key.
     *
     * This is the one place that knows it — the dialog hides the endpoint for these, and the
     * models.json is not written for them.
     */
    fun engineManaged(providerId: String): Boolean = providerId in ENGINE_MANAGED

    /** The providers pi's own catalog carries. */
    private val ENGINE_MANAGED = setOf("minimax", "deepseek", "kimi")

    fun fullModelId(config: AgentModelConfig): String =
        if (config.modelName.contains('/')) config.modelName
        else "${providerKey(config.providerId)}/${config.modelName}"

    fun keyEnv(providerId: String, key: String): Pair<String, String> = when (providerId) {
        "minimax" -> "MINIMAX_CN_API_KEY" to key
        "glm" -> "ZHIPU_API_KEY" to key
        "deepseek" -> "DEEPSEEK_API_KEY" to key
        "kimi" -> "MOONSHOT_API_KEY" to key
        "doubao" -> "ARK_API_KEY" to key
        else -> "OPENAI_API_KEY" to key
    }

    /**
     * The models.json a provider of ours needs: pi knows some providers by itself, the others
     * (glm through bigmodel.cn, doubao, an endpoint of the player's own) are declared here — the
     * endpoint, the key's env var and the model the player picked.
     *
     * The model that goes in is the one this profile names, not a list of our own: a model pi does
     * not know is a model pi cannot run.
     *
     * Null when pi knows the provider by itself.
     */
    fun modelsJson(config: AgentModelConfig): String? {
        if (engineManaged(config.providerId)) return null
        val key = providerKey(config.providerId)
        val (envName, _) = keyEnv(config.providerId, config.apiKey)
        val window = contextWindowFor("$key/${config.modelName}")
        val model = if (window > 0) """{ "id": "${config.modelName}", "contextWindow": $window }"""
        else """{ "id": "${config.modelName}" }"""
        return """
            {
              "providers": {
                "$key": {
                  "baseUrl": "${config.baseUrl.trimEnd('/')}",
                  "api": "openai-completions",
                  "apiKey": "${'$'}${envName}",
                  "compat": { "maxTokensField": "max_tokens" },
                  "models": [ $model ]
                }
              }
            }
        """.trimIndent()
    }
}
