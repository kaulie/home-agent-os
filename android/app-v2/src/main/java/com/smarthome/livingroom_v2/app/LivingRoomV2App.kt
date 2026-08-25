package com.smarthome.livingroom_v2.app

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import com.smarthome.livingroom_v2.BuildConfig
import com.smarthome.livingroom_v2.R
import com.smarthome.livingroom_v2.brain.CompositeBrainClient
import com.smarthome.livingroom_v2.brain.HttpEdgeReporter
import com.smarthome.livingroom_v2.brain.MockBrainClient
import com.smarthome.livingroom_v2.brain.ParticipantStore
import com.smarthome.livingroom_v2.data.AppSettings
import com.smarthome.livingroom_v2.command.CommandHandler
import com.smarthome.livingroom_v2.command.HttpCommandSource
import com.smarthome.livingroom_v2.command.IntentPipeline
import com.smarthome.livingroom_v2.command.IntentStatusClient
import com.smarthome.livingroom_v2.command.dispatcher.LocalTaskDispatcher
import com.smarthome.livingroom_v2.command.runtime.EdgeRuntimeNode
import com.smarthome.livingroom_v2.command.runtime.LocalEdgeRuntime
import com.smarthome.livingroom_v2.data.EdgeIdStore
import com.smarthome.livingroom_v2.edge.EdgeAgent
import com.smarthome.livingroom_v2.edge.SkillRegistry
import com.smarthome.livingroom_v2.service.EdgeAgentController
import com.smarthome.livingroom_v2.service.EdgeAgentService
import com.smarthome.livingroom_v2.skill.music.NetEaseMusicSkill

class LivingRoomV2App : Application() {
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
    lateinit var settings: AppSettings
        private set
    lateinit var participant: ParticipantStore
        private set

    val clientHint: String = BuildConfig.DEFAULT_EDGE_CLIENT_HINT

    /** Brain-issued id if present, else clientHint. */
    val edgeId: String
        get() = edgeAgent.edgeId

    override fun onCreate() {
        super.onCreate()
        instance = this
        createNotificationChannel()
        settings = AppSettings(this)
        participant = ParticipantStore(settings)
        val localBrain = MockBrainClient()
        brain = CompositeBrainClient(
            local = localBrain,
            remote = HttpEdgeReporter(BuildConfig.DEFAULT_BRAIN_BASE_URL, enabled = true),
        )
        registry = SkillRegistry()
        val localNode = EdgeRuntimeNode(
            nodeId = clientHint,
            displayName = "客厅 · Chromecast Edge",
        )
        val intentStatusClient = IntentStatusClient(BuildConfig.DEFAULT_INTENT_URL)
        val localRuntime = LocalEdgeRuntime(
            appContext = this,
            edgeId = clientHint,
            registry = registry,
            brain = brain,
            intentStatusClient = intentStatusClient,
        )
        commandSource = HttpCommandSource(
            BuildConfig.DEFAULT_COMMANDS_PULL_URL,
            intentStatusFilter = null,
            localEdgeId = EdgeIdStore.load(this),
        )
        // EdgeAgent is created below; pipeline logs go through a holder once agent exists.
        lateinit var agentRef: EdgeAgent
        commandHandler = CommandHandler(
            dispatcher = LocalTaskDispatcher(localRuntime),
            localNode = localNode,
            intentStatusClient = intentStatusClient,
            onLog = { msg -> agentRef.pipelineLog(msg) },
        )
        val intentPipeline = IntentPipeline(
            commandHandler = commandHandler,
            intentStatusClient = intentStatusClient,
            localRuntime = localRuntime,
            onLog = { msg -> agentRef.pipelineLog(msg) },
        )
        edgeAgent = EdgeAgent(
            appContext = this,
            identity = EdgeAgent.defaultIdentity(
                clientHint = clientHint,
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
        edgeAgent.installSkills(NetEaseMusicSkill())
        EdgeAgentController.maybeResume(this, reason = "app_onCreate")
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
        lateinit var instance: LivingRoomV2App
            private set
    }
}
