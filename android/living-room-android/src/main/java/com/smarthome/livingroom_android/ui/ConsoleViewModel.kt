package com.smarthome.livingroom_android.ui

import android.app.Application
import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.smarthome.livingroom_android.app.LivingRoomAndroidApp
import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.brain.BrainNetworkEnvironment
import com.smarthome.livingroom_android.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.command.IntentsPullSnapshot
import com.smarthome.livingroom_android.data.HouseholdDirectory
import com.smarthome.livingroom_android.data.HouseholdPerson
import com.smarthome.livingroom_android.edge.EdgeAgent
import com.smarthome.livingroom_android.intent.ClockSyncSample
import android.net.Uri
import com.smarthome.livingroom_android.intent.IntentApi
import com.smarthome.livingroom_android.intent.IntentDetail
import com.smarthome.livingroom_android.intent.LocalUploads
import com.smarthome.livingroom_android.media.AudioPreviewStore
import com.smarthome.livingroom_android.media.LocalAudioPlayer
import com.smarthome.livingroom_android.media.LocalAudioRecorder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import com.smarthome.livingroom_android.intent.IntentJourney
import com.smarthome.livingroom_android.intent.IntentPhase
import com.smarthome.livingroom_android.intent.IntentPresentation
import com.smarthome.livingroom_android.intent.PhaseRow
import com.smarthome.livingroom_android.intent.PhaseVisual
import com.smarthome.livingroom_android.scan.ScanCapture
import com.smarthome.livingroom_android.scan.ScanPreviewStore
import com.smarthome.livingroom_android.skill.CaptureStore
import com.smarthome.livingroom_android.skill.LocalCaptureAssets
import com.smarthome.livingroom_android.service.EdgeAgentController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import kotlin.math.max

enum class PhotoUploadState {
    NONE,
    UPLOADING,
    UPLOADED,
    FAILED,
}

data class ChatTurn(
    val id: String,
    val intentId: String,
    val createdAtMs: Long,
    val userText: String,
    val source: String,
    val journey: IntentJourney,
    val assistantText: String?,
    val awaitingTerminal: Boolean,
    val presentation: IntentPresentation? = null,
    val error: String? = null,
    val inputAssetId: String? = null,
    val localCaptureId: String? = null,
    val uploadState: PhotoUploadState = PhotoUploadState.NONE,
) {
    val isDocumentScan: Boolean get() = source == Capabilities.DOCUMENT_SCAN
    val isAndroidPhoto: Boolean get() = source == LocalUploads.PHOTO
    val isAndroidFile: Boolean get() = source == LocalUploads.FILE
    val isAndroidAudio: Boolean get() = source == LocalUploads.AUDIO
    val isLocalInbox: Boolean
        get() = isDocumentScan || isAndroidPhoto || isAndroidFile || isAndroidAudio
}

class ConsoleViewModel(application: Application) : AndroidViewModel(application), EdgeAgent.Listener {
    private val app = LivingRoomAndroidApp.instance
    private val api = app.intentApi
    private val cm = application.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    val turns = mutableStateListOf<ChatTurn>()
    val previewImages = mutableStateMapOf<String, ByteArray>()
    val previewFailed = mutableStateMapOf<String, Boolean>()
    val originalImages = mutableStateMapOf<String, ByteArray>()
    val feedbackDone = mutableStateMapOf<String, Boolean>()
    val scanPreviewBytes = mutableStateMapOf<String, ByteArray>()

    var historyNotice by mutableStateOf("")
        private set
    var historyExhausted by mutableStateOf(false)
        private set
    var historyLoading by mutableStateOf(false)
        private set
    private var nextBeforeId: Int? = null

    var lanBrainUrl by mutableStateOf(app.settings.lanBrainUrl)
    var cloudBrainUrl by mutableStateOf(app.settings.cloudBrainUrl)
    var brainRouting by mutableStateOf(app.settings.brainRouting)
    var brainEnv by mutableStateOf(BrainNetworkEnvironment())
        private set
    var intentServerUrl by mutableStateOf(BrainEndpoint.intentUrl(app.settings.cloudBrainUrl))
        private set

    var enabledRoles by mutableStateOf(app.settings.enabledRoles)
        private set
    var lastReportedRoles by mutableStateOf(app.settings.lastReportedRoles)
        private set
    var participantId by mutableStateOf(app.edgeAgent.assignedEdgeId.orEmpty())
        private set
    var clientHint by mutableStateOf(app.clientHint)
        private set
    var registeredAtMs by mutableStateOf(app.settings.registeredAtMs)
        private set
    var lastHeartbeatAtMs by mutableStateOf(0L)
        private set
    var lastHeartbeatOk by mutableStateOf(false)
        private set
    var lastHeartbeatError by mutableStateOf("")
        private set
    var lastHeartbeatSuccessAtMs by mutableStateOf(app.settings.lastHeartbeatSuccessAtMs)
        private set
    var heartbeatIntervalMs: Long = 30_000L
    var nextHeartbeatAtMs by mutableStateOf(0L)
        private set
    var agentRunning by mutableStateOf(app.edgeAgent.running)
        private set
    var autoStartOnBoot by mutableStateOf(app.settings.autoStartOnBoot)

    var clockSync by mutableStateOf<ClockSyncSample?>(null)
        private set
    var clockSyncBusy by mutableStateOf(false)
        private set
    var clockSyncError by mutableStateOf("")
        private set
    var statusLine by mutableStateOf("")
        private set

    var sendHint by mutableStateOf("")

    var scanBusy by mutableStateOf(false)
        private set
    var scanHint by mutableStateOf("")
        private set
    var photoHint by mutableStateOf("")
        private set
    var fileBusy by mutableStateOf(false)
        private set
    var fileHint by mutableStateOf("")
        private set
    var fileUploadingName by mutableStateOf("")
        private set
    var audioBusy by mutableStateOf(false)
        private set
    var audioHint by mutableStateOf("")
        private set
    var audioTitle by mutableStateOf("录音")

    val audioRecorder = LocalAudioRecorder(application)
    val audioPlayer = LocalAudioPlayer()

    var audioClockMs by mutableStateOf(0L)
        private set
    var playingAudioAssetId by mutableStateOf<String?>(null)
        private set
    var audioPlaybackPaused by mutableStateOf(false)
        private set
    private var audioClockJob: Job? = null

    var householdPeople by mutableStateOf(HouseholdDirectory.parse(app.settings.householdDirectoryJson))
        private set

    private var networkCallback: ConnectivityManager.NetworkCallback? = null
    private val pollJobs = mutableMapOf<String, Job>()
    private val resolveMutex = Mutex()
    private var bound = false
    @Volatile
    private var coldBootstrapRunning = true

    fun bind() {
        if (bound) {
            onForeground()
            return
        }
        bound = true
        app.edgeAgent.listener = this
        agentRunning = app.edgeAgent.running
        participantId = app.edgeAgent.assignedEdgeId.orEmpty()
        audioPlayer.onStopped = {
            playingAudioAssetId = null
            audioPlaybackPaused = false
        }
        restoreLocalScans()
        startPathMonitor()
        viewModelScope.launch {
            resolveBrainEndpoint(reregister = false)
            if (!app.edgeAgent.running) {
                EdgeAgentController.requestStart(getApplication(), reason = "console")
            }
            app.edgeAgent.registerNow(force = true)
            app.edgeAgent.heartbeatNow()
            coldBootstrapRunning = false
        }
    }

    fun onForeground() {
        if (coldBootstrapRunning) return
        viewModelScope.launch {
            resolveBrainEndpoint(reregister = true)
            catchUpHeartbeatIfOverdue()
        }
    }

    override fun onCleared() {
        networkCallback?.let { runCatching { cm.unregisterNetworkCallback(it) } }
        if (app.edgeAgent.listener === this) app.edgeAgent.listener = null
        audioPlayer.stop()
        audioRecorder.discard()
        super.onCleared()
    }

    fun applyBrainRouting(routing: BrainEndpoint.Routing) {
        if (routing == brainRouting) return
        brainRouting = routing
        app.settings.brainRouting = routing
        viewModelScope.launch { resolveBrainEndpoint(reregister = true) }
    }

    fun applyPinnedBrainUrls() {
        app.settings.lanBrainUrl = lanBrainUrl
        app.settings.cloudBrainUrl = cloudBrainUrl
        app.settings.brainRouting = brainRouting
        viewModelScope.launch { resolveBrainEndpoint(reregister = true) }
    }

    fun predictedBrainMode(routing: BrainEndpoint.Routing): BrainEndpoint.Mode {
        return when (routing) {
            BrainEndpoint.Routing.LAN -> BrainEndpoint.Mode.LAN
            BrainEndpoint.Routing.CLOUD -> BrainEndpoint.Mode.CLOUD
            BrainEndpoint.Routing.AUTO -> when (brainEnv.lanProbeOk) {
                true -> BrainEndpoint.Mode.LAN
                false -> BrainEndpoint.Mode.CLOUD
                null -> if (brainEnv.looksOnHomeLAN) BrainEndpoint.Mode.LAN else BrainEndpoint.Mode.CLOUD
            }
        }
    }

    fun predictedBrainBase(routing: BrainEndpoint.Routing): String {
        return if (predictedBrainMode(routing) == BrainEndpoint.Mode.LAN) {
            BrainEndpoint.displayBase(lanBrainUrl)
        } else {
            BrainEndpoint.displayBase(cloudBrainUrl)
        }
    }

    fun setRole(role: String, enabled: Boolean) {
        app.participant.setRole(role, enabled)
        enabledRoles = app.settings.enabledRoles
    }

    fun setAutoStart(enabled: Boolean) {
        autoStartOnBoot = enabled
        app.settings.autoStartOnBoot = enabled
        if (enabled) EdgeAgentController.requestStart(getApplication(), "auto_start")
    }

    fun startAgent() = EdgeAgentController.requestStart(getApplication(), "manual")

    fun stopAgent() = EdgeAgentController.requestStop(getApplication(), "manual")

    fun clearEdgeId() {
        app.edgeAgent.clearAssignedEdgeId()
        app.settings.registeredAtMs = 0L
        participantId = ""
        registeredAtMs = 0L
    }

    fun advertisedServices(): List<ServiceDescriptor> =
        app.participant.advertisedServices(enabledRoles, app.registry.services())

    /** Auto: LAN when `/api/v1/ping` succeeds, else Cloud. Forced LAN / Cloud skip that choice. */
    suspend fun resolveBrainEndpoint(reregister: Boolean) {
        resolveMutex.withLock {
            brainEnv = brainEnv.copy(resolveBusy = true)
            try {
                val routing = brainRouting
                val lanIntent = BrainEndpoint.intentUrl(lanBrainUrl)
                val cloudIntent = BrainEndpoint.intentUrl(cloudBrainUrl)
                val looksLAN = brainEnv.looksOnHomeLAN
                var probeOk: Boolean? = null
                var probeDetail = ""
                val shouldProbeLan = routing != BrainEndpoint.Routing.CLOUD &&
                    (looksLAN || routing == BrainEndpoint.Routing.LAN)
                if (shouldProbeLan) {
                    val ping = api.ping(lanIntent, timeoutSec = 2)
                    probeOk = ping.ok
                    probeDetail = if (ping.ok) "" else ping.error.ifBlank { "LAN 探测失败" }
                } else if (routing == BrainEndpoint.Routing.CLOUD) {
                    probeDetail = "已强制走云 Brain，跳过 LAN 探测"
                } else {
                    probeOk = false
                    probeDetail = "当前不是家庭局域网，跳过 LAN 探测"
                }
                val useLan = when (routing) {
                    BrainEndpoint.Routing.LAN -> true
                    BrainEndpoint.Routing.CLOUD -> false
                    BrainEndpoint.Routing.AUTO -> probeOk == true
                }
                val next = if (useLan) lanIntent else cloudIntent
                val changed = next != intentServerUrl
                intentServerUrl = next
                val base = BrainEndpoint.displayBase(next)
                app.applyBrainBase(base)
                brainEnv = brainEnv.copy(
                    routing = routing,
                    lanProbeOk = probeOk,
                    lanProbeDetail = probeDetail,
                    mode = if (useLan) BrainEndpoint.Mode.LAN else BrainEndpoint.Mode.CLOUD,
                    activeIntentUrl = next,
                    resolveBusy = false,
                )
                if (reregister && changed && !coldBootstrapRunning) {
                    app.edgeAgent.registerNow(force = true)
                }
            } finally {
                if (brainEnv.resolveBusy) {
                    brainEnv = brainEnv.copy(resolveBusy = false)
                }
            }
        }
    }

    fun sendIntent(text: String, source: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty()) {
            sendHint = "请先输入文字或完成语音识别"
            return
        }
        sendHint = ""
        val turnId = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()
        val pending = ChatTurn(
            id = turnId,
            intentId = "pending…",
            createdAtMs = now,
            userText = trimmed,
            source = source,
            journey = placeholderJourney("pending…", trimmed, IntentPhase.UPLOADED, now),
            assistantText = null,
            awaitingTerminal = true,
        )
        turns.add(pending)
        viewModelScope.launch {
            resolveBrainEndpoint(reregister = true)
            if (!app.edgeAgent.running) {
                EdgeAgentController.requestStart(getApplication(), "send")
                delay(400)
            }
            app.edgeAgent.registerNow(force = false)
            val beat = app.edgeAgent.heartbeatNow()
            if (beat.isFailure) {
                failTurn(turnId, beat.exceptionOrNull()?.message ?: "发出前心跳失败")
                return@launch
            }
            val result = api.submit(
                intentUrl = intentServerUrl,
                text = trimmed,
                source = source,
                clientHint = clientHint,
                participantId = app.edgeAgent.assignedEdgeId ?: participantId,
            )
            if (!result.ok || result.intentId.isNullOrBlank()) {
                failTurn(turnId, result.message.ifBlank { "发出失败" })
                return@launch
            }
            val id = result.intentId
            val phase = IntentPhase.fromWire(result.status) ?: IntentPhase.UPLOADED
            updateTurn(turnId) { turn ->
                turn.copy(
                    intentId = id,
                    journey = placeholderJourney(id, trimmed, phase, turn.createdAtMs, result.detail),
                    presentation = result.detail?.presentation,
                    awaitingTerminal = phase.isTerminal.not(),
                    assistantText = assistantText(phase, result.detail),
                )
            }
            if (!phase.isTerminal) startPolling(turnId, id)
        }
    }

    fun refreshTurnProgress(turnId: String) {
        val turn = turns.firstOrNull { it.id == turnId } ?: return
        if (turn.intentId.toIntOrNull() == null) return
        viewModelScope.launch {
            val result = api.fetchDetail(intentServerUrl, turn.intentId)
            result.detail?.let { applyDetail(turnId, it) }
        }
    }

    fun loadOlderHistory() {
        val pid = (app.edgeAgent.assignedEdgeId ?: participantId).trim()
        if (pid.isEmpty() || historyLoading || historyExhausted) {
            if (pid.isEmpty()) historyNotice = "尚未注册，无法加载历史"
            return
        }
        historyLoading = true
        viewModelScope.launch {
            val page = api.fetchHistory(intentServerUrl, pid, nextBeforeId)
            historyLoading = false
            historyExhausted = page.exhausted
            nextBeforeId = page.nextBeforeId
            val existing = turns.map { it.intentId }.toSet()
            val incoming = page.details
                .filter { it.intentId !in existing }
                .map { it.toChatTurn() }
                .sortedBy { it.createdAtMs }
            if (incoming.isEmpty()) {
                historyNotice = if (page.exhausted) "没有更早的历史" else "没有新的历史"
            } else {
                historyNotice = "加载了 ${incoming.size} 条历史"
                turns.addAll(0, incoming)
            }
        }
    }

    fun syncClock() {
        clockSyncBusy = true
        clockSyncError = ""
        val localAt = System.currentTimeMillis()
        clockSync = ClockSyncSample(localAtMs = localAt)
        viewModelScope.launch {
            val ping = api.ping(intentServerUrl, timeoutSec = 10)
            clockSyncBusy = false
            if (!ping.ok) {
                clockSyncError = ping.error
                return@launch
            }
            clockSync = ClockSyncSample(
                localAtMs = localAt,
                serverAtMs = ping.serverTimeMs,
                skewMs = ping.skewMs,
            )
        }
    }

    fun loadPreview(intentId: String, assetId: String) {
        val key = "$assetId|$intentId|preview"
        if (previewImages.containsKey(key) || previewFailed[key] == true) return
        LocalCaptureAssets.bytes(assetId)?.let {
            previewImages[key] = it
            return
        }
        viewModelScope.launch {
            val bytes = api.fetchAssetBytes(intentServerUrl, assetId, intentId, "preview")
            if (bytes != null) {
                previewImages[key] = bytes
            } else {
                previewFailed[key] = true
            }
        }
    }

    fun loadOriginal(intentId: String, assetId: String, onReady: (ByteArray?) -> Unit) {
        val key = "$assetId|$intentId|original"
        originalImages[key]?.let { onReady(it); return }
        viewModelScope.launch {
            val bytes = api.fetchAssetBytes(intentServerUrl, assetId, intentId, "original")
            if (bytes != null) originalImages[key] = bytes
            onReady(bytes)
        }
    }

    fun submitFeedback(intentId: String, understanding: String, speed: String) {
        val pid = (app.edgeAgent.assignedEdgeId ?: participantId).trim()
        viewModelScope.launch {
            val ok = api.submitFeedback(intentServerUrl, intentId, pid, understanding, speed)
            if (ok) feedbackDone[intentId] = true
        }
    }

    fun updateScanHint(message: String) {
        scanHint = message
    }

    fun runLocalDocumentScan() {
        if (scanBusy) return
        if (intentServerUrl.isBlank()) {
            scanHint = "请先在设置里填写 Brain URL"
            return
        }
        scanBusy = true
        scanHint = ""
        viewModelScope.launch {
            try {
                val jpeg = ScanCapture.captureJpeg()
                val pid = (app.edgeAgent.assignedEdgeId ?: participantId).trim().ifEmpty { clientHint }
                val uploaded = api.uploadAsset(
                    intentUrl = intentServerUrl,
                    jpeg = jpeg,
                    uploadIntent = Capabilities.DOCUMENT_SCAN,
                    participantId = pid,
                )
                ScanPreviewStore.save(getApplication(), uploaded.assetId, jpeg)
                scanPreviewBytes[uploaded.assetId] = jpeg
                val now = System.currentTimeMillis()
                turns.add(
                    ChatTurn(
                        id = UUID.randomUUID().toString(),
                        intentId = "scan-${uploaded.assetId}",
                        createdAtMs = now,
                        userText = "扫描",
                        source = Capabilities.DOCUMENT_SCAN,
                        journey = placeholderJourney(
                            "scan-${uploaded.assetId}",
                            "扫描",
                            IntentPhase.SUCCEEDED,
                            now,
                        ),
                        assistantText = "已上传扫描图 asset_id=${uploaded.assetId}",
                        awaitingTerminal = false,
                        inputAssetId = uploaded.assetId,
                    ),
                )
                persistLocalScans()
            } catch (_: ScanCapture.Cancelled) {
                // user cancelled the system scanner
            } catch (t: Throwable) {
                scanHint = t.message ?: "扫描失败"
            } finally {
                scanBusy = false
            }
        }
    }

    fun updatePhotoHint(message: String) {
        photoHint = message
    }

    fun updateFileHint(message: String) {
        fileHint = message
    }

    fun updateAudioHint(message: String) {
        audioHint = message
    }

    // 拍摄动作（CameraX 已出图）与上传彻底分离：先落本机 inbox 并立即上列表，
    // 上传作为后台异步任务自动触发，不阻塞下一次拍照；上传失败只标记该照片，可重试。
    fun onLocalPhotoCaptured(jpeg: ByteArray) {
        if (intentServerUrl.isBlank()) {
            photoHint = "请先在设置里填写 Brain URL"
            return
        }
        if (jpeg.isEmpty()) {
            photoHint = "拍照失败：空图片"
            return
        }
        photoHint = ""
        viewModelScope.launch {
            val captureId = try {
                withContext(Dispatchers.IO) {
                    CaptureStore.put(
                        getApplication(),
                        jpeg,
                        originalName = "photo_${System.currentTimeMillis()}.jpg",
                        source = "phone",
                    ).captureId
                }
            } catch (t: Throwable) {
                photoHint = t.message ?: "拍照失败：无法写入本机 inbox。"
                return@launch
            }
            val turnId = appendCapturedPhotoTurn(captureId, jpeg)
            uploadCapturedPhoto(turnId, captureId, jpeg)
        }
    }

    fun retryPhotoUpload(turnId: String) {
        val turn = turns.firstOrNull { it.id == turnId } ?: return
        if (!turn.isAndroidPhoto) return
        if (turn.uploadState == PhotoUploadState.UPLOADING) return
        val captureId = turn.localCaptureId?.trim().orEmpty()
        if (captureId.isEmpty()) return
        updateTurn(turnId) {
            it.copy(
                uploadState = PhotoUploadState.UPLOADING,
                error = null,
                assistantText = "拍照成功，已存本机；正在上传…",
            )
        }
        viewModelScope.launch {
            val jpeg = withContext(Dispatchers.IO) {
                runCatching { CaptureStore.readBytes(getApplication(), captureId) }.getOrNull()
            } ?: scanPreviewBytes[captureId]
            if (jpeg == null) {
                updateTurn(turnId) {
                    it.copy(
                        uploadState = PhotoUploadState.FAILED,
                        error = "上传失败：本机 inbox 找不到该照片",
                        assistantText = "拍照成功，照片已存本机；但上传失败：本机 inbox 找不到该照片",
                    )
                }
                persistLocalScans()
                return@launch
            }
            uploadCapturedPhoto(turnId, captureId, jpeg)
        }
    }

    fun photoPreviewBytes(turn: ChatTurn): ByteArray? {
        turn.inputAssetId?.trim()?.takeIf { it.isNotEmpty() }?.let { aid ->
            scanPreviewBytes[aid]?.let { return it }
        }
        val cid = turn.localCaptureId?.trim().orEmpty()
        if (cid.isNotEmpty()) scanPreviewBytes[cid]?.let { return it }
        return null
    }

    private fun appendCapturedPhotoTurn(captureId: String, jpeg: ByteArray): String {
        val turnId = UUID.randomUUID().toString()
        val now = System.currentTimeMillis()
        scanPreviewBytes[captureId] = jpeg
        turns.add(
            ChatTurn(
                id = turnId,
                intentId = "photo-$captureId",
                createdAtMs = now,
                userText = "拍照",
                source = LocalUploads.PHOTO,
                journey = placeholderJourney("photo-$captureId", "拍照", IntentPhase.SUCCEEDED, now),
                assistantText = "拍照成功，已存本机；正在上传…",
                awaitingTerminal = false,
                localCaptureId = captureId,
                uploadState = PhotoUploadState.UPLOADING,
            ),
        )
        persistLocalScans()
        return turnId
    }

    private suspend fun uploadCapturedPhoto(turnId: String, captureId: String, jpeg: ByteArray) {
        try {
            val pid = (app.edgeAgent.assignedEdgeId ?: participantId).trim().ifEmpty { clientHint }
            val uploaded = api.uploadAsset(
                intentUrl = intentServerUrl,
                jpeg = jpeg,
                uploadIntent = LocalUploads.PHOTO,
                participantId = pid,
                fileName = "photo_${System.currentTimeMillis()}.jpg",
                failVerb = "上传",
                mimeType = "image/jpeg",
                assetType = "image",
            )
            withContext(Dispatchers.IO) {
                CaptureStore.markUploaded(getApplication(), captureId, "img_server")
                ScanPreviewStore.save(getApplication(), uploaded.assetId, jpeg)
            }
            scanPreviewBytes[uploaded.assetId] = jpeg
            updateTurn(turnId) { turn ->
                turn.copy(
                    intentId = "photo-${uploaded.assetId}",
                    inputAssetId = uploaded.assetId,
                    uploadState = PhotoUploadState.UPLOADED,
                    assistantText = "拍照成功，已上传 asset_id=${uploaded.assetId}",
                    error = null,
                )
            }
        } catch (t: Throwable) {
            val raw = t.message?.trim().orEmpty()
            val reason = when {
                raw.isEmpty() -> "上传失败"
                raw.contains("上传") -> raw
                else -> "上传失败：$raw"
            }
            updateTurn(turnId) { turn ->
                turn.copy(
                    uploadState = PhotoUploadState.FAILED,
                    error = reason,
                    assistantText = "拍照成功，照片已存本机；但$reason",
                )
            }
        }
        persistLocalScans()
    }

    fun uploadLocalFile(uri: Uri) {
        if (fileBusy) return
        if (intentServerUrl.isBlank()) {
            fileHint = "请先在设置里填写 Brain URL"
            return
        }
        fileBusy = true
        fileHint = ""
        viewModelScope.launch {
            try {
                val cr = getApplication<Application>().contentResolver
                val name = queryDisplayName(uri) ?: "file_${System.currentTimeMillis()}"
                val mime = cr.getType(uri)?.takeIf { it.isNotBlank() } ?: "application/octet-stream"
                fileUploadingName = name
                val bytes = cr.openInputStream(uri)?.use { it.readBytes() }
                    ?: error("读不到所选文件")
                if (bytes.isEmpty()) error("文件为空")
                val pid = (app.edgeAgent.assignedEdgeId ?: participantId).trim().ifEmpty { clientHint }
                val kind = IntentApi.guessAssetType(mime, name)
                val uploaded = api.uploadAsset(
                    intentUrl = intentServerUrl,
                    jpeg = bytes,
                    uploadIntent = LocalUploads.FILE,
                    participantId = pid,
                    fileName = IntentApi.sanitizeUploadName(name, "file.bin"),
                    failVerb = "文件",
                    mimeType = mime,
                    assetType = kind,
                )
                if (kind == "image") {
                    ScanPreviewStore.save(getApplication(), uploaded.assetId, bytes)
                    scanPreviewBytes[uploaded.assetId] = bytes
                }
                appendInboxTurn(
                    assetId = uploaded.assetId,
                    source = LocalUploads.FILE,
                    userText = name,
                    assistant = "已上传文件 asset_id=${uploaded.assetId} · $kind",
                    prefix = "file",
                )
            } catch (t: Throwable) {
                fileHint = t.message ?: "文件上传失败"
            } finally {
                fileBusy = false
                fileUploadingName = ""
            }
        }
    }

    fun startLocalAudio() {
        audioHint = ""
        if (audioRecorder.isActive) return
        audioPlayer.stop()
        audioTitle = defaultAudioTitle()
        if (!audioRecorder.start(audioTitle)) {
            audioHint = audioRecorder.lastError
            pulseAudioClock(false)
        } else {
            pulseAudioClock(true)
        }
    }

    fun pauseLocalAudio() {
        audioRecorder.pause()
        audioHint = audioRecorder.lastError
        pulseAudioClock(false)
    }

    fun resumeLocalAudio() {
        audioRecorder.resume()
        audioHint = audioRecorder.lastError
        if (audioRecorder.isRecording) pulseAudioClock(true)
    }

    fun onAudioPaneLeave() {
        if (audioRecorder.isRecording) stopAndUploadAudio()
    }

    fun playLocalAudio(assetId: String) {
        audioHint = ""
        if (audioRecorder.isActive) return
        val file = AudioPreviewStore.loadFile(getApplication(), assetId)
        if (file == null || !audioPlayer.play(file, assetId)) {
            audioHint = audioPlayer.lastError.ifEmpty { "本机没有这段录音" }
            playingAudioAssetId = null
            audioPlaybackPaused = false
        } else {
            playingAudioAssetId = assetId
            audioPlaybackPaused = false
        }
    }

    fun pauseLocalAudioPlayback() {
        audioPlayer.pause()
        audioPlaybackPaused = true
    }

    fun renameLocalAudio(turnId: String, name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) return
        val idx = turns.indexOfFirst { it.id == turnId }
        if (idx < 0) return
        val turn = turns[idx]
        if (!turn.isAndroidAudio) return
        turns[idx] = turn.copy(userText = trimmed)
        persistLocalScans()
    }

    fun stopAndUploadAudio() {
        pulseAudioClock(false)
        if (audioBusy) return
        val file = audioRecorder.stop()
        if (file == null) {
            audioHint = audioRecorder.lastError.ifEmpty { "没有可上传的录音" }
            return
        }
        if (intentServerUrl.isBlank()) {
            audioHint = "请先在设置里填写 Brain URL"
            file.delete()
            return
        }
        audioBusy = true
        audioHint = ""
        viewModelScope.launch {
            try {
                val bytes = file.readBytes()
                if (bytes.isEmpty()) error("录音为空")
                val pid = (app.edgeAgent.assignedEdgeId ?: participantId).trim().ifEmpty { clientHint }
                val title = IntentApi.sanitizeUploadName(audioTitle.ifBlank { defaultAudioTitle() }, "audio")
                val uploaded = api.uploadAsset(
                    intentUrl = intentServerUrl,
                    jpeg = bytes,
                    uploadIntent = LocalUploads.AUDIO,
                    participantId = pid,
                    fileName = "$title.m4a",
                    failVerb = "录音",
                    mimeType = "audio/mp4",
                    assetType = "audio",
                )
                AudioPreviewStore.save(getApplication(), uploaded.assetId, bytes, "m4a")
                appendInboxTurn(
                    assetId = uploaded.assetId,
                    source = LocalUploads.AUDIO,
                    userText = audioTitle.ifBlank { "录音" },
                    assistant = "已上传录音 asset_id=${uploaded.assetId}",
                    prefix = "audio",
                )
            } catch (t: Throwable) {
                audioHint = t.message ?: "录音上传失败"
            } finally {
                audioBusy = false
                runCatching { file.delete() }
            }
        }
    }

    private fun pulseAudioClock(running: Boolean) {
        if (!running) {
            audioClockJob?.cancel()
            audioClockJob = null
            audioClockMs = System.currentTimeMillis()
            return
        }
        if (audioClockJob?.isActive == true) return
        audioClockJob = viewModelScope.launch {
            while (true) {
                audioClockMs = System.currentTimeMillis()
                delay(200)
            }
        }
    }

    private fun appendInboxTurn(
        assetId: String,
        source: String,
        userText: String,
        assistant: String,
        prefix: String,
    ) {
        val now = System.currentTimeMillis()
        turns.add(
            ChatTurn(
                id = UUID.randomUUID().toString(),
                intentId = "$prefix-$assetId",
                createdAtMs = now,
                userText = userText,
                source = source,
                journey = placeholderJourney("$prefix-$assetId", userText, IntentPhase.SUCCEEDED, now),
                assistantText = assistant,
                awaitingTerminal = false,
                inputAssetId = assetId,
            ),
        )
        persistLocalScans()
    }

    private fun queryDisplayName(uri: Uri): String? {
        val cr = getApplication<Application>().contentResolver
        cr.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME)
                if (idx >= 0) return c.getString(idx)
            }
        }
        return uri.lastPathSegment
    }

    private fun defaultAudioTitle(): String =
        "录音_" + SimpleDateFormat("MMdd_HHmm", Locale.CHINA).format(Date())

    fun addHouseholdPerson(name: String, number: String) {
        val n = name.trim()
        val tel = number.trim()
        if (n.isEmpty() || tel.isEmpty()) return
        householdPeople = householdPeople + HouseholdPerson(n, tel)
        app.settings.householdDirectoryJson = HouseholdDirectory.encode(householdPeople)
    }

    fun removeHouseholdPerson(index: Int) {
        if (index !in householdPeople.indices) return
        householdPeople = householdPeople.toMutableList().also { it.removeAt(index) }
        app.settings.householdDirectoryJson = HouseholdDirectory.encode(householdPeople)
    }

    private fun restoreLocalScans() {
        val raw = app.settings.localScanHistoryJson
        val arr = runCatching { JSONArray(raw) }.getOrNull() ?: return
        val existing = turns.map { it.intentId }.toSet()
        for (i in 0 until arr.length()) {
            val o = arr.optJSONObject(i) ?: continue
            val aid = o.optString("asset_id").trim()
            val cid = o.optString("capture_id").trim()
            if (aid.isEmpty() && cid.isEmpty()) continue
            val source = o.optString("source").trim().ifEmpty { Capabilities.DOCUMENT_SCAN }
            val prefix = when (source) {
                LocalUploads.PHOTO -> "photo"
                LocalUploads.FILE -> "file"
                LocalUploads.AUDIO -> "audio"
                else -> "scan"
            }
            val intentId = o.optString("intent_id").trim().ifEmpty { "$prefix-${aid.ifEmpty { cid }}" }
            if (intentId in existing) continue
            val created = o.optLong("created_at_ms", System.currentTimeMillis())
            val userText = o.optString("user_text").trim().ifEmpty {
                when (source) {
                    LocalUploads.PHOTO -> "拍照"
                    LocalUploads.FILE -> "文件"
                    LocalUploads.AUDIO -> "录音"
                    else -> "扫描"
                }
            }
            if (aid.isNotEmpty()) {
                ScanPreviewStore.load(getApplication(), aid)?.let { scanPreviewBytes[aid] = it }
            } else if (cid.isNotEmpty()) {
                runCatching { CaptureStore.readBytes(getApplication(), cid) }.getOrNull()
                    ?.let { scanPreviewBytes[cid] = it }
            }
            // 上传状态只对照片有意义；崩溃/中断时 UPLOADING 一律诚实落成 FAILED（可重试）。
            val uploadState = if (source == LocalUploads.PHOTO) {
                when (o.optString("upload_state")) {
                    PhotoUploadState.UPLOADED.name -> PhotoUploadState.UPLOADED
                    PhotoUploadState.UPLOADING.name -> PhotoUploadState.FAILED
                    PhotoUploadState.FAILED.name -> PhotoUploadState.FAILED
                    else -> if (aid.isNotEmpty()) PhotoUploadState.UPLOADED else PhotoUploadState.FAILED
                }
            } else {
                PhotoUploadState.NONE
            }
            val fallbackAssistant = when {
                aid.isNotEmpty() -> "已上传 asset_id=$aid"
                source == LocalUploads.PHOTO -> "拍照成功，已存本机"
                else -> ""
            }
            turns.add(
                ChatTurn(
                    id = UUID.randomUUID().toString(),
                    intentId = intentId,
                    createdAtMs = created,
                    userText = userText,
                    source = source,
                    journey = placeholderJourney(intentId, userText, IntentPhase.SUCCEEDED, created),
                    assistantText = o.optString("assistant_text").ifBlank { fallbackAssistant },
                    awaitingTerminal = false,
                    inputAssetId = aid.ifEmpty { null },
                    localCaptureId = cid.ifEmpty { null },
                    uploadState = uploadState,
                ),
            )
        }
        turns.sortBy { it.createdAtMs }
    }

    private fun persistLocalScans() {
        val arr = JSONArray()
        turns.filter { it.isLocalInbox }.forEach { turn ->
            val aid = turn.inputAssetId?.trim().orEmpty()
            val cid = turn.localCaptureId?.trim().orEmpty()
            if (aid.isEmpty() && cid.isEmpty()) return@forEach
            arr.put(
                JSONObject()
                    .put("asset_id", aid)
                    .put("capture_id", cid)
                    .put("upload_state", turn.uploadState.name)
                    .put("intent_id", turn.intentId)
                    .put("source", turn.source)
                    .put("user_text", turn.userText)
                    .put("created_at_ms", turn.createdAtMs)
                    .put("assistant_text", turn.assistantText.orEmpty()),
            )
        }
        app.settings.localScanHistoryJson = arr.toString()
    }

    private fun startPolling(turnId: String, intentId: String) {
        pollJobs[turnId]?.cancel()
        pollJobs[turnId] = viewModelScope.launch {
            val started = System.currentTimeMillis()
            while (System.currentTimeMillis() - started < POLL_TIMEOUT_MS) {
                delay(POLL_INTERVAL_MS)
                val result = api.fetchDetail(intentServerUrl, intentId)
                val detail = result.detail ?: continue
                applyDetail(turnId, detail)
                val phase = IntentPhase.fromWire(detail.status)
                if (phase?.isTerminal == true) break
            }
            val turn = turns.firstOrNull { it.id == turnId } ?: return@launch
            if (turn.awaitingTerminal) {
                updateTurn(turnId) {
                    it.copy(
                        awaitingTerminal = false,
                        error = it.error ?: "等待超时，服务端尚未到达终态",
                        assistantText = it.assistantText ?: "等待超时，服务端尚未到达终态",
                    )
                }
            }
        }
    }

    private fun applyDetail(turnId: String, detail: IntentDetail) {
        val phase = IntentPhase.fromWire(detail.status) ?: IntentPhase.UPLOADED
        updateTurn(turnId) { turn ->
            turn.copy(
                intentId = detail.intentId,
                journey = placeholderJourney(
                    detail.intentId,
                    turn.userText.ifBlank { detail.text },
                    phase,
                    turn.createdAtMs,
                    detail,
                ),
                presentation = detail.presentation ?: turn.presentation,
                awaitingTerminal = !phase.isTerminal,
                assistantText = assistantText(phase, detail) ?: turn.assistantText,
                error = detail.error ?: turn.error,
            )
        }
        val pres = detail.presentation
        if (pres?.type == IntentPresentation.Kind.IMAGE && pres.assetId.isNotEmpty()) {
            loadPreview(detail.intentId, pres.assetId)
        }
    }

    private fun failTurn(turnId: String, message: String) {
        updateTurn(turnId) { turn ->
            turn.copy(
                awaitingTerminal = false,
                error = message,
                assistantText = message,
                journey = placeholderJourney(turn.intentId, turn.userText, IntentPhase.FAILED, turn.createdAtMs),
            )
        }
    }

    private fun updateTurn(turnId: String, transform: (ChatTurn) -> ChatTurn) {
        val idx = turns.indexOfFirst { it.id == turnId }
        if (idx >= 0) turns[idx] = transform(turns[idx])
    }

    private suspend fun catchUpHeartbeatIfOverdue() {
        val interval = heartbeatIntervalMs
        val now = System.currentTimeMillis()
        val overdue = when {
            nextHeartbeatAtMs > 0L -> nextHeartbeatAtMs <= now
            lastHeartbeatAtMs > 0L -> now - lastHeartbeatAtMs >= interval
            else -> true
        }
        if (!overdue) return
        nextHeartbeatAtMs = now + interval
        app.edgeAgent.heartbeatNow()
    }

    private fun startPathMonitor() {
        applyPath()
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                viewModelScope.launch { applyPath() }
            }
            override fun onLost(network: Network) {
                viewModelScope.launch { applyPath() }
            }
            override fun onCapabilitiesChanged(
                network: Network,
                networkCapabilities: NetworkCapabilities,
            ) {
                viewModelScope.launch { applyPath() }
            }
        }
        networkCallback = cb
        runCatching {
            cm.registerNetworkCallback(NetworkRequest.Builder().build(), cb)
        }
    }

    /**
     * Match iOS `NWPathMonitor`: Wi‑Fi counts even when the AP has no Internet
     * (GoPro hotspot). Prefer Wi‑Fi / wired over cellular if both are up.
     */
    private fun classifyPath(): BrainEndpoint.PathKind {
        var wifi = false
        var wired = false
        var cellular = false
        var any = false
        for (network in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(network) ?: continue
            any = true
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) wifi = true
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) wired = true
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) cellular = true
        }
        return when {
            wifi -> BrainEndpoint.PathKind.WIFI
            wired -> BrainEndpoint.PathKind.WIRED
            cellular -> BrainEndpoint.PathKind.CELLULAR
            any -> BrainEndpoint.PathKind.UNKNOWN
            else -> BrainEndpoint.PathKind.NONE
        }
    }

    private fun applyPath() {
        val kind = classifyPath()
        val looks = kind.looksOnHomeLAN
        val pathChanged = kind != brainEnv.pathKind
        brainEnv = brainEnv.copy(pathKind = kind, looksOnHomeLAN = looks)
        if (pathChanged && !coldBootstrapRunning) {
            viewModelScope.launch { resolveBrainEndpoint(reregister = true) }
        }
    }

    override fun onStatus(message: String) {
        statusLine = message
        agentRunning = app.edgeAgent.running
    }

    override fun onReport(report: ExecutionReport) {
        statusLine = report.message ?: report.status.name
    }

    override fun onEdgeIdAssigned(edgeId: String) {
        participantId = edgeId
        registeredAtMs = app.settings.registeredAtMs
    }

    override fun onEdgeInfoReported(info: EdgeNodeInfo) {
        lastHeartbeatAtMs = System.currentTimeMillis()
        lastHeartbeatOk = true
        lastHeartbeatError = ""
        lastReportedRoles = info.roles
        participantId = info.edgeId
        nextHeartbeatAtMs = lastHeartbeatAtMs + heartbeatIntervalMs
        agentRunning = app.edgeAgent.running
    }

    override fun onHeartbeatStatsChanged(successCount: Long, lastSuccessAtMs: Long) {
        lastHeartbeatSuccessAtMs = lastSuccessAtMs
        lastHeartbeatOk = true
    }

    override fun onIntentsPulled(snapshot: IntentsPullSnapshot) {
        if (snapshot.ok) app.seedJourneyFromPull(snapshot)
    }

    companion object {
        private const val POLL_INTERVAL_MS = 5_000L
        private const val POLL_TIMEOUT_MS = 600_000L

        private fun assistantText(phase: IntentPhase, detail: IntentDetail?): String? {
            if (phase == IntentPhase.FAILED) {
                return detail?.error?.takeIf { it.isNotBlank() } ?: "意图失败"
            }
            val pres = detail?.presentation
            if (pres != null && (pres.type == IntentPresentation.Kind.TEXT || pres.type == IntentPresentation.Kind.HTML)) {
                return pres.text.takeIf { it.isNotBlank() }
            }
            return null
        }

        private fun placeholderJourney(
            intentId: String,
            text: String,
            phase: IntentPhase,
            startedAt: Long,
            detail: IntentDetail? = null,
        ): IntentJourney {
            val now = System.currentTimeMillis()
            val phases = IntentPhase.timelineOrder.map { p ->
                when {
                    phase == IntentPhase.FAILED && p.rank == IntentPhase.SUCCEEDED.rank ->
                        PhaseRow(IntentPhase.FAILED, PhaseVisual.FAILED, enteredAtMs = now)
                    p.rank < phase.rank ->
                        PhaseRow(p, PhaseVisual.DONE, enteredAtMs = startedAt, durationMs = 0)
                    p.rank == phase.rank ->
                        PhaseRow(p, PhaseVisual.ACTIVE, enteredAtMs = startedAt, durationMs = max(0, now - startedAt))
                    else -> PhaseRow(p, PhaseVisual.PENDING)
                }
            }
            return IntentJourney(
                intentId = intentId,
                text = text,
                phase = phase,
                phases = phases,
                planSteps = detail?.planSteps.orEmpty(),
                startedAtMs = startedAt,
                updatedAtMs = now,
                presentation = detail?.presentation,
                error = detail?.error,
            )
        }

        private fun IntentDetail.toChatTurn(): ChatTurn {
            val phase = IntentPhase.fromWire(status) ?: IntentPhase.UPLOADED
            val created = createdAtMs ?: System.currentTimeMillis()
            return ChatTurn(
                id = UUID.randomUUID().toString(),
                intentId = intentId,
                createdAtMs = created,
                userText = text.ifBlank { "（历史意图）" },
                source = source,
                journey = placeholderJourney(intentId, text, phase, created, this),
                assistantText = assistantText(phase, this),
                awaitingTerminal = !phase.isTerminal,
                presentation = presentation,
                error = error,
            )
        }
    }
}
