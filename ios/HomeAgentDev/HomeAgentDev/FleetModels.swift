import Foundation

private func decodeFlexibleDouble<K: CodingKey>(
    _ c: KeyedDecodingContainer<K>,
    key: K
) -> Double? {
    if let v = try? c.decodeIfPresent(Double.self, forKey: key) { return v }
    if let v = try? c.decodeIfPresent(Int.self, forKey: key) { return Double(v) }
    if let s = try? c.decodeIfPresent(String.self, forKey: key), let v = Double(s) { return v }
    return nil
}

struct FleetAgent: Identifiable, Decodable, Equatable {
    let handle: String
    let displayName: String
    let agentId: String?
    let lastWakeAt: Double?
    let runningRunId: String?
    let runningStatus: String?
    let isRunning: Bool
    let hasSession: Bool

    var id: String { handle }

    enum CodingKeys: String, CodingKey {
        case handle
        case displayName = "display_name"
        case agentId = "agent_id"
        case lastWakeAt = "last_wake_at"
        case runningRunId = "running_run_id"
        case runningStatus = "running_status"
        case isRunning = "is_running"
        case hasSession = "has_session"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        handle = try c.decode(String.self, forKey: .handle)
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName) ?? handle
        agentId = try c.decodeIfPresent(String.self, forKey: .agentId)
        lastWakeAt = decodeFlexibleDouble(c, key: .lastWakeAt)
        runningRunId = try c.decodeIfPresent(String.self, forKey: .runningRunId)
        runningStatus = try c.decodeIfPresent(String.self, forKey: .runningStatus)
        isRunning = try c.decodeIfPresent(Bool.self, forKey: .isRunning) ?? (runningRunId != nil)
        hasSession = try c.decodeIfPresent(Bool.self, forKey: .hasSession) ?? (agentId != nil)
    }
}

struct FleetBridgeStatus: Decodable, Equatable {
    let agentConnected: Bool?
    let activeRunId: String?
    let activeStatus: String?
    let runningRunId: String?
    let queueDepth: Int?
    let queuedCount: Int?
    let model: String?
    let backend: String?

    enum CodingKeys: String, CodingKey {
        case agentConnected = "agent_connected"
        case activeRunId = "active_run_id"
        case activeStatus = "active_status"
        case runningRunId = "running_run_id"
        case queueDepth = "queue_depth"
        case queuedCount = "queued_count"
        case model
        case backend
    }
}

struct FleetRun: Identifiable, Decodable, Equatable {
    let runId: String
    let status: String
    let targetHandle: String?
    let text: String?
    let createdAt: Double?
    let updatedAt: Double?

    var id: String { runId }

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case status
        case targetHandle = "target_handle"
        case text
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        runId = try c.decode(String.self, forKey: .runId)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        targetHandle = try c.decodeIfPresent(String.self, forKey: .targetHandle)
        text = try c.decodeIfPresent(String.self, forKey: .text)
        createdAt = decodeFlexibleDouble(c, key: .createdAt)
        updatedAt = decodeFlexibleDouble(c, key: .updatedAt)
    }
}

struct FleetSnapshot: Decodable, Equatable {
    let ok: Bool?
    let error: String?
    let bridgeURL: String?
    let bridgeOk: Bool?
    let status: FleetBridgeStatus?
    let agents: [FleetAgent]
    let runs: [FleetRun]

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case bridgeURL = "bridge_url"
        case bridgeOk = "bridge_ok"
        case status
        case agents
        case runs
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        bridgeURL = try c.decodeIfPresent(String.self, forKey: .bridgeURL)
        bridgeOk = try c.decodeIfPresent(Bool.self, forKey: .bridgeOk)
        status = try c.decodeIfPresent(FleetBridgeStatus.self, forKey: .status)
        agents = try c.decodeIfPresent([FleetAgent].self, forKey: .agents) ?? []
        runs = try c.decodeIfPresent([FleetRun].self, forKey: .runs) ?? []
    }
}

struct FleetWakeResponse: Decodable {
    let ok: Bool?
    let error: String?
    let handle: String?
    let runId: String?
    let status: String?

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case handle
        case runId = "run_id"
        case status
    }
}
