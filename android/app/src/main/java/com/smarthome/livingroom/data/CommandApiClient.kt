package com.smarthome.livingroom.data

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class CommandApiClient(
    private val settings: AppSettings,
    private val http: OkHttpClient = defaultClient(),
) {
    fun fetchPendingCommands(): List<RemoteCommand> {
        val url = "${settings.serverBaseUrl}/api/v1/devices/${settings.deviceId}/commands"
        val request = Request.Builder().url(url).get().build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("poll failed: HTTP ${response.code}")
            }
            val body = response.body?.string().orEmpty()
            val root = JSONObject(body)
            val array = root.optJSONArray("commands") ?: return emptyList()
            return buildList {
                for (i in 0 until array.length()) {
                    add(RemoteCommand.fromJson(array.getJSONObject(i)))
                }
            }
        }
    }

    /**
     * Acknowledges a command.
     * @return true if newly acked; false if already gone (HTTP 404 — treated as already acked).
     */
    fun ack(commandId: String, result: AckResult): Boolean {
        val url =
            "${settings.serverBaseUrl}/api/v1/devices/${settings.deviceId}/commands/$commandId/ack"
        val payload = JSONObject()
            .put("status", result.status)
            .put("message", result.message)
            .toString()
        val request = Request.Builder()
            .url(url)
            .post(payload.toRequestBody(JSON))
            .build()
        http.newCall(request).execute().use { response ->
            if (response.code == 404) {
                // Command already removed (duplicate poll / server restart / prior ack)
                return false
            }
            if (!response.isSuccessful) {
                throw IllegalStateException("ack failed: HTTP ${response.code}")
            }
            return true
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(8, TimeUnit.SECONDS)
                .readTimeout(8, TimeUnit.SECONDS)
                .writeTimeout(8, TimeUnit.SECONDS)
                .build()
    }
}
