package com.smarthome.livingroom_v2.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.LayoutInflater
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.smarthome.livingroom_v2.R
import com.smarthome.livingroom_v2.BuildConfig
import com.smarthome.livingroom_v2.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_v2.brain.dto.EdgeNodeInfo
import com.smarthome.livingroom_v2.brain.dto.ExecutionReport
import com.smarthome.livingroom_v2.brain.dto.SchemaField
import com.smarthome.livingroom_v2.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_v2.capability.Capabilities
import com.smarthome.livingroom_v2.command.IntentsPullSnapshot
import com.smarthome.livingroom_v2.data.AppSettings
import com.smarthome.livingroom_v2.edge.EdgeAgent
import com.smarthome.livingroom_v2.service.EdgeAgentController
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity(), EdgeAgent.Listener {
    private lateinit var app: LivingRoomV2App
    private lateinit var settings: AppSettings
    private lateinit var edgeInfoText: TextView
    private lateinit var statusText: TextView
    private lateinit var heartbeatStatsText: TextView
    private lateinit var skillsContainer: LinearLayout
    private lateinit var intentsMetaText: TextView
    private lateinit var intentsBodyText: TextView
    private lateinit var intentsScroll: ScrollView
    private lateinit var logText: TextView
    private lateinit var logScroll: ScrollView
    private lateinit var checkAutoStartOnBoot: CheckBox

    private val logLines = ArrayDeque<String>()
    /** Newest intents poll first; capped to avoid unbounded growth. */
    private val intentsHistory = ArrayDeque<String>()
    private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private val dateTimeFmt = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.getDefault())
    /** Remember why we asked for notification permission before retrying start. */
    private var pendingStartReason: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        app = LivingRoomV2App.instance
        settings = AppSettings(this)

        edgeInfoText = findViewById(R.id.edgeInfoText)
        statusText = findViewById(R.id.statusText)
        heartbeatStatsText = findViewById(R.id.heartbeatStatsText)
        skillsContainer = findViewById(R.id.skillsContainer)
        intentsMetaText = findViewById(R.id.intentsMetaText)
        intentsBodyText = findViewById(R.id.intentsBodyText)
        intentsScroll = findViewById(R.id.intentsScroll)
        logText = findViewById(R.id.logText)
        logScroll = findViewById(R.id.logScroll)
        checkAutoStartOnBoot = findViewById(R.id.checkAutoStartOnBoot)

        refreshEdgeInfo()
        refreshHeartbeatStats()
        renderSkillPanels()

        bindAutoStartCheckbox()

        app.edgeAgent.listener = this
        maybeRequestBluetoothPermission()

        // Re-attach UI to whatever the background service is doing.
        EdgeAgentController.maybeResume(this, reason = "main_onCreate")
        refreshAgentStatus()
        scheduleStatusRefresh()

        findViewById<Button>(R.id.btnStartAgent).setOnClickListener {
            interveneStartAgent(reason = "ui_start")
        }
        findViewById<Button>(R.id.btnStopAgent).setOnClickListener {
            EdgeAgentController.requestStop(this, reason = "ui_stop")
            refreshAgentStatus()
            refreshEdgeInfo()
            appendLog(
                "用户：停止 Agent（仅本次进程停轮询；开机自启勾选不变=" +
                    "${settings.autoStartOnBoot}，进程被杀后按该勾选决定是否恢复）",
            )
        }
        findViewById<Button>(R.id.btnClearEdgeId).setOnClickListener {
            app.edgeAgent.clearAssignedEdgeId()
            refreshEdgeInfo()
            appendLog("用户：清除本地 edgeId，下次启动将重新 register")
        }
        findViewById<Button>(R.id.btnPullIntentsNow).setOnClickListener {
            if (!app.edgeAgent.running) {
                Toast.makeText(this, "请先启动 Agent", Toast.LENGTH_SHORT).show()
                appendLog("提示：先启动 Agent 再拉取 Intents")
                return@setOnClickListener
            }
            appendLog("用户：立即拉取 Intents")
            app.edgeAgent.pullIntentsNow()
        }
        findViewById<Button>(R.id.btnClearLog).setOnClickListener {
            logLines.clear()
            logText.text = "（已清空）"
        }
    }

    override fun onResume() {
        super.onResume()
        EdgeAgentController.maybeResume(this, reason = "main_onResume")
        refreshEdgeInfo()
        refreshHeartbeatStats()
        refreshAgentStatus()
        scheduleStatusRefresh()
    }

    override fun onDestroy() {
        if (app.edgeAgent.listener === this) {
            app.edgeAgent.listener = null
        }
        super.onDestroy()
    }

    override fun onStatus(message: String) {
        appendLog(message)
        refreshAgentStatus(extra = message)
        refreshEdgeInfo()
    }

    override fun onCommandPipelineLog(message: String) {
        appendLog(message)
    }

    override fun onIntentsPulled(snapshot: IntentsPullSnapshot) {
        val whenText = timeFmt.format(Date(snapshot.atMs))
        intentsMetaText.text = "$whenText · ${snapshot.summaryLine()}"
        prependIntentsHistory(whenText, snapshot)
        if (!snapshot.ok) {
            appendLog("Intents 拉取失败: ${snapshot.error}")
        } else if (snapshot.commands.isNotEmpty()) {
            appendLog("Intents ${snapshot.summaryLine()}")
        }
    }

    /** Keep prior polls; newest block on top; scroll stays at top for the latest. */
    private fun prependIntentsHistory(whenText: String, snapshot: IntentsPullSnapshot) {
        val entry = buildString {
            append("════ ").append(whenText).append(" · ").append(snapshot.summaryLine()).append(" ════\n")
            if (snapshot.ok && snapshot.commands.isEmpty()) {
                append("(empty queue)")
            } else {
                append(snapshot.displayBody(maxChars = 2_000))
            }
        }
        // Coalesce consecutive empty-ok polls into one line so 15s ticks don't flood the box.
        if (snapshot.ok && snapshot.commands.isEmpty()) {
            val head = intentsHistory.firstOrNull()
            if (head != null && head.contains(" · 空队列") && head.contains("(empty queue)")) {
                intentsHistory.removeFirst()
            }
        }
        intentsHistory.addFirst(entry)
        while (intentsHistory.size > MAX_INTENTS_HISTORY) {
            intentsHistory.removeLast()
        }
        intentsBodyText.text = intentsHistory.joinToString("\n\n")
        intentsScroll.post {
            intentsScroll.scrollTo(0, 0)
            intentsScroll.smoothScrollTo(0, 0)
        }
    }

    override fun onReport(report: ExecutionReport) {
        appendLog(
            "Report ${report.planId}/${report.stepId} ${report.status}" +
                (report.message?.let { " · $it" } ?: ""),
        )
    }

    override fun onEdgeIdAssigned(edgeId: String) {
        refreshEdgeInfo()
        appendLog("Brain 签发 edgeId=$edgeId")
    }

    override fun onEdgeInfoReported(info: EdgeNodeInfo) {
        val caps = info.services.sumOf { it.capabilities.size }
        appendLog(
            "Heartbeat ${info.edgeId} ${info.onlineStatus.wire} " +
                "health=${info.health.status.wire} services=${info.services.size} caps=$caps",
        )
    }

    override fun onHeartbeatStatsChanged(successCount: Long, lastSuccessAtMs: Long) {
        refreshHeartbeatStats(successCount, lastSuccessAtMs)
    }

    private fun renderSkillPanels() {
        skillsContainer.removeAllViews()
        val inflater = LayoutInflater.from(this)
        for (service in app.registry.services()) {
            skillsContainer.addView(buildServicePanel(inflater, service))
        }
    }

    private fun buildServicePanel(
        inflater: LayoutInflater,
        service: ServiceDescriptor,
    ): LinearLayout {
        val panel = inflater.inflate(R.layout.layout_skill_panel, skillsContainer, false) as LinearLayout
        panel.findViewById<TextView>(R.id.skillTitle).text =
            "${service.displayName} (${service.serviceId})"
        panel.findViewById<TextView>(R.id.skillMeta).text =
            "本地单点 · group=${service.group} · v${service.version} · " +
                "caps=${service.capabilities.joinToString { it.capabilityId }}"

        val actionsContainer = panel.findViewById<LinearLayout>(R.id.actionsContainer)
        val withInputs = service.capabilities.filter { it.inputSchema.isNotEmpty() }
        val noInputs = service.capabilities.filter { it.inputSchema.isEmpty() }

        for (cap in withInputs) {
            actionsContainer.addView(buildCapabilityWithInputsBlock(cap, service.serviceId))
        }
        if (noInputs.isNotEmpty()) {
            actionsContainer.addView(buildCapabilityButtonRow(noInputs, service.serviceId))
        }
        return panel
    }

    /** music.play 等：按 input_schema 渲染入参 + 执行按钮。 */
    private fun buildCapabilityWithInputsBlock(
        capability: CapabilityDescriptor,
        serviceId: String,
    ): LinearLayout {
        val block = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, 0, 0, dp(8))
        }

        val header = TextView(this).apply {
            text = "capability: ${capability.capabilityId}"
            setTextColor(ContextCompat.getColor(this@MainActivity, R.color.text_primary))
            textSize = 13f
        }
        block.addView(header)

        val inputViews = linkedMapOf<String, EditText>()
        val inputsRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(4) }
        }

        for ((name, field) in capability.inputSchema) {
            val col = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { marginEnd = dp(8) }
            }
            col.addView(
                TextView(this).apply {
                    text = field.description.ifEmpty { name } + if (field.required) " *" else ""
                    setTextColor(ContextCompat.getColor(this@MainActivity, R.color.text_secondary))
                    textSize = 11f
                },
            )
            val edit = EditText(this).apply {
                setText(defaultInputValue(name, field))
                setTextColor(ContextCompat.getColor(this@MainActivity, R.color.text_primary))
                setHintTextColor(ContextCompat.getColor(this@MainActivity, R.color.text_secondary))
                textSize = 14f
                minHeight = dp(40)
                isFocusable = true
                isFocusableInTouchMode = true
            }
            col.addView(edit)
            inputViews[name] = edit
            inputsRow.addView(col)
        }
        block.addView(inputsRow)

        val button = compactActionButton(capabilityButtonLabel(capability.capabilityId)) {
            runCapability(serviceId, capability, inputViews)
        }
        block.addView(
            button,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(40),
            ).apply { topMargin = dp(4) },
        )
        return block
    }

    private fun buildCapabilityButtonRow(
        capabilities: List<CapabilityDescriptor>,
        serviceId: String,
    ): LinearLayout {
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply { topMargin = dp(4) }
        }
        capabilities.forEachIndexed { index, cap ->
            val button = compactActionButton(capabilityButtonLabel(cap.capabilityId)) {
                runCapability(serviceId, cap, emptyMap())
            }
            val lp = LinearLayout.LayoutParams(0, dp(40), 1f).apply {
                if (index < capabilities.lastIndex) marginEnd = dp(6)
            }
            row.addView(button, lp)
        }
        return row
    }

    private fun compactActionButton(label: String, onClick: () -> Unit): Button =
        Button(this).apply {
            text = label
            textSize = 12f
            isFocusable = true
            isAllCaps = false
            // Material Button defaults may override drawable; clear tint so selector shows.
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.btn_background)
            backgroundTintList = null
            setTextColor(ContextCompat.getColorStateList(this@MainActivity, R.color.btn_text_tint))
            setPadding(dp(4), 0, dp(4), 0)
            setOnClickListener { onClick() }
        }

    private fun capabilityButtonLabel(capabilityId: String): String =
        when (capabilityId) {
            Capabilities.BLUETOOTH_CONNECT -> "连接蓝牙"
            Capabilities.BLUETOOTH_DISCONNECT -> "断开蓝牙"
            Capabilities.MUSIC_PLAY -> "搜歌播放"
            Capabilities.MUSIC_PAUSE -> "暂停"
            Capabilities.MUSIC_NEXT -> "下一首"
            Capabilities.MUSIC_PREVIOUS -> "上一首"
            Capabilities.MUSIC_STOP -> "停止"
            else -> capabilityId.substringAfterLast('.')
        }

    private fun defaultInputValue(name: String, @Suppress("UNUSED_PARAMETER") field: SchemaField): String =
        when (name) {
            "song" -> "十年"
            "artist" -> ""
            "album" -> ""
            "device_name" -> "WILLEN"
            else -> ""
        }

    private fun runCapability(
        serviceId: String,
        capability: CapabilityDescriptor,
        inputViews: Map<String, EditText>,
    ) {
        val params = linkedMapOf<String, Any?>()
        for ((name, field) in capability.inputSchema) {
            val value = inputViews[name]?.text?.toString()?.trim().orEmpty()
            if (field.required && value.isEmpty()) {
                Toast.makeText(this, "请填写 $name", Toast.LENGTH_SHORT).show()
                return
            }
            if (value.isNotEmpty()) {
                params[name] = value
            }
        }

        if (!app.edgeAgent.running) {
            Toast.makeText(this, "请先启动 Agent", Toast.LENGTH_SHORT).show()
            appendLog("提示：先启动 Agent 再执行 ${capability.capabilityId}")
            return
        }

        appendLog("LocalAction → $serviceId / ${capability.capabilityId} $params")
        Toast.makeText(this, "本地执行 ${capability.capabilityId}", Toast.LENGTH_SHORT).show()
        app.edgeAgent.invokeLocalSkillAction(
            skillId = serviceId,
            capabilityId = capability.capabilityId,
            params = params,
        )
    }

    private fun bindAutoStartCheckbox() {
        checkAutoStartOnBoot.setOnCheckedChangeListener(null)
        checkAutoStartOnBoot.isChecked = settings.autoStartOnBoot
        checkAutoStartOnBoot.setOnCheckedChangeListener { _, isChecked ->
            if (isChecked) {
                settings.autoStartOnBoot = true
                appendLog("开机自启：已开启 → 后台启动 Agent（持续心跳直到手动停止）")
                interveneStartAgent(reason = "auto_start_checked")
            } else {
                EdgeAgentController.disableAutoStartOnly(this)
                appendLog("开机自启：已关闭（不自动停当前 Agent；下次开机不再自启）")
                refreshEdgeInfo()
            }
        }
    }

    /**
     * UI / checkbox intervention: start FGS.
     * Cross-process resume after kill depends on autoStartOnBoot, not Start alone.
     */
    private fun interveneStartAgent(reason: String) {
        settings.agentEnabled = true
        if (!ensureNotificationPermission()) {
            pendingStartReason = reason
            refreshAgentStatus(extra = "等待通知权限")
            appendLog("提示：需通知权限以启动后台服务")
            return
        }
        pendingStartReason = null
        EdgeAgentController.requestStart(this, reason = reason)
        refreshAgentStatus()
        scheduleStatusRefresh()
        appendLog(
            "干预：启动后台 Agent（$reason）· enabled=${settings.agentEnabled} · " +
                "boot=${settings.autoStartOnBoot}",
        )
    }

    private fun refreshAgentStatus(extra: String? = null) {
        val running = app.edgeAgent.running
        val enabled = settings.agentEnabled
        val stopped = EdgeAgentController.stoppedThisProcess
        val base = when {
            running -> "Agent：运行中（后台服务）"
            stopped -> "Agent：已停止（本次进程；开机自启=${settings.autoStartOnBoot}）"
            enabled || settings.autoStartOnBoot -> "Agent：应运行（正在拉起后台服务…）"
            else -> "Agent：已停止"
        }
        statusText.text = if (extra.isNullOrBlank()) base else "$base · $extra"
    }

    /** Service start is async; refresh a few times so UI catches up. */
    private fun scheduleStatusRefresh() {
        statusText.postDelayed({ refreshAgentStatus(); refreshHeartbeatStats() }, 400L)
        statusText.postDelayed({
            refreshAgentStatus()
            refreshEdgeInfo()
            refreshHeartbeatStats()
        }, 1200L)
    }

    private fun refreshHeartbeatStats(
        successCount: Long = app.edgeAgent.heartbeatSuccessCount,
        lastSuccessAtMs: Long = app.edgeAgent.lastHeartbeatSuccessAtMs,
    ) {
        val lastLabel = if (lastSuccessAtMs <= 0L) {
            "—"
        } else {
            dateTimeFmt.format(Date(lastSuccessAtMs))
        }
        heartbeatStatsText.text = getString(
            R.string.heartbeat_stats_format,
            successCount,
            lastLabel,
        )
    }

    private fun refreshEdgeInfo() {
        val assigned = app.edgeAgent.assignedEdgeId
        val assignedLabel = assigned ?: "未签发（启动后会先 /edge-register）"
        edgeInfoText.text =
            "hint=${app.clientHint} · edgeId=$assignedLabel · " +
                "roles=${app.participant.enabledRoles().joinToString(",")} · " +
                "enabled=${settings.agentEnabled} · boot=${settings.autoStartOnBoot} · " +
                "brain=${BuildConfig.DEFAULT_BRAIN_BASE_URL} · hb=${BuildConfig.HEARTBEAT_INTERVAL_MS}ms"
    }

    /** @return true if we can start FGS now (permission granted or not required). */
    private fun ensureNotificationPermission(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (granted) return true
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.POST_NOTIFICATIONS),
            REQ_POST_NOTIFICATIONS,
        )
        return false
    }

    private fun maybeRequestBluetoothPermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.BLUETOOTH_CONNECT,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.BLUETOOTH_CONNECT),
                REQ_BT,
            )
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_POST_NOTIFICATIONS) return
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            interveneStartAgent(reason = pendingStartReason ?: "notification_granted")
        } else {
            Toast.makeText(this, "未授予通知权限，无法保活后台服务", Toast.LENGTH_SHORT).show()
            appendLog("通知权限被拒绝")
            pendingStartReason = null
        }
    }

    private fun appendLog(line: String) {
        val pieces = line
            .split('\n')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .ifEmpty { listOf(line) }
        for (piece in pieces) {
            val stamped = "${timeFmt.format(Date())} $piece"
            logLines.addLast(stamped)
        }
        while (logLines.size > 200) logLines.removeFirst()
        logText.text = logLines.joinToString("\n")
        logScroll.post { logScroll.fullScroll(ScrollView.FOCUS_DOWN) }
    }

    private fun dp(value: Int): Int =
        (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val MAX_INTENTS_HISTORY = 50
        private const val REQ_BT = 2001
        private const val REQ_POST_NOTIFICATIONS = 2002
    }
}
