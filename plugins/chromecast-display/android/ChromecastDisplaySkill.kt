package com.smarthome.livingroom_v2.skill.display

import android.content.Intent
import android.util.Log
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
 * Chromecast TV on-device photo display.
 * Wire: service chromecast.display / group display / display.photo.
 */
class ChromecastDisplaySkill : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.1.0",
        displayName = "Chromecast 投屏",
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
                    "asset_ref" to SchemaField(
                        type = "string",
                        required = true,
                        description = "AssetRef JSON {asset_id, type}。禁止 photo_url。",
                    ),
                ),
            ),
        ),
    )

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.Main) {
        Log.i(TAG, "execute capability=$capabilityId params=$params plan=${ctx.planId}")
        when (capabilityId) {
            Capabilities.DISPLAY_PHOTO -> displayPhoto(params, ctx)
            else -> SkillResult.error("unsupported capability: $capabilityId")
        }
    }

    private fun displayPhoto(params: Map<String, Any?>, ctx: SkillContext): SkillResult {
        val raw = params["photo_url"]?.toString()?.trim().orEmpty()
        if (raw.isEmpty()) {
            return SkillResult.error("display.photo requires photo_url")
        }
        val lower = raw.lowercase()
        if (!lower.startsWith("http://") && !lower.startsWith("https://")) {
            return SkillResult.error("photo_url must be http(s): $raw")
        }
        return try {
            val intent = Intent(ctx.appContext, PhotoCastActivity::class.java).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                putExtra(PhotoCastActivity.EXTRA_PHOTO_URL, raw)
            }
            ctx.appContext.startActivity(intent)
            SkillResult.ok("casting photo · $raw")
        } catch (t: Throwable) {
            Log.e(TAG, "start PhotoCastActivity failed", t)
            SkillResult.error("failed to open cast UI: ${t.message}")
        }
    }

    companion object {
        const val SKILL_ID = "chromecast.display"
        private const val TAG = "ChromecastDisplay"
    }
}
