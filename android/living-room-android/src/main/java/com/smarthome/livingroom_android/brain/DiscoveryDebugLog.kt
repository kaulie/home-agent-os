package com.smarthome.livingroom_android.brain

import android.content.Context
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Same contract as iOS DiscoveryDebugLog: off until the user turns it on. */
object DiscoveryDebugLog {
    private const val PREFS = "living_room_android"
    private const val KEY = "ha.discoveryDebugLog.enabled"
    private const val MAX_LINES = 400
    private val lock = Any()
    private val lines = ArrayDeque<String>()
    @Volatile
    var text: String = ""
        private set

    fun isEnabled(context: Context): Boolean =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getBoolean(KEY, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putBoolean(KEY, enabled)
            .apply()
        if (enabled) log(context, "探测日志已打开", "connect")
    }

    fun log(context: Context?, message: String, category: String? = null) {
        val ctx = context ?: return
        if (!isEnabled(ctx)) return
        val ts = SimpleDateFormat("HH:mm:ss.SSS", Locale.US).format(Date())
        val line = if (!category.isNullOrEmpty()) {
            "[$ts] [$category] $message"
        } else {
            "[$ts] $message"
        }
        synchronized(lock) {
            lines.addLast(line)
            while (lines.size > MAX_LINES) lines.removeFirst()
            text = lines.joinToString("\n")
        }
    }

    fun clear() {
        synchronized(lock) {
            lines.clear()
            text = ""
        }
    }
}
