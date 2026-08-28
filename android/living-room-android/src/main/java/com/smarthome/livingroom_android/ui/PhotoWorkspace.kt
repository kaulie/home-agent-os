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
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.Cameraswitch
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.FlashOff
import androidx.compose.material.icons.filled.FlashOn
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Schedule
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.ContextCompat
import com.smarthome.livingroom_android.camera.NativeCameraSession
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

private enum class PhotoScreen { Hub, CaptureSession }

@Composable
fun PhotoWorkspace(
    vm: ConsoleViewModel,
    onSettings: () -> Unit,
    photoMicEnabled: Boolean,
    photoMicStatus: String,
    photoMicBusy: Boolean,
    photoMicLevel: Float,
    photoVoiceTrace: List<PhotoVoiceTraceLine>,
    onTogglePhotoMic: () -> Unit,
    onCaptureSessionActive: (Boolean) -> Unit,
    onExitCaptureSession: () -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val view = LocalView.current
    val scope = rememberCoroutineScope()
    var screen by remember { mutableStateOf(PhotoScreen.Hub) }
    var hasCamera by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }
    var pendingCaptureSession by remember { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        hasCamera = granted
        if (!granted) {
            vm.updatePhotoHint("拍照失败：需要相机权限（设置 → 应用权限 → 相机）。")
            pendingCaptureSession = false
        } else if (pendingCaptureSession) {
            pendingCaptureSession = false
            screen = PhotoScreen.CaptureSession
        }
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
    val shutterBusy = capturing || vm.cameraCaptureBusy
    val inCaptureSession = screen == PhotoScreen.CaptureSession
    val bindCamera = hasCamera && inCaptureSession

    LaunchedEffect(screen) {
        val active = screen == PhotoScreen.CaptureSession
        onCaptureSessionActive(active)
        if (active) {
            vm.updatePhotoCaptureEnabled(true)
        } else {
            vm.updatePhotoCaptureEnabled(false)
            vm.updatePhotoHint("")
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            onCaptureSessionActive(false)
            vm.updatePhotoCaptureEnabled(false)
            cameraExecutor.shutdown()
        }
    }

    DisposableEffect(inCaptureSession) {
        if (inCaptureSession) {
            view.keepScreenOn = true
        }
        onDispose {
            view.keepScreenOn = false
        }
    }

    DisposableEffect(bindCamera, useFront) {
        if (!bindCamera) {
            NativeCameraSession.detach(imageCapture)
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
                        NativeCameraSession.attach(imageCapture, cameraExecutor)
                    } catch (_: Throwable) {
                        NativeCameraSession.detach(imageCapture)
                        vm.updatePhotoHint("本机没有可用摄像头。")
                    }
                },
                ContextCompat.getMainExecutor(context),
            )
            onDispose {
                NativeCameraSession.detach(imageCapture)
                runCatching { providerFuture.get().unbindAll() }
                camera = null
            }
        }
    }

    val enterCaptureSession = {
        if (!hasCamera) {
            pendingCaptureSession = true
            permission.launch(Manifest.permission.CAMERA)
        } else {
            screen = PhotoScreen.CaptureSession
        }
    }

    val exitCaptureSession = {
        onExitCaptureSession()
        screen = PhotoScreen.Hub
    }

    Box(Modifier.fillMaxSize()) {
        when (screen) {
        PhotoScreen.Hub -> PhotoHubStage(
            photos = photos,
            vm = vm,
            onEnterCapture = enterCaptureSession,
        )
        PhotoScreen.CaptureSession -> PhotoCaptureSessionStage(
            hasCamera = hasCamera,
            previewView = previewView,
            vm = vm,
            photoHint = vm.photoHint,
            onExit = exitCaptureSession,
            photoMicEnabled = photoMicEnabled,
            photoMicStatus = photoMicStatus,
            photoMicBusy = photoMicBusy,
            photoMicLevel = photoMicLevel,
            photoVoiceTrace = photoVoiceTrace,
            onTogglePhotoMic = onTogglePhotoMic,
            flashOn = flashOn,
            useFront = useFront,
            shutterBusy = shutterBusy,
            onToggleFlash = {
                flashOn = !flashOn
                camera?.cameraControl?.enableTorch(flashOn && !useFront)
                imageCapture.flashMode =
                    if (flashOn) ImageCapture.FLASH_MODE_ON else ImageCapture.FLASH_MODE_OFF
            },
            onToggleFront = { useFront = !useFront },
            onShutter = {
                if (vm.intentServerUrl.isBlank()) {
                    vm.updatePhotoHint("请先在设置里填写 Brain URL")
                    onSettings()
                    return@PhotoCaptureSessionStage
                }
                capturing = true
                vm.updatePhotoHint("")
                scope.launch {
                    try {
                        val jpeg = NativeCameraSession.captureJpeg()
                        vm.onLocalPhotoCaptured(jpeg)
                    } catch (t: Throwable) {
                        vm.updatePhotoHint(t.message ?: "拍照失败")
                    } finally {
                        capturing = false
                    }
                }
            },
        )
        }
    }
}

@Composable
private fun PhotoHubStage(
    photos: List<ChatTurn>,
    vm: ConsoleViewModel,
    onEnterCapture: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxSize()
            .background(EdgeTheme.ink),
    ) {
        Box(
            Modifier
                .weight(1f)
                .fillMaxWidth(),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Box(
                    modifier = Modifier
                        .size(132.dp)
                        .clip(CircleShape)
                        .background(EdgeTheme.sand)
                        .clickable(onClick = onEnterCapture),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        Icons.Filled.PhotoCamera,
                        contentDescription = "开启拍照",
                        tint = EdgeTheme.ink,
                        modifier = Modifier.size(56.dp),
                    )
                }
                Spacer(Modifier.height(16.dp))
                Text(
                    "开启拍照",
                    color = Color.White,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "远程 camera.capture 与语音拍照",
                    color = EdgeTheme.mist,
                    fontSize = 13.sp,
                )
            }
        }
        Box(
            Modifier
                .weight(1f)
                .fillMaxWidth()
                .background(EdgeTheme.ink),
        ) {
            PhotoGalleryPane(photos = photos, vm = vm)
        }
    }
}

@Composable
private fun PhotoGalleryPane(
    photos: List<ChatTurn>,
    vm: ConsoleViewModel,
) {
    if (photos.isEmpty()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("还没有照片", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
            Spacer(Modifier.height(8.dp))
            Text(
                "点「开启拍照」后快门或远程 camera.capture 的照片会出现在这里。",
                color = EdgeTheme.mist,
                fontSize = 14.sp,
            )
        }
        return
    }
    LazyColumn(
        Modifier
            .fillMaxSize()
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            EdgeSectionLabel("最近")
            Spacer(Modifier.height(4.dp))
        }
        items(photos, key = { it.id }) { turn ->
            InboxImageRow(turn = turn, vm = vm, noun = "照片")
        }
    }
}

@Composable
private fun PhotoCaptureSessionStage(
    hasCamera: Boolean,
    previewView: PreviewView,
    vm: ConsoleViewModel,
    photoHint: String,
    onExit: () -> Unit,
    photoMicEnabled: Boolean,
    photoMicStatus: String,
    photoMicBusy: Boolean,
    photoMicLevel: Float,
    photoVoiceTrace: List<PhotoVoiceTraceLine>,
    onTogglePhotoMic: () -> Unit,
    flashOn: Boolean,
    useFront: Boolean,
    shutterBusy: Boolean,
    onToggleFlash: () -> Unit,
    onToggleFront: () -> Unit,
    onShutter: () -> Unit,
) {
    Column(Modifier.fillMaxSize().background(Color.Black)) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())
            if (!hasCamera) {
                Column(
                    Modifier
                        .fillMaxSize()
                        .edgeSafeTop()
                        .padding(horizontal = 32.dp),
                    verticalArrangement = Arrangement.Center,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("需要相机权限", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("授权后即可取景拍照。", color = EdgeTheme.mist, fontSize = 14.sp)
                }
            }
            Box(
                Modifier
                    .fillMaxSize()
                    .edgeSafeTop(),
            ) {
                if (hasCamera) {
                    Column(
                        Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = 8.dp)
                            .clip(RoundedCornerShape(50))
                            .background(Color.Black.copy(alpha = 0.55f))
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text(
                            when {
                                vm.cameraCaptureBusy -> "正在拍照…"
                                else -> "Camera Runtime · 屏幕常亮"
                            },
                            color = Color.White,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Text(
                            when {
                                vm.agentRunning -> "在线 · 等待 camera.capture"
                                else -> "Runtime 未启动"
                            },
                            color = EdgeTheme.mist,
                            fontSize = 11.sp,
                        )
                    }
                }
                if (photoHint.isNotEmpty()) {
                    Text(
                        photoHint,
                        color = Color.White,
                        fontSize = 13.sp,
                        modifier = Modifier
                            .align(Alignment.TopCenter)
                            .padding(top = 72.dp, start = 24.dp, end = 24.dp)
                            .clip(RoundedCornerShape(50))
                            .background(Color.Black.copy(alpha = 0.55f))
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                    )
                }
                IconButton(
                    onClick = onExit,
                    modifier = Modifier
                        .align(Alignment.TopStart)
                        .padding(start = 12.dp, top = 8.dp)
                        .size(48.dp)
                        .clip(CircleShape)
                        .background(Color.Black.copy(alpha = 0.35f)),
                ) {
                    Icon(
                        Icons.Filled.Close,
                        contentDescription = "退出拍照",
                        tint = Color.White,
                        modifier = Modifier.size(22.dp),
                    )
                }
                PhotoMicControl(
                    micEnabled = photoMicEnabled,
                    onToggleMic = onTogglePhotoMic,
                    micBusy = photoMicBusy,
                    micLevel = photoMicLevel,
                    statusLine = photoMicStatus,
                    modifier = Modifier
                        .align(Alignment.Center)
                        .padding(horizontal = 16.dp),
                )
                PhotoVoiceTraceOverlay(
                    lines = photoVoiceTrace,
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(start = 16.dp, end = 16.dp, bottom = 108.dp),
                )
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                .background(Color.Black)
                .padding(horizontal = 36.dp, vertical = 22.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onToggleFlash, enabled = !useFront) {
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
                    .clickable(enabled = hasCamera && !shutterBusy, onClick = onShutter),
                contentAlignment = Alignment.Center,
            ) {
                if (shutterBusy) {
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
            IconButton(onClick = onToggleFront) {
                Icon(Icons.Filled.Cameraswitch, contentDescription = "翻转摄像头", tint = Color.White)
            }
        }
    }
}

@Composable
internal fun LocalMediaUploadStatusLine(
    uploadState: PhotoUploadState,
    hasAssetId: Boolean,
    error: String? = null,
    noun: String = "照片",
    onRetry: (() -> Unit)? = null,
) {
    val display = when {
        uploadState == PhotoUploadState.UPLOADED -> PhotoUploadState.UPLOADED
        uploadState == PhotoUploadState.FAILED -> PhotoUploadState.FAILED
        uploadState == PhotoUploadState.UPLOADING -> PhotoUploadState.UPLOADING
        hasAssetId -> PhotoUploadState.UPLOADED
        else -> PhotoUploadState.NONE
    }
    when (display) {
        PhotoUploadState.UPLOADING -> {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(14.dp), color = EdgeTheme.mist, strokeWidth = 2.dp)
                Spacer(Modifier.size(8.dp))
                Text("上传中…", color = EdgeTheme.dim, fontSize = 12.sp)
            }
        }
        PhotoUploadState.UPLOADED -> {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Filled.CheckCircle,
                    contentDescription = null,
                    tint = EdgeTheme.sand,
                    modifier = Modifier.size(14.dp),
                )
                Spacer(Modifier.size(6.dp))
                Text("已上传", color = EdgeTheme.sand, fontSize = 12.sp)
            }
        }
        PhotoUploadState.FAILED -> {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    error ?: "上传失败（$noun 已存本机）",
                    color = Color(0xFFFFB347),
                    fontSize = 12.sp,
                    modifier = Modifier.weight(1f),
                )
                if (onRetry != null) {
                    Spacer(Modifier.size(8.dp))
                    Text(
                        "重试",
                        color = Color.White,
                        fontSize = 12.sp,
                        fontWeight = FontWeight.SemiBold,
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(EdgeTheme.panel)
                            .clickable(onClick = onRetry)
                            .padding(horizontal = 12.dp, vertical = 6.dp),
                    )
                }
            }
        }
        PhotoUploadState.NONE -> {
            if (!hasAssetId) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Filled.Schedule,
                        contentDescription = null,
                        tint = EdgeTheme.dim,
                        modifier = Modifier.size(14.dp),
                    )
                    Spacer(Modifier.size(6.dp))
                    Text(
                        if (onRetry != null) "等待上传…" else "本机已存",
                        color = EdgeTheme.dim,
                        fontSize = 12.sp,
                    )
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
        val hasAssetId = !turn.inputAssetId.isNullOrBlank()
        if (turn.isAndroidPhoto || hasAssetId) {
            Spacer(Modifier.height(6.dp))
            LocalMediaUploadStatusLine(
                uploadState = turn.uploadState,
                hasAssetId = hasAssetId,
                error = turn.error,
                noun = noun,
                onRetry = if (turn.isAndroidPhoto && turn.uploadState == PhotoUploadState.FAILED) {
                    { vm.retryPhotoUpload(turn.id) }
                } else {
                    null
                },
            )
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
