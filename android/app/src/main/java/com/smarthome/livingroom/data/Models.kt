package com.smarthome.livingroom.data

import org.json.JSONObject

enum class MusicApp(val wire: String) {
    SPOTIFY("spotify"),
    NETEASE("netease");

    companion object {
        fun fromWire(value: String): MusicApp =
            entries.firstOrNull { it.wire.equals(value, ignoreCase = true) }
                ?: throw IllegalArgumentException("unknown app: $value")
    }
}

enum class CommandAction(val wire: String) {
    LAUNCH("launch"),
    PLAY("play"),
    PAUSE("pause"),
    PLAY_PAUSE("play_pause"),
    NEXT("next"),
    PREVIOUS("previous"),
    STOP("stop"),
    /** Search by song (+ optional artist) and play. Currently NetEase-first. */
    PLAY_SONG("play_song");

    companion object {
        fun fromWire(value: String): CommandAction =
            entries.firstOrNull { it.wire.equals(value, ignoreCase = true) }
                ?: throw IllegalArgumentException("unknown action: $value")
    }
}

data class RemoteCommand(
    val id: String,
    val action: CommandAction,
    val app: MusicApp,
    val uri: String? = null,
    val song: String? = null,
    val artist: String? = null,
    val createdAt: Double? = null,
) {
    companion object {
        fun fromJson(obj: JSONObject): RemoteCommand =
            RemoteCommand(
                id = obj.getString("id"),
                action = CommandAction.fromWire(obj.getString("action")),
                app = MusicApp.fromWire(obj.getString("app")),
                uri = optionalString(obj, "uri"),
                song = optionalString(obj, "song"),
                artist = optionalString(obj, "artist"),
                createdAt = if (obj.has("created_at") && !obj.isNull("created_at")) {
                    obj.getDouble("created_at")
                } else {
                    null
                },
            )

        private fun optionalString(obj: JSONObject, key: String): String? =
            if (obj.has(key) && !obj.isNull(key)) {
                obj.getString(key).takeIf { it.isNotBlank() }
            } else {
                null
            }
    }
}

data class AckResult(
    val status: String,
    val message: String? = null,
)
