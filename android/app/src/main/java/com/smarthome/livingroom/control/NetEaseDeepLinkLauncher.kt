package com.smarthome.livingroom.control

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.SystemClock
import android.util.Log
import com.smarthome.livingroom.debug.DebugLogStore

/**
 * Opens NetEase phone app via orpheus / https links with multiple strategies (TV 上 startActivity 常无反应).
 */
class NetEaseDeepLinkLauncher(
    private val context: Context,
) {
    data class OpenResult(
        val success: Boolean,
        val uri: String? = null,
        val method: String? = null,
        val packageName: String? = null,
        val detail: String? = null,
    )

    fun openSong(songId: Long, preferredPackage: String = PHONE_PACKAGE): OpenResult {
        val packages = buildPackageCandidates(preferredPackage)
        DebugLogStore.append("[网易云/深链] 已安装: ${packages.ifEmpty { listOf("无") }}")
        if (packages.isEmpty()) {
            return OpenResult(false, detail = "未安装手机版网易云")
        }

        val uris = songUriCandidates(songId)
        val errors = ArrayList<String>()

        for (pkg in packages) {
            for (uri in uris) {
                logIntentHandlers(uri, pkg)

                tryResolveExplicit(uri, pkg)?.let {
                    DebugLogStore.append("[网易云/深链] 成功 method=${it.method} uri=$uri pkg=$pkg")
                    waitForRedirect(it.detail)
                    return it
                }

                tryStartActivity(uri, pkg)?.let {
                    DebugLogStore.append("[网易云/深链] 成功 method=${it.method} uri=$uri pkg=$pkg")
                    waitForRedirect(null)
                    return it
                }

                tryIntentUri(songId, pkg)?.let {
                    DebugLogStore.append("[网易云/深链] 成功 method=${it.method} pkg=$pkg")
                    waitForRedirect(null)
                    return it
                }

                tryShellAm(uri, pkg)?.let {
                    DebugLogStore.append("[网易云/深链] 成功 method=${it.method} uri=$uri pkg=$pkg")
                    waitForRedirect(it.detail)
                    return it
                }

                errors += "$pkg×$uri"
            }

            warmLaunch(pkg)
            SystemClock.sleep(600)
        }

        DebugLogStore.append("[网易云/深链] 全部失败: ${errors.take(8).joinToString("; ")}")
        return OpenResult(false, detail = errors.take(4).joinToString("; "))
    }

    fun probeHandlers(songId: Long = 66842L): String {
        val pkg = PHONE_PACKAGE
        if (!isInstalled(pkg)) return "未安装 $pkg"
        val lines = ArrayList<String>()
        for (uri in songUriCandidates(songId)) {
            val count = queryActivities(uri, pkg).size
            lines += "$uri → $count 个 Activity"
        }
        return lines.joinToString("\n")
    }

    private fun buildPackageCandidates(preferred: String): List<String> {
        val out = LinkedHashSet<String>()
        if (isInstalled(preferred)) out.add(preferred)
        try {
            @Suppress("DEPRECATION")
            context.packageManager.getInstalledApplications(0).forEach { app ->
                val name = app.packageName
                val lower = name.lowercase()
                if (lower == PHONE_PACKAGE || lower == "com.netease.cloudmusic.lite") {
                    out.add(name)
                }
            }
        } catch (_: Throwable) {
        }
        return out.toList()
    }

    private fun songUriCandidates(songId: Long): List<String> = listOf(
        "orpheus://song/$songId/?autoplay=1",
        "orpheus://song/$songId?autoplay=1",
        "orpheus://song/$songId",
        "orpheus://song?id=$songId&autoplay=1",
        "orpheus://song?id=$songId",
        "https://music.163.com/song?id=$songId",
        "https://music.163.com/m/song/$songId",
    )

    /** RedirectActivity 跳转中；切勿再 warmLaunch 主界面（会打断深链）。 */
    private fun waitForRedirect(activityHint: String?) {
        DebugLogStore.append(
            "[网易云/深链] 等待 RedirectActivity 跳转" +
                (activityHint?.let { " ($it)" } ?: "") + "…",
        )
        SystemClock.sleep(2_800)
    }

    private fun warmLaunch(packageName: String) {
        if (!isInstalled(packageName)) return
        val launch = context.packageManager.getLaunchIntentForPackage(packageName) ?: return
        launch.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK or
                Intent.FLAG_ACTIVITY_REORDER_TO_FRONT,
        )
        try {
            context.startActivity(launch)
            DebugLogStore.append("[网易云/深链] 预热拉起 $packageName")
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/深链] 预热失败: ${t.message}")
        }
    }

    private fun logIntentHandlers(uri: String, packageName: String) {
        val acts = queryActivities(uri, packageName)
        if (acts.isEmpty()) {
            DebugLogStore.append("[网易云/深链] 无 handler: $uri @ $packageName")
        } else {
            DebugLogStore.append(
                "[网易云/深链] handler ${acts.size} 个: $uri @ $packageName → " +
                    acts.take(2).joinToString { it.activityInfo.name.substringAfterLast('.') },
            )
        }
    }

    private fun queryActivities(uri: String, packageName: String) =
        try {
            context.packageManager.queryIntentActivities(
                viewIntent(uri, packageName),
                PackageManager.MATCH_DEFAULT_ONLY,
            )
        } catch (_: Throwable) {
            emptyList()
        }

    private fun viewIntent(uri: String, packageName: String?) =
        Intent(Intent.ACTION_VIEW, Uri.parse(uri)).apply {
            addCategory(Intent.CATEGORY_DEFAULT)
            addCategory(Intent.CATEGORY_BROWSABLE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
            if (!packageName.isNullOrEmpty()) setPackage(packageName)
        }

    private fun tryResolveExplicit(uri: String, packageName: String): OpenResult? {
        val base = viewIntent(uri, packageName)
        val resolved = context.packageManager.resolveActivity(
            base,
            PackageManager.MATCH_DEFAULT_ONLY,
        ) ?: return null
        val intent = Intent(base).apply {
            component = ComponentName(
                resolved.activityInfo.packageName,
                resolved.activityInfo.name,
            )
        }
        return if (startSafe(intent, "explicit")) {
            OpenResult(true, uri, "explicit", packageName, resolved.activityInfo.name)
        } else {
            null
        }
    }

    private fun tryStartActivity(uri: String, packageName: String): OpenResult? {
        val intent = viewIntent(uri, packageName)
        return if (startSafe(intent, "startActivity")) {
            OpenResult(true, uri, "startActivity", packageName)
        } else {
            null
        }
    }

    private fun tryIntentUri(songId: Long, packageName: String): OpenResult? {
        val intentUri =
            "intent://song/$songId/#Intent;" +
                "scheme=orpheus;" +
                "package=$packageName;" +
                "S.autoplay=1;" +
                "end"
        return try {
            val intent = Intent.parseUri(intentUri, Intent.URI_INTENT_SCHEME).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            if (startSafe(intent, "intentUri")) {
                OpenResult(true, intentUri, "intentUri", packageName)
            } else {
                null
            }
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/深链] intentUri 解析失败: ${t.message}")
            null
        }
    }

    private fun tryShellAm(uri: String, packageName: String): OpenResult? {
        val escaped = uri.replace("'", "'\\''")
        val cmd = arrayOf(
            "sh", "-c",
            "am start -W -a android.intent.action.VIEW -d '$escaped' -p $packageName",
        )
        return try {
            val proc = Runtime.getRuntime().exec(cmd)
            val exit = proc.waitFor()
            val out = proc.inputStream.bufferedReader().readText().trim()
            val err = proc.errorStream.bufferedReader().readText().trim()
            DebugLogStore.append("[网易云/深链] shell am exit=$exit out=${out.take(120)} err=${err.take(80)}")
            if (exit == 0 || out.contains("Starting") || out.contains("Status: ok")) {
                OpenResult(true, uri, "shell_am", packageName, out.take(200))
            } else {
                null
            }
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/深链] shell am 不可用: ${t.message}")
            null
        }
    }

    private fun startSafe(intent: Intent, label: String): Boolean =
        try {
            context.startActivity(intent)
            Log.i(TAG, "$label ok: $intent")
            true
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云/深链] $label 失败: ${t.javaClass.simpleName} ${t.message}")
            false
        }

    private fun isInstalled(packageName: String): Boolean =
        try {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }

    companion object {
        private const val TAG = "NetEaseDeepLink"
        const val PHONE_PACKAGE = "com.netease.cloudmusic"
    }
}
