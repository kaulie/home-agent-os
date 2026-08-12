package com.smarthome.livingroom.control

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.net.Uri
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import com.smarthome.livingroom.a11y.LivingRoomAccessibilityService
import com.smarthome.livingroom.a11y.NetEaseAccessibilityController
import com.smarthome.livingroom.a11y.SpotifyAccessibilityController
import com.smarthome.livingroom.data.AppSettings
import com.smarthome.livingroom.data.CommandAction
import com.smarthome.livingroom.data.MusicApp
import com.smarthome.livingroom.data.RemoteCommand
import com.smarthome.livingroom.debug.DebugLogStore

/**
 * Executes music commands against Spotify / NetEase apps installed on Chromecast TV.
 *
 * [CommandAction.PLAY_SONG]: runs only the app specified in [RemoteCommand.app] (no cross-fallback).
 */
class MusicController(
    private val context: Context,
    private val settings: AppSettings = AppSettings(context),
    private val netEaseSearch: NetEaseSearchClient = NetEaseSearchClient(),
    private val netEaseA11y: NetEaseAccessibilityController = NetEaseAccessibilityController(context),
    private val spotifyA11y: SpotifyAccessibilityController = SpotifyAccessibilityController(context),
    private val netEasePlaybackVerifier: NetEasePlaybackVerifier = NetEasePlaybackVerifier(context),
    private val netEaseDeepLink: NetEaseDeepLinkLauncher = NetEaseDeepLinkLauncher(context),
) {
    private val audioManager =
        context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    fun execute(command: RemoteCommand) {
        Log.i(
            TAG,
            "execute id=${command.id} action=${command.action} app=${command.app} " +
                "song=${command.song} artist=${command.artist} uri=${command.uri}",
        )
        when (command.action) {
            CommandAction.LAUNCH -> launchApp(command.app, command.uri)
            CommandAction.PLAY -> dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY, command.app)
            CommandAction.PAUSE -> dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PAUSE, command.app)
            CommandAction.PLAY_PAUSE -> dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE, command.app)
            CommandAction.NEXT -> dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_NEXT, command.app)
            CommandAction.PREVIOUS -> dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PREVIOUS, command.app)
            CommandAction.STOP -> dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_STOP, command.app)
            CommandAction.PLAY_SONG -> playSong(command)
        }
    }

    private fun playSong(command: RemoteCommand) {
        when (command.app) {
            MusicApp.NETEASE -> playSongForApp(command, ::tryPlayNetEaseBySearch, ::tryPlayNetEaseByUri, "网易云")
            MusicApp.SPOTIFY -> playSongForApp(command, ::tryPlaySpotifyBySearch, ::tryPlaySpotifyByUri, "Spotify")
        }
    }

    private fun playSongForApp(
        command: RemoteCommand,
        search: (String, String?) -> Boolean,
        byUri: (String) -> Boolean,
        appLabel: String,
    ) {
        if (!command.uri.isNullOrBlank()) {
            if (byUri(command.uri)) return
            val msg = "[$appLabel] 指定 uri 播放失败: ${command.uri}"
            DebugLogStore.append(msg)
            throw IllegalStateException(msg)
        }

        val parsed = SongQueryParser.parse(command.song, command.artist)
        val songName = parsed.song
        if (songName.isEmpty()) {
            throw IllegalArgumentException("play_song 需要 song（歌名；可选在后面加空格和歌手）")
        }
        val artist = parsed.artist
        if (command.song?.contains(' ') == true && command.artist.isNullOrBlank()) {
            DebugLogStore.append("[解析] 「${command.song}」→ 歌名=$songName 歌手=${artist ?: "无"}")
        }
        val label = "「$songName${artist?.let { " - $it" } ?: ""}」"
        DebugLogStore.append("—— [$appLabel] 开始搜歌播放 $label ——")

        val ok = try {
            search(songName, artist)
        } catch (t: Throwable) {
            DebugLogStore.append("[$appLabel] 播放失败: ${t.message}")
            false
        }
        if (ok) {
            DebugLogStore.append("[结果] 成功 · $appLabel $label")
            return
        }

        val msg = "[结果] 播放不成功：$appLabel 未能播放 $label"
        DebugLogStore.append(msg)
        throw IllegalStateException(msg)
    }

    private fun tryPlayNetEaseByUri(uri: String): Boolean {
        val packages = resolveNetEaseDeepLinkPackages()
        val id = extractNetEaseSongId(uri)
        if (id != null && openNetEaseInInstalledApp(id, packages)) {
            SystemClock.sleep(800)
            dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY, MusicApp.NETEASE)
            return confirmNetEaseDeepLinkPlayback(
                song = "",
                artist = null,
                pkg = packages.first(),
            )
        }
        val errors = mutableListOf<String>()
        return tryOpenUriInPackages(uri, packages, errors)
    }

    /**
     * NetEase order:
     * 1) API search
     * 2) Phone app deep link (orpheus://) — TV 版不支持 scheme
     * 3) Accessibility
     */
    private fun tryPlayNetEaseBySearch(song: String, artist: String?): Boolean {
        val deepLinkPkgs = resolveNetEaseDeepLinkPackages()
        DebugLogStore.append(
            "[网易云] 步骤1/4 API搜索… 深链目标=${deepLinkPkgs.ifEmpty { listOf("手机版未安装") }}",
        )

        var hit: NetEaseSongHit? = null
        try {
            hit = netEaseSearch.searchBest(song, artist)
            DebugLogStore.append("[网易云] API命中: ${hit.name} - ${hit.artists} (#${hit.id})")
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云] API未找到: ${t.message}")
        }

        if (hit != null && deepLinkPkgs.isNotEmpty()) {
            DebugLogStore.append("[网易云] 步骤2/4 手机版深链打开 #${hit.id}")
            if (openNetEaseInInstalledApp(hit.id, deepLinkPkgs)) {
                repeat(3) {
                    dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY, MusicApp.NETEASE)
                    SystemClock.sleep(700)
                }
                when (
                    confirmNetEaseDeepLinkPlayback(
                        song = hit.name,
                        artist = hit.artists,
                        pkg = deepLinkPkgs.first(),
                    )
                ) {
                    true -> return true
                    false -> DebugLogStore.append("[网易云] 深链已打开但未确认播放，进入无障碍")
                }
            } else {
                DebugLogStore.append("[网易云] 手机版深链失败，进入无障碍")
            }
        } else if (hit != null) {
            DebugLogStore.append("[网易云] 无手机版包，跳过深链")
        } else {
            DebugLogStore.append("[网易云] 无 API 命中，进入无障碍")
        }

        DebugLogStore.append("[网易云] 步骤3/4 无障碍流程开始")
        if (!LivingRoomAccessibilityService.isConnected()) {
            DebugLogStore.append("[网易云] 无障碍未开启，跳过。网易云整段结束=失败")
            return false
        }
        return try {
            val ok = netEaseA11y.playBySearch(song, artist)
            if (ok) {
                DebugLogStore.append("[网易云] 无障碍流程结束=成功（各步骤均确认）")
            } else {
                DebugLogStore.append("[网易云] 无障碍流程结束=失败（playBySearch 返回 false）")
            }
            ok
        } catch (t: Throwable) {
            DebugLogStore.append("[网易云] 无障碍流程结束=失败: ${t.message}")
            false
        }
    }

    private fun tryPlaySpotifyByUri(uri: String): Boolean {
        val packages = preferredPackages(MusicApp.SPOTIFY).filter { isInstalled(it) }
        val errors = mutableListOf<String>()
        if (tryOpenUriInPackages(uri, packages, errors)) {
            SystemClock.sleep(1200)
            dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY, MusicApp.SPOTIFY)
            return true
        }
        return false
    }

    private fun tryPlaySpotifyBySearch(song: String, artist: String?): Boolean {
        val packages = preferredPackages(MusicApp.SPOTIFY).filter { isInstalled(it) }
        DebugLogStore.append("[Spotify] 开始… 包=${packages.ifEmpty { listOf("无") }}")

        if (LivingRoomAccessibilityService.isConnected()) {
            try {
                DebugLogStore.append("[Spotify] 无障碍流程开始（等待完成）")
                val ok = spotifyA11y.playBySearch(song, artist)
                if (ok) {
                    DebugLogStore.append("[Spotify] 无障碍流程结束=成功")
                } else {
                    DebugLogStore.append("[Spotify] 无障碍流程结束=失败（返回 false）")
                }
                if (ok) return true
            } catch (t: Throwable) {
                DebugLogStore.append("[Spotify] 无障碍失败: ${t.message}")
            }
        } else {
            DebugLogStore.append("[Spotify] 无障碍未开启，跳过 UI 自动化")
        }

        val client = SpotifySearchClient(settings.spotifyClientId, settings.spotifyClientSecret)
        if (!client.isConfigured()) {
            DebugLogStore.append("[Spotify] 未配置 Client ID/Secret，结束=失败")
            return false
        }
        DebugLogStore.append("[Spotify] API 搜索…")
        val hit = client.searchBest(song, artist)
        DebugLogStore.append("[Spotify] API命中: ${hit.name} - ${hit.artists} (${hit.uri})")
        val candidates = listOf(
            hit.uri,
            "spotify:track:${hit.id}",
            "https://open.spotify.com/track/${hit.id}",
        )
        val errors = mutableListOf<String>()
        for (deepLink in candidates) {
            if (tryOpenUriInPackages(deepLink, packages, errors)) {
                DebugLogStore.append("[Spotify] 深链已打开: $deepLink")
                SystemClock.sleep(1500)
                dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY, MusicApp.SPOTIFY)
                return true
            }
        }
        DebugLogStore.append("[Spotify] 曲目深链失败: ${errors.take(4).joinToString("; ")}")
        return false
    }

    /** Debug: probe handlers + open song via all strategies. */
    fun testNetEasePhoneDeepLink(songId: Long = 66842L): Boolean {
        DebugLogStore.append("—— 深链专项测试 #$songId ——")
        DebugLogStore.append(netEaseDeepLink.probeHandlers(songId))
        val opened = netEaseDeepLink.openSong(songId)
        if (!opened.success) {
            DebugLogStore.append("[网易云/深链] 测试失败: ${opened.detail}")
            return false
        }
        repeat(3) {
            dispatchMediaKey(KeyEvent.KEYCODE_MEDIA_PLAY, MusicApp.NETEASE)
            SystemClock.sleep(700)
        }
        return confirmNetEaseDeepLinkPlayback(
            song = "十年",
            artist = "陈奕迅",
            pkg = opened.packageName ?: NETEASE_PHONE_PACKAGE,
        )
    }

    /** @return true only when playback is verified, not merely when startActivity succeeded. */
    private fun confirmNetEaseDeepLinkPlayback(
        song: String,
        artist: String?,
        pkg: String,
    ): Boolean {
        DebugLogStore.append("[网易云] 深链已发出，验证播放（最多 18s）…")
        return when (netEasePlaybackVerifier.verifyAfterDeepLink(song, artist, pkg)) {
            NetEasePlaybackVerifier.Result.PLAYING,
            NetEasePlaybackVerifier.Result.PLAYING_WEAK,
            -> {
                DebugLogStore.append("[网易云] 手机版深链播放已确认")
                true
            }
            NetEasePlaybackVerifier.Result.LOGIN_BLOCKED -> {
                DebugLogStore.append(
                    "[网易云] 手机版停在登录页，请先在网易云手机版完成登录后再试",
                )
                false
            }
            NetEasePlaybackVerifier.Result.NOT_PLAYING,
            NetEasePlaybackVerifier.Result.UNVERIFIED,
            -> false
        }
    }

    private fun openNetEaseInInstalledApp(songId: Long, packages: List<String>): Boolean {
        if (packages.isEmpty()) return false
        val result = netEaseDeepLink.openSong(songId, packages.first())
        if (result.success) {
            DebugLogStore.append(
                "[网易云] 深链已打开: ${result.uri} @ ${result.packageName} via ${result.method}",
            )
            return true
        }
        if (!result.detail.isNullOrBlank()) {
            DebugLogStore.append("[网易云] 深链失败: ${result.detail}")
        }
        return false
    }

    /** 深链只打手机版；TV 版不注册 orpheus scheme。 */
    private fun resolveNetEaseDeepLinkPackages(): List<String> {
        val phone = NETEASE_PHONE_PACKAGE
        return if (isInstalled(phone)) listOf(phone) else emptyList()
    }

    private fun extractNetEaseSongId(uri: String): Long? {
        val idParam = Regex("""[?&]id=(\d+)""").find(uri)?.groupValues?.getOrNull(1)
        if (idParam != null) return idParam.toLongOrNull()
        val pathId = Regex("""(?:song/|song\?id=)(\d+)""").find(uri)?.groupValues?.getOrNull(1)
        return pathId?.toLongOrNull()
    }

    private fun launchApp(app: MusicApp, uri: String?) {
        val packages = if (app == MusicApp.NETEASE) {
            resolveNetEasePackages()
        } else {
            preferredPackages(app)
        }
        if (!uri.isNullOrBlank()) {
            val errors = mutableListOf<String>()
            val deepLinkPkgs = if (app == MusicApp.NETEASE) {
                resolveNetEaseDeepLinkPackages().ifEmpty { packages }
            } else {
                packages
            }
            if (tryOpenUriInPackages(uri, deepLinkPkgs, errors)) return
        }
        for (pkg in packages) {
            if (launchPackage(pkg)) return
        }
        throw ActivityNotFoundException(
            "未找到可启动的 ${app.wire} 应用，探测包名=${packages.ifEmpty { preferredPackages(app) }}",
        )
    }

    private fun preferredPackages(app: MusicApp): List<String> =
        when (app) {
            MusicApp.SPOTIFY -> listOf(
                "com.spotify.tv.android",
                "com.spotify.music",
            )
            MusicApp.NETEASE -> listOf(
                NETEASE_PHONE_PACKAGE,
                NETEASE_TV_PACKAGE,
            )
        }

    private fun resolveNetEasePackages(): List<String> {
        val found = LinkedHashSet<String>()
        for (pkg in preferredPackages(MusicApp.NETEASE)) {
            if (isInstalled(pkg)) found.add(pkg)
        }
        try {
            @Suppress("DEPRECATION")
            val apps = context.packageManager.getInstalledApplications(0)
            for (app in apps) {
                val name = app.packageName
                val lower = name.lowercase()
                if (
                    lower.contains("cloudmusic") ||
                    (lower.contains("netease") && lower.contains("music"))
                ) {
                    found.add(name)
                }
            }
        } catch (t: Throwable) {
            Log.w(TAG, "package scan failed: ${t.message}")
        }
        return found.toList()
    }

    private fun launchPackage(packageName: String): Boolean {
        if (!isInstalled(packageName)) return false
        val launch = context.packageManager.getLaunchIntentForPackage(packageName) ?: return false
        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(launch)
            Log.i(TAG, "launched package=$packageName")
            true
        } catch (t: Throwable) {
            Log.w(TAG, "launch failed package=$packageName: ${t.message}")
            false
        }
    }

    private fun tryOpenUriInPackages(
        uri: String,
        packages: List<String>,
        errors: MutableList<String>,
    ): Boolean {
        val parsed = Uri.parse(uri)
        for (pkg in packages) {
            if (!isInstalled(pkg)) {
                errors.add("$pkg 未安装")
                continue
            }
            val intent = Intent(Intent.ACTION_VIEW, parsed).apply {
                addFlags(
                    Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_SINGLE_TOP,
                )
                addCategory(Intent.CATEGORY_DEFAULT)
                addCategory(Intent.CATEGORY_BROWSABLE)
                setPackage(pkg)
            }
            try {
                context.startActivity(intent)
                Log.i(TAG, "opened uri=$uri via package=$pkg")
                return true
            } catch (t: Throwable) {
                errors.add("$pkg 拒绝 $uri (${t.javaClass.simpleName})")
            }
        }
        return false
    }

    private fun isInstalled(packageName: String): Boolean =
        try {
            context.packageManager.getPackageInfo(packageName, 0)
            true
        } catch (_: PackageManager.NameNotFoundException) {
            false
        }

    private fun dispatchMediaKey(keyCode: Int, app: MusicApp) {
        val now = SystemClock.uptimeMillis()
        val down = KeyEvent(
            now,
            now,
            KeyEvent.ACTION_DOWN,
            keyCode,
            0,
            0,
            0,
            0,
            KeyEvent.FLAG_FROM_SYSTEM,
        )
        val up = KeyEvent(
            now,
            now + 50,
            KeyEvent.ACTION_UP,
            keyCode,
            0,
            0,
            0,
            0,
            KeyEvent.FLAG_FROM_SYSTEM,
        )
        audioManager.dispatchMediaKeyEvent(down)
        audioManager.dispatchMediaKeyEvent(up)
        Log.i(TAG, "dispatched media key=$keyCode app=${app.wire}")
    }

    companion object {
        private const val TAG = "MusicController"
        private const val NETEASE_PHONE_PACKAGE = NetEaseDeepLinkLauncher.PHONE_PACKAGE
        private const val NETEASE_TV_PACKAGE = "com.netease.cloudmusic.tv"
    }
}
