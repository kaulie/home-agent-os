package com.smarthome.livingroom_v2.data

import android.content.Context

/** Lightweight prefs for app-v2 (boot autostart, agent desired state). */
class AppSettings(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /**
     * When true: BOOT_COMPLETED starts the agent, and a **new process** after kill
     * will resume polling via [com.smarthome.livingroom_v2.service.EdgeAgentController.maybeResume].
     * Stop does **not** clear this flag.
     */
    var autoStartOnBoot: Boolean
        get() = prefs.getBoolean(KEY_AUTO_START_ON_BOOT, false)
        set(value) = prefs.edit().putBoolean(KEY_AUTO_START_ON_BOOT, value).apply()

    /**
     * Whether the foreground service should be running in the current desire sense.
     * Cleared by Stop (session); set by Start. Cross-process resume after kill is
     * governed by [autoStartOnBoot], not this flag alone.
     */
    var agentEnabled: Boolean
        get() = prefs.getBoolean(KEY_AGENT_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_AGENT_ENABLED, value).apply()

    /** Cumulative successful online heartbeats (persisted). */
    var heartbeatSuccessCount: Long
        get() = prefs.getLong(KEY_HEARTBEAT_SUCCESS_COUNT, 0L)
        set(value) = prefs.edit().putLong(KEY_HEARTBEAT_SUCCESS_COUNT, value).apply()

    /** Epoch ms of last successful online heartbeat; 0 if never. */
    var lastHeartbeatSuccessAtMs: Long
        get() = prefs.getLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, value).apply()

    fun recordHeartbeatSuccess(atMs: Long = System.currentTimeMillis()) {
        prefs.edit()
            .putLong(KEY_HEARTBEAT_SUCCESS_COUNT, heartbeatSuccessCount + 1)
            .putLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, atMs)
            .apply()
    }

    companion object {
        private const val PREFS = "living_room_v2"
        private const val KEY_AUTO_START_ON_BOOT = "auto_start_on_boot"
        private const val KEY_AGENT_ENABLED = "agent_enabled"
        private const val KEY_HEARTBEAT_SUCCESS_COUNT = "heartbeat_success_count"
        private const val KEY_LAST_HEARTBEAT_SUCCESS_AT = "last_heartbeat_success_at"
    }
}
