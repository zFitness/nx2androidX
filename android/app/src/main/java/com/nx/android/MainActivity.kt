package com.nx.android

import android.Manifest
import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.hardware.input.InputManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.lifecycle.lifecycleScope
import com.nx.android.app.GameShortcuts
import com.nx.android.appstate.LibraryOperationCoordinator
import com.nx.android.appstate.UpdateState
import com.nx.android.appstate.porting.PortCompletionCoordinator
import com.nx.android.data.firmware.FirmwareRepository
import com.nx.android.agent.runtime.GamespecExporter
import com.nx.android.agent.runtime.openGamespecIssue
import com.nx.android.domain.drivers.DriverRepository
import com.nx.android.domain.environment.EnvironmentSetup
import com.nx.android.game.GameActivity
import dagger.hilt.android.AndroidEntryPoint
import com.nx.android.domain.porting.PortPhase
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject
import androidx.activity.compose.setContent
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import com.nx.android.R
import com.nx.android.agent.runtime.AgentEngineStore
import com.nx.android.agent.runtime.AgentSetup
import com.nx.android.agent.ui.AgentConversationState
import com.nx.android.appstate.LibraryState
import com.nx.android.appstate.EnvBuildState
import com.nx.android.appstate.EnvCheckState
import com.nx.android.appstate.OnboardingState
import com.nx.android.appstate.PageStateStore
import com.nx.android.appstate.PlayerState
import com.nx.android.appstate.PortState
import com.nx.android.data.AppLocale
import com.nx.android.data.AppLog
import com.nx.android.data.AppVersion
import com.nx.android.data.CheatRepo
import com.nx.android.data.Gamespec
import com.nx.android.data.LogBundle
import com.nx.android.data.Player
import com.nx.android.data.PrefsStore
import com.nx.android.data.porting.BuildSessionRepository
import com.nx.android.core.storage.AppPaths
import androidx.core.content.FileProvider
import com.nx.android.data.library.LibraryFileScanner
import com.nx.android.domain.GameIdentity
import com.nx.android.domain.LaunchDecision
import com.nx.android.domain.LibraryLogic
import com.nx.android.domain.Ported
import androidx.compose.runtime.snapshotFlow
import com.nx.android.app.AppActions
import com.nx.android.app.AppRoot
import com.nx.android.app.CrashReport
import com.nx.android.input.GamepadScan
import com.nx.android.input.PadCalibration
import com.nx.android.input.PadTestInput
import com.nx.android.input.ui.PadCenterController
import com.nx.android.core.ui.nav.NavEdge
import com.nx.android.core.ui.nav.NavKey
import com.nx.android.core.ui.nav.NavKeys
import com.nx.android.core.ui.nav.UiInput
import android.view.InputDevice
import android.view.KeyEvent
import android.view.MotionEvent
import java.io.File
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * The shell: it owns what only an activity can own — the storage permission, the system pickers — and puts
 * the screen up. Hilt supplies long-lived dependencies; screens receive state holders
 * and action lambdas, never this activity.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var portCompletionCoordinator: PortCompletionCoordinator

    companion object {
        const val EXTRA_TAB = "tab"   // the notification's tap lands on the builds page
        const val EXTRA_BUILD_ID = "buildId"

        /** 十字键帽推到底才算方向（帽子只有 -1/0/1，门槛比摇杆低）。 */
        const val HAT_THRESHOLD = 0.5f

        /** SIGKILL：App 收尾时自己杀的游戏进程（正常结束，不是闪退）。 */
        private const val SIGNALED_KILL = 9
        /** SIGTERM：礼貌终止请求（宿主自己优雅退出成 0，不是闪退）。 */
        private const val SIGNALED_TERM = 15
        /** 宿主给游戏自己的致命 Break 留的退出码（hle_svc.c）：屏幕上有报错，玩家需要知道。 */
        private const val EXIT_GAME_FATAL = 42
    }

    @Inject lateinit var locale: AppLocale
    @Inject lateinit var prefs: PrefsStore
    @Inject lateinit var library: LibraryState
    @Inject lateinit var player: PlayerState
    @Inject lateinit var operations: LibraryOperationCoordinator
    @Inject lateinit var port: PortState
    @Inject lateinit var buildSessions: BuildSessionRepository
    @Inject lateinit var paths: AppPaths
    @Inject lateinit var onboarding: OnboardingState
    @Inject lateinit var environmentSetup: EnvironmentSetup
    @Inject lateinit var drivers: DriverRepository
    @Inject lateinit var firmwareRepo: FirmwareRepository
    @Inject lateinit var envCheck: EnvCheckState
    @Inject lateinit var envBuild: EnvBuildState
    @Inject lateinit var update: UpdateState
    @Inject lateinit var agentEngine: AgentEngineStore
    @Inject lateinit var agentSetup: AgentSetup
    /** 攻关档案的导出：打包器在环境里跑 */
    @Inject lateinit var exporter: GamespecExporter
    /** 助手的会话：整个 App 一份——首页的抽屉、竖屏的聊天页与游戏里的抽屉看的都是它 */
    @Inject lateinit var agentConversation: AgentConversationState
    /** 页面状态快照：助手想知道玩家此刻在哪一局，就读它 */
    @Inject lateinit var pageState: PageStateStore

    /** 界面语言：toast 与分享面板的标题从这里取词 */
    /** Which tab the screen opens on (the notification's tap says the builds page) */
    var launchTab = 0
    private var launchBuildId by mutableStateOf("")

    /** 手柄中心（首页顶栏的入口）：档案跟游戏共用同一个文件 */
    private val padController by lazy { PadCenterController.forContext(this) }

    /** 导入或清除了金手指：这个数一变，设置页那一行跟着重画 */
    private var cheatsChanged by mutableStateOf(0)

    /** 首页的手柄中心开着吗（开着的时候手柄的键不进库页，只进示波与抓键）。
     *  这一份是**唯一**的那份：分发层（dispatchKeyEvent）与页面读的都是它。 */
    var padCenterOpen by mutableStateOf(false)

    /** The assistant's full chat page is open (the portrait one)? The one copy: AppRoot's entry writes it,
     *  the orientation collector in onCreate reads it. The side panel does not count — it is landscape. */
    private var agentFullOpen by mutableStateOf(false)

    /** 摇杆与十字键帽各自的边沿状态：推到底发一次，回中才复位。 */
    private val hatEdge = NavEdge(HAT_THRESHOLD)
    private val stickEdge = NavEdge()

    /** 上一次那个游戏闪退了：弹框把那三条路摆出来（重新构建 / 重新移植 / 反馈） */
    private var crash by mutableStateOf<CrashReport?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 全屏沉浸：内容铺满整块屏幕，系统栏隐藏（下滑临时呼出）
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }
        onboarding.storageOk = storageGranted()
        onboarding.batteryOk = batteryUnrestricted()
        GamepadScan.start(this)   // 顶栏的手柄入口要知道有几只手柄接着
        launchTab = intent?.getIntExtra(EXTRA_TAB, 0) ?: 0
        launchBuildId = intent?.getStringExtra(EXTRA_BUILD_ID).orEmpty()
        if (!prefs.bool(PrefsStore.OB_COMPLETED)) onboarding.open()
        AppLog.init(this)
        port.attach()   // a port the system killed shows up as interrupted
        port.history.filter { !it.legacy && it.phase in setOf(PortPhase.DONE, PortPhase.FAILED, PortPhase.CANCELLED, PortPhase.INTERRUPTED) }
            .forEach(portCompletionCoordinator::complete)
        if (port.phase == PortPhase.INTERRUPTED)
            port.history.firstOrNull { it.phase == PortPhase.INTERRUPTED }?.let(portCompletionCoordinator::complete)
        // 游戏在跑：游戏页是这个任务里压在库页上面的那一页——先把它顶到前面，再画库页（库页画在它下面，
        // 玩家看不见，但游戏结束后它就在那儿）。冷启动问一次进程：`:play` 活着就把游戏页顶回去。
        if (isLauncherEntry(intent) && player.processAlive(this)) GameActivity.resume(this)
        // 桌面快捷方式的点击（冷启动这一条）：与库页卡片走同一扇门
        if (intent?.action == GameShortcuts.ACTION) {
            intent.getStringExtra(GameShortcuts.EXTRA_TITLE_ID)?.let { onShortcut(it) }
        }
        setContent {
            AppRoot(prefs, locale, port, library, onboarding, drivers, environmentSetup, actions,
                launchTab, launchBuildId, padController, agentSetup, agentConversation, pageState,
                padCenterOpen = padCenterOpen, onPadCenter = { padCenterOpen = it },
                agentFullOpen = agentFullOpen, onAgentFull = { agentFullOpen = it },
                crash = crash, onCrashHandled = { crash = null },
                onExportGamespec = { titleId -> exportGamespec(titleId) })
        }
        // The chat page is portrait: while it is open the screen turns; closed, the sensor landscape lock
        // returns. orientation sits in the manifest's configChanges, so this only re-lays the tree out —
        // no page is rebuilt, nothing restarts.
        lifecycleScope.launch {
            snapshotFlow { agentFullOpen }.collect { open ->
                requestedOrientation =
                    if (open) ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
                    else ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
            }
        }
        // the assistant's own facts (the engine that is installed, the models that are configured)
        Thread {
            agentSetup.refresh()
        }.start()
        // The app brought another environment: it is built again, with a progress the player can see.
        // It happens here, at the app's start, before any port: a port that is running is never interrupted.
        envBuild.startIfNeeded()
        lifecycleScope.launch {
            drivers.ensureShipped()
            drivers.refresh()
        }
        // 有没有新版本：冷启动查一次，查不到就安静地过去（引导没走完的第一次启动不查）。
        // 它自己开线程（协程），所以不跟上面那条工具刷新挤在一起：那边出了岔子（未捕获的异常会
        // 杀掉整个进程），也不能把这一查一起带走。
        if (prefs.bool(PrefsStore.OB_COMPLETED)) update.checkQuietly()
    }

    /** The screens' way back to the activity's own privileges: the actions they may ask for, nothing else */
    private val actions = AppActions(
        onAskStorage = { askStorage() },
        onAskBattery = { askBattery() },
        storageOk = { onboarding.storageOk },
        onSetKeys = { prefs.writeKeys(it); envCheck.refresh() },
        onStartPort = { file, cfg ->
            // 没有「所有文件访问」权限就读不到游戏文件（重装 App 后会掉）：移植会死在半个 Python 栈里，先说清楚
            if (port.running) {
                toast(locale.str(R.string.runtime_busy))
            } else if (file.canRead()) {
                // 勾了「构建到共享存储」就落在 Android/data/<pkg>/files/ports（只对直读有意义）；
                // 否则落位跟着这个游戏的数据包走：它在可移动卡上，新包就建在那儿（内部存储的那份不动）
                val packDir = if (cfg.container && cfg.sharedStorage) {
                    getExternalFilesDir(null)?.let { File(it, "ports").absolutePath }
                } else library.packDirOf(file)?.absolutePath
                PortService.start(this, file.absolutePath, prefs.keys,
                                  cfg.touch, cfg.fps60, cfg.experimental, cfg.aliasHeadroom,
                                  cfg.sharedFont, firmwareRepo.folder ?: "", cfg.mtReplay, packDir,
                                  cfg.lowMem, cfg.container)
            } else {
                toast(locale.str(R.string.builds_needs_storage)); askStorage()
            }
        },
        onCancelPort = { PortService.cancel(this) },
        onRun = { pack, name -> runGate(pack, name) },
        // 攻关修好了之后「去跑一下」：按 title ID 找到那一局，走同一扇门
        onRunByTitleId = { titleId ->
            val ported = library.games.firstOrNull { it.titleId.equals(titleId, ignoreCase = true) }?.pack
            if (ported == null) toast(locale.str(R.string.lib_artifact_missing))
            else runGate(ported.pack, ported.name)
        },
        // 闪退之后的「重新构建」：重建运行库再进一次游戏（门还是那一扇）
        onRunRebuild = { pack, name -> runGate(pack, name, rebuild = true) },
        onSendToDesktop = { e ->
            val ported = e.pack
            if (ported == null) toast(locale.str(R.string.lib_artifact_missing))
            else if (GameShortcuts.request(this, ported, e.label)) {
                toast(locale.str(R.string.shortcut_added))
            } else toast(locale.str(R.string.shortcut_unsupported))
        },
        // 直接读取的包：把游戏文件重新关联到它现在的位置（只在没移植的时候）
        onRelinkPack = { pack, game ->
            if (port.running) toast(locale.str(R.string.runtime_busy))
            else PortService.relink(this, pack.absolutePath, game.absolutePath, prefs.keys)
        },
        onToast = { toast(it) },
        version = { versionName() },
        keys = { prefs.keys },
        // 固件：整机级的一份，导入 zip 解到 App 的私有目录（可选项）
        // 名字取自 envCheck 那份状态：导入或清除之后，这一行立刻跟着变（普通读 prefs 不会刷新界面）
        firmware = { envCheck.firmwareName },
        onImportFirmware = { zip -> importFirmware(zip) },
        // 金手指：社区的 Atmosphère 文件，玩家导入一个 zip（App 不带）
        cheatGames = { cheatGames() },
        cheatFiles = { cheatFiles() },
        onImportCheats = { zip -> importCheats(zip) },
        onClearCheats = { clearCheats() },
        // 游戏档案：玩家导入的档案包（App 不带档案），导入的是 App 私有目录里的那一份
        onImportProfiles = { zip -> importProfiles(zip) },
        onClearFirmware = {
            firmwareRepo.clear()
            envCheck.refresh()   // the chip's colour follows it at once
            toast(locale.str(R.string.fw_cleared))
        },
        // 文件管理器能不能看见 App 的私有目录（运行时、存档、日志）。文档提供器自己读这份设置。
        fileProvider = { prefs.bool(PrefsStore.FILE_PROVIDER, true) },
        onSetFileProvider = { on -> prefs.put(PrefsStore.FILE_PROVIDER, on) },
        onShareBuildLog = { id ->
            lifecycleScope.launch {
                val session = port.history.firstOrNull { it.id == id }
                when {
                    session == null || !session.logAvailable -> toast(locale.str(R.string.builds_log_unavailable))
                    buildSessions.logLength(id) == 0L -> toast(locale.str(R.string.builds_log_empty))
                    else -> {
                        val safeName = BuildSessionRepository.safeName(session.game)
                        val log = buildSessions.logFile(id)
                        val zip = withContext(Dispatchers.IO) {
                            LogBundle.build(this@MainActivity, paths.work,
                                listOfNotNull(log?.let { "$safeName-${id.take(8)}.log" to it }),
                                bundleDir(), "$safeName-${id.take(8)}")
                        }
                        shareBundle(zip, R.string.builds_log_share, R.string.builds_log_empty)
                    }
                }
            }
        },
        readBuildLog = { id, offset, length -> buildSessions.readLog(id, offset, length) },
        buildLogLength = { id -> buildSessions.logLength(id) },
        isBuildActive = { id -> port.history.firstOrNull { it.id == id }?.phase == PortPhase.RUNNING },
        emptyBuildLogMessage = { id ->
            val session = port.history.firstOrNull { it.id == id }
            locale.str(when {
                session == null || !session.logAvailable -> R.string.builds_log_unavailable
                session.phase == PortPhase.RUNNING -> R.string.builds_log_waiting
                session.legacy -> R.string.builds_log_legacy
                else -> R.string.builds_log_empty
            })
        },
        titleBuildLog = { id -> port.history.firstOrNull { it.id == id }?.let {
            "${File(it.game).name} · ${SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault()).format(Date(it.startedAt))}"
        } ?: locale.str(R.string.common_log) },
    )

    /**
     * 导入固件包：解压到 App 的私有目录（后台线程，340 MB 的包要十几秒）。
     * 解的是模拟器那种固件包（zip 根下一堆 .nca）；解压后的那份就是移植器要的「系统内容文件夹」。
     */
    private fun importFirmware(zip: File) {
        if (!zip.isFile) { toast(locale.str(R.string.fw_import_failed, zip.name)); return }
        lifecycleScope.launch {
            val n = withContext(Dispatchers.IO) {
                runCatching { firmwareRepo.unpack(zip) }
            }
            n.onSuccess { toast(locale.str(R.string.fw_imported, zip.name, it)); envCheck.refresh() }   // the chip's colour follows it at once
                .onFailure { toast(locale.str(R.string.fw_import_failed, zip.name)) }
        }
    }

    /**
     * 导入金手指包：社区的 Atmosphère 文件（App 不带，玩家从社区仓库或论坛上拿 zip）。
     * 解到 App 自己的目录（files/cheats/<title ID>/<build ID>.txt），抽屉里那个游戏就有金手指了。
     * 分辨率类的条目不要（App 有自己的渲染比例），只有分辨率的文件不写。
     */
    private fun importCheats(zip: File) {
        if (!zip.isFile) { toast(locale.str(R.string.cheats_import_failed, zip.name)); return }
        lifecycleScope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching { CheatRepo.importZip(zip, filesDir) }
            }
            r.onSuccess { s ->
                AppLog.line("cheats: imported ${s.files} file(s) for ${s.gameCount} game(s) from ${zip.name}")
                toast(locale.str(R.string.cheats_imported_toast, s.gameCount, s.files))
                cheatsChanged++
            }.onFailure { e ->
                AppLog.line("[RED] cheats: the import failed: ${e.message}")
                toast(locale.str(R.string.cheats_import_failed, e.message ?: zip.name))
            }
        }
    }

    /** 忘掉导入的金手指：App 私有目录里的那一份删掉（游戏里的那些也不再有） */
    private fun clearCheats() {
        CheatRepo.root(filesDir).deleteRecursively()
        AppLog.line("cheats: the imported cheats were removed")
        toast(locale.str(R.string.cheats_cleared))
        cheatsChanged++
    }

    /** 导入过的金手指：几个游戏、几个文件（设置页那一行） */
    private fun cheatGames(): Int {
        cheatsChanged            // 导入或清除之后这一行要重画
        return CheatRepo.root(filesDir).listFiles()?.count { it.isDirectory } ?: 0
    }

    private fun cheatFiles(): Int {
        cheatsChanged
        return CheatRepo.root(filesDir).listFiles()?.sumOf { dir ->
            dir.listFiles()?.count { it.name.endsWith(".txt") } ?: 0
        } ?: 0
    }

    /**
     * 导入游戏档案包：App 不带档案（几百 MB 的着色器表），玩家导入一份，移植器在自己的目录里找到它们。
     * 导入是移植器做的（它知道档案包的格式），App 只把包放进自己的目录（客机进程看不见手机的存储）。
     */    private fun importProfiles(zip: File) {
        if (!zip.isFile) { toast(locale.str(R.string.profiles_import_failed, zip.name)); return }
        envCheck.importProfiles(zip) { ok, message ->
            if (ok) toast(locale.str(R.string.profiles_imported_toast, envCheck.profilesCount))
            else toast(locale.str(R.string.profiles_import_failed, message.ifBlank { zip.name }))
            envCheck.refresh()
        }
    }

    /**
     * 门：解析 → busy → START / RESUME / REFUSE。卡片、详情面板、桌面快捷方式都走这一条路，
     * 同一个游戏从哪个入口进来结果都一样。
     *
     * @param rebuild 重建运行库再开（闪退后的「重新构建」）：门还是那一扇，只是游戏页多了一件差事
     */
    private fun runGate(pack: File, name: String, rebuild: Boolean = false) {
        LibraryFileScanner.portFromPack(pack)?.let { ported ->
            when (LibraryLogic.launchDecision(player.processAlive(this), player.currentTitleId(), ported.titleId)) {
                // 跑的正是这一个：带回前台，不重启
                LaunchDecision.RESUME -> GameActivity.resume(this)
                // 跑的是别的：把在跑的那个带回前台 + 说明，被点的这个不起
                LaunchDecision.REFUSE -> {
                    GameActivity.resume(this)
                    toast(if (player.currentName().isBlank()) locale.str(R.string.runtime_busy)
                          else locale.str(R.string.lib_game_still_running, player.currentName()))
                }
                // 没有游戏在跑：全新启动
                LaunchDecision.START -> launchStart(ported, name, rebuild)
            }
        } ?: toast(locale.str(R.string.main_cannot_run_not_a_pack, pack.name))
    }

    /**
     * 桌面快捷方式的点击（冷启动落在 onCreate，热启动落在 onNewIntent）：与库页卡片走同一扇门。
     * 解析先按记住的包路径验证一次（库的记忆）——命中只是一次文件验证，不等全量扫描；没命中再等
     * 库首次扫描完成（仿 launchTab 的等待）。扫完还没有，这个游戏就不在了（图标已置灰的路径）。
     */
    private fun onShortcut(titleId: String) {
        if (resolveShortcutByMemory(titleId)) { if (!isTaskRoot) finish(); return }
        lifecycleScope.launch {
            val games = snapshotFlow { library.scanning to library.games }
                .filter { (scanning, games) -> scanning || games.isNotEmpty() }   // 扫描中，或已经有卡
                .map { (scanning, games) -> if (scanning) null else games }        // 扫描结束后交出结果
                .filterNotNull()
                .first()
            val hit = games.firstOrNull { it.titleId.equals(titleId, ignoreCase = true) }?.pack
            if (hit != null) runGate(hit.pack, hit.name)
            else toast(locale.str(R.string.shortcut_disabled))
            if (!isTaskRoot) finish()   // 叠在游戏页上面的那份多余实例退掉：任务里还是 游戏页 > 库页
        }
    }

    /** 按记住的包路径验证一次（不等库扫描）：命中就过门 */
    private fun resolveShortcutByMemory(titleId: String): Boolean {
        val path = try { prefs.json(PrefsStore.LIB_PACKS).optString(titleId.uppercase()) } catch (_: Exception) { "" }
        if (path.isEmpty()) return false
        val ported = LibraryFileScanner.portFromPack(File(path)) ?: return false
        if (!ported.titleId.equals(titleId, ignoreCase = true)) return false
        runGate(ported.pack, ported.name)
        return true
    }

    /**
     * 门放行的 START：占用检查（构建占用着流水线）→ 账本标记（fail-safe 断言住在这里）→ 把包交给
     * 游戏页。宿主的指纹检查与运行库重建都发生在游戏页自己的 prepare 里（旧版宿主在那儿就地重建）。
     */
    private fun launchStart(ported: Ported, name: String, rebuild: Boolean = false) {
        if (port.running) {
            toast(locale.str(R.string.runtime_busy))
            return
        }
        prefs.put(PrefsStore.PLAYER_LAST_START, System.currentTimeMillis().toString())
        player.markLaunched(ported.titleId, name)   // 冷启动读回的身份（进程活着时它就是答案）
        Player.run(this, ported, name, rebuild) { ok ->
            if (!ok) toast(locale.str(R.string.main_cannot_run_no_host, ported.pack.name) + "\n" + locale.str(R.string.runtime_play_failed))
        }
    }

    override fun onResume() {
        super.onResume()
        onboarding.storageOk = storageGranted()   // the permission may have been given in the background
        onboarding.batteryOk = batteryUnrestricted()   // so may the battery exemption
        // 回到前台：顶栏胶囊的两个事实重读一遍（玩家可能在后台改了文件）
        envCheck.refresh()
        // 回到库页：卡片重扫一遍（游戏页的 prepare 会在背后升级包）
        library.rescan()
        if (Build.VERSION.SDK_INT >= 30) {
            val started = prefs.str(PrefsStore.PLAYER_LAST_START).toLongOrNull() ?: 0L
            // 崩溃检测也问账本：processAlive() 是账本给全 app 的同步出口（账本之外没有第二处进程判断）
            if (started > 0 && !player.processAlive(this)) {
                val manager = getSystemService(ActivityManager::class.java)
                val exits = runCatching {
                    manager.getHistoricalProcessExitReasons(packageName, 0, 16).filter {
                        it.processName.endsWith(Player.PROCESS_SUFFIX) && it.timestamp >= started &&
                            isCrash(it.reason, it.status)
                    }
                }.getOrDefault(emptyList())
                if (exits.isNotEmpty()) {
                    prefs.put(PrefsStore.PLAYER_LAST_START, null)
                    // 闪退的不是 toast 能说清的：弹框把三条路摆出来——重新构建、重新移植、反馈
                    crash = CrashReport(player.currentTitleId(), player.currentName())
                    // 这局的档案记一笔：出事时只有 app 在场，玩家的「它又崩了」得有地方落
                    Gamespec.appendEvent(
                        paths.nxHome,
                        player.currentTitleId(),
                        Gamespec.EXIT,
                        "process exited abnormally (${exits.first().reason})",
                    )
                }
            }
        }
    }

    /**
     * 这是不是一次闪退：Android 记的那条退出理由说了算。
     *
     * 宿主自己接住信号后走 _exit(128+sig)（dm/host/crash.c），系统只看到「自己退出」——退出码 >= 128
     * 同样是闪退（真机上抓到的就是这种：EXIT_SELF + 139 = 128+SIGSEGV）。
     * 游戏自己撞上 SDK 的致命 Break 时宿主退的是 42（hle_svc.c）：那是游戏自己的报错，屏幕上本该有
     * 提示——这里把它算成闪退，好让玩家看到「重新构建 / 重新移植 / 反馈」那三条路。
     *
     * 不算闪退的：App 自己收尾时杀的那次是 SIGKILL（9）；SIGTERM（15）是礼貌终止（宿主装了自己的
     * 优雅退出，出来的是 EXIT_SELF 0），排除它只兜住那扇门还没装好的窗口期；系统内存不够杀的那次
     * 记的是 REASON_LOW_MEMORY，根本走不到这里。后台被杀（LOW_MEMORY）与卡死被 ANR 杀同样不算：
     * 「重新构建」救不了内存和挂死。
     */
    private fun isCrash(reason: Int, status: Int): Boolean = when (reason) {
        ApplicationExitInfo.REASON_CRASH, ApplicationExitInfo.REASON_CRASH_NATIVE -> true
        ApplicationExitInfo.REASON_EXIT_SELF -> status >= 128 || status == EXIT_GAME_FATAL
        ApplicationExitInfo.REASON_SIGNALED -> status != SIGNALED_KILL && status != SIGNALED_TERM
        else -> false
    }

    /**
     * 手柄中心开着：手柄的键只进示波，不进库页（库页的按钮不该被手柄按到）。
     * Back 不在这里管：面板自己收（Compose 的 BackHandler）。
     */
    override fun dispatchKeyEvent(e: KeyEvent): Boolean {
        // 手柄中心开着：手柄设备的键只进示波，不进库页。
        // 判据是「这个事件来自手柄设备」，不是「keyCode 是不是手柄键」：有的 ROM 会把
        // 手柄的 B 键再发一个 BACK（小米就是这样），漏下去就把中心关了。
        // 导航条与手势的 Back 不是手柄设备：它们照旧走（BackHandler 关中心）。
        if (padCenterOpen && isGamepad(e.deviceId)) {
            if (GamepadScan.devices.value.none { it.id == e.deviceId }) GamepadScan.refreshNow(this)
            // 认上报方式时，这一下是「测量」，不是按键：不进示波
            if (padController.probing) {
                AppLog.line("pad: a key while the probe waits: device=${e.deviceId} scan=${e.scanCode} key=${e.keyCode}")
            }
            if (padController.probeKey(e.deviceId, e.scanCode, e.keyCode)) return true
            PadTestInput.onKey(e) { deviceId, scan, key -> padController.resolveTarget(deviceId, scan, key) }
            return true
        }
        // 手柄的键 → 界面导航：库页因此能用手柄选游戏、打开与关掉配置面板。
        val nav = navKeyOf(e)
        if (nav != null) {
            val down = e.action == KeyEvent.ACTION_DOWN
            // 按住不放时按节奏连发（首键立即），别一次跳过好几个
            if (down && NavKeys.repeatAllowed(e.repeatCount)) UiInput.emit(nav)
            return true
        }
        return super.dispatchKeyEvent(e)
    }

    /** 摇杆与扳机：中心开着的时候只进示波；中心关着的时候摇杆当方向键。 */
    override fun onGenericMotionEvent(e: MotionEvent): Boolean {
        if (padCenterOpen) {
            val info = GamepadScan.devices.value.firstOrNull { it.id == e.deviceId }
            val deadzone = info?.let { padController.deadzoneOf(it) } ?: PadCalibration.DEFAULT_DEADZONE
            PadTestInput.onMotion(e, deadzone)
            return true
        }
        // 摇杆当方向键：十字键帽优先，左摇杆兜底。边沿触发——推到底发一次，回中才能再走一步，
        // 不然摇杆一推就一路走到底。扳机与肩键不参与导航。
        if (isGamepad(e.deviceId)) {
            // 两边各记各的边沿：帽子的方向与摇杆的方向不是一回事
            val hat = hatEdge.onAxis(
                e.getAxisValue(MotionEvent.AXIS_HAT_X), e.getAxisValue(MotionEvent.AXIS_HAT_Y))
            val stick = stickEdge.onAxis(
                e.getAxisValue(MotionEvent.AXIS_X), e.getAxisValue(MotionEvent.AXIS_Y))
            val dir = hat ?: stick
            if (dir != null) UiInput.emit(dir)
            return true
        }
        return super.onGenericMotionEvent(e)
    }

    /**
     * 这个按键是不是给界面的导航动作。
     *
     * 真手柄：面键按**位置**认（扫描码：底下那颗 = 确认，右边那颗 = 返回）——
     * 系统给的 keyCode 是按手柄上印的字翻的，各家不一样。十字键按 keyCode（`DPAD_*` 都一样）。
     * 手柄自己上报的系统返回键也当返回：小米等 ROM 会把面键的返回再报一个 BACK，
     * 一起收掉就不会「既关掉浮层又退出 App」。导航条与手势的 Back 不是手柄设备，照旧走系统。
     *
     * 调试构建：还认虚拟设备（`adb shell input keyevent`）注进来的十字键与面键——
     * 没有手柄时也能在真机上验这条通路。只认这一小组键，软键盘的键不碰。
     */
    private fun navKeyOf(e: KeyEvent): NavKey? {
        if (isGamepad(e.deviceId)) return NavKeys.fromKeyEvent(e.scanCode, e.keyCode)
        if (BuildConfig.DEBUG && isVirtualDevice(e.deviceId)) return NavKeys.fromInjectedKeyCode(e.keyCode)
        return null
    }

    /** 这只设备是虚拟设备吗（`adb shell input` 注进来的键都算）。 */
    private fun isVirtualDevice(deviceId: Int): Boolean =
        InputDevice.getDevice(deviceId)?.isVirtual == true

    /** 这只设备是手柄吗（虚拟设备不算：小米常驻一个 uinput-xiaomi，它说是手柄却从不发输入）。 */
    private fun isGamepad(deviceId: Int): Boolean {
        val manager = getSystemService(InputManager::class.java) ?: return false
        val device = manager.getInputDevice(deviceId) ?: return false
        return GamepadScan.isGamepad(device)
    }


    /**
     * 桌面图标那条 intent 会送到任务根的**已有**那个库页实例上（栈的顺序不动，游戏页还在最上面）。
     * 有些 ROM 会把任务根拉到前台，库页就盖住了游戏——所以这里再把游戏页顶回最前。
     */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        if (intent.getStringExtra(EXTRA_BUILD_ID).orEmpty().isNotEmpty()) {
            launchTab = intent.getIntExtra(EXTRA_TAB, 0)
            launchBuildId = intent.getStringExtra(EXTRA_BUILD_ID).orEmpty()
        }
        if (isLauncherEntry(intent) && player.processAlive(this)) GameActivity.resume(this)
        // 桌面快捷方式的点击（热启动这一条）
        if (intent.action == GameShortcuts.ACTION) {
            intent.getStringExtra(GameShortcuts.EXTRA_TITLE_ID)?.let { onShortcut(it) }
        }
    }

    /**
     * 「打开 App」的那一条：桌面图标的 intent（MAIN/LAUNCHER）。
     * 别的入口不是——通知点进来是要去构建页的，玩家明确要去那一页，游戏不该把它抢走。
     */
    private fun isLauncherEntry(i: Intent?): Boolean =
        i?.action == Intent.ACTION_MAIN && i.hasCategory(Intent.CATEGORY_LAUNCHER)

    /** The phone's language changed (configChanges holds it): the app's words are read again */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        locale.configurationChanged()
    }

    // ---- the storage (the activity's own privilege) ----------------------------------------------------------

    /** The shared storage: the game files and the ports the tool makes. From Android 11 the old permissions are
     * not enough: the app needs the all-files access, which the user gives once */
    private fun storageGranted(): Boolean {
        if (Build.VERSION.SDK_INT >= 30) return Environment.isExternalStorageManager()
        return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
    }

    fun askStorage() {
        try {
            if (Build.VERSION.SDK_INT >= 30) {
                startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")))
            } else {
                requestPermissions(arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE,
                                          Manifest.permission.WRITE_EXTERNAL_STORAGE), 1)
            }
        } catch (e: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            } catch (e2: Exception) {
                toast(locale.str(R.string.main_no_permission_settings))
            }
        }
    }

    // ---- the battery (the system's own privilege) ------------------------------------------------------------

    /**
     * Whether the app is exempt from the power saving. The unpack and a port are long background jobs:
     * the power saving stops them halfway without it.
     *
     * Some ROMs never report the exemption (the setting lives in their own power manager), and a phone
     * that cannot answer must not look broken: a failure counts as exempt. The check is a hint, not a
     * gate, so nothing depends on the answer being right.
     */
    private fun batteryUnrestricted(): Boolean = try {
        val pm = getSystemService(PowerManager::class.java)
        pm == null || pm.isIgnoringBatteryOptimizations(packageName)
    } catch (e: Exception) {
        true
    }

    /**
     * Android's own prompt: the player allows the app to run in the background there. The list of the
     * exempt apps is the fallback for the ROMs that have no prompt of their own.
     */
    fun askBattery() {
        try {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                 Uri.parse("package:$packageName")))
        } catch (e: Exception) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (e2: Exception) {
                toast(locale.str(R.string.main_no_battery_settings))
            }
        }
    }

    // ---- after the port (the activity's own privilege) -----------------------------------------------------------

    fun versionName(): String = AppVersion.of(this).ifEmpty { "?" }

    fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    /**
     * 导出一局的攻关档案：打包器在环境里跑，zip 放进下载目录，再把玩家送到提 issue 的页面。
     *
     * 档案本身不动——导出是快照，导出完了还能继续往里记。
     */
    private fun exportGamespec(titleId: String) {
        lifecycleScope.launch {
            exporter.export(this@MainActivity, titleId)
                .onSuccess { target ->
                    toast(locale.str(R.string.agent_gamespec_exported, target.name))
                    openGamespecIssue(this@MainActivity)
                }
                .onFailure {
                    toast(locale.str(R.string.agent_gamespec_export_failed, it.message.orEmpty()))
                }
        }
    }

    /**
     * The log bundle's folder in the cache: the FileProvider serves it (res/xml/file_paths.xml), and the
     * bundles older than a week are deleted when a new one is packed.
     */
    private fun bundleDir() = File(cacheDir, "shared-logs")

    /** Sends the log bundle (a zip) out; nothing when there was nothing to pack */
    private fun shareBundle(zip: File?, titleRes: Int, emptyRes: Int) {
        if (zip == null) {
            toast(locale.str(emptyRes))
            return
        }
        try {
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", zip)
            val send = Intent(Intent.ACTION_SEND).setType("application/zip").putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            startActivity(Intent.createChooser(send, locale.str(titleRes)))
        } catch (e: Exception) {
            AppLog.line("[RED] the log bundle could not be shared: ${e.message}")
            toast(locale.str(R.string.main_log_bundle_failed))
        }
    }

    // ---- Activity-owned state holders injected by Hilt ------------------------------------------------------------

}
