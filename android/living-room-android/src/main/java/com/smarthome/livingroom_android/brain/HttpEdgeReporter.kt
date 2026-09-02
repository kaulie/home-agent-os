package com.smarthome.livingroom_android.brain

import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterResponse
import com.smarthome.livingroom_android.command.BrainTimeSync
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** HTTP Edge → Brain: register (get edgeId) then heartbeat with that edgeId. */
class HttpEdgeReporter(
    baseURL: String,
    private val enabled: Boolean = true,
    private val client: OkHttpClient = defaultClient(),
) {
    @Volatile
    var baseURL: String = baseURL.trimEnd('/')
        set(value) {
            field = value.trim().trimEnd('/')
        }

    private val root: String get() = baseURL

    val defaultRegisterURL: String get() = "$root/api/v1/edge-register"
    val defaultHeartbeatURL: String get() = "$root/api/v1/edge-heartbeat"

    private val heartbeatClient: OkHttpClient = client.newBuilder()
        .connectTimeout(HEARTBEAT_TIMEOUT_SEC, TimeUnit.SECONDS)
        .readTimeout(HEARTBEAT_TIMEOUT_SEC, TimeUnit.SECONDS)
        .writeTimeout(HEARTBEAT_TIMEOUT_SEC, TimeUnit.SECONDS)
        .callTimeout(HEARTBEAT_TIMEOUT_SEC, TimeUnit.SECONDS)
        .retryOnConnectionFailure(false)
        .build()

    suspend fun register(
        request: EdgeRegisterRequest,
        urlOverride: String? = null,
        timeoutSec: Long = 6,
    ): EdgeRegisterResponse = withContext(Dispatchers.IO) {
        if (!enabled) {
            val id = request.clientHint?.trim().orEmpty().ifEmpty { "local-edge" }
            return@withContext EdgeRegisterResponse(
                ok = true,
                status = "approved",
                edgeId = id,
                message = "remote reporter disabled",
            )
        }
        val url = urlOverride?.trim()?.takeIf { it.isNotEmpty() } ?: defaultRegisterURL
        val body = EdgeJson.encodeRegisterRequest(request)
            .toRequestBody(JSON_MEDIA)
        val httpRequest = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json; charset=utf-8")
            .build()
        clientForTimeout(timeoutSec).newCall(httpRequest).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw HttpEdgeException(
                    response.code,
                    "edge-register HTTP ${response.code}: ${text.take(200)}",
                )
            }
            EdgeJson.parseRegisterResponse(text)
        }
    }

    suspend fun heartbeat(
        info: EdgeNodeInfo,
        urlOverride: String? = null,
    ): String = withContext(Dispatchers.IO) {
        if (!enabled) return@withContext "(remote disabled)"
        if (info.edgeId.isBlank()) {
            throw HttpEdgeException(401, "heartbeat requires edgeId; register first")
        }
        val url = urlOverride?.trim()?.takeIf { it.isNotEmpty() } ?: defaultHeartbeatURL
        val body = EdgeJson.encodeNodeInfo(info).toRequestBody(JSON_MEDIA)
        val httpRequest = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json; charset=utf-8")
            .build()
        heartbeatClient.newCall(httpRequest).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw HttpEdgeException(
                    response.code,
                    "edge-heartbeat HTTP ${response.code}: ${text.take(200)}",
                )
            }
            applyBrainTimeFromHeartbeat(text)
            text
        }
    }

    private fun clientForTimeout(timeoutSec: Long): OkHttpClient {
        val sec = timeoutSec.coerceAtLeast(1)
        return client.newBuilder()
            .connectTimeout(sec, TimeUnit.SECONDS)
            .readTimeout(sec, TimeUnit.SECONDS)
            .writeTimeout(sec, TimeUnit.SECONDS)
            .callTimeout(sec, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build()
    }

    companion object {
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
        private const val HEARTBEAT_TIMEOUT_SEC = 5L

        private fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(8, TimeUnit.SECONDS)
                .writeTimeout(8, TimeUnit.SECONDS)
                .callTimeout(8, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .build()

        private fun applyBrainTimeFromHeartbeat(body: String) {
            try {
                val o = JSONObject(body)
                var brainTime: Long? = null
                if (o.has("brain_time_ms") && !o.isNull("brain_time_ms")) {
                    brainTime = o.optLong("brain_time_ms")
                }
                if (brainTime == null || brainTime <= 0L) {
                    val edge = o.optJSONObject("edge")
                    if (edge != null && edge.has("brain_time_ms") && !edge.isNull("brain_time_ms")) {
                        brainTime = edge.optLong("brain_time_ms")
                    }
                }
                BrainTimeSync.applyHeartbeat(brainTime)
            } catch (_: Exception) {
                // Ignore malformed heartbeat payloads.
            }
        }
    }
}
