package com.smarthome.livingroom_v2.skill.music

import android.util.Log
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

data class NetEaseSongHit(
    val id: Long,
    val name: String,
    val artists: String,
)

data class NetEaseAlbumHit(
    val id: Long,
    val name: String,
    val artists: String,
    val firstSongId: Long?,
)

/**
 * Resolves song / artist / album queries to NetEase ids via the public search API.
 */
class NetEaseSearchClient(
    private val http: OkHttpClient = NetEaseHttp.client(),
) {
    /** Strategy 1: search single track (type=1), optional artist weighting. */
    fun searchBest(song: String, artist: String?): NetEaseSongHit {
        val songQuery = song.trim()
        require(songQuery.isNotEmpty()) { "song is required" }
        val artistQuery = artist?.trim().orEmpty()

        val hits = LinkedHashMap<Long, NetEaseSongHit>()
        fetchSongSearch(songQuery, artistQuery).forEach { hits[it.id] = it }

        if (hits.isEmpty()) {
            throw IllegalStateException("网易云未找到歌曲: $songQuery $artistQuery")
        }

        val chosen = hits.values.maxBy { scoreSongHit(it, songQuery, artistQuery) }
        val score = scoreSongHit(chosen, songQuery, artistQuery)
        if (artistQuery.isNotEmpty() && score < 80) {
            throw IllegalStateException(
                "未找到足够匹配「$songQuery - $artistQuery」的结果，最接近: ${chosen.name} - ${chosen.artists}",
            )
        }
        Log.i(TAG, "song hit id=${chosen.id} name=${chosen.name} artists=${chosen.artists} score=$score")
        return chosen
    }

    /** Strategy 2: search album (type=10); optional artist filter. */
    fun searchBestAlbum(album: String, artist: String?): NetEaseAlbumHit {
        val albumQuery = album.trim()
        require(albumQuery.isNotEmpty()) { "album is required" }
        val artistQuery = artist?.trim().orEmpty()

        val hits = fetchAlbumSearch(albumQuery, artistQuery)
        if (hits.isEmpty()) {
            throw IllegalStateException("网易云未找到专辑: $albumQuery $artistQuery")
        }

        val chosen = hits.maxBy { scoreAlbumHit(it, albumQuery, artistQuery) }
        val score = scoreAlbumHit(chosen, albumQuery, artistQuery)
        if (artistQuery.isNotEmpty() && score < 80) {
            throw IllegalStateException(
                "未找到足够匹配专辑「$albumQuery - $artistQuery」的结果，最接近: ${chosen.name} - ${chosen.artists}",
            )
        }

        val withSong = if (chosen.firstSongId != null) {
            chosen
        } else {
            chosen.copy(firstSongId = fetchAlbumFirstSongId(chosen.id))
        }
        Log.i(
            TAG,
            "album hit id=${withSong.id} name=${withSong.name} artists=${withSong.artists} " +
                "firstSong=${withSong.firstSongId} score=$score",
        )
        return withSong
    }

    /** Strategy 3: artist-only — search tracks with artist as query, pick best artist match. */
    fun searchBestByArtist(artist: String): NetEaseSongHit {
        val artistQuery = artist.trim()
        require(artistQuery.isNotEmpty()) { "artist is required" }

        val hits = LinkedHashMap<Long, NetEaseSongHit>()
        fetchSongSearch(artistQuery, artistQuery).forEach { hits[it.id] = it }
        // Also search with artist alone as the keyword (no song term).
        fetchSongSearchRaw(artistQuery).forEach { hits.putIfAbsent(it.id, it) }

        if (hits.isEmpty()) {
            throw IllegalStateException("网易云未找到歌手曲目: $artistQuery")
        }

        val chosen = hits.values.maxBy { scoreSongHit(it, song = "", artist = artistQuery) }
        val score = scoreSongHit(chosen, song = "", artist = artistQuery)
        if (score < 80) {
            throw IllegalStateException(
                "未找到足够匹配歌手「$artistQuery」的结果，最接近: ${chosen.name} - ${chosen.artists}",
            )
        }
        Log.i(TAG, "artist hit id=${chosen.id} name=${chosen.name} artists=${chosen.artists} score=$score")
        return chosen
    }

    private fun fetchSongSearch(song: String, artist: String): List<NetEaseSongHit> {
        val query = if (artist.isEmpty()) song else "$song $artist"
        return fetchSongSearchRaw(query)
    }

    private fun fetchSongSearchRaw(query: String): List<NetEaseSongHit> {
        val hits = LinkedHashMap<Long, NetEaseSongHit>()
        parseSongs(fetchCloudSearch(query, type = 1)).forEach { hits[it.id] = it }
        parseSongs(fetchWebSearch(query, type = 1)).forEach { hits.putIfAbsent(it.id, it) }
        return hits.values.toList()
    }

    private fun fetchAlbumSearch(album: String, artist: String): List<NetEaseAlbumHit> {
        val query = if (artist.isEmpty()) album else "$album $artist"
        val hits = LinkedHashMap<Long, NetEaseAlbumHit>()
        parseAlbums(fetchCloudSearch(query, type = 10)).forEach { hits[it.id] = it }
        parseAlbums(fetchWebSearch(query, type = 10)).forEach { hits.putIfAbsent(it.id, it) }
        return hits.values.toList()
    }

    private fun fetchWebSearch(query: String, type: Int): String {
        val encoded = URLEncoder.encode(query, StandardCharsets.UTF_8.name())
        val url =
            "https://music.163.com/api/search/get/web?s=$encoded&type=$type&offset=0&total=true&limit=20"
        val request = Request.Builder()
            .url(url)
            .header("User-Agent", USER_AGENT)
            .header("Referer", "https://music.163.com")
            .get()
            .build()
        return execute(request)
    }

    private fun fetchCloudSearch(query: String, type: Int): String {
        val body = FormBody.Builder()
            .add("s", query)
            .add("type", type.toString())
            .add("limit", "20")
            .add("offset", "0")
            .build()
        val request = Request.Builder()
            .url("https://music.163.com/api/cloudsearch/pc")
            .header("User-Agent", USER_AGENT)
            .header("Referer", "https://music.163.com")
            .post(body)
            .build()
        return execute(request)
    }

    private fun fetchAlbumFirstSongId(albumId: Long): Long? {
        val request = Request.Builder()
            .url("https://music.163.com/api/album/$albumId")
            .header("User-Agent", USER_AGENT)
            .header("Referer", "https://music.163.com")
            .get()
            .build()
        return try {
            val body = execute(request)
            if (body.isBlank()) return null
            val songs = JSONObject(body).optJSONObject("album")?.optJSONArray("songs")
                ?: JSONObject(body).optJSONArray("songs")
                ?: return null
            if (songs.length() == 0) null else songs.getJSONObject(0).optLong("id").takeIf { it > 0 }
        } catch (t: Throwable) {
            Log.w(TAG, "album detail failed id=$albumId: ${t.message}")
            null
        }
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
            out.add(
                NetEaseSongHit(
                    id = item.getLong("id"),
                    name = item.optString("name"),
                    artists = joinArtistNames(item.optJSONArray("artists") ?: item.optJSONArray("ar")),
                ),
            )
        }
        return out
    }

    private fun parseAlbums(body: String): List<NetEaseAlbumHit> {
        if (body.isBlank()) return emptyList()
        val albums = JSONObject(body).optJSONObject("result")?.optJSONArray("albums") ?: return emptyList()
        val out = ArrayList<NetEaseAlbumHit>(albums.length())
        for (i in 0 until albums.length()) {
            val item = albums.getJSONObject(i)
            val artistNames = when {
                item.has("artists") -> joinArtistNames(item.optJSONArray("artists"))
                item.has("artist") -> item.optJSONObject("artist")?.optString("name").orEmpty()
                else -> ""
            }
            val songs = item.optJSONArray("songs")
            val firstSongId = if (songs != null && songs.length() > 0) {
                songs.getJSONObject(0).optLong("id").takeIf { it > 0 }
            } else {
                null
            }
            out.add(
                NetEaseAlbumHit(
                    id = item.getLong("id"),
                    name = item.optString("name"),
                    artists = artistNames,
                    firstSongId = firstSongId,
                ),
            )
        }
        return out
    }

    private fun joinArtistNames(artistsArr: org.json.JSONArray?): String {
        if (artistsArr == null) return ""
        return buildString {
            for (j in 0 until artistsArr.length()) {
                if (j > 0) append(" / ")
                append(artistsArr.getJSONObject(j).optString("name"))
            }
        }
    }

    private fun scoreSongHit(hit: NetEaseSongHit, song: String, artist: String): Int {
        var score = 0
        val name = hit.name.lowercase()
        val artists = hit.artists.lowercase()
        val songL = song.lowercase()
        val artistL = artist.lowercase()

        if (songL.isNotEmpty()) {
            when {
                name == songL -> score += 100
                name.contains(songL) -> score += 70
                songL.contains(name) -> score += 30
            }
        }

        if (artistL.isNotEmpty()) {
            when {
                artists == artistL -> score += 120
                artists.contains(artistL) -> score += 100
                name.contains(artistL) -> score += 95
                name.contains("翻自") && name.contains(artistL) -> score += 110
                else -> score -= 50
            }
        }
        return score
    }

    private fun scoreAlbumHit(hit: NetEaseAlbumHit, album: String, artist: String): Int {
        var score = 0
        val name = hit.name.lowercase()
        val artists = hit.artists.lowercase()
        val albumL = album.lowercase()
        val artistL = artist.lowercase()

        when {
            name == albumL -> score += 100
            name.contains(albumL) -> score += 70
            albumL.contains(name) -> score += 30
        }

        if (artistL.isNotEmpty()) {
            when {
                artists == artistL -> score += 120
                artists.contains(artistL) -> score += 100
                else -> score -= 50
            }
        }
        return score
    }

    companion object {
        private const val TAG = "NetEaseSearchClient"
        private const val USER_AGENT =
            "Mozilla/5.0 (Linux; Android 12; TV) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    }
}
