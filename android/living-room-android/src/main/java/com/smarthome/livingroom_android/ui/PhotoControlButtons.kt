package com.smarthome.livingroom_android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.MicOff
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Capture-session mic control (camera is always on in session). */
@Composable
fun PhotoMicControl(
    micEnabled: Boolean,
    onToggleMic: () -> Unit,
    micBusy: Boolean,
    micLevel: Float,
    statusLine: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            modifier = Modifier
                .size(88.dp)
                .clip(CircleShape)
                .background(if (micEnabled) EdgeTheme.sand else Color.Black.copy(alpha = 0.55f))
                .clickable(enabled = !micBusy) { onToggleMic() },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = if (micEnabled) Icons.Filled.Mic else Icons.Filled.MicOff,
                contentDescription = if (micEnabled) "关闭麦克风" else "开启麦克风",
                tint = if (micEnabled) EdgeTheme.ink else Color.White,
                modifier = Modifier.size(44.dp),
            )
        }
        Spacer(Modifier.height(10.dp))
        VoiceWaveform(
            level = micLevel,
            active = micEnabled && (micBusy || micLevel > 0.12f),
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 8.dp),
        )
        Spacer(Modifier.height(12.dp))
        Text(
            "拍照已开启 · 点麦克风说话",
            color = Color.White,
            fontSize = 15.sp,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            when {
                micBusy -> statusLine.ifBlank { "正在听…" }
                micEnabled -> statusLine.ifBlank { "可以直接说话" }
                else -> "点麦克风说话"
            },
            color = if (micEnabled) EdgeTheme.sand else EdgeTheme.mist,
            fontSize = 14.sp,
            textAlign = TextAlign.Center,
        )
    }
}
