package com.smarthome.livingroom_android.brain

import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterResponse
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.brain.dto.Plan

/**
 * Layer 2 brain boundary.
 * Edge → Brain: [registerEdge] then [reportEdgeInfo] (heartbeat).
 * Intent steps are pulled from the business server via HttpCommandSource (not BrainClient).
 */
interface BrainClient {
    suspend fun registerEdge(request: EdgeRegisterRequest): EdgeRegisterResponse

    /**
     * Heartbeat / offline report.
     * @return true if the remote (or mock) heartbeat succeeded.
     */
    suspend fun reportEdgeInfo(info: EdgeNodeInfo): Boolean

    /** Deprecated local plan pull — always empty; kept for interface stability. */
    suspend fun fetchPlans(edgeId: String): List<Plan>

    suspend fun report(report: ExecutionReport)
}
