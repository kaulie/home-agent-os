package com.smarthome.plugin.chromecast

import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.skill.Skill
import com.smarthome.livingroom_android.skill.SkillContext
import com.smarthome.livingroom_android.skill.SkillResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class ChromecastCastSkill(
    private val onLog: (String) -> Unit = {},
) : Skill {
    override fun service(): ServiceDescriptor =
        ServiceDescriptor(
            serviceId = SKILL_ID,
            version = "0.1.0",
            displayName = "Chromecast Display",
            group = "display",
            capabilities = listOf(
                CapabilityDescriptor(
                    capabilityId = Capabilities.DISPLAY_PHOTO,
                    description = "能：把本步已给出的 image_ref（AssetRef）投到 Chromecast。仅用户明确要投电视时用。不能：拍照、自己捡图、收 photo_url、TTS。缺 image_ref 则失败。",
                    inputSchema = mapOf(
                        "image_ref" to SchemaField("string", required = true),
                    ),
                ),
            ),
        )

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.Main) {
        when (capabilityId) {
            Capabilities.DISPLAY_PHOTO -> {
                val url = params["photo_url"]?.toString()?.trim().orEmpty()
                if (url.isEmpty()) {
                    return@withContext SkillResult.error("missing photo_url")
                }
                val cast = CastSessionController.get(ctx.appContext)
                cast.onLog = onLog
                val result = cast.castPhoto(url)
                if (result.isSuccess) {
                    SkillResult.ok("cast ok → $url")
                } else {
                    SkillResult.error(result.exceptionOrNull()?.message ?: "cast failed")
                }
            }
            else -> SkillResult.error("unsupported capability: $capabilityId")
        }
    }

    companion object {
        const val SKILL_ID = "chromecast.display"
    }
}
