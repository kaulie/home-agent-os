package com.smarthome.livingroom_android.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import android.util.Log
import com.smarthome.livingroom_android.BuildConfig
import com.smarthome.livingroom_android.R
import com.smarthome.livingroom_android.brain.CompositeBrainClient
import com.smarthome.livingroom_android.brain.HttpEdgeReporter
import com.smarthome.livingroom_android.brain.MockBrainClient
import com.smarthome.livingroom_android.brain.dto.EdgeDeviceType
import com.smarthome.livingroom_android.brain.dto.EdgeIdentity
import com.smarthome.livingroom_android.command.CommandHandler
import com.smarthome.livingroom_android.command.HttpCommandSource
import com.smarthome.livingroom_android.command.IntentPipeline
import com.smarthome.livingroom_android.command.IntentStatusClient
import com.smarthome.livingroom_android.command.dispatcher.LocalTaskDispatcher
import com.smarthome.livingroom_android.command.runtime.EdgeRuntimeNode
import com.smarthome.livingroom_android.command.runtime.LocalEdgeRuntime
import com.smarthome.livingroom_android.data.EdgeIdStore
import com.smarthome.livingroom_android.edge.EdgeAgent
import com.smarthome.livingroom_android.edge.SkillRegistry
import com.smarthome.livingroom_android.intent.IntentJourneyStore
import com.smarthome.livingroom_android.intent.IntentPhase
import com.smarthome.livingroom_android.intent.PlanStepRow
import com.smarthome.livingroom_android.service.EdgeAgentController
import com.smarthome.livingroom_android.service.EdgeAgentService
import com.smarthome.plugin.gopro.WifiNetworkSkill
import org.json.JSONObject

/**
 * Slim Android Edge: register/heartbeat + intent logistics + Wi‑Fi switch.
 */
class LivingRoomAndroidApp : Application() {
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
    lateinit var intentJourney: IntentJourneyStore
        private set

    val clientHint: String = BuildConfig.DEFAULT_EDGE_CLIENT_HINT

    val edgeId: String
        get() = edgeAgent.edgeId

    @Volatile
    var pipelineLogSink: ((String) -> Unit)? = null

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()
        intentJourney = IntentJourneyStore()

        brain = CompositeBrainClient(
            local = MockBrainClient(),
            remote = HttpEdgeReporter(BuildConfig.DEFAULT_BRAIN_BASE_URL, enabled = true),
        )
        registry = SkillRegistry()
        val localNode = EdgeRuntimeNode(
            nodeId = clientHint,
            displayName = "客厅 · Android Edge",
        )
        val intentStatusClient = IntentStatusClient(BuildConfig.DEFAULT_INTENT_URL)
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
        commandSource = HttpCommandSource(
            BuildConfig.DEFAULT_COMMANDS_PULL_URL,
            intentStatusFilter = null,
            localEdgeId = EdgeIdStore.load(this),
        )
        lateinit var agentRef: EdgeAgent
        commandHandler = CommandHandler(
            dispatcher = LocalTaskDispatcher(localRuntime),
            localNode = localNode,
            intentStatusClient = intentStatusClient,
            onLog = { msg ->
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
                agentRef.pipelineLog(msg)
                pipelineLogSink?.invoke(msg)
            },
        )
        edgeAgent = EdgeAgent(
            appContext = this,
            identity = EdgeIdentity(
                clientHint = clientHint,
                displayName = "客厅 · Android Edge",
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
        )
        agentRef = edgeAgent
        edgeAgent.installSkills(
            WifiNetworkSkill(
                onProgress = { pipelineLogSink?.invoke(it) },
                homeProbeUrl = BuildConfig.DEFAULT_HOME_PROBE_URL,
            ),
        )
        EdgeAgentController.maybeResume(this, reason = "app_onCreate")
        Log.i(TAG, "slim Edge ready hint=$clientHint")
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
        private const val TAG = "LivingRoomAndroidApp"
        lateinit var instance: LivingRoomAndroidApp
            private set
    }
}
