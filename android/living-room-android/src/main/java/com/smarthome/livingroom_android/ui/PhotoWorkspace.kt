package com.smarthome.livingroom_android.ui

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.util.Size
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.displayCutout
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cameraswitch
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FlashOff
import androidx.compose.material.icons.filled.FlashOn
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import java.nio.ByteBuffer
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

@Composable
fun PhotoWorkspace(
    vm: ConsoleViewModel,
    onClose: () -> Unit,
    onSettings: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var hasCamera by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasCamera = granted
        if (!granted) vm.updatePhotoHint("拍照失败：需要相机权限（设置 → 应用权限 → 相机）。")
    }
    LaunchedEffect(Unit) {
        if (!hasCamera) permission.launch(Manifest.permission.CAMERA)
    }

    val previewView = remember {
        PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER }
    }
    val imageCapture = remember {
        ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .setTargetResolution(Size(1920, 1080))
            .build()
    }
    var camera by remember { mutableStateOf<Camera?>(null) }
    var useFront by remember { mutableStateOf(false) }
    var flashOn by remember { mutableStateOf(false) }
    var capturing by remember { mutableStateOf(false) }
    val cameraExecutor = remember { Executors.newSingleThreadExecutor() }
    val photos = vm.turns.filter { it.isAndroidPhoto }.sortedByDescending { it.createdAtMs }

    DisposableEffect(hasCamera, useFront) {
        if (!hasCamera) {
            onDispose { }
        } else {
            val providerFuture = ProcessCameraProvider.getInstance(context)
            providerFuture.addListener(
                {
                    val provider = providerFuture.get()
                    val preview = Preview.Builder().build().also {
                        it.setSurfaceProvider(previewView.surfaceProvider)
                    }
                    val selector =
                        if (useFront) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA
                    try {
                        provider.unbindAll()
                        camera = provider.bindToLifecycle(lifecycleOwner, selector, preview, imageCapture)
                        camera?.cameraControl?.enableTorch(flashOn && !useFront)
                    } catch (_: Throwable) {
                        vm.updatePhotoHint("本机没有可用摄像头。")
                    }
                },
                ContextCompat.getMainExecutor(context),
            )
            onDispose {
                runCatching { providerFuture.get().unbindAll() }
                camera = null
            }
        }
    }
    DisposableEffect(Unit) {
        onDispose { cameraExecutor.shutdown() }
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(Color.Black)) {
        val stageHeight = maxHeight
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Box(Modifier.fillMaxWidth().height(stageHeight)) {
                AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
                if (!hasCamera) {
                    Column(
                        Modifier.fillMaxSize().padding(horizontal = 32.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text("需要相机权限", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                        Spacer(Modifier.height(8.dp))
                        Text("授权后即可取景拍照。", color = EdgeTheme.mist, fontSize = 14.sp)
                    }
                }
                if (vm.photoHint.isNotEmpty()) {
                    Text(
                        vm.photoHint,
                        color = Color.White,
                        fontSize = 13.sp,
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .padding(bottom = 140.dp, start = 24.dp, end = 24.dp)
                            .clip(RoundedCornerShape(50))
                            .background(Color.Black.copy(alpha = 0.55f))
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    )
                }
                IconButton(
                    onClick = onClose,
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .windowInsetsPadding(WindowInsets.statusBars.union(WindowInsets.displayCutout))
                        .padding(start = 12.dp, top = 8.dp)
                        .size(48.dp)
                        .clip(CircleShape)
                        .background(Color.Black.copy(alpha = 0.35f)),
                ) {
                    Icon(
                        Icons.Filled.Close,
                        contentDescription = "关闭拍照",
                        tint = Color.White,
                        modifier = Modifier.size(22.dp),
                    )
                }
                Row(
                    Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .background(Color.Black)
                        .padding(horizontal = 36.dp, vertical = 22.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    IconButton(
                        onClick = {
                            flashOn = !flashOn
                            camera?.cameraControl?.enableTorch(flashOn && !useFront)
                            imageCapture.flashMode =
                                if (flashOn) ImageCapture.FLASH_MODE_ON else ImageCapture.FLASH_MODE_OFF
                        },
                        enabled = !useFront,
                    ) {
                        Icon(
                            if (flashOn) Icons.Filled.FlashOn else Icons.Filled.FlashOff,
                            contentDescription = if (flashOn) "关闭闪光灯" else "打开闪光灯",
                            tint = if (useFront) Color.White.copy(alpha = 0.35f) else Color.White,
                        )
                    }
                    Spacer(Modifier.weight(1f))
                    Box(
                        modifier = Modifier
                            .size(76.dp)
                            .clip(CircleShape)
                            .background(Color.White.copy(alpha = 0.92f))
                            .clickable(enabled = hasCamera && !capturing) {
                                if (vm.intentServerUrl.isBlank()) {
                                    vm.updatePhotoHint("请先在设置里填写 Brain URL")
                                    onSettings()
                                    return@clickable
                                }
                                capturing = true
                                vm.updatePhotoHint("")
                                takeJpeg(imageCapture, cameraExecutor) { jpeg, error ->
                                    capturing = false
                                    if (jpeg != null) vm.onLocalPhotoCaptured(jpeg)
                                    else vm.updatePhotoHint(error ?: "拍照失败")
                                }
                            },
                        contentAlignment = Alignment.Center,
                    ) {
                        if (capturing) {
                            CircularProgressIndicator(
                                Modifier.size(28.dp),
                                color = EdgeTheme.ink,
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Box(Modifier.size(62.dp).clip(CircleShape).background(Color.White))
                        }
                    }
                    Spacer(Modifier.weight(1f))
                    IconButton(onClick = { useFront = !useFront }) {
                        Icon(Icons.Filled.Cameraswitch, contentDescription = "翻转摄像头", tint = Color.White)
                    }
                }
            }
            Column(Modifier.fillMaxWidth().background(EdgeTheme.ink).padding(20.dp)) {
                EdgeSectionLabel("最近")
                Spacer(Modifier.height(12.dp))
                if (photos.isEmpty()) {
                    Text("还没有照片。对准后点快门，拍完自动上传。", color = EdgeTheme.dim, fontSize = 14.sp)
                } else {
                    photos.forEach { turn ->
                        InboxImageRow(
                            turn = turn,
                            vm = vm,
                            noun = "照片",
                        )
                        Spacer(Modifier.height(16.dp))
                    }
                }
            }
        }
    }
}

@Composable
internal fun InboxImageRow(turn: ChatTurn, vm: ConsoleViewModel, noun: String) {
    var showFull by remember { mutableStateOf(false) }
    val time = remember(turn.createdAtMs) { inboxTimeLabel(turn.createdAtMs) }
    val bytes = vm.photoPreviewBytes(turn)
    Column(Modifier.fillMaxWidth()) {
        Text(time, color = EdgeTheme.dim, fontSize = 12.sp)
        Spacer(Modifier.height(8.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(220.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(EdgeTheme.panel)
                .clickable(enabled = bytes != null) { showFull = true },
            contentAlignment = Alignment.Center,
        ) {
            if (bytes != null) {
                val bmp = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
                if (bmp != null) {
                    Image(
                        bitmap = bmp.asImageBitmap(),
                        contentDescription = noun,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            }
        }
        when (turn.uploadState) {
            PhotoUploadState.UPLOADING -> {
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(14.dp), color = EdgeTheme.mist, strokeWidth = 2.dp)
                    Spacer(Modifier.size(8.dp))
                    Text("上传中…", color = EdgeTheme.dim, fontSize = 12.sp)
                }
            }
            PhotoUploadState.FAILED -> {
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        turn.error ?: "上传失败",
                        color = EdgeTheme.mist,
                        fontSize = 12.sp,
                        modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.size(8.dp))
                    Text(
                        "重试",
                        color = Color.White,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(EdgeTheme.panel)
                            .clickable { vm.retryPhotoUpload(turn.id) }
                            .padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
            }
            else -> {}
        }
    }
    if (showFull && bytes != null) {
        Dialog(onDismissRequest = { showFull = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(
                Modifier.fillMaxSize().background(Color.Black).clickable { showFull = false },
                contentAlignment = Alignment.Center,
            ) {
                val bmp = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
                if (bmp != null) {
                    Image(bmp.asImageBitmap(), contentDescription = "${noun}原图", modifier = Modifier.fillMaxWidth())
                }
            }
        }
    }
}

internal fun inboxTimeLabel(createdAtMs: Long): String {
    val fmt = if (android.text.format.DateUtils.isToday(createdAtMs)) {
        SimpleDateFormat("HH:mm", Locale.CHINA)
    } else {
        SimpleDateFormat("MM/dd HH:mm", Locale.CHINA)
    }
    return fmt.format(Date(createdAtMs))
}

private fun takeJpeg(
    capture: ImageCapture,
    executor: ExecutorService,
    onDone: (ByteArray?, String?) -> Unit,
) {
    capture.takePicture(
        executor,
        object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                val bytes = imageProxyJpeg(image)
                image.close()
                onDone(bytes, if (bytes == null || bytes.isEmpty()) "拍照失败：无法读取照片。" else null)
            }

            override fun onError(exception: ImageCaptureException) {
                onDone(null, exception.message ?: "拍照失败")
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
