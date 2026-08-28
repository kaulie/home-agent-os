package com.smarthome.livingroom_android.data

import android.content.Context
import java.util.UUID

/** Persists Brain-issued edge_id so relaunches skip /edge-register. */
object EdgeIdStore {
    private const val PREFS = "living_room_android_edge_id"
    private const val KEY_ASSIGNED = "assigned_edge_id"
    private const val KEY_RUNTIME_ID = "runtime_id"

    fun load(context: Context): String? {
        val value = context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString(KEY_ASSIGNED, null)
            ?.trim()
            .orEmpty()
        return value.takeIf { it.isNotEmpty() }
    }

    fun save(context: Context, edgeId: String) {
        val trimmed = edgeId.trim()
        if (trimmed.isEmpty()) {
            clear(context)
            return
        }
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_ASSIGNED, trimmed)
            .apply()
    }

    fun clear(context: Context) {
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_ASSIGNED)
            .apply()
    }
}

/**
 * P0 dual-Brain: stable Runtime Identity, client-supplied and persisted.
 * Smooth migration: reuse a previously Brain-issued edge_id as the runtime_id.
 */
object RuntimeIdStore {
    private const val PREFS = "living_room_android_edge_id"
    private const val KEY_RUNTIME_ID = "runtime_id"

    fun load(context: Context): String? {
        val prefs = context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val rid = prefs.getString(KEY_RUNTIME_ID, null)?.trim().orEmpty()
        if (rid.isNotEmpty()) return rid
        // Smooth migration: adopt the legacy Brain-issued edge_id as runtime_id.
        val legacy = prefs.getString("assigned_edge_id", null)?.trim().orEmpty()
        return legacy.takeIf { it.isNotEmpty() }
    }

    fun save(context: Context, runtimeId: String) {
        val trimmed = runtimeId.trim()
        if (trimmed.isEmpty()) return
        context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_RUNTIME_ID, trimmed)
            .apply()
    }

    /** Load or generate+persist a stable runtime_id. */
    fun ensure(context: Context): String {
        load(context)?.let { return it }
        val rid = "runtime-android-" + UUID.randomUUID().toString().replace("-", "").take(16)
        save(context, rid)
        return rid
    }
}
