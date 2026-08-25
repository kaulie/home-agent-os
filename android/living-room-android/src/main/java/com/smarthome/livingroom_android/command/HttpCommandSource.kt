package com.smarthome.livingroom_android.command

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * GET `/api/v1/devices/living-room/intents?edge_id=&peek=1`
 *
 * Keep where any step `assigned_edge_id` matches this node.
 * Drop terminal (`succeeded` / `failed`).
 */
class HttpCommandSource(
    private var pullURL: String,
    /** Optional pin; null/empty = no status filter (required for multi-tick running intents). */
    var intentStatusFilter: String? = null,
    var localEdgeId: String? = null,
    private val client: OkHttpClient = defaultClient(),
) {
    fun setPullURL(url: String) {
        pullURL = url.trim()
    }

    suspend fun fetch(consume: Boolean = false): List<Command> =
        fetchSnapshot(consume).commands

    suspend fun fetchIntents(consume: Boolean = false): List<JSONObject> =
        fetchSnapshot(consume).intents

    suspend fun fetchSnapshot(consume: Boolean = false): IntentsPullSnapshot =
        withContext(Dispatchers.IO) {
            val edgeId = localEdgeId?.trim().orEmpty()
            if (edgeId.isEmpty()) {
                return@withContext IntentsPullSnapshot(
                    atMs = System.currentTimeMillis(),
                    requestUrl = "",
                    httpCode = null,
                    rawBody = "",
                    commands = emptyList(),
                    intents = emptyList(),
                    error = "missing local edge_id (register first)",
                )
            }
            val built = buildRequestUrl(consume, edgeId)
            if (built == null) {
                return@withContext IntentsPullSnapshot(
                    atMs = System.currentTimeMillis(),
                    requestUrl = "",
                    httpCode = null,
                    rawBody = "",
                    commands = emptyList(),
                    intents = emptyList(),
                    error = "pull URL empty",
                )
            }
            val request = Request.Builder().url(built).get().build()
            try {
                client.newCall(request).execute().use { response ->
                    val text = response.body?.string().orEmpty()
                    if (!response.isSuccessful) {
                        return@withContext IntentsPullSnapshot(
                            atMs = System.currentTimeMillis(),
                            requestUrl = built,
                            httpCode = response.code,
                            rawBody = text,
                            commands = emptyList(),
                            intents = emptyList(),
                            error = "HTTP ${response.code}: ${text.take(200)}",
                        )
                    }
                    val intents = parseRelevantIntents(text, edgeId)
                    val commands = intents.flatMapIndexed { index, intent ->
                        makeLocalStepCommands(intent, index, edgeId)
                    }
                    IntentsPullSnapshot(
                        atMs = System.currentTimeMillis(),
                        requestUrl = built,
                        httpCode = response.code,
                        rawBody = text,
                        commands = commands,
                        intents = intents,
                        error = null,
                    )
                }
            } catch (t: Throwable) {
                IntentsPullSnapshot(
                    atMs = System.currentTimeMillis(),
                    requestUrl = built,
                    httpCode = null,
                    rawBody = "",
                    commands = emptyList(),
                    intents = emptyList(),
                    error = t.message ?: t.javaClass.simpleName,
                )
            }
        }

    private fun buildRequestUrl(consume: Boolean, edgeId: String): String? {
        val trimmed = pullURL.trim()
        if (trimmed.isEmpty()) return null
        val httpUrl = trimmed.toHttpUrlOrNull() ?: return trimmed
        val builder = httpUrl.newBuilder()
        for (name in httpUrl.queryParameterNames.toList()) {
            if (name == "peek" || name == "edge_id" || name == "intent_status" || name == "status") {
                builder.removeAllQueryParameters(name)
            }
        }
        builder.setQueryParameter("edge_id", edgeId)
        if (!consume) {
            builder.setQueryParameter("peek", "1")
        }
        val filter = intentStatusFilter?.trim().orEmpty()
        if (filter.isNotEmpty()) {
            builder.setQueryParameter("intent_status", filter)
        }
        return builder.build().toString()
    }

    companion object {
        fun parseCommandsJson(text: String, localEdgeId: String? = null): List<Command> {
            val selfId = localEdgeId?.trim().orEmpty()
            if (selfId.isEmpty()) return emptyList()
            return parseRelevantIntents(text, selfId).flatMapIndexed { index, intent ->
                makeLocalStepCommands(intent, index, selfId)
            }
        }

        fun parseRelevantIntents(text: String, localEdgeId: String): List<JSONObject> {
            val trimmed = text.trim()
            if (trimmed.isEmpty()) return emptyList()
            val selfId = localEdgeId.trim()
            if (selfId.isEmpty()) return emptyList()

            val list: List<JSONObject> = runCatching {
                val root = JSONObject(trimmed)
                when {
                    root.has("intents") -> jsonObjectList(root.getJSONArray("intents"))
                    root.has("execution_plan") || root.has("id") -> listOf(root)
                    else -> emptyList()
                }
            }.getOrElse {
                runCatching { jsonObjectList(JSONArray(trimmed)) }.getOrElse { emptyList() }
            }

            return list.filter { it.length() > 0 && isRelevant(it, selfId) }
        }

        /** Any step assignee, or a real pending_delivery hook. Terminals are never work. */
        fun isRelevant(intent: JSONObject, localEdgeId: String): Boolean {
            val selfId = localEdgeId.trim()
            if (selfId.isEmpty()) return false
            val st = intentWireStatus(intent)
            if (st == "succeeded" || st == "failed") {
                val pending = intent.optJSONObject("pending_delivery")
                val pendingEdge = stringValue(pending?.opt("edge_id"))?.trim().orEmpty()
                return st == "succeeded" && pendingEdge == selfId
            }
            return edgeHasAssignedStep(intent, selfId)
        }

        fun edgeHasAssignedStep(intent: JSONObject, localEdgeId: String): Boolean {
            val selfId = localEdgeId.trim()
            if (selfId.isEmpty()) return false
            val plan = intent.optJSONArray("execution_plan") ?: JSONArray()
            for (i in 0 until plan.length()) {
                val step = plan.optJSONObject(i) ?: continue
                val assigned = stringValue(step.opt("assigned_edge_id"))?.trim().orEmpty()
                if (assigned == selfId) return true
            }
            return false
        }

        fun makeLocalStepCommands(
            intent: JSONObject,
            index: Int,
            localEdgeId: String,
        ): List<Command> {
            val selfId = localEdgeId.trim()
            val plan = intent.optJSONArray("execution_plan") ?: JSONArray()
            val local = mutableListOf<JSONObject>()
            for (i in 0 until plan.length()) {
                val step = plan.optJSONObject(i) ?: continue
                val assigned = stringValue(step.opt("assigned_edge_id"))?.trim().orEmpty()
                if (assigned == selfId) local += step
            }
            if (local.isEmpty()) return emptyList()
            return local.map { makeCommand(intent, it, selfId, plan.length()) }
        }

        fun makeCommand(
            intent: JSONObject,
            step: JSONObject,
            localEdgeId: String,
            planCount: Int? = null,
        ): Command {
            val intentId = stringValue(intent.opt("id"))
                ?: stringValue(intent.opt("intent_id"))
                ?: "intent"
            val status = intentWireStatus(intent)
            val plan = intent.optJSONArray("execution_plan") ?: JSONArray()
            val total = planCount ?: plan.length()
            val stepNum = stringValue(step.opt("step")) ?: "1"
            val capability = stringValue(step.opt("capability"))?.trim().orEmpty()
            val mapped = splitCapability(capability)
            val assigned = stringValue(step.opt("assigned_edge_id"))?.trim()
                ?.takeIf { it.isNotEmpty() }
                ?: localEdgeId
            val params = linkedMapOf<String, Any?>(
                "intent_id" to intentId,
                "capability" to capability,
                "step" to stepNum,
                "plan_step_count" to "$total",
                "assigned_edge_id" to assigned,
                "step_status_api" to "1",
            )
            if (status.isNotEmpty()) params["intent_status"] = status
            val skipKeys = setOf(
                "capability", "step", "reason", "status", "step_status",
                "input_constrict", "output_constrict",
                "assigned_edge_id", "outputs",
                "execution_timing", "delay_sec",
            )
            val keys = step.keys()
            while (keys.hasNext()) {
                val k = keys.next()
                if (k in skipKeys) continue
                params[k] = coerceParamValue(step.opt(k))
            }
            mergeInputConstrict(step, params)
            val raw = jsonToMap(intent).toMutableMap()
            raw["capability"] = capability
            raw["step"] = step.opt("step") ?: stepNum
            raw["assigned_edge_id"] = assigned
            return Command(
                commandId = if (total > 1) "$intentId-$stepNum" else intentId,
                device = mapped.first,
                action = mapped.second,
                params = params,
                schedule = ScheduleSpec.Instant,
                source = CommandSource.SERVER,
                raw = raw,
            )
        }

        fun intentWireStatus(intent: JSONObject): String =
            (stringValue(intent.opt("intent_status"))
                ?: stringValue(intent.opt("status"))
                ?: "").trim().lowercase()

        private fun jsonObjectList(arr: JSONArray): List<JSONObject> {
            val out = mutableListOf<JSONObject>()
            for (i in 0 until arr.length()) {
                arr.optJSONObject(i)?.let { out += it }
            }
            return out
        }

        private fun mergeInputConstrict(step: JSONObject, params: MutableMap<String, Any?>) {
            val constrict = step.optJSONObject("input_constrict") ?: return
            val ck = constrict.keys()
            while (ck.hasNext()) {
                val k = ck.next()
                params[k] = coerceParamValue(constrict.opt(k))
            }
        }

        private fun coerceParamValue(any: Any?): Any? =
            when (any) {
                null, JSONObject.NULL -> null
                is String, is Number, is Boolean -> any
                else -> stringValue(any)
            }

        private fun splitCapability(capability: String): Pair<String, String> {
            val c = capability.trim()
            if (c.isEmpty()) return "" to ""
            if (c.contains(".")) {
                val parts = c.split(".")
                if (parts.size >= 2) {
                    return c to (parts.lastOrNull() ?: "")
                }
            }
            return c to ""
        }

        private fun jsonToMap(o: JSONObject): Map<String, Any?> {
            val raw = mutableMapOf<String, Any?>()
            val rk = o.keys()
            while (rk.hasNext()) {
                val k = rk.next()
                raw[k] = o.opt(k)
            }
            return raw
        }

        fun stringValue(any: Any?): String? =
            when (any) {
                null, JSONObject.NULL -> null
                is String -> any
                is Number -> any.toString()
                else -> any.toString()
            }

        private fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(30, TimeUnit.SECONDS)
                .readTimeout(30, TimeUnit.SECONDS)
                .build()
    }
}
