package com.smarthome.livingroom_v2.skill.music

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.SystemClock
import android.util.Log

/**
 * Opens NetEase phone app via orpheus / https links.
 * Rewritten for v2 — no v1 imports, no accessibility.
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

    fun openSong(songId: Long, preferredPackage: String = PHONE_PACKAGE): OpenResult =
        openUris(
            uris = songUriCandidates(songId),
            preferredPackage = preferredPackage,
            intentPath = "song/$songId",
        )

    /**
     * Open album via orpheus/https; if album deep link fails and [fallbackSongId] is set,
     * fall back to opening that track.
     */
    fun openAlbum(
        albumId: Long,
        fallbackSongId: Long? = null,
        preferredPackage: String = PHONE_PACKAGE,
    ): OpenResult {
        val albumResult = openUris(
            uris = albumUriCandidates(albumId),
            preferredPackage = preferredPackage,
            intentPath = "album/$albumId",
        )
        if (albumResult.success) return albumResult
        if (fallbackSongId != null && fallbackSongId > 0) {
            Log.w(TAG, "album deep link failed, fallback song=$fallbackSongId detail=${albumResult.detail}")
            return openSong(fallbackSongId, preferredPackage)
        }
        return albumResult
    }

    private fun openUris(
        uris: List<String>,
        preferredPackage: String,
        intentPath: String,
    ): OpenResult {
        val packages = buildPackageCandidates(preferredPackage)
        Log.i(TAG, "installed packages=${packages.ifEmpty { listOf("none") }}")
        if (packages.isEmpty()) {
            return OpenResult(
                false,
                detail = "未安装网易云 ($PHONE_PACKAGE / $TV_PACKAGE)",
            )
        }

        val errors = ArrayList<String>()

        for (pkg in packages) {
            for (uri in uris) {
                tryResolveExplicit(uri, pkg)?.let {
                    Log.i(TAG, "ok method=${it.method} uri=$uri pkg=$pkg")
                    waitForRedirect()
                    return it
                }
                tryIntentUri(intentPath, pkg)?.let {
                    Log.i(TAG, "ok method=${it.method} pkg=$pkg")
                    waitForRedirect()
                    return it
                }
                errors += "$pkg×$uri"
            }
            warmLaunch(pkg)
            SystemClock.sleep(600)
        }

        Log.w(TAG, "all failed: ${errors.take(8).joinToString("; ")}")
        return OpenResult(false, detail = errors.take(4).joinToString("; "))
    }

    private fun buildPackageCandidates(preferred: String): List<String> {
        val out = LinkedHashSet<String>()
        if (isInstalled(preferred)) out.add(preferred)
        if (isInstalled(TV_PACKAGE)) out.add(TV_PACKAGE)
        if (isInstalled(LITE_PACKAGE)) out.add(LITE_PACKAGE)
        try {
            @Suppress("DEPRECATION")
            context.packageManager.getInstalledApplications(0).forEach { app ->
                val name = app.packageName
                if (NetEasePlayPolicy.isNeteasePackage(name)) {
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

    private fun albumUriCandidates(albumId: Long): List<String> = listOf(
        "orpheus://album/$albumId/?autoplay=1",
        "orpheus://album/$albumId?autoplay=1",
        "orpheus://album/$albumId",
        "orpheus://album?id=$albumId&autoplay=1",
        "orpheus://album?id=$albumId",
        "https://music.163.com/album?id=$albumId",
        "https://music.163.com/m/album/$albumId",
    )

    private fun waitForRedirect() {
        SystemClock.sleep(2_800)
    }

    private fun warmLaunch(packageName: String) {
        if (!isInstalled(packageName)) return
        val launch = context.packageManager.getLaunchIntentForPackage(packageName) ?: return
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT)
        try {
            context.startActivity(launch)
        } catch (_: Throwable) {
        }
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
        return if (startSafe(intent)) {
            OpenResult(true, uri, "explicit", packageName, resolved.activityInfo.name)
        } else {
            null
        }
    }

    private fun tryIntentUri(path: String, packageName: String): OpenResult? {
        val intentUri =
            "intent://$path/#Intent;" +
                "scheme=orpheus;" +
                "package=$packageName;" +
                "S.autoplay=1;" +
                "end"
        return try {
            val intent = Intent.parseUri(intentUri, Intent.URI_INTENT_SCHEME).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            if (startSafe(intent)) {
                OpenResult(true, intentUri, "intentUri", packageName)
            } else {
                null
            }
        } catch (_: Throwable) {
            null
        }
    }

    private fun startSafe(intent: Intent): Boolean =
        try {
            context.startActivity(intent)
            true
        } catch (t: Throwable) {
            Log.w(TAG, "startActivity failed: ${t.message}")
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
        const val PHONE_PACKAGE = NetEasePlayPolicy.PHONE_PACKAGE
        const val LITE_PACKAGE = NetEasePlayPolicy.LITE_PACKAGE
        const val TV_PACKAGE = NetEasePlayPolicy.TV_PACKAGE
    }
}
