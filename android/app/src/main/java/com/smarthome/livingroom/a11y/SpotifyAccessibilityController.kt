package com.smarthome.livingroom.a11y

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.SystemClock
import android.util.Log
import android.view.accessibility.AccessibilityNodeInfo
import com.smarthome.livingroom.debug.DebugLogStore

/**
 * Drives Spotify TV/mobile via Accessibility: open search → type query → click result.
 */
class SpotifyAccessibilityController(
    private val context: Context,
) {
    fun playBySearch(song: String, artist: String?): Boolean {
        val service = LivingRoomAccessibilityService.instance
            ?: throw IllegalStateException("无障碍未开启")

        val query = listOfNotNull(song.trim(), artist?.trim()?.takeIf { it.isNotEmpty() })
            .joinToString(" ")
        require(query.isNotBlank()) { "song is required" }

        val pkg = resolveSpotifyPackage()
            ?: throw IllegalStateException("未安装 Spotify")

        DebugLogStore.append("Spotify 无障碍播放: $query @ $pkg")
        // Prefill search via deep link when possible, then click a result.
        val searchUri = "spotify:search:${android.net.Uri.encode(query)}"
        try {
            val intent = Intent(Intent.ACTION_VIEW, android.net.Uri.parse(searchUri)).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                setPackage(pkg)
            }
            context.startActivity(intent)
        } catch (_: Throwable) {
            launchPackage(pkg)
        }
        waitForWindow(service, pkg, 8_000)
        SystemClock.sleep(1_500)

        // If search box empty, try typing.
        val edits = service.findNodes { it.isEditable }
        if (edits.isNotEmpty()) {
            val edit = edits.first()
            edit.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
            service.setText(edit, query)
            SystemClock.sleep(1_200)
        }

        if (!clickResult(service, song, artist)) {
            val tree = service.dumpVisibleTree()
            DebugLogStore.append("Spotify 无障碍未点到结果\n$tree")
            throw IllegalStateException("Spotify 无障碍未点到「$song」")
        }
        SystemClock.sleep(800)
        clickByTexts(service, listOf("Play", "播放", "LISTEN NOW", "立即收听"))
        DebugLogStore.append("Spotify 无障碍：已点击结果")
        return true
    }

    private fun clickResult(
        service: LivingRoomAccessibilityService,
        song: String,
        artist: String?,
    ): Boolean {
        val songKey = song.trim()
        val artistKey = artist?.trim().orEmpty()
        val ranked = service.findNodes { node ->
            val blob = "${node.text} ${node.contentDescription}"
            blob.contains(songKey, ignoreCase = true)
        }.sortedByDescending { node ->
            val blob = "${node.text} ${node.contentDescription}"
            var score = 0
            if (blob.contains(songKey, true)) score += 10
            if (artistKey.isNotEmpty() && blob.contains(artistKey, true)) score += 8
            if (node.isClickable) score += 3
            score
        }
        for (node in ranked) {
            if (service.clickNode(node)) {
                DebugLogStore.append("Spotify 无障碍点击: ${node.text ?: node.contentDescription}")
                return true
            }
        }
        return false
    }

    private fun clickByTexts(service: LivingRoomAccessibilityService, texts: List<String>): Boolean {
        for (key in texts) {
            val nodes = service.findNodes {
                val t = it.text?.toString().orEmpty()
                val d = it.contentDescription?.toString().orEmpty()
                t.contains(key, true) || d.contains(key, true)
            }
            for (node in nodes) {
                if (service.clickNode(node)) return true
            }
        }
        return false
    }

    private fun waitForWindow(service: LivingRoomAccessibilityService, pkg: String, timeoutMs: Long) {
        val deadline = SystemClock.uptimeMillis() + timeoutMs
        while (SystemClock.uptimeMillis() < deadline) {
            val root = service.root()
            if (root != null && root.packageName?.toString() == pkg) return
            SystemClock.sleep(250)
        }
    }

    private fun resolveSpotifyPackage(): String? {
        val candidates = listOf("com.spotify.tv.android", "com.spotify.music")
        for (pkg in candidates) {
            if (isInstalled(pkg)) return pkg
        }
        return null
    }

    private fun isInstalled(packageName: String): Boolean =
        try {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }

    private fun launchPackage(packageName: String) {
        val launch = context.packageManager.getLaunchIntentForPackage(packageName)
            ?: throw IllegalStateException("无法启动 $packageName")
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(launch)
        Log.i(TAG, "launched $packageName")
    }

    companion object {
        private const val TAG = "SpotifyA11y"
    }
}
