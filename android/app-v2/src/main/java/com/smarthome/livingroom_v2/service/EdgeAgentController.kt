package com.smarthome.livingroom_v2.service

import android.content.Context
import android.util.Log
import com.smarthome.livingroom_v2.data.AppSettings

/**
 * Agent lifecycle controller.
 *
 * - [AppSettings.autoStartOnBoot]: persisted. Unaffected by Stop. Decides boot +
 *   process-recreate resume.
 * - Stop: temporary for **this process only** — stops polling now; does not clear
 *   autoStartOnBoot. After process kill/recreate, resume iff autoStartOnBoot.
 * - Start: intervention to run in the current process (and until Stop / death).
 */
object EdgeAgentController {
    private const val TAG = "EdgeAgentController"

    /**
     * Set when user presses Stop in this process. Prevents onResume from
     * immediately restarting while the process is still alive.
     * Reset on new process (defaults false) or [requestStart].
     */
    @Volatile
    var stoppedThisProcess: Boolean = false
        private set

    /** Start / resume background service for the current process. */
    fun requestStart(context: Context, reason: String = "manual") {
        val appContext = context.applicationContext
        stoppedThisProcess = false
        AppSettings(appContext).agentEnabled = true
        Log.i(TAG, "requestStart ($reason) stoppedThisProcess=false agentEnabled=true")
        EdgeAgentService.start(appContext)
    }

    /**
     * Stop polling for this process only.
     * Does **not** change [AppSettings.autoStartOnBoot].
     */
    fun requestStop(context: Context, reason: String = "manual") {
        val appContext = context.applicationContext
        stoppedThisProcess = true
        AppSettings(appContext).agentEnabled = false
        Log.i(
            TAG,
            "requestStop ($reason) stoppedThisProcess=true agentEnabled=false " +
                "(autoStartOnBoot unchanged=${AppSettings(appContext).autoStartOnBoot})",
        )
        EdgeAgentService.stop(appContext)
    }

    /**
     * Resume rules:
     * - If user Stop'd in this process → do nothing (temporary session stop).
     * - Else if [AppSettings.autoStartOnBoot] → start (boot / process recreate).
     * - Else if [AppSettings.agentEnabled] → start (same-process sticky / Start).
     */
    fun maybeResume(context: Context, reason: String = "resume") {
        val appContext = context.applicationContext
        val settings = AppSettings(appContext)
        if (stoppedThisProcess) {
            Log.i(TAG, "maybeResume skip ($reason): user stopped this process")
            return
        }
        if (settings.autoStartOnBoot) {
            Log.i(TAG, "maybeResume ($reason): autoStartOnBoot → start")
            requestStart(appContext, reason = reason)
            return
        }
        if (settings.agentEnabled) {
            Log.i(TAG, "maybeResume ($reason): agentEnabled → start")
            EdgeAgentService.start(appContext)
            return
        }
        Log.i(TAG, "maybeResume skip ($reason): no autoStart / not enabled")
    }

    /** BOOT_COMPLETED: only when autoStartOnBoot is checked. */
    fun onBootCompleted(context: Context) {
        val appContext = context.applicationContext
        if (!AppSettings(appContext).autoStartOnBoot) {
            Log.i(TAG, "onBootCompleted skip: autoStartOnBoot=false")
            return
        }
        Log.i(TAG, "onBootCompleted → start service")
        requestStart(appContext, reason = "boot")
    }

    /** Opt out of boot auto-start only; does not stop a currently running agent. */
    fun disableAutoStartOnly(context: Context) {
        AppSettings(context.applicationContext).autoStartOnBoot = false
        Log.i(TAG, "disableAutoStartOnly")
    }
}
