package com.smarthome.livingroom.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.smarthome.livingroom.BuildConfig
import com.smarthome.livingroom.R
import com.smarthome.livingroom.control.MusicController
import com.smarthome.livingroom.data.AckResult
import com.smarthome.livingroom.data.AppSettings
import com.smarthome.livingroom.data.CommandAction
import com.smarthome.livingroom.data.CommandApiClient
import com.smarthome.livingroom.data.MusicApp
import com.smarthome.livingroom.data.RemoteCommand
import com.smarthome.livingroom.debug.DebugLogStore
import com.smarthome.livingroom.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min

class CommandPollService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var settings: AppSettings
    private lateinit var api: CommandApiClient
    private lateinit var music: MusicController
    private var pollJob: Job? = null

    private var lastCommandAt = 0L
    private var lastIdleLogAt = 0L
    private var currentIntervalMs = BuildConfig.POLL_INTERVAL_MS
    private var nextRetryAt = 0L
    private var inFailureState = false
    private var lastFailureMessage: String? = null
    private val forceRetry = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        settings = AppSettings(this)
        api = CommandApiClient(settings)
        music = MusicController(this)
        val now = System.currentTimeMillis()
        lastCommandAt = now
        lastIdleLogAt = 0L
        currentIntervalMs = BuildConfig.POLL_INTERVAL_MS
        DebugLogStore.append("轮询服务已启动 device=${settings.deviceId} server=${settings.serverBaseUrl}")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startAsForeground()
        if (intent?.action == ACTION_RETRY_NOW) {
            forceRetry.set(true)
            DebugLogStore.append("立即重试：跳过等待，马上拉取")
            // Ensure loop is running
            if (pollJob?.isActive != true) {
                pollJob = scope.launch { pollLoop() }
            }
            broadcastUpdate(running = true)
            return START_STICKY
        }
        if (pollJob?.isActive != true) {
            pollJob = scope.launch { pollLoop() }
        }
        broadcastUpdate(running = true)
        return START_STICKY
    }

    override fun onDestroy() {
        DebugLogStore.append("轮询服务已停止")
        pollJob?.cancel()
        scope.cancel()
        broadcastUpdate(running = false)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startAsForeground() {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.service_notification_title))
            .setContentText(getString(R.string.service_notification_text))
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentIntent(open)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private suspend fun pollLoop() {
        while (scope.isActive) {
            var failed = false
            try {
                withContext(Dispatchers.IO) { pollOnce() }
                onPollSuccess()
            } catch (t: Throwable) {
                failed = true
                onPollFailure(t)
            }
            if (!scope.isActive) break
            awaitNextPoll(failed)
        }
    }

    private suspend fun awaitNextPoll(afterFailure: Boolean) {
        val waitMs = if (afterFailure) currentIntervalMs else BuildConfig.POLL_INTERVAL_MS
        if (!afterFailure) {
            currentIntervalMs = BuildConfig.POLL_INTERVAL_MS
        }
        nextRetryAt = System.currentTimeMillis() + waitMs
        broadcastUpdate(running = true)

        val endAt = nextRetryAt
        while (scope.isActive && System.currentTimeMillis() < endAt) {
            if (forceRetry.compareAndSet(true, false)) {
                nextRetryAt = 0L
                broadcastUpdate(running = true)
                return
            }
            delay(200L)
        }
        forceRetry.set(false)
    }

    private fun onPollSuccess() {
        if (inFailureState) {
            DebugLogStore.append("轮询恢复正常，间隔回到 ${formatDuration(BuildConfig.POLL_INTERVAL_MS)}")
        }
        inFailureState = false
        lastFailureMessage = null
        currentIntervalMs = BuildConfig.POLL_INTERVAL_MS
        nextRetryAt = 0L
        broadcastUpdate(running = true)
    }

    private fun onPollFailure(t: Throwable) {
        Log.w(TAG, "poll error: ${t.message}", t)
        val message = t.message ?: "unknown"
        settings.recordLastCommand("轮询失败: $message")

        val previousInterval = currentIntervalMs
        currentIntervalMs = if (!inFailureState) {
            BuildConfig.POLL_INTERVAL_MS * 2
        } else {
            min(currentIntervalMs * 2, MAX_BACKOFF_MS)
        }
        val shouldLog =
            !inFailureState || lastFailureMessage != message || previousInterval != currentIntervalMs
        inFailureState = true
        if (shouldLog) {
            DebugLogStore.append(
                "轮询失败: $message，${formatDuration(currentIntervalMs)}后重试",
            )
        }
        lastFailureMessage = message
        nextRetryAt = System.currentTimeMillis() + currentIntervalMs
        broadcastUpdate(running = true)
    }

    private fun pollOnce() {
        val commands = api.fetchPendingCommands()
        val now = System.currentTimeMillis()
        settings.lastPollAt = now
        settings.lastPollHadCommands = commands.isNotEmpty()

        if (commands.isEmpty()) {
            maybeLogIdle(now)
            broadcastUpdate(running = true)
            return
        }

        lastCommandAt = now
        DebugLogStore.append("收到 ${commands.size} 条指令")
        for (cmd in commands) {
            val detail = buildString {
                append("指令 id=${cmd.id} action=${cmd.action.wire} app=${cmd.app.wire}")
                if (!cmd.song.isNullOrBlank()) append(" song=${cmd.song}")
                if (!cmd.artist.isNullOrBlank()) append(" artist=${cmd.artist}")
                if (!cmd.uri.isNullOrBlank()) append(" uri=${cmd.uri}")
            }
            DebugLogStore.append(detail)
            val summary = formatCommandSummary(cmd)
            try {
                music.execute(cmd)
            } catch (t: Throwable) {
                Log.e(TAG, "command execute failed id=${cmd.id}", t)
                runCatching {
                    api.ack(
                        cmd.id,
                        AckResult(status = "error", message = t.message ?: "unknown"),
                    )
                }.onSuccess { newlyAcked ->
                    if (newlyAcked) {
                        DebugLogStore.append("执行失败 $summary: ${t.message}")
                    } else {
                        DebugLogStore.append(
                            "执行失败 $summary: ${t.message}（指令已不在队列）",
                        )
                    }
                }.onFailure { ackErr ->
                    DebugLogStore.append(
                        "执行失败 $summary: ${t.message}；确认也失败: ${ackErr.message}",
                    )
                }
                settings.recordLastCommand("执行失败 · $summary\n${t.message}")
                broadcastUpdate(running = true)
                continue
            }

            try {
                val newlyAcked = api.ack(cmd.id, AckResult(status = "ok", message = summary))
                if (newlyAcked) {
                    settings.recordLastCommand("执行成功 · $summary")
                    DebugLogStore.append("执行成功 $summary")
                } else {
                    settings.recordLastCommand("执行成功 · $summary\n（确认时已出队）")
                    DebugLogStore.append("执行成功 $summary，ack=404 已出队（可能重复拉取）")
                }
            } catch (t: Throwable) {
                Log.e(TAG, "ack failed after success id=${cmd.id}", t)
                settings.recordLastCommand("执行成功 · $summary\n确认失败: ${t.message}")
                DebugLogStore.append("执行成功 $summary，但确认失败: ${t.message}")
            }
            broadcastUpdate(running = true)
        }
    }

    private fun formatCommandSummary(cmd: RemoteCommand): String {
        val actionLabel = when (cmd.action) {
            CommandAction.LAUNCH -> "启动"
            CommandAction.PLAY -> "继续播放"
            CommandAction.PAUSE -> "暂停"
            CommandAction.PLAY_PAUSE -> "播放/暂停"
            CommandAction.NEXT -> "下一首"
            CommandAction.PREVIOUS -> "上一首"
            CommandAction.STOP -> "停止"
            CommandAction.PLAY_SONG -> "搜歌播放"
        }
        val appLabel = when (cmd.app) {
            MusicApp.NETEASE -> "网易云"
            MusicApp.SPOTIFY -> "Spotify"
        }
        return buildString {
            append("$actionLabel · $appLabel")
            val song = cmd.song?.trim().orEmpty()
            val artist = cmd.artist?.trim().orEmpty()
            when {
                song.isNotEmpty() && artist.isNotEmpty() -> append(" · 「$song - $artist」")
                song.isNotEmpty() -> append(" · 「$song」")
                artist.isNotEmpty() -> append(" · 歌手「$artist」")
            }
            val uri = cmd.uri?.trim().orEmpty()
            if (uri.isNotEmpty()) {
                val shortUri = if (uri.length > 48) uri.take(45) + "…" else uri
                append(" · $shortUri")
            }
            append(" · id=${cmd.id}")
        }
    }

    private fun maybeLogIdle(now: Long) {
        val anchor = maxOf(lastCommandAt, lastIdleLogAt)
        if (now - anchor < IDLE_LOG_INTERVAL_MS) return
        DebugLogStore.append("空指令（已连续 ${IDLE_LOG_INTERVAL_MS / 60_000} 分钟未收到任何指令）")
        lastIdleLogAt = now
    }

    private fun broadcastUpdate(running: Boolean) {
        sendBroadcast(
            Intent(ACTION_STATUS)
                .setPackage(packageName)
                .putExtra(EXTRA_RUNNING, running)
                .putExtra(EXTRA_LAST_POLL, settings.lastPollAt)
                .putExtra(EXTRA_LAST_POLL_HAD_COMMANDS, settings.lastPollHadCommands)
                .putExtra(EXTRA_LAST_CMD, settings.lastCommandSummary)
                .putExtra(EXTRA_LAST_CMD_AT, settings.lastCommandAt)
                .putExtra(EXTRA_IN_FAILURE, inFailureState && running)
                .putExtra(EXTRA_NEXT_RETRY_AT, nextRetryAt)
                .putExtra(EXTRA_RETRY_INTERVAL_MS, currentIntervalMs),
        )
    }

    companion object {
        const val CHANNEL_ID = "command_poll"
        const val ACTION_STATUS = "com.smarthome.livingroom.POLL_STATUS"
        const val ACTION_RETRY_NOW = "com.smarthome.livingroom.RETRY_NOW"
        const val EXTRA_RUNNING = "running"
        const val EXTRA_LAST_POLL = "last_poll"
        const val EXTRA_LAST_POLL_HAD_COMMANDS = "last_poll_had_commands"
        const val EXTRA_LAST_CMD = "last_cmd"
        const val EXTRA_LAST_CMD_AT = "last_cmd_at"
        const val EXTRA_IN_FAILURE = "in_failure"
        const val EXTRA_NEXT_RETRY_AT = "next_retry_at"
        const val EXTRA_RETRY_INTERVAL_MS = "retry_interval_ms"
        private const val NOTIFICATION_ID = 1001
        private const val IDLE_LOG_INTERVAL_MS = 10 * 60 * 1000L
        private const val MAX_BACKOFF_MS = 10 * 60 * 1000L
        private const val TAG = "CommandPollService"

        fun start(context: Context) {
            val intent = Intent(context, CommandPollService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, CommandPollService::class.java))
        }

        fun retryNow(context: Context) {
            val intent = Intent(context, CommandPollService::class.java).apply {
                action = ACTION_RETRY_NOW
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun formatDuration(ms: Long): String {
            val totalSec = (ms / 1000).coerceAtLeast(1)
            return when {
                totalSec < 60 -> "${totalSec} 秒"
                totalSec % 60L == 0L -> "${totalSec / 60} 分钟"
                else -> "${totalSec / 60} 分 ${totalSec % 60} 秒"
            }
        }
    }
}
