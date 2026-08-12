package com.smarthome.livingroom_android.command

import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.plugin.gopro.WifiNetworkSkill
import java.util.UUID

/**
 * Slim Edge: only [network.wifi] executes locally.
 * Other capabilities are tracked/skipped (camera/cast/music belong elsewhere).
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
            return Mapped(null, "", cmd.params, "missing capability_id")
        }
        return when {
            capability in Capabilities.WIFI_ALL ->
                Mapped(WifiNetworkSkill.SKILL_ID, capability, cmd.params)
            capability in Capabilities.CAMERA_ALL ->
                Mapped(null, capability, cmd.params, "camera runs on capture edge (not android slim)")
            capability in Capabilities.DISPLAY_ALL ->
                Mapped(null, capability, cmd.params, "display.photo runs on Cast sender edge")
            capability in Capabilities.MUSIC_ALL ->
                Mapped(null, capability, cmd.params, "music runs on chromecast app-v2")
            else ->
                Mapped(null, capability, cmd.params, "unsupported on living-room-android: '$capability'")
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
}
