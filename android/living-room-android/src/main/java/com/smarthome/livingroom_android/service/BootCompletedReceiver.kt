package com.smarthome.livingroom_android.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

/**
 * Starts EdgeAgentService after device boot when the user enabled auto-start.
 * Does not open MainActivity. Ignores MY_PACKAGE_REPLACED (same as legacy app).
 */
class BootCompletedReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (action != Intent.ACTION_BOOT_COMPLETED) {
            Log.i(TAG, "skip auto-start after $action")
            return
        }
        EdgeAgentController.onBootCompleted(context)
    }

    companion object {
        private const val TAG = "BootCompletedReceiver"
    }
}
