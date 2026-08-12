package com.smarthome.livingroom.control

import android.util.Base64
import android.util.Log
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

data class SpotifyTrackHit(
    val id: String,
    val name: String,
    val artists: String,
    val uri: String,
)

/**
 * Resolves 歌名 + 歌手 via Spotify Web API (Client Credentials).
 * Requires a free Spotify Developer app client id/secret.
 */
class SpotifySearchClient(
    private val clientId: String,
    private val clientSecret: String,
    private val http: OkHttpClient = defaultClient(),
) {
    @Volatile
    private var cachedToken: String? = null

    @Volatile
    private var tokenExpireAtMs: Long = 0L

    fun isConfigured(): Boolean =
        clientId.isNotBlank() && clientSecret.isNotBlank()

    fun searchBest(song: String, artist: String?): SpotifyTrackHit {
        require(isConfigured()) { "未配置 Spotify Client ID/Secret" }
        val songQuery = song.trim()
        require(songQuery.isNotEmpty()) { "song is required" }
        val artistQuery = artist?.trim().orEmpty()

        val q = buildString {
            append("track:")
            append(songQuery)
            if (artistQuery.isNotEmpty()) {
                append(" artist:")
                append(artistQuery)
            }
        }
        val encoded = URLEncoder.encode(q, StandardCharsets.UTF_8.name())
        val request = Request.Builder()
            .url("https://api.spotify.com/v1/search?q=$encoded&type=track&limit=10")
            .header("Authorization", "Bearer ${accessToken()}")
            .get()
            .build()

        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("Spotify 搜索失败: HTTP ${response.code}")
            }
            val body = response.body?.string().orEmpty()
            val items = JSONObject(body)
                .optJSONObject("tracks")
                ?.optJSONArray("items")
                ?: throw IllegalStateException("Spotify 未找到歌曲: $q")
            if (items.length() == 0) {
                throw IllegalStateException("Spotify 未找到歌曲: $q")
            }

            var best: SpotifyTrackHit? = null
            var bestScore = Int.MIN_VALUE
            for (i in 0 until items.length()) {
                val item = items.getJSONObject(i)
                val artistsArr = item.optJSONArray("artists")
                val artists = buildString {
                    if (artistsArr != null) {
                        for (j in 0 until artistsArr.length()) {
                            if (j > 0) append(" / ")
                            append(artistsArr.getJSONObject(j).optString("name"))
                        }
                    }
                }
                val hit = SpotifyTrackHit(
                    id = item.getString("id"),
                    name = item.optString("name"),
                    artists = artists,
                    uri = item.optString("uri").ifBlank { "spotify:track:${item.getString("id")}" },
                )
                val score = scoreHit(hit, songQuery, artistQuery)
                if (score > bestScore) {
                    bestScore = score
                    best = hit
                }
            }
            val chosen = best ?: throw IllegalStateException("Spotify 未找到歌曲: $q")
            Log.i(TAG, "hit ${chosen.uri} ${chosen.name} - ${chosen.artists} score=$bestScore")
            return chosen
        }
    }

    private fun accessToken(): String {
        val now = System.currentTimeMillis()
        cachedToken?.let { token ->
            if (now < tokenExpireAtMs - 30_000) return token
        }
        val basic = Base64.encodeToString(
            "$clientId:$clientSecret".toByteArray(StandardCharsets.UTF_8),
            Base64.NO_WRAP,
        )
        val body = FormBody.Builder()
            .add("grant_type", "client_credentials")
            .build()
        val request = Request.Builder()
            .url("https://accounts.spotify.com/api/token")
            .header("Authorization", "Basic $basic")
            .post(body)
            .build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("Spotify token 失败: HTTP ${response.code}")
            }
            val json = JSONObject(response.body?.string().orEmpty())
            val token = json.getString("access_token")
            val expiresIn = json.optLong("expires_in", 3600L)
            cachedToken = token
            tokenExpireAtMs = now + expiresIn * 1000L
            return token
        }
    }

    private fun scoreHit(hit: SpotifyTrackHit, song: String, artist: String): Int {
        var score = 0
        val name = hit.name.lowercase()
        val artists = hit.artists.lowercase()
        val songL = song.lowercase()
        val artistL = artist.lowercase()
        if (name == songL) score += 100
        else if (name.contains(songL)) score += 70
        if (artistL.isNotEmpty()) {
            when {
                artists == artistL -> score += 120
                artists.contains(artistL) -> score += 90
                else -> score -= 40
            }
        }
        return score
    }

    companion object {
        private const val TAG = "SpotifySearchClient"

        fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(8, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .writeTimeout(8, TimeUnit.SECONDS)
                .build()
    }
}
