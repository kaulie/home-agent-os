package com.smarthome.livingroom_android.skill

import android.util.Log
import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.camera.NativeCameraSession
import com.smarthome.livingroom_android.capability.Capabilities
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Native CameraX provider for `camera.capture`.
 * Requires the Console Photo pane to hold CameraX; does not open the system camera app.
 * Writes a local inbox capture_ref. Upload stays `asset.upload`.
 */
class AndroidCameraSkill : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.1.0",
        displayName = "Android Camera",
        group = "camera",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.CAMERA_CAPTURE,
                kind = "input",
                role = "拍照执行器",
                plannerRecognize = "用本机原生摄像头拍一张现场照（书桌、课本、眼前的东西），写入本机 inbox，产出 capture_ref（还不是 Asset）。允许当「给人看 / 问图上有什么 / 投电视」的前序步。本步不上传、不投屏、不能单步当最终图。下一步上传用 \$capture_ref。禁止把 path 写进 plan。禁止派系统相机 App 或模拟点击快门",
                typicalTriggers = listOf("拍一张", "看看现在", "拍照", "拍张照", "拍的照片", "拍一下"),
                doNotDispatch = listOf(
                    "上传",
                    "传到图床",
                    "传到云上",
                    "单步作为最终给用户看的图",
                    "放歌",
                    "无拍照直接回答画面内容",
                    "GoPro",
                    "打开系统相机",
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
                plannerRecognize = "用本机原生摄像头拍一张现场照并在同一台设备上上传成 Image Asset，产出 asset_ref。拍照后还要给人看、给视觉问、投电视时优先本步，不要再拆成拍照+上传两步（capture_ref 不能跨机）。本步不负责看图理解、不投屏",
                typicalTriggers = listOf(
                    "拍张照片我看一下",
                    "拍张照片我看看",
                    "拍的给我看",
                    "拍照后上传",
                    "把刚拍的照片传到图床",
                ),
                doNotDispatch = listOf("只上传已有图", "看图理解本身", "投屏本身", "不再拍照只传旧图", "GoPro"),
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
        val reason = NativeCameraSession.permissionReason(ctx.appContext)
        if (reason != null) return SkillResult.error(reason)
        return SkillResult.ok("available")
    }

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.Main.immediate) {
        val reason = NativeCameraSession.unavailableReason(ctx.appContext)
        if (reason != null) return@withContext SkillResult.error(reason)
        val jpeg = try {
            NativeCameraSession.captureJpeg()
        } catch (t: Throwable) {
            return@withContext SkillResult.error(t.message ?: "拍照失败")
        }
        val stored = try {
            withContext(Dispatchers.IO) {
                CaptureStore.put(ctx.appContext, jpeg, originalName = "android.jpg", source = "android")
            }
        } catch (t: Throwable) {
            return@withContext SkillResult.error(
                t.message ?: "拍照失败：无法写入本机 inbox。",
            )
        }
        NativeCameraSession.notifyRuntimeStored(stored.captureId, jpeg)
        Log.i(TAG, "camera.capture ok capture_id=${stored.captureId}")
        SkillResult.ok(
            message = "camera.capture ok capture_id=${stored.captureId} (android native, inbox, no asset)",
            outputs = mapOf(
                "capture_ref" to stored.jsonString(),
            ),
        )
    }

    companion object {
        const val SKILL_ID = "android.camera"
        private const val TAG = "AndroidCameraSkill"
    }
}
