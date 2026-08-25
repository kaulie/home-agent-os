package com.smarthome.livingroom_android.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat

@Composable
fun AudioWorkspace(vm: ConsoleViewModel, onSettings: () -> Unit) {
    val context = LocalContext.current
    val clips = vm.turns.filter { it.isAndroidAudio }.sortedByDescending { it.createdAtMs }
    val recorder = vm.audioRecorder
    val clock = vm.audioClockMs
    val recording = recorder.isRecording
    val paused = recorder.isPaused
    val active = recorder.isActive
    val busy = vm.audioBusy
    DisposableEffect(Unit) {
        onDispose { vm.onAudioPaneLeave() }
    }
    val micPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) vm.startLocalAudio()
        else vm.updateAudioHint("录音失败：需要麦克风权限。")
    }

    EdgeCanvas {
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(20.dp, 8.dp, 20.dp, 36.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                Column {
                    EdgeHeroTitle("录音")
                    Spacer(Modifier.height(8.dp))
                    EdgeHeroSubtitle("对着话筒说完再停。暂停不上传；停止后才自动上传并登记 Asset。可改录音名字。不经意图理解。")
                }
            }
            item {
                val stroke = when {
                    busy -> EdgeTheme.sand.copy(alpha = 0.22f)
                    recording -> Color.Red.copy(alpha = 0.7f)
                    paused -> EdgeTheme.sand.copy(alpha = 0.55f)
                    else -> EdgeTheme.sand.copy(alpha = 0.35f)
                }
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(24.dp))
                        .background(EdgeTheme.panel)
                        .border(1.dp, stroke, RoundedCornerShape(24.dp))
                        .padding(vertical = 28.dp, horizontal = 16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    when {
                        busy -> {
                            CircularProgressIndicator(color = EdgeTheme.sand, strokeWidth = 2.dp)
                            Spacer(Modifier.height(12.dp))
                            Text("正在上传…", color = EdgeTheme.sand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                            Spacer(Modifier.height(4.dp))
                            Text(
                                vm.audioTitle.trim().ifEmpty { "登记 Asset 中" }.let {
                                    if (vm.audioTitle.isBlank()) it else "$it · 登记 Asset 中"
                                },
                                color = EdgeTheme.mist,
                                fontSize = 13.sp,
                            )
                        }
                        !active -> {
                            Column(
                                Modifier.fillMaxWidth().clickable {
                                    if (vm.intentServerUrl.isBlank()) {
                                        vm.updateAudioHint("请先在设置里填写 Brain URL")
                                        onSettings()
                                    } else if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) !=
                                        PackageManager.PERMISSION_GRANTED
                                    ) {
                                        micPermission.launch(Manifest.permission.RECORD_AUDIO)
                                    } else {
                                        vm.startLocalAudio()
                                    }
                                },
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Icon(Icons.Filled.Mic, contentDescription = null, tint = EdgeTheme.sand, modifier = Modifier.size(48.dp))
                                Spacer(Modifier.height(12.dp))
                                Text("开始录音", color = EdgeTheme.sand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                                Spacer(Modifier.height(4.dp))
                                Text("可暂停（暂停不上传）", color = EdgeTheme.mist, fontSize = 13.sp)
                            }
                        }
                        else -> {
                            @Suppress("UNUSED_VARIABLE")
                            val tick = clock
                            Text(
                                if (paused) "已暂停  ${recorder.formattedElapsed()}" else recorder.formattedElapsed(),
                                color = Color.White.copy(alpha = 0.94f),
                                fontSize = 28.sp,
                                fontFamily = FontFamily.Monospace,
                            )
                            Spacer(Modifier.height(12.dp))
                            TextField(
                                value = vm.audioTitle,
                                onValueChange = { vm.audioTitle = it },
                                modifier = Modifier.fillMaxWidth(),
                                singleLine = true,
                                colors = TextFieldDefaults.colors(
                                    focusedTextColor = Color.White,
                                    unfocusedTextColor = Color.White,
                                    focusedContainerColor = EdgeTheme.ink.copy(alpha = 0.55f),
                                    unfocusedContainerColor = EdgeTheme.ink.copy(alpha = 0.55f),
                                    cursorColor = EdgeTheme.sand,
                                    focusedIndicatorColor = Color.Transparent,
                                    unfocusedIndicatorColor = Color.Transparent,
                                ),
                            )
                            Spacer(Modifier.height(16.dp))
                            Column(
                                Modifier.fillMaxWidth().clickable {
                                    if (recording) vm.pauseLocalAudio() else vm.resumeLocalAudio()
                                },
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Icon(
                                    if (recording) Icons.Filled.Pause else Icons.Filled.Mic,
                                    contentDescription = null,
                                    tint = EdgeTheme.sand,
                                    modifier = Modifier.size(36.dp),
                                )
                                Spacer(Modifier.height(8.dp))
                                Text(
                                    if (recording) "暂停" else "继续录音",
                                    color = EdgeTheme.sand,
                                    fontWeight = FontWeight.SemiBold,
                                    fontSize = 18.sp,
                                )
                            }
                            Spacer(Modifier.height(16.dp))
                            Text(
                                "停止并上传",
                                color = Color.Red.copy(alpha = 0.92f),
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 16.sp,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(12.dp))
                                    .border(1.dp, Color.Red.copy(alpha = 0.55f), RoundedCornerShape(12.dp))
                                    .clickable { vm.stopAndUploadAudio() }
                                    .padding(vertical = 10.dp),
                                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                            )
                            Spacer(Modifier.height(8.dp))
                            Text("最长 10 分钟", color = EdgeTheme.dim, fontSize = 12.sp)
                        }
                    }
                }
            }
            if (vm.audioHint.isNotEmpty()) {
                item { Text(vm.audioHint, color = Color(0xFFFFB347), fontSize = 13.sp) }
            }
            item { EdgeSectionLabel("最近录音") }
            if (clips.isEmpty()) {
                item {
                    Text("还没有录音。点上方按钮开始，停录后会自动上传。", color = EdgeTheme.dim, fontSize = 14.sp)
                }
            } else {
                items(clips, key = { it.id }) { turn ->
                    AudioInboxRow(turn = turn, vm = vm)
                }
            }
        }
    }
}

@Composable
private fun AudioInboxRow(turn: ChatTurn, vm: ConsoleViewModel) {
    val aid = turn.inputAssetId.orEmpty()
    val playing = vm.playingAudioAssetId == aid && !vm.audioPlaybackPaused
    var menu by remember { mutableStateOf(false) }
    var rename by remember { mutableStateOf(false) }
    var draft by remember { mutableStateOf(turn.userText) }
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(EdgeTheme.panel)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .size(44.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(EdgeTheme.ink.copy(alpha = 0.55f))
                .clickable(enabled = !vm.audioRecorder.isRecording) {
                    if (playing) vm.pauseLocalAudioPlayback() else vm.playLocalAudio(aid)
                },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow,
                contentDescription = if (playing) "暂停播放" else "播放",
                tint = if (vm.audioRecorder.isRecording) EdgeTheme.dim else EdgeTheme.sand,
            )
        }
        Spacer(Modifier.size(12.dp))
        Column(Modifier.weight(1f)) {
            Text(turn.userText, color = Color.White.copy(alpha = 0.92f), fontWeight = FontWeight.SemiBold, fontSize = 16.sp, maxLines = 1)
            Text("音频 · ${inboxTimeLabel(turn.createdAtMs)}", color = EdgeTheme.dim, fontSize = 12.sp)
            if (aid.isNotEmpty()) {
                Text(aid, color = EdgeTheme.dim, fontSize = 11.sp, fontFamily = FontFamily.Monospace, maxLines = 1)
            }
        }
        Box {
            IconButton(onClick = { menu = true }) {
                Icon(Icons.Filled.MoreVert, contentDescription = "更多", tint = EdgeTheme.sand)
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(
                    text = { Text("重命名") },
                    onClick = {
                        menu = false
                        draft = turn.userText
                        rename = true
                    },
                )
            }
        }
    }
    if (rename) {
        AlertDialog(
            onDismissRequest = { rename = false },
            title = { Text("重命名") },
            text = {
                Column {
                    Text("只改本机显示名，不会重新上传。", color = EdgeTheme.mist, fontSize = 13.sp)
                    Spacer(Modifier.height(8.dp))
                    TextField(value = draft, onValueChange = { draft = it }, singleLine = true)
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    vm.renameLocalAudio(turn.id, draft)
                    rename = false
                }) { Text("保存", color = EdgeTheme.sand) }
            },
            dismissButton = {
                TextButton(onClick = { rename = false }) { Text("取消") }
            },
        )
    }
}
