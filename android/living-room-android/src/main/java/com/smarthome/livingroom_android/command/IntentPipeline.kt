package com.smarthome.livingroom_android.command

import android.util.Log
import com.smarthome.livingroom_android.command.runtime.LocalEdgeRuntime
import com.smarthome.livingroom_android.intent.IntentJourneyStore
import com.smarthome.livingroom_android.intent.IntentPhase
import org.json.JSONArray
import org.json.JSONObject

/**
 * Cross-edge intent pipeline (production protocol).
 * Tick order: IntentScheduler → IntentStepExecutor.
 */
class IntentPipeline(
    private val commandHandler: CommandHandler,
    private val intentStatusClient: IntentStatusClient,
    private val localRuntime: LocalEdgeRuntime,
    private val journeyStore: IntentJourneyStore? = null,
    private val onLog: (String) -> Unit = {},
) {
    private val scheduler = IntentScheduler(intentStatusClient, onLog)
    private val executor = IntentStepExecutor(
        commandHandler = commandHandler,
        intentStatusClient = intentStatusClient,
        localRuntime = localRuntime,
        journeyStore = journeyStore,
        onLog = onLog,
    )

    suspend fun handle(intents: List<JSONObject>, localEdgeId: String) {
        val eid = localEdgeId.trim()
        if (eid.isEmpty() || intents.isEmpty()) return
        for ((idx, intent) in intents.withIndex()) {
            val iid = stringValue(intent.opt("id"))
                ?: stringValue(intent.opt("intent_id"))
                ?: "${idx + 1}"
            log("Intent[${idx + 1}/${intents.size}] $iid → scheduler")
            scheduler.handle(intent, eid)
            log("Intent[${idx + 1}/${intents.size}] $iid → step executor")
            executor.handle(intent, eid)
        }
        log("Intent pipeline done: ${intents.size} intent(s)")
    }

    private fun log(message: String) {
        Log.i(TAG, message)
        onLog(message)
    }

    companion object {
        private const val TAG = "IntentPipeline"
    }
}

/** Schedule hops when this edge has an assigned plan step. */
class IntentScheduler(
    private val intentStatusClient: IntentStatusClient,
    private val onLog: (String) -> Unit = {},
) {
    suspend fun handle(intent: JSONObject, localEdgeId: String) {
        val eid = localEdgeId.trim()
        if (eid.isEmpty()) return
        val iid = (
            stringValue(intent.opt("id"))
                ?: stringValue(intent.opt("intent_id"))
                ?: ""
            ).trim()
        val wireStatus = HttpCommandSource.intentWireStatus(intent)

        if (!HttpCommandSource.edgeHasAssignedStep(intent, eid)) {
            log("scheduler: skip intent ${iid.ifEmpty { "?" }} no assigned step for self=$eid")
            return
        }
        if (iid.isEmpty()) {
            log("scheduler: intent missing id")
            return
        }
        if (wireStatus == IntentStatusClient.SUCCEEDED || wireStatus == IntentStatusClient.FAILED) {
            log("scheduler: intent $iid already terminal (status=$wireStatus)")
            return
        }

        if (wireStatus == IntentStatusClient.INTENT_DISPATCHED ||
            wireStatus == IntentStatusClient.RUNNING
        ) {
            reconcileIntentStatusFromSteps(iid, intent, eid, wireStatus)
            return
        }

        if (wireStatus == IntentStatusClient.INTENT_SCHEDULED) {
            val ok2 = intentStatusClient.reportStatus(
                intentId = iid,
                status = IntentStatusClient.INTENT_DISPATCHED,
                edgeNodeId = eid,
                message = "scheduler $eid dispatched",
            )
            log(
                if (ok2) "scheduler: intent $iid → intent_dispatched"
                else "scheduler: intent $iid dispatch report failed",
            )
            return
        }

        // intent_parsed / intent_received / unknown → full schedule hops
        val ok1 = intentStatusClient.reportStatus(
            intentId = iid,
            status = IntentStatusClient.INTENT_SCHEDULED,
            edgeNodeId = eid,
            message = "scheduler $eid scheduled",
        )
        val ok2 = intentStatusClient.reportStatus(
            intentId = iid,
            status = IntentStatusClient.INTENT_DISPATCHED,
            edgeNodeId = eid,
            message = "scheduler $eid dispatched",
        )
        if (ok1 && ok2) {
            log("scheduler: intent $iid intent_scheduled → intent_dispatched")
        } else {
            log("scheduler: intent $iid status report incomplete ok1=$ok1 ok2=$ok2")
        }
    }

    private suspend fun reconcileIntentStatusFromSteps(
        intentId: String,
        intent: JSONObject,
        edgeNodeId: String,
        wireStatus: String,
    ) {
        val plan = IntentStepExecutor.normalizePlan(intent.opt("execution_plan"))
        if (plan.isEmpty()) {
            log("scheduler: intent $intentId dispatched — no plan to reconcile")
            return
        }
        val statuses = plan.map { IntentStepExecutor.stepStatus(it) }
        if (statuses.contains(IntentStatusClient.STEP_FAILED)) {
            val ok = intentStatusClient.reportStatus(
                intentId, IntentStatusClient.FAILED, edgeNodeId, "scheduler: step failed",
            )
            log("scheduler: intent $intentId → failed from steps reportOk=$ok")
            return
        }
        if (statuses.isNotEmpty() && statuses.all { it == IntentStatusClient.STEP_SUCCEEDED }) {
            val ok = intentStatusClient.reportStatus(
                intentId, IntentStatusClient.SUCCEEDED, edgeNodeId, "scheduler: all steps succeeded",
            )
            log("scheduler: intent $intentId → succeeded from steps reportOk=$ok")
            return
        }
        if (statuses.contains(IntentStatusClient.STEP_RUNNING) &&
            wireStatus != IntentStatusClient.RUNNING
        ) {
            val ok = intentStatusClient.reportStatus(
                intentId, IntentStatusClient.RUNNING, edgeNodeId, "scheduler: step running",
            )
            log("scheduler: intent $intentId → running from steps reportOk=$ok")
            return
        }
        log("scheduler: intent $intentId already dispatched (status=$wireStatus) — executor may run")
    }

    private fun log(message: String) {
        Log.i(TAG, message)
        onLog(message)
    }

    companion object {
        private const val TAG = "IntentScheduler"
    }
}

/**
 * Locally assigned waiting steps: step_status 1 → run → 2/3 → requeue with ctx_param.
 */
class IntentStepExecutor(
    private val commandHandler: CommandHandler,
    private val intentStatusClient: IntentStatusClient,
    private val localRuntime: LocalEdgeRuntime,
    private val journeyStore: IntentJourneyStore? = null,
    private val onLog: (String) -> Unit = {},
) {
    private val finishedLocalSteps = mutableMapOf<String, Int>()

    suspend fun handle(intent: JSONObject, localEdgeId: String) {
        val eid = localEdgeId.trim()
        val iid = (
            stringValue(intent.opt("id"))
                ?: stringValue(intent.opt("intent_id"))
                ?: ""
            ).trim()
        if (eid.isEmpty() || iid.isEmpty()) {
            log("executor: skip — empty edgeId/intentId edge=$eid intent=$iid")
            return
        }

        val wireStatus = HttpCommandSource.intentWireStatus(intent)
        if (wireStatus == "intent_parsed" || wireStatus == "intent_received") {
            clearFinished(iid)
            TimingBeats.clearIntent(iid)
            log("executor: intent $iid $wireStatus — cleared local finished-step cache")
        }

        var plan = normalizePlan(intent.opt("execution_plan"))
        if (plan.isEmpty()) {
            log("executor: intent $iid no plan")
            return
        }
        for (step in plan) {
            val n = intValue(step.opt("step")) ?: 0
            if (n > 0 && stepStatus(step) == IntentStatusClient.STEP_WAITING) {
                finishedLocalSteps.remove(stepKey(iid, n))
            }
        }
        applyLocalFinishedOverlay(iid, plan)

        log("executor: intent $iid self=$eid planSteps=${plan.size} ${planSummary(plan)}")

        advanceSkippedBeats(plan, iid, eid)
        if (findNextEligibleLocalStep(plan, eid, intentId = iid) == null) {
            log("executor: intent $iid no eligible local step — ${explainIneligible(plan, eid, intentId = iid)}")
            annotateWaitingRemoteSteps(plan, eid)
            return
        }

        while (true) {
            advanceSkippedBeats(plan, iid, eid)
            val step = findNextEligibleLocalStep(plan, eid, intentId = iid) ?: break
            val stepNum = intValue(step.opt("step")) ?: 0
            val cap = stringValue(step.opt("capability")) ?: "?"
            val timing = ExecutionTimingGate.parseExecutionTiming(step)
            if (stepNum <= 0) {
                log("executor: intent $iid invalid step number in $cap")
                break
            }

            log("executor: intent $iid claim step $stepNum ($cap) → POST step_status=1")
            val reportedRunning = intentStatusClient.reportStepStatus(
                intentId = iid,
                stepId = stepNum,
                stepStatus = IntentStatusClient.STEP_RUNNING,
                edgeNodeId = eid,
            )
            if (!reportedRunning) {
                log("executor: intent $iid step $stepNum POST step_status=1 FAILED")
                break
            }
            setStatus(plan, stepNum, IntentStatusClient.STEP_RUNNING)
            intentStatusClient.reportStatus(
                iid, IntentStatusClient.RUNNING, eid, "executing $cap",
            )
            journeyStore?.upsert(iid, phase = IntentPhase.RUNNING, text = journeyStore.active?.text.orEmpty())
            journeyStore?.updatePlanStep(cap, "running", "执行中…")

            val loaded = brainCtxParam(intent)
            if (loaded.isNotEmpty()) {
                localRuntime.loadContext(iid, loaded)
            }
            val command = HttpCommandSource.makeCommand(intent, step, eid, plan.size)
            log("executor: intent $iid execute step $stepNum ($cap)")
            val results = commandHandler.handle(listOf(command))
            val ok = results.isNotEmpty() && results.all { it.ok && !it.skipped }
            val final = if (ok) IntentStatusClient.STEP_SUCCEEDED else IntentStatusClient.STEP_FAILED
            val failDetail = results.mapNotNull { it.message }.firstOrNull { it.isNotBlank() }
            val stepOutputs = linkedMapOf<String, String>()
            for (r in results) {
                for ((k, v) in r.outputs) {
                    if (v.isNotBlank()) stepOutputs[k] = v
                }
            }
            val localDetail = when {
                !failDetail.isNullOrBlank() -> failDetail
                ok && !stepOutputs["photo_url"].isNullOrBlank() -> "完成 · ${stepOutputs["photo_url"]}"
                ok -> "完成"
                else -> null
            }
            journeyStore?.updatePlanStep(
                cap,
                if (ok) "succeeded" else "failed",
                localDetail.orEmpty(),
            )
            setStatus(plan, stepNum, final)
            finishedLocalSteps[stepKey(iid, stepNum)] = final
            if (ok) annotateWaitingRemoteSteps(plan, eid)

            val reportedFinal = intentStatusClient.reportStepStatus(
                intentId = iid,
                stepId = stepNum,
                stepStatus = final,
                edgeNodeId = eid,
                outputs = stepOutputs.takeIf { it.isNotEmpty() },
                msg = if (ok) null else (failDetail ?: "step $stepNum failed"),
            )
            if (ok && stepOutputs.isNotEmpty()) {
                // Cross-edge: also publish on intent so pull exposes ctx_param promptly.
                intentStatusClient.reportStatus(
                    intentId = iid,
                    status = IntentStatusClient.RUNNING,
                    edgeNodeId = eid,
                    message = "ctx_param publish step $stepNum",
                    outputs = stepOutputs,
                    ctxParam = stepOutputs,
                )
                val ctxKeys = localRuntime.contextSnapshot(iid).keys.sorted()
                log(
                    "executor: intent $iid step $stepNum contextKeys=$ctxKeys " +
                        "outputs→Brain=${stepOutputs.keys.sorted()}",
                )
            }
            if (ok) {
                val hasPendingRemote = plan.any { row ->
                    val n = intValue(row.opt("step")) ?: 0
                    if (n == stepNum) return@any false
                    val assigned = stringValue(row.opt("assigned_edge_id"))?.trim().orEmpty()
                    val st = stepStatus(row)
                    assigned.isNotEmpty() && assigned != eid &&
                        (st == IntentStatusClient.STEP_WAITING || st == IntentStatusClient.STEP_RUNNING)
                }
                if (hasPendingRemote) {
                    val ctx = localRuntime.contextSnapshot(iid)
                    val requeued = intentStatusClient.requeueIntentForPull(
                        intentId = iid,
                        status = IntentStatusClient.RUNNING,
                        executionPlan = planToJsonArray(plan),
                        ctxParam = ctx.takeIf { it.isNotEmpty() } ?: stepOutputs.takeIf { it.isNotEmpty() },
                    )
                    log("executor: intent $iid requeueForPull=$requeued")
                }
            }
            log(
                "executor: intent $iid step $stepNum done status=$final " +
                    "execOk=$ok reportOk=$reportedFinal",
            )

            if (!ok) {
                intentStatusClient.reportStatus(
                    iid, IntentStatusClient.FAILED, eid, failDetail ?: "step $stepNum failed",
                )
                journeyStore?.upsert(
                    iid,
                    phase = IntentPhase.FAILED,
                    text = journeyStore.active?.text.orEmpty(),
                )
                break
            }
            if (!reportedFinal) {
                log("executor: intent $iid step $stepNum terminal report failed — not retrying locally")
                break
            }

            // Recurring: re-arm waiting + advance beat; do not treat as intent-complete yet.
            if (timing.isRecurring) {
                TimingBeats.advanceBeat(iid, stepNum)
                finishedLocalSteps.remove(stepKey(iid, stepNum))
                val rearmed = intentStatusClient.reportStepStatus(
                    intentId = iid,
                    stepId = stepNum,
                    stepStatus = IntentStatusClient.STEP_WAITING,
                    edgeNodeId = eid,
                )
                setStatus(plan, stepNum, IntentStatusClient.STEP_WAITING)
                log(
                    "executor: intent $iid step $stepNum recurring re-arm waiting " +
                        "reportOk=$rearmed beat=${TimingBeats.getBeat(iid, stepNum)}",
                )
                // One beat per tick to avoid tight loops.
                break
            }

            if (allStepsSucceeded(plan)) {
                intentStatusClient.reportStatus(
                    iid, IntentStatusClient.SUCCEEDED, eid, "all steps succeeded",
                )
                journeyStore?.upsert(
                    iid,
                    phase = IntentPhase.SUCCEEDED,
                    text = journeyStore.active?.text.orEmpty(),
                )
            }
        }
    }

    /** Skip interval/cron beats past the miss window (and expire one-shot delay). */
    private fun advanceSkippedBeats(plan: MutableList<JSONObject>, intentId: String, edgeId: String) {
        val now = BrainTimeSync.nowMs()
        val eid = edgeId.trim()
        for (step in plan) {
            val assigned = stringValue(step.opt("assigned_edge_id"))?.trim().orEmpty()
            if (assigned != eid) continue
            if (stepStatus(step) != IntentStatusClient.STEP_WAITING) continue
            val timing = ExecutionTimingGate.parseExecutionTiming(step)
            val n = intValue(step.opt("step")) ?: 0
            if (!timing.isRecurring) {
                if (timing.mode == ExecutionTimingGate.MODE_DELAY) {
                    val gate = ExecutionTimingGate.timingGate(timing, now, 0)
                    if (gate.terminal) {
                        log(
                            "executor: intent $intentId step $n: ${gate.reason} — mark failed (no catch-up)",
                        )
                        step.put("status", IntentStatusClient.STEP_FAILED)
                        step.put("step_status", IntentStatusClient.STEP_FAILED)
                        if (n > 0) finishedLocalSteps[stepKey(intentId, n)] = IntentStatusClient.STEP_FAILED
                    }
                }
                continue
            }
            if (n <= 0) continue
            skipLoop@ for (_i in 0 until 64) {
                val beat = TimingBeats.getBeat(intentId, n)
                val gate = ExecutionTimingGate.timingGate(timing, now, beat)
                if (gate.terminal) {
                    step.put("status", IntentStatusClient.STEP_SUCCEEDED)
                    step.put("step_status", IntentStatusClient.STEP_SUCCEEDED)
                    finishedLocalSteps[stepKey(intentId, n)] = IntentStatusClient.STEP_SUCCEEDED
                    log(
                        "executor: intent $intentId step $n: recurring series done (${gate.reason})",
                    )
                    break@skipLoop
                }
                if (gate.skipBeat) {
                    log(
                        "executor: intent $intentId step $n: skip beat $beat (${gate.reason})",
                    )
                    TimingBeats.advanceBeat(intentId, n)
                    continue@skipLoop
                }
                break@skipLoop
            }
        }
    }

    private fun annotateWaitingRemoteSteps(plan: List<JSONObject>, selfEdgeId: String) {
        val store = journeyStore ?: return
        val eid = selfEdgeId.trim()
        for (row in plan) {
            val n = intValue(row.opt("step")) ?: 0
            val cap = stringValue(row.opt("capability"))?.trim().orEmpty()
            if (n <= 0 || cap.isEmpty()) continue
            val st = stepStatus(row)
            if (st == IntentStatusClient.STEP_SUCCEEDED || st == IntentStatusClient.STEP_FAILED) continue
            val assigned = stringValue(row.opt("assigned_edge_id"))?.trim().orEmpty()
            when {
                assigned.isNotEmpty() && assigned != eid -> {
                    val detail = when {
                        st == IntentStatusClient.STEP_WAITING &&
                            !predecessorsAllSucceeded(plan, n) ->
                            "等待前置 step 完成后再由 $assigned 执行"
                        st == IntentStatusClient.STEP_RUNNING ->
                            "远端执行中：$assigned"
                        else ->
                            "排队：等待 $assigned 领取执行"
                    }
                    store.updatePlanStep(
                        cap,
                        if (st == IntentStatusClient.STEP_RUNNING) "running" else "queued",
                        detail,
                    )
                }
                assigned == eid && st == IntentStatusClient.STEP_WAITING &&
                    !predecessorsAllSucceeded(plan, n) -> {
                    store.updatePlanStep(cap, "queued", "等待前置 step 完成")
                }
            }
        }
    }

    private fun clearFinished(intentId: String) {
        val prefix = "$intentId:"
        finishedLocalSteps.keys.filter { it.startsWith(prefix) }.forEach { finishedLocalSteps.remove(it) }
    }

    private fun applyLocalFinishedOverlay(intentId: String, plan: MutableList<JSONObject>) {
        for (i in plan.indices) {
            val n = intValue(plan[i].opt("step")) ?: 0
            if (n <= 0) continue
            val st = finishedLocalSteps[stepKey(intentId, n)] ?: continue
            plan[i].put("status", st)
            plan[i].put("step_status", st)
        }
    }

    private fun setStatus(plan: MutableList<JSONObject>, step: Int, status: Int) {
        for (row in plan) {
            if (intValue(row.opt("step")) == step) {
                row.put("status", status)
                row.put("step_status", status)
            }
        }
    }

    private fun log(message: String) {
        Log.i(TAG, message)
        onLog(message)
    }

    companion object {
        private const val TAG = "IntentStepExecutor"

        fun normalizePlan(raw: Any?): MutableList<JSONObject> {
            val arr = when (raw) {
                is JSONArray -> raw
                else -> return mutableListOf()
            }
            val out = mutableListOf<JSONObject>()
            for (i in 0 until arr.length()) {
                val dict = arr.optJSONObject(i) ?: continue
                dict.remove("delay_sec")
                dict.remove("delaySec")
                val et = dict.optJSONObject("execution_timing")
                if (et != null) {
                    ExecutionTimingGate.normalizeExecutionTimingObject(et)
                }
                if (!dict.has("status") && dict.has("step_status")) {
                    dict.put("status", dict.opt("step_status"))
                }
                if (!dict.has("status")) {
                    dict.put("status", IntentStatusClient.STEP_WAITING)
                }
                out += dict
            }
            return out
        }

        fun stepStatus(step: JSONObject): Int {
            val raw = step.opt("status") ?: step.opt("step_status")
            return when (raw) {
                is Number -> raw.toInt()
                is String -> raw.toIntOrNull() ?: IntentStatusClient.STEP_WAITING
                else -> IntentStatusClient.STEP_WAITING
            }
        }

        fun findNextEligibleLocalStep(
            plan: List<JSONObject>,
            edgeId: String,
            intentId: String = "",
        ): JSONObject? {
            val eid = edgeId.trim()
            val now = BrainTimeSync.nowMs()
            val ordered = plan.sortedBy { intValue(it.opt("step")) ?: 0 }
            for (step in ordered) {
                val assigned = stringValue(step.opt("assigned_edge_id"))?.trim().orEmpty()
                if (assigned != eid) continue
                val n = intValue(step.opt("step")) ?: 0
                if (stepStatus(step) != IntentStatusClient.STEP_WAITING) continue
                if (!predecessorsAllSucceeded(ordered, n)) continue
                val timing = ExecutionTimingGate.parseExecutionTiming(step)
                val beat = if (intentId.isNotEmpty()) TimingBeats.getBeat(intentId, n) else 0
                val gate = ExecutionTimingGate.timingGate(timing, now, beat)
                if (gate.due) return step
            }
            return null
        }

        fun explainIneligible(
            plan: List<JSONObject>,
            edgeId: String,
            intentId: String = "",
        ): String {
            val eid = edgeId.trim()
            val now = BrainTimeSync.nowMs()
            val ordered = plan.sortedBy { intValue(it.opt("step")) ?: 0 }
            return ordered.joinToString(" | ") { step ->
                val n = intValue(step.opt("step")) ?: 0
                val cap = stringValue(step.opt("capability")) ?: "?"
                val assigned = stringValue(step.opt("assigned_edge_id"))?.trim().orEmpty()
                val st = stepStatus(step)
                when {
                    assigned != eid ->
                        "step$n($cap): assigned=${assigned.ifEmpty { "<empty>" }} ≠ self=$eid"
                    st != IntentStatusClient.STEP_WAITING ->
                        "step$n($cap): status=$st (need 0=waiting)"
                    !predecessorsAllSucceeded(ordered, n) ->
                        "step$n($cap): waiting for predecessors"
                    else -> {
                        val timing = ExecutionTimingGate.parseExecutionTiming(step)
                        val beat = if (intentId.isNotEmpty()) TimingBeats.getBeat(intentId, n) else 0
                        val gate = ExecutionTimingGate.timingGate(timing, now, beat)
                        if (!gate.due) {
                            "step$n($cap): timing ${gate.reason}"
                        } else {
                            "step$n($cap): eligible"
                        }
                    }
                }
            }
        }

        /** Production pull/detail exposes shared bag as `ctx_param` only. */
        fun brainCtxParam(intent: JSONObject): Map<String, String> {
            val bag = intent.optJSONObject("ctx_param") ?: return emptyMap()
            val loaded = linkedMapOf<String, String>()
            val keys = bag.keys()
            while (keys.hasNext()) {
                val k = keys.next()
                val v = bag.opt(k)
                val s = when (v) {
                    null, JSONObject.NULL -> null
                    is String -> v
                    is Number, is Boolean -> v.toString()
                    else -> null
                }?.trim().orEmpty()
                if (s.isNotEmpty()) loaded[k] = s
            }
            return loaded
        }

        private fun predecessorsAllSucceeded(plan: List<JSONObject>, stepNum: Int): Boolean {
            for (step in plan) {
                val n = intValue(step.opt("step")) ?: 0
                if (n >= stepNum) continue
                if (stepStatus(step) != IntentStatusClient.STEP_SUCCEEDED) return false
            }
            return true
        }

        private fun allStepsSucceeded(plan: List<JSONObject>): Boolean {
            if (plan.isEmpty()) return false
            for (s in plan) {
                val timing = ExecutionTimingGate.parseExecutionTiming(s)
                if (timing.isRecurring && stepStatus(s) == IntentStatusClient.STEP_WAITING) {
                    return false
                }
                if (stepStatus(s) != IntentStatusClient.STEP_SUCCEEDED) return false
            }
            return true
        }

        private fun planSummary(plan: List<JSONObject>): String =
            plan.joinToString(" ") { step ->
                val n = intValue(step.opt("step")) ?: 0
                val cap = stringValue(step.opt("capability")) ?: "?"
                val a = stringValue(step.opt("assigned_edge_id")) ?: "-"
                "[$n $cap @$a status=${stepStatus(step)}]"
            }

        private fun planToJsonArray(plan: List<JSONObject>): JSONArray {
            val arr = JSONArray()
            for (row in plan) arr.put(row)
            return arr
        }

        private fun stepKey(intentId: String, step: Int) = "$intentId:$step"

        private fun stringValue(any: Any?): String? = HttpCommandSource.stringValue(any)

        private fun intValue(any: Any?): Int? =
            when (any) {
                null, JSONObject.NULL -> null
                is Number -> any.toInt()
                is String -> any.toIntOrNull()
                else -> null
            }
    }
}

private fun stringValue(any: Any?): String? = HttpCommandSource.stringValue(any)
