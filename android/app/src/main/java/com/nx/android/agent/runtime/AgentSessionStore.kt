package com.nx.android.agent.runtime

import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 活跃会话的指针：引擎的哪个会话文件是玩家此刻所在的那段对话。
 *
 * 会话的内容（消息、工具记录、统计）都在引擎那里，App 不再存第二份；「玩家最后在哪段
 * 会话」是 App 层的状态，所以这根指针留在这里。旧版本留下的会话 JSON 躺在同一个目录里
 * 不读不删。
 */
@Singleton
class AgentSessionStore internal constructor(private val dir: File) {

    /** 注入用的那个：指针住在助手的专属目录里。 */
    @Inject
    constructor(workspace: AgentWorkspace) : this(File(workspace.root, "sessions"))

    private val activeFile: File get() = File(dir, "_active")

    /** 玩家此刻所在的引擎会话文件；还没有过会话就是 null。 */
    fun activePath(): String? =
        activeFile.takeIf { it.isFile }?.readText()?.trim()?.takeIf { it.isNotBlank() }?.takeIf { it.endsWith(".jsonl") }

    /** 指针落到某个引擎会话文件上。 */
    fun setActive(path: String) {
        // 引擎有时报来的是会话的 id（`s-…`），不是文件路径：那个值解析不出会话 id，
        // 指针存了它，子 Agent 的面板就再也找不到这一局的 transcript。指针只收文件。
        if (!path.endsWith(".jsonl")) return
        dir.mkdirs()
        activeFile.writeText(path)
    }

    /** 新会话：指针先空着，第一轮问题发出时引擎会开新文件，那时再指过去。 */
    fun clearActive() {
        runCatching { activeFile.delete() }
    }
}
