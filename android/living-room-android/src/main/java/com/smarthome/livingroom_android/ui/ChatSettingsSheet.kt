package com.smarthome.livingroom_android.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.smarthome.livingroom_android.brain.BrainEndpoint

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatSettingsSheet(vm: ConsoleViewModel, onDismiss: () -> Unit) {
    ModalBottomSheet(
        onDismissRequest = {
            vm.applyPinnedBrainUrls()
            onDismiss()
        },
        containerColor = EdgeTheme.panel,
        contentColor = Color.White,
    ) {
        Column(
            Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp),
        ) {
            var newName by remember { mutableStateOf("") }
            var newNumber by remember { mutableStateOf("") }
            Text("设置", color = Color.White, fontSize = 20.sp)
            Spacer(Modifier.height(16.dp))
            Text("Brain", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(8.dp))
            BrainNetworkStatusBlock(vm)
            Spacer(Modifier.height(12.dp))
            OutlinedTextField(
                value = vm.lanBrainUrl,
                onValueChange = { vm.lanBrainUrl = it },
                label = { Text("局域网 Brain") },
                placeholder = { Text(BrainEndpoint.DEFAULT_LAN_BASE) },
                modifier = Modifier.fillMaxWidth(),
                colors = fieldColors(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = vm.cloudBrainUrl,
                onValueChange = { vm.cloudBrainUrl = it },
                label = { Text("云端 Brain") },
                placeholder = { Text(BrainEndpoint.DEFAULT_CLOUD_BASE) },
                modifier = Modifier.fillMaxWidth(),
                colors = fieldColors(),
            )
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = { vm.applyPinnedBrainUrls() }) {
                Text("应用地址", color = EdgeTheme.sand)
            }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = vm.adminToken,
                onValueChange = { vm.adminToken = it },
                label = { Text("管理员令牌（dev_task）") },
                placeholder = { Text("云端 Brain 需要时填写") },
                modifier = Modifier.fillMaxWidth(),
                colors = fieldColors(),
            )
            TextButton(onClick = { vm.applyAdminToken() }) {
                Text("保存令牌", color = EdgeTheme.sand)
            }
            Spacer(Modifier.height(20.dp))
            Text("本机", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(8.dp))
            Text("client_hint  ${vm.clientHint}", color = EdgeTheme.mist, fontSize = 13.sp)
            Text("participant  ${vm.participantId.ifBlank { "未注册" }}", color = EdgeTheme.mist, fontSize = 13.sp)
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.weight(1f)) {
                    Text("开机自启并后台持续运行", color = Color.White, fontSize = 14.sp)
                    Text("心跳走前台服务保活，不改 Role 广告。", color = EdgeTheme.dim, fontSize = 12.sp)
                }
                Switch(
                    checked = vm.autoStartOnBoot,
                    onCheckedChange = { vm.setAutoStart(it) },
                    colors = SwitchDefaults.colors(checkedTrackColor = EdgeTheme.sand, checkedThumbColor = EdgeTheme.ink),
                )
            }
            Spacer(Modifier.height(8.dp))
            Row {
                Button(
                    onClick = { vm.startAgent() },
                    colors = ButtonDefaults.buttonColors(containerColor = EdgeTheme.sand, contentColor = EdgeTheme.ink),
                    modifier = Modifier.weight(1f),
                ) { Text(if (vm.agentRunning) "Agent 运行中" else "启动 Agent") }
                Spacer(Modifier.padding(6.dp))
                Button(
                    onClick = { vm.stopAgent() },
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White.copy(alpha = 0.12f), contentColor = Color.White),
                    modifier = Modifier.weight(1f),
                ) { Text("停止") }
            }
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = { vm.clearEdgeId() }) {
                Text("清除本地 edgeId（下次重新注册）", color = Color(0xFFFFB347))
            }
            Spacer(Modifier.height(16.dp))
            Text("GoPro 拍照", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "本机广告 camera.capture。不切 Wi‑Fi：请先连上 GoPro 热点。快门走 10.5.5.9，上传走蜂窝（请开移动数据）。顶部「拍照」是本机后置快门（android.photo），不是 GoPro。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(16.dp))
            Text("文档扫描", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "入口在顶部「扫描」。点「开始扫描」打开系统文档扫描仪，完成后 POST /api/v1/assets/upload（upload_intent=document.scan）。不经 Planner。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(16.dp))
            Text("可呼叫的人", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "对客厅说「给妈妈打电话」时，Brain 会派 phone.call。本机只按本步 name 查这份目录，不会去翻通讯录或前序步骤。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(8.dp))
            vm.householdPeople.forEachIndexed { index, person ->
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.weight(1f)) {
                        Text(person.name, color = Color.White, fontSize = 14.sp)
                        Text(person.number, color = EdgeTheme.mist, fontSize = 12.sp)
                    }
                    TextButton(onClick = { vm.removeHouseholdPerson(index) }) {
                        Text("删除", color = Color(0xFFFFB347), fontSize = 12.sp)
                    }
                }
            }
            OutlinedTextField(
                value = newName,
                onValueChange = { newName = it },
                label = { Text("姓名（如妈妈）") },
                modifier = Modifier.fillMaxWidth(),
                colors = fieldColors(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = newNumber,
                onValueChange = { newNumber = it },
                label = { Text("电话号码") },
                modifier = Modifier.fillMaxWidth(),
                colors = fieldColors(),
            )
            Spacer(Modifier.height(4.dp))
            TextButton(
                onClick = {
                    vm.addHouseholdPerson(newName, newNumber)
                    newName = ""
                    newNumber = ""
                },
                enabled = newName.isNotBlank() && newNumber.isNotBlank(),
            ) {
                Text("加入目录", color = EdgeTheme.sand)
            }
            Spacer(Modifier.height(12.dp))
            Text("本机拍照", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "入口在顶部「拍照」。切过去即后置取景，点快门后 POST /api/v1/assets/upload（upload_intent=android.photo）。不经 Planner，也不是 GoPro camera.capture。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(12.dp))
            Text("本机文件", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "入口在顶部「文件」。选取后 POST /api/v1/assets/upload（upload_intent=android.file）。不经 Planner。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(12.dp))
            Text("本机录音", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "入口在顶部「录音」。点开始后可暂停（暂停不上传）；点「停止并上传」才 POST /api/v1/assets/upload（upload_intent=android.audio）。不经 Planner。最近列表显示 asset_id，可重命名，播放本机缓存。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(12.dp))
            Text("直播", color = EdgeTheme.sand, fontSize = 12.sp)
            Spacer(Modifier.height(6.dp))
            Text(
                "本期不做。iPhone 上的 MPEG-TS 推流不对齐到 Android。",
                color = EdgeTheme.dim,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(28.dp))
        }
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = Color.White,
    unfocusedTextColor = Color.White,
    focusedBorderColor = EdgeTheme.sand,
    unfocusedBorderColor = Color.White.copy(alpha = 0.2f),
    focusedLabelColor = EdgeTheme.sand,
    unfocusedLabelColor = EdgeTheme.dim,
    cursorColor = EdgeTheme.sand,
)
