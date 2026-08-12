package com.smarthome.livingroom_android.app

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.text.method.HideReturnsTransformationMethod
import android.text.method.PasswordTransformationMethod
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.smarthome.livingroom_android.BuildConfig
import com.smarthome.livingroom_android.R
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.command.IntentsPullSnapshot
import com.smarthome.livingroom_android.data.AppSettings
import com.smarthome.livingroom_android.edge.EdgeAgent
import com.smarthome.livingroom_android.intent.IntentJourney
import com.smarthome.livingroom_android.intent.IntentJourneyStore
import com.smarthome.livingroom_android.intent.IntentPhase
import com.smarthome.livingroom_android.intent.IntentSubmitClient
import com.smarthome.livingroom_android.intent.SpeechToTextHelper
import com.smarthome.livingroom_android.service.EdgeAgentController
import com.smarthome.livingroom_android.skill.SkillContext
import com.smarthome.plugin.gopro.GoProWifiCoordinator
import com.smarthome.plugin.gopro.WifiNetworkSkill
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity(), EdgeAgent.Listener, IntentJourneyStore.Listener {
    private lateinit var app: LivingRoomAndroidApp
    private lateinit var settings: AppSettings
    private lateinit var statusText: TextView
    private lateinit var journeyText: TextView
    private lateinit var logText: TextView
    private lateinit var intentText: EditText
    private lateinit var intentSourceHint: TextView
    private lateinit var btnVoice: Button
    private lateinit var goproSsid: EditText
    private lateinit var goproPassword: EditText
    private val logLines = ArrayDeque<String>()
    private val timeFmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())
    private var journeyTickJob: Job? = null
    private var pendingSystemWifiSsid: String = ""
    private var systemWifiBaseline: GoProWifiCoordinator.WifiSnapshot? = null

    /** text | voice — matches iOS intentSource */
    private var intentSource: String = "text"
    private var lastVoiceTranscript: String = ""

    private val addWifiLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            val target = pendingSystemWifiSsid
            val baseline = systemWifiBaseline
            appendLog(
                "系统添加网络返回：result=${result.resultCode}" +
                    " (${if (result.resultCode == Activity.RESULT_OK) "OK" else "CANCEL/OTHER"})" +
                    " target=$target",
            )
            if (target.isBlank()) return@registerForActivityResult
            if (result.resultCode != Activity.RESULT_OK) {
                Toast.makeText(this, "未在系统面板确认保存/连接", Toast.LENGTH_LONG).show()
                appendLog("FAIL 用户取消或面板未真正打开")
                return@registerForActivityResult
            }
            lifecycleScope.launch {
                val wifi = GoProWifiCoordinator(this@MainActivity, BuildConfig.DEFAULT_HOME_PROBE_URL)
                try {
                    appendLog("面板已确认，严格校验状态栏 SSID/BSSID…")
                    val joined = wifi.waitForConfirmedPrimarySsid(
                        ssid = target,
                        timeoutMs = 45_000L,
                        onProgress = { appendLog(it) },
                        baseline = baseline,
                    )
                    appendLog("OK 已确认 ${joined.snapshot?.summary}")
                    Toast.makeText(
                        this@MainActivity,
                        "已加入「${joined.primarySsid}」",
                        Toast.LENGTH_LONG,
                    ).show()
                } catch (t: Throwable) {
                    appendLog("FAIL ${t.message}")
                    android.app.AlertDialog.Builder(this@MainActivity)
                        .setTitle("未切到目标 Wi‑Fi")
                        .setMessage(
                            (t.message ?: "unknown") +
                                "\n\n可手动在系统 Wi‑Fi 列表点「$target」",
                        )
                        .setPositiveButton("打开 Wi‑Fi 设置") { _, _ ->
                            runCatching { wifi.openWifiSettings(this@MainActivity) }
                        }
                        .setNegativeButton("关闭", null)
                        .show()
                }
            }
        }

    private val speech by lazy {
        SpeechToTextHelper(
            context = this,
            onPartial = { t ->
                runOnUiThread {
                    intentText.setText(t)
                    intentText.setSelection(t.length)
                    intentSource = "voice"
                    refreshIntentSourceHint("聆听中…")
                }
            },
            onFinal = { t ->
                runOnUiThread {
                    lastVoiceTranscript = t
                    intentText.setText(t)
                    intentText.setSelection(t.length)
                    intentSource = "voice"
                    btnVoice.text = "开始录音"
                    refreshIntentSourceHint("已转写，可发出")
                    appendLog("voice → $t")
                }
            },
            onStatus = { s -> runOnUiThread { refreshIntentSourceHint(s) } },
            onError = { e ->
                runOnUiThread {
                    btnVoice.text = "开始录音"
                    refreshIntentSourceHint(e)
                    appendLog("语音错误: $e")
                    Toast.makeText(this, e, Toast.LENGTH_SHORT).show()
                }
            },
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        app = LivingRoomAndroidApp.instance
        settings = AppSettings(this)
        statusText = findViewById(R.id.statusText)
        journeyText = findViewById(R.id.journeyText)
        logText = findViewById(R.id.logText)
        intentText = findViewById(R.id.intentText)
        intentSourceHint = findViewById(R.id.intentSourceHint)
        btnVoice = findViewById(R.id.btnVoice)
        goproSsid = findViewById(R.id.goproSsid)
        goproPassword = findViewById(R.id.goproPassword)
        goproSsid.setText(settings.goproSsid)
        goproPassword.setText(settings.goproPassword)
        findViewById<CheckBox>(R.id.chkShowPassword).setOnCheckedChangeListener { _, show ->
            val start = goproPassword.selectionStart
            val end = goproPassword.selectionEnd
            if (show) {
                goproPassword.inputType =
                    InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
                goproPassword.transformationMethod = HideReturnsTransformationMethod.getInstance()
            } else {
                goproPassword.inputType =
                    InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                goproPassword.transformationMethod = PasswordTransformationMethod.getInstance()
            }
            if (start >= 0 && end >= 0) {
                goproPassword.setSelection(start.coerceAtMost(goproPassword.text.length), end.coerceAtMost(goproPassword.text.length))
            }
        }

        findViewById<CheckBox>(R.id.chkAutoStart).apply {
            isChecked = settings.autoStartOnBoot
            setOnCheckedChangeListener { _, c -> settings.autoStartOnBoot = c }
        }
        findViewById<Button>(R.id.btnSaveWifi).setOnClickListener {
            persistWifiPrefs()
            Toast.makeText(this, "已保存 SSID/密码", Toast.LENGTH_SHORT).show()
        }
        findViewById<Button>(R.id.btnPermissions).setOnClickListener { requestNeededPermissions() }
        findViewById<Button>(R.id.btnWifiJoin).setOnClickListener { runWifiJoin() }
        findViewById<Button>(R.id.btnWifiSystemAdd).setOnClickListener { runSystemAddNetwork() }
        findViewById<Button>(R.id.btnWifiLeave).setOnClickListener { runWifiLeave() }
        findViewById<Button>(R.id.btnRegister).setOnClickListener {
            appendLog("注册中…")
            findViewById<Button>(R.id.btnRegister).isEnabled = false
            app.edgeAgent.registerOnce { ok, msg ->
                runOnUiThread {
                    findViewById<Button>(R.id.btnRegister).isEnabled = true
                    appendLog(if (ok) "注册：$msg" else "注册失败：$msg")
                    Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
                    refreshStatus()
                }
            }
        }
        findViewById<Button>(R.id.btnHeartbeat).setOnClickListener {
            appendLog("心跳中…")
            findViewById<Button>(R.id.btnHeartbeat).isEnabled = false
            app.edgeAgent.heartbeatOnce { ok, msg ->
                runOnUiThread {
                    findViewById<Button>(R.id.btnHeartbeat).isEnabled = true
                    appendLog(if (ok) "心跳：$msg" else "心跳失败：$msg")
                    Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
                    refreshStatus()
                }
            }
        }
        findViewById<Button>(R.id.btnClearEdgeId).setOnClickListener {
            app.edgeAgent.clearAssignedEdgeId()
            appendLog("cleared edgeId — 可重新点「注册」")
            refreshStatus()
        }
        findViewById<Button>(R.id.btnStartAgent).setOnClickListener {
            EdgeAgentController.requestStart(this, "ui")
            refreshStatus()
        }
        findViewById<Button>(R.id.btnStopAgent).setOnClickListener {
            EdgeAgentController.requestStop(this, "ui")
            refreshStatus()
        }

        btnVoice.setOnClickListener { toggleVoice() }
        findViewById<Button>(R.id.btnSendIntent).setOnClickListener { sendIntent() }
        findViewById<Button>(R.id.btnClearIntent).setOnClickListener {
            if (speech.isListening) speech.stop()
            intentText.setText("")
            lastVoiceTranscript = ""
            intentSource = "text"
            btnVoice.text = "开始录音"
            refreshIntentSourceHint(null)
        }

        app.edgeAgent.listener = this
        app.intentJourney.addListener(this)
        app.pipelineLogSink = { msg -> runOnUiThread { appendLog(msg) } }
        onJourneyChanged(app.intentJourney.active)
        requestNeededPermissions()
        refreshStatus()
        refreshIntentSourceHint(null)
        appendLog("可输入指令或语音转写后发出 · POST ${BuildConfig.DEFAULT_INTENT_URL}")
    }

    override fun onDestroy() {
        journeyTickJob?.cancel()
        speech.stop()
        if (app.edgeAgent.listener === this) app.edgeAgent.listener = null
        app.intentJourney.removeListener(this)
        app.pipelineLogSink = null
        super.onDestroy()
    }

    private fun ensureJourneyTicker(journey: IntentJourney?) {
        val needTick = journey != null && !journey.phase.isTerminal
        if (!needTick) {
            journeyTickJob?.cancel()
            journeyTickJob = null
            return
        }
        if (journeyTickJob?.isActive == true) return
        journeyTickJob = lifecycleScope.launch {
            while (isActive) {
                delay(500)
                app.intentJourney.tick()
            }
        }
    }

    private fun toggleVoice() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.RECORD_AUDIO),
                1002,
            )
            Toast.makeText(this, "请先允许麦克风权限", Toast.LENGTH_SHORT).show()
            return
        }
        if (speech.isListening) {
            speech.stop()
            btnVoice.text = "开始录音"
            intentSource = "voice"
            refreshIntentSourceHint(
                if (intentText.text?.isNotBlank() == true) "已转写，可发出" else "已停止",
            )
            return
        }
        if (!speech.isAvailable) {
            Toast.makeText(this, "本机不支持语音识别", Toast.LENGTH_SHORT).show()
            return
        }
        lastVoiceTranscript = ""
        intentSource = "voice"
        btnVoice.text = "停止录音"
        refreshIntentSourceHint("正在聆听…")
        speech.start()
    }

    private fun sendIntent() {
        if (speech.isListening) speech.stop()
        btnVoice.text = "开始录音"
        val text = intentText.text?.toString()?.trim().orEmpty()
        if (text.isEmpty()) {
            Toast.makeText(this, "请先输入文字或完成语音识别", Toast.LENGTH_SHORT).show()
            return
        }
        val source =
            if (intentSource == "voice" &&
                (text == lastVoiceTranscript || text.startsWith(lastVoiceTranscript))
            ) {
                "voice"
            } else if (intentSource == "voice" && lastVoiceTranscript.isNotEmpty()) {
                "voice"
            } else {
                "text"
            }
        lifecycleScope.launch {
            appendLog("发出指令 source=$source · $text")
            val client = IntentSubmitClient(BuildConfig.DEFAULT_INTENT_URL)
            val result = client.submit(text = text, source = source, edgeId = app.edgeId)
            appendLog(if (result.ok) "OK ${result.message}" else "FAIL ${result.message}")
            if (result.ok && !result.intentId.isNullOrBlank()) {
                val phase = IntentPhase.fromWire(result.status) ?: IntentPhase.UPLOADED
                app.intentJourney.upsert(
                    intentId = result.intentId,
                    text = text,
                    phase = phase,
                )
                // Refresh plan steps from detail when available
                val detail = client.fetchDetail(result.intentId)
                if (detail.ok) {
                    val steps = IntentSubmitClient.lastPlanSteps
                    val p2 = IntentPhase.fromWire(detail.status) ?: phase
                    app.intentJourney.upsert(
                        intentId = result.intentId,
                        text = text,
                        phase = p2,
                        planSteps = steps,
                    )
                    appendLog(detail.message)
                }
                Toast.makeText(this@MainActivity, "已发出 #${result.intentId}", Toast.LENGTH_SHORT)
                    .show()
            } else {
                Toast.makeText(
                    this@MainActivity,
                    result.message,
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    private fun refreshIntentSourceHint(extra: String?) {
        val src = if (intentSource == "voice") "语音" else "文本"
        intentSourceHint.text =
            if (extra.isNullOrBlank()) "来源：$src" else "来源：$src · $extra"
    }

    private fun persistWifiPrefs() {
        settings.goproSsid = goproSsid.text?.toString()?.trim().orEmpty()
        settings.goproPassword = goproPassword.text?.toString().orEmpty()
        appendLog("wifi prefs ssid=${settings.goproSsid}")
    }

    private fun runWifiJoin() {
        persistWifiPrefs()
        if (settings.goproSsid.isBlank()) {
            Toast.makeText(this, "请先填写 SSID", Toast.LENGTH_SHORT).show()
            return
        }
        Toast.makeText(this, "请在即将出现的「连接到设备」里点连接", Toast.LENGTH_LONG).show()
        lifecycleScope.launch {
            appendLog("wifi.join(Specifier)… ssid=${settings.goproSsid}")
            val wifi = GoProWifiCoordinator(this@MainActivity, BuildConfig.DEFAULT_HOME_PROBE_URL)
            appendLog("加入前：${wifi.primarySnapshot().summary}")
            val skill = WifiNetworkSkill(
                onProgress = { appendLog(it) },
                homeProbeUrl = BuildConfig.DEFAULT_HOME_PROBE_URL,
            )
            val ctx = SkillContext(applicationContext, app.edgeId, "local", Capabilities.WIFI_JOIN)
            val result = skill.executeWithActivity(
                Capabilities.WIFI_JOIN,
                emptyMap(),
                ctx,
                activity = this@MainActivity,
            )
            appendLog(if (result.ok) "OK ${result.message}" else "FAIL ${result.message}")
            appendLog("加入后：${wifi.primarySnapshot().summary}")
            if (result.ok) {
                Toast.makeText(this@MainActivity, result.message, Toast.LENGTH_LONG).show()
            } else {
                android.app.AlertDialog.Builder(this@MainActivity)
                    .setTitle("加入失败")
                    .setMessage(result.message ?: "unknown")
                    .setPositiveButton("改用系统设置加入") { _, _ -> runSystemAddNetwork() }
                    .setNegativeButton("关闭", null)
                    .show()
            }
        }
    }

    private fun runSystemAddNetwork() {
        persistWifiPrefs()
        if (settings.goproSsid.isBlank()) {
            Toast.makeText(this, "请先填写 SSID", Toast.LENGTH_SHORT).show()
            return
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            Toast.makeText(this, "需要 Android 11+", Toast.LENGTH_SHORT).show()
            return
        }
        try {
            val wifi = GoProWifiCoordinator(this, BuildConfig.DEFAULT_HOME_PROBE_URL)
            systemWifiBaseline = wifi.primarySnapshot()
            pendingSystemWifiSsid = settings.goproSsid
            val intent = wifi.buildAddNetworksIntent(
                settings.goproSsid,
                settings.goproPassword.ifBlank { null },
            )
            if (intent.resolveActivity(packageManager) == null) {
                appendLog("FAIL 无法解析 ACTION_WIFI_ADD_NETWORKS，改开 Wi‑Fi 设置")
                startActivity(android.content.Intent(Settings.ACTION_WIFI_SETTINGS))
                return
            }
            appendLog("启动系统添加网络（forResult）… 基准：${systemWifiBaseline?.summary}")
            Toast.makeText(this, "请在系统面板点「保存」", Toast.LENGTH_LONG).show()
            addWifiLauncher.launch(intent)
        } catch (t: Throwable) {
            appendLog("FAIL ${t.message}")
            Toast.makeText(this, t.message, Toast.LENGTH_LONG).show()
        }
    }

    private fun runWifiLeave() {
        lifecycleScope.launch {
            appendLog("wifi.leave …")
            val skill = WifiNetworkSkill(
                onProgress = { appendLog(it) },
                homeProbeUrl = BuildConfig.DEFAULT_HOME_PROBE_URL,
            )
            val ctx = SkillContext(applicationContext, app.edgeId, "local", Capabilities.WIFI_LEAVE)
            val result = skill.executeWithActivity(
                Capabilities.WIFI_LEAVE,
                emptyMap(),
                ctx,
                activity = this@MainActivity,
            )
            appendLog(if (result.ok) "OK ${result.message}" else "FAIL ${result.message}")
        }
    }

    private fun requestNeededPermissions() {
        val need = mutableListOf<String>()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) {
            need += Manifest.permission.ACCESS_FINE_LOCATION
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            need += Manifest.permission.RECORD_AUDIO
        }
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.NEARBY_WIFI_DEVICES)
                != PackageManager.PERMISSION_GRANTED
            ) {
                need += Manifest.permission.NEARBY_WIFI_DEVICES
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                need += Manifest.permission.POST_NOTIFICATIONS
            }
        }
        if (need.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, need.toTypedArray(), 1001)
        }
    }

    private fun refreshStatus() {
        statusText.text =
            "edgeId=${app.edgeId} · agent=${if (app.edgeAgent.running) "running" else "stopped"}"
    }

    private fun appendLog(message: String) {
        logLines.addFirst("${timeFmt.format(Date())} $message")
        while (logLines.size > 200) logLines.removeLast()
        logText.text = logLines.joinToString("\n")
    }

    override fun onJourneyChanged(journey: IntentJourney?) {
        runOnUiThread {
            journeyText.text = journey?.logisticsText() ?: "（暂无活跃意图）"
            ensureJourneyTicker(journey)
        }
    }

    override fun onStatus(message: String) {
        runOnUiThread {
            appendLog(message)
            refreshStatus()
        }
    }

    override fun onReport(report: ExecutionReport) {
        runOnUiThread { appendLog("report ${report.status} ${report.message}") }
    }

    override fun onEdgeIdAssigned(edgeId: String) {
        runOnUiThread {
            appendLog("edgeId=$edgeId")
            refreshStatus()
        }
    }

    override fun onIntentsPulled(snapshot: IntentsPullSnapshot) {
        runOnUiThread {
            appendLog(snapshot.summaryLine())
            app.seedJourneyFromPull(snapshot)
        }
    }

    override fun onCommandPipelineLog(message: String) {
        runOnUiThread { appendLog(message) }
    }
}
