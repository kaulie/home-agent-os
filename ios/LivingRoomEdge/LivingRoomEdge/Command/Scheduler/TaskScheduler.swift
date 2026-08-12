import Foundation

@MainActor
class TaskScheduler {
    struct Entry {
        let task: EdgeTask
        let onReady: (EdgeTask) -> Void
    }

    fileprivate(set) var registry: [String: Entry] = [:]
    var kind: String { "base" }

    func schedule(task: EdgeTask, onReady: @escaping (EdgeTask) -> Void) {
        registry[task.taskId] = Entry(task: task, onReady: onReady)
        NSLog("[TaskScheduler] schedule kind=%@ taskId=%@", kind, task.taskId)
        onScheduled(task: task, onReady: onReady)
    }

    @discardableResult
    func cancel(taskId: String) -> Bool {
        let removed = registry.removeValue(forKey: taskId) != nil
        if removed {
            NSLog("[TaskScheduler] cancel kind=%@ taskId=%@", kind, taskId)
        }
        return removed
    }

    func listScheduled() -> [EdgeTask] {
        registry.values.map(\.task)
    }

    @discardableResult
    func debugFire(taskId: String) -> Bool {
        guard let entry = removeEntry(taskId: taskId) else { return false }
        NSLog("[TaskScheduler] debugFire kind=%@ taskId=%@", kind, taskId)
        entry.onReady(entry.task)
        return true
    }

    @discardableResult
    fileprivate func removeEntry(taskId: String) -> Entry? {
        registry.removeValue(forKey: taskId)
    }

    func onScheduled(task: EdgeTask, onReady: @escaping (EdgeTask) -> Void) {
        // subclasses
    }
}

@MainActor
final class InstantScheduler: TaskScheduler {
    override var kind: String { "instant" }

    override func onScheduled(task: EdgeTask, onReady: @escaping (EdgeTask) -> Void) {
        _ = removeEntry(taskId: task.taskId)
        onReady(task)
    }
}

/// Runnable skeleton: registers cron tasks; no parser yet.
@MainActor
final class CronJobScheduler: TaskScheduler {
    override var kind: String { "cron" }

    override func onScheduled(task: EdgeTask, onReady: @escaping (EdgeTask) -> Void) {
        if case let .cron(expr) = task.schedule {
            NSLog("[CronJobScheduler] registered taskId=%@ expr=%@ (skeleton)", task.taskId, expr)
        }
    }
}

/// Runnable skeleton: registers event waits; no event bus yet.
@MainActor
final class EventTriggerScheduler: TaskScheduler {
    override var kind: String { "event" }

    override func onScheduled(task: EdgeTask, onReady: @escaping (EdgeTask) -> Void) {
        if case let .event(ev, _) = task.schedule {
            NSLog("[EventTriggerScheduler] registered taskId=%@ event=%@ (skeleton)", task.taskId, ev)
        }
    }
}

/// Brain intent-level scheduler: reports `intent_scheduled` → `intent_dispatched`
/// when this edge is `scheduler_node`. Does not execute capabilities or step status.
@MainActor
final class IntentScheduler {
    private let intentController: IntentController
    private var doneIntentIds: Set<String> = []
    var onLog: ((String) -> Void)?

    init(intentController: IntentController) {
        self.intentController = intentController
    }

    func handle(intent: [String: Any], localEdgeId: String) async {
        let eid = localEdgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !eid.isEmpty else { return }

        let scheduler = (stringValue(intent["scheduler_node"])
            ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let iid = (stringValue(intent["id"])
            ?? stringValue(intent["intent_id"])
            ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let wireStatus = (stringValue(intent["intent_status"])
            ?? stringValue(intent["status"])
            ?? "").lowercased()

        guard scheduler == eid else {
            log("scheduler: skip intent \(iid.isEmpty ? "?" : iid) scheduler_node=\(scheduler) != self=\(eid)")
            return
        }
        guard !iid.isEmpty else {
            log("scheduler: intent missing id")
            return
        }

        // Brain often reuses numeric intent_id after restart. Only trust wire status —
        // never skip scheduling just because we once handled the same id string.
        if wireStatus == IntentPhase.succeeded.wireValue
            || wireStatus == IntentPhase.failed.wireValue {
            log("scheduler: intent \(iid) already terminal (status=\(wireStatus))")
            return
        }

        let alreadyDispatched = wireStatus == IntentPhase.assigned.wireValue
            || wireStatus == IntentPhase.running.wireValue
        if alreadyDispatched {
            doneIntentIds.insert(iid)
            // Scheduler owns intent-level status from step outcomes (not Brain).
            await reconcileIntentStatusFromSteps(
                intentId: iid,
                intent: intent,
                edgeNodeId: eid,
                wireStatus: wireStatus
            )
            return
        }

        let alreadyScheduled = wireStatus == IntentPhase.scheduled.wireValue
        if alreadyScheduled {
            // Need only the second hop.
            let ok2 = await intentController.reportAndRefresh(
                intentId: iid,
                status: IntentPhase.assigned.wireValue,
                edgeNodeId: eid,
                message: "scheduler \(eid) dispatched"
            )
            if ok2 {
                doneIntentIds.insert(iid)
                log("scheduler: intent \(iid) → intent_dispatched (was \(wireStatus))")
            } else {
                log("scheduler: intent \(iid) dispatch report failed (was \(wireStatus))")
            }
            return
        }

        // intent_parsed (or unknown): always run full schedule, even if local cache
        // still remembers a previous intent that reused the same numeric id.
        if doneIntentIds.contains(iid) {
            doneIntentIds.remove(iid)
            log("scheduler: intent \(iid) status=\(wireStatus) — clearing stale local done cache")
        }

        let ok1 = await intentController.reportAndRefresh(
            intentId: iid,
            status: IntentPhase.scheduled.wireValue,
            edgeNodeId: eid,
            message: "scheduler \(eid) scheduled"
        )
        let ok2 = await intentController.reportAndRefresh(
            intentId: iid,
            status: IntentPhase.assigned.wireValue,
            edgeNodeId: eid,
            message: "scheduler \(eid) dispatched"
        )
        if ok1, ok2 {
            doneIntentIds.insert(iid)
            log("scheduler: intent \(iid) scheduled → dispatched")
        } else {
            // Keep out of doneIntentIds so intent_parsed can retry next tick.
            log("scheduler: intent \(iid) status report incomplete ok1=\(ok1) ok2=\(ok2)")
        }
    }

    /// When schedule hops are done, derive intent running/succeeded/failed from execution_plan steps.
    private func reconcileIntentStatusFromSteps(
        intentId: String,
        intent: [String: Any],
        edgeNodeId: String,
        wireStatus: String
    ) async {
        let plan = IntentStepExecutor.normalizePlan(intent["execution_plan"])
        guard !plan.isEmpty else {
            log("scheduler: intent \(intentId) dispatched — no plan to reconcile")
            return
        }
        let statuses = plan.map { IntentStepExecutor.stepStatus($0) }
        if statuses.contains(IntentStepExecutor.failed) {
            let ok = await intentController.reportAndRefresh(
                intentId: intentId,
                status: IntentPhase.failed.wireValue,
                edgeNodeId: edgeNodeId,
                message: "scheduler: step failed"
            )
            log("scheduler: intent \(intentId) → failed from steps reportOk=\(ok)")
            return
        }
        if !statuses.isEmpty, statuses.allSatisfy({ $0 == IntentStepExecutor.succeeded }) {
            let ok = await intentController.reportAndRefresh(
                intentId: intentId,
                status: IntentPhase.succeeded.wireValue,
                edgeNodeId: edgeNodeId,
                message: "scheduler: all steps succeeded"
            )
            log("scheduler: intent \(intentId) → succeeded from steps reportOk=\(ok)")
            return
        }
        if statuses.contains(IntentStepExecutor.running), wireStatus != "running" {
            let ok = await intentController.reportAndRefresh(
                intentId: intentId,
                status: IntentPhase.running.wireValue,
                edgeNodeId: edgeNodeId,
                message: "scheduler: step running"
            )
            log("scheduler: intent \(intentId) → running from steps reportOk=\(ok)")
            return
        }
        log("scheduler: intent \(intentId) already dispatched (status=\(wireStatus)) — executor may run")
    }

    private func log(_ message: String) {
        NSLog("[IntentScheduler] %@", message)
        onLog?(message)
    }

    private func stringValue(_ any: Any?) -> String? {
        guard let any else { return nil }
        if let s = any as? String { return s }
        if let n = any as? NSNumber { return n.stringValue }
        return String(describing: any)
    }
}

/// Executes locally assigned plan steps in a closed loop:
/// find eligible → report step_status=1 → run → report 2/3 → find next.
@MainActor
final class IntentStepExecutor {
    static let waiting = 0
    static let running = 1
    static let succeeded = 2
    static let failed = 3

    private let commandHandler: CommandHandler
    private let intentController: IntentController
    /// Prevents re-running a step when Brain still returns status=0 after a local finish
    /// (or after step_status=3 POST failed / was dropped).
    private var finishedLocalSteps: [String: Int] = [:]
    var onLog: ((String) -> Void)?

    init(commandHandler: CommandHandler, intentController: IntentController) {
        self.commandHandler = commandHandler
        self.intentController = intentController
    }

    func handle(intent: [String: Any], localEdgeId: String) async {
        let eid = localEdgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        let iid = (stringValue(intent["id"])
            ?? stringValue(intent["intent_id"])
            ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !eid.isEmpty, !iid.isEmpty else {
            log("executor: skip — empty edgeId/intentId edge=\(eid) intent=\(iid)")
            return
        }

        let wireStatus = (stringValue(intent["intent_status"])
            ?? stringValue(intent["status"])
            ?? "").lowercased()
        // New intent reused the same numeric id — allow a fresh run.
        if wireStatus == "intent_parsed" || wireStatus == "intent_received" {
            clearFinished(for: iid)
            log("executor: intent \(iid) \(wireStatus) — cleared local finished-step cache")
        }

        var plan = Self.normalizePlan(intent["execution_plan"])
        guard !plan.isEmpty else {
            log("executor: intent \(iid) no plan — UI will stay at 排队 until a step runs")
            return
        }
        // Brain says step is waiting again → drop stale local "already finished" marks.
        for step in plan {
            let n = intValue(step["step"]) ?? 0
            guard n > 0 else { continue }
            if Self.stepStatus(step) == Self.waiting {
                finishedLocalSteps.removeValue(forKey: Self.stepKey(intentId: iid, step: n))
            }
        }
        applyLocalFinishedOverlay(intentId: iid, plan: &plan)

        log(
            "executor: intent \(iid) self=\(eid) planSteps=\(plan.count) "
                + Self.planSummary(plan)
        )

        if Self.findNextEligibleLocalStep(plan: plan, edgeId: eid, intentId: iid) == nil {
            let reasons = Self.explainIneligible(plan: plan, edgeId: eid, intentId: iid)
            log(
                "executor: intent \(iid) no eligible local step — \(reasons)"
            )
            // Surface "waiting on who / what" on remote plan rows so UI isn't just「排队」.
            annotateWaitingRemoteSteps(intentId: iid, plan: plan, selfEdgeId: eid)
            return
        }

        while true {
            Self.advanceSkippedBeats(plan: &plan, intentId: iid, edgeId: eid)
            guard let step = Self.findNextEligibleLocalStep(plan: plan, edgeId: eid, intentId: iid) else {
                break
            }
            let stepNum = intValue(step["step"]) ?? 0
            let cap = stringValue(step["capability"]) ?? "?"
            let timing = ExecutionTiming.parse(from: step)
            guard stepNum > 0 else {
                log("executor: intent \(iid) invalid step number in \(cap)")
                break
            }

            log("executor: intent \(iid) claim step \(stepNum) (\(cap)) → POST step_status=1")
            let reportedRunning = await intentController.reportStepStatus(
                intentId: iid,
                stepId: stepNum,
                stepStatus: Self.running,
                edgeNodeId: eid
            )
            if !reportedRunning {
                log(
                    "executor: intent \(iid) step \(stepNum) POST step_status=1 FAILED — stuck at 排队; check Brain step status API"
                )
                break
            }
            setStatus(&plan, step: stepNum, status: Self.running)
            // Edge owns whole-job status: first running step → intent running.
            await reportIntentStatus(
                intentId: iid,
                status: IntentPhase.running.wireValue,
                edgeNodeId: eid,
                message: "executing \(cap)"
            )
            advanceJourney(
                intentId: iid,
                phase: .running,
                detail: "executing \(cap)",
                edgeNodeId: eid
            )

            // Hydrate RuntimeContext from Brain before ParamResolver reads `$vars`.
            let loaded = Self.brainCtxParam(from: intent)
            if !loaded.isEmpty {
                commandHandler.loadContext(intentId: iid, values: loaded)
            }
            let command = HttpCommandSource.makeCommand(
                fromIntent: intent,
                step: step,
                localEdgeId: eid
            )
            log("executor: intent \(iid) execute step \(stepNum) (\(cap))")
            let results = await commandHandler.handle([command])
            let ok = results.allSatisfy { $0.ok || $0.skipped }
            let final = ok ? Self.succeeded : Self.failed
            let failDetail = results.compactMap { $0.message }.first { !$0.isEmpty }
            // Raw skill outputs → Brain; Brain registers into context via output_constrict.
            // Local RuntimeContext already published in CommandHandler.handle.
            var stepOutputs: [String: String] = [:]
            for r in results {
                for (k, v) in r.outputs where !v.isEmpty {
                    stepOutputs[k] = v
                }
            }
            // UI first: don't wait on Brain RTT — Mac may cast as soon as step status is posted,
            // and the phone would otherwise still show「执行中 / 排队」after the TV has switched.
            let store = intentController.journeyStore ?? AppModel.shared.intentJourney
            let localDetail: String? = {
                if let failDetail, !failDetail.isEmpty { return failDetail }
                if ok, let url = stepOutputs["photo_url"], !url.isEmpty {
                    return "完成 · \(url)"
                }
                return ok ? "完成" : nil
            }()
            store.updatePlanStep(
                intentId: iid,
                capability: cap,
                status: ok ? .succeeded : .failed,
                detail: localDetail,
                outputs: stepOutputs.isEmpty ? nil : stepOutputs
            )
            setStatus(&plan, step: stepNum, status: final)
            finishedLocalSteps[Self.stepKey(intentId: iid, step: stepNum)] = final
            if ok {
                annotateWaitingRemoteSteps(intentId: iid, plan: plan, selfEdgeId: eid)
            }

            let reportedFinal = await intentController.reportStepStatus(
                intentId: iid,
                stepId: stepNum,
                stepStatus: final,
                edgeNodeId: eid,
                outputs: stepOutputs.isEmpty ? nil : stepOutputs
            )
            // Cross-edge: also push on intent status so pull exposes ctx_param promptly.
            if ok, !stepOutputs.isEmpty {
                let published = await intentController.reportAndRefresh(
                    intentId: iid,
                    status: IntentPhase.running.wireValue,
                    edgeNodeId: eid,
                    message: "ctx_param publish step \(stepNum)",
                    outputs: stepOutputs
                )
                let ctxKeys = commandHandler.contextSnapshot(intentId: iid).keys.sorted()
                log(
                    "executor: intent \(iid) step \(stepNum) contextKeys=\(ctxKeys) "
                        + "outputs→Brain=\(stepOutputs.keys.sorted()) intentPublishOk=\(published)"
                )
            }
            // Keep pull-queue populated for the next assignee (Mac display.photo).
            if ok {
                let hasPendingRemote = plan.contains { row in
                    let n = Self.intValueStatic(row["step"]) ?? 0
                    guard n != stepNum else { return false }
                    let assigned = (
                        row["assigned_edge_id"] as? String
                            ?? ""
                    ).trimmingCharacters(in: .whitespacesAndNewlines)
                    let st = Self.intValueStatic(row["status"])
                        ?? Self.intValueStatic(row["step_status"])
                        ?? 0
                    return !assigned.isEmpty && assigned != eid && (st == Self.waiting || st == Self.running)
                }
                if hasPendingRemote {
                    var planForQueue = plan
                    setStatus(&planForQueue, step: stepNum, status: final)
                    let ctx = commandHandler.contextSnapshot(intentId: iid)
                    let requeued = await intentController.requeueIntentForPull(
                        intentId: iid,
                        status: IntentPhase.running.wireValue,
                        executionPlan: planForQueue,
                        ctxParam: ctx.isEmpty ? (stepOutputs.isEmpty ? nil : stepOutputs) : ctx,
                        schedulerNode: eid
                    )
                    log("executor: intent \(iid) requeueForPull=\(requeued)")
                }
            }
            log(
                "executor: intent \(iid) step \(stepNum) done status=\(final) "
                    + "execOk=\(ok) reportOk=\(reportedFinal)"
            )

            if !ok {
                // Edge owns whole-job status: any step fail → intent failed.
                await reportIntentStatus(
                    intentId: iid,
                    status: IntentPhase.failed.wireValue,
                    edgeNodeId: eid,
                    message: failDetail ?? "step \(stepNum) failed"
                )
                advanceJourney(
                    intentId: iid,
                    phase: .failed,
                    detail: failDetail ?? "step \(stepNum) failed",
                    edgeNodeId: eid,
                    error: failDetail
                )
                break
            }
            if !reportedFinal {
                log(
                    "executor: intent \(iid) step \(stepNum) terminal report failed — not retrying locally"
                )
                break
            }

            // Recurring: re-arm waiting + advance beat; one beat per tick.
            if timing.isRecurring {
                TimingBeats.advance(intentId: iid, step: stepNum)
                finishedLocalSteps.removeValue(forKey: Self.stepKey(intentId: iid, step: stepNum))
                _ = await intentController.reportStepStatus(
                    intentId: iid,
                    stepId: stepNum,
                    stepStatus: Self.waiting,
                    edgeNodeId: eid
                )
                setStatus(&plan, step: stepNum, status: Self.waiting)
                log("executor: intent \(iid) step \(stepNum) re-armed for next beat")
                break
            }

            // All plan steps succeeded → intent succeeded (Brain does not infer this).
            if Self.allStepsSucceeded(plan) {
                await reportIntentStatus(
                    intentId: iid,
                    status: IntentPhase.succeeded.wireValue,
                    edgeNodeId: eid,
                    message: "all steps succeeded"
                )
                advanceJourney(
                    intentId: iid,
                    phase: .succeeded,
                    detail: "all steps succeeded",
                    edgeNodeId: eid
                )
            }
            // Only after terminal report may we search for the next local step.
        }
    }

    /// POST intent-level status (scheduler/executor node responsibility, not Brain).
    private func reportIntentStatus(
        intentId: String,
        status: String,
        edgeNodeId: String,
        message: String
    ) async {
        let ok = await intentController.reportAndRefresh(
            intentId: intentId,
            status: status,
            edgeNodeId: edgeNodeId,
            message: message
        )
        log(
            "executor: intent \(intentId) intent_status=\(status) reportOk=\(ok)"
        )
    }

    private static func allStepsSucceeded(_ plan: [[String: Any]]) -> Bool {
        guard !plan.isEmpty else { return false }
        for step in plan {
            let timing = ExecutionTiming.parse(from: step)
            if timing.isRecurring, stepStatus(step) == waiting {
                return false
            }
            if stepStatus(step) != succeeded {
                return false
            }
        }
        return true
    }

    private func clearFinished(for intentId: String) {
        let prefix = "\(intentId):"
        let keys = finishedLocalSteps.keys.filter { $0.hasPrefix(prefix) }
        keys.forEach { finishedLocalSteps.removeValue(forKey: $0) }
    }

    private func applyLocalFinishedOverlay(intentId: String, plan: inout [[String: Any]]) {
        for i in plan.indices {
            let n = intValue(plan[i]["step"]) ?? 0
            guard n > 0, let st = finishedLocalSteps[Self.stepKey(intentId: intentId, step: n)] else {
                continue
            }
            plan[i]["status"] = st
            plan[i]["step_status"] = st
        }
    }

    private static func stepKey(intentId: String, step: Int) -> String {
        "\(intentId):\(step)"
    }

    private func advanceJourney(
        intentId: String,
        phase: IntentPhase,
        detail: String,
        edgeNodeId: String,
        error: String? = nil
    ) {
        let store = intentController.journeyStore ?? AppModel.shared.intentJourney
        store.applyLocalPhase(
            intentId: intentId,
            phase: phase,
            detail: detail,
            edgeNodeId: edgeNodeId,
            error: error
        )
    }

    /// Update UI for steps assigned to other edges (or blocked on predecessors).
    private func annotateWaitingRemoteSteps(
        intentId: String,
        plan: [[String: Any]],
        selfEdgeId: String
    ) {
        let store = intentController.journeyStore ?? AppModel.shared.intentJourney
        let eid = selfEdgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        for row in plan {
            let n = intValue(row["step"]) ?? 0
            let cap = (stringValue(row["capability"]) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard n > 0, !cap.isEmpty else { continue }
            let st = Self.stepStatus(row)
            if st == Self.succeeded || st == Self.failed { continue }
            let assigned = (
                stringValue(row["assigned_edge_id"])
                    ?? ""
            ).trimmingCharacters(in: .whitespacesAndNewlines)
            let detail: String
            if !assigned.isEmpty, assigned != eid {
                if st == Self.waiting, !Self.predecessorsAllSucceeded(plan, stepNum: n) {
                    detail = "等待前置 step 完成后再由 \(assigned) 执行"
                } else if st == Self.running {
                    detail = "远端执行中：\(assigned)"
                } else {
                    detail = "排队：等待 \(assigned) 领取执行"
                }
                store.updatePlanStep(
                    intentId: intentId,
                    capability: cap,
                    status: st == Self.running ? .running : .queued,
                    detail: detail
                )
            } else if assigned == eid, st == Self.waiting,
                      !Self.predecessorsAllSucceeded(plan, stepNum: n) {
                store.updatePlanStep(
                    intentId: intentId,
                    capability: cap,
                    status: .queued,
                    detail: "等待前置 step 完成"
                )
            }
        }
    }

    static func findNextEligibleLocalStep(
        plan: [[String: Any]],
        edgeId: String,
        intentId: String = ""
    ) -> [String: Any]? {
        let eid = edgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        let now = BrainTimeSync.nowMs()
        let ordered = plan.sorted {
            (intValueStatic($0["step"]) ?? 0) < (intValueStatic($1["step"]) ?? 0)
        }
        for step in ordered {
            let assigned = (stringValueStatic(step["assigned_edge_id"])
                ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard assigned == eid else { continue }
            let n = intValueStatic(step["step"]) ?? 0
            let st = stepStatus(step)
            guard st == waiting else { continue }
            guard predecessorsAllSucceeded(ordered, stepNum: n) else { continue }
            let timing = ExecutionTiming.parse(from: step)
            let beat = intentId.isEmpty ? 0 : TimingBeats.get(intentId: intentId, step: n)
            let gate = timing.gate(nowMs: now, beatIndex: beat)
            guard gate.due else { continue }
            return step
        }
        return nil
    }

    /// Skip interval/cron beats past miss window; expire one-shot delay beyond 15min.
    static func advanceSkippedBeats(plan: inout [[String: Any]], intentId: String, edgeId: String) {
        let eid = edgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        let now = BrainTimeSync.nowMs()
        for i in plan.indices {
            var step = plan[i]
            let assigned = (stringValueStatic(step["assigned_edge_id"])
                ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard assigned == eid else { continue }
            guard stepStatus(step) == waiting else { continue }
            let timing = ExecutionTiming.parse(from: step)
            let n = intValueStatic(step["step"]) ?? 0
            if !timing.isRecurring {
                if timing.mode == .delay {
                    let gate = timing.gate(nowMs: now, beatIndex: 0)
                    if gate.terminal {
                        step["status"] = failed
                        plan[i] = step
                    }
                }
                continue
            }
            for _ in 0 ..< 64 {
                let beat = TimingBeats.get(intentId: intentId, step: n)
                let gate = timing.gate(nowMs: now, beatIndex: beat)
                if gate.terminal {
                    step["status"] = succeeded
                    plan[i] = step
                    break
                }
                if gate.skipBeat {
                    TimingBeats.advance(intentId: intentId, step: n)
                    continue
                }
                break
            }
        }
    }

    /// Human-readable why each plan step is not runnable on this edge.
    static func explainIneligible(
        plan: [[String: Any]],
        edgeId: String,
        intentId: String = ""
    ) -> String {
        let eid = edgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        let now = BrainTimeSync.nowMs()
        let ordered = plan.sorted {
            (intValueStatic($0["step"]) ?? 0) < (intValueStatic($1["step"]) ?? 0)
        }
        return ordered.map { step in
            let n = intValueStatic(step["step"]) ?? 0
            let cap = stringValueStatic(step["capability"]) ?? "?"
            let assigned = (stringValueStatic(step["assigned_edge_id"])
                ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let st = stepStatus(step)
            if assigned != eid {
                return "step\(n)(\(cap)): assigned=\(assigned.isEmpty ? "<empty>" : assigned) ≠ self=\(eid)"
            }
            if st != waiting {
                return "step\(n)(\(cap)): status=\(st) (need 0=waiting; 1=running 2=ok 3=fail)"
            }
            if !predecessorsAllSucceeded(ordered, stepNum: n) {
                let pending = ordered.compactMap { p -> String? in
                    let pn = intValueStatic(p["step"]) ?? 0
                    guard pn < n else { return nil }
                    let ps = stepStatus(p)
                    guard ps != succeeded else { return nil }
                    return "step\(pn)=status\(ps)"
                }.joined(separator: ",")
                return "step\(n)(\(cap)): waiting for predecessors [\(pending)] to be status=2"
            }
            let timing = ExecutionTiming.parse(from: step)
            let beat = intentId.isEmpty ? 0 : TimingBeats.get(intentId: intentId, step: n)
            let gate = timing.gate(nowMs: now, beatIndex: beat)
            if !gate.due {
                return "step\(n)(\(cap)): timing \(gate.reason)"
            }
            return "step\(n)(\(cap)): eligible"
        }.joined(separator: " | ")
    }

    private static func planSummary(_ plan: [[String: Any]]) -> String {
        plan.map { step in
            let n = intValueStatic(step["step"]) ?? 0
            let cap = stringValueStatic(step["capability"]) ?? "?"
            let a = stringValueStatic(step["assigned_edge_id"])
                ?? "-"
            let st = stepStatus(step)
            return "[\(n) \(cap) @\(a) status=\(st)]"
        }.joined(separator: " ")
    }

    private static func predecessorsAllSucceeded(_ plan: [[String: Any]], stepNum: Int) -> Bool {
        for step in plan {
            let n = intValueStatic(step["step"]) ?? 0
            guard n < stepNum else { continue }
            if stepStatus(step) != succeeded { return false }
        }
        return true
    }

    static func stepStatus(_ step: [String: Any]) -> Int {
        if let v = step["status"] as? Int { return v }
        if let v = step["step_status"] as? Int { return v }
        if let s = stringValueStatic(step["status"]) ?? stringValueStatic(step["step_status"]),
           let v = Int(s) { return v }
        return waiting
    }

    static func normalizePlan(_ raw: Any?) -> [[String: Any]] {
        guard let arr = raw as? [Any] else { return [] }
        return arr.compactMap { item -> [String: Any]? in
            guard var dict = item as? [String: Any] else { return nil }
            if dict["status"] == nil, dict["step_status"] != nil {
                dict["status"] = dict["step_status"]
            }
            if dict["status"] == nil {
                dict["status"] = waiting
            }
            dict.removeValue(forKey: "delay_sec")
            if var et = dict["execution_timing"] as? [String: Any] {
                et.removeValue(forKey: "delay_sec")
                dict["execution_timing"] = et
            }
            return dict
        }
    }

    /// Production Brain: shared bag is `ctx_param` only.
    static func brainCtxParam(from intent: [String: Any]) -> [String: String] {
        var loaded: [String: String] = [:]
        guard let bag = intent["ctx_param"] as? [String: Any] else { return [:] }
        for (k, v) in bag {
            if let s = v as? String, !s.isEmpty {
                loaded[k] = s
            } else if let n = v as? NSNumber {
                loaded[k] = n.stringValue
            }
        }
        return loaded
    }

    private func setStatus(_ plan: inout [[String: Any]], step: Int, status: Int) {
        for i in plan.indices {
            if intValue(plan[i]["step"]) == step {
                plan[i]["status"] = status
                plan[i]["step_status"] = status
            }
        }
    }

    private func log(_ message: String) {
        NSLog("[IntentStepExecutor] %@", message)
        onLog?(message)
    }

    private func stringValue(_ any: Any?) -> String? { Self.stringValueStatic(any) }
    private func intValue(_ any: Any?) -> Int? { Self.intValueStatic(any) }

    private static func stringValueStatic(_ any: Any?) -> String? {
        guard let any else { return nil }
        if let s = any as? String { return s }
        if let n = any as? NSNumber { return n.stringValue }
        return nil
    }

    private static func intValueStatic(_ any: Any?) -> Int? {
        if let i = any as? Int { return i }
        if let n = any as? NSNumber { return n.intValue }
        if let s = stringValueStatic(any) { return Int(s) }
        return nil
    }
}
