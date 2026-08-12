package com.smarthome.livingroom_android.command

import android.os.SystemClock

/** Synced Brain wall clock for timingDue / miss-window (not raw local wall clock). */
object BrainTimeSync {
    @Volatile
    private var brainTimeMs: Long? = null

    @Volatile
    private var localMonoAtSync: Long? = null

    fun applyHeartbeat(brainTimeMs: Long?) {
        if (brainTimeMs == null || brainTimeMs <= 0L) return
        this.brainTimeMs = brainTimeMs
        this.localMonoAtSync = SystemClock.elapsedRealtime()
    }

    /** Brain time + monotonic elapsed since last heartbeat sync. */
    fun nowMs(): Long {
        val brain = brainTimeMs
        val mono = localMonoAtSync
        if (brain == null || mono == null) return System.currentTimeMillis()
        return brain + (SystemClock.elapsedRealtime() - mono)
    }
}
