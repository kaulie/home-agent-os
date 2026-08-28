package com.smarthome.livingroom_android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.NestedScrollConnection
import androidx.compose.ui.input.nestedscroll.NestedScrollSource
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

data class PhotoVoiceTraceLine(
    val id: String,
    val atMs: Long,
    val kind: Kind,
    val text: String,
) {
    enum class Kind(val label: String) {
        STATUS("状态"),
        PARTIAL("片段"),
        FINAL("最终"),
        SEND("发送"),
        ERROR("错误"),
    }
}

/** Live mic level bars (0..1). */
@Composable
fun VoiceWaveform(
    level: Float,
    active: Boolean,
    modifier: Modifier = Modifier,
    barCount: Int = 20,
) {
    val bars = List(barCount) { index ->
        if (!active) 0.08f
        else {
            val center = (barCount - 1) / 2f
            val dist = kotlin.math.abs(index - center) / center
            val shape = 1f - dist * 0.55f
            (level * shape).coerceIn(0.08f, 1f)
        }
    }
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(36.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(Color.Black.copy(alpha = 0.45f))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.spacedBy(3.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.Bottom,
    ) {
        bars.forEach { h ->
            Box(
                Modifier
                    .width(5.dp)
                    .height((24 * h).dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(if (active && h > 0.2f) EdgeTheme.sand else Color.White.copy(alpha = 0.35f)),
            )
        }
    }
}

@Composable
fun PhotoVoiceTraceOverlay(
    lines: List<PhotoVoiceTraceLine>,
    modifier: Modifier = Modifier,
) {
    if (lines.isEmpty()) return
    var expanded by remember { mutableStateOf(true) }
    val newestFirst = remember(lines) { lines.asReversed() }
    val scrollState = rememberScrollState()
    val scrollGuard = remember(scrollState) {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource,
            ): Offset = Offset(0f, available.y)
        }
    }
    LaunchedEffect(newestFirst.firstOrNull()?.id) {
        if (expanded) scrollState.scrollTo(0)
    }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color.Black.copy(alpha = 0.65f))
            .padding(horizontal = 10.dp, vertical = 6.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("语音 trace", color = EdgeTheme.mist, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
            IconButton(
                onClick = { expanded = !expanded },
                modifier = Modifier.size(28.dp),
            ) {
                Icon(
                    if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                    contentDescription = if (expanded) "收起" else "展开",
                    tint = EdgeTheme.mist,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
        if (expanded) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 120.dp)
                    .nestedScroll(scrollGuard)
                    .verticalScroll(scrollState),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                newestFirst.forEach { line ->
                    PhotoVoiceTraceRow(line)
                }
            }
        } else {
            val last = newestFirst.firstOrNull()
            if (last != null) {
                PhotoVoiceTraceRow(last)
            }
        }
    }
}

@Composable
fun PhotoVoiceTracePanel(
    lines: List<PhotoVoiceTraceLine>,
    modifier: Modifier = Modifier,
) {
    if (lines.isEmpty()) return
    val newestFirst = remember(lines) { lines.asReversed() }
    val scrollState = rememberScrollState()
    val scrollGuard = remember(scrollState) {
        object : NestedScrollConnection {
            override fun onPostScroll(
                consumed: Offset,
                available: Offset,
                source: NestedScrollSource,
            ): Offset {
                // Do not let trace drag bubble to parent (e.g. gallery list / tab bar).
                return Offset(0f, available.y)
            }
        }
    }
    LaunchedEffect(newestFirst.firstOrNull()?.id) {
        scrollState.scrollTo(0)
    }
    Column(
        modifier = modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color.Black.copy(alpha = 0.62f))
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Text("语音 trace", color = EdgeTheme.mist, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .height(120.dp)
                .padding(top = 6.dp)
                .nestedScroll(scrollGuard)
                .verticalScroll(scrollState),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            newestFirst.forEach { line ->
                PhotoVoiceTraceRow(line)
            }
        }
    }
}

@Composable
private fun PhotoVoiceTraceRow(line: PhotoVoiceTraceLine) {
    val time = rememberTraceTime(line.atMs)
    val kindColor = when (line.kind) {
        PhotoVoiceTraceLine.Kind.PARTIAL -> EdgeTheme.sand.copy(alpha = 0.85f)
        PhotoVoiceTraceLine.Kind.FINAL -> Color.White
        PhotoVoiceTraceLine.Kind.SEND -> Color(0xFF7DDA8A)
        PhotoVoiceTraceLine.Kind.ERROR -> Color(0xFFFF8A80)
        PhotoVoiceTraceLine.Kind.STATUS -> EdgeTheme.mist
    }
    Row(Modifier.fillMaxWidth()) {
        Text(
            time,
            color = EdgeTheme.dim,
            fontSize = 10.sp,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.width(72.dp),
        )
        Text(
            line.kind.label,
            color = kindColor,
            fontSize = 10.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.width(36.dp),
        )
        Text(
            line.text,
            color = Color.White.copy(alpha = 0.92f),
            fontSize = 11.sp,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun rememberTraceTime(atMs: Long): String {
    val fmt = SimpleDateFormat("HH:mm:ss.SSS", Locale.CHINA)
    return fmt.format(Date(atMs))
}
