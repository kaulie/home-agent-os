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
        version = "0.4.0",
        displayName = "网易云音乐",
        group = "music",
        capabilities = listOf(
            // Structured ads — aligned with mac/src/mac_edge/capability_ads.py (not 能/不能 prose).
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_PLAY,
                role = "音乐播放器",
                plannerRecognize = "按歌名/歌手/专辑开始放歌（网易云）。入参 song/artist/album。不负责连蓝牙音箱，不负责暂停/切歌",
                typicalTriggers = listOf("放一首周杰伦", "播放歌曲", "放歌", "放十年", "来首邓丽君"),
                doNotDispatch = listOf("蓝牙连接", "TTS", "开灯", "暂停", "下一首"),
                kind = "action",
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
                role = "暂停播放器",
                plannerRecognize = "暂停当前正在放的歌，不换歌、不选新歌。用户说「暂停一下」用本步，不是停止、不是下一首",
                typicalTriggers = listOf("暂停", "暂停播放", "先停一下"),
                doNotDispatch = listOf("选歌", "蓝牙连接", "TTS", "下一首", "停止播放"),
                kind = "action",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_STOP,
                role = "停止播放器",
                plannerRecognize = "停掉当前播放（这首结束，不是暂停可继续）。用户说「关掉音乐」用本步",
                typicalTriggers = listOf("停止播放", "关掉音乐", "别放了"),
                doNotDispatch = listOf("选歌", "蓝牙连接", "TTS", "暂停", "下一首"),
                kind = "action",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_NEXT,
                role = "下一首切换器",
                plannerRecognize = "切到播放队列的下一首。用户说「下一首/切歌/换一首」用本步，不是按歌名点播",
                typicalTriggers = listOf("下一首", "切歌", "换一首"),
                doNotDispatch = listOf("选歌", "蓝牙连接", "TTS", "暂停", "上一首"),
                kind = "action",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.MUSIC_PREVIOUS,
                role = "上一首切换器",
                plannerRecognize = "切回播放队列的上一首。用户说「上一首/上一曲」用本步",
                typicalTriggers = listOf("上一首", "上一曲"),
                doNotDispatch = listOf("选歌", "蓝牙连接", "TTS", "暂停", "下一首"),
                kind = "action",
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
                "深链失败: ${opened.detail ?: "unknown"}（需安装网易云手机版或 TV 版）",
            )
        }
        return confirmPlayOrFail(
            context,
            opened,
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
                "深链失败: ${opened.detail ?: "unknown"}（需安装网易云手机版或 TV 版）",
            )
        }
        return confirmPlayOrFail(
            context,
            opened,
            "深链已打开 $label → #${hit.id} ${hit.name} - ${hit.artists}" +
                " via ${opened.method}@${opened.packageName}",
        )
    }

    private fun confirmPlayOrFail(
        context: Context,
        opened: NetEaseDeepLinkLauncher.OpenResult,
        openedMsg: String,
    ): SkillResult {
        nudgePlayback(context)
        if (!NetEasePlayPolicy.playbackConfirmed(isMusicActive(context))) {
            return SkillResult.error(
                "网易云深链已发出但未检测到播放（accepted≠playing）" +
                    " via ${opened.method}@${opened.packageName}。电视静音/登录页/TV 版不接 orpheus 都会如此。",
            )
        }
        return SkillResult.ok(openedMsg)
    }

    private fun nudgePlayback(context: Context) {
        repeat(3) {
            dispatchMediaKey(context, KeyEvent.KEYCODE_MEDIA_PLAY)
            SystemClock.sleep(700)
        }
    }

    private fun isMusicActive(context: Context): Boolean {
        val audio = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        repeat(8) {
            if (audio.isMusicActive) return true
            SystemClock.sleep(400)
        }
        return audio.isMusicActive
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
