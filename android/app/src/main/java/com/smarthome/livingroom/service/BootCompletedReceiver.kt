package com.smarthome.livingroom.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.smarthome.livingroom.data.AppSettings
import com.smarthome.livingroom.debug.DebugLogStore

class BootCompletedReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action ?: return
        if (
            action != Intent.ACTION_BOOT_COMPLETED &&
            action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            return
        }

        val settings = AppSettings(context.applicationContext)
        // Only resume after device boot when user previously left polling on.
        // Do not auto-start on app update/reinstall.
        if (action != Intent.ACTION_BOOT_COMPLETED) {
            Log.i(TAG, "skip auto-start after $action")
            return
        }
        if (!settings.pollingEnabled) {
            Log.i(TAG, "skip auto-start after boot: polling disabled")
            return
        }

        Log.i(TAG, "auto-starting poll service after boot")
        DebugLogStore.append("开机后拉取开关为开，自动开始轮询")
        CommandPollService.start(context.applicationContext)
    }

    companion object {
        private const val TAG = "BootCompletedReceiver"
    }
}
