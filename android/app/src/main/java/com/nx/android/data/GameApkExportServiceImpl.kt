package com.nx.android.data

import android.content.Context
import android.os.StatFs
import android.util.Log
import com.nx.android.core.storage.AppPaths
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
    @ApplicationContext private val context: Context,
) : GameApkExportService {

    override fun export(game: GameRef, targetDir: File,
               onProgress: (GameApkExport.Progress) -> Unit,
               log: (String) -> Unit): GameApkExport.Result {
        val manifest = PortablePack.readManifest(game.pack) ?: return fail("no_manifest")
        val packageName = manifest.optString("package")
        if (packageName.isEmpty()) return fail("no_package")
        val gameDir = GameApkExport.gameFilesDir(packageName)
        val apk = File(targetDir, GameApkExport.apkName(game.label))
        // the player's folder already holds an APK of this game's: nothing is overwritten
        if (apk.exists()) return fail("exists")
        val romfs = if (game.romfsAt.isNotEmpty()) File(game.romfsAt) else File(game.pack, PortablePack.ROMFS)
        if (!romfs.isDirectory) return fail("no_romfs")

        // the room: the APK in the player's folder, the data in the game's own directory
        if (freeBytes(targetDir) < GameApkExport.APK_LIMIT_WITH_DRIVER) return fail("no_space")
        val dataBytes = dataBytes(game, romfs)
        if (freeBytes(File(gameDir)) < dataBytes) return fail("no_space")

        val env = File(game.pack, PortablePack.ENV).takeIf { it.isFile }?.readText().orEmpty()

        // 1. the APK, into the folder the player picked (the porter reads the pack itself: the manifest, the
        //    icon and the theme are what the APK carries — the data is not part of it)
        onProgress(GameApkExport.Progress(GameApkExport.Stage.BUILD, 0f))
        val driver = GameApkExport.envValue(env, "DM_VK_DRIVER")?.let { File(it) }?.takeIf { it.isFile }
        val built = exporter.build(game.pack, apk, keyFile(), driver, nextOffset(game.titleId)) { log(it) }
        if (!built.ok) {
            apk.delete()
            return fail(built.reason.ifEmpty { "build_failed" })
        }

        // 2. the install: the APK goes down the wire into the package manager
        onProgress(GameApkExport.Progress(GameApkExport.Stage.INSTALL, 0f))
        val answer = runCatching {
            AdbChannels.exec(context, "cmd package install -r -S ${apk.length()}",
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
                apk = apk.absolutePath, packageName = packageName, size = built.size)
        }

        // 3. the data into the game's own directory
        val moved = moveData(game, packageName, onProgress, log)
        if (!moved) {
            // the game is on the phone: only the data is missing, and moving it again is one tap
            return GameApkExport.Result(ok = false, failure = "move_failed",
                apk = apk.absolutePath, packageName = packageName, size = built.size, installed = true)
        }
        onProgress(GameApkExport.Progress(GameApkExport.Stage.DONE, 1f))
        return GameApkExport.Result(ok = true, apk = apk.absolutePath, packageName = packageName,
            size = built.size, installed = true, moved = true)
    }

    /** Whether the App's key is paired with this phone's adbd (a harmless command answers). */
    override fun paired(): Boolean = AdbChannels.paired(context)

    override fun moveData(game: GameRef, packageName: String,
                 onProgress: (GameApkExport.Progress) -> Unit,
                 log: (String) -> Unit): Boolean {
        val manifest = PortablePack.readManifest(game.pack) ?: return false
        val gameDir = GameApkExport.gameFilesDir(packageName)
        val romfs = if (game.romfsAt.isNotEmpty()) File(game.romfsAt) else File(game.pack, PortablePack.ROMFS)
        if (!romfs.isDirectory) return false

        // the room (the game may have grown since the check in export)
        val dataBytes = dataBytes(game, romfs)
        if (freeBytes(File(gameDir)) < dataBytes) { log("[RED] the game's own directory has no room for the data"); return false }

        // the game's own env and manifest: the rows that pointed inside the pack follow the game's own
        // directory, the shared font travels with the data (the game cannot read the App's private folder)
        val env = File(game.pack, PortablePack.ENV).takeIf { it.isFile }?.readText().orEmpty()
        val font = if (GameApkExport.envValue(env, "DM_SHARED_FONT") == null ||
            File(game.pack, GameApkExport.STANDARD_FONT).isFile) null
            else File(paths.tool, "nxnative/dm/tools/shared_cjk.ttf").takeIf { it.isFile }
        if (GameApkExport.envValue(env, "DM_SHARED_FONT") != null && font == null) {
            log("[RED] the shared font is missing (the tool tree has no shared_cjk.ttf): the game's Chinese text draws as \"?\"")
        }
        val manifestText = PortablePack.manifestForExport(manifest).toString(2)
        val envText = GameApkExport.envForGameDir(env, gameDir)

        // the tar as it is read: the data crosses without a copy of its own on the way
        val total = dataBytes + (font?.length() ?: 0L)
        var copied = 0L
        fun tick(n: Long) {
            copied += n
            onProgress(GameApkExport.Progress(GameApkExport.Stage.MOVE,
                if (total > 0) (copied.toFloat() / total).coerceIn(0f, 1f) else 0f))
        }

        // the unpack: mkdir first (the game's directory exists once the game is installed, but the player
        // may be moving the data before that), tar off stdin, then the chmod — the files arrive owned by the
        // shell, and the game (another uid) could not read them without it
        val command = "mkdir -p '$gameDir' && tar -x -f - -C '$gameDir' && chmod -R a+rX '$gameDir'"
        val pipeIn = PipedInputStream(PIPE_BUFFER)
        val pipeOut = PipedOutputStream(pipeIn)
        val producer = thread(name = "nx2a-export-tar") {
            try {
                TarWriter(pipeOut).use { w ->
                    // the pack's files, the save backups and the management files excepted (they go below,
                    // rewritten for the game's own directory); a RomFS in the build workspace joins them
                    copyTree(game.pack, romfs, w, ::tick)
                    w.putBytes(PortablePack.MANIFEST, manifestText.toByteArray(Charsets.UTF_8))
                    w.putBytes(PortablePack.ENV, envText.toByteArray(Charsets.UTF_8))
                    font?.let { w.putFile(GameApkExport.STANDARD_FONT, it, onBytes = ::tick) }
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
            Log.i(TAG, "the data's transfer failed: ${it.message}")
            log("[RED] the data could not be moved into the game's own directory: ${it.message}")
        }.getOrNull()
        // the reader may have stopped before the tar began: wake the producer out of its wait
        producer.interrupt()
        producer.join(10_000)
        if (answer == null) return false
        // the tar's own silence means nothing (a warning about a mtime it cannot set is not a failure): the
        // manifest being there is the check
        val check = runCatching {
            AdbChannels.exec(context,
                "if [ -f '$gameDir/${PortablePack.MANIFEST}' ]; then echo DATA_OK; else echo DATA_MISSING; fi",
                timeoutMs = 30_000)
        }.getOrNull().orEmpty()
        if (!check.contains("DATA_OK")) {
            log("[RED] the data did not land in the game's own directory (its manifest is not there)")
            return false
        }
        log("the data is in the game's own directory")
        return true
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
