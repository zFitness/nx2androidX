package com.nx.android.agent.ui

import com.nx.android.agent.AgentChat
import com.nx.android.agent.AgentConversation
import com.nx.android.agent.AgentEngineMissingException
import com.nx.android.agent.AgentEvent
import com.nx.android.agent.AgentFailure
import com.nx.android.agent.AgentMessage
import com.nx.android.agent.AgentModelConfig
import com.nx.android.agent.AgentSubagent
import com.nx.android.agent.AgentSubagentCall
import com.nx.android.agent.AgentTextBatch
import com.nx.android.agent.AgentTokenUsage
import com.nx.android.agent.needsConfirmBeforeSwitch
import com.nx.android.data.Gamespec
import com.nx.android.agent.env.PiHistoryMapper
import com.nx.android.agent.env.PiRunner
import com.nx.android.agent.env.PiSessionCatalog
import com.nx.android.agent.env.SubagentStore
import com.nx.android.agent.runtime.AgentModelProfile
import com.nx.android.agent.runtime.AgentModelStore
import com.nx.android.agent.runtime.AgentSessionStore
import com.nx.android.agent.runtime.AgentSettingsStore
import com.nx.android.core.di.ApplicationCoroutineScope
import com.nx.android.core.storage.AppPaths
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** What the chat surfaces render: the conversation, the running turn, the strip's failure, the model choice. */
data class AgentUiState(
    val messages: List<AgentMessage> = emptyList(),
    val running: Boolean = false,
    val error: AgentFailure? = null,
    val config: AgentModelConfig = AgentModelConfig("", "", "", ""),

    /** The capsule and the setup gate both read this: a blank key or endpoint means the assistant cannot run. */
    val configured: Boolean = false,

    /** The env agent's smoke test (ADR-009): its button's state and the turn's text. */
    val piRunning: Boolean = false,
    val piResult: String? = null,

    /** The words half-typed: the drawer closes and opens, the draft stays (it lives here, not in composition). */
    val draft: String = "",

    /** The session dropdown's list (the engine's own sessions), and which one answers now. */
    val sessions: List<PiSessionCatalog.Entry> = emptyList(),
    val activePath: String? = null,

    /** 当前会话的名字（引擎报的那个）；没有名字就退回列表里那一条的标题。 */
    val activeTitle: String = "",

    /** 历史正在从引擎读：对话区给加载态，占用区不给假数字。 */
    val loading: Boolean = false,
    /** 引擎还没装：抽屉引导安装，而不是显示一段空历史。 */
    val engineMissing: Boolean = false,

    /** The session's context occupancy and its model's window (the tool column's usage row). */
    val usageTokens: Long = 0L,
    val usageWindow: Long = 0L,

    /** 主会话的累计用量：引擎那本账上的数（面板上那一栏）。 */
    val sessionUsage: AgentTokenUsage = AgentTokenUsage(),

    /** 这一局派生过的子 Agent 合计花了多少（各次运行自己的用量加起来）。 */
    val subagentUsage: AgentTokenUsage = AgentTokenUsage(),

    /** The models the player configured: the chip's menu lists them. */
    val profiles: List<AgentModelProfile> = emptyList(),
    val activeProfileId: String = "",

    /** The message the running turn writes into: it shows as plain text until the turn ends. */
    val streamingId: Long? = null,

    /** The sub-agents this chat spawned: the runs that finished and the ones still going. */
    val subagents: List<AgentSubagent> = emptyList(),

    /** Which run each sub-agent call started: the card in the conversation looks itself up here. */
    val subagentRuns: Map<String, AgentSubagent> = emptyMap(),

    /**
     * 案例档案时间线上的最新一条：子代理自己记下的进展（在跑的卡片上亮出来）。
     *
     * 那是一行文字，不是状态牌——案例的状态是助手自己说的（回答里的 nx-case 块），
     * App 不去档案里猜。
     */
    val caseProgress: String? = null,

    /**
     * 待确认的会话切换：当前会话有正在跑的子任务，玩家点了切会话。
     *
     * `target` 是要切过去的会话文件；`null` 是「新会话」。
     */
    val switchAsk: AgentSwitchAsk? = null,
)

/**
 * 一次待确认的会话切换：当前会话有正在跑的子任务，玩家点了切会话或新会话。
 *
 * 子代理跟着会话活——切走会把正在跑的那些掐掉。这件事该不该做是玩家的决定，App 只负责
 * 把代价说清楚（几个任务在跑、切过去会中断它们）。
 */
data class AgentSwitchAsk(val target: String?, val running: Int)

/**
 * The assistant's conversation, app-wide: one copy of the messages, of the turn that runs and of
 * the words half-typed.
 *
 * 会话的真相在引擎那里：这里的消息是渲染用的副本，冷启动不急着拉——抽屉第一次打开时
 * 才去读（引擎进程冷启动只要零点几秒，读的那一下用加载态盖住）。历史在整个进程里只有
 * 这一份：首页抽屉、竖屏聊天页、游戏抽屉读的都是它。
 */
@Singleton
class AgentConversationState @Inject constructor(
    private val chat: AgentChat,
    private val settings: AgentSettingsStore,
    private val sessionStore: AgentSessionStore,
    private val catalog: PiSessionCatalog,
    private val piRunner: PiRunner,
    private val models: AgentModelStore,
    private val subagentStore: SubagentStore,
    private val paths: AppPaths,
    @ApplicationCoroutineScope private val scope: CoroutineScope,
) {

    private val conversation = AgentConversation()
    private val _uiState = MutableStateFlow(AgentUiState())
    val uiState: StateFlow<AgentUiState> = _uiState.asStateFlow()

    /** markdown 的预解析缓存：条目进屏时高度一次就对，滚动不再等解析 */
    val markdownCache = AgentMarkdownCache(scope)

    /** 那一轮跑在哪：主线程上（和从前一样），窗口关着它也照跑 */
    private val turnScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    // 这些数字与列表会被后台的那一轮改，也会被界面读：给它们 volatile，跨线程看得见
    @Volatile private var config = settings.config
    @Volatile private var profiles = models.list()
    @Volatile private var activeProfileId = models.activeId()
    @Volatile private var sessions: List<PiSessionCatalog.Entry> = emptyList()
    @Volatile private var activePath: String? = null
    @Volatile private var activeTitle = ""
    @Volatile private var loading = false
    @Volatile private var engineMissing = false
    @Volatile private var usageTokens = 0L
    @Volatile private var usageWindow = 0L

    /** 主会话的累计用量：引擎那本账上的数。 */
    @Volatile private var sessionUsage = AgentTokenUsage()
    @Volatile private var draft = ""
    @Volatile private var piRunning = false
    @Volatile private var piResult: String? = null
    @Volatile private var subagents: List<AgentSubagent> = emptyList()

    /** 哪次调用派出了哪一次运行（卡片与清单都要靠它对上） */
    @Volatile private var subagentRuns: Map<String, AgentSubagent> = emptyMap()

    /** 档案时间线上的最新一条：子代理记下的进展 */
    @Volatile private var caseProgress: String? = null

    /** 待确认的会话切换：有子任务在跑，玩家点了切会话 */
    @Volatile private var switchAsk: AgentSwitchAsk? = null

    /** 子 Agent 在跑的时候，面板要看得见它在干啥：两秒读一次它的 transcript */
    private var subagentWatch: Job? = null

    private var turn: Job? = null

    /** 历史读过了没有：抽屉每次打开都会问一遍，读过就不再劳师动众。 */
    @Volatile private var historyLoaded = false

    init {
        publish()
        watchBackground()
    }

    /**
     * 轮外的那一段：引擎在两轮之间说话（后台子 Agent 跑完了，主 Agent 接着讲）。
     *
     * 它到的时候玩家没有在问——但那正是玩家等着看的东西（子 Agent 的结论、方案写好了
     * 没有），所以它自己是一条消息，实时地长出来。
     */
    private fun watchBackground() {
        scope.launch {
            val batch = AgentTextBatch()
            chat.backgroundEvents.collect { event ->
                when (event) {
                    is AgentEvent.TextDelta -> {
                        // 跟回答一样攒着走：逐字重排太慢
                        batch.add(event.text)
                        if (batch.due()) flushBackground(batch)
                    }
                    is AgentEvent.UsageUpdated -> {
                        usageTokens = event.contextTokens
                        usageWindow = event.contextWindow
                        publish()
                    }
                    is AgentEvent.Notification -> {
                        flushBackground(batch)
                        conversation.followUp(event)
                        // 子 Agent 刚跑完：清单跟上，档案里的进展可能刚变了
                        refreshSubagents()
                        refreshCaseProgress()
                        publish()
                    }
                    is AgentEvent.Failed -> {
                        flushBackground(batch)
                        conversation.apply(event)
                        publish()
                    }
                    else -> {
                        flushBackground(batch)
                        conversation.followUp(event)
                        publish()
                    }
                }
            }
        }
    }

    /** 轮外那一段的缓冲也走了：它落在那条消息里。 */
    private fun flushBackground(batch: AgentTextBatch) {
        val text = batch.take()
        if (text.isEmpty()) return
        conversation.followUp(AgentEvent.TextDelta(text))
        publish()
    }

    /**
     * The assistant message the running turn's events land in; the turn's first event makes it.
     */
    private fun publish() {
        _uiState.value = AgentUiState(
            messages = conversation.messages,
            running = conversation.running,
            error = conversation.failure,
            config = config,
            configured = config.configured,
            piRunning = piRunning,
            piResult = piResult,
            draft = draft,
            sessions = sessions,
            activePath = activePath,
            activeTitle = activeTitle,
            loading = loading,
            engineMissing = engineMissing,
            usageTokens = usageTokens,
            usageWindow = usageWindow,
            sessionUsage = sessionUsage,
            // 子代理那半是各次运行自己的用量加起来：数都是引擎写的，App 只做加法
            subagentUsage = subagents.fold(AgentTokenUsage()) { acc, run -> acc + run.usage },
            profiles = profiles,
            activeProfileId = activeProfileId,
            streamingId = conversation.streamingId,
            subagents = subagents,
            subagentRuns = subagentRuns,
            caseProgress = caseProgress,
            switchAsk = switchAsk,
        )
        // markdown 的 AST 在这里备：读到的历史一落地就开始解析，首开抽屉时高度已经是最终值。
        markdownCache.ensureAll(conversation.messages, conversation.streamingId)
    }

    /**
     * 抽屉打开时问一句：历史在吗？
     *
     * 第一次：从引擎读（指针上的那段，没有就最新的那段），引擎起进程那零点几秒由加载态
     * 盖住。引擎没装则挂出引导，不算失败。
     */
    fun ensureHistory() {
        if (historyLoaded || loading || conversation.running) return
        if (!config.configured) return   // 模型没配：芯片会把玩家送去过设置，先不劳驾引擎
        load(prefer = null)
    }

    /** Another conversation answers from here on: the engine loads its own session, the panel re-renders. */
    fun switchSession(path: String) {
        if (conversation.running || path == activePath) return
        historyLoaded = false
        load(prefer = path)
    }

    /**
     * 切会话（新会话也算）：当前会话有正在跑的子任务时，先问玩家一句。
     *
     * 子代理跟着会话活——切走会把正在跑的那些掐掉，引擎那边不会为它们留下记录。所以这一步
     * 是替玩家挡一下：要不要拿那几份正在干的活去换一段新对话，是他的决定，App 只把代价
     * 说清楚。没有子任务在跑时不打扰，直接切。
     *
     * @param target 要切过去的会话文件；`null` 是「新会话」
     */
    fun requestSwitch(target: String?) {
        if (conversation.running) return   // 引擎正忙着：现在切不了（切了也是乱的）
        if (switchAsk != null) return     // 问过了：等玩家答
        val path = activePath
        val calls = subagentCalls()
        scope.launch {
            // 现场读一次，不用界面上那份：刚派出去的那个子代理也许还没进那份清单
            val runs = withContext(Dispatchers.IO) { subagentStore.list(path, calls).runs }
            if (!needsConfirmBeforeSwitch(runs)) {
                doSwitch(target)
            } else {
                switchAsk = AgentSwitchAsk(target, runs.count { it.running })
                publish()
            }
        }
    }

    /** 玩家确认了：切。 */
    fun confirmSwitch() {
        val ask = switchAsk ?: return
        switchAsk = null
        publish()
        doSwitch(ask.target)
    }

    /** 玩家留下了：不切，那些子任务接着跑。 */
    fun dismissSwitch() {
        if (switchAsk == null) return
        switchAsk = null
        publish()
    }

    /** 真的切：新会话是空的一段对话，切过去是换一段对话。 */
    private fun doSwitch(target: String?) {
        if (target == null) newSession() else switchSession(target)
    }

    /** The menu's new-chat entry: the engine's context resets; the file itself appears at the first prompt. */
    fun newSession() {
        if (conversation.running) return
        chat.reset()
        conversation.load(emptyList())
        // 消息的 id 从头数了：旧对话排好的 AST 一条都不留（不然新回答会渲染成旧回答）
        markdownCache.clear()
        activePath = null
        activeTitle = ""
        subagents = emptyList()
        subagentRuns = emptyMap()
        conversation.dismissFailure()
        usageTokens = 0L
        usageWindow = 0L
        historyLoaded = true   // 空白即所需，第一问发出时引擎自会开新文件
        refreshSessions()
        publish()
    }

    /** 读一段历史：prefer 指定就是切过去读，为空就是指针上的（或最新的）。 */
    private fun load(prefer: String?) {
        loading = true
        engineMissing = false
        publish()
        scope.launch {
            val result = chat.history(prefer)
            loading = false
            result.onSuccess { history ->
                conversation.load(history.messages)
                // 换了一段对话：消息的 id 从头数了，旧 AST 一条都不留（不然新回答会渲染成旧回答）
                markdownCache.clear()
                usageTokens = history.contextTokens
                usageWindow = history.contextWindow
                sessionUsage = history.usage
                activePath = history.sessionFile.ifBlank { null }
                activeTitle = history.title
                historyLoaded = true
                conversation.dismissFailure()
            }.onFailure { e ->
                if (e is AgentEngineMissingException) engineMissing = true
                historyLoaded = true   // 读不回来也不反复重试：引导玩家去处理
            }
            refreshSessions()
            refreshSubagents()
            publish()
        }
    }

    /** 会话列表是磁盘上的目录：后台读，读回来刷新下拉。 */
    private fun refreshSessions() {
        scope.launch {
            val listed = withContext(Dispatchers.IO) { catalog.list() }
            sessions = listed
            if (activePath == null) activePath = sessionStore.activePath()
            publish()
        }
    }

    /**
     * 拉一次主会话的累计用量：面板打开时来一下，拿到的是当下的数。
     *
     * 引擎那本账（`get_session_stats`）——App 不自己累加，重开一次也不会少算。
     */
    fun refreshUsage() {
        scope.launch {
            val usage = withContext(Dispatchers.IO) { chat.usage() }
            sessionUsage = usage
            publish()
        }
    }

    /**
     * 子 Agent 的清单：会话文件里的记录（跑完的）+ 还在写的 transcript（在跑的）。
     *
     * 派生一次的工具调用带着那个子 Agent 的 prompt——它是工具调用与 transcript 之间唯一的
     * 准确联系，靠它把类型和任务对上。
     */
    fun refreshSubagents() {
        val calls = subagentCalls()
        scope.launch {
            // the path is read on disk: it must not be read on the main thread
            val listed = withContext(Dispatchers.IO) {
                subagentStore.list(currentSessionPath(), calls)
            }
            subagents = listed.runs
            subagentRuns = listed.byCall
            // 子代理在跑的时候，档案上的进展也在变：两秒读一次，玩家看得见它干到哪了
            readCaseProgress()
            publish()
        }
    }

    /**
     * 引擎此刻在答的那一局的会话文件。
     *
     * 指针（`activePath`）是引擎在**一轮结束时**报上来的路径：第一轮派出的子 Agent 跑的时候
     * 它还指着上一轮，面板就找不到这一轮子 Agent 的 transcript（空着）。所以跑着的时候读的是
     * 「引擎此刻在写的那个玩家会话文件」——子 Agent 的会话文件同时在写，但它们不算玩家的会话。
     * 闲下来时反过来：玩家在看的那一局，指针说了算（刚切过对话时，引擎还没往新文件上写，
     * 最新的文件还是上一局的）。
     */
    private fun currentSessionPath(): String? {
        val pointed = activePath?.takeIf { File(it).isFile }
        return if (conversation.running) catalog.current()?.path ?: pointed
        else pointed ?: catalog.current()?.path
    }

    /**
     * 子 Agent 在跑的时候，面板要看得见它在干啥：两秒读一次它的 transcript。
     *
     * 轮到结束、也没有在跑的，就停下来——不空转。
     */
    private fun watchSubagents() {
        if (subagentWatch?.isActive == true) return
        subagentWatch = scope.launch {
            while (true) {
                delay(2000)
                val listed = withContext(Dispatchers.IO) {
                    subagentStore.list(currentSessionPath(), subagentCalls())
                }
                subagents = listed.runs
                subagentRuns = listed.byCall
                readCaseProgress()
                publish()
                if (listed.runs.none { it.running } && !conversation.running) break
            }
        }
    }

    /** 这一轮派生过的子 Agent 调用（工具调用带的那条准确联系） */
    private fun subagentCalls(): List<AgentSubagentCall> = conversation.messages.flatMap { message ->
        message.tools.mapNotNull { it.subagent }
    }

    /**
     * 档案时间线上的最新一条：子代理自己记下的进展（跑着的卡片上那一行字）。
     *
     * 只读——档案是子 Agent 写的，app 不碰它。这里只有进展，没有状态：
     * 案例的状态是助手自己说的（回答里的 nx-case 块），app 不去档案里猜。
     */
    private suspend fun readCaseProgress() {
        val dir = withContext(Dispatchers.IO) { Gamespec.recentCaseDir(paths.nxHome) }
        caseProgress = dir?.let { Gamespec.latestTimeline(it) }
    }

    /** 读一次档案的进展：回合结束时跟上。 */
    private fun refreshCaseProgress() {
        scope.launch {
            readCaseProgress()
            publish()
        }
    }

    /** 子 Agent 的完整对话：它自己的会话文件（还在跑的就是它的 transcript）。 */
    suspend fun subagentConversation(subagent: AgentSubagent): List<AgentMessage> =
        withContext(Dispatchers.IO) {
            val messages = subagentStore.conversation(subagent, currentSessionPath())
            PiHistoryMapper.map(messages)
        }

    /**
     * The model chip's menu: the profile the player picks answers from now on. The key stays with
     * the profile — the chip never shows it.
     */
    fun selectProfile(id: String) {
        if (conversation.running) return
        models.setActive(id)
        refreshModels()
    }

    /** Reads the models again: the settings page may have changed them while the panel was closed. */
    fun refreshModels() {
        profiles = models.list()
        activeProfileId = models.activeId()
        config = settings.config
        publish()
    }

    /** The input box is controlled: closing the drawer must not eat the player's half-typed words. */
    fun updateDraft(text: String) {
        draft = text
        publish()
    }

    /** The env agent's smoke test: one headless pi turn through the app's own proxy (ADR-009). */
    fun runPiTest() {
        if (piRunning) return
        piRunning = true
        piResult = null
        publish()
        scope.launch {
            piResult = piRunner.run("用一句话回答：你是什么模型").fold(
                onSuccess = { it.ifBlank { "（空回复）" } },
                onFailure = { "失败：${it.message}" },
            )
            piRunning = false
            publish()
        }
    }

    /** One turn: the words land at once, the answer streams in as the events arrive. */
    fun send(text: String) {
        val words = text.trim()
        if (words.isEmpty() || conversation.running) return
        conversation.dismissFailure()
        draft = ""
        conversation.say(words)
        conversation.begin()
        publish()
        // 子 Agent 可能这一轮就跑起来：看着它
        watchSubagents()
        turn = turnScope.launch {
            val batch = AgentTextBatch()
            val thoughts = AgentTextBatch()
            try {
                chat.send(words).collect { event ->
                    when (event) {
                        is AgentEvent.TextDelta -> {
                            // the deltas wait in the buffer: the answer is re-laid ten times a
                            // second, not once per token
                            batch.add(event.text)
                            if (batch.due()) flush(batch)
                        }
                        is AgentEvent.ThinkingDelta -> {
                            // 思考过程也一样攒着走：它长得比回答还快，逐字重排更慢
                            thoughts.add(event.text)
                            if (thoughts.due()) flushThoughts(thoughts)
                        }
                        is AgentEvent.UsageUpdated -> {
                            usageTokens = event.contextTokens
                            usageWindow = event.contextWindow
                            publish()
                        }
                        else -> {
                            flush(batch)
                            flushThoughts(thoughts)
                            apply(event)
                        }
                    }
                }
            } catch (e: CancellationException) {
                throw e   // the stop button: the cancel stays visible to the scope
            } catch (e: Exception) {
                // 先把缓冲里的字并进正在写的那条：它们本来也已经从模型流出来了。
                // 反过来（先 Failed 后 flush）会造出一条"幽灵回答"——空壳删掉之后
                // flush 又新建了一条。
                flush(batch)
                flushThoughts(thoughts)
                apply(AgentEvent.Failed(AgentFailure.LOOP_ERROR))   // nothing the failure codes cover
            } finally {
                flush(batch)
                flushThoughts(thoughts)
                conversation.end()
                publish()
            }
        }
    }

    /**
     * 停止：这一轮到此为止。
     *
     * 界面立刻解锁（不等引擎），引擎那边收到中止命令后停下手里的活——它不跑完这一轮，
     * 进程也留着给下一轮。已写出的字留在这一轮的回答里。
     */
    fun stop() {
        turn?.cancel()
        turn = null
        chat.abort()
    }

    /** The strip's way out (the next turn replaces the words anyway). */
    fun dismissError() {
        conversation.dismissFailure()
        publish()
    }

    /** The setup sheet's save: the choice lands where the data layer keeps it (the key never shows up here). */
    fun updateConfig(providerId: String, baseUrl: String, apiKey: String, modelName: String) {
        settings.update(AgentModelConfig(providerId, baseUrl, apiKey, modelName))
        config = settings.config
        conversation.dismissFailure()
        publish()
    }

    /** One event of the running turn lands in the rendered list. */
    private fun apply(event: AgentEvent) {
        conversation.apply(event)
        if (event is AgentEvent.TurnDone) {
            // 这一轮可能开过新会话文件（新会话的第一问）：列表与指针都跟上
            activePath = sessionStore.activePath()
            refreshSessions()
        }
        // 子 Agent 可能刚跑完：清单跟着更新
        if (event is AgentEvent.Notification || event is AgentEvent.TurnDone) {
            refreshSubagents()
            // 档案里的进展可能刚变了：读一下
            refreshCaseProgress()
        }
        publish()
    }

    /** The buffer leaves: its words join the answer being written. */
    private fun flush(batch: AgentTextBatch) {
        val text = batch.take()
        if (text.isEmpty()) return
        conversation.appendText(text)
        publish()
    }

    /** 思考过程的缓冲也走了：它落在这一轮的回答里（折起来的那一段）。 */
    private fun flushThoughts(batch: AgentTextBatch) {
        val text = batch.take()
        if (text.isEmpty()) return
        conversation.appendThinking(text)
        publish()
    }
}
