package com.smarthome.livingroom_android.brain

import android.util.Log
import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterResponse
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.brain.dto.Plan
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * HTTP edge register/heartbeat + local fallback.
 * Plans / intents are pulled only via [com.smarthome.livingroom_android.command.HttpCommandSource].
 *
 * Dual-Brain: LAN and Cloud heartbeats run on independent serial queues and do not
 * wait for each other. Each round is 3 attempts × 3s timeout, 1s apart.
 */
class CompositeBrainClient(
    val local: MockBrainClient,
    val remote: HttpEdgeReporter?,
    val secondaryRemote: HttpEdgeReporter? = null,
) : BrainClient {
    /** Invoked on the caller thread (typically IO). roles is the payload sent, only on success. */
    var onBrainHeartbeat: ((baseUrl: String, ok: Boolean, error: String, roles: List<String>?) -> Unit)? = null
    var onBrainRegistered: ((baseUrl: String) -> Unit)? = null
    /** attempt 0 = idle, 1 = 发送中, 2..max = 重试 n/max. */
    var onBrainHeartbeatPhase: ((baseUrl: String, attempt: Int, maxAttempts: Int) -> Unit)? = null

    @Volatile
    private var lastRegisterRequest: EdgeRegisterRequest? = null

    private val beatScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val mutexes = mutableMapOf<String, Mutex>()

    override suspend fun registerEdge(request: EdgeRegisterRequest): EdgeRegisterResponse {
        lastRegisterRequest = request
        val remoteClient = remote
        if (remoteClient != null) {
            val response = remoteClient.register(request)
            onBrainRegistered?.invoke(remoteClient.baseURL)
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
                    participantId = response.edgeId,
                    runtimeId = request.runtimeId,
                    exposurePolicy = request.exposurePolicy,
                ),
            )
            secondaryOrNull()?.let { sec ->
                runCatching { sec.register(request) }
                    .onSuccess { onBrainRegistered?.invoke(sec.baseURL) }
                    .onFailure { Log.w(TAG, "secondary register failed: ${it.message}") }
            }
            return response
        }
        return local.registerEdge(request)
    }

    override suspend fun reportEdgeInfo(info: EdgeNodeInfo): Boolean {
        local.reportEdgeInfo(info)
        val remoteClient = remote ?: return true
        val primaryJob = beatScope.async {
            heartbeatRound(remoteClient, info, heal = true)
        }
        secondaryOrNull()?.let { sec ->
            beatScope.launch {
                heartbeatRound(sec, info, heal = true)
            }
        }
        return primaryJob.await()
    }

    /** Local plan queue removed — always empty; use server intents pull. */
    override suspend fun fetchPlans(edgeId: String): List<Plan> = emptyList()

    override suspend fun report(report: ExecutionReport) =
        local.report(report)

    private fun secondaryOrNull(): HttpEdgeReporter? {
        val sec = secondaryRemote ?: return null
        val primary = remote?.baseURL?.let { BrainEndpoint.normalizeBase(it) }.orEmpty()
        val other = BrainEndpoint.normalizeBase(sec.baseURL)
        if (other.isBlank() || other == primary) return null
        return sec
    }

    private fun mutexFor(base: String): Mutex {
        val key = BrainEndpoint.normalizeBase(base)
        synchronized(mutexes) {
            return mutexes.getOrPut(key) { Mutex() }
        }
    }

    private suspend fun heartbeatRound(
        reporter: HttpEdgeReporter,
        info: EdgeNodeInfo,
        heal: Boolean,
    ): Boolean = mutexFor(reporter.baseURL).withLock {
        heartbeatAttempts(reporter, info, heal)
    }

    private suspend fun heartbeatAttempts(
        reporter: HttpEdgeReporter,
        info: EdgeNodeInfo,
        heal: Boolean,
    ): Boolean {
        val base = reporter.baseURL
        var lastError = "heartbeat failed"
        for (attempt in 1..MAX_ATTEMPTS) {
            if (attempt > 1) {
                onBrainHeartbeatPhase?.invoke(base, attempt, MAX_ATTEMPTS)
                delay(RETRY_GAP_MS)
            } else {
                onBrainHeartbeatPhase?.invoke(base, 1, MAX_ATTEMPTS)
            }
            val result = heartbeatOnce(reporter, info, heal)
            if (result.isSuccess) {
                onBrainHeartbeatPhase?.invoke(base, 0, MAX_ATTEMPTS)
                return true
            }
            lastError = result.exceptionOrNull()?.message ?: lastError
        }
        onBrainHeartbeat?.invoke(base, false, lastError, null)
        onBrainHeartbeatPhase?.invoke(base, 0, MAX_ATTEMPTS)
        return false
    }

    /**
     * @return true on success; false-with-exception carries the error for retry.
     */
    private suspend fun heartbeatOnce(
        reporter: HttpEdgeReporter,
        info: EdgeNodeInfo,
        heal: Boolean,
    ): Result<Boolean> {
        val base = reporter.baseURL
        return try {
            reporter.heartbeat(info)
            onBrainHeartbeat?.invoke(base, true, "", info.roles)
            Result.success(true)
        } catch (e: HttpEdgeException) {
            val needsRegister = e.httpCode == 401 || (e.message?.contains("register first") == true)
            if (heal && needsRegister) {
                val req = lastRegisterRequest
                if (req != null) {
                    val registered = runCatching {
                        reporter.register(req, timeoutSec = ATTEMPT_TIMEOUT_SEC)
                    }
                    if (registered.isSuccess) {
                        onBrainRegistered?.invoke(base)
                    } else {
                        return Result.failure(
                            registered.exceptionOrNull()
                                ?: IllegalStateException("注册失败"),
                        )
                    }
                    return try {
                        reporter.heartbeat(info)
                        onBrainHeartbeat?.invoke(base, true, "", info.roles)
                        Result.success(true)
                    } catch (t: Throwable) {
                        Result.failure(t)
                    }
                }
            }
            Result.failure(e)
        } catch (t: Throwable) {
            Log.w(TAG, "heartbeat failed ${reporter.baseURL}: ${t.message}")
            Result.failure(t)
        }
    }

    companion object {
        private const val TAG = "CompositeBrainClient"
        const val MAX_ATTEMPTS = 3
        const val ATTEMPT_TIMEOUT_SEC = 3L
        const val RETRY_GAP_MS = 1_000L
    }
}
