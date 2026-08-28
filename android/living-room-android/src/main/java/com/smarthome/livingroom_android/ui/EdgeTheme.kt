package com.smarthome.livingroom_android.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.displayCutoutPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

object EdgeTheme {
    val ink = Color(0xFF0D121C)
    val panel = Color(0xFF1A212E)
    val panelStroke = Color.White.copy(alpha = 0.08f)
    val sand = Color(0xFFD1B27A)
    val mist = Color.White.copy(alpha = 0.72f)
    val dim = Color.White.copy(alpha = 0.42f)
    val chatBg = Color(0xFF12151C)
    val bubbleUser = Color(0xFF3B6FE0)
    val bubbleAssistant = Color(0xFF252A35)
}

/** Status bar + display cutout — keep top controls tappable on notched devices. */
fun Modifier.edgeSafeTop(): Modifier = statusBarsPadding().displayCutoutPadding()

@Composable
fun EdgeCanvas(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(modifier.fillMaxSize()) {
        Box(
            Modifier
                .fillMaxSize()
                .background(EdgeTheme.ink),
        )
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.radialGradient(
                        colors = listOf(
                            Color(0x2E2E3847),
                            Color.Transparent,
                        ),
                        center = Offset(80f, 40f),
                        radius = 900f,
                    ),
                ),
        )
        content()
    }
}

@Composable
fun EdgeHeroTitle(text: String) {
    Text(
        text = text,
        color = Color.White.copy(alpha = 0.94f),
        fontSize = 34.sp,
        fontWeight = FontWeight.SemiBold,
        fontFamily = FontFamily.Serif,
    )
}

@Composable
fun EdgeHeroSubtitle(text: String) {
    Text(
        text = text,
        color = EdgeTheme.mist,
        fontSize = 14.sp,
    )
}

@Composable
fun EdgeSectionLabel(text: String) {
    Text(
        text = text.uppercase(),
        color = EdgeTheme.sand.copy(alpha = 0.85f),
        fontSize = 11.sp,
        fontWeight = FontWeight.SemiBold,
        letterSpacing = 1.4.sp,
    )
}

@Composable
fun EdgePanel(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .background(EdgeTheme.panel)
            .border(1.dp, EdgeTheme.panelStroke, RoundedCornerShape(20.dp))
            .padding(18.dp),
    ) {
        content()
    }
}

@Composable
fun EdgeEmptyPlaceholder(title: String, detail: String) {
    EdgePanel {
        Text(
            title,
            color = Color.White.copy(alpha = 0.9f),
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(10.dp))
        Text(detail, color = EdgeTheme.dim, fontSize = 14.sp)
    }
}
