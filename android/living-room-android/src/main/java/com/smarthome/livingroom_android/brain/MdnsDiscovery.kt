package com.smarthome.livingroom_android.brain

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.URL
import kotlin.coroutines.resume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/**
 * mDNS aligned with iOS User Console: Bonjour browse → IPv4 A records → ping verify.
 * HTTP never uses `.local`. TXT `lan_ip` is not trusted over live A records.
 */
object MdnsDiscovery {
    const val BRAIN_TYPE = "_ha-brain._tcp"
    const val GATEWAY_TYPE = "_ha-gateway._tcp"
    const val IMG_SERVER_TYPE = "_ha-img-server._tcp"

    data class Endpoint(val host: String, val port: Int, val txt: Map<String, String>) {
        val baseUrl: String get() = "http://$host:$port"
    }

    fun isUsableLanIPv4(ip: String): Boolean {
        val parts = ip.split('.')
        if (parts.size != 4) return false
        val a = parts[0].toIntOrNull() ?: return false
        val b = parts[1].toIntOrNull() ?: return false
        if (parts.any { it.toIntOrNull() !in 0..255 }) return false
        if (a == 10) return true
        if (a == 172 && b in 16..31) return true
        if (a == 192 && b == 168) return true
        return false
    }

    suspend fun resolve(context: Context, type: String, timeoutMs: Long = 8000): Endpoint? {
        val ipv4 = withContext(Dispatchers.Main) {
            browse(context, type, timeoutMs).filter { isUsableLanIPv4(it.host) }
        }
        return withContext(Dispatchers.IO) {
            DiscoveryDebugLog.log(
                context,
                "browse type=$type count=${ipv4.size} ${ipv4.joinToString { "${it.host}:${it.port}" }}",
                "mDNS browse",
            )
            if (type.startsWith("_ha-brain")) {
                for (ep in ipv4) {
                    if (probeBrain(ep.host, ep.port)) {
                        DiscoveryDebugLog.log(context, "brain ping OK ${ep.baseUrl}", "ping verify")
                        return@withContext ep
                    }
                    DiscoveryDebugLog.log(context, "brain ping FAIL ${ep.baseUrl}", "ping verify")
                }
                return@withContext null
            }
            ipv4.firstOrNull()
        }
    }

    private suspend fun browse(context: Context, type: String, timeoutMs: Long): List<Endpoint> {
        val found = linkedMapOf<String, Endpoint>()
        withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine { cont ->
                val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
                var discovery: NsdManager.DiscoveryListener? = null
                fun finish() {
                    discovery?.let { runCatching { nsd.stopServiceDiscovery(it) } }
                    if (cont.isActive) cont.resume(Unit)
                }
                val browser = object : NsdManager.DiscoveryListener {
                    override fun onDiscoveryStarted(serviceType: String) {}
                    override fun onDiscoveryStopped(serviceType: String) {}
                    override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                        nsd.resolveService(
                            serviceInfo,
                            object : NsdManager.ResolveListener {
                                override fun onServiceResolved(info: NsdServiceInfo) {
                                    val host = ipv4From(info) ?: return
                                    val key = "$host:${info.port}"
                                    found[key] = Endpoint(host, info.port, emptyMap())
                                }
                                override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {}
                            },
                        )
                    }
                    override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
                    override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                        finish()
                    }

                    override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
                }
                discovery = browser
                cont.invokeOnCancellation {
                    runCatching { nsd.stopServiceDiscovery(browser) }
                }
                runCatching {
                    nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, browser)
                }.onFailure { finish() }
            }
        }
        return found.values.toList()
    }

    private fun ipv4From(info: NsdServiceInfo): String? {
        val addr = info.host ?: return null
        val ip = when (addr) {
            is Inet4Address -> addr.hostAddress
            else -> addr.hostAddress?.takeIf { !it.contains(':') }
        } ?: return null
        if (ip.endsWith(".local", ignoreCase = true)) return null
        return ip.takeIf { isUsableLanIPv4(it) }
    }

    private fun probeBrain(host: String, port: Int, timeoutMs: Int = 1000): Boolean {
        val ms = System.currentTimeMillis()
        val url = URL("http://$host:$port/api/v1/ping?client_time_ms=$ms")
        val conn = (url.openConnection() as HttpURLConnection)
        return try {
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.requestMethod = "GET"
            if (conn.responseCode !in 200..299) return false
            val body = conn.inputStream.bufferedReader().readText()
            val json = JSONObject(body)
            json.optString("app") == "brain" ||
                (json.optBoolean("ok") && json.has("server_time_ms"))
        } catch (_: Exception) {
            false
        } finally {
            conn.disconnect()
        }
    }
}
