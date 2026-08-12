package com.smarthome.livingroom.control

/**
 * Parses play_song: song name only, or "歌曲名 歌手" (artist optional).
 */
object SongQueryParser {
    data class Parsed(
        val song: String,
        val artist: String?,
    )

    fun parse(song: String?, artist: String?): Parsed {
        val explicitArtist = artist?.trim()?.takeIf { it.isNotEmpty() }
        val raw = song?.trim().orEmpty()
        if (explicitArtist != null) {
            return Parsed(raw, explicitArtist)
        }
        if (raw.isEmpty()) {
            return Parsed("", null)
        }
        val space = raw.indexOf(' ')
        if (space in 1 until raw.lastIndex) {
            val name = raw.substring(0, space).trim()
            val singer = raw.substring(space + 1).trim()
            if (name.isNotEmpty() && singer.isNotEmpty()) {
                return Parsed(name, singer)
            }
        }
        return Parsed(raw, null)
    }
}
