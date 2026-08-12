package com.smarthome.livingroom_android.data

import android.content.Context

/** Prefs for Living Room Android Edge. */
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

    var goproSsid: String
        get() = prefs.getString(KEY_GOPRO_SSID, "") ?: ""
        set(value) = prefs.edit().putString(KEY_GOPRO_SSID, value).apply()

    var goproPassword: String
        get() = prefs.getString(KEY_GOPRO_PASSWORD, "") ?: ""
        set(value) = prefs.edit().putString(KEY_GOPRO_PASSWORD, value).apply()

    var lastPhotoUrl: String
        get() = prefs.getString(KEY_LAST_PHOTO_URL, "") ?: ""
        set(value) = prefs.edit().putString(KEY_LAST_PHOTO_URL, value).apply()

    fun recordHeartbeatSuccess(atMs: Long = System.currentTimeMillis()) {
        prefs.edit()
            .putLong(KEY_HEARTBEAT_SUCCESS_COUNT, heartbeatSuccessCount + 1)
            .putLong(KEY_LAST_HEARTBEAT_SUCCESS_AT, atMs)
            .apply()
    }

    companion object {
        private const val PREFS = "living_room_android"
        private const val KEY_AUTO_START_ON_BOOT = "auto_start_on_boot"
        private const val KEY_AGENT_ENABLED = "agent_enabled"
        private const val KEY_HEARTBEAT_SUCCESS_COUNT = "heartbeat_success_count"
        private const val KEY_LAST_HEARTBEAT_SUCCESS_AT = "last_heartbeat_success_at"
        private const val KEY_GOPRO_SSID = "gopro_ssid"
        private const val KEY_GOPRO_PASSWORD = "gopro_password"
        private const val KEY_LAST_PHOTO_URL = "last_photo_url"
    }
}
