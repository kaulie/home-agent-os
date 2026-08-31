package com.smarthome.livingroom_android.data

import android.content.Context
import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.brain.dto.ParticipantWire
import java.util.UUID

/** Prefs for HomeAgent Console (Android). */
class AppSettings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    var autoStartOnBoot: Boolean
        get() = prefs.getBoolean(KEY_AUTO_START_ON_BOOT, false)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_START_ON_BOOT, value).apply()

    var agentEnabled: Boolean
        get() = prefs.getBoolean(KEY_AGENT_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_AGENT_ENABLED, value).apply()

    var heartbeatSuccessCount: Long
        get() = prefs.getLong(KEY_HEARTBEAT_SUCCESS_COUNT, 0L)
        set(value) = prefs.edit().putLong(KEY_HEARTBEAT_SUCCESS_COUNT, value).apply()

    var lastHeartbeatSuccessAtMs: Long
        get() = prefs.getLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, value).apply()

    var clientHint: String
        get() = prefs.getString(KEY_CLIENT_HINT, "") ?: ""
        set(value) = prefs.edit().putString(KEY_CLIENT_HINT, value).apply()

    var registeredAtMs: Long
        get() = prefs.getLong(KEY_REGISTERED_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_REGISTERED_AT, value).apply()

    var lanBrainUrl: String
        get() = stored(KEY_LAN_BRAIN, "")
        set(value) = prefs.edit().putString(KEY_LAN_BRAIN, BrainEndpoint.normalizeBase(value)).apply()

    var cloudBrainUrl: String
        get() = stored(KEY_CLOUD_BRAIN, BrainEndpoint.DEFAULT_CLOUD_BASE)
        set(value) = prefs.edit().putString(KEY_CLOUD_BRAIN, BrainEndpoint.normalizeBase(value)).apply()

    var brainRouting: BrainEndpoint.Routing
        get() = BrainEndpoint.Routing.fromWire(prefs.getString(KEY_ROUTING, "auto"))
        set(value) = prefs.edit().putString(KEY_ROUTING, value.wire).apply()

    /** Last Brain intent URL that completed edge-register (iOS `lastRegisteredBrainURL`). */
    var lastRegisteredBrainUrl: String
        get() = prefs.getString(KEY_LAST_REGISTERED_BRAIN, "")?.trim().orEmpty()
        set(value) = prefs.edit().putString(KEY_LAST_REGISTERED_BRAIN, value.trim()).apply()

    var enabledRoles: List<String>
        get() {
            val saved = prefs.getStringSet(KEY_ROLES, null)
            val picked = saved ?: ParticipantWire.defaultRoles().toSet()
            return ParticipantWire.ordered(picked)
        }
        set(value) {
            prefs.edit().putStringSet(KEY_ROLES, ParticipantWire.ordered(value).toSet()).apply()
        }

    var lastReportedRoles: List<String>
        get() = ParticipantWire.ordered(prefs.getStringSet(KEY_LAST_ROLES, emptySet()) ?: emptySet())
        set(value) {
            prefs.edit().putStringSet(KEY_LAST_ROLES, ParticipantWire.ordered(value).toSet()).apply()
        }

    var lastReportedRolesLan: List<String>
        get() = ParticipantWire.ordered(prefs.getStringSet(KEY_LAST_ROLES_LAN, emptySet()) ?: emptySet())
        set(value) {
            prefs.edit().putStringSet(KEY_LAST_ROLES_LAN, ParticipantWire.ordered(value).toSet()).apply()
        }

    var lastReportedRolesCloud: List<String>
        get() = ParticipantWire.ordered(prefs.getStringSet(KEY_LAST_ROLES_CLOUD, emptySet()) ?: emptySet())
        set(value) {
            prefs.edit().putStringSet(KEY_LAST_ROLES_CLOUD, ParticipantWire.ordered(value).toSet()).apply()
        }

    fun lastReportedRoles(mode: BrainEndpoint.Mode): List<String> =
        if (mode == BrainEndpoint.Mode.LAN) lastReportedRolesLan else lastReportedRolesCloud

    fun setLastReportedRoles(mode: BrainEndpoint.Mode, roles: List<String>) {
        if (mode == BrainEndpoint.Mode.LAN) lastReportedRolesLan = roles else lastReportedRolesCloud = roles
    }

    var householdDirectoryJson: String
        get() = prefs.getString(KEY_HOUSEHOLD, "[]") ?: "[]"
        set(value) = prefs.edit().putString(KEY_HOUSEHOLD, value).apply()

    var localScanHistoryJson: String
        get() = prefs.getString(KEY_SCAN_HISTORY, "[]") ?: "[]"
        set(value) = prefs.edit().putString(KEY_SCAN_HISTORY, value).apply()

    /**
     * P0 Capability Exposure Policy as raw wire "lan:cap1,cap2;cloud:cap3".
     * Empty = open by default (backward compatible).
     */
    var exposurePolicyWire: String
        get() = prefs.getString(KEY_EXPOSURE_POLICY, "")?.trim().orEmpty()
        set(value) = prefs.edit().putString(KEY_EXPOSURE_POLICY, value.trim()).apply()

    /** Optional `X-Admin-Token` for Brain admin APIs (e.g. dev_task → agent-bridge). */
    var adminToken: String
        get() = prefs.getString(KEY_ADMIN_TOKEN, "")?.trim().orEmpty()
        set(value) = prefs.edit().putString(KEY_ADMIN_TOKEN, value.trim()).apply()

    /** Parsed exposure policy, or null when open. */
    fun exposurePolicy(): Map<String, List<String>>? = parseExposurePolicy(exposurePolicyWire)

    init {
        migrateEnableRuntimeOnce()
    }

    private fun parseExposurePolicy(raw: String): Map<String, List<String>>? {
        val text = raw.trim()
        if (text.isEmpty()) return null
        val out = linkedMapOf<String, List<String>>()
        for (part in text.split(";")) {
            val seg = part.trim()
            if (seg.isEmpty() || ":" !in seg) continue
            val parts = seg.split(":", limit = 2)
            val d = parts[0].trim().lowercase()
            val caps = parts.getOrElse(1) { "" }
            if (d.isEmpty()) continue
            out[d] = caps.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        }
        return out.takeIf { it.isNotEmpty() }
    }

    /** Existing Console installs saved intent_source+endpoint only; turn runtime on once. */
    private fun migrateEnableRuntimeOnce() {
        if (prefs.getBoolean(KEY_RUNTIME_MIGRATED, false)) return
        val saved = prefs.getStringSet(KEY_ROLES, null)
        if (saved != null && ParticipantWire.ROLE_RUNTIME !in saved) {
            enabledRoles = ParticipantWire.ordered(saved + ParticipantWire.ROLE_RUNTIME)
        }
        prefs.edit().putBoolean(KEY_RUNTIME_MIGRATED, true).apply()
    }

    fun recordHeartbeatSuccess(atMs: Long = System.currentTimeMillis()) {
        prefs.edit()
            .putLong(KEY_HEARTBEAT_SUCCESS_COUNT, heartbeatSuccessCount + 1)
            .putLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, atMs)
            .apply()
    }

    fun ensureClientHint(androidId: String?): String {
        val saved = clientHint.trim()
        if (saved.isNotEmpty()) return saved
        val suffix = androidId?.trim()?.replace("-", "")?.takeLast(8)?.takeIf { it.isNotEmpty() }
            ?: UUID.randomUUID().toString().replace("-", "").take(8)
        val hint = "living-room-android-$suffix"
        clientHint = hint
        return hint
    }

    private fun stored(key: String, fallback: String): String {
        val saved = prefs.getString(key, "")?.trim().orEmpty()
        return if (saved.isEmpty()) fallback else BrainEndpoint.normalizeBase(saved)
    }

    companion object {
        private const val PREFS = "living_room_android"
        private const val KEY_AUTO_START_ON_BOOT = "auto_start_on_boot"
        private const val KEY_AGENT_ENABLED = "agent_enabled"
        private const val KEY_HEARTBEAT_SUCCESS_COUNT = "heartbeat_success_count"
        private const val KEY_LAST_HEARTBEAT_SUCCESS_AT = "last_heartbeat_success_at"
        private const val KEY_CLIENT_HINT = "client_hint"
        private const val KEY_REGISTERED_AT = "registered_at_ms"
        private const val KEY_LAN_BRAIN = "brain_lan_url"
        private const val KEY_CLOUD_BRAIN = "brain_cloud_url"
        private const val KEY_ROUTING = "brain_routing"
        private const val KEY_LAST_REGISTERED_BRAIN = "last_registered_brain_url"
        private const val KEY_ROLES = "enabled_roles"
        private const val KEY_LAST_ROLES = "last_reported_roles"
        private const val KEY_LAST_ROLES_LAN = "last_reported_roles_lan"
        private const val KEY_LAST_ROLES_CLOUD = "last_reported_roles_cloud"
        private const val KEY_HOUSEHOLD = "household_directory_json"
        private const val KEY_SCAN_HISTORY = "local_scan_history_json"
        private const val KEY_RUNTIME_MIGRATED = "runtime_role_migrated_v1"
        private const val KEY_EXPOSURE_POLICY = "exposure_policy_wire"
        private const val KEY_ADMIN_TOKEN = "admin_token"
    }
}
