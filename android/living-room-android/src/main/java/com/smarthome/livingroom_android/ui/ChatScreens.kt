package com.smarthome.livingroom_android.ui

import android.graphics.BitmapFactory
import android.widget.Toast
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.DocumentScanner
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.outlined.AccountTree
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.smarthome.livingroom_android.intent.IntentJourney
import com.smarthome.livingroom_android.intent.IntentPhase
import com.smarthome.livingroom_android.intent.IntentPresentation
import com.smarthome.livingroom_android.intent.PhaseVisual
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

enum class ChatPane { Chat, Scan, Photo, File, Audio }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InteractTab(
    vm: ConsoleViewModel,
    speechListening: Boolean,
    speechDraft: String,
    speechStatus: String,
    onToggleSpeech: () -> Unit,
    onDraftChangeFromSpeech: (String) -> Unit,
    onOpenSettings: () -> Unit,
    pane: ChatPane,
    onPane: (ChatPane) -> Unit,
    photoMicEnabled: Boolean,
    photoMicStatus: String,
    photoMicBusy: Boolean,
    photoMicLevel: Float,
    photoVoiceTrace: List<PhotoVoiceTraceLine>,
    onTogglePhotoMic: () -> Unit,
    onExitCaptureSession: () -> Unit,
    photoCaptureSessionActive: Boolean,
    onCaptureSessionActive: (Boolean) -> Unit,
) {
    var previousPane by remember { mutableStateOf(pane) }
    LaunchedEffect(pane) {
        if (previousPane == ChatPane.Audio && pane != ChatPane.Audio) {
            vm.onAudioPaneLeave()
        }
        previousPane = pane
    }
    Column(Modifier.fillMaxSize().background(if (pane == ChatPane.Chat) EdgeTheme.chatBg else EdgeTheme.ink)) {
        if (pane != ChatPane.Photo || !photoCaptureSessionActive) {
            InteractTopBar(pane = pane, onPane = onPane, onOpenSettings = onOpenSettings)
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (pane) {
            ChatPane.Chat -> ChatList(
                vm = vm,
                speechListening = speechListening,
                speechDraft = speechDraft,
                speechStatus = speechStatus,
                onToggleSpeech = onToggleSpeech,
                onDraftChangeFromSpeech = onDraftChangeFromSpeech,
            )
            ChatPane.Scan -> ScanWorkspace(
                vm = vm,
                onSettings = onOpenSettings,
            )
            ChatPane.Photo -> PhotoWorkspace(
                vm = vm,
                onSettings = onOpenSettings,
                photoMicEnabled = photoMicEnabled,
                photoMicStatus = photoMicStatus,
                photoMicBusy = photoMicBusy,
                photoMicLevel = photoMicLevel,
                photoVoiceTrace = photoVoiceTrace,
                onTogglePhotoMic = onTogglePhotoMic,
                onCaptureSessionActive = onCaptureSessionActive,
                onExitCaptureSession = onExitCaptureSession,
            )
            ChatPane.File -> FileWorkspace(
                vm = vm,
                onSettings = onOpenSettings,
            )
            ChatPane.Audio -> AudioWorkspace(
                vm = vm,
                onSettings = onOpenSettings,
            )
            }
        }
    }
}

@Composable
private fun InteractTopBar(
    pane: ChatPane,
    onPane: (ChatPane) -> Unit,
    onOpenSettings: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .edgeSafeTop()
            .background(if (pane == ChatPane.Chat) EdgeTheme.chatBg else EdgeTheme.ink)
            .padding(horizontal = 8.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            Modifier
                .weight(1f)
                .horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            ChatPane.entries.forEach { p ->
                val selected = pane == p
                FilterChip(
                    selected = selected,
                    onClick = { onPane(p) },
                    label = {
                        Text(
                            when (p) {
                                ChatPane.Chat -> "对话"
                                ChatPane.Scan -> "扫描"
                                ChatPane.Photo -> "拍照"
                                ChatPane.File -> "文件"
                                ChatPane.Audio -> "录音"
                            },
                            fontSize = 13.sp,
                        )
                    },
                    colors = FilterChipDefaults.filterChipColors(
                        selectedContainerColor = EdgeTheme.sand,
                        selectedLabelColor = EdgeTheme.ink,
                        containerColor = Color.White.copy(alpha = 0.06f),
                        labelColor = EdgeTheme.mist,
                    ),
                )
            }
        }
        IconButton(onClick = onOpenSettings) {
            Icon(Icons.Filled.Settings, contentDescription = "设置", tint = EdgeTheme.sand)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChatList(
    vm: ConsoleViewModel,
    speechListening: Boolean,
    speechDraft: String,
    speechStatus: String,
    onToggleSpeech: () -> Unit,
    onDraftChangeFromSpeech: (String) -> Unit,
) {
    val chatTurns = vm.turns.filter { !it.isLocalInbox }
    var draft by remember { mutableStateOf("") }
    var intentSource by remember { mutableStateOf("text") }
    var progressTurnId by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()
    val focus = LocalFocusManager.current

    LaunchedEffect(speechDraft, speechListening) {
        if (speechListening || speechDraft.isNotEmpty()) {
            draft = speechDraft
            if (speechListening) intentSource = "voice"
        }
    }
    LaunchedEffect(chatTurns.size, chatTurns.lastOrNull()?.assistantText) {
        if (chatTurns.isNotEmpty()) {
            listState.animateScrollToItem(chatTurns.lastIndex)
        }
    }

    Box(Modifier.fillMaxSize().imePadding()) {
        Column(Modifier.fillMaxSize()) {
            BrainEnvironmentStrip(vm)
            PullToRefreshBox(
                isRefreshing = vm.historyLoading,
                onRefresh = { vm.loadOlderHistory() },
                modifier = Modifier.weight(1f),
            ) {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(14.dp, 12.dp, 14.dp, 12.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    if (vm.historyNotice.isNotEmpty()) {
                        item {
                            Text(
                                vm.historyNotice,
                                color = EdgeTheme.dim,
                                fontSize = 11.sp,
                                modifier = Modifier.fillMaxWidth(),
                                textAlign = TextAlign.Center,
                            )
                        }
                    }
                    if (chatTurns.isEmpty()) {
                        item { EmptyChat() }
                    }
                    items(chatTurns, key = { it.id }) { turn ->
                        ChatTurnCard(
                            turn = turn,
                            vm = vm,
                            onOpenProgress = {
                                focus.clearFocus()
                                vm.refreshTurnProgress(turn.id)
                                progressTurnId = turn.id
                            },
                        )
                    }
                }
            }
            Composer(
                draft = draft,
                onDraft = {
                    draft = it
                    if (!speechListening && intentSource == "voice" && it != speechDraft) {
                        intentSource = "text"
                    }
                },
                hint = vm.sendHint,
                listening = speechListening,
                status = speechStatus,
                onMic = onToggleSpeech,
                onSend = {
                    val text = draft.trim()
                    if (text.isEmpty()) {
                        vm.sendHint = "请先输入文字或完成语音识别"
                        return@Composer
                    }
                    val source = if (intentSource == "voice" && speechDraft.isNotEmpty()) "voice" else "text"
                    vm.sendIntent(text, source)
                    draft = ""
                    intentSource = "text"
                    onDraftChangeFromSpeech("")
                    focus.clearFocus()
                },
            )
        }
        val overlayTurn = vm.turns.firstOrNull { it.id == progressTurnId }
        if (overlayTurn != null) {
            IntentProgressOverlay(journey = overlayTurn.journey, onClose = { progressTurnId = null })
        }
    }
}

@Composable
private fun EmptyChat() {
    Column(
        Modifier.fillMaxWidth().padding(top = 48.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(
            Icons.Outlined.ChatBubbleOutline,
            contentDescription = null,
            tint = EdgeTheme.dim,
            modifier = Modifier.size(40.dp),
        )
        Spacer(Modifier.height(8.dp))
        Text("对客厅说一句话", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
        Spacer(Modifier.height(6.dp))
        Text(
            "文本或语音发出意图。可连续发多条，不必等上一单结束。下拉加载本机历史。",
            color = EdgeTheme.dim,
            fontSize = 13.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 24.dp),
        )
    }
}

@Composable
private fun Composer(
    draft: String,
    onDraft: (String) -> Unit,
    hint: String,
    listening: Boolean,
    status: String,
    onMic: () -> Unit,
    onSend: () -> Unit,
) {
    Column(
        Modifier
            .fillMaxWidth()
            .background(Color(0xFF1A1E27))
            .padding(horizontal = 16.dp, vertical = 13.dp),
    ) {
        when {
            hint.isNotEmpty() -> {
                Text(hint, color = Color(0xFFFFB347), fontSize = 11.sp)
                Spacer(Modifier.height(4.dp))
            }
            status.isNotEmpty() -> {
                Text(status, color = EdgeTheme.dim, fontSize = 11.sp)
                Spacer(Modifier.height(4.dp))
            }
            listening -> {
                Text("正在聆听…", color = EdgeTheme.dim, fontSize = 11.sp)
                Spacer(Modifier.height(4.dp))
            }
        }
        Row(verticalAlignment = Alignment.Bottom) {
            IconButton(onClick = onMic) {
                Icon(
                    if (listening) Icons.Filled.Stop else Icons.Filled.Mic,
                    contentDescription = if (listening) "停止录音" else "开始录音",
                    tint = if (listening) Color.Red else EdgeTheme.sand,
                    modifier = Modifier.size(32.dp),
                )
            }
            OutlinedTextField(
                value = draft,
                onValueChange = onDraft,
                modifier = Modifier.weight(1f),
                placeholder = { Text("输入指令…", color = EdgeTheme.dim) },
                maxLines = 5,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { onSend() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = Color.White,
                    unfocusedTextColor = Color.White,
                    focusedBorderColor = EdgeTheme.sand,
                    unfocusedBorderColor = Color.White.copy(alpha = 0.2f),
                    cursorColor = EdgeTheme.sand,
                ),
                shape = RoundedCornerShape(16.dp),
            )
            IconButton(onClick = onSend, enabled = draft.isNotBlank()) {
                Icon(
                    Icons.Filled.ArrowUpward,
                    contentDescription = "发出",
                    tint = if (draft.isNotBlank()) EdgeTheme.sand else EdgeTheme.dim,
                    modifier = Modifier.size(32.dp),
                )
            }
        }
    }
}

@Composable
private fun ChatTurnCard(
    turn: ChatTurn,
    vm: ConsoleViewModel,
    onOpenProgress: () -> Unit,
) {
    val time = remember(turn.createdAtMs) {
        SimpleDateFormat("HH:mm", Locale.CHINA).format(Date(turn.createdAtMs))
    }
    val complete = !turn.awaitingTerminal && turn.journey.phase == IntentPhase.SUCCEEDED
    Column(Modifier.fillMaxWidth()) {
        Text(
            time,
            color = EdgeTheme.dim,
            fontSize = 11.sp,
            modifier = Modifier.fillMaxWidth(),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
            if (complete) {
                Icon(Icons.Filled.CheckCircle, contentDescription = "已执行完成", tint = Color(0xFF4CAF50), modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(6.dp))
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    turn.userText,
                    color = Color.White,
                    fontSize = 16.sp,
                    modifier = Modifier
                        .widthIn(max = 280.dp)
                        .clip(RoundedCornerShape(16.dp))
                        .background(EdgeTheme.bubbleUser)
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                )
                Spacer(Modifier.height(4.dp))
                IntentIdCaption(turn.intentId)
                Spacer(Modifier.height(2.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = onOpenProgress) {
                        if (turn.awaitingTerminal) {
                            CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 1.5.dp, color = Color(0xFFFF9800))
                            Spacer(Modifier.width(4.dp))
                        } else {
                            Icon(Icons.Outlined.AccountTree, contentDescription = null, modifier = Modifier.size(14.dp), tint = EdgeTheme.mist)
                            Spacer(Modifier.width(4.dp))
                        }
                        Text("进度", color = if (turn.awaitingTerminal) Color(0xFFFF9800) else EdgeTheme.mist, fontSize = 12.sp)
                    }
                    val elapsed = IntentJourney.formatDualElapsed(
                        clientMs = System.currentTimeMillis() - turn.createdAtMs,
                        serverMs = null,
                    )
                    Text(elapsed.ifEmpty { "—" }, color = EdgeTheme.dim, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        AssistantBubble(turn, vm)
    }
}

@Composable
private fun AssistantBubble(turn: ChatTurn, vm: ConsoleViewModel) {
    val failed = turn.journey.phase == IntentPhase.FAILED || turn.error != null && !turn.awaitingTerminal && turn.presentation == null
    when {
        failed && (turn.assistantText != null || turn.error != null) -> {
            Column(Modifier.widthIn(max = 300.dp)) {
                Text(
                    turn.assistantText ?: turn.error ?: "意图失败",
                    color = Color(0xFFFF6B6B),
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(16.dp))
                        .background(EdgeTheme.bubbleAssistant)
                        .padding(horizontal = 12.dp, vertical = 8.dp),
                )
                BugReportStrip(turn = turn, vm = vm)
            }
        }
        turn.presentation?.hasContent == true -> {
            PresentationBlock(turn, vm)
        }
        turn.awaitingTerminal -> {
            Row(
                Modifier
                    .clip(RoundedCornerShape(16.dp))
                    .background(EdgeTheme.bubbleAssistant)
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = EdgeTheme.sand)
                Spacer(Modifier.width(8.dp))
                Text("正在执行…", color = EdgeTheme.mist, fontSize = 14.sp)
            }
        }
        !turn.assistantText.isNullOrBlank() -> {
            Text(
                turn.assistantText!!,
                color = Color.White,
                modifier = Modifier
                    .widthIn(max = 300.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(EdgeTheme.bubbleAssistant)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
    }
}

@Composable
private fun PresentationBlock(turn: ChatTurn, vm: ConsoleViewModel) {
    val pres = turn.presentation ?: return
    val context = LocalContext.current
    var showFull by remember { mutableStateOf(false) }
    var fullBytes by remember { mutableStateOf<ByteArray?>(null) }
    Column(
        Modifier
            .widthIn(max = 300.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(EdgeTheme.bubbleAssistant)
            .padding(10.dp),
    ) {
        when (pres.type) {
            IntentPresentation.Kind.IMAGE -> {
                val key = "${pres.assetId}|${turn.intentId}|preview"
                LaunchedEffect(key) { vm.loadPreview(turn.intentId, pres.assetId) }
                val bytes = vm.previewImages[key]
                if (bytes != null) {
                    val bmp = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
                    if (bmp != null) {
                        Image(
                            bitmap = bmp.asImageBitmap(),
                            contentDescription = "结果图",
                            contentScale = ContentScale.Crop,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(180.dp)
                                .clip(RoundedCornerShape(12.dp))
                                .clickable {
                                    vm.loadOriginal(turn.intentId, pres.assetId) { data ->
                                        fullBytes = data ?: bytes
                                        showFull = true
                                    }
                                },
                        )
                    }
                } else if (vm.previewFailed[key] == true) {
                    Text("无法用 asset_id 取到图（图还在拍照端本地，未上传到 Brain）", color = EdgeTheme.dim, fontSize = 13.sp)
                } else {
                    Column(
                        Modifier
                            .fillMaxWidth()
                            .height(140.dp),
                        verticalArrangement = Arrangement.Center,
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        CircularProgressIndicator(Modifier.size(22.dp), color = EdgeTheme.sand, strokeWidth = 2.dp)
                        Spacer(Modifier.height(8.dp))
                        Text("正在经 Brain 拉取缩略图…", color = EdgeTheme.dim, fontSize = 12.sp)
                    }
                }
                if (pres.text.isNotEmpty()) {
                    Spacer(Modifier.height(6.dp))
                    Text(pres.text, color = Color.White, fontSize = 14.sp)
                }
            }
            IntentPresentation.Kind.VIDEO -> {
                Text(pres.videoUrl ?: "视频", color = Color.White, fontSize = 14.sp)
            }
            else -> Text(pres.text, color = Color.White, fontSize = 15.sp)
        }
        if (pres.copyText.isNotEmpty()) {
            TextButton(onClick = {
                val clip = android.content.ClipData.newPlainText("presentation", pres.copyText)
                (context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager)
                    .setPrimaryClip(clip)
                Toast.makeText(context, "已复制", Toast.LENGTH_SHORT).show()
            }) { Text("复制", color = EdgeTheme.sand, fontSize = 12.sp) }
        }
    }
    if (showFull && fullBytes != null) {
        Dialog(onDismissRequest = { showFull = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color.Black)
                    .clickable { showFull = false },
                contentAlignment = Alignment.Center,
            ) {
                val bmp = remember(fullBytes) { BitmapFactory.decodeByteArray(fullBytes, 0, fullBytes!!.size) }
                if (bmp != null) {
                    Image(bmp.asImageBitmap(), contentDescription = "原图", modifier = Modifier.fillMaxWidth())
                }
            }
        }
    }
}

@Composable
private fun BugReportStrip(turn: ChatTurn, vm: ConsoleViewModel) {
    val busy = vm.devBugBusy[turn.id] == true
    val submitted = vm.devBugSubmitted[turn.id] == true
    val err = vm.devBugError[turn.id]
    val canSubmit = turn.intentId.toIntOrNull() != null && !submitted
    if (!canSubmit && err.isNullOrBlank()) {
        if (submitted) {
            Text(
                "已提交问题，正在分析。",
                color = EdgeTheme.mist,
                fontSize = 12.sp,
                modifier = Modifier.padding(top = 4.dp, start = 4.dp),
            )
        }
        return
    }
    Column(Modifier.padding(top = 4.dp)) {
        if (canSubmit) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(
                    onClick = { vm.reportBug(turn.id) },
                    enabled = !busy,
                ) {
                    if (busy) {
                        CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 1.5.dp, color = EdgeTheme.sand)
                        Spacer(Modifier.width(6.dp))
                        Text("提交中…", color = EdgeTheme.sand, fontSize = 12.sp)
                    } else {
                        Text("一键报 Bug", color = EdgeTheme.sand, fontSize = 12.sp)
                    }
                }
            }
        }
        if (!err.isNullOrBlank()) {
            Text(
                err,
                color = Color(0xFFFFB347),
                fontSize = 11.sp,
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp),
            )
        }
    }
}

@Composable
private fun IntentIdCaption(intentId: String) {
    val context = LocalContext.current
    val id = intentId.trim()
    val label = if (id.isEmpty()) "id —" else "id $id"
    Text(
        label,
        color = EdgeTheme.dim,
        fontSize = 11.sp,
        fontFamily = FontFamily.Monospace,
        modifier = Modifier.clickable(enabled = id.isNotEmpty()) {
            val clip = android.content.ClipData.newPlainText("intent_id", id)
            (context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager)
                .setPrimaryClip(clip)
            Toast.makeText(context, "已复制 $label", Toast.LENGTH_SHORT).show()
        },
    )
}

@Composable
private fun MiniChip(label: String, selected: Boolean, onClick: () -> Unit) {
    Text(
        label,
        color = if (selected) EdgeTheme.ink else EdgeTheme.mist,
        fontSize = 11.sp,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(if (selected) EdgeTheme.sand else Color.White.copy(alpha = 0.08f))
            .clickable(onClick = onClick)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

@Composable
fun IntentProgressOverlay(journey: IntentJourney, onClose: () -> Unit) {
    Box(
        Modifier
            .fillMaxSize()
            .background(Color.Black.copy(alpha = 0.32f))
            .clickable(onClick = onClose),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            Modifier
                .padding(20.dp)
                .widthIn(max = 440.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(EdgeTheme.panel)
                .clickable(enabled = false) {}
                .padding(16.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("执行进度", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                    Spacer(Modifier.height(2.dp))
                    IntentIdCaption(journey.intentId)
                }
                val chip = when {
                    journey.phase == IntentPhase.FAILED -> "失败" to Color.Red
                    journey.phase.isTerminal -> "完成" to Color(0xFF4CAF50)
                    else -> "进行中" to Color(0xFFFF9800)
                }
                Text(
                    chip.first,
                    color = chip.second,
                    fontSize = 11.sp,
                    modifier = Modifier
                        .clip(RoundedCornerShape(50))
                        .background(chip.second.copy(alpha = 0.14f))
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
                IconButton(onClick = onClose) {
                    Icon(Icons.Filled.Close, contentDescription = "关闭", tint = EdgeTheme.mist)
                }
            }
            Spacer(Modifier.height(8.dp))
            journey.phases.forEach { row ->
                val mark = when (row.visual) {
                    PhaseVisual.DONE -> "✓"
                    PhaseVisual.ACTIVE -> "▶"
                    PhaseVisual.FAILED -> "✗"
                    PhaseVisual.PENDING -> "·"
                }
                val color = when (row.visual) {
                    PhaseVisual.DONE -> Color(0xFF4CAF50)
                    PhaseVisual.ACTIVE -> Color(0xFFFF9800)
                    PhaseVisual.FAILED -> Color.Red
                    PhaseVisual.PENDING -> EdgeTheme.dim
                }
                val dur = row.durationMs?.let { IntentJourney.formatDuration(it) } ?: "—"
                Text("$mark  ${row.phase.displayLabel(row.visual, journey.reportedWire)}  [$dur]", color = color, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                Spacer(Modifier.height(6.dp))
            }
            if (journey.planSteps.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                Text("plan", color = EdgeTheme.sand, fontSize = 11.sp)
                journey.planSteps.forEach { s ->
                    Text(
                        "step${s.step} ${s.capability} [${s.status}] ${s.detail}",
                        color = EdgeTheme.mist,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
            if (!journey.error.isNullOrBlank()) {
                Spacer(Modifier.height(8.dp))
                Text(journey.error, color = Color(0xFFFF6B6B), fontSize = 12.sp)
            }
        }
    }
}

@Composable
private fun ScanWorkspace(vm: ConsoleViewModel, onSettings: () -> Unit) {
    val scans = vm.turns.filter { it.isDocumentScan }.sortedByDescending { it.createdAtMs }
    EdgeCanvas {
        androidx.compose.foundation.lazy.LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(20.dp, 8.dp, 20.dp, 36.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            item {
                Column {
                    EdgeHeroTitle("扫描")
                    Spacer(Modifier.height(8.dp))
                    EdgeHeroSubtitle("纸质小票、文档：立刻打开系统扫描仪，完成后自动上传并登记 Asset。不经意图理解。")
                }
            }
            item {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(24.dp))
                        .background(EdgeTheme.panel)
                        .clickable(enabled = !vm.scanBusy) {
                            if (vm.intentServerUrl.isBlank()) {
                                vm.updateScanHint("请先在设置里填写 Brain URL")
                                onSettings()
                            } else {
                                vm.runLocalDocumentScan()
                            }
                        }
                        .padding(vertical = 36.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    if (vm.scanBusy) {
                        CircularProgressIndicator(color = EdgeTheme.sand, strokeWidth = 2.dp)
                        Spacer(Modifier.height(12.dp))
                        Text("正在上传…", color = EdgeTheme.sand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                        Spacer(Modifier.height(4.dp))
                        Text("扫描图登记中", color = EdgeTheme.mist, fontSize = 13.sp)
                    } else {
                        Icon(
                            Icons.Filled.DocumentScanner,
                            contentDescription = null,
                            tint = EdgeTheme.sand,
                            modifier = Modifier.size(48.dp),
                        )
                        Spacer(Modifier.height(12.dp))
                        Text("开始扫描", color = EdgeTheme.sand, fontWeight = FontWeight.SemiBold, fontSize = 20.sp)
                        Spacer(Modifier.height(4.dp))
                        Text("打开系统扫描仪", color = EdgeTheme.mist, fontSize = 13.sp)
                    }
                }
            }
            if (vm.scanHint.isNotEmpty()) {
                item {
                    Text(vm.scanHint, color = Color(0xFFFFB347), fontSize = 13.sp)
                }
            }
            item { EdgeSectionLabel("最近扫描") }
            if (scans.isEmpty()) {
                item {
                    Text("还没有扫描图。点上方按钮打开系统扫描仪。", color = EdgeTheme.dim, fontSize = 14.sp)
                }
            } else {
                items(scans, key = { it.id }) { turn ->
                    ScanTimelineRow(turn = turn, vm = vm)
                }
            }
        }
    }
}

@Composable
private fun ScanTimelineRow(turn: ChatTurn, vm: ConsoleViewModel) {
    val aid = turn.inputAssetId.orEmpty()
    var showFull by remember { mutableStateOf(false) }
    val time = remember(turn.createdAtMs) {
        val fmt = if (android.text.format.DateUtils.isToday(turn.createdAtMs)) {
            SimpleDateFormat("HH:mm", Locale.CHINA)
        } else {
            SimpleDateFormat("MM/dd HH:mm", Locale.CHINA)
        }
        fmt.format(Date(turn.createdAtMs))
    }
    val bytes = vm.scanPreviewBytes[aid]
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
                        contentDescription = "扫描图",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            } else {
                Icon(Icons.Filled.DocumentScanner, contentDescription = null, tint = EdgeTheme.dim, modifier = Modifier.size(36.dp))
            }
        }
        val hasAssetId = aid.isNotEmpty()
        if (hasAssetId || turn.uploadState != PhotoUploadState.NONE) {
            Spacer(Modifier.height(6.dp))
            LocalMediaUploadStatusLine(
                uploadState = turn.uploadState,
                hasAssetId = hasAssetId,
                error = turn.error,
                noun = "扫描图",
            )
        }
    }
    if (showFull && bytes != null) {
        Dialog(onDismissRequest = { showFull = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
            Box(
                Modifier
                    .fillMaxSize()
                    .background(Color.Black)
                    .clickable { showFull = false },
                contentAlignment = Alignment.Center,
            ) {
                val bmp = remember(bytes) { BitmapFactory.decodeByteArray(bytes, 0, bytes.size) }
                if (bmp != null) {
                    Image(bmp.asImageBitmap(), contentDescription = "扫描原图", modifier = Modifier.fillMaxWidth())
                }
            }
        }
    }
}

@Composable
fun WorkspacePlaceholder(
    title: String,
    subtitle: String,
    detail: String,
    onSettings: () -> Unit,
    onClose: (() -> Unit)? = null,
    fullscreen: Boolean = false,
) {
    EdgeCanvas {
        Column(Modifier.fillMaxSize().padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (onClose != null) {
                    IconButton(onClick = onClose) {
                        Icon(Icons.Filled.Close, contentDescription = "关闭", tint = EdgeTheme.sand)
                    }
                }
                Spacer(Modifier.weight(1f))
                IconButton(onClick = onSettings) {
                    Icon(Icons.Filled.Settings, contentDescription = "设置", tint = EdgeTheme.sand)
                }
            }
            Spacer(Modifier.height(12.dp))
            EdgeHeroTitle(title)
            Spacer(Modifier.height(8.dp))
            EdgeHeroSubtitle(subtitle)
            Spacer(Modifier.height(24.dp))
            EdgeEmptyPlaceholder(title = "即将接入", detail = detail)
            if (fullscreen) {
                Spacer(Modifier.height(16.dp))
                Text("此页第一期为占位，不采集、不推流。", color = EdgeTheme.dim, fontSize = 13.sp)
            }
        }
    }
}
