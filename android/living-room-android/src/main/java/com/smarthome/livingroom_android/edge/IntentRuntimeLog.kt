package com.smarthome.livingroom_android.edge

import java.util.ArrayDeque
import java.util.concurrent.ConcurrentHashMap

/** Best-effort per-intent runtime log lines from local Edge execution. */
object IntentRuntimeLog {
    private const val MAX_LINES = 80
    private val lines = ConcurrentHashMap<String, ArrayDeque<String>>()

    fun append(intentId: String?, line: String) {
        val iid = intentId?.trim().orEmpty()
        val text = line.trim()
        if (iid.isEmpty() || text.isEmpty()) return
        val queue = lines.getOrPut(iid) { ArrayDeque() }
        synchronized(queue) {
            queue.addLast(text)
            while (queue.size > MAX_LINES) {
                queue.removeFirst()
            }
        }
    }

    fun snapshot(intentId: String): List<String> {
        val iid = intentId.trim()
        if (iid.isEmpty()) return emptyList()
        val queue = lines[iid] ?: return emptyList()
        synchronized(queue) {
            return queue.toList()
        }
    }

    fun snapshotMap(intentId: String, contextKeys: List<String> = emptyList()): Map<String, Any> {
        val out = linkedMapOf<String, Any>()
        val logLines = snapshot(intentId)
        if (logLines.isNotEmpty()) {
            out["lines"] = logLines
        }
        if (contextKeys.isNotEmpty()) {
            out["runtime_context_keys"] = contextKeys
        }
        return out
    }
}
