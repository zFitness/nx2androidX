package com.nx.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import androidx.core.content.ContextCompat
import com.nx.android.appstate.ExportState
import com.nx.android.data.AppLocale
import com.nx.android.domain.ApkMeta
import com.nx.android.domain.GameApkExport
import com.nx.android.domain.GameApkExportService
import com.nx.android.domain.GameRef
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlin.concurrent.thread

/**
 * 导出 APK 的前台服务：构建、安装与搬数据加起来是十几分钟的活儿，App 一退到后台就会被冻结（MIUI 尤甚），
 * 传输死得无声无息。这条服务的常驻通知让进程保持前台优先级——和移植的 PortService 同一个道理：它不持有
 * 状态，ExportState 是唯一的真源，服务负责让活儿跑完并把进度映到通知里。不是 sticky：传输没法续跑，
 * 被杀掉算一次中断，失败框里的「搬数据」就是它的重来。
 */
@AndroidEntryPoint
class ExportService : Service() {

    companion object {
        const val CHANNEL = "nx2a_export"
        const val NOTIFY_ID = 2
        private const val ACTION_START = "com.nx.android.export.START"
        private const val ACTION_MOVE = "com.nx.android.export.MOVE"
        private const val TITLE_ID = "titleId"
        private const val LABEL = "label"
        private const val PACK = "pack"
        private const val ROMFS = "romfs"
        private const val PACKAGE = "package"
        private const val VERSION = "version"
        private const val AUTHOR = "author"
        private const val EMAIL = "email"
        private const val DESCRIPTION = "description"

        /** The game's identity crosses the Intent as plain strings: the Activity's objects cannot. */
        private fun intent(ctx: Context, action: String, game: GameRef) =
            Intent(ctx, ExportService::class.java).setAction(action)
                .putExtra(TITLE_ID, game.titleId).putExtra(LABEL, game.label)
                .putExtra(PACK, game.pack.absolutePath).putExtra(ROMFS, game.romfsAt)

        /** Starts the whole export: build, install, data. 从头导出：构建 → 安装 → 数据 */
        fun start(ctx: Context, game: GameRef, meta: ApkMeta) =
            ContextCompat.startForegroundService(ctx, intent(ctx, ACTION_START, game)
                .putExtra(PACKAGE, meta.packageName).putExtra(VERSION, meta.versionName)
                .putExtra(AUTHOR, meta.author).putExtra(EMAIL, meta.email)
                .putExtra(DESCRIPTION, meta.description))

        /** Moves the data only (the retry: the game is installed, the transfer died halfway). 只搬数据 */
        fun startMove(ctx: Context, game: GameRef, packageName: String) =
            ContextCompat.startForegroundService(ctx, intent(ctx, ACTION_MOVE, game).putExtra(PACKAGE, packageName))
    }

    @Inject lateinit var exportService: GameApkExportService
    @Inject lateinit var state: ExportState
    @Inject lateinit var locale: AppLocale

    private lateinit var nm: NotificationManager

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, locale.str(R.string.export_notification_channel),
                NotificationManager.IMPORTANCE_LOW),
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // 重入保护（PortService 同款）：一次只跑一个导出——两次 start 会写同一个临时 APK、互相 stopSelf
        if (state.running) { stopSelf(startId); return START_NOT_STICKY }
        if (intent == null) return stop(startId)
        val packPath = intent.getStringExtra(PACK) ?: return stop(startId)
        val game = GameRef(
            intent.getStringExtra(TITLE_ID) ?: return stop(startId),
            intent.getStringExtra(LABEL) ?: return stop(startId),
            java.io.File(packPath),
            intent.getStringExtra(ROMFS) ?: "",
        )
        val meta = ApkMeta(
            packageName = intent.getStringExtra(PACKAGE) ?: "",
            versionName = intent.getStringExtra(VERSION) ?: "",
            author = intent.getStringExtra(AUTHOR) ?: "",
            email = intent.getStringExtra(EMAIL) ?: "",
            description = intent.getStringExtra(DESCRIPTION) ?: "",
        )
        when (intent.action) {
            ACTION_START -> {
                begin(game, locale.str(R.string.export_notification_build))
                thread(name = "nx2a-export") {
                    done(exportService.export(game, meta, { p -> onProgress(p) }, { }))
                }
            }
            ACTION_MOVE -> {
                val packageName = intent.getStringExtra(PACKAGE) ?: return stop(startId)
                begin(game, locale.str(R.string.lib_apk_export_stage_move))
                thread(name = "nx2a-export-move") {
                    val ok = exportService.moveData(game, packageName, { p -> onProgress(p) }, { })
                    done(if (ok) GameApkExport.Result(ok = true, installed = true, moved = true)
                         else GameApkExport.Result(ok = false, failure = "move_failed", installed = true))
                }
            }
            else -> return stop(startId)
        }
        return START_NOT_STICKY
    }

    /** 前台通知先挂上，状态先起来（界面立刻转向），活儿在后头线程里跑 */
    private fun begin(game: GameRef, stage: String) {
        state.begin(game.label)
        startForeground(NOTIFY_ID, notification(game.label, stage, null).build())
    }

    /** 进度映进通知：限着频（每个 64 KB 块都发会把通知打爆），状态那口照收 */
    private var lastNotify = 0L
    private fun onProgress(p: GameApkExport.Progress) {
        state.onProgress(p)
        val now = System.currentTimeMillis()
        if (now - lastNotify < 500) return
        lastNotify = now
        nm.notify(NOTIFY_ID, notification(state.game, stageText(p), p.fraction).build())
    }

    private fun stageText(p: GameApkExport.Progress): String = locale.str(when (p.stage) {
        GameApkExport.Stage.BUILD -> R.string.lib_apk_export_stage_build
        GameApkExport.Stage.INSTALL -> R.string.lib_apk_export_stage_install
        GameApkExport.Stage.MOVE -> R.string.lib_apk_export_stage_move
        else -> R.string.lib_apk_export_stage_build
    })

    /** 活儿结束了：结果交给状态口（界面出框），通知收尾，服务退场 */
    private fun done(r: com.nx.android.domain.GameApkExport.Result) {
        state.finish(r)
        val text = if (r.ok) locale.str(R.string.lib_apk_export_done)
        else locale.str(R.string.export_notification_failed, locale.str(
            when (r.failure) {
                "install_failed" -> R.string.lib_apk_install_failed_title
                "move_failed" -> R.string.lib_apk_move_failed_title
                else -> R.string.lib_apk_export_failed_title
            }))
        nm.notify(NOTIFY_ID, notification(state.game, text, null).setAutoCancel(true).build())
        stopForeground(STOP_FOREGROUND_DETACH)
        stopSelf()
    }

    private fun notification(game: String, what: String, fraction: Float?): Notification.Builder {
        val tap = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentTitle(game.ifEmpty { locale.str(R.string.app_name) })
            .setContentText(what)
            .setProgress(100, ((fraction ?: 0f) * 100).toInt(), fraction == null)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(tap)
    }

    private fun stop(startId: Int): Int {
        stopSelf(startId); return START_NOT_STICKY
    }
}
