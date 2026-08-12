package com.smarthome.livingroom_android.data

import android.content.Context

/** Persists Brain-issued edge_id so relaunches skip /edge-register. */
object EdgeIdStore {
    private const val PREFS = "living_room_android_edge_id"
    private const val KEY_ASSIGNED = "assigned_edge_id"

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
