package com.smarthome.livingroom_v2.command.runtime

import android.content.Context
import android.util.Log
import com.smarthome.livingroom_v2.brain.BrainClient
import com.smarthome.livingroom_v2.brain.dto.ExecutionReport
import com.smarthome.livingroom_v2.brain.dto.StepStatus
import com.smarthome.livingroom_v2.command.IntentStatusClient
import com.smarthome.livingroom_v2.command.Task
import com.smarthome.livingroom_v2.edge.SkillRegistry
import com.smarthome.livingroom_v2.skill.SkillContext
import com.smarthome.livingroom_v2.skill.SkillResult

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
 * `step_status_api=1` (always set for server plan steps with execution_timing).
 */
class LocalEdgeRuntime(
    private val appContext: Context,
    private var edgeId: String,
    private val registry: SkillRegistry,
    private val brain: BrainClient,
    private val intentStatusClient: IntentStatusClient? = null,
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
            report(task, StepStatus.SKIPPED, msg)
            return TaskExecutionResult(task.taskId, ok = false, message = msg, skipped = true)
        }

        val skillId = task.skillId
        if (skillId.isNullOrBlank()) {
            val msg = "no skill mapped"
            report(task, StepStatus.SKIPPED, msg)
            return TaskExecutionResult(task.taskId, ok = false, message = msg, skipped = true)
        }

        if (jobId != null && !stepStatusOnly) {
            reportIntentJob(jobId, IntentStatusClient.RUNNING, node.nodeId, "executing $capability")
        }

        val skill = registry.get(skillId)
        val ctxKey = jobId ?: task.commandId
        val runtimeCtx = contexts.getOrPut(ctxKey) { RuntimeContext() }
        val result: SkillResult = if (skill == null) {
            SkillResult.error("skill not registered: $skillId")
        } else {
            val ctx = SkillContext(
                appContext = appContext,
                edgeId = edgeId,
                planId = task.commandId,
                stepId = task.taskId,
            )
            try {
                val resolved = runtimeCtx.resolveParams(task.params)
                val avail = skill.isAvailable(capability, resolved, ctx)
                if (!avail.ok) {
                    SkillResult.error(avail.message ?: "$capability unavailable")
                } else {
                    skill.execute(capability, resolved, ctx)
                }
            } catch (t: Throwable) {
                Log.e(TAG, "skill threw skillId=$skillId capability=$capability", t)
                SkillResult.error(t.message ?: t.javaClass.simpleName)
            }
        }
        if (result.ok && result.outputs.isNotEmpty()) {
            runtimeCtx.publish(result.outputs)
        }
        if (jobId != null && !stepStatusOnly) {
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
