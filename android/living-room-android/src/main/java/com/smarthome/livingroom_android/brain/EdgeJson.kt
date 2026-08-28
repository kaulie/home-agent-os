package com.smarthome.livingroom_android.brain

import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.EdgeHealthSnapshot
import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterResponse
import com.smarthome.livingroom_android.brain.dto.EndpointAd
import com.smarthome.livingroom_android.brain.dto.IntentSourceAd
import com.smarthome.livingroom_android.brain.dto.ParticipantWire
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import org.json.JSONArray
import org.json.JSONObject

/** JSON encode/decode for edge register / heartbeat (snake_case, org.json). */
object EdgeJson {
    fun encodeRegisterRequest(request: EdgeRegisterRequest): String {
        val o = JSONObject()
        o.put("client_hint", request.clientHint)
        o.put("display_name", request.displayName)
        o.put("device_type", request.deviceType.wire)
        val loc = request.location?.trim()?.takeIf { it.isNotEmpty() } ?: request.room
        o.put("location", loc)
        o.put("room", request.room)
        o.put("services", encodeServices(request.services))
        applyRoles(o, request.roles)
        o.put("intent_sources", encodeIntentSources(request.intentSources))
        o.put("endpoints", encodeEndpoints(request.endpoints))
        val pid = request.participantId?.trim().orEmpty()
        val rid = request.runtimeId?.trim().orEmpty().ifEmpty { pid }
        if (rid.isNotEmpty()) {
            o.put("runtime_id", rid)
            o.put("participant_id", rid)
            o.put("edge_id", rid)
        } else if (pid.isNotEmpty()) {
            o.put("participant_id", pid)
            o.put("edge_id", pid)
        }
        encodeExposurePolicy(o, request.exposurePolicy)
        if (request.appVersion != null) o.put("app_version", request.appVersion)
        o.put("reported_at", request.reportedAtSec)
        return o.toString()
    }

    fun encodeNodeInfo(info: EdgeNodeInfo): String {
        val o = JSONObject()
        o.put("edge_id", info.edgeId)
        o.put("display_name", info.displayName)
        o.put("device_type", info.deviceType.wire)
        val loc = info.location?.trim()?.takeIf { it.isNotEmpty() } ?: info.room
        o.put("location", loc)
        o.put("room", info.room)
        o.put("online_status", info.onlineStatus.wire)
        o.put("health", encodeHealth(info.health))
        o.put("services", encodeServices(info.services))
        applyRoles(o, info.roles)
        o.put("intent_sources", encodeIntentSources(info.intentSources))
        o.put("endpoints", encodeEndpoints(info.endpoints))
        val pid = info.participantId?.trim().orEmpty().ifEmpty { info.edgeId }
        val rid = info.runtimeId?.trim().orEmpty().ifEmpty { pid }
        if (rid.isNotEmpty()) {
            o.put("runtime_id", rid)
            o.put("participant_id", rid)
            o.put("edge_id", rid)
        } else if (pid.isNotEmpty()) {
            o.put("participant_id", pid)
            o.put("edge_id", pid)
        }
        encodeExposurePolicy(o, info.exposurePolicy)
        if (info.appVersion != null) o.put("app_version", info.appVersion)
        o.put("reported_at", info.reportedAtSec)
        o.put("client_time_ms", info.clientTimeMs)
        return o.toString()
    }

    private fun encodeExposurePolicy(o: JSONObject, policy: Map<String, List<String>>?) {
        if (policy == null) return
        val obj = JSONObject()
        for ((domain, caps) in policy) {
            obj.put(domain, JSONArray(caps))
        }
        o.put("exposure_policy", obj)
    }

    fun parseRegisterResponse(body: String): EdgeRegisterResponse {
        val o = JSONObject(body)
        val edgeId = o.optString("edge_id", "")
            .ifBlank { o.optString("participant_id", "") }
            .ifBlank { o.optString("edgeId", "") }
            .trim()
        return EdgeRegisterResponse(
            ok = o.optBoolean("ok", false) || edgeId.isNotEmpty(),
            status = o.optString("status", if (edgeId.isNotEmpty()) "approved" else ""),
            edgeId = edgeId,
            message = o.optString("message", ""),
            ts = if (o.has("ts")) o.optDouble("ts") else null,
        )
    }

    private fun applyRoles(o: JSONObject, roles: List<String>) {
        val ordered = ParticipantWire.ordered(roles)
        o.put("roles", JSONArray(ordered))
        o.put("role_intent_source", ordered.contains(ParticipantWire.ROLE_INTENT_SOURCE))
        o.put("role_runtime", ordered.contains(ParticipantWire.ROLE_RUNTIME))
        o.put("role_endpoint", ordered.contains(ParticipantWire.ROLE_ENDPOINT))
        o.put("role_observer", ordered.contains(ParticipantWire.ROLE_OBSERVER))
    }

    private fun encodeIntentSources(sources: List<IntentSourceAd>): JSONArray {
        val arr = JSONArray()
        for (s in sources) {
            arr.put(
                JSONObject()
                    .put("source_id", s.sourceId)
                    .put("channel", s.channel),
            )
        }
        return arr
    }

    private fun encodeEndpoints(endpoints: List<EndpointAd>): JSONArray {
        val arr = JSONArray()
        for (e in endpoints) {
            arr.put(
                JSONObject()
                    .put("endpoint_id", e.endpointId)
                    .put("type", e.type)
                    .put("supported_presentation", JSONArray(e.supportedPresentation)),
            )
        }
        return arr
    }

    private fun encodeHealth(health: EdgeHealthSnapshot): JSONObject {
        val details = JSONObject()
        health.details.forEach { (k, v) -> details.put(k, v) }
        return JSONObject()
            .put("status", health.status.wire)
            .put("summary", health.summary)
            .put("details", details)
    }

    private fun encodeServices(services: List<ServiceDescriptor>): JSONArray {
        val arr = JSONArray()
        for (svc in services) {
            arr.put(
                JSONObject()
                    .put("service_id", svc.serviceId)
                    .put("version", svc.version)
                    .put("display_name", svc.displayName)
                    .put("group", svc.group)
                    .put("capabilities", encodeCapabilities(svc.capabilities)),
            )
        }
        return arr
    }

    private fun encodeCapabilities(caps: List<CapabilityDescriptor>): JSONArray {
        val arr = JSONArray()
        for (cap in caps) {
            val o = JSONObject()
                .put("capability_id", cap.capabilityId)
                .put("role", cap.role)
                .put("planner_recognize", cap.plannerRecognize)
                .put("typical_triggers", JSONArray(cap.typicalTriggers))
                .put("do_not_dispatch", JSONArray(cap.doNotDispatch))
                .put("input_schema", encodeSchema(cap.inputSchema))
                .put("output_schema", encodeSchema(cap.outputSchema))
            if (cap.kind.isNotBlank()) {
                o.put("kind", cap.kind)
            }
            o.put("composition", cap.composition.ifBlank { "atomic" })
            if (cap.decomposesTo.isNotEmpty()) {
                o.put("decomposes_to", JSONArray(cap.decomposesTo))
            }
            if (cap.preferWhen.isNotBlank()) {
                o.put("prefer_when", cap.preferWhen)
            }
            if (cap.description.isNotBlank()) {
                o.put("description", cap.description)
            }
            // P0: availability snapshot fields (heartbeat only; null on declaration).
            cap.available?.let { o.put("available", it) }
            cap.observedAt?.let { o.put("observed_at", it) }
            cap.unavailableReason?.let { o.put("unavailable_reason", it) }
            arr.put(o)
        }
        return arr
    }

    private fun encodeSchema(schema: Map<String, SchemaField>): JSONObject {
        val o = JSONObject()
        for ((name, field) in schema) {
            o.put(
                name,
                JSONObject()
                    .put("type", field.type)
                    .put("required", field.required)
                    .put("description", field.description),
            )
        }
        return o
    }
}
