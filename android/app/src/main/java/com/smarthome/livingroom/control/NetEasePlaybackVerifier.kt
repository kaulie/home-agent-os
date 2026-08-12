package com.smarthome.livingroom.control

import android.content.Context
import android.media.AudioManager
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import com.smarthome.livingroom.a11y.LivingRoomAccessibilityService
import com.smarthome.livingroom.debug.DebugLogStore

/**
 * Confirms NetEase actually started playback after a deep link — not just that startActivity succeeded.
 */
class NetEasePlaybackVerifier(
    context: Context,
) {
    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    enum class Result {
        /** UI or audio indicates target song is playing. */
        PLAYING,
        /** Audio active and no login gate (metadata unavailable). */
        PLAYING_WEAK,
        /** Login / auth screen blocking playback. */
        LOGIN_BLOCKED,
        /** Deep link opened but nothing playing. */
        NOT_PLAYING,
        /** Cannot verify (a11y off and no audio). */
        UNVERIFIED,
    }

    fun verifyAfterDeepLink(
        song: String,
        artist: String?,
        packageName: String,
        timeoutMs: Long = 18_000L,
    ): Result {
        val service = LivingRoomAccessibilityService.instance
        if (service == null) {
            DebugLogStore.append("[网易云] 深链后无法验证：无障碍未开启")
            SystemClock.sleep(minOf(timeoutMs, 4_000L))
            return if (audioManager.isMusicActive) Result.PLAYING_WEAK else Result.UNVERIFIED
        }

        service.setAutomationTarget(packageName)
        try {
            return verifyLoop(service, song, artist, timeoutMs)
        } finally {
            service.setAutomationTarget(null)
        }
    }

    private fun verifyLoop(
        service: LivingRoomAccessibilityService,
        song: String,
        artist: String?,
        timeoutMs: Long,
    ): Result {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        var loginDismissAttempts = 0
        var weakAudioHits = 0
        var playAssistAttempts = 0
        var lastLog = 0L

        while (SystemClock.uptimeMillis() < deadline) {
            if (isLoginGateShowing(service)) {
                DebugLogStore.append("[网易云] 检测到登录/确认页")
                if (loginDismissAttempts < 3 && tryDismissLoginGate(service)) {
                    loginDismissAttempts++
                    DebugLogStore.append("[网易云] 已尝试跳过登录 ($loginDismissAttempts/3)")
                    SystemClock.sleep(900)
                    continue
                }
                return Result.LOGIN_BLOCKED
            }

            val songKey = song.trim()
            if (songKey.isNotEmpty() && isSongVisible(service, song, artist)) {
                DebugLogStore.append("[网易云] 验证通过：界面可见「$songKey」")
                return Result.PLAYING
            }

            if (audioManager.isMusicActive) {
                weakAudioHits++
                if (weakAudioHits >= 2) {
                    DebugLogStore.append("[网易云] 验证通过：音频活跃${if (songKey.isEmpty()) "" else "（未读到歌名）"}")
                    return Result.PLAYING_WEAK
                }
            } else {
                weakAudioHits = 0
                if (playAssistAttempts < 4) {
                    if (tryClickPlayControl(service)) {
                        playAssistAttempts++
                        DebugLogStore.append("[网易云] 深链后辅助点播放 ($playAssistAttempts/4)")
                        SystemClock.sleep(900)
                        continue
                    }
                }
            }

            val now = SystemClock.uptimeMillis()
            if (now - lastLog > 3_000) {
                DebugLogStore.append(
                    "[网易云] 验证中… audio=${audioManager.isMusicActive} " +
                        "songOnScreen=${songKey.isNotEmpty() && hasSongText(service, songKey)}",
                )
                lastLog = now
            }

            SystemClock.sleep(450)
        }

        DebugLogStore.append("[网易云] 验证超时：未检测到播放")
        return Result.NOT_PLAYING
    }

    private fun hasSongText(service: LivingRoomAccessibilityService, song: String): Boolean =
        service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            val d = node.contentDescription?.toString().orEmpty()
            t.contains(song) || d.contains(song)
        }.isNotEmpty()

    private fun tryClickPlayControl(service: LivingRoomAccessibilityService): Boolean {
        val labels = listOf("播放全部", "立即播放", "开始播放", "播放", "Play")
        for (label in labels) {
            val nodes = service.findNodes { node ->
                val t = node.text?.toString()?.trim().orEmpty()
                val d = node.contentDescription?.toString()?.trim().orEmpty()
                (t == label || d == label) && !t.contains("最近播放")
            }
            for (node in nodes) {
                val how = service.clickNodeDetailed(node)
                if (how != null) {
                    DebugLogStore.append("[网易云] 辅助点击「$label」via $how")
                    return true
                }
            }
        }
        val playDesc = service.findNodes { node ->
            val d = node.contentDescription?.toString()?.lowercase().orEmpty()
            node.isClickable && (d.contains("play") || d == "播放")
        }
        for (node in playDesc) {
            val how = service.clickNodeDetailed(node)
            if (how != null) {
                DebugLogStore.append("[网易云] 辅助点击播放控件 via $how")
                return true
            }
        }
        return false
    }

    private fun isLoginGateShowing(service: LivingRoomAccessibilityService): Boolean {
        val markers = listOf(
            "确认登录",
            "登录后",
            "立即登录",
            "手机号登录",
            "请登录",
            "登录网易云",
            "微信登录",
            "QQ登录",
            "扫码登录",
            "账号登录",
            "登录解锁",
            "先登录",
        )
        return service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            val d = node.contentDescription?.toString().orEmpty()
            markers.any { m -> t.contains(m) || d.contains(m) }
        }.isNotEmpty()
    }

    private fun tryDismissLoginGate(service: LivingRoomAccessibilityService): Boolean {
        val labels = listOf(
            "稍后",
            "稍后再说",
            "暂不登录",
            "跳过",
            "取消",
            "暂不",
            "以后再说",
            "游客",
            "关闭",
        )
        for (label in labels) {
            val nodes = service.findNodes { node ->
                val t = node.text?.toString()?.trim().orEmpty()
                val d = node.contentDescription?.toString()?.trim().orEmpty()
                t == label || d == label || t.contains(label) || d.contains(label)
            }
            for (node in nodes) {
                val how = service.clickNodeDetailed(node)
                if (how != null) {
                    DebugLogStore.append("[网易云] 登录页点击「$label」via $how")
                    return true
                }
            }
        }
        service.performGlobalAction(android.accessibilityservice.AccessibilityService.GLOBAL_ACTION_BACK)
        DebugLogStore.append("[网易云] 登录页发送 BACK")
        SystemClock.sleep(400)
        return true
    }

    private fun isSongVisible(
        service: LivingRoomAccessibilityService,
        song: String,
        artist: String?,
    ): Boolean {
        val songKey = song.trim()
        if (songKey.isEmpty()) return false
        val artistKey = artist?.trim().orEmpty()
        val playerHints = listOf("暂停", "正在播放", "Play", "Pause", "歌词")
        val hasPlayerHint = service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            val d = node.contentDescription?.toString().orEmpty()
            playerHints.any { h -> t.contains(h) || d.contains(h, ignoreCase = true) }
        }.isNotEmpty()

        val songNodes = service.findNodes { node ->
            val t = node.text?.toString().orEmpty()
            val d = node.contentDescription?.toString().orEmpty()
            t.contains(songKey) || d.contains(songKey)
        }
        if (songNodes.isEmpty()) return false

        if (artistKey.isNotEmpty()) {
            val artistVisible = service.findNodes { node ->
                val t = node.text?.toString().orEmpty()
                val d = node.contentDescription?.toString().orEmpty()
                t.contains(artistKey) || d.contains(artistKey)
            }.isNotEmpty()
            if (artistVisible) return true
        }

        return hasPlayerHint || songNodes.any { isLikelyTitleNode(it) }
    }

    private fun isLikelyTitleNode(node: AccessibilityNodeInfo): Boolean {
        val t = node.text?.toString()?.trim().orEmpty()
        return t.isNotEmpty() && t.length <= 40
    }
}
