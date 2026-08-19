package com.smarthome.livingroom_android.brain

import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.EdgeHealthSnapshot
import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterResponse
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
        o.put("roles", JSONArray(request.roles))
        o.put("role_runtime", true)
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
        o.put("roles", JSONArray(info.roles))
        o.put("role_runtime", true)
        if (info.appVersion != null) o.put("app_version", info.appVersion)
        o.put("reported_at", info.reportedAtSec)
        o.put("client_time_ms", info.clientTimeMs)
        return o.toString()
    }

    fun parseRegisterResponse(body: String): EdgeRegisterResponse {
        val o = JSONObject(body)
        val edgeId = o.optString("edge_id", o.optString("edgeId", "")).trim()
        return EdgeRegisterResponse(
            ok = o.optBoolean("ok", false),
            status = o.optString("status", ""),
            edgeId = edgeId,
            message = o.optString("message", ""),
            ts = if (o.has("ts")) o.optDouble("ts") else null,
        )
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
            arr.put(
                JSONObject()
                    .put("capability_id", cap.capabilityId)
                    .put("description", cap.description)
                    .put("input_schema", encodeSchema(cap.inputSchema))
                    .put("output_schema", encodeSchema(cap.outputSchema)),
            )
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
