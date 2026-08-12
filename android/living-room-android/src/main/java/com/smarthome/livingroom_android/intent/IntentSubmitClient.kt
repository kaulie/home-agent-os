package com.smarthome.livingroom_android.intent

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

data class IntentSubmitResult(
    val ok: Boolean,
    val intentId: String?,
    val status: String?,
    val message: String,
    val rawBody: String,
)

/**
 * POST `/api/v1/intent` — same contract as iOS IntentController.
 * Body: `{ "text", "source": "text"|"voice", "edge_id" }`
 */
class IntentSubmitClient(
    private val intentURL: String,
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build(),
) {
    suspend fun submit(
        text: String,
        source: String,
        edgeId: String,
    ): IntentSubmitResult = withContext(Dispatchers.IO) {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) {
            return@withContext IntentSubmitResult(false, null, null, "text is empty", "")
        }
        val src = if (source == "voice") "voice" else "text"
        val payload = JSONObject()
            .put("text", trimmed)
            .put("source", src)
            .put("edge_id", edgeId)
            .toString()
        val req = Request.Builder()
            .url(intentURL.trim())
            .post(payload.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()
        try {
            client.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    return@withContext IntentSubmitResult(
                        false,
                        null,
                        null,
                        "HTTP ${resp.code}: ${body.take(200)}",
                        body,
                    )
                }
                val json = runCatching { JSONObject(body) }.getOrNull()
                val id = json?.opt("intent_id")?.toString()?.takeIf { it.isNotBlank() && it != "null" }
                    ?: json?.opt("id")?.toString()?.takeIf { it.isNotBlank() && it != "null" }
                val status = json?.optString("intent_status")?.takeIf { it.isNotBlank() }
                    ?: json?.optString("status")?.takeIf { it.isNotBlank() }
                IntentSubmitResult(
                    ok = true,
                    intentId = id,
                    status = status,
                    message = if (id != null) "intent_id=$id status=$status" else body.take(200),
                    rawBody = body,
                )
            }
        } catch (t: Throwable) {
            IntentSubmitResult(false, null, null, t.message ?: t.javaClass.simpleName, "")
        }
    }

    suspend fun fetchDetail(intentId: String): IntentSubmitResult = withContext(Dispatchers.IO) {
        val base = intentURL.trim().trimEnd('/')
        val detailUrl = if (base.endsWith("/intent")) {
            base.removeSuffix("/intent") + "/intent_detail?intent_id=$intentId"
        } else {
            "$base/../intent_detail?intent_id=$intentId"
        }
        val req = Request.Builder().url(detailUrl).get().build()
        try {
            client.newCall(req).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    return@withContext IntentSubmitResult(
                        false,
                        intentId,
                        null,
                        "detail HTTP ${resp.code}",
                        body,
                    )
                }
                val json = runCatching { JSONObject(body) }.getOrNull()
                val status = json?.optString("intent_status")?.takeIf { it.isNotBlank() }
                    ?: json?.optString("status")?.takeIf { it.isNotBlank() }
                val steps = mutableListOf<PlanStepRow>()
                val plan = json?.optJSONArray("execution_plan")
                if (plan != null) {
                    for (i in 0 until plan.length()) {
                        val step = plan.optJSONObject(i) ?: continue
                        steps += PlanStepRow(
                            step = step.optInt("step", i + 1),
                            capability = step.optString("capability", ""),
                            status = "planned",
                            detail = "",
                        )
                    }
                }
                IntentSubmitResult(
                    ok = true,
                    intentId = intentId,
                    status = status,
                    message = "detail status=$status steps=${steps.size}",
                    rawBody = body,
                ).also {
                    // attach steps via companion parse helper used by UI
                    lastPlanSteps = steps
                }
            }
        } catch (t: Throwable) {
            IntentSubmitResult(false, intentId, null, t.message ?: "detail failed", "")
        }
    }

    companion object {
        @Volatile
        var lastPlanSteps: List<PlanStepRow> = emptyList()
    }
}
