package com.smarthome.livingroom_android.service

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.smarthome.livingroom_android.R
import com.smarthome.livingroom_android.app.LivingRoomAndroidApp
import com.smarthome.livingroom_android.app.MainActivity
import com.smarthome.livingroom_android.data.AppSettings

/**
 * Background host for EdgeAgent (foreground notification for keep-alive).
 * UI start/stop only request start/stop; boot / [EdgeAgentController.maybeResume] also drive this.
 */
class EdgeAgentService : Service() {
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!AppSettings(this).agentEnabled) {
            Log.i(TAG, "onStartCommand but agentEnabled=false → stopSelf")
            stopSelf()
            return START_NOT_STICKY
        }
        startAsForeground()
        runCatching {
            LivingRoomAndroidApp.instance.edgeAgent.start()
            Log.i(TAG, "EdgeAgent started from service")
        }.onFailure { t ->
            Log.e(TAG, "failed to start EdgeAgent", t)
        }
        return START_STICKY
    }

    override fun onDestroy() {
        runCatching {
            if (LivingRoomAndroidApp.instance.edgeAgent.running) {
                LivingRoomAndroidApp.instance.edgeAgent.stop()
                Log.i(TAG, "EdgeAgent stopped in onDestroy")
            }
        }
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startAsForeground() {
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.service_notification_title))
            .setContentText(getString(R.string.service_notification_text))
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setContentIntent(open)
            .setOngoing(true)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            @Suppress("DEPRECATION")
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    companion object {
        const val CHANNEL_ID = "edge_agent_v2"
        private const val NOTIFICATION_ID = 2001
        private const val TAG = "EdgeAgentService"

        fun start(context: Context) {
            val intent = Intent(context, EdgeAgentService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, EdgeAgentService::class.java))
        }
    }
}
