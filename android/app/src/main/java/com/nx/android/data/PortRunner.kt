package com.nx.android.data

import com.nx.android.BuildConfig
import com.nx.android.R
import com.nx.android.domain.GameSource
import com.nx.android.domain.environment.EnvironmentSetup
import com.nx.android.domain.environment.GuestProcessLauncher
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Runs the porter and the doctor: the process handling that used to live in the activity, unchanged in its
 * behavior (one stream for stdout and stderr, the porter's events by line, cancel stops the porter and the
 * tools it started). Every run is one thread; the output goes to [onLine] from that thread.
 */
class PortRunner(
    private val environmentSetup: EnvironmentSetup,
    private val guestLauncher: GuestProcessLauncher,
    private val str: (Int, Array<out Any?>) -> String,
    private val statusFile: File? = null,
    private val onLine: (String) -> Unit,
) {

    @Volatile private var cancelled = false
    @Volatile private var proc: Process? = null

    fun port(
        gameFile: String, keys: String,
        touch: Boolean, fps60: Boolean, experimental: Boolean,
        aliasHeadroom: Int,
        sharedFont: String = "", firmware: String = "", mtReplay: Boolean = false,
        packDir: String? = null,
        proxyPort: Int? = null,
        onEnd: () -> Unit,
    ): Thread {
        val args = portArgs(gameFile, keys, touch, fps60, experimental, aliasHeadroom, !BuildConfig.NX_LSFG,
            sharedFont, firmware, mtReplay, deviceLanguage())
        // A file in a netdisk's folder is not there yet in its middle: the port would read it as a broken dump
        GameSource.cloudFolder(gameFile)?.let { onLine(s(R.string.runner_cloud_folder, it)) }
        val extra = buildMap {
            if (!packDir.isNullOrBlank()) put("NX2A_PACK_DIR", packDir)
            proxyPort?.let { putAll(proxyEnv(it)) }
        }
        return start(args, { onEnd() }, extra)
    }

    /**
     * The phone's own language: the pack follows it when the game has it (the porter takes it as a wish: a game
     * without it is packed in its own first language, as before).
     */
    private fun deviceLanguage(): String = Locale.getDefault().toLanguageTag()

    companion object {

        /**
         * The guest cannot resolve names itself: glibc reads /etc/resolv.conf, Android has none, and an
         * unprivileged app may not write /etc. A port that needs the network (the 60 fps stage fetches a
         * config from GitHub) therefore rides the app's own CONNECT proxy, the one the assistant uses.
         * Only the port process gets these variables; other guest runs stay offline.
         */
        fun proxyEnv(port: Int): Map<String, String> = mapOf(
            "http_proxy" to "http://127.0.0.1:$port",
            "https_proxy" to "http://127.0.0.1:$port",
        )

        /**
         * The porter's command line for a port: pure, so the test can check it on the JVM.
         *
         * There is no output folder on the command line: the data pack goes into the app's own folder
         * (the porter's app mode puts it there, whatever the caller says).
         *
         * The extra address space (the alias region): Auto passes nothing, the porter decides by itself
         * (the version the profile was tested with gets none, another one 8 GB).
         *
         * The player's own overrides: the system font (a .ttf; empty = the app's own, which has the CJK
         * glyphs), the firmware dump's system content folder (empty = none) and the multithread replay.
         */
        fun portArgs(gameFile: String, keys: String, touch: Boolean, fps60: Boolean,
                     experimental: Boolean, aliasHeadroom: Int, noLsfg: Boolean,
                     sharedFont: String = "", firmware: String = "", mtReplay: Boolean = false,
                     deviceLanguage: String = ""): List<String> {
            val args = mutableListOf("-m", "porter", "port", gameFile, "-k", keys, "--progress", "json", "--app")
            if (touch) args += "--touch"
            if (fps60) args += "--fps60"
            if (experimental) args += "--experimental"
            if (aliasHeadroom >= 0) args += listOf("--alias-headroom", aliasHeadroom.toString())
            if (sharedFont.isNotBlank()) args += listOf("--shared-font", sharedFont.trim())
            if (firmware.isNotBlank()) args += listOf("--firmware", firmware.trim())
            if (mtReplay) args += "--mt-replay"
            if (deviceLanguage.isNotBlank()) args += listOf("--language-preferred", deviceLanguage.trim())
            // A build without the frame generation (the Gradle property nxLsfg=false): the host the app builds on the
            // device is then smaller and the frame generation reports that it is not in this build (android/NOTICE.md).
            if (noLsfg) args += "--no-lsfg"
            return args
        }
    }

    /**
     * The tools check: the interpreter paths first (the porter would otherwise report its tools missing from the
     * saved setting). [json] asks for the rows as one JSON array, the form the keys check reads.
     */
    fun doctor(keys: String, json: Boolean, onEnd: () -> Unit): Thread {
        val args = mutableListOf("-m", "porter", "doctor")
        if (json) args += "--json"
        if (keys.isNotBlank()) args += listOf("-k", keys.trim())
        val t = Thread {
            try {
                onLine(s(R.string.runner_checking_tools))
                environmentSetup.patchInterpreters()
                onLine(s(R.string.runner_interpreter_patched))
            } catch (e: Exception) {
                onLine(s(R.string.runner_interpreter_patch_failed, e.message))
            }
            start(args, { onEnd() })
        }
        t.start()
        return t
    }

    /**
     * Imports a package of game profiles into the player's own folder (porter profiles import).
     *
     * The package has to be in the app's own folder: the guest sees the app's files, not the phone's storage, so a package
     * picked on the SD card is copied into the app's folder before it is handed over. The exit code says whether the
     * import worked; the porter's own lines say why it did not.
     */
    fun importProfiles(packageFile: String, onEnd: (Int) -> Unit): Thread {
        val args = mutableListOf("-m", "porter", "profiles", "import", packageFile)
        return start(args, onEnd)
    }

    /**
     * One run of a guest program.
     *
     * The caller hears about the end exactly once: [onEnd] is called with the exit code (the program's own
     * code; -1 when the run did not get that far - it failed, or it never started). The end is told in the
     * finally, so it is told on every path: a run that failed is told as a failure, not as a success.
     */
    private fun start(args: List<String>, onEnd: (Int) -> Unit, extra: Map<String, String> = emptyMap()): Thread {
        val t = Thread {
            var code = -1
            try {
                if (cancelled) return@Thread
                val p = guestLauncher.guest(args, extra = extra)
                proc = p
                if (cancelled) {
                    p.destroyForcibly()
                    return@Thread
                }
                p.inputStream.bufferedReader().forEachLine { onLine(it) }
                code = runCatching { p.waitFor() }.getOrDefault(-1)
                if (code != 0) onLine(exitLine(code))
                statusFile?.let { writeStatus(it, code) }
            } catch (e: Exception) {
                onLine("[RED] ${e.message}")
            } finally {
                proc = null
                onEnd(code)
            }
        }
        t.start()
        return t
    }

    /**
     * How the run ended: the exit code, or the signal that killed it (the system takes the memory when a port
     * grows too big; the JDK reports such a process as 128 + the signal).
     */
    private fun exitLine(code: Int): String {
        val sig = signal(code)
        return if (sig != 0) s(R.string.runner_killed, sig) else s(R.string.runner_exit_code, code)
    }

    /** One of the app's own strings: its id and the arguments it takes */
    private fun s(id: Int, vararg args: Any?): String = str(id, args)

    /** The signal that killed the process, 0 when it ended on its own */
    private fun signal(code: Int): Int = if (code in 129..255) code - 128 else 0

    /**
     * The run's end, in a file: the log bundle takes it, so a port the system killed says so (the porter itself
     * had no chance to write anything).
     */
    private fun writeStatus(file: File, code: Int) {
        try {
            file.parentFile?.mkdirs()
            val sig = signal(code)
            val what = if (sig != 0) "killed by signal $sig" else "exit code $code"
            file.writeText("port: $what\ntime: ${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())}\n")
        } catch (e: Exception) {
        }
    }

    /** Stops the porter and the tools it started (they are the app's own processes, stopped one by one) */
    fun cancel() {
        cancelled = true
        try { proc?.destroyForcibly() } catch (e: Exception) {
        }
        proc = null
        val me = android.os.Process.myPid()
        for (d in File("/proc").listFiles() ?: return) {
            if (!d.name.all { it.isDigit() }) continue
            val pid = d.name.toLong()
            if (pid == me.toLong()) continue
            try {
                val cmd = File(d, "cmdline").readText()
                if (cmd.contains("python3.13") || cmd.contains("dotnet") || cmd.contains("ld-linux") ||
                    cmd.contains("clang") || cmd.contains("nx_extract")
                ) {
                    android.os.Process.killProcess(pid.toInt())
                }
            } catch (e: Exception) {
            }
        }
    }
}
