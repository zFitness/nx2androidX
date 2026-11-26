package com.nx.android.appstate

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.nx.android.domain.GameApkExport
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 导出 APK 的那口状态：跑在前台 ExportService 里的活儿，界面从这口看进度与结果。它不持有参数——参数在
 * Intent 里；谁都可以读，只有服务写。
 *
 * （移植的那口是 PortState，这里照它的规矩来：服务只让进程活着并把这口状态推进。）
 */
@Singleton
class ExportState @Inject constructor() {

    /** 有导出在跑（构建/安装/搬运） */
    var running by mutableStateOf(false)
        private set

    /** 正在导出的游戏名字（通知与界面标题用） */
    var game by mutableStateOf("")
        private set

    /** 跑到哪了（构建没有进度可言，安装与搬运按字节走） */
    var progress by mutableStateOf<GameApkExport.Progress?>(null)
        private set

    /** 最后一次导出的结果：界面拿它出完成框/失败框；界面看完自己 clear() */
    var result by mutableStateOf<GameApkExport.Result?>(null)
        private set

    fun begin(game: String) {
        this.game = game
        running = true
        progress = null
        result = null
    }

    fun onProgress(p: GameApkExport.Progress) {
        progress = p
    }

    fun finish(r: GameApkExport.Result) {
        running = false
        progress = null
        result = r
    }

    /** 界面看完结果把它收掉 */
    fun clear() {
        result = null
    }
}
