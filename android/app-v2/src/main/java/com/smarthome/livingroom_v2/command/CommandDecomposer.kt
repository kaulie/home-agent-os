package com.smarthome.livingroom_v2.command

import com.smarthome.livingroom_v2.capability.Capabilities
import com.smarthome.livingroom_v2.skill.music.NetEaseMusicSkill
import java.util.UUID

/**
 * Map server intent `execution_plan[].capability` → local Task.
 * Mirrors iOS `CommandDecomposer`.
 * Install matrix: Chromecast = NetEase only; display.photo / GoPro run on iPhone.
 */
object CommandDecomposer {
    fun fromServerCommand(cmd: Command): List<Task> {
        val mapped = mapCapability(cmd)
        return listOf(
            Task(
                taskId = "task-${cmd.commandId}-${UUID.randomUUID().toString().take(6)}",
                commandId = cmd.commandId,
                skillId = mapped.skillId,
                action = mapped.capabilityId,
                params = mapped.params,
                schedule = cmd.schedule,
                targetHint = mapped.capabilityId,
                skipReason = mapped.skipReason,
            ),
        )
    }

    private data class Mapped(
        val skillId: String?,
        val capabilityId: String,
        val params: Map<String, Any?>,
        val skipReason: String? = null,
    )

    private fun mapCapability(cmd: Command): Mapped {
        val capability = resolveCapabilityId(cmd)
        if (capability.isEmpty()) {
            return Mapped(
                skillId = null,
                capabilityId = "",
                params = cmd.params,
                skipReason = "missing capability_id",
            )
        }
        return when {
            capability in Capabilities.MUSIC_ALL -> {
                val params = normalizeMusicParams(capability, cmd.params).toMutableMap()
                params["capability"] = capability
                Mapped(
                    skillId = NetEaseMusicSkill.SKILL_ID,
                    capabilityId = capability,
                    params = params,
                )
            }
            capability in Capabilities.DISPLAY_ALL ->
                Mapped(
                    skillId = null,
                    capabilityId = capability,
                    params = cmd.params,
                    skipReason = "chromecast.display runs on iphone Cast sender",
                )
            capability in Capabilities.CAMERA_ALL ->
                Mapped(
                    skillId = null,
                    capabilityId = capability,
                    params = cmd.params,
                    skipReason = "gopro.camera not installed on chromecast",
                )
            capability in Capabilities.BLUETOOTH_ALL ->
                Mapped(
                    skillId = null,
                    capabilityId = capability,
                    params = cmd.params,
                    skipReason = "marshall.willen not installed on chromecast",
                )
            else ->
                Mapped(
                    skillId = null,
                    capabilityId = capability,
                    params = cmd.params,
                    skipReason = "unsupported capability: '$capability'",
                )
        }
    }

    private fun resolveCapabilityId(cmd: Command): String {
        val fromParams = cmd.params["capability"]?.toString()?.trim().orEmpty()
        return when {
            fromParams.isNotEmpty() -> fromParams
            cmd.device.trim().isNotEmpty() -> cmd.device.trim()
            else -> cmd.action.trim()
        }
    }

    /** Keep only song / artist / album for music.play. */
    private fun normalizeMusicParams(
        capability: String,
        params: Map<String, Any?>,
    ): Map<String, Any?> {
        if (capability != Capabilities.MUSIC_PLAY) return params
        val out = params.toMutableMap()
        val song = out["song"]?.toString()?.trim().orEmpty()
        val artist = out["artist"]?.toString()?.trim().orEmpty()
        val album = out["album"]?.toString()?.trim().orEmpty()
        if (song.isNotEmpty()) out["song"] = song else out.remove("song")
        if (artist.isNotEmpty()) out["artist"] = artist else out.remove("artist")
        if (album.isNotEmpty()) out["album"] = album else out.remove("album")
        return out
    }
}
