package com.smarthome.livingroom_android.intent

import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.ui.BrainHeartbeatStatus
import com.smarthome.livingroom_android.ui.BrainNetworkEnvironment
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** User Console execution现场 extras for `POST /api/v1/debug/report`. */
object DebugClientSnapshot {
    private val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    fun build(
        env: BrainNetworkEnvironment,
        intentServerUrl: String,
        lanHeartbeat: BrainHeartbeatStatus,
        cloudHeartbeat: BrainHeartbeatStatus,
        clientHint: String,
        journey: IntentJourney,
        intentId: String,
        runtimeLog: Map<String, Any> = emptyMap(),
    ): Map<String, Any> {
        val primary = env.mode
        return linkedMapOf(
            "primary_brain" to mapOf(
                "mode" to primary.name.lowercase(Locale.US),
                "mode_label" to env.mode.label,
                "routing" to env.routing.rawValue,
                "routing_label" to env.routing.title,
                "base_url" to BrainEndpoint.displayBase(intentServerUrl),
                "intent_url" to intentServerUrl,
                "path_kind" to env.pathKind.name.lowercase(Locale.US),
                "looks_on_home_lan" to env.looksOnHomeLAN,
            ),
            "heartbeat" to mapOf(
                "primary_mode" to primary.name.lowercase(Locale.US),
                "lan" to heartbeatMap(lanHeartbeat),
                "cloud" to heartbeatMap(cloudHeartbeat),
            ),
            "runtime_intent_log" to runtimeIntentLog(journey, intentId, runtimeLog),
            "journey_phase" to journey.phase.wire,
            "journey_error" to (journey.error.orEmpty()),
            "journey_logistics" to journey.logisticsText(),
            "brain_mode" to env.mode.label,
            "brain_routing" to env.routing.title,
            "brain_base" to BrainEndpoint.displayBase(intentServerUrl),
            "client_hint" to clientHint,
        )
    }

    fun toJsonObject(map: Map<String, Any>): JSONObject {
        val out = JSONObject()
        for ((key, value) in map) {
            out.put(key, toJsonValue(value))
        }
        return out
    }

    private fun heartbeatMap(status: BrainHeartbeatStatus): Map<String, Any?> {
        return linkedMapOf(
            "mode" to status.mode.name.lowercase(Locale.US),
            "registered" to status.registered,
            "last_ok" to status.lastOk,
            "last_error" to status.lastError,
            "phase" to status.phase.name.lowercase(Locale.US),
            "registered_at" to isoOrNull(status.registeredAtMs),
            "last_attempt_at" to isoOrNull(status.lastAttemptAtMs),
            "last_success_at" to isoOrNull(status.lastSuccessAtMs),
        )
    }

    private fun runtimeIntentLog(
        journey: IntentJourney,
        intentId: String,
        runtimeLog: Map<String, Any>,
    ): Map<String, Any> {
        val log = linkedMapOf<String, Any>()
        if (runtimeLog.isNotEmpty()) {
            log.putAll(runtimeLog)
        } else {
            log["note"] = "no local runtime log for this intent"
        }
        if (journey.planSteps.isNotEmpty()) {
            log["plan_steps"] = journey.planSteps.map { step ->
                mapOf(
                    "step" to step.step,
                    "capability" to step.capability,
                    "status" to step.status,
                    "detail" to step.detail,
                )
            }
        }
        log["intent_id"] = intentId
        return log
    }

    private fun isoOrNull(ms: Long): String? {
        if (ms <= 0L) return null
        return iso.format(Date(ms))
    }

    private fun toJsonValue(value: Any?): Any {
        return when (value) {
            null -> JSONObject.NULL
            is Map<*, *> -> {
                val nested = JSONObject()
                value.forEach { (k, v) ->
                    if (k is String) nested.put(k, toJsonValue(v))
                }
                nested
            }
            is List<*> -> {
                val arr = JSONArray()
                value.forEach { arr.put(toJsonValue(it)) }
                arr
            }
            else -> value
        }
    }
}
