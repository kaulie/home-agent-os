import Foundation

/// In-process stand-in for the AI brain (mirrors Android MockBrainClient).
/// Isolated on the main actor — no NSLock (Swift 6 forbids lock/unlock in async contexts).
@MainActor
final class MockBrainClient: BrainClient, ObservableObject {
    private var registrations: [String: EdgeNodeInfo] = [:]
    private var pendingPlans: [String: [Plan]] = [:]
    private(set) var reports: [ExecutionReport] = []
    /// edgeIds issued by mock registerEdge.
    private var issuedEdgeIds: Set<String> = []

    var lastNodeInfo: EdgeNodeInfo? {
        registrations.values.max(by: { $0.reportedAt < $1.reportedAt })
    }

    /// Legacy alias.
    var lastRegistration: EdgeRegistration? {
        guard let info = lastNodeInfo else { return nil }
        return EdgeRegistration(edgeId: info.edgeId, services: info.services, registeredAt: info.reportedAt)
    }

    func nodeInfo(for edgeId: String) -> EdgeNodeInfo? {
        registrations[edgeId]
    }

    func enqueuePlan(edgeId: String, plan: Plan) {
        pendingPlans[edgeId, default: []].append(plan)
    }

    @discardableResult
    func enqueueSkillAction(
        edgeId: String,
        skillId: String,
        action: String,
        params: [String: String] = [:]
    ) -> Plan {
        let plan = Plan(
            planId: "plan-\(UUID().uuidString.prefix(8))",
            steps: [
                PlanStep(
                    stepId: "step-1",
                    skillId: skillId,
                    action: action,
                    params: params,
                    onFailure: .abort
                ),
            ]
        )
        enqueuePlan(edgeId: edgeId, plan: plan)
        return plan
    }

    func registerEdge(_ request: EdgeRegisterRequest) async throws -> EdgeRegisterResponse {
        let hint = (request.clientHint ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let edgeId: String
        if !hint.isEmpty, !issuedEdgeIds.contains(hint) {
            edgeId = hint
        } else if !hint.isEmpty {
            edgeId = "\(hint)-\(String(UUID().uuidString.prefix(6)).lowercased())"
        } else {
            edgeId = "edge-\(String(UUID().uuidString.prefix(8)).lowercased())"
        }
        issuedEdgeIds.insert(edgeId)
        return EdgeRegisterResponse(
            ok: true,
            status: "approved",
            edgeId: edgeId,
            message: "mock approved"
        )
    }

    func reportEdgeInfo(_ info: EdgeNodeInfo) async throws {
        if info.edgeId.isEmpty {
            throw NSError(
                domain: "MockBrainClient",
                code: 401,
                userInfo: [NSLocalizedDescriptionKey: "heartbeat requires edgeId; call registerEdge first"]
            )
        }
        issuedEdgeIds.insert(info.edgeId)
        registrations[info.edgeId] = info
    }

    func fetchPlans(edgeId: String) async throws -> [Plan] {
        let drained = pendingPlans[edgeId] ?? []
        pendingPlans[edgeId] = []
        return drained
    }

    func report(_ report: ExecutionReport) async throws {
        reports.append(report)
        if reports.count > 100 {
            reports.removeFirst(reports.count - 100)
        }
    }
}
