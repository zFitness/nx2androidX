package com.nx.android.domain

import java.io.File
import org.json.JSONObject

/**
 * A port that leaves the phone as a game of its own: an APK the player installs by hand, and the data that
 * game reads.
 *
 * The exported game is the upstream's APK front (dm/android/front_android.c): its data root is the app's own
 * external directory (/storage/emulated/0/Android/data/<package>/files), which the system gives every app and
 * asks for no permission. So the exported game starts without a dialog and runs on the device's own driver
 * unless the pack says otherwise.
 *
 * The data has to be *in* that directory before the game starts, and no app may write into another app's
 * directory: the shell does it, over the App's own ADB channel. The data crosses as a tar stream — the App
 * reads the pack and the shell unpacks it where it lands — so it exists twice, in the pack it came from and
 * in the game's own directory, and nowhere else. The player's storage keeps nothing but the APK: a copy the
 * player can carry away is the portable export's job.
 */
object GameApkExport {

    /** The exported game's own directory on the device: the one the system gives every app. */
    fun gameFilesDir(packageName: String): String = "/storage/emulated/0/Android/data/$packageName/files"

    /** The APK's size limit, in bytes: with a driver at most (the driverless ones sit well below it). */
    const val APK_LIMIT_WITH_DRIVER = 35L * 1024 * 1024

    /** The stages of an export, in the order they happen. */
    enum class Stage { BUILD, INSTALL, MOVE, DONE }

    /** How far an export has come. */
    data class Progress(val stage: Stage, val fraction: Float, val message: String = "")

    /**
     * The outcome of an export.
     *
     * [installed] says whether the game got onto the phone; [moved] whether the data reached the game's own
     * directory. Either can fail on its own; [detail] carries the installer's (or the shell's) own words.
     */
    data class Result(
        val ok: Boolean,
        val failure: String? = null,
        val detail: String? = null,
        val packageName: String = "",
        val size: Long = 0L,
        val installed: Boolean = false,
        val moved: Boolean = false,
    )

    /**
     * The paths inside a pack that travel with it: an env row whose value ends with one of these points into
     * the pack, so it follows the folder wherever the folder is.
     */
    private val PACK_PATHS = listOf("/aoc", "/sysdata", "/standard.ttf", "/nintendo_ext.ttf")

    /** The font the exported data carries when the pack does not have one of its own. */
    const val STANDARD_FONT = "standard.ttf"

    /**
     * The env.txt the exported data folder carries: the rows that pointed inside the pack follow the exported
     * game's own directory (that is where the folder ends up), the shared font travels with the folder (the
     * exporting phone's copy is out of the game's reach), and the row that pointed at the exporting phone's
     * build workspace is gone (the game's files are inside the folder now).
     */
    fun envForGameDir(env: String, gameDir: String): String {
        val base = gameDir.trimEnd('/')
        val kept = env.lineSequence().mapNotNull { line ->
            if (line.trimStart().startsWith("#") || !line.contains('=')) return@mapNotNull line
            val key = line.substringBefore('=', "")
            val value = line.substringAfter('=')
            when {
                // the game's files are inside the folder: the front reads <its own directory>/RomFS
                key.trim() == "DM_ROMFS" -> null
                // the shared font travels with the folder
                key.trim() == "DM_SHARED_FONT" -> "$key=$base/$STANDARD_FONT"
                else -> {
                    val suffix = PACK_PATHS.firstOrNull { value.endsWith(it) && value.length > it.length }
                        ?: return@mapNotNull line
                    val head = value.dropLast(suffix.length)
                    if (!head.startsWith("/")) return@mapNotNull line
                    "$key=$base$suffix"
                }
            }
        }.toList()
        return kept.joinToString("\n").trimEnd('\n') + "\n"
    }

    /** One env.txt row's value, or null when the row is not there. */
    fun envValue(env: String, key: String): String? = env.lineSequence()
        .firstOrNull { it.contains('=') && !it.trimStart().startsWith("#") && it.substringBefore('=').trim() == key }
        ?.substringAfter('=')
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    /** How big a tree is (only stat: files and bytes, no content read). */
    fun treeBytes(dir: File): Long {
        var bytes = 0L
        val stack = ArrayDeque<File>()
        stack.addLast(dir)
        while (stack.isNotEmpty()) {
            val d = stack.removeLast()
            val children = d.listFiles() ?: continue
            for (child in children) {
                if (child.isDirectory) stack.addLast(child) else bytes += child.length()
            }
        }
        return bytes
    }

    /** A human size for the interface (the App's own wording). */
    fun sizeText(bytes: Long): String = when {
        bytes >= 1024L * 1024 * 1024 -> String.format("%.1f GB", bytes / 1024.0 / 1024 / 1024)
        bytes >= 1024L * 1024 -> String.format("%.0f MB", bytes / 1024.0 / 1024)
        bytes >= 1024L -> String.format("%.0f kB", bytes / 1024.0)
        else -> "$bytes B"
    }
}
