package com.smarthome.livingroom_android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Cancel
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.brain.BrainNetworkEnvironment
import com.smarthome.livingroom_android.brain.dto.ParticipantWire
import kotlinx.coroutines.delay
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max

@Composable
fun SystemObserverPane() {
    EdgeCanvas {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            EdgeHeroTitle("系统")
            Spacer(Modifier.height(8.dp))
            EdgeHeroSubtitle("以 observer 身份旁观整屋动态。当前 Brain 尚未提供事件流 / 活跃 session 查询接口，先占位。")
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("系统事件")
            Spacer(Modifier.height(12.dp))
            EdgeEmptyPlaceholder(
                title = "事件流待接入",
                detail = "预期展示：节点上线/下线、intent 入队与终态、能力调度失败等。待 Brain 提供 observer 事件 API 后填充。",
            )
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("活跃 Session")
            Spacer(Modifier.height(12.dp))
            EdgeEmptyPlaceholder(
                title = "Session 列表待接入",
                detail = "预期展示：当前进行中的 intent / 对话 session 及其参与节点。待 Brain 提供活跃 session 查询后填充。",
            )
        }
    }
}

@Composable
fun RuntimeCapabilitiesPane(vm: ConsoleViewModel) {
    val runtimeOn = vm.enabledRoles.contains(ParticipantWire.ROLE_RUNTIME)
    val rows = vm.advertisedServices().flatMap { svc ->
        svc.capabilities.map { cap ->
            Triple(svc, cap.capabilityId, cap)
        }
    }
    EdgeCanvas {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            EdgeHeroTitle("能力")
            Spacer(Modifier.height(8.dp))
            EdgeHeroSubtitle(
                if (runtimeOn) {
                    "本节点作为 Runtime 向下属能力做只读展示，不在此发起实质调用。"
                } else {
                    "未启用 runtime role，当前不会向 Brain 广告任何能力。可在「节点」页开启。"
                },
            )
            Spacer(Modifier.height(16.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                androidx.compose.foundation.Canvas(Modifier.size(8.dp)) {
                    drawCircle(if (runtimeOn) Color(0xD94CAF50) else EdgeTheme.dim)
                }
                Spacer(Modifier.size(10.dp))
                Text(
                    if (runtimeOn) "runtime 已启用 · ${rows.size} 项能力" else "runtime 未启用",
                    color = EdgeTheme.mist,
                    fontSize = 13.sp,
                )
            }
            Spacer(Modifier.height(20.dp))
            if (rows.isEmpty()) {
                EdgeEmptyPlaceholder(
                    title = "暂无下属能力",
                    detail = "开启 runtime 后，将列出本机广告的 capability（document.scan、phone.call、camera.capture）。本期不安装 light.set。",
                )
            } else {
                EdgeSectionLabel("下属能力")
                Spacer(Modifier.height(12.dp))
                rows.forEach { (svc, cid, cap) ->
                    EdgePanel(Modifier.padding(bottom = 12.dp)) {
                        Row {
                            Text(cid, color = Color.White, fontSize = 17.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold)
                            Spacer(Modifier.weight(1f))
                            Text(svc.displayName, color = EdgeTheme.sand, fontSize = 12.sp)
                        }
                        if (cap.role.isNotBlank()) {
                            Spacer(Modifier.height(8.dp))
                            Text(cap.role, color = EdgeTheme.mist, fontSize = 14.sp)
                        }
                        if (cap.plannerRecognize.isNotBlank()) {
                            Spacer(Modifier.height(6.dp))
                            Text(cap.plannerRecognize, color = EdgeTheme.dim, fontSize = 13.sp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun EntityBrowserPane(vm: ConsoleViewModel) {
    val devices = vm.advertisedServices().map { svc ->
        svc.serviceId to svc
    }
    EdgeCanvas {
        Column(Modifier.fillMaxSize()) {
            Row(
                Modifier
                    .padding(16.dp, 12.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(EdgeTheme.sand)
                    .padding(horizontal = 14.dp, vertical = 10.dp),
            ) {
                Column {
                    Text("Device", color = EdgeTheme.ink, fontWeight = FontWeight.SemiBold, fontSize = 14.sp)
                    Text("物理设备", color = EdgeTheme.ink.copy(alpha = 0.75f), fontSize = 11.sp)
                }
            }
            Column(
                Modifier
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
            ) {
                EdgeHeroTitle("Device")
                Spacer(Modifier.height(8.dp))
                EdgeHeroSubtitle("Device 是 Entity 的一种。以下为本节点当前会广告的设备实体（本地视图；Brain Entity Registry 未点名不接入）。")
                Spacer(Modifier.height(16.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    androidx.compose.foundation.Canvas(Modifier.size(8.dp)) {
                        drawCircle(if (devices.isEmpty()) EdgeTheme.dim else Color(0xD94CAF50))
                    }
                    Spacer(Modifier.size(10.dp))
                    Text(
                        if (devices.isEmpty()) "暂无 Device 实体" else "${devices.size} 台 Device",
                        color = EdgeTheme.mist,
                        fontSize = 13.sp,
                    )
                }
                Spacer(Modifier.height(20.dp))
                if (devices.isEmpty()) {
                    EdgeEmptyPlaceholder(
                        title = "无 Device",
                        detail = "开启 runtime（并安装可执行能力）后，本机广告的服务会映射为 Device 实体出现在此。",
                    )
                } else {
                    EdgeSectionLabel("实体列表")
                    Spacer(Modifier.height(12.dp))
                    devices.forEach { (_, svc) ->
                        EdgePanel(Modifier.padding(bottom = 12.dp)) {
                            Text(svc.displayName, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                            Spacer(Modifier.height(6.dp))
                            Text("device.${svc.serviceId}", color = EdgeTheme.dim, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                            Spacer(Modifier.height(6.dp))
                            Text("service · ${svc.serviceId}", color = EdgeTheme.mist, fontSize = 13.sp)
                            val caps = svc.capabilities.joinToString(" · ") { it.capabilityId }
                            if (caps.isNotEmpty()) {
                                Spacer(Modifier.height(4.dp))
                                Text(caps, color = EdgeTheme.dim, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun NodeInfoPane(vm: ConsoleViewModel, onOpenSettings: () -> Unit) {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1000)
            now = System.currentTimeMillis()
        }
    }
    EdgeCanvas {
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    EdgeHeroTitle("节点")
                    Spacer(Modifier.height(8.dp))
                    EdgeHeroSubtitle("当前网络环境、心跳与对时。角色变更只影响下次心跳组包。")
                }
                IconButton(onClick = onOpenSettings) {
                    Icon(Icons.Filled.Settings, contentDescription = "设置", tint = EdgeTheme.sand)
                }
            }
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("当前网络环境")
            Spacer(Modifier.height(12.dp))
            EdgePanel { BrainNetworkStatusBlock(vm, showProbeDetail = true) }
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("身份")
            Spacer(Modifier.height(12.dp))
            EdgePanel {
                InfoLine("本节点 id", vm.participantId.ifBlank { "未注册" })
                Spacer(Modifier.height(14.dp))
                InfoLine("注册时间", formatNodeTime(vm.registeredAtMs))
                Spacer(Modifier.height(14.dp))
                InfoLine("client_hint", vm.clientHint)
            }
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("心跳")
            Spacer(Modifier.height(12.dp))
            EdgePanel {
                InfoLine("最近一次", formatNodeTime(vm.lastHeartbeatAtMs))
                Spacer(Modifier.height(12.dp))
                HeartbeatOutcomeRow(
                    attempted = vm.lastHeartbeatAtMs > 0L,
                    ok = vm.lastHeartbeatOk,
                )
                Spacer(Modifier.height(12.dp))
                InfoLine("最近一次成功", formatNodeTime(vm.lastHeartbeatSuccessAtMs))
                if (vm.lastHeartbeatSuccessAtMs > 0L) {
                    Spacer(Modifier.height(12.dp))
                    HeartbeatOutcomeRow(attempted = true, ok = true)
                }
                if (vm.nextHeartbeatAtMs > 0L) {
                    val sec = max(0, ceil((vm.nextHeartbeatAtMs - now) / 1000.0).toInt())
                    Spacer(Modifier.height(12.dp))
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text("距离下次 ", color = EdgeTheme.dim, fontSize = 13.sp)
                        Text("$sec", color = EdgeTheme.sand, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                        Text(" 秒", color = EdgeTheme.sand.copy(alpha = 0.85f), fontSize = 14.sp)
                    }
                }
                if (!vm.lastHeartbeatOk && vm.lastHeartbeatError.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(vm.lastHeartbeatError, color = Color.Red.copy(alpha = 0.9f), fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                }
            }
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("对时")
            Spacer(Modifier.height(12.dp))
            EdgePanel {
                Button(
                    onClick = { vm.syncClock() },
                    enabled = !vm.clockSyncBusy,
                    colors = ButtonDefaults.buttonColors(containerColor = EdgeTheme.sand, contentColor = EdgeTheme.ink),
                ) {
                    if (vm.clockSyncBusy) {
                        CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp, color = EdgeTheme.ink)
                        Spacer(Modifier.size(8.dp))
                    }
                    Text(if (vm.clockSyncBusy) "对时中…" else "对时")
                }
                vm.clockSync?.let { sample ->
                    Spacer(Modifier.height(12.dp))
                    Text("【本地时间】${formatNodeTimeMs(sample.localAtMs)}", color = Color.White.copy(alpha = 0.9f), fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                    val server = sample.serverAtMs
                    if (server != null) {
                        Text("【服务端时间】${formatNodeTimeMs(server)}", color = Color.White.copy(alpha = 0.9f), fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                    } else if (vm.clockSyncBusy) {
                        Text("【服务端时间】…", color = EdgeTheme.dim, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                    }
                    sample.skewMs?.let { skew ->
                        Text("【时差】${formatSkew(skew)}", color = Color.White.copy(alpha = 0.9f), fontSize = 13.sp, fontFamily = FontFamily.Monospace)
                    }
                }
                if (vm.clockSyncError.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(vm.clockSyncError, color = Color.Red.copy(alpha = 0.9f), fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                }
            }
            Spacer(Modifier.height(28.dp))
            EdgeSectionLabel("角色")
            Spacer(Modifier.height(12.dp))
            EdgePanel {
                InfoLine("上报 role", vm.lastReportedRoles.joinToString(", ").ifBlank { "—" })
                Spacer(Modifier.height(12.dp))
                Text("变更（下次心跳）", color = EdgeTheme.dim, fontSize = 12.sp)
                Spacer(Modifier.height(8.dp))
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    ParticipantWire.ALL_ROLES.chunked(2).forEach { pair ->
                        Row(horizontalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.fillMaxWidth()) {
                            pair.forEach { role ->
                                val on = vm.enabledRoles.contains(role)
                                Text(
                                    role,
                                    color = if (on) EdgeTheme.ink else EdgeTheme.mist,
                                    fontSize = 12.sp,
                                    fontFamily = FontFamily.Monospace,
                                    fontWeight = FontWeight.SemiBold,
                                    modifier = Modifier
                                        .weight(1f)
                                        .clip(RoundedCornerShape(10.dp))
                                        .background(if (on) EdgeTheme.sand else Color.White.copy(alpha = 0.06f))
                                        .clickable { vm.setRole(role, !on) }
                                        .padding(vertical = 10.dp),
                                    textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                                )
                            }
                            if (pair.size == 1) Spacer(Modifier.weight(1f))
                        }
                    }
                }
                Spacer(Modifier.height(10.dp))
                Text("点选只改下次心跳组包；上报 role 是上一次心跳请求里的 roles。", color = EdgeTheme.dim, fontSize = 12.sp)
            }
            Spacer(Modifier.height(36.dp))
        }
    }
}

fun brainModeTint(mode: BrainEndpoint.Mode): Color =
    if (mode == BrainEndpoint.Mode.LAN) Color(0xFF299E6B) else Color(0xFFDB7A29)

@Composable
fun BrainEnvironmentStrip(vm: ConsoleViewModel) {
    var showSwitcher by remember { mutableStateOf(false) }
    val env = vm.brainEnv
    val tint = brainModeTint(env.mode)
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable { showSwitcher = true }
            .background(tint.copy(alpha = 0.12f))
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        androidx.compose.foundation.Canvas(Modifier.size(9.dp)) { drawCircle(tint) }
        Column(Modifier.weight(1f)) {
            Text("当前环境  ${env.modeLabel}", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            Text(env.activeBaseUrl, color = EdgeTheme.mist, fontSize = 11.sp, fontFamily = FontFamily.Monospace, maxLines = 1)
        }
        Text(env.routingLabel, color = EdgeTheme.mist, fontSize = 11.sp)
        if (env.resolveBusy) {
            CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = EdgeTheme.sand)
        }
    }
    if (showSwitcher) {
        BrainRoutingSwitcherSheet(vm) { showSwitcher = false }
    }
}

@Composable
fun BrainNetworkStatusBlock(vm: ConsoleViewModel, showProbeDetail: Boolean = false) {
    var showSwitcher by remember { mutableStateOf(false) }
    val env = vm.brainEnv
    val tint = brainModeTint(env.mode)
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            androidx.compose.foundation.Canvas(Modifier.size(10.dp)) { drawCircle(tint) }
            Spacer(Modifier.size(10.dp))
            Column(Modifier.weight(1f)) {
                Text("当前环境", color = EdgeTheme.dim, fontSize = 12.sp)
                Text(env.modeLabel, color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            }
            if (env.resolveBusy) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = EdgeTheme.sand)
            }
        }
        Spacer(Modifier.height(8.dp))
        Text("对话、心跳、注册都发到这里。", color = EdgeTheme.mist, fontSize = 12.sp)
        Spacer(Modifier.height(12.dp))
        StatusLine("在用地址", env.activeBaseUrl)
        Spacer(Modifier.height(8.dp))
        StatusLine("连接方式", env.routingLabel)
        Spacer(Modifier.height(8.dp))
        StatusLine(
            "本机网络",
            if (env.looksOnHomeLAN) "家庭局域网（${env.pathKind.label}）"
            else "不在家庭局域网（${env.pathKind.label}）",
        )
        Spacer(Modifier.height(8.dp))
        StatusLine(
            "局域网 Brain",
            when (env.lanProbeOk) {
                true -> "可达"
                false -> "不可达"
                null -> "尚未探测"
            },
        )
        if (showProbeDetail && env.lanProbeDetail.isNotEmpty() && env.lanProbeOk != true) {
            Spacer(Modifier.height(8.dp))
            Text(env.lanProbeDetail, color = Color(0xFFFF9800), fontSize = 12.sp, fontFamily = FontFamily.Monospace)
        }
        Spacer(Modifier.height(14.dp))
        Text(
            "更改连接方式…",
            color = EdgeTheme.ink,
            fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(EdgeTheme.sand)
                .clickable { showSwitcher = true }
                .padding(vertical = 10.dp),
        )
    }
    if (showSwitcher) {
        BrainRoutingSwitcherSheet(vm) { showSwitcher = false }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BrainRoutingSwitcherSheet(vm: ConsoleViewModel, onDismiss: () -> Unit) {
    var draft by remember { mutableStateOf(vm.brainRouting) }
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = EdgeTheme.panel,
        contentColor = Color.White,
    ) {
        val env = vm.brainEnv
        val tint = brainModeTint(env.mode)
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp)) {
            Text("更改连接方式", color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(12.dp))
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(10.dp))
                    .background(tint.copy(alpha = 0.12f))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                androidx.compose.foundation.Canvas(Modifier.size(8.dp)) { drawCircle(tint) }
                Text("此刻实际连接：${env.modeLabel}", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
            }
            Spacer(Modifier.height(12.dp))
            BrainEndpoint.Routing.entries.forEach { route ->
                val selected = draft == route
                val predicted = vm.predictedBrainMode(route)
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .clickable { draft = route }
                        .padding(vertical = 10.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Icon(
                        imageVector = if (selected) Icons.Filled.CheckCircle else Icons.Filled.RadioButtonUnchecked,
                        contentDescription = null,
                        tint = if (selected) EdgeTheme.sand else EdgeTheme.dim,
                        modifier = Modifier.size(22.dp),
                    )
                    Column(Modifier.weight(1f)) {
                        Text(route.title, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Spacer(Modifier.height(4.dp))
                        Text(route.subtitle, color = EdgeTheme.mist, fontSize = 12.sp)
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "确认后将连接到 ${predicted.label}  ${vm.predictedBrainBase(route)}",
                            color = brainModeTint(predicted),
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Medium,
                        )
                    }
                }
            }
            val unchanged = draft == vm.brainRouting
            val predicted = vm.predictedBrainMode(draft)
            val warnLan = draft == BrainEndpoint.Routing.LAN && !vm.brainEnv.looksOnHomeLAN
            if (warnLan) {
                Spacer(Modifier.height(8.dp))
                Text(
                    "当前不像在家庭局域网，锁定局域网后对话可能发不出去。",
                    color = Color(0xFFFF9800),
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                )
            }
            Spacer(Modifier.height(12.dp))
            Text(
                text = if (unchanged) "保持当前方式" else "确认切换到${predicted.label}",
                color = if (unchanged) Color.White else EdgeTheme.ink,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(if (unchanged) Color.White.copy(alpha = 0.12f) else EdgeTheme.sand)
                    .clickable(enabled = !vm.brainEnv.resolveBusy) {
                        if (!unchanged) vm.applyBrainRouting(draft)
                        onDismiss()
                    }
                    .padding(vertical = 12.dp),
            )
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                Text("取消", color = EdgeTheme.mist)
            }
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun HeartbeatOutcomeRow(attempted: Boolean, ok: Boolean) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (attempted) {
            Icon(
                imageVector = if (ok) Icons.Filled.CheckCircle else Icons.Filled.Cancel,
                contentDescription = if (ok) "心跳成功" else "心跳失败",
                tint = if (ok) Color(0xFF4CAF50) else Color.Red,
                modifier = Modifier.size(18.dp),
            )
        }
        Text(
            text = when {
                ok -> "成功"
                !attempted -> "尚未心跳"
                else -> "失败"
            },
            color = EdgeTheme.mist,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
        )
    }
}

@Composable
private fun InfoLine(label: String, value: String) {
    Column {
        Text(label, color = EdgeTheme.dim, fontSize = 12.sp)
        Spacer(Modifier.height(4.dp))
        Text(value, color = Color.White.copy(alpha = 0.92f), fontSize = 15.sp, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun StatusLine(label: String, value: String) {
    Column {
        Text(label, color = EdgeTheme.dim, fontSize = 12.sp)
        Text(value, color = Color.White, fontSize = 13.sp)
    }
}

private fun formatNodeTime(ms: Long): String {
    if (ms <= 0L) return "—"
    val f = SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.CHINA)
    return f.format(Date(ms))
}

private fun formatNodeTimeMs(ms: Long): String {
    val f = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS", Locale.CHINA)
    return f.format(Date(ms))
}

private fun formatSkew(skewMs: Int): String {
    if (skewMs == 0) return "0ms"
    val absMs = abs(skewMs)
    val who = if (skewMs > 0) "服务端快" else "本机快"
    return if (absMs >= 1000) {
        String.format(Locale.CHINA, "%s %.2fs (%+dms)", who, absMs / 1000.0, skewMs)
    } else {
        val sign = if (skewMs >= 0) "+" else ""
        "$who ${absMs}ms ($sign${skewMs}ms)"
    }
}
