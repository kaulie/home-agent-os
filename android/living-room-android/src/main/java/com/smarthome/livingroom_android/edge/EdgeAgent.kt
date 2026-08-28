package com.smarthome.livingroom_android.edge

import android.content.Context
import android.util.Log
import com.smarthome.livingroom_android.brain.BrainClient
import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.brain.CompositeBrainClient
import com.smarthome.livingroom_android.brain.HttpEdgeException
import com.smarthome.livingroom_android.brain.ParticipantStore
import com.smarthome.livingroom_android.brain.dto.EdgeDeviceType
import com.smarthome.livingroom_android.brain.dto.EdgeHealthSnapshot
import com.smarthome.livingroom_android.brain.dto.EdgeHealthStatus
import com.smarthome.livingroom_android.brain.dto.EdgeIdentity
import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.EdgeOnlineStatus
import com.smarthome.livingroom_android.brain.dto.EdgeRegisterRequest
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.brain.dto.ParticipantWire
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.command.CommandHandler
import com.smarthome.livingroom_android.command.HttpCommandSource
import com.smarthome.livingroom_android.command.IntentPipeline
import com.smarthome.livingroom_android.command.IntentsPullSnapshot
import com.smarthome.livingroom_android.command.runtime.LocalEdgeRuntime
import com.smarthome.livingroom_android.data.AppSettings
import com.smarthome.livingroom_android.data.EdgeIdStore
import com.smarthome.livingroom_android.data.RuntimeIdStore
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
    private val participant: ParticipantStore,
) {
    interface Listener {
        fun onStatus(message: String)
        fun onReport(report: ExecutionReport)
        fun onEdgeIdAssigned(edgeId: String) {}
        fun onEdgeInfoReported(info: EdgeNodeInfo) {}
        fun onHeartbeatStatsChanged(successCount: Long, lastSuccessAtMs: Long) {}
        /** Per-Brain heartbeat result (LAN or Cloud base URL). roles is the payload sent, only on success. */
        fun onBrainHeartbeat(baseUrl: String, ok: Boolean, error: String, roles: List<String>? = null) {}
        /** attempt 0 = idle, 1 = 发送中, 2..max = 重试 n/max. */
        fun onBrainHeartbeatPhase(baseUrl: String, attempt: Int, maxAttempts: Int) {}
        /** Wall time of the next scheduled heartbeat tick (countdown). */
        fun onHeartbeatScheduled(nextAtMs: Long) {}
        /** Per-Brain register success (LAN or Cloud base URL). */
        fun onBrainRegistered(baseUrl: String) {}
        /** CommandHandler / Agent pipeline lines for the run-log panel. */
        fun onCommandPipelineLog(message: String) {}
        /** Latest intents poll (including empty queue) for the snapshot panel. */
        fun onIntentsPulled(snapshot: IntentsPullSnapshot) {}
    }

    private val settings = AppSettings(appContext)

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val pollMutex = Mutex()
    private var loopJob: Job? = null
    private var pullJob: Job? = null
    @Volatile
    var nextHeartbeatAtMs: Long = 0L
        private set

    @Volatile
    var assignedEdgeId: String? = EdgeIdStore.load(appContext)
        private set

    /** P0: stable Runtime Identity, client-supplied (persisted, smooth migration from edge_id). */
    private val runtimeId: String = RuntimeIdStore.ensure(appContext)

    /** P0 Capability Exposure Policy (null = open). */
    private val exposurePolicy: Map<String, List<String>>? get() = settings.exposurePolicy()

    /** Effective id: Brain-issued if present, else clientHint (UI only until register). */
    val edgeId: String
        get() = assignedEdgeId?.takeIf { it.isNotBlank() } ?: identity.clientHint

    val hasCachedEdgeId: Boolean
        get() = !assignedEdgeId.isNullOrBlank()

    init {
        val composite = brain as? CompositeBrainClient
        composite?.onBrainHeartbeat = { base, ok, error, roles ->
            if (ok && roles != null) {
                persistReportedRoles(base, roles)
            }
            scope.launch { listener?.onBrainHeartbeat(base, ok, error, roles) }
        }
        composite?.onBrainHeartbeatPhase = { base, attempt, maxAttempts ->
            scope.launch { listener?.onBrainHeartbeatPhase(base, attempt, maxAttempts) }
        }
        composite?.onBrainRegistered = { base ->
            scope.launch { listener?.onBrainRegistered(base) }
        }
    }

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
                }
            } catch (t: Throwable) {
                handleBrainFailure(t, phase = "register/heartbeat")
            }
            while (isActive && running) {
                val now = System.currentTimeMillis()
                nextHeartbeatAtMs = now + heartbeatIntervalMs
                listener?.onHeartbeatScheduled(nextHeartbeatAtMs)
                launch(Dispatchers.IO) { heartbeatTick() }
                delay(heartbeatIntervalMs)
            }
        }
        pullJob = scope.launch {
            while (isActive && running) {
                try {
                    withContext(Dispatchers.IO) {
                        pullAndHandleServerCommands()
                    }
                } catch (t: Throwable) {
                    Log.w(TAG, "intents pull failed: ${t.message}")
                }
                delay(heartbeatIntervalMs)
            }
        }
    }

    fun stop() {
        val wasRunning = running
        val hadId = assignedEdgeId != null
        running = false
        loopJob?.cancel()
        loopJob = null
        pullJob?.cancel()
        pullJob = null
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
        scope.launch {
            withContext(Dispatchers.IO) {
                runCatching { pullAndHandleServerCommands() }
            }
        }
    }

    fun clearAssignedEdgeId() {
        assignedEdgeId = null
        EdgeIdStore.clear(appContext)
        settings.lastRegisteredBrainUrl = ""
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
            val result = heartbeatNow()
            onDone(result.isSuccess, result.getOrElse { it.message ?: it.javaClass.simpleName })
        }
    }

    suspend fun heartbeatNow(): Result<String> = withContext(Dispatchers.IO) {
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
        }.also { result ->
            val ok = result.isSuccess
            val msg = result.getOrElse { it.message ?: it.javaClass.simpleName }
            postStatus(if (ok) msg else "心跳失败：$msg")
            if (!ok) {
                result.exceptionOrNull()?.let { handleBrainFailure(it, phase = "heartbeat") }
            }
        }
    }

    /**
     * Register with the Brain currently in [HttpEdgeReporter.baseURL].
     * Matches iOS `ensureRegistered`: skip when this URL already registered,
     * unless [force]. Switching LAN↔Cloud does **not** wipe the local edge id.
     */
    suspend fun registerNow(force: Boolean = false): Result<String> = withContext(Dispatchers.IO) {
        runCatching {
            val url = currentBrainIntentUrl()
            val cached = assignedEdgeId?.trim().orEmpty()
                .ifBlank { EdgeIdStore.load(appContext).orEmpty() }
            if (!force && cached.isNotBlank() && url.isNotBlank() &&
                settings.lastRegisteredBrainUrl == url
            ) {
                applyAssignedEdgeId(cached)
                notifyPrimaryRegistered()
                return@runCatching "已注册，复用本地 edge_id=$cached"
            }
            if (cached.isNotBlank()) applyAssignedEdgeId(cached)
            performRegisterWithBrain()
            if (url.isNotBlank()) settings.lastRegisteredBrainUrl = url
            "注册成功 edge_id=$assignedEdgeId"
        }
    }

    private fun currentBrainIntentUrl(): String {
        val base = (brain as? CompositeBrainClient)?.remote?.baseURL.orEmpty()
        return if (base.isBlank()) "" else BrainEndpoint.intentUrl(base)
    }

    private fun notifyPrimaryRegistered() {
        val base = (brain as? CompositeBrainClient)?.remote?.baseURL.orEmpty()
        if (base.isBlank()) return
        scope.launch { listener?.onBrainRegistered(base) }
    }

    private suspend fun ensureRegisteredWithBrain() {
        val url = currentBrainIntentUrl()
        val existing = assignedEdgeId?.trim().orEmpty()
            .ifBlank { EdgeIdStore.load(appContext).orEmpty() }
        if (existing.isNotEmpty() && url.isNotBlank() && settings.lastRegisteredBrainUrl == url) {
            applyAssignedEdgeId(existing)
            notifyPrimaryRegistered()
            postStatus("Reuse cached edge_id=$existing (skip register)")
            return
        }
        if (existing.isNotEmpty()) applyAssignedEdgeId(existing)
        performRegisterWithBrain()
        if (url.isNotBlank()) settings.lastRegisteredBrainUrl = url
    }

    private suspend fun performRegisterWithBrain() {
        val roles = participant.enabledRoles()
        val request = EdgeRegisterRequest(
            clientHint = identity.clientHint,
            displayName = identity.displayName,
            deviceType = identity.deviceType,
            room = identity.room,
            services = participant.advertisedServices(roles, registry.services()),
            appVersion = identity.appVersion,
            location = identity.location,
            roles = roles,
            intentSources = participant.intentSources(roles),
            endpoints = participant.endpoints(roles),
            // P0: client-supplied identity is authoritative. Send runtime_id as
            // participant_id so the Brain creates/updates this exact id (no hint rebind).
            participantId = assignedEdgeId ?: runtimeId,
            runtimeId = runtimeId,
            exposurePolicy = exposurePolicy,
        )
        postStatus("Registering with Brain…")
        val response = brain.registerEdge(request)
        if (!response.isApproved) {
            val detail = response.message.ifEmpty { response.status }
            throw IllegalStateException(
                "Brain register ${response.status.ifEmpty { "failed" }}: $detail",
            )
        }
        applyAssignedEdgeId(response.edgeId)
        // Keep runtime_id store in sync with the Brain-returned id (should equal runtimeId).
        if (response.edgeId != runtimeId) {
            RuntimeIdStore.save(appContext, response.edgeId)
        }
        settings.registeredAtMs = System.currentTimeMillis()
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

    suspend fun buildNodeInfo(online: EdgeOnlineStatus): EdgeNodeInfo {
        val health = if (online == EdgeOnlineStatus.OFFLINE) {
            EdgeHealthSnapshot(status = EdgeHealthStatus.UNKNOWN, summary = "agent stopped")
        } else {
            EdgeHealthSnapshot(
                status = if (running) EdgeHealthStatus.HEALTHY else EdgeHealthStatus.UNKNOWN,
                summary = if (running) "agent running" else "agent idle",
            )
        }
        val roles = participant.enabledRoles()
        val services = participant.advertisedServices(roles, registry.services())
        // P0: heartbeat carries an availability snapshot (Runtime IsAvailable()).
        val snapshotted = if (online == EdgeOnlineStatus.ONLINE) {
            availabilitySnapshot(services)
        } else {
            services
        }
        return EdgeNodeInfo(
            edgeId = edgeId,
            displayName = identity.displayName,
            deviceType = identity.deviceType,
            room = identity.room,
            onlineStatus = online,
            health = health,
            services = snapshotted,
            appVersion = identity.appVersion,
            location = identity.location,
            roles = roles,
            intentSources = participant.intentSources(roles),
            endpoints = participant.endpoints(roles),
            participantId = assignedEdgeId ?: edgeId,
            runtimeId = runtimeId,
            exposurePolicy = exposurePolicy,
        )
    }

    /**
     * P0: probe each declared capability via its Skill.isAvailable() and inject
     * {available, observed_at}. DECLARED-but-unavailable caps stay advertised
     * (Brain keeps the Declaration) but carry available=false so the schedulable
     * map filters them out. Probes are best-effort; failures default to available.
     */
    private suspend fun availabilitySnapshot(services: List<ServiceDescriptor>): List<ServiceDescriptor> {
        val ctx = SkillContext(
            appContext = appContext,
            edgeId = edgeId,
            planId = "availability-probe",
            stepId = "probe-${System.currentTimeMillis()}",
        )
        val probed = services.map { svc ->
            val owner = registry.get(svc.serviceId)
            val probedCaps = svc.capabilities.map { cap ->
                val probe = runCatching {
                    owner?.isAvailable(cap.capabilityId, emptyMap(), ctx)
                }.getOrNull()
                val ok = probe?.ok ?: true
                val now = System.currentTimeMillis() / 1000.0
                cap.copy(
                    available = ok,
                    observedAt = now,
                    unavailableReason = if (ok) null else (probe?.message ?: "unavailable"),
                )
            }
            svc.copy(capabilities = probedCaps)
        }
        val availByService = probed.associate { svc ->
            svc.serviceId to svc.capabilities.associate { cap ->
                cap.capabilityId to (cap.available ?: true)
            }
        }
        val availAny = mutableMapOf<String, Boolean>()
        for (svc in probed) {
            for (cap in svc.capabilities) {
                val ok = cap.available ?: true
                availAny[cap.capabilityId] = availAny[cap.capabilityId] == true || ok
            }
        }
        return probed.map { svc ->
            val own = availByService[svc.serviceId].orEmpty()
            svc.copy(
                capabilities = svc.capabilities.map { cap ->
                    if (cap.composition != "composite" || cap.decomposesTo.isEmpty()) {
                        cap
                    } else {
                        val atomOk = cap.decomposesTo.all { atom ->
                            own[atom] ?: (availAny[atom] == true)
                        }
                        if (atomOk && (cap.available ?: true)) {
                            cap
                        } else {
                            cap.copy(
                                available = false,
                                unavailableReason = cap.unavailableReason
                                    ?: "composite atomics unavailable",
                            )
                        }
                    }
                },
            )
        }
    }

    /**
     * Re-run Runtime [Skill.isAvailable] for every advertised capability (same logic
     * as heartbeat snapshot). Does not POST edge-heartbeat — for Console UI refresh.
     */
    suspend fun probeCapabilityAvailability(): List<ServiceDescriptor> {
        val roles = participant.enabledRoles()
        if (!roles.contains(ParticipantWire.ROLE_RUNTIME)) {
            return emptyList()
        }
        val services = participant.advertisedServices(roles, registry.services())
        return availabilitySnapshot(services)
    }

    private suspend fun heartbeatTick() {
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
        }.onFailure { t ->
            handleBrainFailure(t, phase = "heartbeat")
        }
    }

    private suspend fun pullAndHandleServerCommands() {
        pollMutex.withLock {
            pullAndHandleServerCommandsLocked()
        }
    }

    private suspend fun pullAndHandleServerCommandsLocked() {
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

    /** Manual pull now (same path as the pull loop). */
    fun pullIntentsNow() {
        scope.launch {
            withContext(Dispatchers.IO) {
                runCatching { pullAndHandleServerCommands() }
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
                        val avail = skill.isAvailable(capabilityId, params, ctx)
                        if (!avail.ok) {
                            SkillResult.error(avail.message ?: "$capabilityId unavailable")
                        } else {
                            skill.execute(capabilityId, params, ctx)
                        }
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

    private fun persistReportedRoles(baseUrl: String, roles: List<String>) {
        val mode = modeForBaseUrl(baseUrl)
        settings.setLastReportedRoles(mode, roles)
        val primary = (brain as? CompositeBrainClient)?.remote?.baseURL
            ?.let { BrainEndpoint.normalizeBase(it) }
            .orEmpty()
        if (primary.isNotEmpty() && BrainEndpoint.normalizeBase(baseUrl) == primary) {
            settings.lastReportedRoles = roles
        }
    }

    private fun modeForBaseUrl(baseUrl: String): BrainEndpoint.Mode {
        val root = BrainEndpoint.normalizeBase(baseUrl)
        val cloud = BrainEndpoint.normalizeBase(settings.cloudBrainUrl)
        return if (root == cloud) BrainEndpoint.Mode.CLOUD else BrainEndpoint.Mode.LAN
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
                displayName = "客厅 Android",
                deviceType = EdgeDeviceType.ANDROID,
                room = "living-room",
                appVersion = appVersion,
            )
    }
}
