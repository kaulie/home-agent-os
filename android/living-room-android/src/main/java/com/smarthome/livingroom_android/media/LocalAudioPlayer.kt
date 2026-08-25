package com.smarthome.livingroom_android.media

import android.media.MediaPlayer
import java.io.File

class LocalAudioPlayer {
    var lastError: String = ""
        private set
    var playingAssetId: String? = null
        private set
    var isPaused: Boolean = false
        private set
    var onStopped: (() -> Unit)? = null

    private var player: MediaPlayer? = null

    val isPlaying: Boolean get() = player?.isPlaying == true

    fun play(file: File, assetId: String): Boolean {
        lastError = ""
        stop(notify = false)
        if (!file.isFile || file.length() == 0L) {
            lastError = "本机没有这段录音"
            return false
        }
        return try {
            val mp = MediaPlayer()
            mp.setDataSource(file.absolutePath)
            mp.setOnCompletionListener { stop() }
            mp.prepare()
            mp.start()
            player = mp
            playingAssetId = assetId
            isPaused = false
            true
        } catch (t: Throwable) {
            lastError = t.message ?: "播放失败"
            false
        }
    }

    fun pause() {
        runCatching { player?.pause() }
        isPaused = true
    }

    fun stop(notify: Boolean = true) {
        val mp = player
        player = null
        playingAssetId = null
        isPaused = false
        if (mp != null) {
            runCatching { mp.stop() }
            runCatching { mp.release() }
        }
        if (notify) onStopped?.invoke()
    }
}
