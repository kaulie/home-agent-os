package com.smarthome.livingroom_android.scan

import android.app.Activity
import androidx.activity.result.ActivityResult
import com.google.mlkit.vision.documentscanner.GmsDocumentScannerOptions
import com.google.mlkit.vision.documentscanner.GmsDocumentScanning
import com.google.mlkit.vision.documentscanner.GmsDocumentScanningResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.lang.ref.WeakReference

/**
 * ML Kit document scanner, hosted by [MainActivity].
 * Local scan UI and runtime `document.scan` share this gate.
 */
object ScanCapture {
    interface Host {
        fun launchScanner()
    }

    @Volatile
    private var hostRef: WeakReference<Host>? = null

    @Volatile
    private var activityRef: WeakReference<Activity>? = null

    @Volatile
    private var pending: CompletableDeferred<Result<ByteArray>>? = null

    fun isHostAttached(): Boolean = hostRef?.get() != null

    fun attach(activity: Activity, host: Host) {
        activityRef = WeakReference(activity)
        hostRef = WeakReference(host)
    }

    fun detach(host: Host) {
        if (hostRef?.get() === host) {
            hostRef = null
            activityRef = null
        }
    }

    suspend fun captureJpeg(): ByteArray {
        val host = hostRef?.get()
            ?: error("扫描失败：请先打开 HomeAgent Console 再扫。")
        pending?.cancel()
        val next = CompletableDeferred<Result<ByteArray>>()
        pending = next
        withContext(Dispatchers.Main.immediate) {
            host.launchScanner()
        }
        return next.await().getOrThrow()
    }

    fun startMlKit(activity: Activity, startIntentSender: (android.content.IntentSender) -> Unit) {
        val options = GmsDocumentScannerOptions.Builder()
            .setGalleryImportAllowed(false)
            .setPageLimit(1)
            .setResultFormats(GmsDocumentScannerOptions.RESULT_FORMAT_JPEG)
            .setScannerMode(GmsDocumentScannerOptions.SCANNER_MODE_FULL)
            .build()
        GmsDocumentScanning.getClient(options)
            .getStartScanIntent(activity)
            .addOnSuccessListener { sender ->
                startIntentSender(sender)
            }
            .addOnFailureListener { e ->
                complete(Result.failure(IllegalStateException("扫描失败：无法打开系统扫描仪（${e.message}）")))
            }
    }

    fun onActivityResult(activity: Activity, result: ActivityResult) {
        if (result.resultCode != Activity.RESULT_OK) {
            complete(Result.failure(Cancelled()))
            return
        }
        val scan = GmsDocumentScanningResult.fromActivityResultIntent(result.data)
        val uri = scan?.pages?.firstOrNull()?.imageUri
        if (uri == null) {
            complete(Result.failure(IllegalStateException("扫描失败：没有扫描页。")))
            return
        }
        try {
            val bytes = activity.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            if (bytes == null || bytes.isEmpty()) {
                complete(Result.failure(IllegalStateException("扫描失败：读不到扫描图。")))
            } else {
                complete(Result.success(bytes))
            }
        } catch (t: Throwable) {
            complete(Result.failure(IllegalStateException("扫描失败：${t.message}")))
        }
    }

    fun complete(result: Result<ByteArray>) {
        val wait = pending
        pending = null
        wait?.complete(result)
    }

    class Cancelled : Exception("已取消")
}
