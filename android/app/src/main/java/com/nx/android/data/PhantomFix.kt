package com.nx.android.data

import android.content.Context
import android.provider.Settings
import android.util.Log
import androidx.annotation.StringRes
import com.nx.android.R
import com.nx.android.domain.PhantomCheck

/**
 * Android 12 and newer stop an app's "phantom" child processes above a limit (32, counted for the whole
 * system), and the Linux environment starts many of them: the porter is one, and so are the compiler and
 * the shader translator below it. When the list overflows, the oldest one goes first - the porter - and
 * the port dies with no error at all (the App sees exit 137 and nothing else).
 *
 * The switch is only writable by the shell user, so the fix pairs the App with the phone over Wireless
 * debugging ([AdbPairing] — the pairing code is typed into a notification, so the code dialog in Settings
 * stays open), then connects to adbd over 127.0.0.1 and changes the setting (AdbWire.kt). The setting
 * survives reboots; Wireless debugging is switched off again afterwards when it was off before.
 *
 * Ported from the same author's fexdroid project.
 */
object PhantomFix {
    private const val KEY = "settings_enable_monitor_phantom_procs"
    private const val MAX = "2147483647"
    private const val PREFS = "phantom-fix"
    private const val TAG = "nx2a-phantom"

    val state: AdbPairing.State get() = AdbPairing.state

    /**
     * Whether Android may kill the guests' processes now. Runs a command: not on the main thread.
     *
     * The decision itself is in domain/PhantomCheck.kt, free of Android, so it can be tested on the JVM.
     */
    fun status(ctx: Context): PhantomCheck.Status {
        val sdk = android.os.Build.VERSION.SDK_INT
        if (sdk < android.os.Build.VERSION_CODES.S) return PhantomCheck.Status.NOT_NEEDED
        // Android 12: the app may not read device_config at all, so our own fix is the only sign
        if (sdk == android.os.Build.VERSION_CODES.S && prefs(ctx).getBoolean("fixed", false)) return PhantomCheck.Status.OFF
        val max = runCmd("/system/bin/device_config", "get", "activity_manager", "max_phantom_processes").trim()
        val global = runCatching { Settings.Global.getString(ctx.contentResolver, KEY) }.getOrNull().orEmpty()
        val flag = getprop("persist.sys.fflag.override.$KEY")
        return PhantomCheck.status(sdk, max, global, flag)
    }

    /** The fix's own note: it was done here before, so Android 12's unreadable setting is known */
    private fun prefs(ctx: Context) = ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Runs a program and gives back what it printed */
    private fun runCmd(vararg cmd: String): String = runCatching {
        val p = ProcessBuilder(*cmd).redirectErrorStream(true).start()
        val out = p.inputStream.bufferedReader().readText()
        p.waitFor()
        out
    }.getOrElse { "<${it.javaClass.simpleName}: ${it.message}>" }

    /** A system property's value */
    private fun getprop(name: String): String = runCmd("/system/bin/getprop", name).trim()

    private fun str(@StringRes id: Int, vararg args: Any?): String = AdbPairing.s(id, *args)

    /** Shows the code notification and starts looking for Wireless debugging's ports. */
    fun begin(ctx: Context) = AdbPairing.begin(ctx, after = ::fix)

    fun cancel(ctx: Context) = AdbPairing.cancel(ctx)

    /**
     * Pairs with [code], then switches the limit off. [port] overrides the discovered pairing port
     * (the "IP address & Port" line of the code dialog). [done] runs on the worker thread.
     */
    fun submit(ctx: Context, code: String, port: Int? = null, done: () -> Unit = {}) =
        AdbPairing.submit(ctx, code, port, done)

    /** The switch itself, on the wire the pairing opened. Throws = Failed, the reason goes to the player. */
    private fun fix(app: Context, wire: AdbWire, cPort: Int) {
        AdbPairing.step(R.string.phantom_step_changing)
        val wifiAdbWasOn = runCatching {
            Settings.Global.getInt(app.contentResolver, "adb_wifi_enabled", 0) == 1
        }.getOrDefault(true)
        val sdk = android.os.Build.VERSION.SDK_INT
        val cmds = buildList {
            if (sdk > android.os.Build.VERSION_CODES.S) add("settings put global $KEY false")
            // Android 12 has only the limit; raising it helps on later versions too.
            add("device_config set_sync_disabled_for_tests persistent")
            add("device_config put activity_manager max_phantom_processes $MAX")
            add("echo =")
            add("settings get global $KEY")
            add("device_config get activity_manager max_phantom_processes")
        }
        val out = wire.exec("127.0.0.1", cPort, cmds.joinToString("; ")).substringAfterLast("=\n").lines().map { it.trim() }
        val ok = if (sdk > android.os.Build.VERSION_CODES.S) out.getOrNull(0) == "false" || out.getOrNull(1) == MAX else out.getOrNull(1) == MAX
        if (!ok) throw IllegalStateException(str(R.string.phantom_err_not_confirmed, out.joinToString(" / ")))
        Log.i(TAG, "limit switched off (${out.joinToString(" / ")}); Wireless debugging was on before: $wifiAdbWasOn")
        prefs(app).edit().putBoolean("fixed", true).apply()
        // Switching it off closes this very connection, so the command never answers (EOF): expected.
        if (!wifiAdbWasOn) runCatching { wire.exec("127.0.0.1", cPort, "settings put global adb_wifi_enabled 0", 5_000) }
    }
}
