package com.smarthome.livingroom_android.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.provider.Settings
import android.util.Log
import com.smarthome.livingroom_android.BuildConfig
import com.smarthome.livingroom_android.R
import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.brain.CompositeBrainClient
import com.smarthome.livingroom_android.brain.HttpEdgeReporter
import com.smarthome.livingroom_android.brain.MockBrainClient
import com.smarthome.livingroom_android.brain.ParticipantStore
import com.smarthome.livingroom_android.brain.dto.EdgeDeviceType
import com.smarthome.livingroom_android.brain.dto.EdgeIdentity
import com.smarthome.livingroom_android.command.CommandHandler
import com.smarthome.livingroom_android.command.HttpCommandSource
import com.smarthome.livingroom_android.command.IntentPipeline
import com.smarthome.livingroom_android.command.IntentStatusClient
import com.smarthome.livingroom_android.command.dispatcher.LocalTaskDispatcher
import com.smarthome.livingroom_android.command.runtime.EdgeRuntimeNode
import com.smarthome.livingroom_android.command.runtime.LocalEdgeRuntime
import com.smarthome.livingroom_android.edge.IntentRuntimeLog
import com.smarthome.livingroom_android.data.AppSettings
import com.smarthome.livingroom_android.data.EdgeIdStore
import com.smarthome.livingroom_android.data.HouseholdDirectory
import com.smarthome.livingroom_android.edge.EdgeAgent
import com.smarthome.livingroom_android.edge.SkillRegistry
import com.smarthome.livingroom_android.intent.IntentApi
import com.smarthome.livingroom_android.intent.IntentJourneyStore
import com.smarthome.livingroom_android.intent.IntentPhase
import com.smarthome.livingroom_android.intent.PlanStepRow
import com.smarthome.livingroom_android.service.EdgeAgentController
import com.smarthome.livingroom_android.service.EdgeAgentService
import com.smarthome.livingroom_android.skill.AndroidCameraSkill
import com.smarthome.livingroom_android.skill.AssetUploadSkill
import com.smarthome.livingroom_android.skill.DocumentScanSkill
import com.smarthome.livingroom_android.skill.GoProCameraSkill
import com.smarthome.livingroom_android.skill.PhoneCallSkill
import org.json.JSONObject

/**
 * HomeAgent Console: Intent Source + Endpoint + local runtime (document.scan, phone.call).
 */
class LivingRoomAndroidApp : Application() {
    lateinit var settings: AppSettings
        private set
    lateinit var participant: ParticipantStore
        private set
    lateinit var brain: CompositeBrainClient
        private set
    lateinit var registry: SkillRegistry
        private set
    lateinit var edgeAgent: EdgeAgent
        private set
    lateinit var commandHandler: CommandHandler
        private set
    lateinit var commandSource: HttpCommandSource
        private set
    lateinit var intentStatusClient: IntentStatusClient
        private set
    lateinit var intentJourney: IntentJourneyStore
        private set
    lateinit var intentApi: IntentApi
        private set
    lateinit var localRuntime: LocalEdgeRuntime
        private set
    lateinit var reporter: HttpEdgeReporter
        private set
    lateinit var secondaryReporter: HttpEdgeReporter
        private set

    val clientHint: String
        get() = settings.clientHint

    val edgeId: String
        get() = edgeAgent.edgeId

    @Volatile
    var pipelineLogSink: ((String) -> Unit)? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()
        settings = AppSettings(this)
        settings.ensureClientHint(Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID))
        participant = ParticipantStore(settings)
        intentJourney = IntentJourneyStore()
        intentApi = IntentApi()

        val initialBase = BrainEndpoint.normalizeBase(settings.cloudBrainUrl)
        reporter = HttpEdgeReporter(initialBase, enabled = true)
        // P0 dual-Brain: also register/heartbeat with the LAN Brain so both Brains
        // see this Runtime. The active routing Brain (reporter) stays primary for pull/status.
        secondaryReporter = HttpEdgeReporter(
            BrainEndpoint.normalizeBase(settings.lanBrainUrl),
            enabled = true,
        )
        brain = CompositeBrainClient(
            local = MockBrainClient(),
            remote = reporter,
            secondaryRemote = secondaryReporter,
        )
        registry = SkillRegistry()
        val localNode = EdgeRuntimeNode(
            nodeId = clientHint,
            displayName = "客厅 Android",
        )
        intentStatusClient = IntentStatusClient(BrainEndpoint.intentUrl(initialBase))
        val localRuntime = LocalEdgeRuntime(
            appContext = this,
            edgeId = clientHint,
            registry = registry,
            brain = brain,
            intentStatusClient = intentStatusClient,
            onIntentPhase = { intentId, phase, message ->
                intentJourney.upsert(intentId, phase = phase, text = message)
            },
            onPlanStep = { capability, status, detail ->
                intentJourney.updatePlanStep(capability, status, detail)
            },
        )
        this.localRuntime = localRuntime
        commandSource = HttpCommandSource(
            BrainEndpoint.livingRoomIntentsPullUrl(initialBase),
            intentStatusFilter = null,
            localEdgeId = EdgeIdStore.load(this),
        )
        lateinit var agentRef: EdgeAgent
        commandHandler = CommandHandler(
            dispatcher = LocalTaskDispatcher(localRuntime),
            localNode = localNode,
            intentStatusClient = intentStatusClient,
            onLog = { msg ->
                IntentRuntimeLog.append(LivingRoomAndroidApp.extractIntentId(msg), msg)
                agentRef.pipelineLog(msg)
                pipelineLogSink?.invoke(msg)
            },
        )
        val intentPipeline = IntentPipeline(
            commandHandler = commandHandler,
            intentStatusClient = intentStatusClient,
            localRuntime = localRuntime,
            journeyStore = intentJourney,
            onLog = { msg ->
                IntentRuntimeLog.append(LivingRoomAndroidApp.extractIntentId(msg), msg)
                agentRef.pipelineLog(msg)
                pipelineLogSink?.invoke(msg)
            },
        )
        edgeAgent = EdgeAgent(
            appContext = this,
            identity = EdgeIdentity(
                clientHint = clientHint,
                displayName = "客厅 Android",
                deviceType = EdgeDeviceType.ANDROID,
                room = "living-room",
                appVersion = BuildConfig.VERSION_NAME,
            ),
            brain = brain,
            registry = registry,
            heartbeatIntervalMs = BuildConfig.HEARTBEAT_INTERVAL_MS,
            commandSource = commandSource,
            commandHandler = commandHandler,
            localRuntime = localRuntime,
            intentPipeline = intentPipeline,
            participant = participant,
        )
        agentRef = edgeAgent
        edgeAgent.installSkills(
            DocumentScanSkill(
                intentUrl = { BrainEndpoint.intentUrl(reporter.baseURL) },
                participantId = { edgeAgent.assignedEdgeId ?: clientHint },
                api = intentApi,
            ),
            AndroidCameraSkill(),
            GoProCameraSkill(
                intentUrl = { BrainEndpoint.intentUrl(reporter.baseURL) },
                participantId = { edgeAgent.assignedEdgeId ?: clientHint },
                api = intentApi,
            ),
            AssetUploadSkill(
                intentUrl = { BrainEndpoint.intentUrl(reporter.baseURL) },
                participantId = { edgeAgent.assignedEdgeId ?: clientHint },
                api = intentApi,
            ),
            PhoneCallSkill(
                people = { HouseholdDirectory.parse(settings.householdDirectoryJson) },
            ),
        )
        EdgeAgentController.maybeResume(this, reason = "app_onCreate")
        Log.i(TAG, "Console ready hint=$clientHint")
    }

    fun applyBrainBase(base: String) {
        val root = BrainEndpoint.normalizeBase(base)
        val lan = BrainEndpoint.normalizeBase(settings.lanBrainUrl)
        val cloud = BrainEndpoint.normalizeBase(settings.cloudBrainUrl)
        if (root != BrainEndpoint.normalizeBase(reporter.baseURL)) {
            reporter.baseURL = root
            commandSource.setPullURL(BrainEndpoint.livingRoomIntentsPullUrl(root))
            intentStatusClient.intentBaseURL = BrainEndpoint.intentUrl(root)
            Log.i(TAG, "Brain base → $root")
        }
        // The other slot (not the active routing Brain) gets best-effort register/heartbeat.
        val other = when (root) {
            lan -> cloud
            cloud -> lan
            else -> ""
        }
        if (other.isNotBlank() && other != root) {
            secondaryReporter.baseURL = other
        }
    }

    fun seedJourneyFromPull(snapshot: com.smarthome.livingroom_android.command.IntentsPullSnapshot) {
        val intent = snapshot.intents.firstOrNull()
        if (intent != null) {
            seedJourneyFromIntent(intent)
            return
        }
        val cmd = snapshot.commands.firstOrNull() ?: return
        val intentId = cmd.params["intent_id"]?.toString()?.trim().orEmpty()
            .ifBlank { cmd.commandId }
        val text = cmd.params["text"]?.toString()
            ?: cmd.params["utterance"]?.toString()
            ?: "${cmd.device}/${cmd.action}"
        val phase = IntentPhase.fromWire(cmd.params["intent_status"]?.toString())
            ?: IntentPhase.INTENT_PARSED
        val steps = snapshot.commands.mapIndexed { i, c ->
            PlanStepRow(
                step = i + 1,
                capability = c.params["capability"]?.toString() ?: c.action,
                status = "pulled",
                detail = c.device,
            )
        }
        intentJourney.upsert(intentId, text = text, phase = phase, planSteps = steps)
    }

    private fun seedJourneyFromIntent(intent: JSONObject) {
        val intentId = (
            intent.opt("id")?.toString()
                ?: intent.optString("intent_id", "")
            ).trim()
        if (intentId.isEmpty()) return
        val text = intent.optString("text", intent.optString("utterance", ""))
        val phase = IntentPhase.fromWire(
            intent.optString("intent_status", intent.optString("status", "")),
        ) ?: IntentPhase.INTENT_PARSED
        val plan = intent.optJSONArray("execution_plan")
        val steps = mutableListOf<PlanStepRow>()
        if (plan != null) {
            for (i in 0 until plan.length()) {
                val step = plan.optJSONObject(i) ?: continue
                val n = step.optInt("step", i + 1)
                val cap = step.optString("capability", "")
                val assigned = step.optString("assigned_edge_id", "")
                val st = when (val raw = step.opt("status") ?: step.opt("step_status")) {
                    is Number -> raw.toInt()
                    is String -> raw.toIntOrNull() ?: 0
                    else -> 0
                }
                val statusLabel = when (st) {
                    1 -> "running"
                    2 -> "succeeded"
                    3 -> "failed"
                    else -> "queued"
                }
                steps += PlanStepRow(
                    step = n,
                    capability = cap,
                    status = statusLabel,
                    detail = if (assigned.isNotBlank()) "@$assigned" else "",
                )
            }
        }
        intentJourney.upsert(intentId, text = text, phase = phase, planSteps = steps)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val channel = NotificationChannel(
            EdgeAgentService.CHANNEL_ID,
            getString(R.string.service_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    companion object {
        private const val TAG = "HomeAgentConsole"
        private val intentIdPattern = Regex("""intent[_ ]?id[=:#\s]+(\d+)""", RegexOption.IGNORE_CASE)
        lateinit var instance: LivingRoomAndroidApp
            private set

        fun extractIntentId(message: String): String? =
            intentIdPattern.find(message)?.groupValues?.getOrNull(1)
    }
}
