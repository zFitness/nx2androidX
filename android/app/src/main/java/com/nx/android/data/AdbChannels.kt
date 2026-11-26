package com.nx.android.data

import android.content.Context
import android.os.Build
import android.util.Log
import org.conscrypt.Conscrypt
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.Provider
import java.security.interfaces.RSAPrivateCrtKey
import javax.net.ssl.SSLSocket

/**
 * The App's own channel to this phone's adbd: the same client PhantomFix uses to switch off
 * Android's child-process limit (AdbWire.kt), with the shell's rights.
 *
 * The export needs it: the platform lets no App write into another App's Android/data directory
 * (not even with All-files access), but the shell may. The exported game reads its files from
 * its own external directory, so the data has to get there.
 *
 * The key is the App's own (made once, kept out of the backups); the player pairs it once with
 * a pairing code, and the pairing holds until the key is forgotten.
 */
object AdbChannels {
    private const val LOOPBACK = "127.0.0.1"
    private const val TAG = "nx2a-adb"

    /** The App's adb key: made once, kept out of the backups (the same key PhantomFix pairs with). */
    fun key(app: Context): RSAPrivateCrtKey {
        val f = File(app.noBackupFilesDir, "adb-key.pk8")
        if (f.isFile) runCatching { return AdbWire.loadKey(f.readBytes()) }
        val k = AdbWire.newKey()
        val tmp = File(f.path + ".tmp")
        tmp.writeBytes(k.encoded)
        tmp.renameTo(f)
        return k
    }

    /**
     * The port adbd listens on for connections: the ROM publishes it as a property on some
     * builds, the mDNS service answers it on the others.
     */
    fun connectPort(ctx: Context, timeoutMs: Long = 15_000): Int? {
        property(ctx, "service.adb.tls.port")?.toIntOrNull()?.takeIf { it in 1..65535 }?.let { return it }
        var port: Int? = null
        val mdns = AdbMdns(ctx, "_adb-tls-connect._tcp") { port = it }
        mdns.start()
        try {
            val end = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < end && port == null) Thread.sleep(250)
        } finally { mdns.stop() }
        return port
    }

    /** The pairing port (a different one, and it changes): found over mDNS. */
    fun pairPort(ctx: Context, timeoutMs: Long = 15_000): Int? {
        var port: Int? = null
        val mdns = AdbMdns(ctx, "_adb-tls-pairing._tcp") { port = it }
        mdns.start()
        try {
            val end = System.currentTimeMillis() + timeoutMs
            while (System.currentTimeMillis() < end && port == null) Thread.sleep(250)
        } finally { mdns.stop() }
        return port
    }

    /**
     * Pairs with the code shown under Wireless debugging › Pair device with pairing code.
     *
     * The pairing port is found over mDNS unless the caller knows it (the code dialog shows it).
     */
    fun pair(ctx: Context, code: String, pairPort: Int? = null) {
        val port = pairPort ?: pairPort(ctx) ?: throw IOException("the pairing port is unknown (wireless debugging is off?)")
        AdbWire(key(ctx), ConscryptTls, "nx2a@${Build.MODEL}").pair(LOOPBACK, port, code)
    }

    /**
     * Runs a command as the shell user and gives back what it printed.
     *
     * Throws when the key is not paired (the wire says so) or when wireless debugging is off.
     */
    fun exec(ctx: Context, command: String, timeoutMs: Long = 30_000): String {
        val port = connectPort(ctx) ?: throw IOException("adb's port is unknown (wireless debugging is off?)")
        return AdbWire(key(ctx), ConscryptTls, "nx2a@${Build.MODEL}").exec(LOOPBACK, port, command, timeoutMs.toInt())
    }

    /**
     * Runs a command as the shell user, feeding [input] to its stdin, and gives back what it printed.
     *
     * The bytes go down the wire as they are read — the streamed install feeds the APK to `cmd package
     * install -S`, the data goes to a tar that unpacks where it lands. [onSent] reports how much has gone (a
     * game's data takes minutes, and the player watches it move).
     */
    fun exec(ctx: Context, command: String, input: InputStream?,
             onSent: (Long) -> Unit = {}, timeoutMs: Long = 30_000): String {
        val port = connectPort(ctx) ?: throw IOException("adb's port is unknown (wireless debugging is off?)")
        return AdbWire(key(ctx), ConscryptTls, "nx2a@${Build.MODEL}")
            .exec(LOOPBACK, port, command, input, onSent, timeoutMs.toInt())
    }

    /** Whether the App's key is paired with this phone's adbd (a harmless command answers). */
    fun paired(ctx: Context): Boolean = runCatching { exec(ctx, "echo nx2a", 10_000) }
        .onFailure { Log.i(TAG, "the shell channel is not ready: ${it.message}") }
        .isSuccess

    /** A system property's value (the hidden API is not ours to call). */
    private fun property(ctx: Context, name: String): String? = runCatching {
        val p = ProcessBuilder("/system/bin/getprop", name).redirectErrorStream(true).start()
        val out = p.inputStream.bufferedReader().readText().trim()
        p.waitFor()
        out.ifEmpty { null }
    }.getOrNull()

    internal object ConscryptTls : AdbWire.Tls {
        override val provider: Provider by lazy { Conscrypt.newProvider() }
        override fun exportKeyingMaterial(socket: SSLSocket, label: String, length: Int): ByteArray =
            Conscrypt.exportKeyingMaterial(socket, label, null, length)
    }
}
