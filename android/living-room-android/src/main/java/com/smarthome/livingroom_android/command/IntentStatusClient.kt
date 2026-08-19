package com.smarthome.livingroom_android.command

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Intent / step status reporter — production Brain contract only.
 *
 * Intent status: POST `/api/v1/intent/<id>/status`
 *   `{ intent_id, intent_status, edge_node_id, ts?, message?, outputs?, ctx_param? }`
 *
 * Step status: POST `/api/v1/intent/<id>/step/<n>/status`
 *   `{ step_status, edge_node_id, ts [, outputs] [, msg] }`
 *
 * Requeue: POST `/api/v1/devices/living-room/intents`
 *   `{ id, intent_status, execution_plan, skip_routing, scheduler_node?, ctx_param? }`
 */
class IntentStatusClient(
    private val intentBaseURL: String,
    private val client: OkHttpClient = defaultClient(),
) {
    suspend fun reportStatus(
        intentId: String,
        status: String,
        edgeNodeId: String? = null,
        message: String? = null,
        outputs: Map<String, String>? = null,
        ctxParam: Map<String, String>? = null,
    ): Boolean = withContext(Dispatchers.IO) {
        val trimmedId = intentId.trim()
        if (trimmedId.isEmpty()) return@withContext false
        val wireStatus = status.trim()
        if (wireStatus.isEmpty()) return@withContext false

        val payload = JSONObject().apply {
            put("intent_status", wireStatus)
            put("status", wireStatus)
            trimmedId.toIntOrNull()?.let { put("intent_id", it) }
                ?: put("intent_id", trimmedId)
            if (!edgeNodeId.isNullOrBlank()) {
                put("edge_node_id", edgeNodeId.trim())
            }
            if (!message.isNullOrBlank()) {
                put("message", message)
            }
            putStringMap("outputs", outputs)
            putStringMap("ctx_param", ctxParam)
        }
        val url = intentStatusUrl(trimmedId) ?: return@withContext false
        postJson(url, payload, "intent-status")
    }

    suspend fun reportStepStatus(
        intentId: String,
        stepId: Int,
        stepStatus: Int,
        edgeNodeId: String,
        outputs: Map<String, String>? = null,
        tsMs: Long = System.currentTimeMillis(),
        msg: String? = null,
    ): Boolean = withContext(Dispatchers.IO) {
        val trimmedId = intentId.trim()
        val eid = edgeNodeId.trim()
        if (trimmedId.isEmpty() || stepId <= 0 || eid.isEmpty()) return@withContext false
        val url = stepStatusUrl(trimmedId, stepId) ?: return@withContext false
        val payload = JSONObject().apply {
            put("step_status", stepStatus)
            put("edge_node_id", eid)
            put("ts", tsMs)
            // Skill outputs only — Brain registers into ctx_param via output_constrict.
            putStringMap("outputs", outputs)
            val note = msg?.trim().orEmpty()
            if (note.isNotEmpty()) {
                put("msg", if (note.length <= 1000) note else note.take(999) + "…")
            }
        }
        postJson(url, payload, "step-status")
    }

    suspend fun requeueIntentForPull(
        intentId: String,
        status: String,
        executionPlan: JSONArray,
        ctxParam: Map<String, String>? = null,
        schedulerNode: String? = null,
    ): Boolean = withContext(Dispatchers.IO) {
        val trimmedId = intentId.trim()
        if (trimmedId.isEmpty() || executionPlan.length() == 0) return@withContext false
        val url = livingRoomIntentsUrl() ?: return@withContext false
        val payload = JSONObject().apply {
            trimmedId.toIntOrNull()?.let { put("id", it) } ?: put("id", trimmedId)
            put("status", status)
            put("intent_status", status)
            put("execution_plan", executionPlan)
            put("skip_routing", true)
            if (!schedulerNode.isNullOrBlank()) put("scheduler_node", schedulerNode.trim())
            putStringMap("ctx_param", ctxParam)
        }
        postJson(url, payload, "intent-requeue")
    }

    suspend fun fetchIntentDetail(intentId: String): JSONObject? = withContext(Dispatchers.IO) {
        val trimmedId = intentId.trim()
        if (trimmedId.isEmpty()) return@withContext null
        val url = intentDetailUrl(trimmedId) ?: return@withContext null
        val request = Request.Builder().url(url).get().build()
        try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext null
                val text = response.body?.string().orEmpty()
                JSONObject(text)
            }
        } catch (t: Throwable) {
            Log.w(TAG, "intent_detail failed: ${t.message}")
            null
        }
    }

    private fun JSONObject.putStringMap(key: String, values: Map<String, String>?) {
        if (values.isNullOrEmpty()) return
        val bag = JSONObject()
        for ((k, v) in values) {
            if (k.isNotBlank() && v.isNotBlank()) bag.put(k, v)
        }
        if (bag.length() > 0) put(key, bag)
    }

    private fun postJson(url: String, payload: JSONObject, label: String): Boolean {
        val body = payload.toString().toRequestBody(JSON_MEDIA)
        val request = Request.Builder()
            .url(url)
            .post(body)
            .header("Content-Type", "application/json; charset=utf-8")
            .build()
        return try {
            client.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    Log.i(TAG, "$label ok url=$url")
                    true
                } else {
                    Log.w(TAG, "$label HTTP ${response.code} url=$url body=${response.body?.string()?.take(160)}")
                    false
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "$label failed url=$url: ${t.message}")
            false
        }
    }

    private fun intentStatusUrl(intentId: String): String? {
        val base = intentBaseURL.trim().trimEnd('/')
        if (base.isEmpty()) return null
        return "$base/$intentId/status"
    }

    private fun stepStatusUrl(intentId: String, stepId: Int): String? {
        val base = intentBaseURL.trim()
        if (base.isEmpty()) return null
        return when {
            base.endsWith("/intent") ->
                base.dropLast("intent".length) + "intent/$intentId/step/$stepId/status"
            base.contains("/api/v1/") -> {
                val idx = base.indexOf("/api/v1/")
                base.substring(0, idx + "/api/v1/".length) + "intent/$intentId/step/$stepId/status"
            }
            else -> "$base/intent/$intentId/step/$stepId/status"
        }
    }

    private fun intentDetailUrl(intentId: String): String? {
        val base = intentBaseURL.trim()
        if (base.isEmpty()) return null
        val path = when {
            base.endsWith("/intent") -> base.dropLast("intent".length) + "intent_detail"
            base.contains("/api/v1/") -> {
                val idx = base.indexOf("/api/v1/")
                base.substring(0, idx + "/api/v1/".length) + "intent_detail"
            }
            else -> "$base/intent_detail"
        }
        return "$path?intent_id=$intentId"
    }

    private fun livingRoomIntentsUrl(): String? {
        val base = intentBaseURL.trim()
        if (base.isEmpty()) return null
        return when {
            base.contains("/api/v1/") -> {
                val idx = base.indexOf("/api/v1/")
                base.substring(0, idx + "/api/v1/".length) + "devices/living-room/intents"
            }
            else -> "$base/devices/living-room/intents"
        }
    }

    companion object {
        private const val TAG = "IntentStatusClient"
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        /** Production intent_status wire values. */
        const val INTENT_SCHEDULED = "intent_scheduled"
        const val INTENT_DISPATCHED = "intent_dispatched"
        const val RUNNING = "running"
        const val SUCCEEDED = "succeeded"
        const val FAILED = "failed"

        const val STEP_WAITING = 0
        const val STEP_RUNNING = 1
        const val STEP_SUCCEEDED = 2
        const val STEP_FAILED = 3

        fun intentIdFromParams(params: Map<String, Any?>): String? {
            val raw = params["intent_id"] ?: return null
            val s = when (raw) {
                is String -> raw.trim()
                is Number -> raw.toString()
                else -> raw.toString().trim()
            }
            return s.takeIf { it.isNotEmpty() }
        }

        private fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .build()
    }
}
