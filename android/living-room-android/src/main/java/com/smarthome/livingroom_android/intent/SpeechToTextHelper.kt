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
import java.util.concurrent.Executor

/**
 * On-device Chinese speech → text. Does not use cloud recognition.
 *
 * Android 12+: [SpeechRecognizer.createOnDeviceSpeechRecognizer].
 * Android 13+: check / download the zh-CN on-device pack if missing.
 */
class SpeechToTextHelper(
    context: Context,
    private val onPartial: (String) -> Unit = {},
    private val onFinal: (String) -> Unit = {},
    private val onStatus: (String) -> Unit = {},
    private val onError: (String) -> Unit = {},
) {
    private val host = context
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
                notifyError("本机没有离线语音识别。请到系统设置下载中文语音识别包后再试。")
                return
            }
            rebuildOnDevice()
            if (Build.VERSION.SDK_INT >= 33) {
                notifyStatus("正在检查中文离线语音包…")
                checkPackThenListen()
            } else {
                startListening()
            }
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(host)) {
            notifyError("本机不支持语音识别")
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

    private fun checkPackThenListen() {
        val r = recognizer ?: return notifyError("离线识别器未创建")
        r.checkRecognitionSupport(
            recognizeIntent(),
            executor,
            object : RecognitionSupportCallback {
                override fun onSupportResult(support: RecognitionSupport) {
                    if (released) return
                    Log.i(
                        TAG,
                        "on-device langs installed=${support.installedOnDeviceLanguages} " +
                            "pending=${support.pendingOnDeviceLanguages} " +
                            "supported=${support.supportedOnDeviceLanguages}",
                    )
                    val installed = pickSimplifiedChinese(support.installedOnDeviceLanguages)
                    if (installed != null) {
                        languageTag = installed
                        startListening()
                        return
                    }
                    if (pickSimplifiedChinese(support.pendingOnDeviceLanguages) != null) {
                        notifyError("中文离线语音包正在下载，完成后请再点麦克风")
                        return
                    }
                    val supported = pickSimplifiedChinese(support.supportedOnDeviceLanguages)
                    if (supported == null) {
                        notifyError("本机离线识别不支持中文。请在系统设置里下载简体中文语音识别包。")
                        return
                    }
                    languageTag = supported
                    downloadChinesePack()
                }

                override fun onError(error: Int) {
                    if (released) return
                    notifyError(errorMessage(error))
                }
            },
        )
    }

    private fun downloadChinesePack() {
        val r = recognizer ?: return
        notifyStatus("正在下载中文离线语音包…")
        if (Build.VERSION.SDK_INT >= 34) {
            r.triggerModelDownload(
                recognizeIntent(),
                executor,
                object : ModelDownloadListener {
                    override fun onProgress(completedPercent: Int) {
                        if (released) return
                        notifyStatus("正在下载中文离线语音包 $completedPercent%")
                    }

                    override fun onSuccess() {
                        if (released) return
                        startListening()
                    }

                    override fun onScheduled() {
                        if (released) return
                        notifyStatus("中文离线语音包已加入下载队列…")
                    }

                    override fun onError(error: Int) {
                        if (released) return
                        notifyError("中文离线语音包下载失败。请到系统设置手动下载。code=$error")
                    }
                },
            )
            return
        }
        if (Build.VERSION.SDK_INT >= 33) {
            r.triggerModelDownload(recognizeIntent())
            notifyError("已开始下载中文离线语音包，完成后请再点麦克风")
        }
    }

    private fun startListening() {
        notifyStatus("正在聆听…")
        try {
            recognizer?.startListening(recognizeIntent())
        } catch (t: Throwable) {
            isListening = false
            notifyError("无法启动离线语音识别：${t.message}")
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

    private fun notifyError(message: String) {
        isListening = false
        onError(message)
    }

    private val listener = object : RecognitionListener {
        override fun onReadyForSpeech(params: Bundle?) {
            isListening = true
            notifyStatus("正在聆听…")
        }

        override fun onBeginningOfSpeech() {
            notifyStatus("检测到说话")
        }

        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {
            notifyStatus("识别中…")
        }

        override fun onError(error: Int) {
            if (released) return
            isListening = false
            if (error == ERROR_LANGUAGE_UNAVAILABLE && retries < 1 && Build.VERSION.SDK_INT >= 33) {
                retries += 1
                Log.w(TAG, "on-device language missing, downloading pack")
                downloadChinesePack()
                return
            }
            if (error in RETRYABLE && retries < 1) {
                retries += 1
                Log.w(TAG, "on-device speech error=$error, retry $retries")
                if (Build.VERSION.SDK_INT >= 31) rebuildOnDevice() else rebuildDefaultOffline()
                startListening()
                return
            }
            retries = 0
            notifyError(errorMessage(error))
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
                notifyError("未识别到内容")
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

        private val RETRYABLE = setOf(
            SpeechRecognizer.ERROR_CLIENT,
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY,
        )

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
                SpeechRecognizer.ERROR_NETWORK -> "离线语音包不可用。请在系统设置下载简体中文语音识别包。"
                SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "离线语音包不可用。请在系统设置下载简体中文语音识别包。"
                SpeechRecognizer.ERROR_NO_MATCH -> "没有听清，请再说一次"
                SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别器忙，请重试"
                SpeechRecognizer.ERROR_SERVER -> "离线识别服务出错"
                SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没有听到说话"
                ERROR_SERVER_DISCONNECTED -> "离线识别服务断开。请确认已下载中文语音识别包。"
                ERROR_LANGUAGE_NOT_SUPPORTED -> "本机离线识别不支持中文"
                ERROR_LANGUAGE_UNAVAILABLE -> "未安装中文离线语音包。请在系统设置下载简体中文语音识别。"
                else -> "识别错误 code=$code"
            }
    }
}
