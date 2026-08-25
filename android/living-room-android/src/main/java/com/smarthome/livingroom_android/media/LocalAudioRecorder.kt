package com.smarthome.livingroom_android.media

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/** AAC/M4A recorder with pause. Pause does not upload; stop() returns the file. */
class LocalAudioRecorder(private val context: Context) {
    var isRecording: Boolean = false
        private set
    var isPaused: Boolean = false
        private set
    var lastError: String = ""
        private set
    var outputFile: File? = null
        private set

    private var recorder: MediaRecorder? = null
    private var elapsedBaseMs: Long = 0L
    private var runStartedMs: Long = 0L

    val isActive: Boolean get() = isRecording || isPaused

    fun elapsedMs(): Long {
        if (!isActive) return 0L
        val running = if (isRecording && runStartedMs > 0L) {
            System.currentTimeMillis() - runStartedMs
        } else {
            0L
        }
        return (elapsedBaseMs + running).coerceAtLeast(0L)
    }

    fun formattedElapsed(): String {
        val total = elapsedMs() / 1000
        val m = total / 60
        val s = total % 60
        return "%d:%02d".format(m, s)
    }

    fun start(titleHint: String): Boolean {
        lastError = ""
        if (isActive) return true
        val dir = File(context.cacheDir, "audio-inbox")
        dir.mkdirs()
        val safe = IntentSafeNames.file(titleHint, "audio")
        val file = File(dir, "${safe}_${System.currentTimeMillis()}.m4a")
        val rec = if (Build.VERSION.SDK_INT >= 31) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }
        return try {
            rec.setAudioSource(MediaRecorder.AudioSource.MIC)
            rec.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            rec.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            rec.setAudioEncodingBitRate(96_000)
            rec.setAudioSamplingRate(44_100)
            rec.setOutputFile(file.absolutePath)
            rec.prepare()
            rec.start()
            recorder = rec
            outputFile = file
            isRecording = true
            isPaused = false
            elapsedBaseMs = 0L
            runStartedMs = System.currentTimeMillis()
            true
        } catch (t: Throwable) {
            rec.release()
            recorder = null
            outputFile = null
            lastError = t.message ?: "无法开始录音"
            false
        }
    }

    fun pause() {
        lastError = ""
        val rec = recorder ?: return
        if (!isRecording || isPaused) return
        try {
            rec.pause()
            if (runStartedMs > 0L) {
                elapsedBaseMs += System.currentTimeMillis() - runStartedMs
            }
            runStartedMs = 0L
            isRecording = false
            isPaused = true
        } catch (t: Throwable) {
            lastError = t.message ?: "暂停失败"
        }
    }

    fun resume() {
        lastError = ""
        val rec = recorder ?: return
        if (!isPaused) return
        try {
            rec.resume()
            runStartedMs = System.currentTimeMillis()
            isPaused = false
            isRecording = true
        } catch (t: Throwable) {
            lastError = t.message ?: "继续录音失败"
        }
    }

    /** Stop and close the file. Caller uploads. */
    fun stop(): File? {
        lastError = ""
        val rec = recorder
        val file = outputFile
        recorder = null
        isRecording = false
        isPaused = false
        elapsedBaseMs = 0L
        runStartedMs = 0L
        if (rec == null) return file?.takeIf { it.isFile && it.length() > 0L }
        return try {
            rec.stop()
            rec.release()
            file?.takeIf { it.isFile && it.length() > 0L }
        } catch (t: Throwable) {
            rec.release()
            lastError = t.message ?: "停止录音失败"
            file?.takeIf { it.isFile && it.length() > 0L }
        }
    }

    fun discard() {
        stop()?.delete()
        outputFile = null
    }
}

internal object IntentSafeNames {
    fun file(raw: String, fallback: String): String {
        val trimmed = raw.trim().ifEmpty { fallback }
        return trimmed.replace(Regex("[\\\\/:*?\"<>|\\s]+"), "_").ifEmpty { fallback }
    }
}
