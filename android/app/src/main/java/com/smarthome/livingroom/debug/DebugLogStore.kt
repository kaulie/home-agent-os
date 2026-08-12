package com.smarthome.livingroom.debug

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.CopyOnWriteArrayList

/**
 * In-memory ring buffer of debug lines for the on-screen panel.
 */
object DebugLogStore {
    private const val MAX_LINES = 200
    private val lines = CopyOnWriteArrayList<String>()
    private val listeners = CopyOnWriteArrayList<() -> Unit>()
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

    fun snapshot(): List<String> = lines.toList()

    fun snapshotText(): String = snapshot().joinToString("\n")

    fun clear() {
        lines.clear()
        notifyChanged()
    }

    fun append(message: String) {
        val stamped = "[${timeFormat.format(Date())}] $message"
        lines.add(stamped)
        while (lines.size > MAX_LINES) {
            lines.removeAt(0)
        }
        notifyChanged()
    }

    fun addListener(listener: () -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: () -> Unit) {
        listeners.remove(listener)
    }

    private fun notifyChanged() {
        for (listener in listeners) {
            listener()
        }
    }
}
