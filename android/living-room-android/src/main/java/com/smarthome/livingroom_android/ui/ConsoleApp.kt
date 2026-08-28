package com.smarthome.livingroom_android.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChatBubble
import androidx.compose.material.icons.filled.Hub
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.Sensors
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

enum class EdgeTab { Chat, System, Runtime, Entity, Node }

@Composable
fun ConsoleApp(
    vm: ConsoleViewModel,
    speechListening: Boolean,
    speechDraft: String,
    speechStatus: String,
    onToggleSpeech: () -> Unit,
    onDraftChangeFromSpeech: (String) -> Unit,
    photoMicEnabled: Boolean,
    photoMicStatus: String,
    photoMicBusy: Boolean,
    photoMicLevel: Float,
    photoVoiceTrace: List<PhotoVoiceTraceLine>,
    onTogglePhotoMic: () -> Unit,
    onLeavePhotoPane: () -> Unit,
    onExitCaptureSession: () -> Unit,
) {
    var tab by remember { mutableStateOf(EdgeTab.Chat) }
    var showSettings by remember { mutableStateOf(false) }
    var interactPane by remember { mutableStateOf(ChatPane.Photo) }
    var photoCaptureSessionActive by remember { mutableStateOf(false) }
    val hideBottomBar =
        tab == EdgeTab.Chat && interactPane == ChatPane.Photo && photoCaptureSessionActive

    LaunchedEffect(Unit) { vm.bind() }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) vm.onForeground()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(tab, interactPane) {
        if (tab != EdgeTab.Chat || interactPane != ChatPane.Photo) {
            onLeavePhotoPane()
        }
        if (tab != EdgeTab.Chat && interactPane == ChatPane.Audio) {
            vm.onAudioPaneLeave()
        }
    }

    Scaffold(
        containerColor = EdgeTheme.ink,
        bottomBar = {
            if (!hideBottomBar) {
                NavigationBar(containerColor = EdgeTheme.ink, contentColor = EdgeTheme.sand) {
                    val items = listOf(
                        EdgeTab.Chat to ("互动" to Icons.Filled.ChatBubble),
                        EdgeTab.System to ("系统" to Icons.Filled.Sensors),
                        EdgeTab.Runtime to ("能力" to Icons.Filled.Layers),
                        EdgeTab.Entity to ("实体" to Icons.Filled.Inventory2),
                        EdgeTab.Node to ("节点" to Icons.Filled.Hub),
                    )
                    items.forEach { (value, meta) ->
                        val selected = tab == value
                        NavigationBarItem(
                            selected = selected,
                            onClick = { tab = value },
                            icon = { Icon(meta.second, contentDescription = meta.first) },
                            label = { Text(meta.first, fontSize = 11.sp) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = EdgeTheme.sand,
                                selectedTextColor = EdgeTheme.sand,
                                unselectedIconColor = Color.White.copy(alpha = 0.38f),
                                unselectedTextColor = Color.White.copy(alpha = 0.38f),
                                indicatorColor = Color.White.copy(alpha = 0.06f),
                            ),
                        )
                    }
                }
            }
        },
    ) { padding ->
        Box(if (hideBottomBar) Modifier.fillMaxSize() else Modifier.padding(padding)) {
            when (tab) {
                EdgeTab.Chat -> InteractTab(
                    vm = vm,
                    speechListening = speechListening,
                    speechDraft = speechDraft,
                    speechStatus = speechStatus,
                    onToggleSpeech = onToggleSpeech,
                    onDraftChangeFromSpeech = onDraftChangeFromSpeech,
                    onOpenSettings = { showSettings = true },
                    pane = interactPane,
                    onPane = { interactPane = it },
                    photoMicEnabled = photoMicEnabled,
                    photoMicStatus = photoMicStatus,
                    photoMicBusy = photoMicBusy,
                    photoMicLevel = photoMicLevel,
                    photoVoiceTrace = photoVoiceTrace,
                    onTogglePhotoMic = onTogglePhotoMic,
                    onExitCaptureSession = onExitCaptureSession,
                    photoCaptureSessionActive = photoCaptureSessionActive,
                    onCaptureSessionActive = { photoCaptureSessionActive = it },
                )
                EdgeTab.System -> SystemObserverPane()
                EdgeTab.Runtime -> RuntimeCapabilitiesPane(vm)
                EdgeTab.Entity -> EntityBrowserPane(vm)
                EdgeTab.Node -> NodeInfoPane(vm, onOpenSettings = { showSettings = true })
            }
        }
    }
    if (showSettings) {
        ChatSettingsSheet(vm) { showSettings = false }
    }
}
