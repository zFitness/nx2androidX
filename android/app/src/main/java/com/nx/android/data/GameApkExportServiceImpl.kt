package com.nx.android.data

import android.content.Context
import android.os.StatFs
import android.util.Log
import com.nx.android.core.storage.AppPaths
import com.nx.android.domain.ApkMeta
import com.nx.android.domain.ApkMetaStore
import com.nx.android.domain.ChannelState
import com.nx.android.domain.GameApkExport
import com.nx.android.domain.GameApkExportService
import com.nx.android.domain.GameRef
import com.nx.android.domain.PortablePack
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.io.File
import java.io.PipedInputStream
import java.io.PipedOutputStream
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.concurrent.thread
import org.json.JSONObject

/**
 * The export of a finished port as a game of its own: an APK that gets installed on this phone, and the data
 * that game reads.
 *
 * The order matters:
 * 1. the APK is built in the guest (the host for a NativeActivity of its own, then the APK) into the folder
 *    the player picked. That folder holds nothing else: the data is not written into the player's storage —
 *    a copy the player can carry away is the portable export's job;
 * 2. the APK is installed on this phone over the App's ADB channel: the APK goes down the wire into `cmd
 *    package install -S` (the streamed install), so the player never touches a file manager;
 * 3. the data goes into the exported game's own directory over the same channel. The App tars the pack as it
 *    reads it and the shell untars it there (the platform lets no app write into another app's directory,
 *    but the shell can). The data exists twice when this returns: in the pack it came from, and in the
 *    game's own directory.
 *
 * The channel has to be there before any of it: without wireless debugging (and the App paired once), nothing
 * can be installed and the data has no way across. The interface asks the player to pair first — the code is
 * typed into a notification (AdbPairing).
 *
 * The work runs inside the foreground ExportService: a transfer of many minutes dies silently when Android
 * freezes the app in the background, and the freeze is the rule, not the exception.
 */
@Singleton
class GameApkExportServiceImpl @Inject constructor(
    private val paths: AppPaths,
    private val exporter: GameApkExporter,
    private val prefs: PrefsStore,
    private val apkMeta: ApkMetaStore,
    @ApplicationContext private val context: Context,
) : GameApkExportService {

    override fun export(game: GameRef, meta: ApkMeta,
               onProgress: (GameApkExport.Progress) -> Unit,
               log: (String) -> Unit): GameApkExport.Result {
        val manifest = PortablePack.readManifest(game.pack) ?: return fail("no_manifest")
        val packageName = meta.packageName.ifBlank { manifest.optString("package") }
        if (packageName.isEmpty()) return fail("no_package")
        val gameDir = GameApkExport.gameFilesDir(packageName)
        // the APK is a temporary file in the App's own cache: it is installed over the wire and then it is
        // gone — nothing lands in the player's storage
        val apk = File(paths.tmp, "export-${game.titleId}.apk")
        apk.delete()
        val romfs = if (game.romfsAt.isNotEmpty()) File(game.romfsAt) else File(game.pack, PortablePack.ROMFS)
        if (!romfs.isDirectory) return fail("no_romfs")

        // the room: the APK on the App's own volume, the data in the game's own directory
        if (freeBytes(paths.tmp) < GameApkExport.APK_LIMIT_WITH_DRIVER) return fail("no_space")
        val dataBytes = dataBytes(game, romfs)
        if (freeBytes(File(gameDir)) < dataBytes) return fail("no_space")

        val env = File(game.pack, PortablePack.ENV).takeIf { it.isFile }?.readText().orEmpty()

        // 1. the APK, into the folder the player picked (the porter reads the pack itself: the manifest, the
        //    icon and the theme are what the APK carries — the data is not part of it)
        onProgress(GameApkExport.Progress(GameApkExport.Stage.BUILD, 0f))
        val driver = GameApkExport.envValue(env, "DM_VK_DRIVER")?.let { File(it) }?.takeIf { it.isFile }
        val built = exporter.build(game.pack, apk, keyFile(), driver, nextOffset(game.titleId), packageName,
            meta.versionName.ifBlank { "1.0.0" }) { log(it) }
        if (!built.ok) {
            apk.delete()
            return fail(built.reason.ifEmpty { "build_failed" })
        }

        // 2. the install: the APK goes down the wire into the package manager. `-d` allows a downgrade: the
        //    player's copy may carry a higher versionCode (an export made when the count was higher), and a
        //    fresh export must still install over it
        onProgress(GameApkExport.Progress(GameApkExport.Stage.INSTALL, 0f))
        try {
            val answer = runCatching {
                AdbChannels.exec(context, "cmd package install -r -d -S ${apk.length()}",
                    apk.inputStream().buffered(),
                    { sent -> onProgress(GameApkExport.Progress(GameApkExport.Stage.INSTALL,
                        (sent.toFloat() / apk.length().toFloat()).coerceIn(0f, 1f))) },
                    WIRE_IDLE_TIMEOUT_MS)
                }.onFailure {
                    Log.i(TAG, "the streamed install failed: ${it.message}")
                    log("[RED] the game could not be installed: ${it.message}")
                }.getOrNull()
            if (answer == null || !answer.contains("Success")) {
                log("[RED] the game did not install: ${answer?.trim()?.lineSequence()?.lastOrNull() ?: "no answer"}")
                return GameApkExport.Result(ok = false, failure = "install_failed", detail = answer?.takeLast(300),
                    packageName = packageName, size = built.size)
            }

            // 3. the data into the game's own directory
            val moved = moveData(game, packageName, onProgress, log)
            if (!moved) {
                // the game is on the phone: only the data is missing, and moving it again is one tap
                return GameApkExport.Result(ok = false, failure = "move_failed",
                    packageName = packageName, size = built.size, installed = true)
            }
            onProgress(GameApkExport.Progress(GameApkExport.Stage.DONE, 1f))
            return GameApkExport.Result(ok = true, packageName = packageName,
                size = built.size, installed = true, moved = true)
        } finally {
            apk.delete()   // the game is installed; the installer's file has done its job
        }
    }

    /** The channel's state: ready / wireless debugging off / never paired. */
    override fun channel(): ChannelState = AdbChannels.state(context)

    override fun moveData(game: GameRef, packageName: String,
                 onProgress: (GameApkExport.Progress) -> Unit,
                 log: (String) -> Unit): Boolean {
        val manifest = PortablePack.readManifest(game.pack) ?: return false
        val gameDir = GameApkExport.gameFilesDir(packageName)
        val romfs = if (game.romfsAt.isNotEmpty()) File(game.romfsAt) else File(game.pack, PortablePack.ROMFS)
        if (!romfs.isDirectory) return false

        // no space check here: a retry overwrites the last attempt's files in place, so counting the leftover
        // bytes against the transfer would refuse a fit (export() checked the room before anything ran)

        // the game's own env and manifest: the rows that pointed inside the pack follow the game's own
        // directory, the shared font travels with the data (the game cannot read the App's private folder),
        // and the identity the player filled in (package, author, email, description) rides in the manifest
        val env = File(game.pack, PortablePack.ENV).takeIf { it.isFile }?.readText().orEmpty()
        val font = if (GameApkExport.envValue(env, "DM_SHARED_FONT") == null ||
            File(game.pack, GameApkExport.STANDARD_FONT).isFile) null
            else File(paths.tool, "nxnative/dm/tools/shared_cjk.ttf").takeIf { it.isFile }
        if (GameApkExport.envValue(env, "DM_SHARED_FONT") != null && font == null) {
            log("[RED] the shared font is missing (the tool tree has no shared_cjk.ttf): the game's Chinese text draws as \"?\"")
        }
        val manifestJson = PortablePack.manifestForExport(manifest)
        manifestJson.put("package", packageName)
        apkMeta.read(game.titleId)?.let { m ->
            if (m.author.isNotBlank()) manifestJson.put("author", m.author)
            if (m.email.isNotBlank()) manifestJson.put("email", m.email)
            if (m.description.isNotBlank()) manifestJson.put("description", m.description)
        }
        val manifestText = manifestJson.toString(2)
        val envText = GameApkExport.envForGameDir(env, gameDir)

        // the tar as it is read: the data crosses without a copy of its own on the way
        val total = dataBytes(game, romfs) + (font?.length() ?: 0L)

        // the unpack: mkdir first (the game's directory exists once the game is installed, but the player
        // may be moving the data before that), tar off stdin, then the chmod — the files arrive owned by the
        // shell, and the game (another uid) could not read them without it.
        // The channel flaps (MIUI drops the wireless listener while USB is plugged): a failed attempt is not
        // a verdict — the completeness check runs either way (the manifest goes as the LAST entry of the
        // stream, so its presence says every byte before it landed), and one automatic retry covers the flap.
        // Beyond that the player taps 搬数据 again. The space check lives in export(): a retry overwrites in
        // place, so counting the leftover bytes against the transfer would refuse a fit.
        val command = "mkdir -p '$gameDir' && tar -x -f - -C '$gameDir' && chmod -R a+rX '$gameDir'"
        var attempts = 0
        var lastFail = ""
        while (true) {
            attempts++
            var copied = 0L   // 每次尝试归零：进度跟着这一次的字节走（上次尝试的残余不算数）
            fun tick(n: Long) {
                copied += n
                onProgress(GameApkExport.Progress(GameApkExport.Stage.MOVE,
                    if (total > 0) (copied.toFloat() / total).coerceIn(0f, 1f) else 0f))
            }
            val pipeIn = PipedInputStream(PIPE_BUFFER)
            val pipeOut = PipedOutputStream(pipeIn)
            val producer = thread(name = "nx2a-export-tar") {
                try {
                    TarWriter(pipeOut).use { w ->
                        // the pack's files, the save backups and the management files excepted (they go below,
                        // rewritten for the game's own directory); a RomFS in the build workspace joins them
                        copyTree(game.pack, romfs, w, ::tick)
                        w.putBytes(PortablePack.ENV, envText.toByteArray(Charsets.UTF_8))
                        font?.let { w.putFile(GameApkExport.STANDARD_FONT, it, onBytes = ::tick) }
                        // the manifest goes LAST: it is the completeness marker, so its presence says
                        // everything before it (env, font, all the game files) landed too
                        w.putBytes(PortablePack.MANIFEST, manifestText.toByteArray(Charsets.UTF_8))
                    }
                } catch (t: Throwable) {
                    // the reader is gone (the channel dropped): the short stream is what the shell sees
                    Log.i(TAG, "the tar stopped early: ${t.message}")
                }
                runCatching { pipeOut.close() }
            }
            val answer = runCatching {
                AdbChannels.exec(context, command, pipeIn, {}, WIRE_IDLE_TIMEOUT_MS)
            }.onFailure {
                lastFail = it.message ?: it.javaClass.simpleName
                Log.i(TAG, "the data's transfer failed (attempt $attempts): $lastFail")
            }.getOrNull()
            // the reader may have stopped before the tar began: wake the producer out of its wait
            producer.interrupt()
            producer.join(10_000)
            // the verdict is the manifest, not the transfer's own answer — it is the last entry of the
            // stream, so its presence says the tar finished (an earlier attempt may have finished it)
            val dataThere = runCatching {
                AdbChannels.exec(context,
                    "if [ -f '$gameDir/${PortablePack.MANIFEST}' ]; then echo DATA_OK; else echo DATA_MISSING; fi",
                    timeoutMs = 30_000)
            }.getOrNull().orEmpty().contains("DATA_OK")
            if (dataThere) {
                log(if (answer == null) "the data is in the game's own directory (an earlier attempt finished it)"
                    else "the data is in the game's own directory")
                return true
            }
            if (lastFail.isBlank()) lastFail = "its manifest is not there"
            if (attempts >= 3) {
                log("[RED] the data did not land in the game's own directory ($lastFail)")
                return false
            }
            log("the channel dropped mid-transfer: waiting 15s and trying again ($attempts/3)")
            Thread.sleep(15_000)
        }
    }

    /** The pack's tree, into the tar: the save backups and the two management files excepted */
    private fun copyTree(pack: File, romfs: File, w: TarWriter, tick: (Long) -> Unit) {
        val romfsOutside = romfs.parentFile?.absolutePath != pack.absolutePath
        putTree(pack, setOf(PortablePack.SAVES, PortablePack.MANIFEST, PortablePack.ENV), w, tick, "")
        if (romfsOutside) putTree(romfs, emptySet(), w, tick, PortablePack.ROMFS)
    }

    /** One folder of the tree, under [base] inside the archive (the top level is the game's own directory) */
    private fun putTree(dir: File, exclude: Set<String>, w: TarWriter, tick: (Long) -> Unit, base: String) {
        if (base.isNotEmpty()) w.putDirectory(base)
        val children = dir.listFiles() ?: return
        for (child in children.sortedBy { it.name }) {
            val name = if (base.isEmpty()) child.name else "$base/${child.name}"
            when {
                child.isDirectory -> putTree(child, emptySet(), w, tick, name)
                child.name in exclude -> {}
                else -> w.putFile(name, child, onBytes = tick)
            }
        }
    }

    /** How much the data is: the pack, and a RomFS that lives in the build workspace (not inside the pack) */
    private fun dataBytes(game: GameRef, romfs: File): Long =
        GameApkExport.treeBytes(game.pack) +
            (if (romfs.parentFile?.absolutePath != game.pack.absolutePath) GameApkExport.treeBytes(romfs) else 0L)

    /** The signing key: one for every exported game (the app's own private folder). */
    private fun keyFile(): File = File(paths.nxHome, "export-signing-key.json")

    /**
     * The versionCode offset: the app counts the exports of the same game, so a later one installs over an
     * earlier one (Android refuses to install over a lower versionCode).
     */
    private fun nextOffset(titleId: String): Int {
        val counts = prefs.json(PrefsStore.LIB_EXPORTS)
        val n = counts.optInt(titleId, 0)
        counts.put(titleId, n + 1)
        prefs.putJson(PrefsStore.LIB_EXPORTS, counts)
        return n
    }

    /** The room on the volume a path is on (the nearest existing folder above it). */
    private fun freeBytes(target: File): Long {
        var dir = target
        while (!dir.exists() && dir.parentFile != null) dir = dir.parentFile ?: break
        return runCatching { StatFs(dir.absolutePath).availableBytes }.getOrDefault(0L)
    }

    private fun fail(why: String) = GameApkExport.Result(false, why)

    companion object {
        private const val TAG = "nx2a-export"
        /**
         * The wire's idle timeout: how long no message may go without the transfer being called dead. A
         * healthy transfer acks continuously; a wedged one (the phone asleep, adbd restarted) used to sit
         * for half an hour before giving up — a minute is enough to tell the difference.
         */
        private const val WIRE_IDLE_TIMEOUT_MS = 60 * 1000L
        /** The pipe between the tar and the wire: enough to keep the socket fed while the disk reads */
        private const val PIPE_BUFFER = 512 * 1024
    }
}

@Module
@InstallIn(SingletonComponent::class)
abstract class GameApkExportModule {
    @Binds
    @Singleton
    abstract fun bindGameApkExportService(impl: GameApkExportServiceImpl): GameApkExportService
}
