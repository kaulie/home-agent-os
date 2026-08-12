import Foundation

struct PlanOutcome {
    let planId: String
    let reports: [ExecutionReport]
    let aborted: Bool
}

@MainActor
final class PlanExecutor {
    var edgeId: String
    private let registry: SkillRegistry
    private let brain: BrainClient

    init(edgeId: String, registry: SkillRegistry, brain: BrainClient) {
        self.edgeId = edgeId
        self.registry = registry
        self.brain = brain
    }

    func execute(_ plan: Plan) async -> PlanOutcome {
        var reports: [ExecutionReport] = []
        var aborted = false

        for (index, step) in plan.steps.enumerated() {
            let result: SkillResult
            if let skill = registry.get(step.skillId) {
                let ctx = SkillContext(edgeId: edgeId, planId: plan.planId, stepId: step.stepId)
                result = await skill.execute(capabilityId: step.action, params: step.params, context: ctx)
            } else {
                result = .error("skill not registered: \(step.skillId)")
            }

            let reportMessage: String?
            if let outputs = result.outputs, !outputs.isEmpty,
               let data = try? JSONSerialization.data(withJSONObject: outputs, options: [.sortedKeys]),
               let json = String(data: data, encoding: .utf8) {
                if let base = result.message, !base.isEmpty {
                    reportMessage = "\(base)\noutputs=\(json)"
                } else {
                    reportMessage = "outputs=\(json)"
                }
            } else {
                reportMessage = result.message
            }
            let report = ExecutionReport(
                planId: plan.planId,
                stepId: step.stepId,
                status: result.ok ? .ok : .error,
                message: reportMessage
            )
            reports.append(report)
            try? await brain.report(report)

            if !result.ok && step.onFailure == .abort {
                aborted = true
                for rest in plan.steps.suffix(from: index + 1) {
                    let skipped = ExecutionReport(
                        planId: plan.planId,
                        stepId: rest.stepId,
                        status: .skipped,
                        message: "aborted after failure of \(step.stepId)"
                    )
                    reports.append(skipped)
                    try? await brain.report(skipped)
                }
                break
            }
        }

        return PlanOutcome(planId: plan.planId, reports: reports, aborted: aborted)
    }
}
