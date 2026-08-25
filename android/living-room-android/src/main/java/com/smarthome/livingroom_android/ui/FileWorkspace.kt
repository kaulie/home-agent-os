package com.smarthome.livingroom_android.ui

import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AudioFile
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Movie
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.TableChart
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.foundation.Canvas
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

@Composable
fun FileWorkspace(vm: ConsoleViewModel, onSettings: () -> Unit) {
    val files = vm.turns.filter { it.isAndroidFile }.sortedByDescending { it.createdAtMs }
    var notice by remember { mutableStateOf("") }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) vm.uploadLocalFile(uri)
    }
    EdgeCanvas {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(20.dp, 8.dp, 20.dp, 36.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                Column {
                    EdgeHeroTitle("文件")
                    Spacer(Modifier.height(8.dp))
                    EdgeHeroSubtitle("从系统文件选择器选取，上传后登记为 Asset。不经意图理解。")
                }
            }
            item {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(24.dp))
                        .clickable(enabled = !vm.fileBusy) {
                            if (vm.intentServerUrl.isBlank()) {
                                vm.updateFileHint("请先在设置里填写 Brain URL")
                                onSettings()
                            } else {
                                vm.updateFileHint("")
                                picker.launch(arrayOf("*/*"))
                            }
                        }
                        .padding(1.dp),
                ) {
                    Canvas(Modifier.matchParentSize()) {
                        drawRoundRect(
                            color = EdgeTheme.sand.copy(alpha = if (vm.fileBusy) 0.22f else 0.45f),
                            cornerRadius = CornerRadius(24.dp.toPx()),
                            style = Stroke(
                                width = 1.2.dp.toPx(),
                                pathEffect = PathEffect.dashPathEffect(floatArrayOf(16f, 12f)),
                            ),
                        )
                    }
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .background(EdgeTheme.panel, RoundedCornerShape(24.dp))
                            .padding(vertical = 36.dp, horizontal = 16.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        if (vm.fileBusy) {
                            CircularProgressIndicator(color = EdgeTheme.sand, strokeWidth = 2.dp)
                            Spacer(Modifier.height(12.dp))
                            Text("正在上传…", color = EdgeTheme.sand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                            Spacer(Modifier.height(4.dp))
                            Text(
                                vm.fileUploadingName.ifBlank { "登记 Asset 中" },
                                color = EdgeTheme.mist,
                                fontSize = 13.sp,
                            )
                        } else {
                            Icon(
                                Icons.Filled.Folder,
                                contentDescription = null,
                                tint = EdgeTheme.sand,
                                modifier = Modifier.size(48.dp),
                            )
                            Spacer(Modifier.height(12.dp))
                            Text("选择文件", color = EdgeTheme.sand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                            Spacer(Modifier.height(4.dp))
                            Text("PDF、图片、表格、文本…", color = EdgeTheme.mist, fontSize = 13.sp)
                        }
                    }
                }
            }
            if (vm.fileHint.isNotEmpty()) {
                item { Text(vm.fileHint, color = Color(0xFFFFB347), fontSize = 13.sp) }
            } else if (notice.isNotEmpty()) {
                item { Text(notice, color = EdgeTheme.sand, fontSize = 13.sp) }
            }
            item { EdgeSectionLabel("最近文件") }
            if (files.isEmpty()) {
                item {
                    Text("还没有上传过文件。点上方卡片从系统文件选择器选取。", color = EdgeTheme.dim, fontSize = 14.sp)
                }
            } else {
                items(files, key = { it.id }) { turn ->
                    FileInboxRow(turn = turn, vm = vm, onNotice = { notice = it })
                }
            }
        }
    }
}

@Composable
private fun FileInboxRow(turn: ChatTurn, vm: ConsoleViewModel, onNotice: (String) -> Unit) {
    val kind = fileKind(turn)
    val bytes = if (kind == "image") vm.scanPreviewBytes[turn.inputAssetId.orEmpty()] else null
    var showFull by remember { mutableStateOf(false) }
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(EdgeTheme.panel)
            .clickable {
                if (kind == "image" && bytes != null) {
                    showFull = true
                } else {
                    val aid = turn.inputAssetId.orEmpty()
                    onNotice(if (aid.isEmpty()) "已登记，但没有 asset_id。" else "已登记 Asset · $aid")
                }
            }
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(44.dp).clip(RoundedCornerShape(10.dp)).background(EdgeTheme.ink.copy(alpha = 0.55f)),
            contentAlignment = Alignment.Center,
        ) {
            if (bytes != null) {
                val bmp = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
                if (bmp != null) {
                    Image(
                        bmp.asImageBitmap(),
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            } else {
                Icon(fileGlyph(kind, turn.userText), contentDescription = null, tint = EdgeTheme.sand)
            }
        }
        Spacer(Modifier.size(12.dp))
        Column(Modifier.weight(1f)) {
            Text(turn.userText, color = Color.White.copy(alpha = 0.92f), fontWeight = FontWeight.SemiBold, fontSize = 16.sp, maxLines = 1)
            Text("${kindLabel(kind)} · ${inboxTimeLabel(turn.createdAtMs)}", color = EdgeTheme.dim, fontSize = 12.sp)
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
                    Image(bmp.asImageBitmap(), contentDescription = "原图", modifier = Modifier.fillMaxWidth())
                }
            }
        }
    }
}

private fun fileKind(turn: ChatTurn): String {
    val text = turn.assistantText.orEmpty()
    val idx = text.lastIndexOf(" · ")
    if (idx >= 0) {
        val raw = text.substring(idx + 3).trim()
        if (raw in setOf("image", "audio", "video", "document", "file")) return raw
    }
    val name = turn.userText.lowercase()
    return when {
        name.endsWith(".jpg") || name.endsWith(".jpeg") || name.endsWith(".png") ||
            name.endsWith(".gif") || name.endsWith(".webp") -> "image"
        name.endsWith(".m4a") || name.endsWith(".mp3") || name.endsWith(".wav") -> "audio"
        name.endsWith(".mp4") || name.endsWith(".mov") -> "video"
        else -> "file"
    }
}

private fun kindLabel(kind: String) = when (kind) {
    "image" -> "图片"
    "audio" -> "音频"
    "video" -> "视频"
    else -> "文档"
}

private fun fileGlyph(kind: String, name: String) = when {
    kind == "image" -> Icons.Filled.Folder
    kind == "audio" -> Icons.Filled.AudioFile
    kind == "video" -> Icons.Filled.Movie
    name.lowercase().endsWith(".pdf") -> Icons.Filled.PictureAsPdf
    name.lowercase().endsWith(".xls") || name.lowercase().endsWith(".xlsx") ||
        name.lowercase().endsWith(".csv") -> Icons.Filled.TableChart
    name.lowercase().endsWith(".txt") || name.lowercase().endsWith(".md") -> Icons.Filled.Description
    else -> Icons.Filled.Description
}
