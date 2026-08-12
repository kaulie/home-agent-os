package com.smarthome.livingroom_android.command.runtime

/**
 * Intent-scoped key/value bag for `$photo_url` style params (aligned with iOS RuntimeContext).
 */
class RuntimeContext {
    private val values = linkedMapOf<String, String>()

    fun publish(outputs: Map<String, String>) {
        for ((k, v) in outputs) {
            val key = k.trim()
            val value = v.trim()
            if (key.isNotEmpty() && value.isNotEmpty()) {
                values[key] = value
            }
        }
    }

    fun load(values: Map<String, String>) = publish(values)

    fun get(key: String): String? = values[key.trim()]

    fun snapshot(): Map<String, String> = values.toMap()

    fun resolveParams(params: Map<String, Any?>): Map<String, Any?> {
        if (params.isEmpty()) return params
        val out = linkedMapOf<String, Any?>()
        for ((k, v) in params) {
            out[k] = resolveValue(v)
        }
        return out
    }

    private fun resolveValue(value: Any?): Any? {
        val s = value as? String ?: return value
        val trimmed = s.trim()
        if (trimmed.startsWith("\${") && trimmed.endsWith("}")) {
            val key = trimmed.removePrefix("\${").removeSuffix("}").trim()
            return get(key) ?: error("unresolved context key: $trimmed")
        }
        if (trimmed.startsWith("$") && !trimmed.startsWith("\${")) {
            val key = trimmed.removePrefix("$").trim()
            if (key.isNotEmpty() && key.all { it.isLetterOrDigit() || it == '_' }) {
                return get(key) ?: error("unresolved context key: $trimmed")
            }
        }
        return value
    }
}
