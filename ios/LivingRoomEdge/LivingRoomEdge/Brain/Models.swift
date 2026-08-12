import Foundation

// MARK: - Service / Capability (wire)

struct SchemaField: Codable, Hashable {
    let type: String
    let required: Bool
    let description: String

    init(type: String, required: Bool = false, description: String = "") {
        self.type = type
        self.required = required
        self.description = description
    }
}

struct CapabilityDescriptor: Codable, Hashable, Identifiable {
    var id: String { capabilityId }
    let capabilityId: String
    let description: String
    let inputSchema: [String: SchemaField]
    let outputSchema: [String: SchemaField]

    enum CodingKeys: String, CodingKey {
        case capabilityId = "capability_id"
        case description
        case inputSchema = "input_schema"
        case outputSchema = "output_schema"
    }

    init(
        capabilityId: String,
        description: String,
        inputSchema: [String: SchemaField] = [:],
        outputSchema: [String: SchemaField] = [:]
    ) {
        self.capabilityId = capabilityId
        self.description = description
        self.inputSchema = inputSchema
        self.outputSchema = outputSchema
    }
}

struct ServiceDescriptor: Codable, Hashable, Identifiable {
    var id: String { serviceId }
    let serviceId: String
    let version: String
    let displayName: String
    let group: String
    let capabilities: [CapabilityDescriptor]

    enum CodingKeys: String, CodingKey {
        case serviceId = "service_id"
        case version
        case displayName = "display_name"
        case group
        case capabilities
    }

    init(
        serviceId: String,
        version: String,
        displayName: String,
        group: String,
        capabilities: [CapabilityDescriptor]
    ) {
        self.serviceId = serviceId
        self.version = version
        self.displayName = displayName
        self.group = group
        self.capabilities = capabilities
    }
}

enum OnFailurePolicy: String, Codable {
    case abort
    case continuePolicy = "continue"
}

struct PlanStep: Codable, Identifiable {
    var id: String { stepId }
    let stepId: String
    let skillId: String
    let action: String
    let params: [String: String]
    let onFailure: OnFailurePolicy

    init(
        stepId: String,
        skillId: String,
        action: String,
        params: [String: String] = [:],
        onFailure: OnFailurePolicy = .abort
    ) {
        self.stepId = stepId
        self.skillId = skillId
        self.action = action
        self.params = params
        self.onFailure = onFailure
    }
}

struct Plan: Codable, Identifiable {
    var id: String { planId }
    let planId: String
    let steps: [PlanStep]
    let createdAt: TimeInterval

    init(planId: String, steps: [PlanStep], createdAt: TimeInterval = Date().timeIntervalSince1970) {
        self.planId = planId
        self.steps = steps
        self.createdAt = createdAt
    }
}

enum StepStatus: String, Codable {
    case ok
    case error
    case skipped
}

struct ExecutionReport: Codable, Identifiable {
    var id: String { "\(planId)-\(stepId)-\(finishedAt)" }
    let planId: String
    let stepId: String
    let status: StepStatus
    let message: String?
    let finishedAt: TimeInterval

    init(
        planId: String,
        stepId: String,
        status: StepStatus,
        message: String? = nil,
        finishedAt: TimeInterval = Date().timeIntervalSince1970
    ) {
        self.planId = planId
        self.stepId = stepId
        self.status = status
        self.message = message
        self.finishedAt = finishedAt
    }
}

struct EdgeRegistration: Codable {
    let edgeId: String
    let services: [ServiceDescriptor]
    let registeredAt: TimeInterval

    init(
        edgeId: String,
        services: [ServiceDescriptor],
        registeredAt: TimeInterval = Date().timeIntervalSince1970
    ) {
        self.edgeId = edgeId
        self.services = services
        self.registeredAt = registeredAt
    }
}

// MARK: - Edge node info report (identity / device / online / health / services)

enum EdgeDeviceType: String, Codable, CaseIterable {
    case iphone
    case ipad
    case mac
    case androidTv = "android_tv"
    case xiaomiTv = "xiaomi_tv"
    case chromecast
    case android
    case other
}

enum EdgeOnlineStatus: String, Codable {
    case online
    case offline
}

enum EdgeHealthStatus: String, Codable {
    case healthy
    case degraded
    case unhealthy
    case unknown
}

struct EdgeHealthSnapshot: Codable, Equatable {
    let status: EdgeHealthStatus
    let summary: String
    /// Optional subsystem notes, e.g. `gopro` → "Wi‑Fi unknown".
    let details: [String: String]

    init(
        status: EdgeHealthStatus = .unknown,
        summary: String = "unknown",
        details: [String: String] = [:]
    ) {
        self.status = status
        self.summary = summary
        self.details = details
    }
}

/// Full edge-node snapshot reported on register / heartbeat / offline.
struct EdgeNodeInfo: Codable, Equatable {
    let edgeId: String
    let displayName: String
    let deviceType: EdgeDeviceType
    let room: String
    let onlineStatus: EdgeOnlineStatus
    let health: EdgeHealthSnapshot
    let services: [ServiceDescriptor]
    let appVersion: String?
    let reportedAt: TimeInterval
    /// Unix epoch milliseconds — used by Brain for clock skew checks.
    let clientTimeMs: Int64

    enum CodingKeys: String, CodingKey {
        case edgeId = "edge_id"
        case displayName = "display_name"
        case deviceType = "device_type"
        case room
        case onlineStatus = "online_status"
        case health
        case services
        case appVersion = "app_version"
        case reportedAt = "reported_at"
        case clientTimeMs = "client_time_ms"
    }

    init(
        edgeId: String,
        displayName: String,
        deviceType: EdgeDeviceType,
        room: String = "living-room",
        onlineStatus: EdgeOnlineStatus,
        health: EdgeHealthSnapshot,
        services: [ServiceDescriptor],
        appVersion: String? = nil,
        reportedAt: TimeInterval = Date().timeIntervalSince1970,
        clientTimeMs: Int64 = Int64(Date().timeIntervalSince1970 * 1000)
    ) {
        self.edgeId = edgeId
        self.displayName = displayName
        self.deviceType = deviceType
        self.room = room
        self.onlineStatus = onlineStatus
        self.health = health
        self.services = services
        self.appVersion = appVersion
        self.reportedAt = reportedAt
        self.clientTimeMs = clientTimeMs
    }
}

/// Static identity for an edge node (client-side profile before Brain assigns edgeId).
struct EdgeIdentity: Equatable {
    /// Local preferred id / hint sent at register time (Brain may assign a different edgeId).
    let clientHint: String
    let displayName: String
    let deviceType: EdgeDeviceType
    let room: String
    let appVersion: String?

    /// Backward-compatible alias for `clientHint`.
    var edgeId: String { clientHint }

    init(
        edgeId: String,
        displayName: String,
        deviceType: EdgeDeviceType,
        room: String = "living-room",
        appVersion: String? = nil
    ) {
        self.clientHint = edgeId
        self.displayName = displayName
        self.deviceType = deviceType
        self.room = room
        self.appVersion = appVersion
    }
}

/// First-contact register request (no trusted edge_id yet).
struct EdgeRegisterRequest: Codable {
    let clientHint: String?
    let displayName: String
    let deviceType: EdgeDeviceType
    let room: String
    let services: [ServiceDescriptor]
    let appVersion: String?
    let reportedAt: TimeInterval

    enum CodingKeys: String, CodingKey {
        case clientHint = "client_hint"
        case displayName = "display_name"
        case deviceType = "device_type"
        case room
        case services
        case appVersion = "app_version"
        case reportedAt = "reported_at"
    }

    init(
        clientHint: String?,
        displayName: String,
        deviceType: EdgeDeviceType,
        room: String,
        services: [ServiceDescriptor],
        appVersion: String? = nil,
        reportedAt: TimeInterval = Date().timeIntervalSince1970
    ) {
        self.clientHint = clientHint
        self.displayName = displayName
        self.deviceType = deviceType
        self.room = room
        self.services = services
        self.appVersion = appVersion
        self.reportedAt = reportedAt
    }
}

/// Brain register response:
/// `{ "ok": bool, "ts": number, "status": "approved"|"rejected", "edge_id": string, "message": string }`
struct EdgeRegisterResponse: Codable, Equatable {
    let ok: Bool
    let ts: TimeInterval?
    let status: String
    /// Mapped from JSON key `edge_id` only.
    let edgeId: String
    let message: String

    var isApproved: Bool {
        ok
            && status.lowercased() == "approved"
            && !edgeId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var debugSummary: String {
        "ok=\(ok) status=\(status) edge_id=\(edgeId.isEmpty ? "(empty)" : edgeId) message=\(message)"
    }

    enum CodingKeys: String, CodingKey {
        case ok
        case ts
        case status
        case edge_id
        case message
    }

    init(
        ok: Bool,
        ts: TimeInterval? = Date().timeIntervalSince1970,
        status: String,
        edgeId: String,
        message: String = ""
    ) {
        self.ok = ok
        self.ts = ts
        self.status = status
        self.edgeId = edgeId
        self.message = message
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok) ?? false
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        message = try c.decodeIfPresent(String.self, forKey: .message) ?? ""
        if let t = try c.decodeIfPresent(Double.self, forKey: .ts) {
            ts = t
        } else if let i = try c.decodeIfPresent(Int.self, forKey: .ts) {
            ts = TimeInterval(i)
        } else {
            ts = nil
        }
        edgeId = (try c.decodeIfPresent(String.self, forKey: .edge_id) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(ok, forKey: .ok)
        try c.encodeIfPresent(ts, forKey: .ts)
        try c.encode(status, forKey: .status)
        try c.encode(edgeId, forKey: .edge_id)
        try c.encode(message, forKey: .message)
    }
}
