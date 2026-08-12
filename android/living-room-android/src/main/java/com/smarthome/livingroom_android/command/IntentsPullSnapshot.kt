package com.smarthome.livingroom_android.command

import org.json.JSONObject

/**
 * One intents poll cycle for UI (snapshot box + run log).
 */
data class IntentsPullSnapshot(
    val atMs: Long,
    val requestUrl: String,
    val httpCode: Int?,
    val rawBody: String,
    val commands: List<Command>,
    /** Relevant intents after terminal/relevance filter (peek input for pipeline). */
    val intents: List<JSONObject> = emptyList(),
    val error: String? = null,
) {
    val ok: Boolean get() = error == null

    fun summaryLine(): String {
        if (error != null) return "拉取失败 · $error"
        return if (intents.isEmpty() && commands.isEmpty()) {
            "空队列 · 0 intents"
        } else {
            "pulled ${intents.size} intent(s) / ${commands.size} local step(s)"
        }
    }

    fun displayBody(maxChars: Int = 4000): String {
        val header = buildString {
            append("URL: ").append(requestUrl).append('\n')
            if (httpCode != null) append("HTTP ").append(httpCode).append('\n')
            if (error != null) append("ERROR: ").append(error).append('\n')
            append("intents=").append(intents.size)
                .append(" localSteps=").append(commands.size).append('\n')
            append("---\n")
        }
        val body = rawBody.ifBlank { "(empty body)" }
        val clipped =
            if (body.length <= maxChars) body
            else body.take(maxChars) + "\n… truncated ${body.length - maxChars} chars"
        return header + clipped
    }
}
