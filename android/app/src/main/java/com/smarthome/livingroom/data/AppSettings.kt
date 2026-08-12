package com.smarthome.livingroom.data

import android.content.Context
import com.smarthome.livingroom.BuildConfig

class AppSettings(context: Context) {
    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    var serverBaseUrl: String
        get() = prefs.getString(KEY_SERVER, BuildConfig.DEFAULT_SERVER_BASE_URL)
            ?.trimEnd('/')
            ?: BuildConfig.DEFAULT_SERVER_BASE_URL
        set(value) = prefs.edit().putString(KEY_SERVER, value.trimEnd('/')).apply()

    var deviceId: String
        get() = prefs.getString(KEY_DEVICE, BuildConfig.DEFAULT_DEVICE_ID)
            ?: BuildConfig.DEFAULT_DEVICE_ID
        set(value) = prefs.edit().putString(KEY_DEVICE, value).apply()

    var lastPollAt: Long
        get() = prefs.getLong(KEY_LAST_POLL, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_POLL, value).apply()

    /** Whether the most recent successful poll returned any commands. */
    var lastPollHadCommands: Boolean
        get() = prefs.getBoolean(KEY_LAST_POLL_HAD_COMMANDS, false)
        set(value) = prefs.edit().putBoolean(KEY_LAST_POLL_HAD_COMMANDS, value).apply()

    var lastCommandSummary: String
        get() = prefs.getString(KEY_LAST_CMD, "—") ?: "—"
        set(value) = prefs.edit().putString(KEY_LAST_CMD, value).apply()

    var lastCommandAt: Long
        get() = prefs.getLong(KEY_LAST_CMD_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_LAST_CMD_AT, value).apply()

    fun recordLastCommand(summary: String, at: Long = System.currentTimeMillis()) {
        prefs.edit()
            .putString(KEY_LAST_CMD, summary)
            .putLong(KEY_LAST_CMD_AT, at)
            .apply()
    }

    /** Whether remote command polling is enabled. Default: off. */
    var pollingEnabled: Boolean
        get() = prefs.getBoolean(KEY_POLLING_ENABLED, false)
        set(value) = prefs.edit().putBoolean(KEY_POLLING_ENABLED, value).apply()

    var spotifyClientId: String
        get() = prefs.getString(KEY_SPOTIFY_CLIENT_ID, "") ?: ""
        set(value) = prefs.edit().putString(KEY_SPOTIFY_CLIENT_ID, value.trim()).apply()

    var spotifyClientSecret: String
        get() = prefs.getString(KEY_SPOTIFY_CLIENT_SECRET, "") ?: ""
        set(value) = prefs.edit().putString(KEY_SPOTIFY_CLIENT_SECRET, value.trim()).apply()

    companion object {
        private const val PREFS = "living_room_control"
        private const val KEY_SERVER = "server_base_url"
        private const val KEY_DEVICE = "device_id"
        private const val KEY_LAST_POLL = "last_poll_at"
        private const val KEY_LAST_POLL_HAD_COMMANDS = "last_poll_had_commands"
        private const val KEY_LAST_CMD = "last_command_summary"
        private const val KEY_LAST_CMD_AT = "last_command_at"
        // New key so older installs that left polling on don't keep auto-pulling.
        private const val KEY_POLLING_ENABLED = "polling_enabled_default_off"
        private const val KEY_SPOTIFY_CLIENT_ID = "spotify_client_id"
        private const val KEY_SPOTIFY_CLIENT_SECRET = "spotify_client_secret"
    }
}
