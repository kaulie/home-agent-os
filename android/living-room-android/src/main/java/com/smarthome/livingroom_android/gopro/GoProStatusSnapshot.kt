package com.smarthome.livingroom_android.gopro

import org.json.JSONObject

/** Parsed subset of GoPro `/gp/gpControl/status` (HERO4+ gpControl). */
data class GoProStatusSnapshot(
    val mode: Mode,
    val isBusy: Boolean,
    val displayLine: String,
) {
    enum class Mode(val raw: Int) {
        VIDEO(0),
        PHOTO(1),
        MULTI(2),
        UNKNOWN(-1),
        ;

        val label: String
            get() = when (this) {
                VIDEO -> "录像"
                PHOTO -> "拍照"
                MULTI -> "连拍/延时"
                UNKNOWN -> "未知模式"
            }

        companion object {
            fun fromRaw(raw: Int): Mode = entries.firstOrNull { it.raw == raw } ?: UNKNOWN
        }
    }

    companion object {
        fun parse(jsonBody: String): GoProStatusSnapshot? {
            val root = runCatching { JSONObject(jsonBody) }.getOrNull() ?: return null
            val status = root.optJSONObject("status") ?: return null
            val mode = Mode.fromRaw(intVal(status, "43") ?: -1)
            val busy = (intVal(status, "8") ?: 0) != 0
            val name = status.optString("30").trim()
            val parts = mutableListOf(mode.label, if (busy) "忙碌/录制中" else "空闲")
            intVal(status, "70")?.let { parts += "电量${it}%" }
            if (name.isNotEmpty()) parts += name
            return GoProStatusSnapshot(mode = mode, isBusy = busy, displayLine = parts.joinToString(" · "))
        }

        private fun intVal(o: JSONObject, key: String): Int? {
            if (!o.has(key) || o.isNull(key)) return null
            val v = o.opt(key)
            return when (v) {
                is Number -> v.toInt()
                is String -> v.toIntOrNull()
                else -> null
            }
        }
    }
}
