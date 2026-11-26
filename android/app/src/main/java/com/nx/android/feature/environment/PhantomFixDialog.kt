package com.nx.android.feature.environment

import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.nx.android.R
import com.nx.android.data.AdbPairing
import com.nx.android.core.ui.components.CapsuleButton
import com.nx.android.core.ui.components.QuietButton
import com.nx.android.core.ui.theme.NxPalette

/**
 * The way out of the child-process limit: the automatic fix (the phone pairs with itself over Wireless
 * debugging) and the manual one (a line of adb, or Developer options on Android 14+).
 *
 * The card is the app's own shape (a scrim and a rounded card, like the environment checklist), not a
 * Material dialog: the app's screens do not use them.
 */
@Composable
fun PhantomFixDialog(onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val st = AdbPairing.state
    var devOn by remember { mutableStateOf(AdbPairing.developerOptionsOn(ctx)) }
    var notificationsOn by remember { mutableStateOf(true) }

    // Back from Settings (or the notification prompt): Developer options or notifications may be on now.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                devOn = AdbPairing.developerOptionsOn(ctx)
                notificationsOn = AdbPairing.prepareNotifications(ctx)
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    val close = { if (AdbPairing.state !is AdbPairing.State.Working) AdbPairing.cancel(ctx); onDismiss() }

    Box(
        Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.6f)).clickable { close() },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.widthIn(max = 520.dp)
                .clip(RoundedCornerShape(20.dp))
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(20.dp))
                .background(NxPalette.Surface.copy(alpha = 0.9f))
                .clickable(enabled = false) {},
        ) {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text(stringResource(R.string.phantom_fix_title), style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    QuietButton(stringResource(R.string.phantom_close), close)
                }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                Column(
                    Modifier.fillMaxWidth().heightIn(max = 420.dp).verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Text(stringResource(R.string.phantom_fix_text), style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)

                    Text(stringResource(R.string.phantom_auto_title), style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary)
                    Text(
                        stringResource(if (devOn) R.string.phantom_auto_step1 else R.string.phantom_auto_step1_devoff),
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(stringResource(R.string.phantom_auto_step2), style = MaterialTheme.typography.bodySmall)

                    if (!notificationsOn) {
                        Text(stringResource(R.string.phantom_notifications_off), style = MaterialTheme.typography.bodySmall,
                            color = NxPalette.Danger)
                        QuietButton(stringResource(R.string.phantom_notifications_on), onClick = {
                            runCatching {
                                ctx.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                                    .putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName))
                            }
                        })
                    }

                    FixProgress(st)

                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)

                    Text(stringResource(R.string.phantom_manual_title), style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.primary)
                    if (Build.VERSION.SDK_INT >= 34) {
                        Text(stringResource(R.string.phantom_manual_toggle), style = MaterialTheme.typography.bodySmall)
                    }
                    Text(stringResource(R.string.phantom_manual_pc), style = MaterialTheme.typography.bodySmall)
                    Text(
                        if (Build.VERSION.SDK_INT > 31) "adb shell settings put global settings_enable_monitor_phantom_procs false"
                        else "adb shell device_config set_sync_disabled_for_tests persistent; " +
                            "adb shell device_config put activity_manager max_phantom_processes 2147483647",
                        style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }
    }
}

/** What the fix is doing: the button that starts it, the progress, the way out when it fails */
@Composable
private fun FixProgress(st: AdbPairing.State) {
    val ctx = LocalContext.current
    when (st) {
        AdbPairing.State.Idle -> CapsuleButton(stringResource(R.string.phantom_start_fix), onClick = {
            AdbPairing.begin(ctx)
            AdbPairing.openDeveloperOptions(ctx)
        })
        is AdbPairing.State.Waiting, is AdbPairing.State.Failed -> {
            if (st is AdbPairing.State.Failed) {
                Text(st.message, color = NxPalette.Danger, style = MaterialTheme.typography.bodySmall)
            }
            val port = (st as? AdbPairing.State.Waiting)?.pairPort
            Text(
                stringResource(if (port != null) R.string.phantom_waiting_port else R.string.phantom_waiting, port ?: 0),
                style = MaterialTheme.typography.bodySmall,
            )
            ManualCode()
            QuietButton(stringResource(R.string.phantom_start_fix), onClick = { AdbPairing.openDeveloperOptions(ctx) })
        }
        is AdbPairing.State.Working -> Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = NxPalette.Cream)
            Spacer(Modifier.width(10.dp))
            Text(st.step, style = MaterialTheme.typography.bodyMedium)
        }
        AdbPairing.State.Done -> Text(stringResource(R.string.phantom_done), color = NxPalette.Ready,
            style = MaterialTheme.typography.bodyMedium)
    }
}

/** For split screen, or when the notification does not show: the code (and port) typed in the app. */
@Composable
private fun ManualCode() {
    val ctx = LocalContext.current
    var code by remember { mutableStateOf("") }
    var port by remember { mutableStateOf("") }
    Text(stringResource(R.string.phantom_manual_entry), style = MaterialTheme.typography.bodySmall)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, Modifier.weight(1f), singleLine = true,
            label = { Text(stringResource(R.string.phantom_code_label)) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword))
        OutlinedTextField(port, { port = it.filter(Char::isDigit).take(5) }, Modifier.weight(1f), singleLine = true,
            label = { Text(stringResource(R.string.phantom_port_label)) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
    }
    CapsuleButton(stringResource(R.string.phantom_pair_button), onClick = {
        AdbPairing.submit(ctx, code, port.toIntOrNull())
    }, enabled = code.length == 6)
}
