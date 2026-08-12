package com.smarthome.livingroom.ui

import android.Manifest
import android.content.BroadcastReceiver
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.widget.SwitchCompat
import androidx.core.content.ContextCompat
import com.smarthome.livingroom.a11y.LivingRoomAccessibilityService
import com.smarthome.livingroom.a11y.NetEaseAccessibilityController
import com.smarthome.livingroom.R
import com.smarthome.livingroom.control.BluetoothSpeakerConnector
import com.smarthome.livingroom.control.MusicController
import com.smarthome.livingroom.data.AppSettings
import com.smarthome.livingroom.data.CommandAction
import com.smarthome.livingroom.data.MusicApp
import com.smarthome.livingroom.data.RemoteCommand
import com.smarthome.livingroom.debug.DebugLogStore
import com.smarthome.livingroom.service.CommandPollService
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private lateinit var settings: AppSettings
    private lateinit var statusText: TextView
    private lateinit var retryHintText: TextView
    private lateinit var pollingSwitch: SwitchCompat
    private lateinit var deviceInput: EditText
    private lateinit var serverInput: EditText
    private lateinit var lastPollText: TextView
    private lateinit var lastCommandText: TextView
    private lateinit var pageScroll: ScrollView
    private lateinit var debugLogText: TextView
    private lateinit var debugLogScroll: ScrollView
    private lateinit var btnRetryNow: Button
    private lateinit var musicController: MusicController
    private val bluetoothSpeakerConnector by lazy { BluetoothSpeakerConnector(this) }
    private var ignoreSwitchCallback = false
    private val localActionExecutor = Executors.newSingleThreadExecutor()

    private val requestBluetoothConnect =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                runConnectWillenSpeaker()
            } else {
                DebugLogStore.append("[蓝牙] 用户拒绝 BLUETOOTH_CONNECT 权限")
                Toast.makeText(this, "需要蓝牙权限才能连接 WILLEN", Toast.LENGTH_LONG).show()
            }
        }

    private var serviceRunning = false
    private var inFailure = false
    private var nextRetryAt = 0L

    private val mainHandler = Handler(Looper.getMainLooper())
    private val onDebugLogChanged: () -> Unit = {
        mainHandler.post { refreshDebugLog() }
    }
    private val countdownTick = object : Runnable {
        override fun run() {
            updateRetryHint()
            if (serviceRunning && inFailure && nextRetryAt > System.currentTimeMillis()) {
                mainHandler.postDelayed(this, 500L)
            }
        }
    }

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != CommandPollService.ACTION_STATUS) return
            serviceRunning = intent.getBooleanExtra(CommandPollService.EXTRA_RUNNING, false)
            inFailure = intent.getBooleanExtra(CommandPollService.EXTRA_IN_FAILURE, false)
            nextRetryAt = intent.getLongExtra(CommandPollService.EXTRA_NEXT_RETRY_AT, 0L)
            val lastPoll = intent.getLongExtra(CommandPollService.EXTRA_LAST_POLL, settings.lastPollAt)
            val lastCmd = intent.getStringExtra(CommandPollService.EXTRA_LAST_CMD)
                ?: settings.lastCommandSummary
            val lastCmdAt = intent.getLongExtra(
                CommandPollService.EXTRA_LAST_CMD_AT,
                settings.lastCommandAt,
            )
            val pollHadCommands = intent.getBooleanExtra(
                CommandPollService.EXTRA_LAST_POLL_HAD_COMMANDS,
                settings.lastPollHadCommands,
            )
            render(serviceRunning, lastPoll, lastCmd, lastCmdAt, pollHadCommands)
            // Keep switch aligned with user preference, not transient service lifecycle.
            setSwitchChecked(settings.pollingEnabled)
            scheduleCountdown()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        settings = AppSettings(this)
        musicController = MusicController(this)
        val netEaseA11y = NetEaseAccessibilityController(this)

        statusText = findViewById(R.id.statusText)
        retryHintText = findViewById(R.id.retryHintText)
        pollingSwitch = findViewById(R.id.pollingSwitch)
        deviceInput = findViewById(R.id.deviceInput)
        serverInput = findViewById(R.id.serverInput)
        lastPollText = findViewById(R.id.lastPollText)
        lastCommandText = findViewById(R.id.lastCommandText)
        pageScroll = findViewById(R.id.pageScroll)
        debugLogText = findViewById(R.id.debugLogText)
        debugLogScroll = findViewById(R.id.debugLogScroll)
        btnRetryNow = findViewById(R.id.btnRetryNow)

        deviceInput.setText(settings.deviceId)
        serverInput.setText(settings.serverBaseUrl)

        // Default: switch off, do not poll. Stop any leftover service from a previous run.
        if (!settings.pollingEnabled) {
            CommandPollService.stop(this)
        }
        setSwitchChecked(settings.pollingEnabled)

        findViewById<Button>(R.id.btnSave).setOnClickListener { saveConfig() }
        findViewById<Button>(R.id.btnClearLog).setOnClickListener {
            DebugLogStore.clear()
            refreshDebugLog()
        }
        findViewById<Button>(R.id.btnCopyLog).setOnClickListener { copyDebugLog() }
        btnRetryNow.setOnClickListener { onRetryNow() }
        findViewById<Button>(R.id.btnGlobalPause).setOnClickListener {
            runGlobalMediaAction(CommandAction.PAUSE, "全局暂停")
        }
        findViewById<Button>(R.id.btnGlobalPlay).setOnClickListener {
            runGlobalMediaAction(CommandAction.PLAY, "全局继续")
        }
        findViewById<Button>(R.id.btnSpotifyLaunch).setOnClickListener {
            runSpotifyLocalAction(CommandAction.LAUNCH, "启动 Spotify")
        }
        val spotifySongInput = findViewById<EditText>(R.id.spotifySongInput)
        val spotifyArtistInput = findViewById<EditText>(R.id.spotifyArtistInput)
        val spotifyClientIdInput = findViewById<EditText>(R.id.spotifyClientIdInput)
        val spotifyClientSecretInput = findViewById<EditText>(R.id.spotifyClientSecretInput)
        spotifyClientIdInput.setText(settings.spotifyClientId)
        spotifyClientSecretInput.setText(settings.spotifyClientSecret)
        findViewById<Button>(R.id.btnSpotifyPlaySong).setOnClickListener {
            settings.spotifyClientId = spotifyClientIdInput.text?.toString().orEmpty()
            settings.spotifyClientSecret = spotifyClientSecretInput.text?.toString().orEmpty()
            val song = spotifySongInput.text?.toString()?.trim().orEmpty()
            val artist = spotifyArtistInput.text?.toString()?.trim().orEmpty()
            if (song.isEmpty()) {
                Toast.makeText(this, "请填写歌名", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            runSpotifyPlaySong(song, artist.ifEmpty { null })
        }
        val neteaseSongInput = findViewById<EditText>(R.id.neteaseSongInput)
        val neteaseArtistInput = findViewById<EditText>(R.id.neteaseArtistInput)
        findViewById<Button>(R.id.btnNeteasePresetPipizhanji).setOnClickListener {
            neteaseSongInput.setText("披荆斩棘")
            neteaseArtistInput.setText("")
        }
        findViewById<Button>(R.id.btnNeteasePresetShinian).setOnClickListener {
            neteaseSongInput.setText("十年")
            neteaseArtistInput.setText("陈奕迅")
        }
        findViewById<Button>(R.id.btnNeteasePlaySong).setOnClickListener {
            val parsed = com.smarthome.livingroom.control.SongQueryParser.parse(
                neteaseSongInput.text?.toString(),
                neteaseArtistInput.text?.toString(),
            )
            if (parsed.song.isEmpty()) {
                Toast.makeText(this, "请填写歌名", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            runNeteasePlaySong(parsed.song, parsed.artist)
        }
        findViewById<Button>(R.id.btnNeteaseDeepLinkTest).setOnClickListener {
            localActionExecutor.execute {
                try {
                    val ok = musicController.testNetEasePhoneDeepLink(66842L)
                    runOnUiThread {
                        Toast.makeText(
                            this,
                            if (ok) "深链测试成功" else "深链测试失败，见调试日志",
                            Toast.LENGTH_LONG,
                        ).show()
                    }
                } catch (t: Throwable) {
                    DebugLogStore.append("深链测试异常: ${t.message}")
                }
            }
        }
        findViewById<Button>(R.id.btnConnectWillen).setOnClickListener {
            connectWillenSpeaker()
        }
        findViewById<Button>(R.id.btnEnableA11y).setOnClickListener {
            DebugLogStore.append(
                if (LivingRoomAccessibilityService.isConnected()) {
                    "无障碍已开启"
                } else {
                    "请在系统设置中开启「客厅中控」无障碍服务"
                },
            )
            NetEaseAccessibilityController.openAccessibilitySettings(this)
        }
        findViewById<Button>(R.id.btnDumpA11y).setOnClickListener {
            localActionExecutor.execute {
                try {
                    // Bring NetEase forward first so dump is useful.
                    val launch = packageManager.getLaunchIntentForPackage("com.netease.cloudmusic")
                        ?: packageManager.getLaunchIntentForPackage("com.netease.cloudmusic.tv")
                    if (launch != null) {
                        launch.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK)
                        startActivity(launch)
                        Thread.sleep(2500)
                    }
                    netEaseA11y.dumpUi()
                } catch (t: Throwable) {
                    DebugLogStore.append("导出节点失败: ${t.message}")
                }
            }
        }
        pollingSwitch.setOnCheckedChangeListener { _, isChecked ->
            if (ignoreSwitchCallback) return@setOnCheckedChangeListener
            onPollingToggled(isChecked)
        }

        val shouldPoll = settings.pollingEnabled
        serviceRunning = false
        renderFromSettings(running = false)
        refreshDebugLog()
        if (shouldPoll) {
            serviceRunning = true
            renderFromSettings(running = true)
            CommandPollService.start(this)
        } else {
            DebugLogStore.append("拉取开关默认关闭，不拉取远端指令")
        }
        DebugLogStore.append(
            if (LivingRoomAccessibilityService.isConnected()) {
                "无障碍：已开启"
            } else {
                "无障碍：未开启（网易云搜歌请先点「打开无障碍设置」）"
            },
        )
        updateRetryButtonEnabled()
    }

    override fun onStart() {
        super.onStart()
        DebugLogStore.addListener(onDebugLogChanged)
        refreshDebugLog()
        ContextCompat.registerReceiver(
            this,
            statusReceiver,
            IntentFilter(CommandPollService.ACTION_STATUS),
            ContextCompat.RECEIVER_NOT_EXPORTED,
        )
    }

    override fun onStop() {
        mainHandler.removeCallbacks(countdownTick)
        DebugLogStore.removeListener(onDebugLogChanged)
        unregisterReceiver(statusReceiver)
        super.onStop()
    }

    private fun connectWillenSpeaker() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) !=
            android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            requestBluetoothConnect.launch(Manifest.permission.BLUETOOTH_CONNECT)
            return
        }
        runConnectWillenSpeaker()
    }

    private fun runConnectWillenSpeaker() {
        DebugLogStore.append("[蓝牙] 开始连接 WILLEN…")
        localActionExecutor.execute {
            val result = bluetoothSpeakerConnector.connectBondedSpeaker()
            mainHandler.post {
                Toast.makeText(
                    this,
                    if (result.success) {
                        "WILLEN 已连接"
                    } else {
                        result.message
                    },
                    Toast.LENGTH_LONG,
                ).show()
            }
        }
    }

    private fun runNeteasePlaySong(song: String, artist: String?) {
        val label = if (artist.isNullOrBlank()) {
            "网易云播放「$song」"
        } else {
            "网易云播放「$song - $artist」"
        }
        DebugLogStore.append("本地测试：$label")
        localActionExecutor.execute {
            try {
                val command = RemoteCommand(
                    id = "local-play_song-${System.currentTimeMillis()}",
                    action = CommandAction.PLAY_SONG,
                    app = MusicApp.NETEASE,
                    song = song,
                    artist = artist,
                )
                musicController.execute(command)
                DebugLogStore.append("本地测试成功：$label")
                mainHandler.post {
                    Toast.makeText(this, "$label 已发送", Toast.LENGTH_SHORT).show()
                }
            } catch (t: Throwable) {
                DebugLogStore.append("本地测试失败：$label — ${t.message}")
                mainHandler.post {
                    Toast.makeText(this, "$label 失败: ${t.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun runSpotifyPlaySong(song: String, artist: String?) {
        val label = if (artist.isNullOrBlank()) {
            "Spotify 播放「$song」"
        } else {
            "Spotify 播放「$song - $artist」"
        }
        DebugLogStore.append("本地测试：$label")
        localActionExecutor.execute {
            try {
                val command = RemoteCommand(
                    id = "local-spotify-play_song-${System.currentTimeMillis()}",
                    action = CommandAction.PLAY_SONG,
                    app = MusicApp.SPOTIFY,
                    song = song,
                    artist = artist,
                )
                musicController.execute(command)
                DebugLogStore.append("本地测试成功：$label")
                mainHandler.post {
                    Toast.makeText(this, "$label 已发送", Toast.LENGTH_SHORT).show()
                }
            } catch (t: Throwable) {
                DebugLogStore.append("本地测试失败：$label — ${t.message}")
                mainHandler.post {
                    Toast.makeText(this, "$label 失败: ${t.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun runSpotifyLocalAction(action: CommandAction, label: String) {
        runLocalMusicAction(action, MusicApp.SPOTIFY, label)
    }

    /** System media keys for whichever app currently holds audio focus. */
    private fun runGlobalMediaAction(action: CommandAction, label: String) {
        // app field is required by RemoteCommand but ignored by media-key dispatch routing
        runLocalMusicAction(action, MusicApp.NETEASE, label)
    }

    private fun runLocalMusicAction(action: CommandAction, app: MusicApp, label: String) {
        DebugLogStore.append("本地测试：$label")
        localActionExecutor.execute {
            try {
                val command = RemoteCommand(
                    id = "local-${action.wire}-${System.currentTimeMillis()}",
                    action = action,
                    app = app,
                )
                musicController.execute(command)
                DebugLogStore.append("本地测试成功：$label")
                mainHandler.post {
                    Toast.makeText(this, "$label 已发送", Toast.LENGTH_SHORT).show()
                }
            } catch (t: Throwable) {
                DebugLogStore.append("本地测试失败：$label — ${t.message}")
                mainHandler.post {
                    Toast.makeText(this, "$label 失败: ${t.message}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun onRetryNow() {
        if (!settings.pollingEnabled) {
            Toast.makeText(this, "请先打开「拉取远端指令」", Toast.LENGTH_SHORT).show()
            return
        }
        if (!saveConfig(showToast = false)) return
        CommandPollService.retryNow(this)
        Toast.makeText(this, "正在立即重试…", Toast.LENGTH_SHORT).show()
    }

    private fun onPollingToggled(enabled: Boolean) {
        if (enabled) {
            if (!saveConfig(showToast = false)) {
                setSwitchChecked(false)
                return
            }
            settings.pollingEnabled = true
            DebugLogStore.append("用户打开拉取开关，开始轮询")
            CommandPollService.start(this)
            serviceRunning = true
            renderFromSettings(running = true)
        } else {
            settings.pollingEnabled = false
            DebugLogStore.append("用户关闭拉取开关，停止轮询")
            CommandPollService.stop(this)
            serviceRunning = false
            inFailure = false
            nextRetryAt = 0L
            renderFromSettings(running = false)
            updateRetryHint()
        }
        updateRetryButtonEnabled()
    }

    private fun setSwitchChecked(checked: Boolean) {
        if (pollingSwitch.isChecked == checked) return
        ignoreSwitchCallback = true
        pollingSwitch.isChecked = checked
        ignoreSwitchCallback = false
    }

    private fun saveConfig(showToast: Boolean = true): Boolean {
        val device = deviceInput.text?.toString()?.trim().orEmpty()
        val server = serverInput.text?.toString()?.trim().orEmpty()
        if (device.isEmpty() || server.isEmpty()) {
            Toast.makeText(this, "设备 ID 和服务器地址不能为空", Toast.LENGTH_SHORT).show()
            return false
        }
        settings.deviceId = device
        settings.serverBaseUrl = server
        findViewById<EditText>(R.id.spotifyClientIdInput)?.let {
            settings.spotifyClientId = it.text?.toString().orEmpty()
        }
        findViewById<EditText>(R.id.spotifyClientSecretInput)?.let {
            settings.spotifyClientSecret = it.text?.toString().orEmpty()
        }
        DebugLogStore.append("已保存配置 device=$device server=$server")
        if (showToast) {
            Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show()
        }
        return true
    }

    private fun renderFromSettings(running: Boolean) {
        render(
            running = running,
            lastPoll = settings.lastPollAt,
            lastCmd = settings.lastCommandSummary,
            lastCmdAt = settings.lastCommandAt,
            pollHadCommands = settings.lastPollHadCommands,
        )
    }

    private fun render(
        running: Boolean,
        lastPoll: Long,
        lastCmd: String,
        lastCmdAt: Long,
        pollHadCommands: Boolean,
    ) {
        statusText.text = when {
            !running -> "服务状态：未拉取"
            inFailure -> "服务状态：轮询失败（退避中）"
            else -> "服务状态：轮询中（每 10 秒）"
        }
        statusText.setTextColor(
            ContextCompat.getColor(
                this,
                if (inFailure && running) R.color.danger else R.color.accent,
            ),
        )
        lastPollText.text = when {
            lastPoll <= 0L -> "最近轮询：—"
            inFailure -> "最近轮询：${formatTime(lastPoll)}（失败）"
            pollHadCommands -> "最近轮询：${formatTime(lastPoll)}（收到指令）"
            else -> "最近轮询：${formatTime(lastPoll)}（无新指令）"
        }
        lastCommandText.text = when {
            lastCmd.isBlank() || lastCmd == "—" -> "最近指令：—"
            // Successful empty poll: don't present a stale error as "this round"
            !inFailure && lastPoll > 0L && !pollHadCommands -> {
                val previous = if (lastCmdAt > 0L) {
                    "上次结果：[${formatTime(lastCmdAt)}] $lastCmd"
                } else {
                    "上次结果：$lastCmd"
                }
                "最近指令：本轮无新指令\n$previous"
            }
            lastPoll <= 0L -> {
                val stamped = if (lastCmdAt > 0L) {
                    "[${formatTime(lastCmdAt)}] $lastCmd"
                } else {
                    lastCmd
                }
                "最近指令（缓存）：$stamped"
            }
            lastCmdAt > 0L -> "最近指令：[${formatTime(lastCmdAt)}] $lastCmd"
            else -> "最近指令：$lastCmd"
        }
        updateRetryHint()
        updateRetryButtonEnabled()
    }

    private fun scheduleCountdown() {
        mainHandler.removeCallbacks(countdownTick)
        if (serviceRunning && inFailure && nextRetryAt > System.currentTimeMillis()) {
            mainHandler.post(countdownTick)
        } else {
            updateRetryHint()
        }
    }

    private fun updateRetryHint() {
        if (!serviceRunning || !inFailure || nextRetryAt <= 0L) {
            retryHintText.visibility = View.GONE
            retryHintText.text = ""
            return
        }
        val remainMs = nextRetryAt - System.currentTimeMillis()
        retryHintText.visibility = View.VISIBLE
        retryHintText.text = if (remainMs <= 0L) {
            "即将重试…"
        } else {
            "${CommandPollService.formatDuration(remainMs)}后重试"
        }
    }

    private fun updateRetryButtonEnabled() {
        btnRetryNow.isEnabled = settings.pollingEnabled
        btnRetryNow.alpha = if (settings.pollingEnabled) 1f else 0.45f
    }

    private fun copyDebugLog() {
        val lines = DebugLogStore.snapshot()
        val text = if (lines.isEmpty()) {
            debugLogText.text?.toString().orEmpty()
        } else {
            lines.joinToString("\n")
        }
        if (text.isBlank() || text == "等待操作…") {
            Toast.makeText(this, "暂无日志可复制", Toast.LENGTH_SHORT).show()
            return
        }
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        clipboard.setPrimaryClip(ClipData.newPlainText("客厅中控调试日志", text))
        Toast.makeText(this, "已复制 ${lines.size.coerceAtLeast(1)} 行日志到剪贴板", Toast.LENGTH_SHORT).show()
    }

    private fun refreshDebugLog() {
        val followLogTail = isNearBottom(debugLogScroll)
        val lines = DebugLogStore.snapshot()
        debugLogText.text = if (lines.isEmpty()) "等待操作…" else lines.joinToString("\n")

        // Log lives in the right pane; only auto-follow when already near the bottom.
        if (!followLogTail) return
        debugLogScroll.post {
            val child = debugLogScroll.getChildAt(0)
            val max = ((child?.height ?: 0) - debugLogScroll.height).coerceAtLeast(0)
            debugLogScroll.scrollTo(0, max)
        }
    }

    private fun isNearBottom(scrollView: ScrollView, thresholdPx: Int = 80): Boolean {
        val child = scrollView.getChildAt(0) ?: return true
        val maxScroll = (child.height - scrollView.height).coerceAtLeast(0)
        if (maxScroll <= 0) return true
        return scrollView.scrollY >= maxScroll - thresholdPx
    }

    private fun formatTime(epochMs: Long): String {
        if (epochMs <= 0L) return "—"
        return SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(epochMs))
    }
}
