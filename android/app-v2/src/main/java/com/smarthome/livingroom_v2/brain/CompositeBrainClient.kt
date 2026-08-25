package com.smarthome.livingroom_v2.brain

import android.util.Log
import com.smarthome.livingroom_v2.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_v2.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_v2.brain.dto.EdgeRegisterResponse
import com.smarthome.livingroom_v2.brain.dto.ExecutionReport
import com.smarthome.livingroom_v2.brain.dto.Plan

/**
 * HTTP edge register/heartbeat + local fallback.
 * Plans / intents are pulled only via [com.smarthome.livingroom_v2.command.HttpCommandSource].
 */
class CompositeBrainClient(
    val local: MockBrainClient,
    val remote: HttpEdgeReporter?,
) : BrainClient {
    override suspend fun registerEdge(request: EdgeRegisterRequest): EdgeRegisterResponse {
        val remoteClient = remote
        if (remoteClient != null) {
            val response = remoteClient.register(request)
            local.registerEdge(
                EdgeRegisterRequest(
                    clientHint = response.edgeId,
                    displayName = request.displayName,
                    deviceType = request.deviceType,
                    room = request.room,
                    services = request.services,
                    appVersion = request.appVersion,
                    roles = request.roles,
                    location = request.location,
                    intentSources = request.intentSources,
                    endpoints = request.endpoints,
                    participantId = request.participantId,
                ),
            )
            return response
        }
        return local.registerEdge(request)
    }

    override suspend fun reportEdgeInfo(info: EdgeNodeInfo): Boolean {
        local.reportEdgeInfo(info)
        val remoteClient = remote ?: return true
        return try {
            remoteClient.heartbeat(info)
            true
        } catch (e: HttpEdgeException) {
            if (e.httpCode == 401) throw e
            Log.w(TAG, "remote heartbeat failed: ${e.message}")
            false
        } catch (t: Throwable) {
            Log.w(TAG, "remote heartbeat failed: ${t.message}")
            false
        }
    }

    /** Local plan queue removed — always empty; use server intents pull. */
    override suspend fun fetchPlans(edgeId: String): List<Plan> = emptyList()

    override suspend fun report(report: ExecutionReport) =
        local.report(report)

    companion object {
        private const val TAG = "CompositeBrainClient"
    }
}
