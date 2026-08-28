package com.smarthome.livingroom_android.skill

import android.util.Log
import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.gopro.GoProDriver
import com.smarthome.livingroom_android.gopro.GoProNetworks
import com.smarthome.livingroom_android.intent.IntentApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * iPhone-style `camera.capture`: talk to GoPro on its AP, write a local inbox
 * capture_ref (not an Asset). Does not join or switch Wi‑Fi. Upload is `asset.upload`.
 */
class GoProCameraSkill(
    private val intentUrl: () -> String,
    private val participantId: () -> String,
    private val api: IntentApi,
) : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.1.0",
        displayName = "GoPro Camera",
        group = "camera",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.CAMERA_CAPTURE,
                kind = "input",
                role = "拍照执行器",
                plannerRecognize = "按快门拍一张现场照（客厅、电视画面、眼前的东西），写入本机 inbox，产出 capture_ref（还不是 Asset）。允许当「给人看 / 问图上有什么 / 投电视」的前序步。本步不上传、不投屏、不能单步当最终图。下一步上传用 \$capture_ref。禁止把 path 写进 plan",
                typicalTriggers = listOf("拍一张", "看看现在", "拍照", "拍张照", "拍的照片", "拍一下", "看看客厅电视画面", "拍一下电视屏幕"),
                doNotDispatch = listOf(
                    "上传",
                    "传到图床",
                    "传到云上",
                    "单步作为最终给用户看的图",
                    "放歌",
                    "无拍照直接回答画面内容",
                    "本机后置拍照",
                ),
                inputSchema = emptyMap(),
                outputSchema = mapOf(
                    "capture_ref" to SchemaField(
                        type = "string",
                        required = true,
                        description = "CaptureRef JSON {capture_id, type, mime_type}。本机 inbox 句柄，还不是 Asset。禁止 path / photo_url / asset_id。",
                    ),
                ),
                composition = "atomic",
            ),
            CapabilityDescriptor(
                capabilityId = Capabilities.CAMERA_CAPTURE_AND_UPLOAD,
                kind = "action",
                composition = "composite",
                decomposesTo = listOf(Capabilities.CAMERA_CAPTURE, Capabilities.ASSET_UPLOAD),
                preferWhen = "拍照后还有后续动作要消费这张照片（给人看、变成 Asset、vision、投屏）时，优先本能力，不要把 decomposes_to 拆成多步",
                role = "拍照并上传器",
                plannerRecognize = "拍一张现场照并在同一台设备上上传成 Image Asset，产出 asset_ref。拍照后还要给人看、给视觉问、投电视时优先本步，不要再拆成拍照+上传两步（capture_ref 不能跨机）。本步不负责看图理解、不投屏",
                typicalTriggers = listOf(
                    "拍张照片我看一下",
                    "拍张照片我看看",
                    "拍的给我看",
                    "拍照后上传",
                    "把刚拍的照片传到图床",
                ),
                doNotDispatch = listOf("只上传已有图", "看图理解本身", "投屏本身", "不再拍照只传旧图"),
                inputSchema = mapOf(
                    "dest" to SchemaField(
                        type = "string",
                        required = false,
                        description = "img_server（默认）| cloud。传给内部 asset.upload。",
                    ),
                ),
                outputSchema = mapOf(
                    "asset_ref" to SchemaField(
                        type = "string",
                        required = true,
                        description = "上传后的 AssetRef JSON。禁止 photo_url / path / capture_ref 当用户可见 identity。",
                    ),
                    "dest" to SchemaField(
                        type = "string",
                        required = false,
                        description = "img_server 或 cloud",
                    ),
                ),
            ),
        ),
    )

    override suspend fun isAvailable(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult {
        val probe = GoProDriver(ctx.appContext).probeAvailable(2)
        if (!probe.ok) {
            return SkillResult.error(probe.message)
        }
        if (capabilityId == Capabilities.CAMERA_CAPTURE_AND_UPLOAD) {
            return SkillResult.ok("available")
        }
        return SkillResult.ok("available")
    }

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.IO) {
        val driver = GoProDriver(ctx.appContext)
        val probe = driver.probeAvailable(2)
        if (!probe.ok) return@withContext SkillResult.error(probe.message)
        val jpeg = try {
            driver.captureJpeg(probe.network)
        } catch (t: Throwable) {
            return@withContext SkillResult.error(
                "拍照失败：${t.message ?: "GoPro 快门或下载出错"}",
            )
        }
        val stored = try {
            CaptureStore.put(ctx.appContext, jpeg, originalName = "gopro.jpg")
        } catch (t: Throwable) {
            return@withContext SkillResult.error(
                t.message ?: "拍照失败：无法写入本机 inbox。",
            )
        }
        Log.i(TAG, "camera.capture ok capture_id=${stored.captureId}")
        SkillResult.ok(
            message = "camera.capture ok capture_id=${stored.captureId} (android, inbox, no asset)",
            outputs = mapOf(
                "capture_ref" to stored.jsonString(),
            ),
        )
    }

    companion object {
        const val SKILL_ID = "gopro.camera"
        private const val TAG = "GoProCameraSkill"
    }
}
