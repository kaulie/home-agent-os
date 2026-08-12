package com.smarthome.livingroom.control

import android.util.Log
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

data class NetEaseSongHit(
    val id: Long,
    val name: String,
    val artists: String,
)

/**
 * Resolves 歌名 + 歌手 to a NetEase Cloud Music song id via the public search API.
 */
class NetEaseSearchClient(
    private val http: OkHttpClient = defaultClient(),
) {
    fun searchBest(song: String, artist: String?): NetEaseSongHit {
        val songQuery = song.trim()
        require(songQuery.isNotEmpty()) { "song is required" }
        val artistQuery = artist?.trim().orEmpty()

        val hits = LinkedHashMap<Long, NetEaseSongHit>()
        // cloudsearch usually ranks covers / originals better for 歌名+歌手.
        fetchCloudSearch(songQuery, artistQuery).forEach { hits[it.id] = it }
        fetchWebSearch(songQuery, artistQuery).forEach { hits.putIfAbsent(it.id, it) }

        if (hits.isEmpty()) {
            throw IllegalStateException("网易云未找到歌曲: $songQuery $artistQuery")
        }

        val chosen = hits.values.maxBy { scoreHit(it, songQuery, artistQuery) }
        val score = scoreHit(chosen, songQuery, artistQuery)
        if (artistQuery.isNotEmpty() && score < 80) {
            throw IllegalStateException(
                "未找到足够匹配「$songQuery - $artistQuery」的结果，最接近: ${chosen.name} - ${chosen.artists}",
            )
        }
        Log.i(TAG, "search hit id=${chosen.id} name=${chosen.name} artists=${chosen.artists} score=$score")
        return chosen
    }

    private fun fetchWebSearch(song: String, artist: String): List<NetEaseSongHit> {
        val query = if (artist.isEmpty()) song else "$song $artist"
        val encoded = URLEncoder.encode(query, StandardCharsets.UTF_8.name())
        val url =
            "https://music.163.com/api/search/get/web?s=$encoded&type=1&offset=0&total=true&limit=20"
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", USER_AGENT)
            .header("Referer", "https://music.163.com")
            .get()
            .build()
        return parseSongs(execute(request))
    }

    private fun fetchCloudSearch(song: String, artist: String): List<NetEaseSongHit> {
        val query = if (artist.isEmpty()) song else "$song $artist"
        val body = FormBody.Builder()
            .add("s", query)
            .add("type", "1")
            .add("limit", "20")
            .add("offset", "0")
            .build()
        val request = Request.Builder()
            .url("https://music.163.com/api/cloudsearch/pc")
            .header("User-Agent", USER_AGENT)
            .header("Referer", "https://music.163.com")
            .post(body)
            .build()
        return parseSongs(execute(request))
    }

    private fun execute(request: Request): String {
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("网易云搜索失败: HTTP ${response.code}")
            }
            return response.body?.string().orEmpty()
        }
    }

    private fun parseSongs(body: String): List<NetEaseSongHit> {
        if (body.isBlank()) return emptyList()
        val songs = JSONObject(body).optJSONObject("result")?.optJSONArray("songs") ?: return emptyList()
        val out = ArrayList<NetEaseSongHit>(songs.length())
        for (i in 0 until songs.length()) {
            val item = songs.getJSONObject(i)
            val artistsArr = item.optJSONArray("artists") ?: item.optJSONArray("ar")
            val artists = buildString {
                if (artistsArr != null) {
                    for (j in 0 until artistsArr.length()) {
                        if (j > 0) append(" / ")
                        append(artistsArr.getJSONObject(j).optString("name"))
                    }
                }
            }
            out.add(
                NetEaseSongHit(
                    id = item.getLong("id"),
                    name = item.optString("name"),
                    artists = artists,
                ),
            )
        }
        return out
    }

    private fun scoreHit(hit: NetEaseSongHit, song: String, artist: String): Int {
        var score = 0
        val name = hit.name.lowercase()
        val artists = hit.artists.lowercase()
        val songL = song.lowercase()
        val artistL = artist.lowercase()

        if (name == songL) score += 100
        else if (name.contains(songL)) score += 70
        else if (songL.contains(name)) score += 30

        if (artistL.isNotEmpty()) {
            when {
                artists == artistL -> score += 120
                artists.contains(artistL) -> score += 100
                // e.g. 天空之城（翻自 李志）
                name.contains(artistL) -> score += 95
                name.contains("翻自") && name.contains(artistL) -> score += 110
                else -> score -= 50
            }
        }
        return score
    }

    companion object {
        private const val TAG = "NetEaseSearchClient"
        private const val USER_AGENT =
            "Mozilla/5.0 (Linux; Android 12; TV) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"

        fun defaultClient(): OkHttpClient =
            OkHttpClient.Builder()
                .connectTimeout(8, TimeUnit.SECONDS)
                .readTimeout(10, TimeUnit.SECONDS)
                .writeTimeout(8, TimeUnit.SECONDS)
                .build()
    }
}
