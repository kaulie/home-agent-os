package com.smarthome.livingroom_android.skill

import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.intent.IntentApi
import com.smarthome.livingroom_android.scan.ScanCapture

/** Runtime + local-input `document.scan`: system scanner → assets/upload. */
class DocumentScanSkill(
    private val intentUrl: () -> String,
    private val participantId: () -> String,
    private val api: IntentApi,
) : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.1.0",
        displayName = "Document Scanner",
        group = "document",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.DOCUMENT_SCAN,
                kind = "input",
                role = "纸质文档扫描器",
                plannerRecognize = "用手机系统文档扫描拍纸质（小票、文件、作业），直接上传成 Image Asset。只负责扫进系统，不读字、不算金额、不总结、不投屏。读字要另排 OCR",
                typicalTriggers = listOf("扫描一下", "扫一下", "扫描一下这个小票", "扫一下文档", "扫一下作业"),
                doNotDispatch = listOf("OCR", "金额识别", "看图理解", "投屏", "开灯"),
                inputSchema = mapOf(
                    "mode" to SchemaField(
                        type = "string",
                        required = false,
                        description = "默认 document",
                    ),
                ),
                outputSchema = mapOf(
                    "status" to SchemaField(
                        type = "string",
                        required = true,
                        description = "completed 或 cancelled",
                    ),
                    "asset_ref" to SchemaField(
                        type = "string",
                        required = true,
                        description = "Image AssetRef JSON。禁止 photo_url。",
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
        if (!ScanCapture.isHostAttached()) {
            return SkillResult.error("扫描失败：请先打开 HomeAgent Console 再扫。")
        }
        return SkillResult.ok("available")
    }

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult {
        val jpeg = try {
            ScanCapture.captureJpeg()
        } catch (c: ScanCapture.Cancelled) {
            return SkillResult.error("扫描已取消")
        } catch (t: Throwable) {
            return SkillResult.error(t.message ?: "扫描失败")
        }
        val intentId = params["intent_id"]?.toString()?.trim()?.takeIf { it.isNotEmpty() }
        val uploaded = try {
            api.uploadAsset(
                intentUrl = intentUrl(),
                jpeg = jpeg,
                uploadIntent = Capabilities.DOCUMENT_SCAN,
                participantId = participantId(),
                intentId = intentId,
                fileName = "scan_${System.currentTimeMillis()}.jpg",
                failVerb = "扫描",
            )
        } catch (t: Throwable) {
            return SkillResult.error(t.message ?: "扫描上传失败")
        }
        return SkillResult.ok(
            message = "document.scan ok asset_id=${uploaded.assetId}",
            outputs = mapOf(
                "status" to "completed",
                "asset_ref" to uploaded.assetRefJson,
                "asset_id" to uploaded.assetId,
            ),
        )
    }

    companion object {
        const val SKILL_ID = "document.scanner"
    }
}
