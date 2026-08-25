package com.smarthome.livingroom_android.command

import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.skill.AssetUploadSkill
import com.smarthome.livingroom_android.skill.DocumentScanSkill
import com.smarthome.livingroom_android.skill.GoProCameraSkill
import com.smarthome.livingroom_android.skill.PhoneCallSkill
import java.util.UUID

/**
 * Console Edge: map advertised capabilities to installed skills.
 * Unmapped assigned steps are skipped with a readable msg.
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
            capability in Capabilities.SCAN_ALL ->
                Mapped(DocumentScanSkill.SKILL_ID, capability, cmd.params)
            capability == Capabilities.PHONE_CALL ->
                Mapped(PhoneCallSkill.SKILL_ID, capability, cmd.params)
            capability == Capabilities.CAMERA_CAPTURE ->
                Mapped(GoProCameraSkill.SKILL_ID, capability, cmd.params)
            capability == Capabilities.ASSET_UPLOAD ->
                Mapped(AssetUploadSkill.SKILL_ID, capability, cmd.params)
            capability == Capabilities.TAKE_VIDEO ->
                Mapped(null, capability, cmd.params, "take_video is not advertised on Console")
            capability in Capabilities.WIFI_ALL ->
                Mapped(null, capability, cmd.params, "network.wifi is not advertised on Console")
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
