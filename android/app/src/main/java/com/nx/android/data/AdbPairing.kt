package com.nx.android.data

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import androidx.annotation.StringRes
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.nx.android.R
import java.security.interfaces.RSAPrivateCrtKey
import java.security.Provider
import javax.net.ssl.SSLSocket
import kotlin.concurrent.thread
import org.conscrypt.Conscrypt

/**
 * App 与这台手机的一次配对：玩家在设置里打开「无线调试 › 使用配对码配对设备」，把六位码输进**通知**
 * （RemoteInput）里——App 退到后台也不丢，输完立即配。配好之后做什么，由 [begin] 注册的 [after] 决定：
 * 子进程上限的修复拿它改 device_config，导出 APK 拿它继续安装与搬数据。
 *
 * 配对本身只有一件事：App 的密钥（[AdbChannels.key]，made once）跟这台手机的 adbd 配一次，配对 holds 到
 * 密钥被忘掉为止。配对端口与连接端口都靠 mDNS 找到（服务的连 IP:Port 也可以手填，分屏用）。
 */
object AdbPairing {
    private const val CHANNEL = "adb-pairing"
    private const val NOTIFY_ID = 7
    private const val LOOPBACK = "127.0.0.1"
    private const val TAG = "nx2a-pair"
    const val EXTRA_CODE = "code"

    /** What the pairing is doing now */
    sealed interface State {
        /** Nothing started yet */
        data object Idle : State

        /** Waiting for the pairing code; [pairPort] once Wireless debugging's pairing service is seen */
        data class Waiting(val pairPort: Int?) : State

        /** Working; [step] says what */
        data class Working(val step: String) : State

        /** Paired (and the owner's own work is done) */
        data object Done : State

        /** It did not work; [message] says why */
        data class Failed(val message: String) : State
    }

    var state by mutableStateOf<State>(State.Idle); private set

    @Volatile private var pairPort: Int? = null
    @Volatile private var connectPort: Int? = null
    private var discoveries = listOf<Mdns>()

    /** 配好之后的活儿：PhantomFix 改上限，导出继续安装与搬数据。抛出异常 = 失败（原因给玩家看） */
    private var after: ((app: Context, wire: AdbWire, connectPort: Int) -> Unit)? = null

    /** The app and the words it speaks: set once, when the app starts */
    private var app: Context? = null
    private var locale: AppLocale? = null

    /** Hands the pairing the app and its words: the App wires this once, at startup */
    fun attach(ctx: Context, loc: AppLocale) {
        app = ctx.applicationContext
        locale = loc
    }

    internal fun s(@StringRes id: Int, vararg args: Any?): String {
        val l = locale
        if (l != null) return l.str(id, *args)
        val c = app ?: return ""
        return c.getString(id, *args)
    }

    /** The owner's own step, on the way (the state and the notification's progress line follow) */
    internal fun step(@StringRes id: Int) {
        state = State.Working(s(id))
        app?.let { notifyProgress(it) }
    }

    /**
     * Shows the code notification and starts looking for Wireless debugging's ports. [after] runs once the
     * pairing holds (on the pairing's worker thread); it throws = Failed, with its message shown.
     */
    fun begin(ctx: Context, after: ((app: Context, wire: AdbWire, connectPort: Int) -> Unit)? = null) {
        val app = ctx.applicationContext
        this.after = after
        pairPort = null
        connectPort = null
        stopDiscovery()
        discoveries = listOf(
            Mdns(app, "_adb-tls-pairing._tcp") { pairPort = it; if (state is State.Waiting) state = State.Waiting(it) },
            Mdns(app, "_adb-tls-connect._tcp") { connectPort = it },
        ).onEach { it.start() }
        state = State.Waiting(null)
        notifyCodeRequest(app)
    }

    fun cancel(ctx: Context) {
        stopDiscovery()
        ctx.getSystemService(NotificationManager::class.java)?.cancel(NOTIFY_ID)
        if (state !is State.Working) state = State.Idle
    }

    private fun stopDiscovery() { discoveries.forEach { it.stop() }; discoveries = emptyList() }

    /**
     * Pairs with [code] (the port overrides the one discovered — the "IP address & Port" line of the code
     * dialog), then runs the owner's [after]. [done] runs on the worker thread either way.
     */
    fun submit(ctx: Context, code: String, port: Int? = null, done: () -> Unit = {}) {
        val app = ctx.applicationContext
        if (state is State.Working) { done(); return }
        val work = after
        state = State.Working(s(R.string.phantom_step_pairing))
        notifyProgress(app)
        thread(name = "adb-pairing") {
            try {
                val wire = pair(app, code.filter(Char::isDigit), port)
                val cPort = connectPortOf(app)
                if (work != null) {
                    work(app, wire, cPort)
                } else {
                    state = State.Done
                }
            } catch (e: AdbWire.PairingRejected) {
                state = State.Failed(s(R.string.phantom_err_code))
            } catch (e: Exception) {
                Log.w(TAG, "pairing failed", e)
                state = State.Failed(e.message ?: e.javaClass.simpleName)
            } finally {
                notifyResult(app)
                done()
            }
        }
    }

    /** Pairs, then waits for the connection port to show up. The wire is ready to run commands. */
    private fun pair(app: Context, code: String, portOverride: Int?): AdbWire {
        if (code.length != 6) throw IllegalArgumentException(s(R.string.phantom_err_code_format))
        val wire = AdbWire(key(app), ConscryptTls, "nx2a@${Build.MODEL}")
        val pPort = portOverride ?: waitFor(15_000) { pairPort } ?: throw IllegalStateException(s(R.string.phantom_err_no_pairing))
        wire.pair(LOOPBACK, pPort, code)
        state = State.Working(s(R.string.phantom_step_connecting))
        return wire
    }

    /** The connection port: Android publishes it as a property on some ROMs, always over mDNS. */
    private fun connectPortOf(app: Context): Int =
        getprop("service.adb.tls.port").toIntOrNull()?.takeIf { it in 1..65535 }
            ?: waitFor(15_000) { connectPort }
            ?: throw IllegalStateException(s(R.string.phantom_err_no_connect))

    private fun waitFor(ms: Long, value: () -> Int?): Int? {
        val end = System.currentTimeMillis() + ms
        while (System.currentTimeMillis() < end) { value()?.let { return it }; Thread.sleep(250) }
        return value()
    }

    /** The App's adb key, made once; kept out of backups. */
    private fun key(app: Context): RSAPrivateCrtKey = AdbChannels.key(app)

    internal object ConscryptTls : AdbWire.Tls {
        override val provider: Provider by lazy { Conscrypt.newProvider() }
        override fun exportKeyingMaterial(socket: SSLSocket, label: String, length: Int): ByteArray =
            Conscrypt.exportKeyingMaterial(socket, label, null, length)
    }

    private fun getprop(name: String): String = runCatching {
        val p = ProcessBuilder("/system/bin/getprop", name).redirectErrorStream(true).start()
        val out = p.inputStream.bufferedReader().readText()
        p.waitFor()
        out
    }.getOrElse { "" }.trim()

    fun developerOptionsOn(ctx: Context) = runCatching {
        Settings.Global.getInt(ctx.contentResolver, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) == 1
    }.getOrDefault(true)

    /**
     * Opens Developer options at the Wireless debugging row, or "About phone" (where the build
     * number is tapped 7 times) while Developer options are off: their page would only show a
     * toast and close.
     */
    fun openDeveloperOptions(ctx: Context) {
        // Settings scrolls to (and highlights) the preference named in its fragment arguments.
        val key = "toggle_adb_wireless"
        val dev = Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS)
            .putExtra(":settings:fragment_args_key", key)
            .putExtra(":settings:show_fragment_args", Bundle().apply { putString(":settings:fragment_args_key", key) })
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
        val about = Intent(Settings.ACTION_DEVICE_INFO_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { ctx.startActivity(if (developerOptionsOn(ctx)) dev else about) }
    }

    // --- Notification: the code is typed here while Settings shows it --------------------------

    /**
     * Creates the channel early, while the app is in front: on Android 13+ an app that targets an
     * older SDK gets the notification permission prompt only then, not once Settings is open.
     */
    fun prepareNotifications(ctx: Context): Boolean = channel(ctx.applicationContext).areNotificationsEnabled()

    private fun channel(app: Context): NotificationManager {
        val nm = app.getSystemService(NotificationManager::class.java)
        // High importance: shown over Settings as a heads-up, where the code is.
        nm.createNotificationChannel(NotificationChannel(CHANNEL, s(R.string.lib_apk_pair_channel), NotificationManager.IMPORTANCE_HIGH))
        return nm
    }

    private fun base(app: Context) = Notification.Builder(app, CHANNEL)
        .setSmallIcon(android.R.drawable.ic_lock_idle_lock)
        .setContentTitle(s(R.string.phantom_notify_title))
        .setOnlyAlertOnce(true)

    /** Asks for the code; [problem] (the last attempt's error) goes first. */
    private fun notifyCodeRequest(app: Context, problem: String? = null) {
        val nm = channel(app)
        val input = RemoteInput.Builder(EXTRA_CODE).setLabel(s(R.string.phantom_code_label)).build()
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0)
        val reply = PendingIntent.getBroadcast(app, 0, Intent(app, AdbPairingReceiver::class.java), flags)
        val action = Notification.Action.Builder(null, s(R.string.phantom_code_action), reply).addRemoteInput(input).build()
        val text = listOfNotNull(problem, s(R.string.phantom_notify_code)).joinToString("\n")
        nm.notify(NOTIFY_ID, base(app).setContentText(problem ?: text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .addAction(action).setOngoing(true).build())
    }

    private fun notifyProgress(app: Context) {
        val step = (state as? State.Working)?.step ?: s(R.string.phantom_step_pairing)
        channel(app).notify(NOTIFY_ID, base(app).setContentText(step)
            .setProgress(0, 0, true).setOngoing(true).build())
    }

    private fun notifyResult(app: Context) {
        when (val st = state) {
            is State.Done -> channel(app).notify(NOTIFY_ID, base(app).setContentText(s(R.string.lib_apk_pair_done)).setAutoCancel(true).build())
            // Ask again (a mistyped code is the usual cause), with the reason.
            is State.Failed -> notifyCodeRequest(app, st.message)
            else -> {}
        }
    }

    /** One mDNS service type, resolved to a port when the service runs on this phone. */
    private class Mdns(app: Context, private val type: String, private val onPort: (Int) -> Unit) {
        private val nsd = app.getSystemService(NsdManager::class.java)
        private val queue = ArrayDeque<NsdServiceInfo>()
        private var resolving = false
        @Volatile private var stopped = false

        private val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(t: String) {}
            override fun onDiscoveryStopped(t: String) {}
            override fun onStartDiscoveryFailed(t: String, e: Int) {}
            override fun onStopDiscoveryFailed(t: String, e: Int) {}
            override fun onServiceLost(s: NsdServiceInfo) {}
            override fun onServiceFound(s: NsdServiceInfo) { synchronized(queue) { queue.addLast(s) }; next() }
        }

        fun start() = runCatching { nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, listener) }
        fun stop() { stopped = true; runCatching { nsd.stopServiceDiscovery(listener) } }

        // NsdManager resolves one service at a time (FAILURE_ALREADY_ACTIVE otherwise).
        private fun next() {
            val s = synchronized(queue) { if (resolving || stopped) null else queue.removeFirstOrNull()?.also { resolving = true } } ?: return
            @Suppress("DEPRECATION")
            runCatching {
                nsd.resolveService(s, object : NsdManager.ResolveListener {
                    override fun onResolveFailed(si: NsdServiceInfo, e: Int) { done() }
                    override fun onServiceResolved(si: NsdServiceInfo) {
                        @Suppress("DEPRECATION") val host = si.host
                        if (host != null && isThisPhone(host) && si.port in 1..65535) onPort(si.port)
                        done()
                    }
                })
            }.onFailure { done() }
        }

        private fun done() { synchronized(queue) { resolving = false }; next() }

        private fun isThisPhone(a: java.net.InetAddress): Boolean = a.isLoopbackAddress || runCatching {
            java.net.NetworkInterface.getNetworkInterfaces().toList().any { i -> i.inetAddresses.toList().any { it.address.contentEquals(a.address) } }
        }.getOrDefault(false)
    }
}

/** The pairing code typed into the notification (the shade shows it while Settings shows the code). */
class AdbPairingReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val code = RemoteInput.getResultsFromIntent(intent)?.getCharSequence(AdbPairing.EXTRA_CODE)?.toString() ?: return
        val pending = goAsync()
        AdbPairing.submit(context, code) { pending.finish() }
    }
}
