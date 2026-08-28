package com.smarthome.livingroom_android.camera

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.core.content.ContextCompat
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.nio.ByteBuffer
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * CameraX session owned by the Console Photo pane.
 * [camera.capture] uses this ImageCapture; it does not launch the system camera app.
 */
object NativeCameraSession {
    interface Listener {
        fun onCaptureBusy(busy: Boolean) {}
        fun onRuntimeCaptureStored(captureId: String, jpeg: ByteArray) {}
    }

    @Volatile
    var listener: Listener? = null

    @Volatile
    private var imageCapture: ImageCapture? = null

    @Volatile
    private var executor: Executor? = null

    private val ready = AtomicBoolean(false)
    private val captureEnabled = AtomicBoolean(false)
    private val captureMutex = Mutex()

    fun isReady(): Boolean = ready.get() && imageCapture != null && executor != null

    fun isCaptureEnabled(): Boolean = captureEnabled.get()

    fun setCaptureEnabled(enabled: Boolean) {
        captureEnabled.set(enabled)
    }

    fun hasCameraPermission(context: Context): Boolean {
        return ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
            PackageManager.PERMISSION_GRANTED
    }

    fun unavailableReason(context: Context): String? {
        if (!hasCameraPermission(context)) {
            return "拍照不可用：需要相机权限（设置 → 应用权限 → 相机）。"
        }
        if (!isReady()) {
            return "拍照不可用：请保持 Agent Console 在拍照页面前台。"
        }
        if (!captureEnabled.get()) {
            return "拍照已关闭：请在拍照页打开相机按钮。"
        }
        return null
    }

    fun permissionReason(context: Context): String? {
        if (!hasCameraPermission(context)) {
            return "拍照不可用：需要相机权限（设置 → 应用权限 → 相机）。"
        }
        return null
    }

    fun attach(capture: ImageCapture, cameraExecutor: Executor) {
        imageCapture = capture
        executor = cameraExecutor
        ready.set(true)
    }

    fun detach(capture: ImageCapture? = null) {
        if (capture != null && imageCapture !== capture) return
        ready.set(false)
        imageCapture = null
        executor = null
    }

    suspend fun captureJpeg(): ByteArray = captureMutex.withLock {
        val capture = imageCapture
        val exec = executor
        if (!ready.get() || capture == null || exec == null) {
            error("拍照失败：请保持 Agent Console 在拍照页面前台。")
        }
        if (!captureEnabled.get()) {
            error("拍照已关闭：请在拍照页打开相机按钮。")
        }
        listener?.onCaptureBusy(true)
        try {
            takePicture(capture, exec)
        } finally {
            listener?.onCaptureBusy(false)
        }
    }

    fun notifyRuntimeStored(captureId: String, jpeg: ByteArray) {
        listener?.onRuntimeCaptureStored(captureId, jpeg)
    }

    private suspend fun takePicture(capture: ImageCapture, exec: Executor): ByteArray =
        suspendCancellableCoroutine { cont ->
            capture.takePicture(
                exec,
                object : ImageCapture.OnImageCapturedCallback() {
                    override fun onCaptureSuccess(image: ImageProxy) {
                        val bytes = imageProxyJpeg(image)
                        image.close()
                        if (bytes == null || bytes.isEmpty()) {
                            if (cont.isActive) {
                                cont.resumeWithException(
                                    IllegalStateException("拍照失败：无法读取照片。"),
                                )
                            }
                        } else if (cont.isActive) {
                            cont.resume(bytes)
                        }
                    }

                    override fun onError(exception: ImageCaptureException) {
                        if (cont.isActive) {
                            cont.resumeWithException(
                                IllegalStateException(exception.message ?: "拍照失败"),
                            )
                        }
                    }
                },
            )
        }

    private fun imageProxyJpeg(image: ImageProxy): ByteArray? {
        return try {
            val plane: ByteBuffer = image.planes[0].buffer
            val bytes = ByteArray(plane.remaining())
            plane.get(bytes)
            bytes
        } catch (_: Throwable) {
            null
        }
    }
}
