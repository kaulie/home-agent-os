package com.smarthome.livingroom_v2.brain.dto

/** One field in input_schema / output_schema. */
data class SchemaField(
    val type: String,
    val required: Boolean = false,
    val description: String = "",
)

/** One capability under a service (wire + local invoke). */
data class CapabilityDescriptor(
    val capabilityId: String,
    val description: String,
    val inputSchema: Map<String, SchemaField> = emptyMap(),
    val outputSchema: Map<String, SchemaField> = emptyMap(),
)

/**
 * Edge → Brain service unit.
 * group: music / camera / speaker / …
 */
data class ServiceDescriptor(
    val serviceId: String,
    val version: String,
    val displayName: String,
    val group: String,
    val capabilities: List<CapabilityDescriptor>,
)

enum class OnFailurePolicy {
    ABORT,
    CONTINUE,
}

data class PlanStep(
    val stepId: String,
    val skillId: String,
    val action: String,
    val params: Map<String, Any?> = emptyMap(),
    val onFailure: OnFailurePolicy = OnFailurePolicy.ABORT,
)

data class Plan(
    val planId: String,
    val steps: List<PlanStep>,
    val createdAt: Long = System.currentTimeMillis(),
)

enum class StepStatus {
    OK,
    ERROR,
    SKIPPED,
}

data class ExecutionReport(
    val planId: String,
    val stepId: String,
    val status: StepStatus,
    val message: String? = null,
    val finishedAt: Long = System.currentTimeMillis(),
)

data class EdgeRegistration(
    val edgeId: String,
    val services: List<ServiceDescriptor>,
    val registeredAt: Long = System.currentTimeMillis(),
)

enum class EdgeDeviceType(val wire: String) {
    IPHONE("iphone"),
    IPAD("ipad"),
    MAC("mac"),
    ANDROID_TV("android_tv"),
    XIAOMI_TV("xiaomi_tv"),
    CHROMECAST("chromecast"),
    ANDROID("android"),
    OTHER("other"),
    ;

    companion object {
        fun fromWire(value: String?): EdgeDeviceType {
            val v = value?.trim()?.lowercase().orEmpty()
            return entries.firstOrNull { it.wire == v } ?: OTHER
        }
    }
}

enum class EdgeOnlineStatus(val wire: String) {
    ONLINE("online"),
    OFFLINE("offline"),
}

enum class EdgeHealthStatus(val wire: String) {
    HEALTHY("healthy"),
    DEGRADED("degraded"),
    UNHEALTHY("unhealthy"),
    UNKNOWN("unknown"),
}

data class EdgeHealthSnapshot(
    val status: EdgeHealthStatus = EdgeHealthStatus.UNKNOWN,
    val summary: String = "unknown",
    val details: Map<String, String> = emptyMap(),
)

/** Participant Model roles (docs/participant-model.md). */
object ParticipantWire {
    const val ROLE_RUNTIME = "runtime"

    fun runtimeRoles(): List<String> = listOf(ROLE_RUNTIME)
}

/** Static identity before Brain assigns edgeId. */
data class EdgeIdentity(
    val clientHint: String,
    val displayName: String,
    val deviceType: EdgeDeviceType,
    val room: String = "living-room",
    val appVersion: String? = null,
) {
    val location: String
        get() = room
}

/** First-contact register (no trusted edge_id yet). */
data class EdgeRegisterRequest(
    val clientHint: String?,
    val displayName: String,
    val deviceType: EdgeDeviceType,
    val room: String,
    val services: List<ServiceDescriptor>,
    val appVersion: String? = null,
    val reportedAtSec: Double = System.currentTimeMillis() / 1000.0,
    val roles: List<String> = ParticipantWire.runtimeRoles(),
    val location: String? = null,
)

data class EdgeRegisterResponse(
    val ok: Boolean,
    val status: String,
    val edgeId: String,
    val message: String = "",
    val ts: Double? = null,
) {
    val isApproved: Boolean
        get() = ok &&
            status.equals("approved", ignoreCase = true) &&
            edgeId.isNotBlank()
}

/** Full edge-node snapshot for register / heartbeat / offline. */
data class EdgeNodeInfo(
    val edgeId: String,
    val displayName: String,
    val deviceType: EdgeDeviceType,
    val room: String,
    val onlineStatus: EdgeOnlineStatus,
    val health: EdgeHealthSnapshot,
    val services: List<ServiceDescriptor>,
    val appVersion: String? = null,
    val reportedAtSec: Double = System.currentTimeMillis() / 1000.0,
    val clientTimeMs: Long = System.currentTimeMillis(),
    val roles: List<String> = ParticipantWire.runtimeRoles(),
    val location: String? = null,
)
