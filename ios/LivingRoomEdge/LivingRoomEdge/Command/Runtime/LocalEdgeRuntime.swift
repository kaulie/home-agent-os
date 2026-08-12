import Foundation

@MainActor
protocol EdgeRuntime: AnyObject {
    func execute(task: EdgeTask, node: EdgeRuntimeNode) async -> TaskExecutionResult
}

@MainActor
final class LocalEdgeRuntime: EdgeRuntime {
    private var edgeId: String
    private let registry: SkillRegistry
    private let brain: BrainClient
    private let intentController: IntentController?

    init(
        edgeId: String,
        registry: SkillRegistry,
        brain: BrainClient,
        intentController: IntentController? = nil
    ) {
        self.edgeId = edgeId
        self.registry = registry
        self.brain = brain
        self.intentController = intentController
    }

    func updateEdgeId(_ id: String) {
        edgeId = id
    }

    func execute(task: EdgeTask, node: EdgeRuntimeNode) async -> TaskExecutionResult {
        let jobId = CommandHandler.intentId(from: task.params)
        let capability = (task.params["capability"] ?? task.action)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let stepStatusOnly = Self.usesStepStatusAPI(params: task.params)
        if let skip = task.skipReason, !skip.isEmpty {
            let msg = "skipped: \(skip)"
            await report(task: task, status: .skipped, message: msg)
            if let jobId {
                markPlanStep(jobId: jobId, capability: capability, status: .skipped, detail: msg)
                if !stepStatusOnly {
                    await reportIntentJob(
                        jobId: jobId,
                        status: IntentPhase.failed.wireValue,
                        edgeNodeId: node.nodeId,
                        message: msg
                    )
                }
            }
            return TaskExecutionResult(taskId: task.taskId, ok: true, message: msg, skipped: true)
        }
        guard let skillId = task.skillId, !skillId.isEmpty else {
            let msg = "no skill mapped"
            await report(task: task, status: .skipped, message: msg)
            if let jobId {
                markPlanStep(jobId: jobId, capability: capability, status: .failed, detail: msg)
                if !stepStatusOnly {
                    await reportIntentJob(
                        jobId: jobId,
                        status: IntentPhase.failed.wireValue,
                        edgeNodeId: node.nodeId,
                        message: msg
                    )
                }
            }
            return TaskExecutionResult(taskId: task.taskId, ok: false, message: msg, skipped: true)
        }
        if let jobId {
            markPlanStep(
                jobId: jobId,
                capability: capability,
                status: .running,
                detail: Self.runningDetail(skillId: skillId, action: task.action, capability: capability)
            )
            if !stepStatusOnly {
                await reportIntentJob(
                    jobId: jobId,
                    status: IntentPhase.running.wireValue,
                    edgeNodeId: node.nodeId,
                    message: "executing \(skillId).\(task.action)"
                )
            }
        }
        let result: SkillResult
        if let skill = registry.get(skillId) {
            let ctx = SkillContext(edgeId: edgeId, planId: task.commandId, stepId: task.taskId)
            let capabilityId = task.action
            let params = task.params
            // Keep heavy camera/cast work off the cooperative MainActor queue so
            // heartbeat + intent_detail polling can interleave during long pipelines.
            result = await SkillExecutionHop.run(skill: skill, capabilityId: capabilityId, params: params, context: ctx)
        } else {
            result = .error("skill not registered: \(skillId)")
        }
        await report(task: task, status: result.ok ? .ok : .error, message: Self.reportMessage(from: result))
        if let jobId {
            let detail = result.message?
                .split(separator: "\n", omittingEmptySubsequences: false)
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .first { !$0.isEmpty }
                .map { String($0) }
            let stepStatus: IntentPlanStepRunStatus = result.ok ? .succeeded : .failed
            markPlanStep(
                jobId: jobId,
                capability: capability,
                status: stepStatus,
                detail: detail
            )
            // Cross-edge path: IntentStepExecutor owns step_status 1/2/3.
            // Legacy single-node path still reports whole-job running/succeeded/failed.
            if !stepStatusOnly {
                let jobWire: String
                if !result.ok {
                    jobWire = IntentPhase.failed.wireValue
                } else if Self.isLastPlanStep(params: task.params) {
                    jobWire = IntentPhase.succeeded.wireValue
                } else {
                    jobWire = IntentPhase.running.wireValue
                }
                await reportIntentJob(
                    jobId: jobId,
                    status: jobWire,
                    edgeNodeId: node.nodeId,
                    message: Self.reportMessage(from: result) ?? (result.ok ? "ok" : "failed"),
                    outputs: result.outputs
                )
            }
            // Re-assert after intent_detail refresh (job-level status must not wipe per-step).
            markPlanStep(
                jobId: jobId,
                capability: capability,
                status: stepStatus,
                detail: detail
            )
        }
        NSLog(
            "[LocalEdgeRuntime] executed taskId=%@ skill=%@ action=%@ ok=%@",
            task.taskId, skillId, task.action, result.ok ? "true" : "false"
        )
        return TaskExecutionResult(
            taskId: task.taskId,
            ok: result.ok,
            message: result.message,
            skipped: false,
            outputs: result.outputs ?? [:]
        )
    }

    private static func reportMessage(from result: SkillResult) -> String? {
        let base = result.message?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let outputs = result.outputs, !outputs.isEmpty else {
            return (base?.isEmpty == false) ? base : nil
        }
        guard let data = try? JSONSerialization.data(withJSONObject: outputs, options: [.sortedKeys]),
              let json = String(data: data, encoding: .utf8) else {
            return (base?.isEmpty == false) ? base : nil
        }
        if let base, !base.isEmpty {
            return "\(base)\noutputs=\(json)"
        }
        return "outputs=\(json)"
    }

    /// True when this capability is the last row of execution_plan (or plan size unknown).
    private static func isLastPlanStep(params: [String: String]) -> Bool {
        let step = Int(params["step"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "") ?? 0
        let count = Int(params["plan_step_count"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "") ?? 0
        if count <= 0 || step <= 0 { return true }
        return step >= count
    }

    /// Cross-edge executor reports step status separately; skip whole-job intent_status.
    private static func usesStepStatusAPI(params: [String: String]) -> Bool {
        (params["step_status_api"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines) == "1"
    }

    /// Short Chinese activity line for the plan-step row while a skill runs.
    private static func runningDetail(skillId: String, action: String, capability: String) -> String {
        let cap = capability.trimmingCharacters(in: .whitespacesAndNewlines)
        switch cap {
        case Capabilities.cameraCapture:
            return "开始拍照流水线（快门 → 下载 → 上传）…"
        case Capabilities.displayPhoto:
            return "开始投屏…"
        case Capabilities.intentDispatch:
            return "正在向 Brain 下发意图…"
        default:
            return "执行 \(skillId).\(action)…"
        }
    }

    /// Report to backend only; timeline updates via intent_detail after successful POST.
    private func reportIntentJob(
        jobId: String,
        status: String,
        edgeNodeId: String,
        message: String,
        outputs: [String: String]? = nil
    ) async {
        guard let intentController else {
            NSLog(
                "[LocalEdgeRuntime] intent status report skipped (no IntentController) intent_id=%@ status=%@",
                jobId,
                status
            )
            return
        }
        let ok = await intentController.reportAndRefresh(
            intentId: jobId,
            status: status,
            edgeNodeId: edgeNodeId,
            message: message,
            outputs: outputs
        )
        if !ok {
            NSLog(
                "[LocalEdgeRuntime] intent status report failed intent_id=%@ status=%@",
                jobId,
                status
            )
        }
    }

    private func markPlanStep(
        jobId: String,
        capability: String,
        status: IntentPlanStepRunStatus,
        detail: String?
    ) {
        let store = intentController?.journeyStore ?? AppModel.shared.intentJourney
        let cap = capability.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cap.isEmpty else { return }
        store.updatePlanStep(intentId: jobId, capability: cap, status: status, detail: detail)
    }

    private func report(task: EdgeTask, status: StepStatus, message: String?) async {
        let report = ExecutionReport(
            planId: task.commandId,
            stepId: task.taskId,
            status: status,
            message: message
        )
        try? await brain.report(report)
    }
}

/// Runs skill work outside the caller's actor isolation so MainActor loops stay responsive.
enum SkillExecutionHop {
    static func run(
        skill: Skill,
        capabilityId: String,
        params: [String: String],
        context: SkillContext
    ) async -> SkillResult {
        await withCheckedContinuation { cont in
            Task.detached(priority: .userInitiated) {
                let result = await skill.execute(
                    capabilityId: capabilityId,
                    params: params,
                    context: context
                )
                cont.resume(returning: result)
            }
        }
    }
}
