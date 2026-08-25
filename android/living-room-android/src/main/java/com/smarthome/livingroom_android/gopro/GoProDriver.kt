package com.smarthome.livingroom_android.gopro

import android.content.Context
import android.net.Network
import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject

/** GoPro gpControl on the phone. No Wi‑Fi join/switch — camera HTTP only. */
class GoProDriver(
    private val appContext: Context,
    private val baseHost: String = DEFAULT_HOST,
) {
    data class Probe(val ok: Boolean, val message: String, val network: Network? = null)

    data class MediaItem(
        val folder: String,
        val name: String,
        val timestamp: String,
        val isStill: Boolean,
    ) {
        val path: String
            get() = if (folder.isEmpty()) "/videos/DCIM/$name" else "/videos/DCIM/$folder/$name"
    }

    private val host = baseHost.trimEnd('/')

    suspend fun probeAvailable(timeoutSeconds: Long = 2): Probe = withContext(Dispatchers.IO) {
        val cm = GoProNetworks.connectivity(appContext)
        val candidates = buildList<Network?> {
            addAll(GoProNetworks.wifiNetworks(cm))
            add(null)
        }
        var last = "连不上 GoPro"
        for (net in candidates.distinct()) {
            val client = GoProNetworks.client(net, timeoutSeconds, timeoutSeconds)
            val result = runCatching { get(client, host + PATH_STATUS) }
            result.onSuccess { body ->
                if (body.http in 200..299) {
                    return@withContext Probe(true, "available", net)
                }
                last = "GoPro HTTP ${body.http}"
            }
            result.onFailure { last = it.message ?: last }
        }
        Probe(
            ok = false,
            message = "拍照不可用：连不上 GoPro（$last）。请确认已连相机热点且相机开机。",
        )
    }

    suspend fun captureJpeg(network: Network?): ByteArray = withContext(Dispatchers.IO) {
        val client = GoProNetworks.client(network, 8, 20)
        val statusBody = get(client, host + PATH_STATUS).text
        val snap = GoProStatusSnapshot.parse(statusBody)
        if (snap?.isBusy == true) {
            runCatching { get(client, host + PATH_SHUTTER_STOP) }
            delay(600)
        }
        get(client, host + PATH_MODE_PHOTO)
        runCatching { get(client, host + PATH_SUB_MODE_PHOTO) }
        delay(500)
        val mid = GoProStatusSnapshot.parse(get(client, host + PATH_STATUS).text)
        if (mid != null && mid.mode != GoProStatusSnapshot.Mode.PHOTO) {
            error("未能切到拍照模式，当前：${mid.displayLine}。请先停止录像/延时计时后再拍。")
        }
        get(client, host + PATH_SHUTTER_START)
        delay(2_000)
        val list = get(client, host + PATH_MEDIA_LIST).text
        val item = extractLatestStill(list)
            ?: error("拍照失败：相机媒体库里没有照片。")
        val downloadClient = GoProNetworks.client(network, 8, 120)
        val primary = mediaBaseHost + item.path
        val bytes = runCatching { getBytes(downloadClient, primary) }.getOrElse { first ->
            val fallback = host + item.path
            if (fallback == primary) throw first
            runCatching { getBytes(downloadClient, fallback) }.getOrElse { throw first }
        }
        if (bytes.isEmpty()) error("拍照失败：下载的照片是空的。")
        Log.i(TAG, "downloaded ${item.path} ${bytes.size} bytes")
        bytes
    }

    private val mediaBaseHost: String
        get() {
            val rest = host.removePrefix("http://").removePrefix("https://")
            val name = rest.substringBefore("/")
            val hostname = name.substringBefore(":")
            return "http://$hostname:8080"
        }

    private data class HttpText(val http: Int, val text: String)

    private fun get(client: OkHttpClient, url: String): HttpText {
        val req = Request.Builder().url(url).get().build()
        client.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (resp.code !in 200..299) {
                error("GoPro HTTP ${resp.code}：${text.take(120)}")
            }
            return HttpText(resp.code, text)
        }
    }

    private fun getBytes(client: OkHttpClient, url: String): ByteArray {
        val req = Request.Builder().url(url).get().build()
        client.newCall(req).execute().use { resp ->
            if (resp.code !in 200..299) {
                error("GoPro 下载 HTTP ${resp.code}")
            }
            return resp.body?.bytes() ?: ByteArray(0)
        }
    }

    companion object {
        private const val TAG = "GoProDriver"
        const val DEFAULT_HOST = "http://10.5.5.9"
        private const val PATH_STATUS = "/gp/gpControl/status"
        private const val PATH_MODE_PHOTO = "/gp/gpControl/command/mode?p=1"
        private const val PATH_SUB_MODE_PHOTO = "/gp/gpControl/command/sub_mode?mode=1&sub_mode=0"
        private const val PATH_SHUTTER_START = "/gp/gpControl/command/shutter?p=1"
        private const val PATH_SHUTTER_STOP = "/gp/gpControl/command/shutter?p=0"
        private const val PATH_MEDIA_LIST = "/gp/gpMediaList"

        fun extractLatestStill(json: String): MediaItem? {
            val root = runCatching { JSONObject(json) }.getOrNull() ?: return null
            val media = root.optJSONArray("media") ?: return null
            data class Ranked(val item: MediaItem, val order: Int)
            val candidates = mutableListOf<Ranked>()
            var order = 0
            for (i in 0 until media.length()) {
                val folderEntry = media.optJSONObject(i) ?: continue
                val folder = folderEntry.optString("d")
                val files = folderEntry.optJSONArray("fs") ?: JSONArray()
                for (j in 0 until files.length()) {
                    val file = files.optJSONObject(j) ?: continue
                    val name = file.optString("n")
                    if (name.isEmpty()) continue
                    val lower = name.lowercase()
                    val still = lower.endsWith(".jpg") || lower.endsWith(".jpeg") || lower.endsWith(".gpr")
                    val ts = numericString(file.opt("cre")).ifEmpty { numericString(file.opt("mod")) }
                    candidates += Ranked(MediaItem(folder, name, ts, still), order)
                    order += 1
                }
            }
            val stills = candidates.filter { it.item.isStill }
            val pool = stills.ifEmpty { candidates }
            return pool.maxWithOrNull(
                compareBy<Ranked> { folderSequence(it.item.folder) }
                    .thenBy { fileSequence(it.item.name) }
                    .thenBy { it.order }
                    .thenBy { it.item.timestamp.toDoubleOrNull() ?: -1.0 }
                    .thenBy { it.item.name },
            )?.item
        }

        private fun numericString(any: Any?): String = when (any) {
            null, JSONObject.NULL -> ""
            is Number -> any.toLong().toString()
            else -> any.toString().trim()
        }

        private fun folderSequence(folder: String): Int =
            folder.takeWhile { it.isDigit() }.toIntOrNull() ?: -1

        private fun fileSequence(name: String): Int {
            val stem = name.substringBeforeLast('.').uppercase()
            val digits = stem.reversed().takeWhile { it.isDigit() }.reversed()
            return digits.toIntOrNull() ?: -1
        }
    }
}
