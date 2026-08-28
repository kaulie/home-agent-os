package com.smarthome.livingroom_android.intent

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.ModelDownloadListener
import android.speech.RecognitionListener
import android.speech.RecognitionSupport
import android.speech.RecognitionSupportCallback
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.util.Log
import androidx.core.content.ContextCompat
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.Executor

/**
 * On-device Chinese speech → text. Does not use cloud recognition.
 *
 * Android 12+: [SpeechRecognizer.createOnDeviceSpeechRecognizer].
 * Android 13+: check / download the zh-CN on-device pack once via [OnDeviceZhPackCoordinator].
 */
class SpeechToTextHelper(
    context: Context,
    private val onPartial: (String) -> Unit = {},
    private val onFinal: (String) -> Unit = {},
    private val onStatus: (String) -> Unit = {},
    private val onError: (String, Int) -> Unit = { _, _ -> },
    private val onRmsLevel: (Float) -> Unit = {},
) {
    private val host = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val executor: Executor = ContextCompat.getMainExecutor(host)
    private var recognizer: SpeechRecognizer? = null
    private var released = false
    private var retries = 0
    private var languageTag = ZH_CN

    @Volatile
    var isListening: Boolean = false
        private set

    fun start() {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            main.post { start() }
            return
        }
        released = false
        retries = 0
        languageTag = ZH_CN
        if (Build.VERSION.SDK_INT >= 31) {
            if (!SpeechRecognizer.isOnDeviceRecognitionAvailable(host)) {
                notifyError(
                    "本机没有离线语音识别。请到 系统设置 → Google → 语音识别 下载中文离线包。",
                    ERROR_LANGUAGE_UNAVAILABLE,
                )
                return
            }
            rebuildOnDevice()
            if (Build.VERSION.SDK_INT >= 33) {
                notifyStatus("正在检查中文离线语音包…")
                OnDeviceZhPackCoordinator.ensureReady(
                    host,
                    onProgress = { notifyStatus(it) },
                    onReady = { tag ->
                        if (released) return@ensureReady
                        languageTag = tag
                        startListening()
                    },
                    onFailed = { message, code ->
                        if (released) return@ensureReady
                        notifyError(message, code)
                    },
                )
            } else {
                startListening()
            }
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(host)) {
            notifyError("本机不支持语音识别", SpeechRecognizer.ERROR_CLIENT)
            return
        }
        rebuildDefaultOffline()
        startListening()
    }

    fun stop() {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            main.post { stop() }
            return
        }
        released = true
        isListening = false
        teardown()
    }

    private fun rebuildOnDevice() {
        teardown()
        released = false
        val r = SpeechRecognizer.createOnDeviceSpeechRecognizer(host)
        recognizer = r
        r.setRecognitionListener(listener)
    }

    private fun rebuildDefaultOffline() {
        teardown()
        released = false
        val r = SpeechRecognizer.createSpeechRecognizer(host)
        recognizer = r
        r.setRecognitionListener(listener)
    }

    private fun recognizeIntent(): Intent =
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, languageTag)
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, host.packageName)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        }

    private fun startListening() {
        notifyStatus("正在聆听…")
        try {
            recognizer?.startListening(recognizeIntent())
        } catch (t: Throwable) {
            isListening = false
            notifyError("无法启动离线语音识别：${t.message}", SpeechRecognizer.ERROR_CLIENT)
        }
    }

    private fun teardown() {
        val old = recognizer
        recognizer = null
        old?.setRecognitionListener(null)
        old?.runCatching {
            stopListening()
            destroy()
        }
    }

    private fun notifyStatus(message: String) {
        onStatus(message)
    }

    private fun notifyError(message: String, code: Int) {
        isListening = false
        onError(message, code)
    }

    private val listener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {
            isListening = true
            notifyStatus("正在聆听…")
        }

        override fun onBeginningOfSpeech() {
            notifyStatus("检测到说话")
        }

        override fun onRmsChanged(rmsdB: Float) {
            val level = ((rmsdB + 2f) / 12f).coerceIn(0f, 1f)
            onRmsLevel(level)
        }

        override fun onBufferReceived(buffer: ByteArray?) {}

        override fun onEndOfSpeech() {
            notifyStatus("识别中…")
        }

        override fun onError(error: Int) {
            if (released) return
            isListening = false
            if (error == ERROR_LANGUAGE_UNAVAILABLE && retries < 1 && Build.VERSION.SDK_INT >= 33) {
                retries += 1
                Log.w(TAG, "on-device language missing, re-check pack")
                OnDeviceZhPackCoordinator.invalidate()
                OnDeviceZhPackCoordinator.ensureReady(
                    host,
                    onProgress = { notifyStatus(it) },
                    onReady = { tag ->
                        if (released) return@ensureReady
                        languageTag = tag
                        startListening()
                    },
                    onFailed = { message, code ->
                        if (released) return@ensureReady
                        notifyError(message, code)
                    },
                )
                return
            }
            val maxRetries = if (error == ERROR_SERVER_DISCONNECTED) MAX_SERVER_DISCONNECT_RETRIES else 1
            if (error in RETRYABLE && retries < maxRetries) {
                retries += 1
                Log.w(TAG, "on-device speech error=$error, retry $retries/$maxRetries")
                main.postDelayed({
                    if (released) return@postDelayed
                    if (Build.VERSION.SDK_INT >= 31) rebuildOnDevice() else rebuildDefaultOffline()
                    startListening()
                }, if (error == ERROR_SERVER_DISCONNECTED) 600L else 200L)
                return
            }
            retries = 0
            notifyError(errorMessage(error), error)
        }

        override fun onResults(results: Bundle?) {
            if (released) return
            isListening = false
            retries = 0
            val best = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull().orEmpty()
            if (best.isNotBlank()) {
                onFinal(best)
                notifyStatus("已转写")
            } else {
                notifyError("未识别到内容", SpeechRecognizer.ERROR_NO_MATCH)
            }
        }

        override fun onPartialResults(partialResults: Bundle?) {
            if (released) return
            val best = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                ?.firstOrNull().orEmpty()
            if (best.isNotBlank()) onPartial(best)
        }

        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    companion object {
        private const val TAG = "SpeechToText"
        private const val ZH_CN = "zh-CN"
        private const val ERROR_SERVER_DISCONNECTED = 11
        private const val ERROR_LANGUAGE_NOT_SUPPORTED = 12
        private const val ERROR_LANGUAGE_UNAVAILABLE = 13
        private const val MAX_SERVER_DISCONNECT_RETRIES = 3

        private val RETRYABLE = setOf(
            SpeechRecognizer.ERROR_CLIENT,
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY,
            ERROR_SERVER_DISCONNECTED,
        )

        /** Prefetch zh-CN pack once; safe to call from Application / Activity onCreate. */
        fun prefetchPack(context: Context) {
            if (Build.VERSION.SDK_INT < 33) return
            if (!SpeechRecognizer.isOnDeviceRecognitionAvailable(context)) return
            OnDeviceZhPackCoordinator.ensureReady(
                context.applicationContext,
                onProgress = { Log.i(TAG, "prefetch: $it") },
                onReady = { Log.i(TAG, "prefetch ready: $it") },
                onFailed = { message, code -> Log.w(TAG, "prefetch failed: $message code=$code") },
            )
        }

        /** Photo mic may auto-restart only after benign end-of-utterance errors. */
        fun shouldAutoRestartAfterError(code: Int): Boolean =
            code == SpeechRecognizer.ERROR_NO_MATCH ||
                code == SpeechRecognizer.ERROR_SPEECH_TIMEOUT

        fun pickSimplifiedChinese(tags: Collection<String>?): String? {
            val list = tags.orEmpty().map { it.trim() }.filter { it.isNotEmpty() }
            return list.firstOrNull { it.equals("zh-CN", ignoreCase = true) }
                ?: list.firstOrNull { isSimplifiedChinese(it) }
        }

        private fun isSimplifiedChinese(tag: String): Boolean {
            val t = tag.trim().lowercase().replace('_', '-')
            if (t.contains("hant") || t.endsWith("-tw") || t.endsWith("-hk") || t.endsWith("-mo")) {
                return false
            }
            return t == "zh" ||
                t == "zh-cn" ||
                t.startsWith("zh-hans") ||
                t.startsWith("cmn-hans") ||
                t == "cmn-cn"
        }

        private fun errorMessage(code: Int): String =
            when (code) {
                SpeechRecognizer.ERROR_AUDIO -> "录音错误"
                SpeechRecognizer.ERROR_CLIENT -> "离线识别出错，请再试一次"
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "缺少麦克风权限"
                SpeechRecognizer.ERROR_NETWORK -> "离线语音包不可用。请到 系统设置 → Google → 语音识别 下载简体中文包。"
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "离线语音包不可用。请到 系统设置 → Google → 语音识别 下载简体中文包。"
                SpeechRecognizer.ERROR_NO_MATCH -> "没有听清，请再说一次"
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别器忙，请重试"
                SpeechRecognizer.ERROR_SERVER -> "离线识别服务出错"
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没有听到说话"
                ERROR_SERVER_DISCONNECTED -> "离线识别服务未就绪。若刚下载完语音包，请等几秒再开麦克风；仍失败请到系统设置确认中文离线包已安装。"
                ERROR_LANGUAGE_NOT_SUPPORTED -> "本机离线识别不支持中文"
                ERROR_LANGUAGE_UNAVAILABLE -> "未安装中文离线语音包。应用正在或需要下载，请稍候再试。"
                else -> "识别错误 code=$code"
            }

        private fun packIntent(languageTag: String, packageName: String): Intent =
            Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, languageTag)
                putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, packageName)
                putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
            }
    }
}

/** One global zh-CN pack check/download so chat + photo mic do not fight each other. */
private object OnDeviceZhPackCoordinator {
    private val main = Handler(Looper.getMainLooper())
    private var state: PackState = PackState.Idle
    private var languageTag: String = SpeechToTextHelper.pickSimplifiedChinese(listOf("zh-CN")) ?: "zh-CN"
    private var packRecognizer: SpeechRecognizer? = null
    private val waiters = CopyOnWriteArrayList<PackWaiter>()
    private var pollRunnable: Runnable? = null

    private enum class PackState { Idle, Checking, Downloading, Ready, Failed }

    private data class PackWaiter(
        val onProgress: (String) -> Unit,
        val onReady: (String) -> Unit,
        val onFailed: (String, Int) -> Unit,
    )

    fun invalidate() {
        state = PackState.Idle
    }

    fun ensureReady(
        context: Context,
        onProgress: (String) -> Unit,
        onReady: (String) -> Unit,
        onFailed: (String, Int) -> Unit,
    ) {
        val app = context.applicationContext
        main.post {
            when (state) {
                PackState.Ready -> {
                    onReady(languageTag)
                    return@post
                }
                PackState.Failed -> {
                    state = PackState.Idle
                }
                PackState.Checking, PackState.Downloading -> {
                    waiters += PackWaiter(onProgress, onReady, onFailed)
                    return@post
                }
                PackState.Idle -> Unit
            }
            state = PackState.Checking
            waiters += PackWaiter(onProgress, onReady, onFailed)
            broadcastProgress("正在检查中文离线语音包…")
            checkSupport(app)
        }
    }

    private fun checkSupport(context: Context) {
        val r = obtainPackRecognizer(context)
        r.checkRecognitionSupport(
            packIntent(languageTag, context.packageName),
            ContextCompat.getMainExecutor(context),
            object : RecognitionSupportCallback {
                override fun onSupportResult(support: RecognitionSupport) {
                    main.post {
                        Log.i(
                            TAG,
                            "pack installed=${support.installedOnDeviceLanguages} " +
                                "pending=${support.pendingOnDeviceLanguages} " +
                                "supported=${support.supportedOnDeviceLanguages}",
                        )
                        val installed = SpeechToTextHelper.pickSimplifiedChinese(support.installedOnDeviceLanguages)
                        if (installed != null) {
                            markReady(installed)
                            return@post
                        }
                        if (SpeechToTextHelper.pickSimplifiedChinese(support.pendingOnDeviceLanguages) != null) {
                            state = PackState.Downloading
                            broadcastProgress("中文离线语音包正在下载，请稍候…")
                            schedulePoll(context)
                            return@post
                        }
                        val supported = SpeechToTextHelper.pickSimplifiedChinese(support.supportedOnDeviceLanguages)
                        if (supported == null) {
                            markFailed(
                                "本机离线识别不支持中文。请在系统设置里下载简体中文语音识别包。",
                                ERROR_LANGUAGE_NOT_SUPPORTED,
                            )
                            return@post
                        }
                        languageTag = supported
                        startDownload(context, supported)
                    }
                }

                override fun onError(error: Int) {
                    main.post {
                        markFailed(errorMessage(error), error)
                    }
                }
            },
        )
    }

    private fun startDownload(context: Context, tag: String) {
        state = PackState.Downloading
        broadcastProgress("正在下载中文离线语音包（只需一次）…")
        val r = obtainPackRecognizer(context)
        val intent = packIntent(tag, context.packageName)
        if (Build.VERSION.SDK_INT >= 34) {
            r.triggerModelDownload(
                intent,
                ContextCompat.getMainExecutor(context),
                object : ModelDownloadListener {
                    override fun onProgress(completedPercent: Int) {
                        main.post {
                            broadcastProgress("正在下载中文离线语音包 $completedPercent%（只需一次）")
                        }
                    }

                    override fun onSuccess() {
                        main.post { recheckAfterDownload(context) }
                    }

                    override fun onScheduled() {
                        main.post {
                            broadcastProgress("中文离线语音包已加入下载队列…")
                            schedulePoll(context)
                        }
                    }

                    override fun onError(error: Int) {
                        main.post {
                            markFailed("中文离线语音包下载失败。请到系统设置手动下载。code=$error", error)
                        }
                    }
                },
            )
            return
        }
        if (Build.VERSION.SDK_INT >= 33) {
            r.triggerModelDownload(intent)
            broadcastProgress("已开始下载中文离线语音包，完成后会自动就绪…")
            schedulePoll(context)
        }
    }

    private fun schedulePoll(context: Context) {
        pollRunnable?.let { main.removeCallbacks(it) }
        val app = context.applicationContext
        val runnable = Runnable {
            if (state != PackState.Downloading) return@Runnable
            checkSupport(app)
        }
        pollRunnable = runnable
        main.postDelayed(runnable, 2500L)
    }

    private fun recheckAfterDownload(context: Context) {
        state = PackState.Checking
        checkSupport(context.applicationContext)
    }

    private fun markReady(tag: String) {
        pollRunnable?.let { main.removeCallbacks(it) }
        pollRunnable = null
        state = PackState.Ready
        languageTag = tag
        broadcastProgress("中文离线语音包已就绪")
        val pending = waiters.toList()
        waiters.clear()
        pending.forEach { it.onReady(tag) }
    }

    private fun markFailed(message: String, code: Int) {
        pollRunnable?.let { main.removeCallbacks(it) }
        pollRunnable = null
        state = PackState.Failed
        val pending = waiters.toList()
        waiters.clear()
        pending.forEach { it.onFailed(message, code) }
    }

    private fun broadcastProgress(message: String) {
        waiters.forEach { it.onProgress(message) }
    }

    private fun obtainPackRecognizer(context: Context): SpeechRecognizer {
        packRecognizer?.let { return it }
        val r = SpeechRecognizer.createOnDeviceSpeechRecognizer(context.applicationContext)
        packRecognizer = r
        return r
    }

    private fun packIntent(languageTag: String, packageName: String): Intent =
        Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, languageTag)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE, languageTag)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, packageName)
            putExtra(RecognizerIntent.EXTRA_PREFER_OFFLINE, true)
        }

    private fun errorMessage(code: Int): String =
        when (code) {
            SpeechRecognizer.ERROR_NETWORK, SpeechRecognizer.ERROR_NETWORK_TIMEOUT ->
                "下载中文离线语音包需要网络。请连 Wi‑Fi 后重试，或到系统设置手动下载。"
            else -> "检查中文离线语音包失败 code=$code"
        }

    private const val TAG = "OnDeviceZhPack"
    private const val ERROR_LANGUAGE_UNAVAILABLE = 13
    private const val ERROR_LANGUAGE_NOT_SUPPORTED = 12
}
