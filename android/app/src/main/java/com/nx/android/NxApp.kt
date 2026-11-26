package com.nx.android

import android.app.Application
import com.nx.android.data.AppLocale
import com.nx.android.data.AdbPairing
import com.nx.android.app.AppProcess
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

/**
 * The app's own wiring: every long-lived object is built here, once, and flows one way from here — the UI
 * takes what it shows, the service takes what it runs. Nothing else builds these.
 */
@HiltAndroidApp
class NxApp : Application() {

    val isMainProcess: Boolean by lazy(LazyThreadSafetyMode.NONE) { AppProcess.isMainProcess(this) }

    @Inject lateinit var locale: AppLocale

    override fun onCreate() {
        super.onCreate()
        AppProcess.markStarted()
        if (isMainProcess) AdbPairing.attach(this, locale)
    }
}
