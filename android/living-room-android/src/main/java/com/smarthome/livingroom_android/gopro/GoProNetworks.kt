package com.smarthome.livingroom_android.gopro

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Build
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Dns
import okhttp3.OkHttpClient
import java.net.UnknownHostException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume

/**
 * Bind OkHttp to a specific [Network]. Needed because GoPro AP has no internet:
 * default routing often uses cellular, so 10.5.5.9 would miss the camera.
 */
object GoProNetworks {
    fun connectivity(context: Context): ConnectivityManager =
        context.applicationContext.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    fun wifiNetworks(cm: ConnectivityManager): List<Network> =
        cm.allNetworks.filter { n ->
            cm.getNetworkCapabilities(n)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        }

    fun internetNetworks(cm: ConnectivityManager, exclude: Network?): List<Network> =
        cm.allNetworks.filter { n ->
            if (n == exclude) return@filter false
            val caps = cm.getNetworkCapabilities(n) ?: return@filter false
            caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        }.sortedByDescending { n ->
            val caps = cm.getNetworkCapabilities(n)
            val validated = caps?.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
            val cellular = caps?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true
            (if (validated) 2 else 0) + (if (cellular) 1 else 0)
        }

    fun client(network: Network?, connectSec: Long, readSec: Long): OkHttpClient {
        val b = OkHttpClient.Builder()
            .connectTimeout(connectSec, TimeUnit.SECONDS)
            .readTimeout(readSec, TimeUnit.SECONDS)
            .writeTimeout(readSec, TimeUnit.SECONDS)
        if (network != null) {
            b.socketFactory(network.socketFactory)
            b.dns(object : Dns {
                override fun lookup(hostname: String): List<java.net.InetAddress> {
                    val addrs = runCatching { network.getAllByName(hostname).toList() }
                        .getOrDefault(emptyList())
                    if (addrs.isEmpty()) throw UnknownHostException(hostname)
                    return addrs
                }
            })
        }
        return b.build()
    }

    suspend fun requestCellular(cm: ConnectivityManager, timeoutMs: Int = 8_000): Network? =
        suspendCancellableCoroutine { cont ->
            val req = NetworkRequest.Builder()
                .addTransportType(NetworkCapabilities.TRANSPORT_CELLULAR)
                .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
                .build()
            val cb = object : ConnectivityManager.NetworkCallback() {
                private fun finish(network: Network?) {
                    runCatching { cm.unregisterNetworkCallback(this) }
                    if (cont.isActive) cont.resume(network)
                }

                override fun onAvailable(network: Network) = finish(network)

                override fun onUnavailable() = finish(null)
            }
            cont.invokeOnCancellation {
                runCatching { cm.unregisterNetworkCallback(cb) }
            }
            try {
                if (Build.VERSION.SDK_INT >= 26) {
                    cm.requestNetwork(req, cb, timeoutMs)
                } else {
                    cm.requestNetwork(req, cb)
                }
            } catch (_: Throwable) {
                if (cont.isActive) cont.resume(null)
            }
        }
}
