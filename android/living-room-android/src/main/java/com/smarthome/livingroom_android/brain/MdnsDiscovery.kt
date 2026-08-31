package com.smarthome.livingroom_android.brain

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import kotlin.coroutines.resume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * mDNS resolver for Home Agent well-known LAN services (Android NsdManager).
 *
 * Well-known types (labels <= 15 bytes, RFC 6763 §7.1):
 *   _ha-brain._tcp         Brain (server/home_brain.py)        :9527
 *   _ha-gateway._tcp       Mac Edge gateway (voice/video rx)   TXT ports
 *   _ha-img-server._tcp    img-server (img-server/serve.py)    :8080
 */
object MdnsDiscovery {
    const val BRAIN_TYPE = "_ha-brain._tcp"
    const val GATEWAY_TYPE = "_ha-gateway._tcp"
    const val IMG_SERVER_TYPE = "_ha-img-server._tcp"

    data class Endpoint(val host: String, val port: Int, val txt: Map<String, String>) {
        val baseUrl: String get() = "http://$host:$port"
    }

    /** Resolve the first service of `type`; null when not found on the LAN. */
    suspend fun resolve(context: Context, type: String, timeoutMs: Long = 3000): Endpoint? =
        withContext(Dispatchers.Main) {
            withTimeoutOrNull(timeoutMs) {
                suspendCancellableCoroutine { cont ->
                    val nsd = context.getSystemService(Context.NSD_SERVICE) as NsdManager
                    var done = false
                    var discovery: NsdManager.DiscoveryListener? = null

                    fun finish(endpoint: Endpoint?) {
                        if (done) return
                        done = true
                        discovery?.let { runCatching { nsd.stopServiceDiscovery(it) } }
                        if (cont.isActive) cont.resume(endpoint)
                    }

                    val browser = object : NsdManager.DiscoveryListener {
                        override fun onDiscoveryStarted(serviceType: String) {}
                        override fun onDiscoveryStopped(serviceType: String) {}
                        override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                            if (done) return
                            nsd.resolveService(
                                serviceInfo,
                                object : NsdManager.ResolveListener {
                                    override fun onServiceResolved(info: NsdServiceInfo) {
                                        val host = info.host?.hostAddress ?: return finish(null)
                                        finish(Endpoint(host, info.port, emptyMap()))
                                    }

                                    override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                                        finish(null)
                                    }

                                    override fun onServiceLost(info: NsdServiceInfo) {}
                                },
                            )
                        }

                        override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
                        override fun onDiscoveryFailed(serviceType: String, errorCode: Int) {
                            finish(null)
                        }
                    }
                    discovery = browser
                    cont.invokeOnCancellation {
                        runCatching { nsd.stopServiceDiscovery(browser) }
                    }
                    runCatching {
                        nsd.discoverServices(type, NsdManager.PROTOCOL_DNS_SD, browser)
                    }.onFailure { finish(null) }
                }
            }
        }
}
