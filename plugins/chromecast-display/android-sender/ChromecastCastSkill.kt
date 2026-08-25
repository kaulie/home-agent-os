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
                    role = "单图投屏器",
                    plannerRecognize = "把一张已有 Image Asset 投到电视/投屏端。入参 asset_ref（常为 \$asset_ref）。这是计划步，不能只用 presentation.endpoint 代替。多张轮播不要用本步",
                    typicalTriggers = listOf("把这张图投到电视", "投屏", "投到电视", "丢到电视", "放到电视"),
                    doNotDispatch = listOf("拍多图", "幻灯片", "放歌", "按厂商选 Chromecast"),
                    kind = "output",
                    inputSchema = mapOf(
                        "asset_ref" to SchemaField("string", required = true),
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
