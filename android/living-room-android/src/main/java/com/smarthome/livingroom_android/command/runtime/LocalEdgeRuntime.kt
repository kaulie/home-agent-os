package com.smarthome.livingroom_android.command.runtime

import android.content.Context
import android.util.Log
import com.smarthome.livingroom_android.brain.BrainClient
import com.smarthome.livingroom_android.brain.dto.ExecutionReport
import com.smarthome.livingroom_android.brain.dto.StepStatus
import com.smarthome.livingroom_android.capability.Capabilities
import com.smarthome.livingroom_android.command.IntentStatusClient
import com.smarthome.livingroom_android.command.Task
import com.smarthome.livingroom_android.edge.IntentRuntimeLog
import com.smarthome.livingroom_android.edge.SkillRegistry
import com.smarthome.livingroom_android.intent.IntentPhase
import com.smarthome.livingroom_android.skill.AndroidCameraSkill
import com.smarthome.livingroom_android.skill.AssetUploadSkill
import com.smarthome.livingroom_android.skill.GoProCameraSkill
import com.smarthome.livingroom_android.skill.Skill
import com.smarthome.livingroom_android.skill.SkillContext
import com.smarthome.livingroom_android.skill.SkillResult

data class EdgeRuntimeNode(
    val nodeId: String,
    val displayName: String = nodeId,
)

data class TaskExecutionResult(
    val taskId: String,
    val ok: Boolean,
    val message: String?,
    val skipped: Boolean = false,
    val outputs: Map<String, String> = emptyMap(),
)

interface EdgeRuntime {
    suspend fun execute(task: Task, node: EdgeRuntimeNode): TaskExecutionResult
}

/**
 * Local skill runtime. Whole-job / step_status are owned by IntentPipeline when
 * `step_status_api=1` (always set for server plan steps).
 */
class LocalEdgeRuntime(
    private val appContext: Context,
    private var edgeId: String,
    private val registry: SkillRegistry,
    private val brain: BrainClient,
    private val intentStatusClient: IntentStatusClient? = null,
    private val onIntentPhase: ((intentId: String, phase: IntentPhase, message: String) -> Unit)? = null,
    private val onPlanStep: ((capability: String, status: String, detail: String) -> Unit)? = null,
) : EdgeRuntime {
    private val contexts = mutableMapOf<String, RuntimeContext>()

    fun updateEdgeId(id: String) {
        edgeId = id
    }

    fun loadContext(intentId: String, values: Map<String, String>) {
        val iid = intentId.trim()
        if (iid.isEmpty() || values.isEmpty()) return
        contexts.getOrPut(iid) { RuntimeContext() }.load(values)
    }

    fun contextSnapshot(intentId: String): Map<String, String> {
        val iid = intentId.trim()
        if (iid.isEmpty()) return emptyMap()
        return contexts[iid]?.snapshot().orEmpty()
    }

    override suspend fun execute(task: Task, node: EdgeRuntimeNode): TaskExecutionResult {
        val jobId = IntentStatusClient.intentIdFromParams(task.params)
        val capability = task.params["capability"]?.toString()?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?: task.action
        val stepStatusOnly = task.params["step_status_api"]?.toString()?.trim() == "1"

        if (!task.skipReason.isNullOrBlank()) {
            val msg = "skipped: ${task.skipReason}"
            onPlanStep?.invoke(capability, "skipped", msg)
            report(task, StepStatus.SKIPPED, msg)
            return TaskExecutionResult(task.taskId, ok = false, message = msg, skipped = true)
        }

        if (capability == Capabilities.CAMERA_CAPTURE_AND_UPLOAD) {
            return executeCaptureAndUpload(task, node, jobId, stepStatusOnly)
        }

        val skillId = task.skillId
        if (skillId.isNullOrBlank() && capability != Capabilities.CAMERA_CAPTURE) {
            val msg = "no skill mapped"
            onPlanStep?.invoke(capability, "failed", msg)
            report(task, StepStatus.SKIPPED, msg)
            return TaskExecutionResult(task.taskId, ok = false, message = msg, skipped = true)
        }

        if (jobId != null && !stepStatusOnly) {
            onIntentPhase?.invoke(jobId, IntentPhase.RUNNING, "executing $capability")
            IntentRuntimeLog.append(jobId, "executing $capability")
            reportIntentJob(jobId, IntentStatusClient.RUNNING, node.nodeId, "executing $capability")
        }
        onPlanStep?.invoke(capability, "running", skillId ?: capability)

        val ctxKey = jobId ?: task.commandId
        val runtimeCtx = contexts.getOrPut(ctxKey) { RuntimeContext() }
        val ctx = SkillContext(
            appContext = appContext,
            edgeId = edgeId,
            planId = task.commandId,
            stepId = task.taskId,
        )
        val resolved = runtimeCtx.resolveParams(task.params)
        val result: SkillResult = try {
            if (capability == Capabilities.CAMERA_CAPTURE) {
                val picked = pickCaptureSkill(skillId, resolved, ctx)
                if (picked == null) {
                    SkillResult.error("skill not registered: ${skillId ?: "camera.capture"}")
                } else {
                    val avail = picked.isAvailable(Capabilities.CAMERA_CAPTURE, resolved, ctx)
                    if (!avail.ok) {
                        SkillResult.error(avail.message ?: "camera.capture unavailable")
                    } else {
                        picked.execute(Capabilities.CAMERA_CAPTURE, resolved, ctx)
                    }
                }
            } else {
                val skill = registry.get(skillId.orEmpty())
                if (skill == null) {
                    SkillResult.error("skill not registered: $skillId")
                } else {
                    val avail = skill.isAvailable(task.action, resolved, ctx)
                    if (!avail.ok) {
                        SkillResult.error(avail.message ?: "${task.action} unavailable")
                    } else {
                        skill.execute(task.action, resolved, ctx)
                    }
                }
            }
        } catch (t: Throwable) {
            Log.e(TAG, "skill threw", t)
            SkillResult.error(t.message ?: t.javaClass.simpleName)
        }
        if (result.ok && result.outputs.isNotEmpty()) {
            runtimeCtx.publish(result.outputs)
        }
        onPlanStep?.invoke(
            capability,
            if (result.ok) "succeeded" else "failed",
            result.message.orEmpty(),
        )
        if (jobId != null && !stepStatusOnly) {
            val phase = if (result.ok) IntentPhase.SUCCEEDED else IntentPhase.FAILED
            onIntentPhase?.invoke(jobId, phase, result.message ?: phase.wire)
            reportIntentJob(
                jobId,
                if (result.ok) IntentStatusClient.SUCCEEDED else IntentStatusClient.FAILED,
                node.nodeId,
                result.message ?: if (result.ok) "ok" else "failed",
                outputs = result.outputs.takeIf { it.isNotEmpty() },
            )
        }
        report(task, if (result.ok) StepStatus.OK else StepStatus.ERROR, result.message)
        return TaskExecutionResult(
            task.taskId,
            ok = result.ok,
            message = result.message,
            outputs = result.outputs,
        )
    }

    private suspend fun executeCaptureAndUpload(
        task: Task,
        node: EdgeRuntimeNode,
        jobId: String?,
        stepStatusOnly: Boolean,
    ): TaskExecutionResult {
        val capability = Capabilities.CAMERA_CAPTURE_AND_UPLOAD
        if (jobId != null && !stepStatusOnly) {
            onIntentPhase?.invoke(jobId, IntentPhase.RUNNING, "正在拍照（camera.capture）")
            reportIntentJob(jobId, IntentStatusClient.RUNNING, node.nodeId, "正在拍照（camera.capture）")
        }
        onPlanStep?.invoke(capability, "running", "camera.capture")
        val ctxKey = jobId ?: task.commandId
        val runtimeCtx = contexts.getOrPut(ctxKey) { RuntimeContext() }
        val ctx = SkillContext(
            appContext = appContext,
            edgeId = edgeId,
            planId = task.commandId,
            stepId = task.taskId,
        )
        val resolved = runtimeCtx.resolveParams(task.params)
        val captureSkill = pickCaptureSkill(task.skillId, resolved, ctx)
        val uploadSkill = registry.get(AssetUploadSkill.SKILL_ID)
        if (captureSkill == null || uploadSkill == null) {
            val msg = "camera.capture_and_upload 缺少本机 camera.capture 或 asset.upload"
            onPlanStep?.invoke(capability, "failed", msg)
            report(task, StepStatus.ERROR, msg)
            return TaskExecutionResult(task.taskId, ok = false, message = msg)
        }
        val captureAvail = captureSkill.isAvailable(Capabilities.CAMERA_CAPTURE, resolved, ctx)
        val capture: SkillResult = if (!captureAvail.ok) {
            SkillResult.error(captureAvail.message ?: "camera.capture unavailable")
        } else {
            try {
                captureSkill.execute(Capabilities.CAMERA_CAPTURE, resolved, ctx)
            } catch (t: Throwable) {
                SkillResult.error(t.message ?: t.javaClass.simpleName)
            }
        }
        if (!capture.ok) {
            onPlanStep?.invoke(capability, "failed", capture.message.orEmpty())
            if (jobId != null && !stepStatusOnly) {
                onIntentPhase?.invoke(jobId, IntentPhase.FAILED, capture.message ?: "failed")
                reportIntentJob(
                    jobId,
                    IntentStatusClient.FAILED,
                    node.nodeId,
                    capture.message ?: "failed",
                )
            }
            report(task, StepStatus.ERROR, capture.message)
            return TaskExecutionResult(task.taskId, ok = false, message = capture.message)
        }
        if (capture.outputs.isNotEmpty()) {
            runtimeCtx.publish(capture.outputs)
        }
        if (jobId != null && !stepStatusOnly) {
            onIntentPhase?.invoke(jobId, IntentPhase.RUNNING, "正在上传（asset.upload）")
            reportIntentJob(jobId, IntentStatusClient.RUNNING, node.nodeId, "正在上传（asset.upload）")
        }
        onPlanStep?.invoke(capability, "running", "asset.upload")
        val uploadParams = resolved.toMutableMap()
        if (uploadParams["capture_ref"] == null) {
            capture.outputs["capture_ref"]?.let { uploadParams["capture_ref"] = it }
        }
        val uploadAvail = uploadSkill.isAvailable(Capabilities.ASSET_UPLOAD, uploadParams, ctx)
        val upload: SkillResult = if (!uploadAvail.ok) {
            SkillResult.error(uploadAvail.message ?: "asset.upload unavailable")
        } else {
            try {
                uploadSkill.execute(Capabilities.ASSET_UPLOAD, uploadParams, ctx)
            } catch (t: Throwable) {
                SkillResult.error(t.message ?: t.javaClass.simpleName)
            }
        }
        if (!upload.ok) {
            val wrapped = wrapUploadFailure(upload.message)
            onPlanStep?.invoke(capability, "failed", wrapped)
            if (jobId != null && !stepStatusOnly) {
                onIntentPhase?.invoke(jobId, IntentPhase.FAILED, wrapped)
                reportIntentJob(jobId, IntentStatusClient.FAILED, node.nodeId, wrapped)
            }
            report(task, StepStatus.ERROR, wrapped)
            return TaskExecutionResult(task.taskId, ok = false, message = wrapped)
        }
        val out = linkedMapOf<String, String>()
        upload.outputs["asset_ref"]?.let { out["asset_ref"] = it }
        upload.outputs["dest"]?.let { out["dest"] = it }
        if (out.isNotEmpty()) {
            runtimeCtx.publish(out)
        }
        onPlanStep?.invoke(capability, "succeeded", upload.message.orEmpty())
        if (jobId != null && !stepStatusOnly) {
            onIntentPhase?.invoke(jobId, IntentPhase.SUCCEEDED, upload.message ?: "ok")
            reportIntentJob(
                jobId,
                IntentStatusClient.SUCCEEDED,
                node.nodeId,
                upload.message ?: "ok",
                outputs = out.takeIf { it.isNotEmpty() },
            )
        }
        report(task, StepStatus.OK, upload.message)
        return TaskExecutionResult(task.taskId, ok = true, message = upload.message, outputs = out)
    }

    /**
     * Prefer the native CameraX provider; keep GoPro as a fallback when the
     * Photo pane is not holding the camera (or native is otherwise unavailable).
     */
    private suspend fun pickCaptureSkill(
        preferredSkillId: String?,
        params: Map<String, Any?>,
        ctx: SkillContext,
    ): Skill? {
        val appliance = params["appliance"]?.toString()?.trim().orEmpty().lowercase()
        val preferGopro = "gopro" in appliance
        val order = listOfNotNull(
            preferredSkillId?.takeIf { it.isNotBlank() },
            if (preferGopro) GoProCameraSkill.SKILL_ID else AndroidCameraSkill.SKILL_ID,
            if (preferGopro) AndroidCameraSkill.SKILL_ID else GoProCameraSkill.SKILL_ID,
        ).distinct()
        var fallback: Skill? = null
        for (id in order) {
            val skill = registry.get(id) ?: continue
            if (fallback == null) fallback = skill
            val avail = runCatching {
                skill.isAvailable(Capabilities.CAMERA_CAPTURE, params, ctx)
            }.getOrNull()
            if (avail?.ok == true) return skill
        }
        return fallback
    }

    private fun wrapUploadFailure(raw: String?): String {
        val text = raw?.trim().orEmpty().ifEmpty { "上传失败" }
        if (text.startsWith("拍照成功")) return text
        return if ("上传" in text || text.lowercase().contains("upload")) {
            "拍照成功，照片已保存在本机；但$text"
        } else {
            "拍照成功，照片已保存在本机；但上传失败：$text"
        }
    }

    private suspend fun reportIntentJob(
        jobId: String,
        status: String,
        edgeNodeId: String,
        message: String,
        outputs: Map<String, String>? = null,
    ) {
        val client = intentStatusClient ?: return
        val ok = client.reportStatus(
            intentId = jobId,
            status = status,
            edgeNodeId = edgeNodeId,
            message = message,
            outputs = outputs,
            ctxParam = outputs,
        )
        if (!ok) Log.w(TAG, "intent status failed intent_id=$jobId status=$status")
    }

    private suspend fun report(task: Task, status: StepStatus, message: String?) {
        brain.report(
            ExecutionReport(
                planId = task.commandId,
                stepId = task.taskId,
                status = status,
                message = message,
            ),
        )
    }

    companion object {
        private const val TAG = "LocalEdgeRuntime"
    }
}
