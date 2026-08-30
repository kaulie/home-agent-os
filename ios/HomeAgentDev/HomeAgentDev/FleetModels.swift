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

struct FleetChatWorkItem: Decodable, Equatable, Identifiable {
    let id: Int
    let fromHandle: String?
    let preview: String?
    let ackType: String?

    enum CodingKeys: String, CodingKey {
        case id
        case fromHandle = "from"
        case preview
        case ackType = "ack_type"
    }
}

struct FleetAgent: Identifiable, Decodable, Equatable {
    let handle: String
    let displayName: String
    let agentId: String?
    let lastWakeAt: Double?
    let runningRunId: String?
    let runningStatus: String?
    let queuedRunId: String?
    let activeRunId: String?
    let activeStatus: String?
    let sourceMessageId: Int?
    let isRunning: Bool
    let isQueued: Bool
    let hasSession: Bool
    let phase: String?
    let phaseLabel: String?
    let aligned: Bool?
    let desync: String?
    let chatOpenCount: Int?
    let chatAwaitingRecv: [FleetChatWorkItem]

    var id: String { handle }

    var phaseBadgeText: String {
        if let phaseLabel, !phaseLabel.isEmpty { return phaseLabel }
        if isRunning { return runningStatus ?? "执行中" }
        if isQueued { return "队列中" }
        if hasSession { return "session" }
        return "空闲"
    }

    var phaseIsActive: Bool {
        let key = (phase ?? "").lowercased()
        return isRunning || isQueued || key == "awaiting_recv" || key == "awaiting_ide" || key == "acked"
    }

    enum CodingKeys: String, CodingKey {
        case handle
        case displayName = "display_name"
        case agentId = "agent_id"
        case lastWakeAt = "last_wake_at"
        case runningRunId = "running_run_id"
        case runningStatus = "running_status"
        case queuedRunId = "queued_run_id"
        case activeRunId = "active_run_id"
        case activeStatus = "active_status"
        case sourceMessageId = "source_message_id"
        case isRunning = "is_running"
        case isQueued = "is_queued"
        case hasSession = "has_session"
        case phase
        case phaseLabel = "phase_label"
        case aligned
        case desync
        case chatOpenCount = "chat_open_count"
        case chatAwaitingRecv = "chat_awaiting_recv"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        handle = try c.decode(String.self, forKey: .handle)
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName) ?? handle
        agentId = try c.decodeIfPresent(String.self, forKey: .agentId)
        lastWakeAt = decodeFlexibleDouble(c, key: .lastWakeAt)
        runningRunId = try c.decodeIfPresent(String.self, forKey: .runningRunId)
        runningStatus = try c.decodeIfPresent(String.self, forKey: .runningStatus)
        queuedRunId = try c.decodeIfPresent(String.self, forKey: .queuedRunId)
        activeRunId = try c.decodeIfPresent(String.self, forKey: .activeRunId)
        activeStatus = try c.decodeIfPresent(String.self, forKey: .activeStatus)
        if let n = try? c.decodeIfPresent(Int.self, forKey: .sourceMessageId) {
            sourceMessageId = n
        } else if let s = try? c.decodeIfPresent(String.self, forKey: .sourceMessageId), let n = Int(s) {
            sourceMessageId = n
        } else {
            sourceMessageId = nil
        }
        isRunning = try c.decodeIfPresent(Bool.self, forKey: .isRunning) ?? (runningRunId != nil)
        isQueued = try c.decodeIfPresent(Bool.self, forKey: .isQueued) ?? (queuedRunId != nil)
        hasSession = try c.decodeIfPresent(Bool.self, forKey: .hasSession) ?? (agentId != nil)
        phase = try c.decodeIfPresent(String.self, forKey: .phase)
        phaseLabel = try c.decodeIfPresent(String.self, forKey: .phaseLabel)
        aligned = try c.decodeIfPresent(Bool.self, forKey: .aligned)
        desync = try c.decodeIfPresent(String.self, forKey: .desync)
        chatOpenCount = try c.decodeIfPresent(Int.self, forKey: .chatOpenCount)
        chatAwaitingRecv = try c.decodeIfPresent([FleetChatWorkItem].self, forKey: .chatAwaitingRecv) ?? []
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
    let sourceMessageId: Int?

    var id: String { runId }

    enum CodingKeys: String, CodingKey {
        case runId = "run_id"
        case status
        case targetHandle = "target_handle"
        case text
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case sourceMessageId = "source_message_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        runId = try c.decode(String.self, forKey: .runId)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        targetHandle = try c.decodeIfPresent(String.self, forKey: .targetHandle)
        text = try c.decodeIfPresent(String.self, forKey: .text)
        createdAt = decodeFlexibleDouble(c, key: .createdAt)
        updatedAt = decodeFlexibleDouble(c, key: .updatedAt)
        if let n = try? c.decodeIfPresent(Int.self, forKey: .sourceMessageId) {
            sourceMessageId = n
        } else if let s = try? c.decodeIfPresent(String.self, forKey: .sourceMessageId), let n = Int(s) {
            sourceMessageId = n
        } else {
            sourceMessageId = nil
        }
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
    let workAligned: Bool?
    let desyncHandles: [String]

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case bridgeURL = "bridge_url"
        case bridgeOk = "bridge_ok"
        case status
        case agents
        case runs
        case workAligned = "work_aligned"
        case desyncHandles = "desync_handles"
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
        workAligned = try c.decodeIfPresent(Bool.self, forKey: .workAligned)
        desyncHandles = try c.decodeIfPresent([String].self, forKey: .desyncHandles) ?? []
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
