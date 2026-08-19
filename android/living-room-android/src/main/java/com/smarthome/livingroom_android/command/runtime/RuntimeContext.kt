package com.smarthome.livingroom_android.command.runtime

import org.json.JSONArray
import org.json.JSONObject

/**
 * Intent-scoped key/value bag for `$photo_url` style params (aligned with iOS / Mac).
 * Supports whole-value and inline `$name` / `${name}`, dotted JSON paths
 * (`$lighting.whole`), and legacy `$perception_json.summary` → `$summary`.
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

    fun get(key: String): String? = values[key.trim()]?.takeIf { it.isNotEmpty() }

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
        if ("{{" in s || "}}" in s) {
            error("unsupported param template (use \$var): $s")
        }
        val pattern = Regex("""\$\{([A-Za-z_][A-Za-z0-9_.]*)\}|\$([A-Za-z_][A-Za-z0-9_.]*)""")
        if (!pattern.containsMatchIn(s)) {
            return value
        }
        return pattern.replace(s) { m ->
            val name = m.groupValues[1].ifEmpty { m.groupValues[2] }
            lookup(name) ?: error("unresolved context variable \$$name")
        }
    }

    private fun lookup(name: String): String? {
        // Legacy: $perception_json.summary → flat $summary
        if (name == "perception_json" || name.startsWith("perception_json.")) {
            val rest = name.removePrefix("perception_json").trimStart('.')
            if (rest.isEmpty()) return null
            return lookup(rest)
        }

        get(name)?.let { return it }

        if ("." in name) {
            val parts = name.split(".")
            if (parts.size < 2) return null
            var rootVal = get(parts[0])
            if (rootVal == null) {
                val snake = camelToSnake(parts[0])
                if (snake != parts[0]) rootVal = get(snake)
            }
            return rootVal?.let { jsonPathGet(it, parts.drop(1)) }
        }

        val snake = camelToSnake(name)
        if (snake != name) {
            get(snake)?.let { return it }
        }
        return null
    }

    companion object {
        /** photoURL → photo_url */
        fun camelToSnake(name: String): String {
            val s1 = name.replace(Regex("(.)([A-Z][a-z]+)"), "$1_$2")
            return s1.replace(Regex("([a-z0-9])([A-Z])"), "$1_$2").lowercase()
        }

        fun jsonPathGet(rootText: String, path: List<String>): String? {
            var cur: Any = try {
                JSONObject(rootText)
            } catch (_: Exception) {
                try {
                    JSONArray(rootText)
                } catch (_: Exception) {
                    return null
                }
            }
            for (part in path) {
                cur = when (cur) {
                    is JSONObject -> {
                        when {
                            cur.has(part) -> cur.get(part)
                            cur.has(camelToSnake(part)) -> cur.get(camelToSnake(part))
                            else -> return null
                        }
                    }
                    is JSONArray -> {
                        val idx = part.toIntOrNull() ?: return null
                        if (idx < 0 || idx >= cur.length()) return null
                        cur.get(idx)
                    }
                    else -> return null
                }
            }
            return when (cur) {
                is String -> cur.trim().ifEmpty { null }
                is JSONObject, is JSONArray -> cur.toString()
                JSONObject.NULL -> null
                else -> cur.toString().trim().ifEmpty { null }
            }
        }
    }
}
