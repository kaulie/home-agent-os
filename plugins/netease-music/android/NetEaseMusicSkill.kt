package com.smarthome.livingroom_v2.skill.music

import android.content.Context
import android.media.AudioManager
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import com.smarthome.livingroom_v2.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_v2.brain.dto.SchemaField
import com.smarthome.livingroom_v2.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_v2.capability.Capabilities
import com.smarthome.livingroom_v2.skill.Skill
import com.smarthome.livingroom_v2.skill.SkillContext
import com.smarthome.livingroom_v2.skill.SkillResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * NetEase via API search + phone-app deep link. No accessibility.
 * Wire: service netease.music / group music / music.play|pause|stop|next|previous.
 *
 * music.play strategies (priority): song → album → artist-only.
 */
class NetEaseMusicSkill(
    private val search: NetEaseSearchClient = NetEaseSearchClient(),
) : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.3.0",
        displayName = "网易云音乐",
        group = "music",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_PLAY,
                description = "能：按 song / album / artist 在网易云播放。用户要放歌时用本能力。不能：用 query.content 或 notify.speak 顶替；无本能力时 plan=[]；不投屏、不 TTS 念歌词当播放。song/artist/album 至少填一个。",
                inputSchema = mapOf(
                    "song" to SchemaField(
                        type = "string",
                        required = false,
                        description = "歌曲",
                    ),
                    "artist" to SchemaField(
                        type = "string",
                        required = false,
                        description = "歌手",
                    ),
                    "album" to SchemaField(
                        type = "string",
                        required = false,
                        description = "专辑",
                    ),
                ),
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_PAUSE,
                description = "能：暂停当前网易云播放。不能：开始播放（用 music.play）；搜歌；TTS；投屏。",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_STOP,
                description = "能：停止当前网易云播放。不能：开始播放（用 music.play）；搜歌；TTS；投屏。",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_NEXT,
                description = "能：网易云切到下一首。不能：指定歌名播放（用 music.play）；TTS；投屏。",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_PREVIOUS,
                description = "能：网易云切到上一首。不能：指定歌名播放（用 music.play）；TTS；投屏。",
            ),
        ),
    )

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.IO) {
        Log.i(TAG, "execute capability=$capabilityId params=$params plan=${ctx.planId}")
        when (capabilityId) {
            Capabilities.MUSIC_PLAY -> playMusic(params, ctx.appContext)
            Capabilities.MUSIC_PAUSE -> {
                dispatchMediaKey(ctx.appContext, KeyEvent.KEYCODE_MEDIA_PAUSE)
                SkillResult.ok("media pause")
            }
            Capabilities.MUSIC_STOP -> {
                dispatchMediaKey(ctx.appContext, KeyEvent.KEYCODE_MEDIA_STOP)
                SkillResult.ok("media stop")
            }
            Capabilities.MUSIC_NEXT -> {
                dispatchMediaKey(ctx.appContext, KeyEvent.KEYCODE_MEDIA_NEXT)
                SkillResult.ok("media next")
            }
            Capabilities.MUSIC_PREVIOUS -> {
                dispatchMediaKey(ctx.appContext, KeyEvent.KEYCODE_MEDIA_PREVIOUS)
                SkillResult.ok("media previous")
            }
            else -> SkillResult.error("unsupported capability: $capabilityId")
        }
    }

    private fun playMusic(params: Map<String, Any?>, context: Context): SkillResult {
        val song = params.stringParam("song")
        val artist = params.stringParam("artist")
        val album = params.stringParam("album")
        if (song.isEmpty() && artist.isEmpty() && album.isEmpty()) {
            return SkillResult.error(
                "${Capabilities.MUSIC_PLAY} requires song, artist, or album",
            )
        }

        return when {
            song.isNotEmpty() -> playBySong(song, artist.ifEmpty { null }, context)
            album.isNotEmpty() -> playByAlbum(album, artist.ifEmpty { null }, context)
            else -> playByArtist(artist, context)
        }
    }

    private fun playBySong(song: String, artist: String?, context: Context): SkillResult {
        val label = if (artist != null) "「$song - $artist」" else "「$song」"
        val hit = try {
            search.searchBest(song, artist)
        } catch (t: Throwable) {
            return SkillResult.error("搜歌失败: ${t.message}")
        }
        Log.i(TAG, "strategy=song hit #${hit.id} ${hit.name} - ${hit.artists}")
        return openSongAndNudge(context, hit, label)
    }

    private fun playByAlbum(album: String, artist: String?, context: Context): SkillResult {
        val label = if (artist != null) "专辑「$album - $artist」" else "专辑「$album」"
        val hit = try {
            search.searchBestAlbum(album, artist)
        } catch (t: Throwable) {
            return SkillResult.error("搜专辑失败: ${t.message}")
        }
        Log.i(
            TAG,
            "strategy=album hit #${hit.id} ${hit.name} - ${hit.artists} firstSong=${hit.firstSongId}",
        )

        val opened = NetEaseDeepLinkLauncher(context).openAlbum(hit.id, hit.firstSongId)
        if (!opened.success) {
            return SkillResult.error(
                "深链失败: ${opened.detail ?: "unknown"}（需安装手机版网易云）",
            )
        }
        nudgePlayback(context)
        return SkillResult.ok(
            "深链已打开 $label → album#${hit.id} ${hit.name} - ${hit.artists}" +
                " via ${opened.method}@${opened.packageName}",
        )
    }

    private fun playByArtist(artist: String, context: Context): SkillResult {
        val label = "歌手「$artist」"
        val hit = try {
            search.searchBestByArtist(artist)
        } catch (t: Throwable) {
            return SkillResult.error("搜歌手失败: ${t.message}")
        }
        Log.i(TAG, "strategy=artist hit #${hit.id} ${hit.name} - ${hit.artists}")
        return openSongAndNudge(context, hit, label)
    }

    private fun openSongAndNudge(
        context: Context,
        hit: NetEaseSongHit,
        label: String,
    ): SkillResult {
        val opened = NetEaseDeepLinkLauncher(context).openSong(hit.id)
        if (!opened.success) {
            return SkillResult.error(
                "深链失败: ${opened.detail ?: "unknown"}（需安装手机版网易云）",
            )
        }
        nudgePlayback(context)
        return SkillResult.ok(
            "深链已打开 $label → #${hit.id} ${hit.name} - ${hit.artists}" +
                " via ${opened.method}@${opened.packageName}",
        )
    }

    private fun nudgePlayback(context: Context) {
        repeat(3) {
            dispatchMediaKey(context, KeyEvent.KEYCODE_MEDIA_PLAY)
            SystemClock.sleep(700)
        }
    }

    private fun dispatchMediaKey(context: Context, keyCode: Int) {
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        val now = SystemClock.uptimeMillis()
        val down = KeyEvent(
            now, now, KeyEvent.ACTION_DOWN, keyCode, 0, 0, 0, 0, KeyEvent.FLAG_FROM_SYSTEM,
        )
        val up = KeyEvent(
            now, now + 50, KeyEvent.ACTION_UP, keyCode, 0, 0, 0, 0, KeyEvent.FLAG_FROM_SYSTEM,
        )
        audio.dispatchMediaKeyEvent(down)
        audio.dispatchMediaKeyEvent(up)
    }

    private fun Map<String, Any?>.stringParam(key: String): String =
        this[key]?.toString()?.trim().orEmpty()

    companion object {
        const val SKILL_ID = "netease.music"
        private const val TAG = "NetEaseMusicSkill"
    }
}
