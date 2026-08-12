package com.smarthome.livingroom_android.intent

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import java.util.Locale

/**
 * On-device speech → text (Chinese), similar to iOS SpeechRecognizer.
 */
class SpeechToTextHelper(
    context: Context,
    private val onPartial: (String) -> Unit = {},
    private val onFinal: (String) -> Unit = {},
    private val onStatus: (String) -> Unit = {},
    private val onError: (String) -> Unit = {},
) {
    private val appContext = context.applicationContext
    private var recognizer: SpeechRecognizer? = null

    val isAvailable: Boolean
        get() = SpeechRecognizer.isRecognitionAvailable(appContext)

    @Volatile
    var isListening: Boolean = false
        private set

    fun start(locale: Locale = Locale.SIMPLIFIED_CHINESE) {
        if (!isAvailable) {
            onError("本机不支持语音识别")
            return
        }
        stop()
        val r = SpeechRecognizer.createSpeechRecognizer(appContext)
        recognizer = r
        r.setRecognitionListener(object : RecognitionListener {
            override fun onReadyForSpeech(params: Bundle?) {
                isListening = true
                onStatus("正在聆听…")
            }

            override fun onBeginningOfSpeech() {
                onStatus("检测到说话")
            }

            override fun onRmsChanged(rmsdB: Float) {}
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {
                onStatus("识别中…")
            }

            override fun onError(error: Int) {
                isListening = false
                onError(errorMessage(error))
            }

            override fun onResults(results: Bundle?) {
                isListening = false
                val texts = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                val best = texts?.firstOrNull().orEmpty()
                if (best.isNotBlank()) {
                    onFinal(best)
                    onStatus("已转写")
                } else {
                    onError("未识别到内容")
                }
            }

            override fun onPartialResults(partialResults: Bundle?) {
                val texts =
                    partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                val best = texts?.firstOrNull().orEmpty()
                if (best.isNotBlank()) onPartial(best)
            }

            override fun onEvent(eventType: Int, params: Bundle?) {}
        })

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(
                RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
            )
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, locale.toLanguageTag())
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 3)
        }
        r.startListening(intent)
    }

    fun stop() {
        isListening = false
        recognizer?.runCatching {
            stopListening()
            destroy()
        }
        recognizer = null
    }

    private fun errorMessage(code: Int): String =
        when (code) {
            SpeechRecognizer.ERROR_AUDIO -> "录音错误"
            SpeechRecognizer.ERROR_CLIENT -> "客户端错误"
            SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "缺少麦克风权限"
            SpeechRecognizer.ERROR_NETWORK -> "网络错误（部分机型语音需联网）"
            SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "网络超时"
            SpeechRecognizer.ERROR_NO_MATCH -> "未匹配到语音"
            SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "识别器忙，请重试"
            SpeechRecognizer.ERROR_SERVER -> "识别服务错误"
            SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没有听到说话"
            else -> "识别错误 code=$code"
        }
}
