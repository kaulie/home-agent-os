package com.smarthome.livingroom_android.brain

/**
 * Two persisted Brain slots (LAN / Cloud) plus helpers to turn a base into `/api/v1/intent`.
 * Mirrors iOS `BrainEndpoint`.
 * Fresh-install defaults: edit `config/endpoints.json` then `python3 tools/sync_endpoints.py`.
 */
object BrainEndpoint {
    const val DEFAULT_LAN_BASE = "http://192.168.3.73:9527"
    const val DEFAULT_CLOUD_BASE = "http://115.190.153.53:9527"

    enum class Mode {
        LAN,
        CLOUD,
        ;

        val label: String get() = if (this == LAN) "局域网" else "云端"
    }

    enum class Routing {
        AUTO,
        LAN,
        CLOUD,
        ;

        val title: String
            get() = when (this) {
                AUTO -> "按网络自动"
                LAN -> "锁定局域网"
                CLOUD -> "锁定云端"
            }

        val pickerLabel: String get() = title

        val subtitle: String
            get() = when (this) {
                AUTO -> "在家 Wi‑Fi 且局域网 Brain 可达时走局域网，否则走云端。"
                LAN -> "始终连家里的 Brain。外出或局域网不通时对话会失败。"
                CLOUD -> "始终连云端 Brain。即使在家也不走局域网。"
            }

        val wire: String
            get() = when (this) {
                AUTO -> "auto"
                LAN -> "lan"
                CLOUD -> "cloud"
            }

        companion object {
            fun fromWire(raw: String?): Routing {
                return when (raw?.trim()?.lowercase()) {
                    "lan" -> LAN
                    "cloud" -> CLOUD
                    else -> AUTO
                }
            }
        }
    }

    enum class PathKind {
        WIFI,
        WIRED,
        CELLULAR,
        NONE,
        UNKNOWN,
        ;

        val looksOnHomeLAN: Boolean get() = this == WIFI || this == WIRED

        val label: String
            get() = when (this) {
                WIFI -> "Wi‑Fi"
                WIRED -> "有线"
                CELLULAR -> "蜂窝"
                NONE -> "无网络"
                UNKNOWN -> "未知"
            }
    }

    fun normalizeBase(raw: String): String {
        var value = raw.trim()
        while (value.endsWith("/")) {
            value = value.dropLast(1)
        }
        return value
    }

    fun intentUrl(from: String): String {
        val base = normalizeBase(from)
        if (base.endsWith("/api/v1/intent")) return base
        if (base.contains("/api/v1/")) return base
        return "$base/api/v1/intent"
    }

    fun displayBase(from: String): String {
        var value = normalizeBase(from)
        if (value.endsWith("/api/v1/intent")) {
            value = value.dropLast("/api/v1/intent".length)
        }
        return normalizeBase(value)
    }

    fun apiUrl(fromIntentOrBase: String, leaf: String): String {
        val trimmed = normalizeBase(fromIntentOrBase)
        val path = when {
            trimmed.endsWith("/intent") ->
                trimmed.dropLast("intent".length) + leaf.trimStart('/')
            trimmed.contains("/api/v1/") -> {
                val idx = trimmed.indexOf("/api/v1/")
                trimmed.substring(0, idx + "/api/v1/".length) + leaf.trimStart('/')
            }
            else -> "$trimmed/api/v1/${leaf.trimStart('/')}"
        }
        return path
    }

    fun destLabel(intentUrl: String, cloudBase: String = DEFAULT_CLOUD_BASE): String {
        val given = displayBase(intentUrl)
        val cloud = displayBase(cloudBase)
        if (given.equals(cloud, ignoreCase = true)) return "cloud"
        val givenHost = runCatching { java.net.URI(given).host }.getOrNull()?.lowercase().orEmpty()
        val cloudHost = runCatching { java.net.URI(cloud).host }.getOrNull()?.lowercase().orEmpty()
        if (givenHost.isNotEmpty() && givenHost == cloudHost) return "cloud"
        return "img_server"
    }

    fun pingUrl(fromIntentOrBase: String, clientTimeMs: Long): String {
        val base = apiUrl(fromIntentOrBase, "ping")
        val sep = if (base.contains("?")) "&" else "?"
        return "${base}${sep}client_time_ms=$clientTimeMs"
    }

    fun intentsListUrl(
        fromIntentOrBase: String,
        participantId: String,
        beforeId: Int?,
        limit: Int,
    ): String {
        val base = apiUrl(fromIntentOrBase, "intents")
        val builder = StringBuilder(base)
        builder.append("?participant_id=").append(java.net.URLEncoder.encode(participantId, "UTF-8"))
        builder.append("&limit=").append(limit.coerceIn(1, 5))
        if (beforeId != null && beforeId >= 1) {
            builder.append("&before_id=").append(beforeId)
        }
        return builder.toString()
    }

    fun intentDetailUrl(fromIntentOrBase: String, intentId: String): String {
        val base = apiUrl(fromIntentOrBase, "intent_detail")
        val sep = if (base.contains("?")) "&" else "?"
        return "${base}${sep}intent_id=${java.net.URLEncoder.encode(intentId, "UTF-8")}"
    }

    fun assetContentUrl(
        fromIntentOrBase: String,
        assetId: String,
        intentId: String,
        representation: String,
    ): String {
        val encodedId = java.net.URLEncoder.encode(assetId, "UTF-8")
        val base = apiUrl(fromIntentOrBase, "assets/$encodedId/content")
        val sep = if (base.contains("?")) "&" else "?"
        val iid = java.net.URLEncoder.encode(intentId, "UTF-8")
        val rep = java.net.URLEncoder.encode(representation, "UTF-8")
        return "${base}${sep}intent_id=$iid&representation=$rep"
    }

    fun livingRoomIntentsPullUrl(fromIntentOrBase: String): String =
        apiUrl(fromIntentOrBase, "devices/living-room/intents")
}

data class BrainNetworkEnvironment(
    val pathKind: BrainEndpoint.PathKind = BrainEndpoint.PathKind.UNKNOWN,
    val looksOnHomeLAN: Boolean = false,
    val lanProbeOk: Boolean? = null,
    val lanProbeDetail: String = "",
    val routing: BrainEndpoint.Routing = BrainEndpoint.Routing.AUTO,
    val mode: BrainEndpoint.Mode = BrainEndpoint.Mode.CLOUD,
    val activeIntentUrl: String = BrainEndpoint.intentUrl(BrainEndpoint.DEFAULT_CLOUD_BASE),
    val resolveBusy: Boolean = false,
) {
    val modeLabel: String get() = mode.label
    val routingLabel: String get() = routing.title
    val activeBaseUrl: String get() = BrainEndpoint.displayBase(activeIntentUrl)

    val summaryLine: String
        get() {
            val path = if (looksOnHomeLAN) {
                "像在家庭局域网（${pathKind.label}）"
            } else {
                "不在家庭局域网（${pathKind.label}）"
            }
            val probe = when (lanProbeOk) {
                true -> "LAN 探测成功"
                false -> "LAN 探测失败"
                null -> "尚未探测 LAN"
            }
            return "$path · $probe · 路由 $routingLabel · 当前 $modeLabel $activeBaseUrl"
        }
}
