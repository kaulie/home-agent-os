package com.smarthome.livingroom_android.edge

import android.content.Context
import android.util.Log
import com.smarthome.livingroom_android.brain.BrainClient
import com.smarthome.livingroom_android.brain.HttpEdgeException
import com.smarthome.livingroom_android.brain.dto.EdgeDeviceType
import com.smarthome.livingroom_android.brain.dto.EdgeHealthSnapshot
import com.smarthome.livingroom_android.brain.dto.EdgeHealthStatus
import com.smarthome.livingroom_android.brain.dto.EdgeIdentity
import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeOnlineStatus
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.command.CommandHandler
import com.smarthome.livingroom_android.command.HttpCommandSource
import com.smarthome.livingroom_android.command.IntentPipeline
import com.smarthome.livingroom_android.command.IntentsPullSnapshot
import com.smarthome.livingroom_android.command.runtime.LocalEdgeRuntime
import com.smarthome.livingroom_android.data.AppSettings
import com.smarthome.livingroom_android.data.EdgeIdStore
import com.smarthome.livingroom_android.skill.Skill
import com.smarthome.livingroom_android.skill.SkillContext
import com.smarthome.livingroom_android.skill.SkillResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Layer 4 Edge Agent: register → heartbeat → peek intents → IntentScheduler → IntentStepExecutor.
 */
class EdgeAgent(
    private val appContext: Context,
    val identity: EdgeIdentity,
    private val brain: BrainClient,
    private val registry: SkillRegistry,
    private val heartbeatIntervalMs: Long,
    private val commandSource: HttpCommandSource,
    private val commandHandler: CommandHandler,
    private val localRuntime: LocalEdgeRuntime,
    private val intentPipeline: IntentPipeline? = null,
) {
    interface Listener {
        fun onStatus(message: String)
        fun onReport(report: ExecutionReport)
        fun onEdgeIdAssigned(edgeId: String) {}
        fun onEdgeInfoReported(info: EdgeNodeInfo) {}
        fun onHeartbeatStatsChanged(successCount: Long, lastSuccessAtMs: Long) {}
        /** CommandHandler / Agent pipeline lines for the run-log panel. */
        fun onCommandPipelineLog(message: String) {}
        /** Latest intents poll (including empty queue) for the snapshot panel. */
        fun onIntentsPulled(snapshot: IntentsPullSnapshot) {}
    }

    private val settings = AppSettings(appContext)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val pollMutex = Mutex()
    private var loopJob: Job? = null

    @Volatile
    var assignedEdgeId: String? = EdgeIdStore.load(appContext)
        private set

    /** Effective id: Brain-issued if present, else clientHint (UI only until register). */
    val edgeId: String
        get() = assignedEdgeId?.takeIf { it.isNotBlank() } ?: identity.clientHint

    val hasCachedEdgeId: Boolean
        get() = !assignedEdgeId.isNullOrBlank()

    @Volatile
    var running: Boolean = false
        private set

    var listener: Listener? = null

    val heartbeatSuccessCount: Long
        get() = settings.heartbeatSuccessCount

    val lastHeartbeatSuccessAtMs: Long
        get() = settings.lastHeartbeatSuccessAtMs

    fun installSkills(vararg skills: Skill) {
        registry.registerAll(*skills)
    }

    fun start() {
        if (running) return
        running = true
        postStatus(
            "EdgeAgent starting hint=${identity.clientHint} device=${identity.deviceType.wire}" +
                (assignedEdgeId?.let { " assigned=$it" } ?: " (need register)"),
        )
        loopJob = scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    ensureRegisteredWithBrain()
                    val info = buildNodeInfo(EdgeOnlineStatus.ONLINE)
                    val ok = brain.reportEdgeInfo(info)
                    withContext(Dispatchers.Main) {
                        listener?.onEdgeInfoReported(info)
                    }
                    if (ok) {
                        recordOnlineHeartbeatSuccess()
                        val capCount = info.services.sumOf { it.capabilities.size }
                        postStatus(
                            "Heartbeat ok edgeId=${info.edgeId} services=${info.services.size} " +
                                "caps=$capCount",
                        )
                    } else {
                        postStatus("Heartbeat failed (remote) edgeId=${info.edgeId}")
                    }
                    pullAndHandleServerCommands()
                }
            } catch (t: Throwable) {
                handleBrainFailure(t, phase = "register/heartbeat")
            }
            while (isActive && running) {
                delay(heartbeatIntervalMs)
                if (!isActive || !running) break
                tick()
            }
        }
    }

    fun stop() {
        val wasRunning = running
        val hadId = assignedEdgeId != null
        running = false
        loopJob?.cancel()
        loopJob = null
        if (wasRunning && hadId) {
            scope.launch {
                withContext(Dispatchers.IO) {
                    runCatching {
                        val info = buildNodeInfo(EdgeOnlineStatus.OFFLINE)
                        brain.reportEdgeInfo(info)
                        withContext(Dispatchers.Main) {
                            listener?.onEdgeInfoReported(info)
                        }
                    }
                }
                postStatus("EdgeAgent stopped (reported offline to Brain)")
            }
        } else {
            postStatus("EdgeAgent stopped")
        }
    }

    fun shutdown() {
        stop()
        scope.cancel()
    }

    /** Pull + execute once immediately (e.g. after UI injects a plan). */
    fun pollNow() {
        scope.launch { tick() }
    }

    fun clearAssignedEdgeId() {
        assignedEdgeId = null
        EdgeIdStore.clear(appContext)
        commandSource.localEdgeId = null
        localRuntime.updateEdgeId(identity.clientHint)
        postStatus("Cleared assigned edgeId; next start will re-register")
    }

    fun adoptAssignedEdgeId(id: String) {
        val trimmed = id.trim()
        if (trimmed.isEmpty()) return
        applyAssignedEdgeId(trimmed)
        postStatus("Adopted Brain edgeId=$trimmed (saved locally)")
    }

    /**
     * One-shot UI register (same as iOS「注册」).
     * If a local edge_id already exists, skips POST unless [force] is true.
     */
    fun registerOnce(force: Boolean = false, onDone: (ok: Boolean, message: String) -> Unit = { _, _ -> }) {
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    if (!force) {
                        val cached = assignedEdgeId?.trim().orEmpty()
                            .ifBlank { EdgeIdStore.load(appContext).orEmpty() }
                        if (cached.isNotBlank()) {
                            applyAssignedEdgeId(cached)
                            return@runCatching "已注册，复用本地 edge_id=$cached（清 edgeId 后可重新注册）"
                        }
                    } else {
                        clearAssignedEdgeId()
                    }
                    performRegisterWithBrain()
                    "注册成功 edge_id=$assignedEdgeId"
                }
            }
            val ok = result.isSuccess
            val msg = result.getOrElse { it.message ?: it.javaClass.simpleName }
            postStatus(if (ok) msg else "注册失败：$msg")
            if (!ok) handleBrainFailure(result.exceptionOrNull()!!, phase = "register")
            onDone(ok, msg)
        }
    }

    /** One-shot UI heartbeat (same as iOS「心跳」) — requires assigned edge_id. */
    fun heartbeatOnce(onDone: (ok: Boolean, message: String) -> Unit = { _, _ -> }) {
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    ensureRegisteredWithBrain()
                    val id = assignedEdgeId?.trim().orEmpty()
                    if (id.isEmpty()) {
                        error("请先注册拿到 edgeId，再发心跳")
                    }
                    val info = buildNodeInfo(EdgeOnlineStatus.ONLINE)
                    val ok = brain.reportEdgeInfo(info)
                    withContext(Dispatchers.Main) {
                        listener?.onEdgeInfoReported(info)
                    }
                    if (!ok) error("Heartbeat failed (remote) edgeId=${info.edgeId}")
                    recordOnlineHeartbeatSuccess()
                    "心跳成功 edgeId=${info.edgeId} services=${info.services.size}"
                }
            }
            val ok = result.isSuccess
            val msg = result.getOrElse { it.message ?: it.javaClass.simpleName }
            postStatus(if (ok) msg else "心跳失败：$msg")
            if (!ok) {
                result.exceptionOrNull()?.let { handleBrainFailure(it, phase = "heartbeat") }
            }
            onDone(ok, msg)
        }
    }

    private suspend fun ensureRegisteredWithBrain() {
        val existing = assignedEdgeId?.trim().orEmpty()
        if (existing.isNotEmpty()) {
            commandSource.localEdgeId = existing
            localRuntime.updateEdgeId(existing)
            postStatus("Reuse cached edge_id=$existing (skip register)")
            return
        }
        val fromStore = EdgeIdStore.load(appContext)
        if (!fromStore.isNullOrBlank()) {
            applyAssignedEdgeId(fromStore)
            postStatus("Loaded edge_id=$fromStore from local store (skip register)")
            return
        }
        performRegisterWithBrain()
    }

    private suspend fun performRegisterWithBrain() {
        val request = EdgeRegisterRequest(
            clientHint = identity.clientHint,
            displayName = identity.displayName,
            deviceType = identity.deviceType,
            room = identity.room,
            services = registry.services(),
            appVersion = identity.appVersion,
        )
        postStatus("No cached edge_id — registering with Brain…")
        val response = brain.registerEdge(request)
        if (!response.isApproved) {
            val detail = response.message.ifEmpty { response.status }
            throw IllegalStateException(
                "Brain register ${response.status.ifEmpty { "failed" }}: $detail",
            )
        }
        applyAssignedEdgeId(response.edgeId)
        postStatus(
            "Brain assigned edgeId=${response.edgeId} status=${response.status} (saved locally)",
        )
    }

    private fun applyAssignedEdgeId(id: String) {
        assignedEdgeId = id
        EdgeIdStore.save(appContext, id)
        localRuntime.updateEdgeId(id)
        commandSource.localEdgeId = id
        scope.launch {
            listener?.onEdgeIdAssigned(id)
        }
    }

    fun buildNodeInfo(online: EdgeOnlineStatus): EdgeNodeInfo {
        val health = if (online == EdgeOnlineStatus.OFFLINE) {
            EdgeHealthSnapshot(status = EdgeHealthStatus.UNKNOWN, summary = "agent stopped")
        } else {
            EdgeHealthSnapshot(
                status = if (running) EdgeHealthStatus.HEALTHY else EdgeHealthStatus.UNKNOWN,
                summary = if (running) "agent running" else "agent idle",
            )
        }
        return EdgeNodeInfo(
            edgeId = edgeId,
            displayName = identity.displayName,
            deviceType = identity.deviceType,
            room = identity.room,
            onlineStatus = online,
            health = health,
            services = registry.services(),
            appVersion = identity.appVersion,
        )
    }

    private suspend fun tick() {
        pollMutex.withLock {
            withContext(Dispatchers.IO) {
                runCatching {
                    ensureRegisteredWithBrain()
                    val info = buildNodeInfo(EdgeOnlineStatus.ONLINE)
                    val ok = brain.reportEdgeInfo(info)
                    withContext(Dispatchers.Main) {
                        listener?.onEdgeInfoReported(info)
                    }
                    if (ok) {
                        recordOnlineHeartbeatSuccess()
                    } else {
                        postStatus("Heartbeat failed (remote) edgeId=${info.edgeId}")
                    }
                    pullAndHandleServerCommands()
                }.onFailure { t ->
                    handleBrainFailure(t, phase = "tick")
                }
            }
        }
    }

    private suspend fun pullAndHandleServerCommands() {
        // Peek (not pop): multi-tick / multi-edge need the same intent until terminal.
        val snapshot = commandSource.fetchSnapshot(consume = false)
        withContext(Dispatchers.Main) {
            listener?.onIntentsPulled(snapshot)
        }
        if (!snapshot.ok) {
            postStatus("Intents pull failed: ${snapshot.error}")
            Log.w(TAG, "intents pull failed: ${snapshot.error}")
            return
        }
        if (snapshot.intents.isEmpty()) {
            return
        }
        val pipeline = intentPipeline
        if (pipeline != null) {
            postStatus(
                "Pulled ${snapshot.intents.size} intent(s) edgeId=$edgeId → scheduler then step executor",
            )
            pipeline.handle(snapshot.intents, edgeId)
            return
        }
        // Legacy fallback: expand local steps only.
        if (snapshot.commands.isEmpty()) return
        postStatus("Pulled ${snapshot.commands.size} server intent step(s) → CommandHandler")
        val results = commandHandler.handle(snapshot.commands)
        results.forEachIndexed { idx, r ->
            val status = when {
                r.skipped -> "skipped"
                r.ok -> "ok"
                else -> "error"
            }
            val hint = r.message
                ?.lineSequence()
                ?.map { it.trim() }
                ?.firstOrNull { it.isNotEmpty() }
                ?.let { line ->
                    val clipped = if (line.length > 80) line.take(80) + "…" else line
                    " · $clipped"
                }
                .orEmpty()
            postStatus("Task[${idx + 1}/${results.size}] $status taskId=${r.taskId}$hint")
        }
        postStatus(
            "CommandHandler done server: ok=${results.count { it.ok }} " +
                "skipped=${results.count { it.skipped }} total=${results.size}",
        )
    }

    /** Manual pull now (same path as tick). */
    fun pullIntentsNow() {
        scope.launch {
            pollMutex.withLock {
                withContext(Dispatchers.IO) {
                    pullAndHandleServerCommands()
                }
            }
        }
    }

    /**
     * Local debug single-point skill invoke (搜歌 / 连蓝牙等).
     *
     * **Not** the intent pipeline: no HttpCommandSource, no CommandHandler,
     * no intent_status reporting. Server intents go only through
     * [pullAndHandleServerCommands].
     */
    fun invokeLocalSkillAction(
        skillId: String,
        capabilityId: String,
        params: Map<String, Any?> = emptyMap(),
    ) {
        scope.launch {
            withContext(Dispatchers.IO) {
                postStatus("LocalAction $skillId / $capabilityId (bypass intent pipeline)")
                val skill = registry.get(skillId)
                val result: SkillResult = if (skill == null) {
                    SkillResult.error("skill not registered: $skillId")
                } else {
                    val ctx = SkillContext(
                        appContext = appContext,
                        edgeId = edgeId,
                        planId = "local-action",
                        stepId = "local-${System.currentTimeMillis()}",
                    )
                    try {
                        skill.execute(capabilityId, params, ctx)
                    } catch (t: Throwable) {
                        Log.e(
                            TAG,
                            "local skill threw skillId=$skillId capability=$capabilityId",
                            t,
                        )
                        SkillResult.error(t.message ?: t.javaClass.simpleName)
                    }
                }
                postStatus(
                    "LocalAction done ok=${result.ok}" +
                        (result.message?.let { " · $it" } ?: ""),
                )
            }
        }
    }

    private fun handleBrainFailure(t: Throwable, phase: String) {
        if (t is HttpEdgeException && t.httpCode == 401) {
            clearAssignedEdgeId()
            postStatus("Brain 不认可 edgeId，已清除，将重新 register")
            Log.w(TAG, "$phase 401", t)
            return
        }
        postStatus("Brain $phase failed: ${t.message}")
        Log.e(TAG, "$phase failed", t)
    }

    private fun recordOnlineHeartbeatSuccess() {
        settings.recordHeartbeatSuccess()
        val count = settings.heartbeatSuccessCount
        val at = settings.lastHeartbeatSuccessAtMs
        scope.launch {
            listener?.onHeartbeatStatsChanged(count, at)
        }
    }

    private fun postStatus(message: String) {
        scope.launch {
            listener?.onStatus(message)
        }
    }

    /** Used by CommandHandler to surface pipeline logs on the UI. */
    fun pipelineLog(message: String) {
        scope.launch {
            listener?.onCommandPipelineLog(message)
        }
    }

    companion object {
        private const val TAG = "EdgeAgent"

        fun defaultIdentity(clientHint: String, appVersion: String?): EdgeIdentity =
            EdgeIdentity(
                clientHint = clientHint,
                displayName = "客厅 · Android Edge",
                deviceType = EdgeDeviceType.ANDROID,
                room = "living-room",
                appVersion = appVersion,
            )
    }
}
