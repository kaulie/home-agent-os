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
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import com.smarthome.livingroom_android.intent.SpeechToTextHelper
import com.smarthome.livingroom_android.scan.ScanCapture
import com.smarthome.livingroom_android.ui.ConsoleApp
import com.smarthome.livingroom_android.ui.ConsoleViewModel
import com.smarthome.livingroom_android.ui.EdgeTheme

class MainActivity : AppCompatActivity(), ScanCapture.Host {
    private val vm: ConsoleViewModel by viewModels()

    private var speechListening by mutableStateOf(false)
    private var speechDraft by mutableStateOf("")
    private var speechStatus by mutableStateOf("")

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
            onError = { e ->
                runOnUiThread {
                    speechListening = false
                    speechStatus = ""
                    Toast.makeText(this, e, Toast.LENGTH_LONG).show()
                }
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
}
