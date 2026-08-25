package com.smarthome.livingroom_android.intent

import com.smarthome.livingroom_android.brain.BrainEndpoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class IntentSubmitResult(
    val ok: Boolean,
    val intentId: String?,
    val status: String?,
    val message: String,
    val rawBody: String,
    val detail: IntentDetail? = null,
)

data class IntentDetail(
    val intentId: String,
    val status: String?,
    val text: String,
    val source: String,
    val intentOrigin: String? = null,
    val presentation: IntentPresentation?,
    val planSteps: List<PlanStepRow>,
    val error: String?,
    val createdAtMs: Long?,
)

data class IntentHistoryPage(
    val details: List<IntentDetail>,
    val nextBeforeId: Int?,
    val exhausted: Boolean,
)

data class ClockPing(
    val ok: Boolean,
    val serverTimeMs: Long? = null,
    val skewMs: Int? = null,
    val error: String = "",
)

data class ClockSyncSample(
    val localAtMs: Long,
    val serverAtMs: Long? = null,
    val skewMs: Int? = null,
)

data class AssetUploadResult(
    val assetId: String,
    val assetRefJson: String,
)

/**
 * Phone-side Brain client: POST intent, GET intent_detail / history / assets / ping.
 */
class IntentApi(
    private val client: OkHttpClient = defaultClient(),
) {
    suspend fun submit(
        intentUrl: String,
        text: String,
        source: String,
        clientHint: String,
        participantId: String?,
    ): IntentSubmitResult = withContext(Dispatchers.IO) {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) {
            return@withContext IntentSubmitResult(false, null, null, "text is empty", "")
        }
        val src = if (source == "voice") "voice" else "text"
        val payload = JSONObject()
            .put("text", trimmed)
            .put("source", src)
            .put("client_hint", clientHint)
        val pid = participantId?.trim().orEmpty()
        if (pid.isNotEmpty()) {
            payload.put("participant_id", pid)
            payload.put("edge_id", pid)
        }
        val req = Request.Builder()
            .url(intentUrl.trim())
            .post(payload.toString().toRequestBody(JSON_MEDIA))
            .build()
        executeJson(req, "intent") { json, body, code ->
            if (code !in 200..299) {
                return@executeJson IntentSubmitResult(
                    false, null, null, "HTTP $code: ${body.take(200)}", body,
                )
            }
            val detail = parseDetail(json, body)
            val id = detail?.intentId
            IntentSubmitResult(
                ok = !id.isNullOrBlank(),
                intentId = id,
                status = detail?.status,
                message = if (id != null) "intent_id=$id status=${detail.status}" else body.take(200),
                rawBody = body,
                detail = detail,
            )
        }
    }

    suspend fun fetchDetail(intentUrl: String, intentId: String): IntentSubmitResult =
        withContext(Dispatchers.IO) {
            val url = BrainEndpoint.intentDetailUrl(intentUrl, intentId)
            val req = Request.Builder().url(url).get().build()
            executeJson(req, "intent-detail") { json, body, code ->
                if (code !in 200..299) {
                    return@executeJson IntentSubmitResult(
                        false, intentId, null, "detail HTTP $code", body,
                    )
                }
                val detail = parseDetail(json, body, fallbackId = intentId)
                IntentSubmitResult(
                    ok = true,
                    intentId = detail?.intentId ?: intentId,
                    status = detail?.status,
                    message = "detail status=${detail?.status}",
                    rawBody = body,
                    detail = detail,
                )
            }
        }

    suspend fun fetchHistory(
        intentUrl: String,
        participantId: String,
        beforeId: Int?,
        limit: Int = HISTORY_PAGE_LIMIT,
    ): IntentHistoryPage = withContext(Dispatchers.IO) {
        val pid = participantId.trim()
        if (pid.isEmpty()) {
            return@withContext IntentHistoryPage(emptyList(), null, true)
        }
        val pageLimit = limit.coerceIn(1, HISTORY_PAGE_LIMIT)
        val url = BrainEndpoint.intentsListUrl(intentUrl, pid, beforeId, pageLimit)
        val req = Request.Builder().url(url).get().build()
        try {
            client.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    return@withContext IntentHistoryPage(emptyList(), null, false)
                }
                val json = runCatching { JSONObject(body) }.getOrNull()
                    ?: return@withContext IntentHistoryPage(emptyList(), null, false)
                val rows = json.optJSONArray("intents") ?: JSONArray()
                val details = mutableListOf<IntentDetail>()
                for (i in 0 until rows.length()) {
                    val row = rows.optJSONObject(i) ?: continue
                    parseDetail(row, row.toString())?.let { details += it }
                }
                val next = when {
                    json.has("next_before_id") && !json.isNull("next_before_id") ->
                        json.optInt("next_before_id")
                    else -> details.mapNotNull { it.intentId.toIntOrNull() }.minOrNull()
                }
                val exhausted = if (json.has("exhausted")) {
                    json.optBoolean("exhausted")
                } else {
                    details.size < pageLimit
                }
                IntentHistoryPage(
                    details = details,
                    nextBeforeId = if (exhausted) null else next,
                    exhausted = exhausted,
                )
            }
        } catch (_: Throwable) {
            IntentHistoryPage(emptyList(), null, false)
        }
    }

    suspend fun ping(intentOrBaseUrl: String, timeoutSec: Long = 2): ClockPing =
        withContext(Dispatchers.IO) {
            val localAt = System.currentTimeMillis()
            val url = BrainEndpoint.pingUrl(intentOrBaseUrl, localAt)
            val req = Request.Builder().url(url).get().build()
            val pingClient = client.newBuilder()
                .connectTimeout(timeoutSec, TimeUnit.SECONDS)
                .readTimeout(timeoutSec, TimeUnit.SECONDS)
                .callTimeout(timeoutSec + 1, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .build()
            try {
                pingClient.newCall(req).execute().use { resp ->
                    val body = resp.body?.string().orEmpty()
                    if (!resp.isSuccessful) {
                        return@withContext ClockPing(false, error = "对时 HTTP ${resp.code}")
                    }
                    val json = runCatching { JSONObject(body) }.getOrNull()
                        ?: return@withContext ClockPing(false, error = "对时响应无效")
                    if (!json.optBoolean("ok", true)) {
                        return@withContext ClockPing(false, error = "对时响应 ok=false")
                    }
                    val serverMs = jsonLong(json, "server_time_ms")
                        ?: jsonLong(json, "server_time")?.let { it * 1000 }
                        ?: return@withContext ClockPing(false, error = "对时响应缺少 server_time_ms")
                    val skew = if (json.has("skew_ms") && !json.isNull("skew_ms")) {
                        json.optInt("skew_ms")
                    } else {
                        (serverMs - localAt).toInt()
                    }
                    ClockPing(ok = true, serverTimeMs = serverMs, skewMs = skew)
                }
            } catch (t: Throwable) {
                ClockPing(false, error = t.message ?: t.javaClass.simpleName)
            }
        }

    suspend fun fetchAssetBytes(
        intentUrl: String,
        assetId: String,
        intentId: String,
        representation: String = "preview",
    ): ByteArray? = withContext(Dispatchers.IO) {
        val aid = assetId.trim()
        val iid = intentId.trim()
        if (aid.isEmpty() || iid.isEmpty()) return@withContext null
        val reps = representationCandidates(representation)
        repeat(4) { attempt ->
            for (rep in reps) {
                val url = BrainEndpoint.assetContentUrl(intentUrl, aid, iid, rep)
                val req = Request.Builder().url(url).get().build()
                val bytes = runCatching {
                    client.newCall(req).execute().use { resp ->
                        if (!resp.isSuccessful) null else resp.body?.bytes()
                    }
                }.getOrNull()
                if (bytes != null && bytes.size > 32 && looksLikeImage(bytes)) {
                    return@withContext bytes
                }
            }
            if (attempt < 3) delay(1_500)
        }
        null
    }

    suspend fun uploadAsset(
        intentUrl: String,
        jpeg: ByteArray,
        uploadIntent: String,
        participantId: String?,
        intentId: String? = null,
        fileName: String = "upload_${System.currentTimeMillis()}.jpg",
        failVerb: String = "上传",
        mimeType: String = "image/jpeg",
        assetType: String = "image",
        httpClient: OkHttpClient = client,
    ): AssetUploadResult = withContext(Dispatchers.IO) {
        val url = BrainEndpoint.apiUrl(intentUrl, "assets/upload")
        val safeName = sanitizeUploadName(fileName, "upload.bin")
        val mime = mimeType.trim().ifEmpty { "application/octet-stream" }
        val kind = assetType.trim().ifEmpty { "file" }
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("upload_intent", uploadIntent)
            .addFormDataPart("producer", uploadIntent)
            .addFormDataPart("type", kind)
            .addFormDataPart("mime_type", mime)
            .apply {
                val pid = participantId?.trim().orEmpty()
                if (pid.isNotEmpty()) {
                    addFormDataPart("edge_id", pid)
                    addFormDataPart("participant_id", pid)
                }
                val iid = intentId?.trim().orEmpty()
                if (iid.isNotEmpty()) addFormDataPart("intent_id", iid)
            }
            .addFormDataPart(
                "file",
                safeName,
                jpeg.toRequestBody(mime.toMediaType()),
            )
            .build()
        val req = Request.Builder().url(url).post(body).build()
        httpClient.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                error("${failVerb}失败：上传 HTTP ${resp.code}：${text.take(200)}")
            }
            val json = runCatching { JSONObject(text) }.getOrNull()
                ?: error("${failVerb}失败：上传未返回 JSON")
            val aid = json.optString("asset_id").ifBlank {
                json.optJSONObject("asset")?.optString("asset_id").orEmpty()
            }.ifBlank {
                json.optJSONObject("asset_ref")?.optString("asset_id").orEmpty()
            }.trim()
            if (aid.isEmpty()) error("${failVerb}失败：上传未返回 asset_id。")
            val ref = json.optJSONObject("asset_ref")?.toString()
                ?: JSONObject()
                    .put("asset_id", aid)
                    .put("type", kind)
                    .put("mime_type", mime)
                    .toString()
            AssetUploadResult(assetId = aid, assetRefJson = ref)
        }
    }

    suspend fun registerLocalAsset(
        intentUrl: String,
        localPath: String,
        participantId: String?,
        intentId: String?,
        producer: String,
        failVerb: String = "拍照",
        httpClient: OkHttpClient = client,
    ): AssetUploadResult = withContext(Dispatchers.IO) {
        val url = BrainEndpoint.apiUrl(intentUrl, "assets")
        val pid = participantId?.trim().orEmpty()
        val storage = JSONObject()
            .put("backend", "local")
            .put("key", localPath)
        if (pid.isNotEmpty()) storage.put("edge_id", pid)
        val payload = JSONObject()
            .put("type", "image")
            .put("mime_type", "image/jpeg")
            .put("producer", producer)
            .put("storage", storage)
        if (pid.isNotEmpty()) {
            payload.put("edge_id", pid)
            payload.put("participant_id", pid)
        }
        val iid = intentId?.trim().orEmpty()
        if (iid.isNotEmpty()) {
            payload.put("intent_id", iid)
            payload.put("execution_id", iid)
        }
        val req = Request.Builder()
            .url(url)
            .post(payload.toString().toRequestBody(JSON_MEDIA))
            .build()
        httpClient.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                error("${failVerb}失败：登记 asset HTTP ${resp.code}：${text.take(200)}")
            }
            val json = runCatching { JSONObject(text) }.getOrNull()
                ?: error("${failVerb}失败：登记 asset 未返回 JSON")
            val aid = json.optString("asset_id").ifBlank {
                json.optJSONObject("asset")?.optString("asset_id").orEmpty()
            }.ifBlank {
                json.optJSONObject("asset_ref")?.optString("asset_id").orEmpty()
            }.trim()
            if (aid.isEmpty()) error("${failVerb}失败：登记 asset 未返回 asset_id。")
            val ref = json.optJSONObject("asset_ref")?.toString()
                ?: JSONObject()
                    .put("asset_id", aid)
                    .put("type", "image")
                    .put("mime_type", "image/jpeg")
                    .toString()
            AssetUploadResult(assetId = aid, assetRefJson = ref)
        }
    }

    suspend fun fetchAssetLocalPath(
        intentUrl: String,
        assetId: String,
        intentId: String,
        participantId: String?,
        httpClient: OkHttpClient = client,
    ): String? = withContext(Dispatchers.IO) {
        val aid = assetId.trim()
        if (aid.isEmpty()) return@withContext null
        val base = BrainEndpoint.apiUrl(intentUrl, "assets/$aid")
        val qs = buildString {
            append("intent_id=").append(java.net.URLEncoder.encode(intentId, "UTF-8"))
            val pid = participantId?.trim().orEmpty()
            if (pid.isNotEmpty()) {
                append("&edge_id=").append(java.net.URLEncoder.encode(pid, "UTF-8"))
            }
        }
        val req = Request.Builder().url("$base?$qs").get().build()
        httpClient.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) return@withContext null
            val json = runCatching { JSONObject(resp.body?.string().orEmpty()) }.getOrNull()
                ?: return@withContext null
            val asset = json.optJSONObject("asset") ?: json
            val storage = asset.optJSONObject("storage") ?: return@withContext null
            if (storage.optString("backend").trim().lowercase() != "local") return@withContext null
            storage.optString("key").trim().takeIf { it.isNotEmpty() }
        }
    }

    suspend fun submitFeedback(
        intentUrl: String,
        intentId: String,
        participantId: String,
        understanding: String,
        responseSpeed: String,
    ): Boolean = withContext(Dispatchers.IO) {
        val url = BrainEndpoint.apiUrl(intentUrl, "intent_feedback")
        val payload = JSONObject()
            .put("intent_id", intentId.toIntOrNull() ?: intentId)
            .put("participant_id", participantId)
            .put("understanding", understanding)
            .put("response_speed", responseSpeed)
        val req = Request.Builder()
            .url(url)
            .post(payload.toString().toRequestBody(JSON_MEDIA))
            .build()
        try {
            client.newCall(req).execute().use { it.isSuccessful }
        } catch (_: Throwable) {
            false
        }
    }

    private inline fun executeJson(
        req: Request,
        @Suppress("UNUSED_PARAMETER") label: String,
        parse: (JSONObject, String, Int) -> IntentSubmitResult,
    ): IntentSubmitResult {
        return try {
            client.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                val json = runCatching { JSONObject(body) }.getOrNull() ?: JSONObject()
                parse(json, body, resp.code)
            }
        } catch (t: Throwable) {
            IntentSubmitResult(false, null, null, t.message ?: t.javaClass.simpleName, "")
        }
    }

    companion object {
        const val HISTORY_PAGE_LIMIT = 5
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        fun sanitizeUploadName(raw: String, fallback: String): String {
            val trimmed = raw.trim().ifEmpty { fallback }
            val cleaned = trimmed.replace(Regex("[\\\\/:*?\"<>|\\s]+"), "_")
            return cleaned.ifEmpty { fallback }
        }

        fun guessAssetType(mime: String, filename: String): String {
            val m = mime.lowercase()
            val ext = filename.substringAfterLast('.', "").lowercase()
            return when {
                m.startsWith("image/") || ext in setOf("jpg", "jpeg", "png", "gif", "webp", "heic") -> "image"
                m.startsWith("audio/") || ext in setOf("m4a", "aac", "mp3", "wav", "ogg") -> "audio"
                m.startsWith("video/") || ext in setOf("mp4", "mov", "m4v") -> "video"
                else -> "file"
            }
        }

        fun parseDetail(
            json: JSONObject,
            raw: String,
            fallbackId: String? = null,
        ): IntentDetail? {
            val id = json.opt("intent_id")?.toString()?.takeIf { it.isNotBlank() && it != "null" }
                ?: json.opt("id")?.toString()?.takeIf { it.isNotBlank() && it != "null" }
                ?: fallbackId
            if (id.isNullOrBlank()) return null
            val status = json.optString("intent_status").takeIf { it.isNotBlank() }
                ?: json.optString("status").takeIf { it.isNotBlank() }
            val text = json.optString("text", json.optString("utterance", ""))
            val sourceRaw = json.optString("source", "text").trim().lowercase()
            val source = if (sourceRaw == "voice") "voice" else "text"
            val originRaw = json.optString("intent_origin", "").trim().lowercase()
            val intentOrigin = if (originRaw == "lan" || originRaw == "cloud") originRaw else null
            val error = json.optString("error").takeIf { it.isNotBlank() }
                ?: json.optString("msg").takeIf { it.isNotBlank() }
                ?: json.optString("message").takeIf { it.isNotBlank() && status == "failed" }
            val created = jsonLong(json, "created_at")
                ?: jsonLong(json, "intent_base_time")
                ?: jsonLong(json, "base_time")
            val createdMs = created?.let { if (it < 1_000_000_000_000L) it * 1000 else it }
            val steps = mutableListOf<PlanStepRow>()
            val plan = json.optJSONArray("execution_plan")
            if (plan != null) {
                for (i in 0 until plan.length()) {
                    val step = plan.optJSONObject(i) ?: continue
                    val st = when (val rawSt = step.opt("status") ?: step.opt("step_status")) {
                        is Number -> rawSt.toInt()
                        is String -> rawSt.toIntOrNull() ?: 0
                        else -> 0
                    }
                    val statusLabel = when (st) {
                        1 -> "running"
                        2 -> "succeeded"
                        3 -> "failed"
                        else -> step.optString("status").ifBlank { "queued" }
                    }
                    steps += PlanStepRow(
                        step = step.optInt("step", i + 1),
                        capability = step.optString("capability", ""),
                        status = statusLabel,
                        detail = step.optString("assigned_edge_id", "").let {
                            if (it.isNotBlank()) "@$it" else ""
                        },
                    )
                }
            }
            return IntentDetail(
                intentId = id,
                status = status,
                text = text,
                source = source,
                intentOrigin = intentOrigin,
                presentation = IntentPresentation.parse(json.opt("presentation")),
                planSteps = steps,
                error = error,
                createdAtMs = createdMs,
            )
        }

        private fun jsonLong(json: JSONObject, key: String): Long? {
            if (!json.has(key) || json.isNull(key)) return null
            val raw = json.opt(key) ?: return null
            return when (raw) {
                is Number -> raw.toLong()
                is String -> raw.toLongOrNull()
                else -> null
            }
        }

        private fun representationCandidates(preferred: String): List<String> {
            val p = preferred.trim().lowercase()
            return when (p) {
                "", "preview", "thumbnail" -> listOf("preview", "original")
                "original" -> listOf("original", "preview")
                else -> listOf(p, "preview", "original")
            }
        }

        private fun looksLikeImage(bytes: ByteArray): Boolean {
            if (bytes.size < 8) return false
            // JPEG
            if (bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte()) return true
            // PNG
            if (bytes[0] == 0x89.toByte() && bytes[1] == 0x50.toByte()) return true
            // GIF / WEBP
            if (bytes[0] == 'G'.code.toByte() && bytes[1] == 'I'.code.toByte()) return true
            if (bytes[0] == 'R'.code.toByte() && bytes[1] == 'I'.code.toByte()) return true
            return false
        }

        private fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(60, TimeUnit.SECONDS)
                .writeTimeout(60, TimeUnit.SECONDS)
                .build()
    }
}

/** Back-compat wrapper used by leftover debug paths. */
class IntentSubmitClient(
    private val intentURL: String,
    private val api: IntentApi = IntentApi(),
) {
    suspend fun submit(text: String, source: String, edgeId: String): IntentSubmitResult =
        api.submit(
            intentUrl = intentURL,
            text = text,
            source = source,
            clientHint = edgeId,
            participantId = edgeId,
        )

    suspend fun fetchDetail(intentId: String): IntentSubmitResult =
        api.fetchDetail(intentURL, intentId)

    companion object {
        @Volatile
        var lastPlanSteps: List<PlanStepRow> = emptyList()
    }
}
