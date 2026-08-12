package com.smarthome.plugin.gopro

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.SupplicantState
import android.net.wifi.WifiInfo
import android.net.wifi.WifiManager
import android.net.wifi.WifiNetworkSpecifier
import android.net.wifi.WifiNetworkSuggestion
import android.os.Build
import android.provider.Settings
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Join a named Wi‑Fi (e.g. GoPro AP).
 *
 * Visible status-bar switch: [Settings.ACTION_WIFI_ADD_NETWORKS] + strict SSID/BSSID confirm.
 * Peer bind (may not change status bar): [WifiNetworkSpecifier].
 */
class GoProWifiCoordinator(
    context: Context,
    private val homeProbeUrl: String,
    private val goproProbeUrl: String = "http://10.5.5.9/gp/gpControl/status",
) {
    private val appContext = context.applicationContext
    private val cm = appContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    private val wifiManager = appContext.getSystemService(Context.WIFI_SERVICE) as WifiManager

    @Volatile
    private var tempNetwork: Network? = null

    @Volatile
    private var callback: ConnectivityManager.NetworkCallback? = null

    data class WifiSnapshot(
        val ssid: String?,
        val bssid: String?,
        val networkId: Int,
        val supplicant: String,
        val rssi: Int,
        val transportWifi: Boolean,
    ) {
        val summary: String
            get() = "ssid=${ssid ?: "?"} bssid=${bssid ?: "?"} nid=$networkId " +
                "state=$supplicant rssi=$rssi wifiTransport=$transportWifi"
    }

    data class JoinResult(
        val ssid: String,
        val primarySsid: String?,
        val boundSsid: String?,
        val goproReachable: Boolean,
        val mode: String,
        val snapshot: WifiSnapshot? = null,
    )

    /**
     * Specifier path: shows system「连接到设备」sheet. Does **not** guarantee status-bar SSID change.
     */
    suspend fun connectViaSpecifier(
        activity: Activity,
        ssid: String,
        password: String?,
        timeoutMs: Long = 60_000L,
        onProgress: (String) -> Unit = {},
    ): JoinResult {
        val trimmed = validateSsidPassword(ssid, password, onProgress)
        val pass = password?.trim().orEmpty().ifBlank { null }
        disconnectGoPro(bindHome = false)
        onProgress("当前：${primarySnapshot().summary}")

        val errors = mutableListOf<String>()
        for (localOnly in listOf(true, false)) {
            onProgress("弹出「连接到设备」localOnly=$localOnly — 请点「连接」")
            try {
                val network = requestSpecifierNetwork(
                    activity = activity,
                    ssid = trimmed,
                    password = pass,
                    localOnly = localOnly,
                    timeoutMs = timeoutMs,
                )
                tempNetwork = network
                cm.bindProcessToNetwork(network)

                val bound = ssidOf(network)
                val snap = primarySnapshot()
                onProgress("onAvailable bound=${bound ?: "?"}｜$snap")

                val goproOk = withContext(Dispatchers.IO) { probeHttp(goproProbeUrl, network) }
                val boundOk = bound != null && ssidEquals(bound, trimmed)
                if (!boundOk && !goproOk) {
                    disconnectGoPro(bindHome = false)
                    error(
                        "未确认绑定到「$trimmed」（bound=${bound ?: "无"}，GoPro 不可达）。$snap",
                    )
                }
                onProgress(
                    if (isConfirmedOnSsid(trimmed, snap)) {
                        "成功：状态栏已在「$trimmed」"
                    } else {
                        "成功：进程已绑定「${bound ?: trimmed}」" +
                            "（状态栏仍是「${snap.ssid ?: "未知"}」— Specifier 常不改状态栏）"
                    },
                )
                return JoinResult(
                    ssid = trimmed,
                    primarySsid = snap.ssid,
                    boundSsid = bound,
                    goproReachable = goproOk,
                    mode = "specifier_localOnly_$localOnly",
                    snapshot = snap,
                )
            } catch (t: Throwable) {
                errors += "localOnly=$localOnly → ${t.message ?: t.javaClass.simpleName}"
                Log.w(TAG, "specifier failed localOnly=$localOnly", t)
                disconnectGoPro(bindHome = false)
            }
        }
        error(errors.joinToString(" | ").ifBlank { "Specifier 加入失败" })
    }

    /**
     * After [Settings.ACTION_WIFI_ADD_NETWORKS] returns, wait until primary Wi‑Fi is
     * **confirmed** on [ssid] (SSID + BSSID + COMPLETED, consecutive samples).
     */
    suspend fun waitForConfirmedPrimarySsid(
        ssid: String,
        timeoutMs: Long = 45_000L,
        onProgress: (String) -> Unit = {},
        baseline: WifiSnapshot? = primarySnapshot(),
    ): JoinResult {
        val trimmed = ssid.trim()
        require(trimmed.isNotEmpty()) { "SSID 为空" }
        onProgress("等待状态栏确认切到「$trimmed」… 基准：${baseline?.summary}")

        val deadline = System.currentTimeMillis() + timeoutMs
        var streak = 0
        var lastLog: String? = null
        while (System.currentTimeMillis() < deadline) {
            val snap = primarySnapshot()
            val line = snap.summary
            if (line != lastLog) {
                onProgress("轮询：$line")
                lastLog = line
            }
            if (isConfirmedOnSsid(trimmed, snap)) {
                streak++
                if (streak >= CONFIRM_STREAK) {
                    // Reject “already looked like target” without a real association change
                    // only when baseline was already confirmed on same SSID+BSSID.
                    val sameAsBaseline = baseline != null &&
                        isConfirmedOnSsid(trimmed, baseline) &&
                        !baseline.bssid.isNullOrBlank() &&
                        baseline.bssid.equals(snap.bssid, ignoreCase = true)
                    if (sameAsBaseline) {
                        onProgress("已在目标网（基准相同），视为成功")
                    }
                    val goproOk = withContext(Dispatchers.IO) { probeHttp(goproProbeUrl) }
                    return JoinResult(
                        ssid = trimmed,
                        primarySsid = snap.ssid,
                        boundSsid = null,
                        goproReachable = goproOk,
                        mode = "system_add_networks",
                        snapshot = snap,
                    )
                }
            } else {
                streak = 0
            }
            delay(500)
        }
        val cur = primarySnapshot()
        error(
            "超时未确认切到「$trimmed」。当前：${cur.summary}" +
                "（仅 SSID 字符串一致不够，需 BSSID + 已连接）",
        )
    }

    fun buildAddNetworksIntent(ssid: String, password: String?): Intent {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            error("系统「添加网络」需要 Android 11+")
        }
        val trimmed = ssid.trim()
        require(trimmed.isNotEmpty()) { "SSID 为空" }
        val builder = WifiNetworkSuggestion.Builder().setSsid(trimmed)
        val pass = password?.trim().orEmpty()
        if (pass.isNotEmpty()) {
            if (pass.length < 8 || pass.length > 63) {
                error("Wi‑Fi 密码长度须为 8–63 位（当前 ${pass.length}）")
            }
            builder.setWpa2Passphrase(pass)
        }
        return Intent(Settings.ACTION_WIFI_ADD_NETWORKS).apply {
            putParcelableArrayListExtra(
                Settings.EXTRA_WIFI_NETWORK_LIST,
                arrayListOf(builder.build()),
            )
        }
    }

    fun openSystemAddNetworkSheet(activity: Activity, ssid: String, password: String?) {
        val intent = buildAddNetworksIntent(ssid, password)
        if (intent.resolveActivity(activity.packageManager) == null) {
            error("本机无法打开 ACTION_WIFI_ADD_NETWORKS")
        }
        activity.startActivity(intent)
    }

    fun openWifiSettings(activity: Activity) {
        activity.startActivity(Intent(Settings.ACTION_WIFI_SETTINGS))
    }

    fun bindGoProIfHeld() {
        tempNetwork?.let { cm.bindProcessToNetwork(it) }
    }

    fun disconnectGoPro(bindHome: Boolean = true) {
        callback?.let { cb -> runCatching { cm.unregisterNetworkCallback(cb) } }
        callback = null
        tempNetwork = null
        if (bindHome) cm.bindProcessToNetwork(null)
        Log.i(TAG, "released temp Wi‑Fi")
    }

    suspend fun waitUntilHomeReady(
        timeoutMs: Long = 90_000L,
        pollMs: Long = 2_000L,
        onProgress: (String) -> Unit = {},
    ) {
        disconnectGoPro(bindHome = true)
        val deadline = System.currentTimeMillis() + timeoutMs
        var attempt = 0
        while (System.currentTimeMillis() < deadline) {
            attempt++
            if (probeHttp(homeProbeUrl)) {
                onProgress("home network ready (attempt=$attempt)")
                return
            }
            if (attempt <= 3 || attempt % 3 == 0) {
                onProgress("waiting for home / probe $homeProbeUrl ($attempt)")
            }
            delay(pollMs)
        }
        error("home network timeout ${timeoutMs / 1000}s")
    }

    /** @deprecated Use Specifier or Activity-Result + [waitForConfirmedPrimarySsid]. */
    suspend fun connectGoPro(
        activity: Activity,
        ssid: String,
        password: String?,
        timeoutMs: Long = 60_000L,
        onProgress: (String) -> Unit = {},
        preferVisibleSwitch: Boolean = false,
    ): JoinResult {
        if (preferVisibleSwitch && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            onProgress("打开系统添加网络（无 Activity Result 时可能无界面）…")
            withContext(Dispatchers.Main) {
                openSystemAddNetworkSheet(activity, ssid, password)
            }
            return waitForConfirmedPrimarySsid(ssid, timeoutMs, onProgress)
        }
        return connectViaSpecifier(activity, ssid, password, timeoutMs, onProgress)
    }

    fun primarySsid(): String? = primarySnapshot().ssid

    fun primarySnapshot(): WifiSnapshot {
        @Suppress("DEPRECATION")
        val info = wifiManager.connectionInfo
        val caps = cm.activeNetwork?.let { cm.getNetworkCapabilities(it) }
        val fromTransport = (caps?.transportInfo as? WifiInfo)
        val ssid = normalizeSsid(fromTransport?.ssid) ?: normalizeSsid(info?.ssid)
        val bssid = normalizeBssid(fromTransport?.bssid) ?: normalizeBssid(info?.bssid)
        val nid = when {
            fromTransport != null && fromTransport.networkId >= 0 -> fromTransport.networkId
            else -> info?.networkId ?: -1
        }
        val supp = (fromTransport?.supplicantState ?: info?.supplicantState)?.name ?: "?"
        val rssi = fromTransport?.rssi ?: info?.rssi ?: 0
        val wifiTransport = caps?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        return WifiSnapshot(ssid, bssid, nid, supp, rssi, wifiTransport)
    }

    fun ssidOf(network: Network): String? {
        val caps = cm.getNetworkCapabilities(network) ?: return null
        val info = caps.transportInfo
        if (info is WifiInfo) return normalizeSsid(info.ssid)
        if (cm.activeNetwork == network) {
            @Suppress("DEPRECATION")
            return normalizeSsid(wifiManager.connectionInfo?.ssid)
        }
        return null
    }

    fun isConfirmedOnSsid(target: String, snap: WifiSnapshot = primarySnapshot()): Boolean {
        if (!ssidEquals(snap.ssid ?: return false, target)) return false
        if (!snap.transportWifi) return false
        if (snap.bssid.isNullOrBlank()) return false
        if (snap.networkId < 0) return false
        // Must be fully associated — SSID string alone is not enough (caused false "已加入").
        return snap.supplicant in setOf(
            SupplicantState.COMPLETED.name,
            SupplicantState.ASSOCIATED.name,
        )
    }

    fun probeHttp(url: String, network: Network? = null): Boolean =
        try {
            val builder = OkHttpClient.Builder()
                .connectTimeout(2, TimeUnit.SECONDS)
                .readTimeout(2, TimeUnit.SECONDS)
            if (network != null) {
                builder.socketFactory(network.socketFactory)
            }
            builder.build()
                .newCall(Request.Builder().url(url).get().build())
                .execute()
                .use { true }
        } catch (_: Throwable) {
            false
        }

    private fun validateSsidPassword(
        ssid: String,
        password: String?,
        onProgress: (String) -> Unit,
    ): String {
        val trimmed = ssid.trim()
        require(trimmed.isNotEmpty()) { "SSID 为空" }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) error("需要 Android 10+")
        val pass = password?.trim().orEmpty()
        if (pass.isNotEmpty() && (pass.length < 8 || pass.length > 63)) {
            error("Wi‑Fi 密码长度须为 8–63 位（当前 ${pass.length}）")
        }
        if (!isLocationEnabled()) {
            onProgress("警告：定位未开，SSID/BSSID 可能读不到")
        }
        return trimmed
    }

    private suspend fun requestSpecifierNetwork(
        activity: Activity,
        ssid: String,
        password: String?,
        localOnly: Boolean,
        timeoutMs: Long,
    ): Network = withContext(Dispatchers.Main) {
        val activityCm =
            activity.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val specifierBuilder = WifiNetworkSpecifier.Builder().setSsid(ssid)
        if (!password.isNullOrBlank()) {
            specifierBuilder.setWpa2Passphrase(password)
        }
        val reqBuilder = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
            .setNetworkSpecifier(specifierBuilder.build())
        if (localOnly) {
            reqBuilder.removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        }
        val request = reqBuilder.build()

        withTimeout(timeoutMs) {
            suspendCancellableCoroutine { cont ->
                val cb = object : ConnectivityManager.NetworkCallback() {
                    override fun onAvailable(network: Network) {
                        Log.i(TAG, "onAvailable $network localOnly=$localOnly")
                        if (cont.isActive) cont.resume(network)
                    }

                    override fun onUnavailable() {
                        Log.w(TAG, "onUnavailable localOnly=$localOnly")
                        if (cont.isActive) {
                            cont.resumeWithException(
                                IllegalStateException(
                                    "系统未连接（取消了面板 / 密码错误 / 找不到 SSID）",
                                ),
                            )
                        }
                    }

                    override fun onLost(network: Network) {
                        Log.w(TAG, "onLost $network")
                    }
                }
                callback = cb
                try {
                    activityCm.requestNetwork(request, cb)
                } catch (t: Throwable) {
                    if (cont.isActive) cont.resumeWithException(t)
                    return@suspendCancellableCoroutine
                }
                cont.invokeOnCancellation {
                    runCatching { activityCm.unregisterNetworkCallback(cb) }
                }
            }
        }
    }

    private fun isLocationEnabled(): Boolean {
        val lm = appContext.getSystemService(Context.LOCATION_SERVICE) as? LocationManager
            ?: return true
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            lm.isLocationEnabled
        } else {
            @Suppress("DEPRECATION")
            lm.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
                lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        }
    }

    companion object {
        private const val TAG = "WifiSwitch"
        private const val CONFIRM_STREAK = 3

        fun normalizeSsid(raw: String?): String? {
            if (raw.isNullOrBlank()) return null
            var s = raw.trim()
            if (s == WifiManager.UNKNOWN_SSID || s == "<unknown ssid>") return null
            if (s.length >= 2 && s.startsWith("\"") && s.endsWith("\"")) {
                s = s.substring(1, s.length - 1)
            }
            return s.ifBlank { null }
        }

        fun normalizeBssid(raw: String?): String? {
            if (raw.isNullOrBlank()) return null
            val s = raw.trim().lowercase()
            if (s == "02:00:00:00:00:00" || s == "00:00:00:00:00:00" || s == "any") return null
            return s
        }

        fun ssidEquals(a: String, b: String): Boolean =
            normalizeSsid(a)?.equals(normalizeSsid(b), ignoreCase = true) == true
    }
}
