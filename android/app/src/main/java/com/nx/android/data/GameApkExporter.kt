package com.nx.android.data

import com.nx.android.domain.PortEvents
import com.nx.android.domain.environment.GuestProcessLauncher
import java.io.File
import javax.inject.Inject

/** What the guest's export command made: the APK, and whether it worked. */
data class GameApkBuild(
    val ok: Boolean,
    val reason: String = "",
    val apk: String = "",
    val packageName: String = "",
    val size: Long = 0L,
)

/**
 * Runs the porter's export command in the guest: it builds the host for a NativeActivity of its own (the
 * upstream's APK front, dm/android/front_android.c) and packs the APK. The signing is the Python standard
 * library's own (mkapk.py: no JDK, no Android SDK), so nothing else is needed on the phone.
 */
class GameApkExporter @Inject constructor(private val guestLauncher: GuestProcessLauncher) {

    /**
     * Builds the APK of a game whose data folder is ready.
     *
     * @param dataFolder the self-sufficient data folder (the manifest, the icon, the theme)
     * @param apk where to write the APK
     * @param key the signing key (the app's own: every exported game shares it)
     * @param driver the Vulkan driver the APK carries, null for the device's own
     * @param vercodeOffset the versionCode offset (the app counts the exports of the same game)
     */
    fun build(dataFolder: File, apk: File, key: File, driver: File?, vercodeOffset: Int,
              packageName: String = "", versionName: String = "", log: (String) -> Unit): GameApkBuild {
        var reason = ""
        var built = GameApkBuild(false)
        return try {
            val process = guestLauncher.guest(args(dataFolder, apk, key, driver, vercodeOffset, packageName, versionName))
            process.inputStream.bufferedReader().useLines { lines ->
                lines.forEach { line ->
                    val event = PortEvents.parse(line)
                    val message = event?.message?.takeIf { it.isNotBlank() } ?: line
                    log(message)
                    if (message.startsWith("[RED] ")) reason = message.removePrefix("[RED] ")
                    if (event?.kind == "result") {
                        built = GameApkBuild(true, "", event.apk, event.pkg, 0L)
                    }
                }
            }
            val code = process.waitFor()
            if (code != 0) {
                GameApkBuild(false, reason.ifEmpty { "The export command exited with code $code" })
            } else if (!built.ok) {
                GameApkBuild(false, reason.ifEmpty { "The export command did not report an APK" })
            } else {
                GameApkBuild(true, "", apk.absolutePath, built.packageName, apk.length())
            }
        } catch (error: Exception) {
            GameApkBuild(false, error.message.orEmpty())
        }
    }

    companion object {
        /** The command line the guest runs. */
        fun args(dataFolder: File, apk: File, key: File, driver: File?, vercodeOffset: Int,
                 packageName: String = "", versionName: String = ""): List<String> {
            val args = mutableListOf(
                "-m", "porter.phone_cli", "export-apk", dataFolder.absolutePath,
                "--out", apk.absolutePath,
                "--key", key.absolutePath,
                "--vercode-offset", vercodeOffset.toString(),
                "--progress", "json",
            )
            if (packageName.isNotBlank()) args += listOf("--package", packageName)
            if (versionName.isNotBlank()) args += listOf("--version-name", versionName)
            if (driver != null) args += listOf("--driver", driver.absolutePath)
            return args
        }
    }
}
