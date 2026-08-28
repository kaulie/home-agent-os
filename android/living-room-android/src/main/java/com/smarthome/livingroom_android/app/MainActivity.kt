package com.smarthome.livingroom_android.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.compose.setContent
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import com.smarthome.livingroom_android.intent.SpeechToTextHelper
import com.smarthome.livingroom_android.scan.ScanCapture
import com.smarthome.livingroom_android.ui.ConsoleApp
import com.smarthome.livingroom_android.ui.ConsoleViewModel
import com.smarthome.livingroom_android.ui.EdgeTheme
import com.smarthome.livingroom_android.ui.PhotoVoiceTraceLine
import java.util.UUID

class MainActivity : AppCompatActivity(), ScanCapture.Host {
    private val vm: ConsoleViewModel by viewModels()

    private var speechListening by mutableStateOf(false)
    private var speechDraft by mutableStateOf("")
    private var speechStatus by mutableStateOf("")

    private var photoMicEnabled by mutableStateOf(false)
    private var photoMicStatus by mutableStateOf("")
    private var photoMicBusy by mutableStateOf(false)
    private var photoMicLevel by mutableStateOf(0f)
    private val photoVoiceTrace = mutableStateListOf<PhotoVoiceTraceLine>()

    private val speech by lazy {
        SpeechToTextHelper(
            context = this,
            onPartial = { t ->
                runOnUiThread {
                    speechDraft = t
                    speechListening = true
                }
            },
            onFinal = { t ->
                runOnUiThread {
                    speechDraft = t
                    speechListening = false
                    speechStatus = ""
                }
            },
            onStatus = { s ->
                runOnUiThread { speechStatus = s }
            },
            onError = { e, _ ->
                runOnUiThread {
                    speechListening = false
                    speechStatus = ""
                    Toast.makeText(this, e, Toast.LENGTH_LONG).show()
                }
            },
        )
    }

    private val photoSpeech by lazy {
        SpeechToTextHelper(
            context = this,
            onPartial = { text ->
                runOnUiThread {
                    photoMicBusy = true
                    if (text.isNotBlank()) updatePhotoPartialTrace(text)
                }
            },
            onFinal = { text ->
                runOnUiThread {
                    photoMicBusy = false
                    photoMicLevel = 0f
                    if (text.isNotBlank()) {
                        appendPhotoTrace(PhotoVoiceTraceLine.Kind.FINAL, text)
                    }
                    if (text.isBlank() || !photoMicEnabled) return@runOnUiThread
                    photoMicStatus = "正在理解…"
                    appendPhotoTrace(PhotoVoiceTraceLine.Kind.STATUS, "POST /api/v1/intent …")
                    vm.sendPhotoVoiceIntent(text) { ok, message ->
                        runOnUiThread {
                            photoMicStatus = message
                            appendPhotoTrace(
                                if (ok) PhotoVoiceTraceLine.Kind.SEND else PhotoVoiceTraceLine.Kind.ERROR,
                                message,
                            )
                            schedulePhotoMicRestart()
                        }
                    }
                }
            },
            onStatus = { s ->
                runOnUiThread {
                    photoMicStatus = s
                    photoMicBusy = s.contains("聆听") || s.contains("识别") || s.contains("检查")
                    if (s.isNotBlank()) appendPhotoTrace(PhotoVoiceTraceLine.Kind.STATUS, s)
                }
            },
            onError = { e, code ->
                runOnUiThread {
                    photoMicBusy = false
                    photoMicLevel = 0f
                    photoMicStatus = e
                    appendPhotoTrace(PhotoVoiceTraceLine.Kind.ERROR, e)
                    if (photoMicEnabled) {
                        Toast.makeText(this, e, Toast.LENGTH_LONG).show()
                    }
                    if (photoMicEnabled && SpeechToTextHelper.shouldAutoRestartAfterError(code)) {
                        schedulePhotoMicRestart(delayMs = 1200)
                    }
                }
            },
            onRmsLevel = { level ->
                runOnUiThread { photoMicLevel = level }
            },
        )
    }

    private val micPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startSpeech() else Toast.makeText(this, "需要麦克风权限才能语音发出", Toast.LENGTH_SHORT).show()
    }

    private val notifyPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { /* foreground service still starts; notification may be silent */ }

    private val cameraPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startScanIntent()
        else ScanCapture.complete(Result.failure(IllegalStateException("扫描失败：需要相机权限。")))
    }

    private val scanLauncher = registerForActivityResult(
        ActivityResultContracts.StartIntentSenderForResult(),
    ) { result ->
        ScanCapture.onActivityResult(this, result)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            notifyPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        SpeechToTextHelper.prefetchPack(this)
        setContent {
            MaterialTheme(
                colorScheme = darkColorScheme(
                    background = EdgeTheme.ink,
                    surface = EdgeTheme.panel,
                    primary = EdgeTheme.sand,
                    onPrimary = EdgeTheme.ink,
                    onSurface = androidx.compose.ui.graphics.Color.White,
                ),
            ) {
                ConsoleApp(
                    vm = vm,
                    speechListening = speechListening,
                    speechDraft = speechDraft,
                    speechStatus = speechStatus,
                    onToggleSpeech = { toggleSpeech() },
                    onDraftChangeFromSpeech = { speechDraft = it },
                    photoMicEnabled = photoMicEnabled,
                    photoMicStatus = photoMicStatus,
                    photoMicBusy = photoMicBusy,
                    photoMicLevel = photoMicLevel,
                    photoVoiceTrace = photoVoiceTrace,
                    onTogglePhotoMic = { togglePhotoMic() },
                    onLeavePhotoPane = { stopPhotoMic() },
                    onExitCaptureSession = { stopPhotoMic() },
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        ScanCapture.attach(this, this)
    }

    override fun onPause() {
        ScanCapture.detach(this)
        super.onPause()
    }

    override fun onDestroy() {
        speech.stop()
        photoSpeech.stop()
        super.onDestroy()
    }

    override fun launchScanner() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) {
            cameraPermission.launch(Manifest.permission.CAMERA)
            return
        }
        startScanIntent()
    }

    private fun startScanIntent() {
        ScanCapture.startMlKit(this) { sender ->
            try {
                scanLauncher.launch(IntentSenderRequest.Builder(sender).build())
            } catch (t: Throwable) {
                ScanCapture.complete(
                    Result.failure(IllegalStateException("扫描失败：无法打开系统扫描仪（${t.message}）")),
                )
            }
        }
    }

    private fun toggleSpeech() {
        if (speechListening) {
            speech.stop()
            speechListening = false
            speechStatus = ""
            return
        }
        stopPhotoMic()
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            micPermission.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        startSpeech()
    }

    private fun startSpeech() {
        speechDraft = ""
        speechStatus = "正在检查中文离线语音包…"
        speechListening = true
        speech.start()
    }

    private fun togglePhotoMic() {
        if (photoMicEnabled) {
            stopPhotoMic()
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            photoMicPermission.launch(Manifest.permission.RECORD_AUDIO)
            return
        }
        startPhotoMic()
    }

    private val photoMicPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) startPhotoMic()
        else Toast.makeText(this, "需要麦克风权限才能语音发出", Toast.LENGTH_SHORT).show()
    }

    private fun startPhotoMic() {
        stopChatSpeech()
        photoVoiceTrace.clear()
        photoMicEnabled = true
        photoMicLevel = 0f
        photoMicStatus = "正在检查中文离线语音包…"
        photoMicBusy = true
        appendPhotoTrace(PhotoVoiceTraceLine.Kind.STATUS, "麦克风已开启")
        photoSpeech.start()
    }

    private fun stopPhotoMic() {
        val wasEnabled = photoMicEnabled
        photoMicEnabled = false
        photoMicBusy = false
        photoMicLevel = 0f
        photoMicStatus = ""
        photoSpeech.stop()
        if (wasEnabled) {
            appendPhotoTrace(PhotoVoiceTraceLine.Kind.STATUS, "麦克风已关闭")
        }
    }

    private fun stopChatSpeech() {
        if (speechListening) {
            speech.stop()
            speechListening = false
            speechStatus = ""
        }
    }

    private fun appendPhotoTrace(kind: PhotoVoiceTraceLine.Kind, text: String) {
        if (text.isBlank()) return
        photoVoiceTrace.add(
            PhotoVoiceTraceLine(
                id = UUID.randomUUID().toString(),
                atMs = System.currentTimeMillis(),
                kind = kind,
                text = text,
            ),
        )
        while (photoVoiceTrace.size > 48) {
            photoVoiceTrace.removeAt(0)
        }
    }

    private fun updatePhotoPartialTrace(text: String) {
        val last = photoVoiceTrace.lastOrNull()
        if (last?.kind == PhotoVoiceTraceLine.Kind.PARTIAL) {
            photoVoiceTrace[photoVoiceTrace.lastIndex] = last.copy(
                text = text,
                atMs = System.currentTimeMillis(),
            )
        } else {
            appendPhotoTrace(PhotoVoiceTraceLine.Kind.PARTIAL, text)
        }
    }

    private fun schedulePhotoMicRestart(delayMs: Long = 800) {
        if (!photoMicEnabled) return
        window.decorView.postDelayed({
            if (!photoMicEnabled) return@postDelayed
            photoMicStatus = "可以直接说话"
            appendPhotoTrace(PhotoVoiceTraceLine.Kind.STATUS, "继续聆听…")
            photoSpeech.start()
        }, delayMs)
    }
}
