package com.smarthome.livingroom_v2.edge

import android.content.Context
import android.util.Log
import com.smarthome.livingroom_v2.brain.BrainClient
import com.smarthome.livingroom_v2.brain.dto.ExecutionReport
import com.smarthome.livingroom_v2.brain.dto.OnFailurePolicy
import com.smarthome.livingroom_v2.brain.dto.Plan
import com.smarthome.livingroom_v2.brain.dto.StepStatus
import com.smarthome.livingroom_v2.skill.SkillContext
import com.smarthome.livingroom_v2.skill.SkillResult

class PlanExecutor(
    private val appContext: Context,
    var edgeId: String,
    private val registry: SkillRegistry,
    private val brain: BrainClient,
) {
    data class Outcome(
        val planId: String,
        val reports: List<ExecutionReport>,
        val aborted: Boolean,
    )

    suspend fun execute(plan: Plan): Outcome {
        val reports = mutableListOf<ExecutionReport>()
        var aborted = false
        for (step in plan.steps) {
            val skill = registry.get(step.skillId)
            val result: SkillResult
            if (skill == null) {
                result = SkillResult.error("skill not registered: ${step.skillId}")
            } else {
                val ctx = SkillContext(
                    appContext = appContext,
                    edgeId = edgeId,
                    planId = plan.planId,
                    stepId = step.stepId,
                )
                result = try {
                    skill.execute(step.action, step.params, ctx)
                } catch (t: Throwable) {
                    Log.e(TAG, "skill threw id=${step.skillId} capability=${step.action}", t)
                    SkillResult.error(t.message ?: t.javaClass.simpleName)
                }
            }

            val report = ExecutionReport(
                planId = plan.planId,
                stepId = step.stepId,
                status = if (result.ok) StepStatus.OK else StepStatus.ERROR,
                message = result.message,
            )
            reports += report
            brain.report(report)

            if (!result.ok && step.onFailure == OnFailurePolicy.ABORT) {
                aborted = true
                // Mark remaining steps skipped
                for (rest in plan.steps.dropWhile { it.stepId != step.stepId }.drop(1)) {
                    val skipped = ExecutionReport(
                        planId = plan.planId,
                        stepId = rest.stepId,
                        status = StepStatus.SKIPPED,
                        message = "aborted after failure of ${step.stepId}",
                    )
                    reports += skipped
                    brain.report(skipped)
                }
                break
            }
        }
        return Outcome(planId = plan.planId, reports = reports, aborted = aborted)
    }

    companion object {
        private const val TAG = "PlanExecutor"
    }
}
