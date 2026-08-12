import Foundation

@MainActor
protocol BrainClient: AnyObject {
    /// **First contact:** Edge → Brain register. Brain returns trusted `edgeId` after confirmation.
    /// Heartbeat must not be called until this succeeds (or a previously assigned edgeId is reused).
    func registerEdge(_ request: EdgeRegisterRequest) async throws -> EdgeRegisterResponse

    /// **Edge → Brain heartbeat** (requires a Brain-issued `info.edgeId`).
    func reportEdgeInfo(_ info: EdgeNodeInfo) async throws
    func fetchPlans(edgeId: String) async throws -> [Plan]
    func report(_ report: ExecutionReport) async throws
}
