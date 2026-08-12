package com.smarthome.livingroom_v2.brain

import com.smarthome.livingroom_v2.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_v2.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_v2.brain.dto.EdgeRegisterResponse
import com.smarthome.livingroom_v2.brain.dto.EdgeRegistration
import com.smarthome.livingroom_v2.brain.dto.ExecutionReport
import com.smarthome.livingroom_v2.brain.dto.Plan
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/**
 * Local stand-in used only when remote Brain is unavailable (register/heartbeat/report).
 * Intent / plan pull is always from the real server via [HttpCommandSource] — no local plan queue.
 */
class MockBrainClient : BrainClient {
    private val registrations = ConcurrentHashMap<String, EdgeNodeInfo>()
    private val reports = CopyOnWriteArrayList<ExecutionReport>()
    private val issuedEdgeIds = ConcurrentHashMap.newKeySet<String>()

    val lastNodeInfo: EdgeNodeInfo?
        get() = registrations.values.maxByOrNull { it.reportedAtSec }

    val lastRegistration: EdgeRegistration?
        get() {
            val info = lastNodeInfo ?: return null
            return EdgeRegistration(
                edgeId = info.edgeId,
                services = info.services,
                registeredAt = (info.reportedAtSec * 1000).toLong(),
            )
        }

    fun snapshotReports(): List<ExecutionReport> = reports.toList()

    override suspend fun registerEdge(request: EdgeRegisterRequest): EdgeRegisterResponse {
        val hint = request.clientHint?.trim().orEmpty()
        val edgeId = when {
            hint.isNotEmpty() && hint !in issuedEdgeIds -> hint
            hint.isNotEmpty() -> "$hint-${UUID.randomUUID().toString().take(6).lowercase()}"
            else -> "edge-${UUID.randomUUID().toString().take(8).lowercase()}"
        }
        issuedEdgeIds.add(edgeId)
        return EdgeRegisterResponse(
            ok = true,
            status = "approved",
            edgeId = edgeId,
            message = "mock approved",
            ts = System.currentTimeMillis() / 1000.0,
        )
    }

    override suspend fun reportEdgeInfo(info: EdgeNodeInfo): Boolean {
        if (info.edgeId.isBlank()) {
            throw HttpEdgeException(401, "heartbeat requires edgeId; call registerEdge first")
        }
        issuedEdgeIds.add(info.edgeId)
        registrations[info.edgeId] = info
        return true
    }

    override suspend fun fetchPlans(edgeId: String): List<Plan> = emptyList()

    override suspend fun report(report: ExecutionReport) {
        reports.add(report)
        if (reports.size > 100) {
            reports.subList(0, reports.size - 100).clear()
        }
    }
}
