package com.nx.android.feature.gamedetail

import android.content.ActivityNotFoundException
import android.content.Intent
import android.os.Environment
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Android
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.CleaningServices
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.FolderOpen
import androidx.compose.material.icons.filled.GridView
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.SdCard
import androidx.compose.material.icons.filled.Tune
import androidx.compose.material.icons.filled.ViewAgenda
import androidx.compose.material.icons.outlined.VideogameAsset
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.BlurredEdgeTreatment
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.blur
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.lifecycle.viewmodel.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.nx.android.R
import com.nx.android.agent.ui.AgentEntry
import com.nx.android.app.GameShortcuts
import com.nx.android.appstate.LibraryState
import com.nx.android.appstate.PortState
import com.nx.android.domain.drivers.Driver
import com.nx.android.data.GameIcon
import com.nx.android.data.GameLog
import com.nx.android.ExportService
import com.nx.android.data.AdbPairing
import com.nx.android.appstate.ExportState
import com.nx.android.data.LogBundle
import com.nx.android.data.SaveShare
import com.nx.android.data.StorageVolumes
import com.nx.android.domain.GameIdentity
import com.nx.android.domain.GAME_FILE_EXTENSIONS
import com.nx.android.domain.GameCleanup
import com.nx.android.domain.GameEntry
import com.nx.android.domain.GameApkExport
import com.nx.android.domain.GameStatus
import com.nx.android.domain.GameApkExportService
import com.nx.android.domain.GameRef
import com.nx.android.domain.LibraryLogic
import com.nx.android.domain.PackMover
import com.nx.android.domain.PortablePack
import com.nx.android.domain.Ported
import com.nx.android.domain.saves.SaveRepository
import com.nx.android.domain.saves.SaveSource
import com.nx.android.domain.saves.SaveTarget
import com.nx.android.data.saves.SaveIo
import com.nx.android.domain.playback.RunOptionsSnapshot
import com.nx.android.app.AppActions
import com.nx.android.core.ui.LocalAppLocale
import com.nx.android.core.ui.components.CapsuleButton
import com.nx.android.core.ui.components.Hint
import com.nx.android.feature.filepicker.PickerMode
import com.nx.android.feature.filepicker.PickerRequest
import com.nx.android.core.ui.components.PickRow
import com.nx.android.core.ui.components.QuietButton
import com.nx.android.core.ui.components.StatusDot
import com.nx.android.core.ui.components.rememberGameIcon
import com.nx.android.core.ui.components.sizeText
import com.nx.android.core.ui.nav.NavKey
import com.nx.android.core.ui.nav.OnNavKey
import com.nx.android.core.ui.failureText
import com.nx.android.core.ui.theme.NxPalette
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File


@Composable
private fun statusLabel(s: GameStatus): String = when (s) {
    GameStatus.NOT_PORTED -> stringResource(R.string.common_not_ported)
    GameStatus.PORTING -> stringResource(R.string.common_porting)
    GameStatus.DONE -> stringResource(R.string.common_done)
}

@Composable
private fun experimentalTag(ported: Ported?): String? =
    if (ported?.status == "experimental") stringResource(R.string.lib_experimental) else null

private fun versionTag(ported: Ported?): String? =
    ported?.display?.trim()?.takeIf { it.isNotEmpty() }

private enum class Removal { CACHE, DELETE, FORGET }

/** 一次破坏性动作的请求：做什么、要删哪些东西、哪些够不着（卡不在时） */
private data class RemovalRequest(val kind: Removal, val plan: GameCleanup.Plan,
                                  val unreachable: List<File> = emptyList())

/**
 * 导出 APK 的说明框里要说清的事：APK 落在哪、有多大、数据放在哪、什么时候搬进游戏自己的目录。
 * 框里的每一句都是玩家要知道的（APK 得自己装，数据最后才搬）。
 */
private data class ApkExportPlan(
    val target: File,          // 落点：APK 在这里（数据不进玩家的存储）
    val dataBytes: Long,       // 数据有多大
    val gameDir: String,       // 导出游戏自己的目录（数据最后搬进这里）
    val packageName: String,   // 导出游戏的包名
)

/**
 * 导出 APK 失败的原因：服务给的是代码，这里翻成玩家看得懂的话。
 */
@Composable
private fun apkFailureText(failure: String?): String {
    val locale = LocalAppLocale.current
    return when (failure) {
        "exists" -> locale.str(R.string.lib_apk_export_err_exists)
        "no_space" -> locale.str(R.string.lib_apk_export_err_space)
        "no_romfs" -> locale.str(R.string.lib_apk_export_err_romfs)
        "no_manifest", "no_package", "no_pack" -> locale.str(R.string.lib_apk_export_err_pack)
        "build_failed", "no_font" -> locale.str(R.string.lib_apk_export_err_build)
        "no_channel" -> locale.str(R.string.lib_apk_export_err_channel)
        null, "" -> locale.str(R.string.common_error_unknown_reason)
        else -> failure
    }
}

/**
 * 移植配置面板：文件路径、状态与该游戏自己的选项，开始移植与安装也从这里走。
 * 由页面的根在最上层画（MainScreen），它的遮罩要盖住顶栏。
 */
@Composable
fun GameDetailRoute(lib: LibraryState, port: PortState,
                    e: GameEntry, installedDrivers: List<Driver>, actions: AppActions, onGoBuilds: () -> Unit,
                    onRequest: (PickerRequest) -> Unit, onClose: () -> Unit, navActive: Boolean = false,
                    onOpenAgent: () -> Unit = {}, agentVisible: Boolean = true) {
    val viewModel: GameDetailViewModel = hiltViewModel(key = "game-detail-${e.key}")
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()
    LaunchedEffect(e.titleId, e.pack?.pack) { viewModel.open(e.titleId, e.pack?.pack) }
    DisposableEffect(viewModel, e.titleId) {
        onDispose { viewModel.close(e.titleId) }
    }
    GameDetailScreen(lib, port, e, installedDrivers, viewModel.saveRepository, viewModel.saveIo,
        viewModel.exportService, viewModel.exportState,
        uiState, viewModel::selectLanguage, viewModel::selectDriver, actions, onGoBuilds, onRequest, onClose,
        navActive = navActive, onOpenAgent = onOpenAgent, agentVisible = agentVisible)
}

@Composable
private fun GameDetailScreen(lib: LibraryState, port: PortState,
                        e: GameEntry, installedDrivers: List<Driver>, saveRepository: SaveRepository,
                        saveIo: SaveIo, exportService: GameApkExportService, exportState: ExportState,
                        detailState: GameDetailUiState,
                        onSelectLanguage: (String?) -> Unit, onSelectDriver: (String?) -> Unit,
                        actions: AppActions, onGoBuilds: () -> Unit,
                        onRequest: (PickerRequest) -> Unit, onClose: () -> Unit,
                        navActive: Boolean = false, onOpenAgent: () -> Unit = {},
                        agentVisible: Boolean = true) {
    val locale = LocalAppLocale.current
    val status = lib.statusOf(e)
    // Title ID：游戏的身份（还没构建过的还没有）
    val titleId = detailState.titleId ?: e.titleId
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var menuOpen by remember { mutableStateOf(false) }
    var removal by remember { mutableStateOf<RemovalRequest?>(null) }
    // 删除存档：等玩家确认（删的是游戏自己的进度，不可恢复）
    var pendingDelete by remember { mutableStateOf(false) }
    // 可移动卡（SD 卡）上 App 自己的端口目录：插着才有
    val cardDirs = remember { StorageVolumes.removablePortsDirs(context) }
    // 搬移：等玩家确认的目标目录（null = 没有要搬的）
    var moveTarget by remember { mutableStateOf<File?>(null) }
    var choosingVolume by remember { mutableStateOf(false) }
    var moving by remember { mutableStateOf(false) }
    // 搬移进度：卡上写入很慢，玩家要看得见还在动
    var moveProgress by remember { mutableStateOf<PackMover.Progress?>(null) }
    // 删除/清缓存正在进行（遮罩挡着，不让乱点）
    var removing by remember { mutableStateOf(false) }
    // 导出：把这个移植变成一个文件夹（卡上写入很慢，玩家要看得见还在动）
    var exporting by remember { mutableStateOf(false) }
    var exportProgress by remember { mutableStateOf<PortablePack.Progress?>(null) }
    // 导出 APK：把这个移植变成一个可以自己安装的游戏（先说明白，再动手）
    var apkPlan by remember { mutableStateOf<ApkExportPlan?>(null) }
    // 通道（无线调试开着、App 配对过）：说明框打开时查一次，配好对再查一次（null = 还在查）
    var apkChannel by remember { mutableStateOf<Boolean?>(null) }
    // 配对：码输进系统通知（玩家去设置里拿码，App 退到后台也不丢）；配好了自动继续
    var apkPairForMove by remember { mutableStateOf(false) }
    // 进度与结果在 exportState 那口里：活儿跑在前台 ExportService 里，App 退到后台也不死
    // 正在搬移/删除时：返回键不做事（别把进行中的动作打断，面板也别关）
    BackHandler(enabled = moving || removing || exporting || exportState.running) { }
    BackHandler(enabled = !(moving || removing || exporting || exportState.running)) { onClose() }
    // 手柄的返回键：跟系统的返回键一条路（正在搬移/删除时同样不做事）
    OnNavKey(enabled = navActive && !moving && !removing && !exporting && !exportState.running) { key ->
        if (key == NavKey.Back) onClose()
    }
    // 说明框开着就查一次通道（查在后台：mDNS 要等上几秒）
    LaunchedEffect(apkPlan) {
        if (apkPlan == null) { apkChannel = null; return@LaunchedEffect }
        apkChannel = null
        apkChannel = withContext(Dispatchers.IO) { exportService.paired() }
    }

    /**
     * 开始构建：源文件在就直接带过去；不在了（玩家把它挪走腾空间去了）就请他重新选一个。
     */
    fun build() {
        val src = e.source
        if (src != null) {
            lib.buildsTarget = src
            onClose()
            onGoBuilds()
        } else {
            onRequest(PickerRequest(PickerMode.FILE, GAME_FILE_EXTENSIONS, File("/storage"),
                locale.str(R.string.builds_choose_game_file),
                onPicked = { f ->
                    if (LibraryLogic.sourceMatchesTitle(f.name, e.titleId)) {
                        lib.buildsTarget = f; onClose(); onGoBuilds()
                    } else {
                        actions.onToast(locale.str(R.string.lib_source_mismatch))
                    }
                }))
        }
    }
    // 完成的移植：数据包里带着宿主写的运行日志（log.txt）
    val ported = e.pack
    // 这个游戏的包现在在哪：私有目录，还是卡上
    val packOnCard = ported?.pack?.parentFile?.let { p ->
        cardDirs.firstOrNull { it.second.absolutePath == p.absolutePath }
    }
    // 数据包里的存档（packs 的 saves/）：删包时它们会一起消失
    val packHasSaves = ported?.let {
        val s = File(it.pack, "saves")
        s.isDirectory && s.listFiles()?.isNotEmpty() == true
    } == true
    // 数据包读的是工作区里的 RomFS：工作区是游戏的一部分，清构建缓存会让它跑不起来——那种卡不摆这个按钮
    val cacheLocked = e.romfsSharedWithWorkspace

    /**
     * 破坏性动作：正在构建 / 正在运行就说清楚为什么，不能动；能动就把要删的东西算出来给确认框。
     * 清缓存不动数据包，删游戏连数据包与存档一起删——两个动作的确认框各自写清影响。
     */
    fun askRemoval(kind: Removal) {
        val blocked = lib.removalBlocked(e)
        if (blocked != null) {
            actions.onToast(locale.str(removeBlockedText(blocked)))
            return
        }
        scope.launch {
            val p = withContext(Dispatchers.IO) {
                when (kind) {
                    Removal.CACHE -> lib.planCache(e)
                    // 移出导入的包：什么都不删（那个文件夹是玩家的文件），只是把它从库里拿掉
                    Removal.FORGET -> GameCleanup.Plan(emptyList(), workspaceKnown = true)
                    else -> lib.planRemoval(e)
                }
            }
            // 卡不在时够不着的包：先说清楚（不然玩家以为全删干净了）
            val unreachable = withContext(Dispatchers.IO) { lib.unreachablePacks(e) }
            removal = RemovalRequest(kind, p, unreachable)
        }
    }

    /** 确认之后真的做 */
    fun doRemoval() {
        val req = removal ?: return
        removal = null
        removing = true
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                when (req.kind) {
                    Removal.CACHE -> lib.clearCache(e)
                    Removal.FORGET -> {
                        // 只忘路径：那个文件夹里的文件原地不动
                        if (lib.forgetImported(e)) GameCleanup.Result(GameCleanup.Outcome.DONE)
                        else GameCleanup.Result(GameCleanup.Outcome.FAILED)
                    }
                    else -> lib.remove(e)
                }
            }
            removing = false
            // 游戏从库里删除：它的桌面图标置灰，点下去不再启动（清构建缓存不动桌面图标）
            if (r.outcome == GameCleanup.Outcome.DONE && (req.kind == Removal.DELETE || req.kind == Removal.FORGET)) {
                GameShortcuts.disable(context, e.titleId, locale.str(R.string.shortcut_disabled))
            }
            actions.onToast(
                when (r.outcome) {
                    GameCleanup.Outcome.DONE -> {
                        // 游戏没了，这个抽屉也就没有意义了
                        if (req.kind == Removal.DELETE || req.kind == Removal.FORGET) onClose()
                        val done = when (req.kind) {
                            Removal.CACHE -> locale.str(R.string.lib_remove_cache_done)
                            Removal.FORGET -> locale.str(R.string.lib_forget_done)
                            else -> locale.str(R.string.lib_remove_done)
                        }
                        if (r.workspaceKnown) done else locale.str(
                            if (req.kind == Removal.CACHE) R.string.lib_remove_cache_workspace_unknown
                            else R.string.lib_remove_workspace_unknown)
                    }
                    GameCleanup.Outcome.FAILED -> {
                        // 卡上那份够不着：说清楚是卡上的那一份没删成（不能只说「删除失败」）
                        val onCard = r.failed.filter { it.absolutePath.startsWith("/storage/") &&
                                                       !it.absolutePath.startsWith("/storage/emulated") }
                        if (onCard.isNotEmpty())
                            locale.str(R.string.lib_remove_failed_card, onCard.joinToString { it.absolutePath })
                        else
                            locale.str(R.string.lib_remove_failed_files, r.failed.joinToString { it.name })
                    }
                    GameCleanup.Outcome.BUSY_PORTING -> locale.str(R.string.lib_remove_busy_porting)
                    GameCleanup.Outcome.BUSY_RUNNING -> locale.str(R.string.lib_remove_busy_running)
                    GameCleanup.Outcome.BUSY_MOVING -> locale.str(R.string.lib_pack_busy_moving)
                    GameCleanup.Outcome.WORKSPACE_IN_USE -> locale.str(R.string.lib_remove_cache_workspace_in_use)
                }
            )
        }
    }

    /**
     * 搬移数据包：到可移动卡上，或者搬回内部存储。
     *
     * 正在构建 / 正在运行 / 正在搬都不能搬（说清楚为什么）；没有卡时那个动作不可用。
     * 搬完之前要确认：卡上写入很慢，拔卡就把这次搬移弄坏了。
     */
    fun askMove() {
        val blocked = lib.moveBlocked(e)
        if (blocked != null) {
            actions.onToast(locale.str(removeBlockedText(blocked)))
            return
        }
        when {
            packOnCard != null -> moveTarget = lib.internalPortsDir()          // 搬回内部存储
            cardDirs.isEmpty() -> actions.onToast(locale.str(R.string.lib_pack_no_card))
            cardDirs.size == 1 -> moveTarget = cardDirs[0].second
            else -> choosingVolume = true                                       // 多张卡：先问哪一张
        }
    }

    /** 确认之后真的搬（后台线程，卡上写入很慢） */
    fun doMove(target: File) {
        moveTarget = null
        moving = true
        moveProgress = null
        scope.launch {
            val r = withContext(Dispatchers.IO) { lib.movePack(e, target) { moveProgress = it } }
            moving = false
            moveProgress = null
            actions.onToast(
                if (r.ok) locale.str(R.string.lib_pack_moved)
                else locale.str(R.string.lib_pack_move_failed, r.failure ?: "")
            )
        }
    }

    /** 确认之后真的删存档：删掉活存档与设备存档（删掉了没有由存档那边说了算） */
    fun doDeleteSave() {
        // 存档按数据包清单里的 title id 分着（导出、导入用的是同一个）
        val id = ported?.titleId ?: titleId
        scope.launch {
            val r = saveRepository.erase(id)
            r.onSuccess { removed ->
                actions.onToast(
                    if (removed) locale.str(R.string.lib_deleted) else locale.str(R.string.lib_no_saves))
            }.onFailure {
                actions.onToast(locale.str(R.string.lib_delete_failed, failureText(locale, it)))
            }
        }
    }

    /** 真的导出（后台线程：卡上写入很慢） */
    fun doExport(target: File) {
        exporting = true
        exportProgress = null
        scope.launch {
            val r = withContext(Dispatchers.IO) { lib.exportPack(e, target) { exportProgress = it } }
            exporting = false
            exportProgress = null
            actions.onToast(
                if (r.ok) locale.str(R.string.lib_pack_export_done, r.folder)
                else locale.str(R.string.lib_pack_export_failed, r.failure ?: "")
            )
        }
    }

    /**
     * 导出：玩家选一个落点，App 把这个移植写成一个文件夹（数据包 + 散装的游戏文件）。
     *
     * 导出不动 App 里的任何东西：这个游戏照常能玩。
     */
    fun askExport() {
        onRequest(PickerRequest(PickerMode.DIR, emptySet(), File("/storage"),
            locale.str(R.string.lib_pack_export_pick),
            onPicked = { target -> doExport(target) }))
    }

    /**
     * 导出 APK：先把要做的事说清楚（APK 落在哪、有多大、数据直接进游戏自己的目录、装与搬都走 App 自己的
     * 通道），玩家点头才动手。App 自己装：不替玩家拉起安装器，但 APK 也不用玩家去找。
     */
    fun askExportApk() {
        val pack = e.pack ?: return
        val manifest = PortablePack.readManifest(pack.pack)
        val packageName = manifest?.optString("package").orEmpty()
        if (packageName.isEmpty()) { actions.onToast(locale.str(R.string.lib_apk_export_err_pack)); return }
        val romfs = if (pack.romfsAt.isNotEmpty()) File(pack.romfsAt) else File(pack.pack, PortablePack.ROMFS)
        if (!romfs.isDirectory) { actions.onToast(locale.str(R.string.lib_apk_export_err_romfs)); return }
        val bytes = GameApkExport.treeBytes(pack.pack) +
            (if (romfs.parentFile?.absolutePath != pack.pack.absolutePath) GameApkExport.treeBytes(romfs) else 0L)
        apkPlan = ApkExportPlan(
            target = File(Environment.getExternalStorageDirectory(), "NX2A-Games"),
            dataBytes = bytes,
            gameDir = GameApkExport.gameFilesDir(packageName),
            packageName = packageName,
        )
    }

    /** 换个落点：App 自带的目录选择器（APK 落在这里；数据不进玩家的存储） */
    fun pickExportApkDir(plan: ApkExportPlan) {
        onRequest(PickerRequest(PickerMode.DIR, emptySet(), plan.target,
            locale.str(R.string.lib_apk_export_pick),
            onPicked = { target -> apkPlan = plan.copy(target = target) }))
    }

    /** 导出要用的游戏身份：给服务与实现的一把钥匙 */
    fun gameRef(): GameRef? {
        val pack = e.pack ?: return null
        return GameRef(e.titleId, e.label, pack.pack, pack.romfsAt)
    }

    /** 真的导出：活儿交给前台 ExportService（App 退了也活着）；后台起不了服务时就地跑（罕见路径） */
    fun doExportApk(plan: ApkExportPlan) {
        val ref = gameRef() ?: return
        apkPlan = null
        try {
            ExportService.start(context, ref, plan.target.absolutePath)
        } catch (err: Exception) {
            // 从后台起前台服务被系统拒（配对回调里的那条路）：就地跑，App 在前台时没有区别
            exportState.begin(e.label)
            scope.launch {
                val r = withContext(Dispatchers.IO) {
                    exportService.export(ref, plan.target, { p -> exportState.onProgress(p) }, { })
                }
                exportState.finish(r)
            }
        }
    }

    /** 数据再搬一次（重试）：活儿同样交给前台服务；已到的部分不用清，tar 会盖掉它 */
    fun moveAgain() {
        val r = exportState.result ?: return
        val ref = gameRef() ?: return
        try {
            ExportService.startMove(context, ref, r.packageName)
        } catch (err: Exception) {
            exportState.begin(e.label)
            scope.launch {
                val moved = withContext(Dispatchers.IO) {
                    exportService.moveData(ref, r.packageName, { p -> exportState.onProgress(p) })
                }
                exportState.finish(if (moved) r.copy(ok = true, failure = null, installed = true, moved = true)
                                   else r.copy(ok = false, failure = "move_failed"))
            }
        }
    }

    /** 配好了自动继续：为搬数据配的就去搬，为开始导出配的就开始导出 */
    fun apkPairContinue() {
        if (apkPairForMove) moveAgain() else apkPlan?.let { doExportApk(it) }
    }

    /**
     * 配对：码输进系统通知（PhantomFix 同一条路）——玩家去设置里拿码，App 退到后台也不丢，输完立即配。
     * 配好了自动继续（apkPairContinue）。
     */
    fun startPairing(forMove: Boolean) {
        apkPairForMove = forMove
        AdbPairing.begin(context) { _, _, _ ->
            scope.launch {
                AdbPairing.cancel(context)
                apkPairContinue()
            }
        }
        AdbPairing.openDeveloperOptions(context)
    }

    /** 游戏运行日志：宿主把它写在了数据包里（上一轮的在 log.prev.txt），打成日志包再发出去 */
    fun shareGameLog(target: Ported) {
        if (!actions.storageOk()) { actions.onToast(locale.str(R.string.lib_log_needs_storage)); return }
        val game = e.label
        val facts = GameLog.facts(game, target.titleId, target.display, target.status, target.playerApiRevision)
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching {
                    GameLog.bundle(LogBundle.deviceText(context), game, facts, target.pack, SaveShare.packagesDir(context))
                }
            }
            r.onSuccess { bundle ->
                if (bundle == null) {
                    actions.onToast(locale.str(R.string.lib_no_runtime_log))
                } else {
                    runCatching {
                        context.startActivity(
                            Intent.createChooser(SaveShare.intent(context, bundle), locale.str(R.string.main_share_log)))
                    }.onFailure { e ->
                        actions.onToast(if (e is ActivityNotFoundException) locale.str(R.string.lib_no_receiver)
                        else locale.str(R.string.lib_share_failed, failureText(locale, e)))
                    }
                }
            }.onFailure {
                actions.onToast(locale.str(R.string.lib_log_export_failed, failureText(locale, it)))
            }
        }
    }

    Box(
        Modifier.fillMaxSize()
            // 遮罩：左边留出游戏自己的画面，往右渐渐暗下去接到面板（不是一块死黑）
            .background(
                Brush.horizontalGradient(
                    0f to Color.Transparent,
                    0.28f to Color(0x8C0E0E0F),
                    0.44f to Color(0xD90E0E0F),
                    1f to Color(0xF20E0E0F),
                )
            )
            .clickable { onClose() },
        contentAlignment = Alignment.CenterEnd,
    ) {
        Box(
            Modifier
                .width(460.dp)
                .fillMaxHeight()
                .background(NxPalette.Surface),
        ) {
        Column(
            Modifier
                .fillMaxSize()
                .clickable(enabled = false) {}
                .verticalScroll(rememberScrollState())
                // 底部多留一截：右下角那个入口占着的地方，滚到最后一项时不被它压住
                .padding(start = 24.dp, end = 24.dp, top = 24.dp, bottom = 76.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Column(Modifier.weight(1f)) {
                    Text(
                        e.label,
                        style = MaterialTheme.typography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        (listOfNotNull(titleId, versionTag(ported), statusLabel(status), experimentalTag(ported)) +
                            com.nx.android.feature.library.needsTags(lib.profileOf(titleId), ported)).joinToString("  ·  "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                // 已完成的游戏才有可管理的产物
                if (status == GameStatus.DONE) {
                    Box {
                        QuietButton(locale.str(R.string.lib_manage), onClick = { menuOpen = !menuOpen },
                            modifier = Modifier.width(112.dp),
                            trailing = { Icon(Icons.Filled.KeyboardArrowDown, null, Modifier.size(18.dp)) })
                        DropdownMenu(
                            expanded = menuOpen,
                            onDismissRequest = { menuOpen = false },
                        ) {
                            DropdownMenuItem(
                                text = { Text(locale.str(R.string.main_share_log)) },
                                leadingIcon = { Icon(Icons.Filled.Description, null, Modifier.size(18.dp)) },
                                onClick = {
                                    menuOpen = false
                                    val p = ported
                                    if (p == null) actions.onToast(locale.str(R.string.lib_artifact_missing))
                                    else shareGameLog(p)
                                },
                            )
                            // 发送到桌面：桌面快捷方式（pin shortcut），点击与库页卡片走同一扇门（已完成的游戏才有）
                            DropdownMenuItem(
                                text = { Text(locale.str(R.string.lib_pin_shortcut)) },
                                leadingIcon = { Icon(Icons.Filled.Home, null, Modifier.size(18.dp)) },
                                onClick = {
                                    menuOpen = false
                                    actions.onSendToDesktop(e)
                                },
                            )
                            // 导入的包已经在玩家自己挑的目录里了：搬它没有意义。
                            // 搬移要有落点：包在卡上（搬回手机），或者有一张插着的卡（搬过去）。
                            if (!e.isImported && (packOnCard != null || cardDirs.isNotEmpty())) {
                                DropdownMenuItem(
                                    text = { Text(locale.str(if (packOnCard != null) R.string.lib_pack_move_back else R.string.lib_pack_move_to_card)) },
                                    leadingIcon = { Icon(Icons.Filled.SdCard, null, Modifier.size(18.dp)) },
                                    onClick = { menuOpen = false; askMove() },
                                )
                            }
                            // 导出：把这个移植变成一个文件夹（数据包 + 散装的游戏文件）
                            // 导入的包本身就是那个文件夹了（还是玩家自己的文件）：再导出只是原样拷一遍
                            if (e.exportable) {
                                DropdownMenuItem(
                                    text = { Text(locale.str(R.string.lib_pack_export_action)) },
                                    leadingIcon = { Icon(Icons.Filled.FolderOpen, null, Modifier.size(18.dp)) },
                                    onClick = { menuOpen = false; askExport() },
                                )
                            }
                            // 导出 APK：把这个移植变成一个可以自己安装的游戏（装不装由玩家决定）
                            if (e.exportable) {
                                DropdownMenuItem(
                                    text = { Text(locale.str(R.string.lib_apk_export_action)) },
                                    leadingIcon = { Icon(Icons.Filled.Android, null, Modifier.size(18.dp)) },
                                    onClick = { menuOpen = false; askExportApk() },
                                )
                            }
                            // 重建运行库：不闪退也要能点名重建（宿主行为变了、存档布局修了这类时候），
                            // 走闪退弹框的同一条路（重建标记一路传到游戏页的 prepare）
                            DropdownMenuItem(
                                text = { Text(locale.str(R.string.lib_rebuild_runtime_action)) },
                                leadingIcon = { Icon(Icons.Filled.Build, null, Modifier.size(18.dp)) },
                                onClick = {
                                    menuOpen = false
                                    val p = ported
                                    if (p == null) actions.onToast(locale.str(R.string.lib_artifact_missing))
                                    else actions.onRunRebuild(p.pack, e.label)
                                },
                            )
                            if (!cacheLocked && !e.isImported) {
                                DropdownMenuItem(
                                    text = { Text(locale.str(R.string.lib_remove_cache_action)) },
                                    leadingIcon = { Icon(Icons.Filled.CleaningServices, null, Modifier.size(18.dp)) },
                                    onClick = { menuOpen = false; askRemoval(Removal.CACHE) },
                                )
                            }
                            // 删除存档：只删游戏自己的进度，数据包与游戏文件不动
                            DropdownMenuItem(
                                text = { Text(locale.str(R.string.lib_delete_saves), color = NxPalette.Danger) },
                                leadingIcon = { Icon(Icons.Filled.DeleteForever, null, Modifier.size(18.dp), tint = NxPalette.Danger) },
                                onClick = { menuOpen = false; pendingDelete = true },
                            )
                            if (e.isImported) {
                                // 移出：只忘路径，那个文件夹里的文件原地不动（那是玩家的文件）
                                DropdownMenuItem(
                                    text = { Text(locale.str(R.string.lib_forget_action), color = NxPalette.Danger) },
                                    leadingIcon = { Icon(Icons.Filled.Delete, null, Modifier.size(18.dp), tint = NxPalette.Danger) },
                                    onClick = { menuOpen = false; askRemoval(Removal.FORGET) },
                                )
                            } else {
                                DropdownMenuItem(
                                    text = { Text(locale.str(R.string.lib_remove_action), color = NxPalette.Danger) },
                                    leadingIcon = { Icon(Icons.Filled.Delete, null, Modifier.size(18.dp), tint = NxPalette.Danger) },
                                    onClick = { menuOpen = false; askRemoval(Removal.DELETE) },
                                )
                            }
                        }
                    }
                }
            }
            // 源文件在的时候告诉玩家它在哪；不在了（挪走腾空间去了）就说明它不在了
            e.sourcePath?.let {
                Hint(it, size = 11.sp)
                if (e.source == null) Hint(locale.str(R.string.lib_source_missing), size = 11.sp)
            }

            // 内容自上而下顺排：不用弹性 spacer 把它压到底（那会在路径与「产物：」之间开一大片空白）；
            // 列本身可滚，存档多时也够得着。

            when {
                status == GameStatus.PORTING -> {
                    Hint(locale.str(R.string.lib_porting_see_builds))
                    Spacer(Modifier.height(6.dp))
                    CapsuleButton(locale.str(R.string.lib_view_builds), {
                        // 第一次构建还没有源文件的记忆：那就带着正在跑的那个构建的源文件去
                        lib.buildsTarget = e.source ?: port.gameFile.takeIf { port.running }?.let { File(it) }
                        onClose()
                        onGoBuilds()
                    }, modifier = Modifier.fillMaxWidth())
                }
                status == GameStatus.DONE -> {
                    // 导入的包：文件在玩家自己挑的目录里，App 不拥有它
                    if (e.isImported) {
                        Hint(locale.str(R.string.lib_pack_imported_hint), size = 11.sp)
                    }
                    if (ported == null) {
                        Hint(locale.str(R.string.lib_artifact_missing_state))
                    } else {
                        Hint(locale.str(R.string.builds_artifact_path, ported.pack.absolutePath), size = 11.sp)
                        Spacer(Modifier.height(8.dp))
                        RunOptions(installedDrivers, detailState.runOptions,
                            detailState.runOptionsFailure, onSelectLanguage, onSelectDriver)
                        Spacer(Modifier.height(10.dp))
                        SaveRows(ported, e.label, saveRepository, saveIo, actions.onToast)
                        Spacer(Modifier.height(6.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            // 一个「运行」：运行库过期/缺失也点它——门放行后游戏页的 Loading 自己重建。
                            // 占用不在这里拦：点「运行」由门统一裁决（在跑的带回、别的拒绝并说明）。
                            CapsuleButton(locale.str(R.string.builds_run_action), {
                                actions.onRun(ported.pack, e.label)
                            }, modifier = Modifier.weight(1f))
                            CapsuleButton(locale.str(R.string.lib_build_action), {
                                build()
                            }, modifier = Modifier.weight(1f))
                        }
                    }
                }
                else -> {
                    if (ported != null) {
                        // 包在而运行库不齐（过期/缺失）：一样的「运行」，游戏页的 Loading 自己补齐
                        CapsuleButton(locale.str(R.string.builds_run_action), {
                            actions.onRun(ported.pack, e.label)
                        }, modifier = Modifier.fillMaxWidth())
                        Spacer(Modifier.height(8.dp))
                    }
                    // 导入的包够不着了（卡不在？）：说清楚，别让它看着像一个没移植的游戏
                    if (e.isImported && ported == null) {
                        Hint(locale.str(R.string.lib_pack_imported_unreachable), size = 11.sp)
                    } else {
                        Hint(if (e.work != null && e.pack == null) locale.str(R.string.lib_residual_hint)
                             else locale.str(R.string.lib_needs_build_hint))
                    }
                    Spacer(Modifier.height(8.dp))
                    CapsuleButton(locale.str(R.string.lib_build_action), {
                        build()
                    }, modifier = Modifier.fillMaxWidth())
                    // 导入的游戏够不着了：它没法玩，但玩家得能把它从库里拿掉
                    if (e.isImported) {
                        Spacer(Modifier.height(8.dp))
                        QuietButton(locale.str(R.string.lib_forget_action),
                            onClick = { askRemoval(Removal.FORGET) },
                            modifier = Modifier.fillMaxWidth())
                    }
                    // 导入的游戏：它没有构建缓存可清，也没有数据包可删 —— 只有「移出」
                    if (!e.isImported) {
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                            // 清构建缓存：游戏照常能玩，只把能再生的东西清掉
                            // （数据包读的是工作区里的 RomFS 时不行：那种卡只留删除游戏）
                            if (!cacheLocked) {
                                QuietButton(locale.str(R.string.lib_remove_cache_action),
                                    { askRemoval(Removal.CACHE) }, modifier = Modifier.weight(1f))
                            }
                            QuietButton(locale.str(R.string.lib_remove_action),
                                { askRemoval(Removal.DELETE) }, modifier = Modifier.weight(1f))
                        }
                    }
                }
            }
        }
        // 助手的入口：贴在面板自己的右下角，不拖（面板盖住了页面的那一角，入口得由面板带）
        Box(Modifier.align(Alignment.BottomEnd).padding(24.dp)) {
            if (agentVisible) {
                AgentEntry(onClick = onOpenAgent)
            }
        }
        }
    }

    // 删除存档的确认框：写明后果（不可恢复），并指向导出入口
    if (pendingDelete) {
        AlertDialog(
            onDismissRequest = { pendingDelete = false },
            title = { Text(locale.str(R.string.lib_delete_confirm)) },
            text = { Text(locale.str(R.string.lib_delete_confirm_body), style = MaterialTheme.typography.bodyMedium) },
            confirmButton = {
                TextButton(onClick = { pendingDelete = false; doDeleteSave() }) {
                    Text(locale.str(R.string.lib_delete_saves), color = NxPalette.Danger)
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = false }) { Text(locale.str(R.string.common_cancel)) }
            },
        )
    }

    // 搬移的确认框：写明后果（拔卡后不能玩、卸载会连同删掉它）
    moveTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { moveTarget = null },
            title = { Text(locale.str(if (packOnCard != null) R.string.lib_pack_move_back_title else R.string.lib_pack_move_title)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        locale.str(if (packOnCard != null) R.string.lib_pack_move_back_text else R.string.lib_pack_move_text),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Text("· ${target.absolutePath}", style = MaterialTheme.typography.bodySmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            },
            confirmButton = {
                TextButton(onClick = { doMove(target) }) {
                    Text(locale.str(R.string.lib_pack_move_confirm))
                }
            },
            dismissButton = {
                TextButton(onClick = { moveTarget = null }) {
                    Text(locale.str(R.string.common_cancel))
                }
            },
        )
    }

    // 多张卡：问搬到哪一张
    if (choosingVolume) {
        AlertDialog(
            onDismissRequest = { choosingVolume = false },
            title = { Text(locale.str(R.string.lib_pack_choose_volume_title)) },
            text = {
                Column {
                    cardDirs.forEach { (name, dir) ->
                        TextButton(
                            onClick = { choosingVolume = false; moveTarget = dir },
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text(name) }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { choosingVolume = false }) {
                    Text(locale.str(R.string.common_cancel))
                }
            },
        )
    }

    removal?.let { req ->
        // 要删的东西，一样一行：数据包（带存档）、工作区、半成品包
        val items = req.plan.targets.map { t ->
            when (t.kind) {
                GameCleanup.Kind.PACK ->
                    if (packHasSaves) locale.str(R.string.lib_remove_item_pack_saves)
                    else locale.str(R.string.lib_remove_item_pack)
                GameCleanup.Kind.WORKSPACE -> locale.str(R.string.lib_remove_item_workspace)
                GameCleanup.Kind.PARTIAL -> locale.str(R.string.lib_remove_item_partial)
                GameCleanup.Kind.RUNTIME -> locale.str(R.string.lib_remove_item_runtime)
            }
        }
        AlertDialog(
            onDismissRequest = { removal = null },
            title = {
                Text(locale.str(when (req.kind) {
                    Removal.CACHE -> R.string.lib_remove_cache_confirm_title
                    Removal.FORGET -> R.string.lib_forget_confirm_title
                    else -> R.string.lib_remove_confirm_title
                }))
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(
                        when {
                            req.kind == Removal.FORGET -> locale.str(R.string.lib_forget_what)
                            req.kind == Removal.CACHE && req.plan.workspaceInUse -> locale.str(R.string.lib_remove_cache_workspace_in_use)
                            req.kind == Removal.CACHE && items.isEmpty() -> locale.str(R.string.lib_remove_cache_nothing)
                            req.kind == Removal.CACHE && status == GameStatus.DONE -> locale.str(R.string.lib_remove_cache_what_done)
                            req.kind == Removal.CACHE -> locale.str(R.string.lib_remove_cache_what_failed)
                            items.isEmpty() -> locale.str(R.string.lib_remove_what_empty)
                            status == GameStatus.DONE -> locale.str(R.string.lib_remove_what_done)
                            else -> locale.str(R.string.lib_remove_what_failed)
                        },
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    items.forEach {
                        Text("· $it", style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    // 移出导入的包：那个文件夹在哪，写清楚（文件留在原地）
                    if (req.kind == Removal.FORGET) {
                        e.imported?.let {
                            Text(locale.str(R.string.lib_forget_path, it.path),
                                 style = MaterialTheme.typography.bodySmall,
                                 color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    // 卡不在：卡上那份这次删不到，先说清楚
                    if (req.unreachable.isNotEmpty()) {
                        Text(locale.str(R.string.lib_remove_unreachable_card),
                             style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                        req.unreachable.forEach {
                            Text("· ${it.absolutePath}", style = MaterialTheme.typography.bodySmall,
                                 color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
            },
            confirmButton = {
                TextButton(onClick = { doRemoval() }) {
                    Text(locale.str(when (req.kind) {
                        Removal.CACHE -> R.string.common_clear
                        Removal.FORGET -> R.string.lib_forget_confirm_action
                        else -> R.string.common_delete
                    }),
                         color = NxPalette.Danger)
                }
            },
            dismissButton = {
                TextButton(onClick = { removal = null }) {
                    Text(locale.str(R.string.common_cancel))
                }
            },
        )
    }

    /** 配对进行中的那一段（说明框里）：码输进通知最稳，通知没开或想手输就在这里输；状态是 AdbPairing 的 */
    @Composable
    fun PairingInline(notificationsOn: Boolean) {
        when (val st = AdbPairing.state) {
            AdbPairing.State.Idle -> {}
            AdbPairing.State.Done -> Text(locale.str(R.string.lib_apk_pair_done),
                style = MaterialTheme.typography.bodySmall, color = NxPalette.Ready)
            is AdbPairing.State.Working -> Row(verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                Text(st.step, style = MaterialTheme.typography.bodySmall)
            }
            is AdbPairing.State.Waiting, is AdbPairing.State.Failed -> {
                if (st is AdbPairing.State.Failed) {
                    Text(st.message, style = MaterialTheme.typography.bodySmall, color = NxPalette.Danger)
                }
                val port = (st as? AdbPairing.State.Waiting)?.pairPort
                Text(locale.str(if (port != null) R.string.phantom_waiting_port else R.string.phantom_waiting, port ?: 0),
                     style = MaterialTheme.typography.bodySmall,
                     color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (!notificationsOn) {
                    Text(locale.str(R.string.phantom_notifications_off),
                         style = MaterialTheme.typography.bodySmall, color = NxPalette.Danger)
                }
                // 手输（分屏或通知没开时）：跟通知走的是同一次配对，配好了同样自动继续
                var code by remember { mutableStateOf("") }
                var portText by remember { mutableStateOf("") }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, Modifier.weight(1f),
                        singleLine = true, label = { Text(locale.str(R.string.phantom_code_label)) })
                    OutlinedTextField(portText, { portText = it.filter(Char::isDigit).take(5) }, Modifier.weight(1f),
                        singleLine = true, label = { Text(locale.str(R.string.phantom_port_label)) })
                }
                TextButton(onClick = { AdbPairing.submit(context, code, portText.toIntOrNull()) },
                           enabled = code.length == 6) {
                    Text(locale.str(R.string.phantom_pair_button))
                }
            }
        }
    }

    // 导出 APK 的说明框：APK 落在哪、有多大、数据直接进游戏自己的目录、装与搬都走 App 自己的通道。
    // 通道不在就先配对——没有通道，装不了也搬不了（配对的码输进通知里，去设置拿码也不丢）
    apkPlan?.let { plan ->
        AlertDialog(
            onDismissRequest = {
                apkPlan = null
                if (AdbPairing.state !is AdbPairing.State.Working) AdbPairing.cancel(context)
            },
            title = { Text(locale.str(R.string.lib_apk_export_title)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(locale.str(R.string.lib_apk_export_where,
                                    File(plan.target, GameApkExport.apkName(e.label)).absolutePath),
                         style = MaterialTheme.typography.bodyMedium)
                    Text(locale.str(R.string.lib_apk_export_data,
                                    GameApkExport.sizeText(plan.dataBytes), plan.gameDir),
                         style = MaterialTheme.typography.bodyMedium)
                    Text(locale.str(R.string.lib_apk_export_move),
                         style = MaterialTheme.typography.bodySmall,
                         color = MaterialTheme.colorScheme.onSurfaceVariant)
                    // 配对进行中：通知里收码（去设置拿码的那会儿这条就等着），或在这里手输
                    PairingInline(remember { AdbPairing.prepareNotifications(context) })
                }
            },
            confirmButton = {
                when (apkChannel) {
                    null -> TextButton(onClick = {}, enabled = false) {
                        Text(locale.str(R.string.lib_apk_check_channel))
                    }
                    false -> TextButton(onClick = { startPairing(forMove = false) }) {
                        Text(locale.str(R.string.lib_apk_pair_first))
                    }
                    else -> TextButton(onClick = { doExportApk(plan) }) {
                        Text(locale.str(R.string.lib_apk_export_confirm))
                    }
                }
            },
            dismissButton = {
                Row {
                    TextButton(onClick = { pickExportApkDir(plan) }) {
                        Text(locale.str(R.string.lib_apk_export_change))
                    }
                    TextButton(onClick = {
                        apkPlan = null
                        if (AdbPairing.state !is AdbPairing.State.Working) AdbPairing.cancel(context)
                    }) {
                        Text(locale.str(R.string.common_cancel))
                    }
                }
            },
        )
    }

    // 导出之后：装上了没有、数据到了没有（两件事各自能成，各自能败）
    exportState.result?.let { r ->
        AlertDialog(
            onDismissRequest = { if (!exportState.running) exportState.clear() },
            title = { Text(locale.str(when {
                r.ok -> R.string.lib_apk_export_done_title
                r.failure == "install_failed" -> R.string.lib_apk_install_failed_title
                r.failure == "move_failed" -> R.string.lib_apk_move_failed_title
                else -> R.string.lib_apk_export_failed_title
            })) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (r.ok) {
                        Text(locale.str(R.string.lib_apk_export_done), style = MaterialTheme.typography.bodyMedium)
                        Text(locale.str(R.string.lib_apk_export_apk_kept, r.apk),
                             style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        val why = r.detail?.trim()?.lineSequence()?.lastOrNull().orEmpty()
                        Text(locale.str(when (r.failure) {
                            "install_failed" -> R.string.lib_apk_export_err_install
                            "move_failed" -> R.string.lib_apk_export_err_move
                            "background" -> R.string.lib_apk_export_err_background
                            else -> R.string.lib_apk_export_failed
                        }, if (r.failure == "install_failed" || r.failure == "move_failed") why
                           else apkFailureText(r.failure)),
                             style = MaterialTheme.typography.bodyMedium)
                    }
                }
            },
            confirmButton = {
                when {
                    r.ok -> TextButton(onClick = { exportState.clear() }) {
                        Text(locale.str(R.string.common_ok))
                    }
                    r.failure == "install_failed" || r.failure == "move_failed" ->
                        TextButton(onClick = { moveAgain() }, enabled = !exportState.running) {
                            Text(locale.str(R.string.lib_apk_move_again))
                        }
                    else -> TextButton(onClick = { exportState.clear() }) {
                        Text(locale.str(R.string.common_ok))
                    }
                }
            },
            dismissButton = {
                if (!r.ok && (r.failure == "install_failed" || r.failure == "move_failed")) {
                    TextButton(onClick = { exportState.clear() }) { Text(locale.str(R.string.common_cancel)) }
                }
            },
        )
    }

    // 全屏遮罩：搬移/删除/导出进行中挡住整个屏幕——这些动作要一分钟上下，不能让人乱点
    if (moving || removing || exporting || exportState.running) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color(0xCC0E0E0F))
                .clickable(enabled = false) {},   // 吃掉所有点击：下面那些按钮都按不到
            contentAlignment = Alignment.Center,
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (exportState.running) {
                    // 导出跑在前台服务里：构建（没有进度可言）、安装与搬运（按已送的字节走）
                    val p = exportState.progress
                    if (p != null && p.stage != GameApkExport.Stage.BUILD) {
                        LinearProgressIndicator(
                            progress = { p.fraction },
                            modifier = Modifier.width(220.dp),
                        )
                    } else {
                        CircularProgressIndicator()
                    }
                    Text(locale.str(when (p?.stage) {
                        GameApkExport.Stage.INSTALL -> R.string.lib_apk_export_stage_install
                        GameApkExport.Stage.MOVE -> R.string.lib_apk_export_stage_move
                        else -> R.string.lib_apk_export_stage_build
                    }),
                         style = MaterialTheme.typography.bodyMedium)
                    if (p != null && p.stage == GameApkExport.Stage.MOVE) {
                        Text(locale.str(R.string.lib_apk_export_stage_move_hint),
                             style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } else if (exporting) {
                    val p = exportProgress
                    if (p != null) {
                        LinearProgressIndicator(
                            progress = { p.fraction },
                            modifier = Modifier.width(220.dp),
                        )
                    } else {
                        CircularProgressIndicator()
                    }
                    Text(locale.str(R.string.lib_pack_export_working),
                         style = MaterialTheme.typography.bodyMedium)
                    p?.let {
                        Text(locale.str(R.string.lib_pack_export_progress,
                                        sizeText(it.bytes), sizeText(it.totalBytes)),
                             style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } else if (moving) {
                    val p = moveProgress
                    if (p != null) {
                        LinearProgressIndicator(
                            progress = { p.fraction },
                            modifier = Modifier.width(220.dp),
                        )
                    } else {
                        CircularProgressIndicator()
                    }
                    Text(locale.str(R.string.lib_pack_moving),
                         style = MaterialTheme.typography.bodyMedium)
                    // 已搬多少 / 一共多少
                    p?.let {
                        Text(locale.str(R.string.lib_pack_move_progress,
                                        sizeText(it.bytes), sizeText(it.totalBytes)),
                             style = MaterialTheme.typography.bodySmall,
                             color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                } else {
                    CircularProgressIndicator()
                    Text(locale.str(R.string.lib_cleanup_working),
                         style = MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

/** 删不了的时候说清楚为什么 */
private fun removeBlockedText(outcome: GameCleanup.Outcome): Int = when (outcome) {
    GameCleanup.Outcome.BUSY_PORTING -> R.string.lib_remove_busy_porting
    GameCleanup.Outcome.BUSY_RUNNING -> R.string.lib_remove_busy_running
    GameCleanup.Outcome.BUSY_MOVING -> R.string.lib_pack_busy_moving
    else -> R.string.lib_remove_failed
}

/**
 * 运行前配置（数据包的 env.txt，下次运行生效）：游戏语言与 Vulkan 驱动，选项来自包内的清单文件。
 * 驱动有两个来源：数据包自己带的（写在 drivers.txt 里，宿主在自己旁边找它）和玩家装在 App 里的
 * （在 App 的私有目录里，按绝对路径写进 env.txt）。
 */
@Composable
private fun RunOptions(
    installed: List<Driver>,
    options: RunOptionsSnapshot?,
    failure: Throwable?,
    onSelectLanguage: (String?) -> Unit,
    onSelectDriver: (String?) -> Unit,
) {
    val systemDriver = stringResource(R.string.driver_system_default)
    if (options != null) {
        PickRow(stringResource(R.string.lib_section_language), options.languages, options.language,
            onSelect = onSelectLanguage, fallback = systemDriver)
        PickRow(stringResource(R.string.driver_section),
            options.driverChoices(installed.map { it.library.absolutePath to it.label })
                .map { (value, name) -> value to (name ?: systemDriver) }, options.driver,
            // the device's own driver is an empty value, not the absence of the row: the app keeps that choice
            // (an absent row is where the default driver goes)
            onSelect = { value -> onSelectDriver(value) }, fallback = systemDriver,
            hint = stringResource(R.string.driver_pick_hint))
    } else {
        CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
    }
    failure?.let { Hint(failureText(LocalAppLocale.current, it), size = 11.sp) }
}

    /**
     * 存档（库页侧）：导出成一个 zip 交给系统文件管理器选地方，导入从系统文件管理器选一个 zip 换进去。
     *
     * 活存档是应用自己的文件（宿主把它挂在 filesDir/save/<titleId>），所以这里直接动它：不写请求文件，
     * 也不用等下次启动游戏。回到库页时游戏已经退出，它不再往存档里写。
     */
    @Composable
    private fun SaveRows(ported: Ported, gameName: String, repository: SaveRepository, io: SaveIo,
                         onToast: (String) -> Unit) {
        val locale = LocalAppLocale.current
        val scope = rememberCoroutineScope()
        val titleId = ported.titleId

        var busy by remember { mutableStateOf(false) }
        var note by remember { mutableStateOf("") }          // 上一次做了什么（留在面板里，不只弹一下）
        var pendingImport by remember { mutableStateOf<SaveSource?>(null) }

        fun doExport(target: SaveTarget) {
            busy = true
            scope.launch {
                val r = repository.export(titleId, gameName, target)
                busy = false
                r.onSuccess {
                    note = locale.str(R.string.lib_exported)
                    onToast(note)
                }.onFailure {
                    note = locale.str(R.string.lib_export_failed, failureText(locale, it))
                    onToast(note)
                }
            }
        }

        fun doImport(source: SaveSource) {
            busy = true
            scope.launch {
                val r = repository.import(titleId, source)
                busy = false
                r.onSuccess {
                    note = locale.str(R.string.lib_imported)
                    onToast(note)
                }.onFailure {
                    note = locale.str(R.string.lib_pack_import_failed, failureText(locale, it))
                    onToast(note)
                }
            }
        }

        // 导出：系统文件管理器（"另存为"）让玩家挑地方，包直接写进去，中间没有放包的地方
        val exportLauncher = rememberLauncherForActivityResult(
            ActivityResultContracts.CreateDocument("application/zip")) { uri ->
            if (uri != null) doExport(io.target(uri))
        }

        // 导入：系统文件管理器让玩家挑一个包（哪儿来的都行）
        val importLauncher = rememberLauncherForActivityResult(
            ActivityResultContracts.OpenDocument()) { uri ->
            if (uri == null) return@rememberLauncherForActivityResult
            val source = io.source(uri)
            val other = repository.titleIdInPackage(source.name)
            if (other != null && !other.equals(titleId, ignoreCase = true)) {
                onToast(locale.str(R.string.lib_other_games_save, other))
            } else {
                pendingImport = source
            }
        }

        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f))
        Text(locale.str(R.string.lib_section_saves), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
            QuietButton(locale.str(R.string.lib_export_saves), onClick = {
                exportLauncher.launch(repository.suggestedPackageName(titleId, gameName))
            }, modifier = Modifier.weight(1f), enabled = !busy)
            QuietButton(locale.str(R.string.lib_import_saves), onClick = {
                importLauncher.launch(arrayOf("application/zip", "application/octet-stream"))
            }, modifier = Modifier.weight(1f), enabled = !busy)
        }
        if (note.isNotEmpty()) Hint(note, size = 11.sp)

        // 换进去就是换掉现在的进度：没有备份可退，先问一遍
        pendingImport?.let { source ->
            AlertDialog(
                onDismissRequest = { pendingImport = null },
                title = { Text(locale.str(R.string.lib_import_confirm)) },
                text = { Text(locale.str(R.string.lib_import_confirm_body, source.name)) },
                confirmButton = {
                    TextButton(onClick = {
                        pendingImport = null
                        doImport(source)
                    }) { Text(locale.str(R.string.common_import), color = NxPalette.Building) }
                },
                dismissButton = { TextButton(onClick = { pendingImport = null }) { Text(locale.str(R.string.common_cancel)) } },
            )
        }
    }
