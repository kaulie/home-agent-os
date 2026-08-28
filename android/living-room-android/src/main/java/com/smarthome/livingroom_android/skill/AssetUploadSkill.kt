package com.smarthome.livingroom_android.skill

import android.util.Log
import com.smarthome.livingroom_android.brain.BrainEndpoint
import com.smarthome.livingroom_android.brain.dto.CapabilityDescriptor
import com.smarthome.livingroom_android.brain.dto.SchemaField
import com.smarthome.livingroom_android.brain.dto.ServiceDescriptor
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.intent.IntentApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

/**
 * `asset.upload`: this step's resolved params only (capture_ref / asset_ref + dest).
 * Inbox bytes come from CaptureStore; already-registered Assets from LocalCaptureAssets
 * or Brain. This plugin does not scan step_outputs.
 */
class AssetUploadSkill(
    private val intentUrl: () -> String,
    private val participantId: () -> String,
    private val api: IntentApi,
) : Skill {
    override fun service(): ServiceDescriptor = ServiceDescriptor(
        serviceId = SKILL_ID,
        version = "0.1.0",
        displayName = "Local Asset",
        group = "asset",
        capabilities = listOf(
            CapabilityDescriptor(
                capabilityId = Capabilities.ASSET_UPLOAD,
                kind = "action",
                role = "Asset 上传器",
                plannerRecognize = "不负责按快门。把本机 inbox 的 capture 或已有 Asset 传到家里图床/云端，产出可给后续步用的 asset_ref。拍完要给人看、给视觉问、投电视，必须另排本步，入参 \$capture_ref。已有 Asset 再传一份用 asset_ref",
                typicalTriggers = listOf(
                    "把这张图传到云上",
                    "传到家里图床",
                    "上传到图片服务器",
                    "把刚拍的照片传到图床",
                    "拍照后上传",
                ),
                doNotDispatch = listOf("拍照", "投屏", "看图理解", "Google Drive", "Dropbox"),
                inputSchema = mapOf(
                    "capture_ref" to SchemaField(
                        type = "string",
                        required = false,
                        description = "本机 inbox CaptureRef JSON {capture_id, type, mime_type}。拍照后上传常为 \$capture_ref。",
                    ),
                    "asset_ref" to SchemaField(
                        type = "string",
                        required = false,
                        description = "已登记 Asset 的 AssetRef JSON。禁止 photo_url / path。已有 Asset 再传一份时用。",
                    ),
                    "dest" to SchemaField(
                        type = "string",
                        required = false,
                        description = "img_server（默认）| cloud | gdrive | dropbox。gdrive/dropbox 本轮未实现。",
                    ),
                ),
                outputSchema = mapOf(
                    "asset_ref" to SchemaField(
                        type = "string",
                        required = true,
                        description = "上传后的 AssetRef JSON。禁止 photo_url。",
                    ),
                    "dest" to SchemaField(
                        type = "string",
                        required = true,
                        description = "img_server 或 cloud",
                    ),
                ),
            ),
        ),
    )

    override suspend fun execute(
        capabilityId: String,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): SkillResult = withContext(Dispatchers.IO) {
        val destRaw = (params["dest"] ?: params["upload_dest"] ?: "img_server").toString().trim()
        when (destRaw.lowercase()) {
            "gdrive", "dropbox" -> return@withContext SkillResult.error(
                "asset.upload 失败：dest=$destRaw 尚未实现。",
            )
        }
        val primary = intentUrl()
        val dest = BrainEndpoint.destLabel(primary)
        val uploadUrl = BrainEndpoint.apiUrl(primary, "assets/upload")
        Log.i(TAG, "asset.upload POST $uploadUrl dest=$dest destParam=$destRaw")
        var captureId = CaptureStore.parseCaptureId(params["capture_ref"])
        val assetId = parseAssetId(params["asset_ref"])
        if (captureId == null && assetId == null) {
            captureId = try {
                CaptureStore.uniquePending(ctx.appContext, dest)
            } catch (t: Throwable) {
                return@withContext SkillResult.error(
                    t.message ?: "asset.upload 失败：缺少 capture_ref 或 asset_ref。",
                )
            }
        }
        val jpeg: ByteArray
        val fileName: String
        if (captureId != null) {
            jpeg = try {
                CaptureStore.readBytes(ctx.appContext, captureId)
            } catch (t: Throwable) {
                return@withContext SkillResult.error(
                    t.message ?: "本机 inbox 没有 $captureId",
                )
            }
            fileName = "$captureId.jpg"
        } else {
            val aid = assetId
                ?: return@withContext SkillResult.error("asset.upload 失败：缺少 capture_ref 或 asset_ref。")
            val intentIdForLoad = params["intent_id"]?.toString()?.trim().orEmpty()
            jpeg = loadBytes(ctx, aid, intentIdForLoad)
                ?: return@withContext SkillResult.error(
                    "卡在上传（asset.upload）：无法从本机或 Brain 读取 asset $aid 的内容。",
                )
            fileName = "$aid.jpg"
        }
        val intentId = params["intent_id"]?.toString()?.trim().orEmpty()
        val pid = participantId()
        val uploaded = try {
            api.uploadAsset(
                intentUrl = primary,
                jpeg = jpeg,
                uploadIntent = Capabilities.ASSET_UPLOAD,
                participantId = pid,
                intentId = intentId.takeIf { it.isNotEmpty() },
                fileName = fileName,
                failVerb = "上传",
            )
        } catch (t: Throwable) {
            return@withContext SkillResult.error(t.message ?: "asset.upload 失败。")
        }
        if (captureId != null) {
            CaptureStore.markUploaded(ctx.appContext, captureId, dest)
        }
        Log.i(TAG, "asset.upload ok dest=$dest asset_id=${uploaded.assetId}")
        SkillResult.ok(
            message = "asset.upload dest=$dest\nasset_id: ${uploaded.assetId}",
            outputs = mapOf(
                "asset_ref" to uploaded.assetRefJson,
                "dest" to dest,
            ),
        )
    }

    private suspend fun loadBytes(
        ctx: SkillContext,
        assetId: String,
        intentId: String,
    ): ByteArray? {
        LocalCaptureAssets.bytes(assetId)?.let { return it }
        val pid = participantId()
        val path = runCatching {
            api.fetchAssetLocalPath(
                intentUrl = intentUrl(),
                assetId = assetId,
                intentId = intentId,
                participantId = pid,
            )
        }.getOrNull()
        if (!path.isNullOrBlank()) {
            val f = File(path)
            if (f.isFile && f.length() > 0) {
                return runCatching { f.readBytes() }.getOrNull()
            }
        }
        if (intentId.isBlank()) return null
        return api.fetchAssetBytes(
            intentUrl = intentUrl(),
            assetId = assetId,
            intentId = intentId,
            representation = "original",
        )
    }

    private fun parseAssetId(raw: Any?): String? {
        when (raw) {
            null -> return null
            is Map<*, *> -> {
                val aid = raw["asset_id"]?.toString()?.trim().orEmpty()
                return aid.takeIf { it.isNotEmpty() && !it.startsWith("$") }
            }
            else -> {
                val text = raw.toString().trim()
                if (text.isEmpty() || text.startsWith("$")) return null
                if (text.startsWith("{")) {
                    val obj = runCatching { JSONObject(text) }.getOrNull()
                    val aid = obj?.optString("asset_id").orEmpty().trim()
                    return aid.takeIf { it.isNotEmpty() }
                }
                return text
            }
        }
    }

    companion object {
        const val SKILL_ID = "local.asset"
        private const val TAG = "AssetUploadSkill"
    }
}
