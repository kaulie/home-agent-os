package com.smarthome.livingroom_v2.skill.display

import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.view.Gravity
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Fullscreen photo viewer for [ChromecastDisplaySkill] / display.photo.
 */
class PhotoCastActivity : AppCompatActivity() {
    private val scope = CoroutineScope(Dispatchers.Main + Job())
    private lateinit var imageView: ImageView
    private lateinit var statusView: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.BLACK)
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        }
        imageView = ImageView(this).apply {
            scaleType = ImageView.ScaleType.FIT_CENTER
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        }
        statusView = TextView(this).apply {
            setTextColor(Color.LTGRAY)
            textSize = 18f
            gravity = Gravity.CENTER
            text = "加载中…"
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT,
            )
        }
        root.addView(imageView)
        root.addView(statusView)
        setContentView(root)

        val url = intent?.getStringExtra(EXTRA_PHOTO_URL)?.trim().orEmpty()
        if (url.isEmpty()) {
            statusView.text = "缺少 photo_url"
            return
        }
        loadPhoto(url)
    }

    private fun loadPhoto(url: String) {
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { downloadBitmap(url) }
            }
            result.onSuccess { bitmap ->
                statusView.text = ""
                statusView.visibility = android.view.View.GONE
                imageView.setImageBitmap(bitmap)
            }.onFailure { err ->
                Log.e(TAG, "load failed url=$url", err)
                statusView.visibility = android.view.View.VISIBLE
                statusView.text = "加载失败：${err.message ?: err.javaClass.simpleName}"
            }
        }
    }

    private fun downloadBitmap(url: String) =
        http.newCall(
            Request.Builder().url(url).get().build(),
        ).execute().use { response ->
            if (!response.isSuccessful) {
                error("HTTP ${response.code}")
            }
            val bytes = response.body?.bytes() ?: error("empty body")
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                ?: error("decode failed (${bytes.size} bytes)")
        }

    override fun onDestroy() {
        scope.coroutineContext[Job]?.cancel()
        super.onDestroy()
    }

    companion object {
        const val EXTRA_PHOTO_URL = "photo_url"
        private const val TAG = "PhotoCastActivity"
        private val http = OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
    }
}
