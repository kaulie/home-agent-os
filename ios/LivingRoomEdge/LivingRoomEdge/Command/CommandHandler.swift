import Foundation

@MainActor
final class CommandHandler {
    private let dispatcher: TaskDispatcher
    private let localNode: EdgeRuntimeNode
    private let intentController: IntentController?
    private let instant = InstantScheduler()
    private let cron = CronJobScheduler()
    private let event = EventTriggerScheduler()
    /// Persist context across pulls for the same intent (capture then display).
    private var contextsByIntentId: [String: RuntimeContext] = [:]
    var onLog: ((String) -> Void)?

    init(
        dispatcher: TaskDispatcher,
        localNode: EdgeRuntimeNode,
        intentController: IntentController? = nil
    ) {
        self.dispatcher = dispatcher
        self.localNode = localNode
        self.intentController = intentController
    }

    func scheduler(for spec: ScheduleSpec) -> TaskScheduler {
        switch spec {
        case .instant: return instant
        case .cron: return cron
        case .event: return event
        }
    }

    @discardableResult
    func handle(_ commands: [EdgeCommand]) async -> [TaskExecutionResult] {
        guard !commands.isEmpty else { return [] }
        var results: [TaskExecutionResult] = []
        // One ephemeral context for commands without intent_id (UI / mock).
        var orphanContext: RuntimeContext?
        for cmd in commands {
            log(
                "Command received id=\(cmd.commandId) device=\(cmd.device) action=\(cmd.action) source=\(cmd.source.rawValue)"
            )
            let context = contextForCommand(cmd, orphan: &orphanContext)
            var working = cmd
            if cmd.source == .server {
                do {
                    let resolved = try ParamResolver.resolve(params: cmd.params, context: context)
                    working = cmd.with(params: resolved)
                } catch {
                    let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                    log(
                        "Param resolve failed id=\(cmd.commandId): \(msg) contextKeys=\(context.snapshot().keys.sorted().joined(separator: ","))"
                    )
                    let failed = await failUnresolved(command: cmd, message: msg)
                    results.append(failed)
                    continue
                }
            }
            let tasks: [EdgeTask]
            switch working.source {
            case .mockPlan, .ui:
                tasks = CommandDecomposer.planCommandsToTasks([working])
            case .server:
                tasks = CommandDecomposer.fromServerCommand(working)
            }
            for task in tasks {
                log(
                    "Task decomposed taskId=\(task.taskId) skill=\(task.skillId ?? "nil") action=\(task.action) schedule=\(task.schedule.kind) outputConstrict=\(task.outputConstrict.keys.sorted().joined(separator: ","))"
                )
                let result = await scheduleAndDispatch(task)
                results.append(result)
                if result.ok, !task.outputConstrict.isEmpty {
                    let published = context.publish(
                        outputs: result.outputs,
                        constrict: task.outputConstrict
                    )
                    log(
                        "Context publish action=\(task.action) keys=\(published.joined(separator: ","))"
                    )
                }
            }
        }
        return results
    }

    /// Hydrate intent context from Brain `ctx_param` before resolving `$vars`.
    func loadContext(intentId: String, values: [String: String]) {
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !iid.isEmpty, !values.isEmpty else { return }
        let ctx = contextsByIntentId[iid] ?? RuntimeContext()
        for (k, v) in values {
            let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = v.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, !value.isEmpty, !value.hasPrefix("$") else { continue }
            // Reuse publish path with a synthetic constrict (data_dest=context).
            _ = ctx.publish(
                outputs: [key: value],
                constrict: [key: OutputConstrictField(type: "string", dataDest: "context")]
            )
        }
        contextsByIntentId[iid] = ctx
        log("Context load intent=\(iid) keys=\(ctx.snapshot().keys.sorted().joined(separator: ","))")
    }

    func contextSnapshot(intentId: String) -> [String: String] {
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !iid.isEmpty else { return [:] }
        return contextsByIntentId[iid]?.snapshot() ?? [:]
    }

    private func contextForCommand(
        _ cmd: EdgeCommand,
        orphan: inout RuntimeContext?
    ) -> RuntimeContext {
        if let intentId = Self.intentId(from: cmd.params) {
            if let existing = contextsByIntentId[intentId] {
                return existing
            }
            let created = RuntimeContext()
            contextsByIntentId[intentId] = created
            return created
        }
        if let orphan { return orphan }
        let created = RuntimeContext()
        orphan = created
        return created
    }

    private func failUnresolved(command: EdgeCommand, message: String) async -> TaskExecutionResult {
        let capability = (command.params["capability"] ?? command.action)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let jobId = Self.intentId(from: command.params) {
            markPlanStep(jobId: jobId, capability: capability, status: .failed, detail: message)
            // Cross-edge: IntentStepExecutor reports step_status=3; skip whole-job failed.
            let stepAPI = (command.params["step_status_api"] ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines) == "1"
            if !stepAPI {
                await reportIntentJob(
                    jobId: jobId,
                    status: IntentPhase.failed.wireValue,
                    message: message
                )
            }
        }
        return TaskExecutionResult(
            taskId: "task-\(command.commandId)-resolve",
            ok: false,
            message: message,
            skipped: false
        )
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

    private func scheduleAndDispatch(_ task: EdgeTask) async -> TaskExecutionResult {
        let sched = scheduler(for: task.schedule)
        log("Scheduled(\(task.schedule.kind)) taskId=\(task.taskId)")
        switch task.schedule {
        case .instant:
            let ready = await withCheckedContinuation { (cont: CheckedContinuation<EdgeTask, Never>) in
                sched.schedule(task: task) { ready in
                    cont.resume(returning: ready)
                }
            }
            return await dispatchReady(ready)
        case .cron, .event:
            sched.schedule(task: task) { _ in }
            log("Task parked in \(task.schedule.kind) scheduler taskId=\(task.taskId) (skeleton)")
            return TaskExecutionResult(
                taskId: task.taskId,
                ok: true,
                message: "parked:\(task.schedule.kind)",
                skipped: true
            )
        }
    }

    private func dispatchReady(_ task: EdgeTask) async -> TaskExecutionResult {
        // Cross-edge: intent_scheduled / intent_dispatched are owned by IntentScheduler;
        // step 0/1/2/3 by IntentStepExecutor. Do not emit whole-job hub/scheduled/assigned here.
        log("Dispatched(local) taskId=\(task.taskId) → \(localNode.nodeId)")
        let result = await dispatcher.dispatch(task: task, node: localNode)
        let status = result.skipped ? "skipped" : (result.ok ? "ok" : "error")
        log(
            "Executed taskId=\(task.taskId) action=\(task.action) status=\(status)"
        )
        if let msg = result.message?.trimmingCharacters(in: .whitespacesAndNewlines), !msg.isEmpty {
            for line in msg.split(separator: "\n", omittingEmptySubsequences: false) {
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                guard !trimmed.isEmpty else { continue }
                log("  └ \(trimmed)")
            }
        }
        return result
    }

    private func reportIntentJob(jobId: String, status: String, message: String) async {
        guard let intentController else {
            log("intent status report skipped (no IntentController) intent_id=\(jobId) status=\(status)")
            return
        }
        let ok = await intentController.reportAndRefresh(
            intentId: jobId,
            status: status,
            edgeNodeId: localNode.nodeId,
            message: message
        )
        if !ok {
            log("intent status report failed intent_id=\(jobId) status=\(status)")
        }
    }

    static func intentId(from params: [String: String]) -> String? {
        if let v = params["intent_id"]?.trimmingCharacters(in: .whitespacesAndNewlines), !v.isEmpty {
            return v
        }
        return nil
    }

    private func log(_ message: String) {
        NSLog("[CommandHandler] %@", message)
        onLog?(message)
    }
}
