import Foundation

enum OnlineFilter: String, CaseIterable, Identifiable {
    case online
    case offline
    case never

    var id: String { rawValue }

    var title: String {
        switch self {
        case .online: return "在线"
        case .offline: return "离线"
        case .never: return "未心跳"
        }
    }
}

struct AdminNodesResponse: Decodable {
    let ok: Bool?
    let nodes: [AdminNode]
    let error: String?

    enum CodingKeys: String, CodingKey {
        case ok, nodes, error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        nodes = try c.decodeIfPresent([AdminNode].self, forKey: .nodes) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

struct AdminPolicyResponse: Decodable {
    let ok: Bool?
    let error: String?
}

struct AdminLogsResponse: Decodable {
    let ok: Bool?
    let logs: [BrainAdminLog]
    let error: String?

    enum CodingKeys: String, CodingKey {
        case ok, logs, error
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        logs = try c.decodeIfPresent([BrainAdminLog].self, forKey: .logs) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

struct BrainAdminLog: Decodable {
    let id: Int
    let ts: Date?
    let actor: String
    let action: String
    let participantId: String
    let targetKind: String
    let targetId: String
    let result: String
    let summary: String

    enum CodingKeys: String, CodingKey {
        case id, ts, actor, action, result, summary
        case participantId = "participant_id"
        case targetKind = "target_kind"
        case targetId = "target_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let intId = try? c.decode(Int.self, forKey: .id) {
            id = intId
        } else if let text = try c.decodeIfPresent(String.self, forKey: .id), let parsed = Int(text) {
            id = parsed
        } else {
            id = 0
        }
        ts = WireTime.decode(c, key: .ts)
        actor = try c.decodeIfPresent(String.self, forKey: .actor) ?? ""
        action = try c.decodeIfPresent(String.self, forKey: .action) ?? ""
        participantId = try c.decodeIfPresent(String.self, forKey: .participantId) ?? ""
        targetKind = try c.decodeIfPresent(String.self, forKey: .targetKind) ?? ""
        targetId = try c.decodeIfPresent(String.self, forKey: .targetId) ?? ""
        result = try c.decodeIfPresent(String.self, forKey: .result) ?? ""
        summary = try c.decodeIfPresent(String.self, forKey: .summary) ?? ""
    }

    func asEntry() -> AdminLogEntry {
        let kind: AdminLogKind
        if result == "error" {
            kind = .error
        } else if action.hasPrefix("policy") {
            kind = .policy
        } else {
            kind = .policy
        }
        return AdminLogEntry(
            id: "brain-\(id)",
            at: ts ?? Date(),
            kind: kind,
            summary: summary.isEmpty ? fallbackSummary : summary
        )
    }

    private var fallbackSummary: String {
        let verb: String
        switch action {
        case "policy_enable": verb = "打开"
        case "policy_disable": verb = "关掉"
        case "policy_replace": verb = "改写"
        default: verb = "改"
        }
        let target = targetId.isEmpty ? "策略" : targetId
        let who = participantId.isEmpty ? "节点" : participantId
        if action == "policy_replace" {
            return "\(verb) \(who) 的调度策略"
        }
        return "\(verb) \(who) 的 \(target)"
    }
}

struct AdminNode: Identifiable, Decodable, Equatable {
    var id: String { participantId }

    let participantId: String
    let displayName: String
    let deviceType: String
    let location: String
    let onlineStatus: String
    let onlineStatusNote: String
    let lastActiveAt: Date?
    let registeredAt: Date?
    let roles: [AdminRole]
    let runtimeCapabilities: [AdminCapability]

    var title: String {
        let name = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? participantId : name
    }

    var shortId: String {
        let pid = participantId
        if pid.hasPrefix("edge-node-") {
            return String(pid.dropFirst("edge-node-".count))
        }
        return pid
    }

    var kindLine: String {
        let bits = [deviceType, location]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        if !bits.isEmpty {
            return bits.joined(separator: " · ")
        }
        let declared = roles.filter(\.registered).compactMap(\.shortLabel)
        return declared.isEmpty ? "未声明身份" : declared.joined(separator: " · ")
    }

    var isOnline: Bool { onlineStatus == "online" }

    var statusLabel: String {
        switch onlineStatus {
        case "online": return "在线"
        case "offline": return "离线"
        default: return "未心跳"
        }
    }

    var lastSeenLabel: String {
        guard let lastActiveAt else { return "从未心跳" }
        return "心跳 \(AdminNode.relativeLabel(since: lastActiveAt))"
    }

    var registeredLabel: String {
        guard let registeredAt else { return "注册时间未知" }
        return "注册 \(AdminNode.absoluteLabel(registeredAt))"
    }

    var declaredRoles: [AdminRole] { roles.filter(\.registered) }

    var undeclaredRoleNames: [String] {
        roles.filter { !$0.registered }.map(\.title)
    }

    enum CodingKeys: String, CodingKey {
        case participantId = "participant_id"
        case edgeId = "edge_id"
        case displayName = "display_name"
        case deviceType = "device_type"
        case location
        case onlineStatus = "online_status"
        case onlineStatusNote = "online_status_note"
        case lastActiveAt = "last_active_at"
        case registeredAt = "registered_at"
        case roles
        case runtimeCapabilities = "runtime_capabilities"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let pid = (try c.decodeIfPresent(String.self, forKey: .participantId) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let eid = (try c.decodeIfPresent(String.self, forKey: .edgeId) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        participantId = pid.isEmpty ? eid : pid
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName) ?? ""
        deviceType = try c.decodeIfPresent(String.self, forKey: .deviceType) ?? ""
        location = try c.decodeIfPresent(String.self, forKey: .location) ?? ""
        onlineStatus = try c.decodeIfPresent(String.self, forKey: .onlineStatus) ?? "never"
        onlineStatusNote = try c.decodeIfPresent(String.self, forKey: .onlineStatusNote) ?? ""
        roles = try c.decodeIfPresent([AdminRole].self, forKey: .roles) ?? []
        runtimeCapabilities = try c.decodeIfPresent([AdminCapability].self, forKey: .runtimeCapabilities) ?? []
        lastActiveAt = WireTime.decode(c, key: .lastActiveAt)
        registeredAt = WireTime.decode(c, key: .registeredAt)
    }

    static func relativeLabel(since date: Date, now: Date = Date()) -> String {
        let seconds = max(0, Int(now.timeIntervalSince(date)))
        if seconds < 10 { return "刚刚" }
        if seconds < 60 { return "\(seconds) 秒前" }
        let minutes = seconds / 60
        if minutes < 60 { return "\(minutes) 分钟前" }
        let hours = minutes / 60
        if hours < 24 { return "\(hours) 小时前" }
        let days = hours / 24
        return "\(days) 天前"
    }

    static func absoluteLabel(_ date: Date) -> String {
        WireTime.absoluteLabel(date)
    }
}

struct AdminRole: Identifiable, Decodable, Equatable {
    var id: String { roleId }
    let roleId: String
    let registered: Bool
    let enabled: Bool
    let schedulable: Bool

    var title: String {
        switch roleId {
        case "intent_source": return "发出 Intent"
        case "runtime": return "执行 Runtime"
        case "endpoint": return "呈现 Endpoint"
        case "observer": return "观察 Observer"
        default: return roleId
        }
    }

    var shortLabel: String? {
        switch roleId {
        case "intent_source": return "发出"
        case "runtime": return "执行"
        case "endpoint": return "呈现"
        case "observer": return "观察"
        default: return nil
        }
    }

    var hint: String {
        if !registered { return "节点未声明此身份" }
        if !schedulable { return "已声明，但当前不可调度" }
        switch roleId {
        case "intent_source": return "关后不能下命令"
        case "runtime": return "关后不再接计划步"
        case "endpoint": return "关后不再呈现结果"
        case "observer": return "关后不再收产品事件"
        default: return "节点已声明"
        }
    }

    enum CodingKeys: String, CodingKey {
        case roleId = "id"
        case registered
        case enabled
        case schedulable
    }
}

struct AdminCapability: Identifiable, Decodable, Equatable {
    var id: String { capabilityId }
    let capabilityId: String
    let serviceId: String
    let group: String
    let kind: String
    let description: String
    let enabled: Bool
    let schedulable: Bool

    var hint: String {
        let known: [String: String] = [
            "notify.speak": "本机播报",
            "query.content": "知识问答",
            "vision.ask": "看图问答",
            "vision.perceive": "看图理解",
            "clock.now": "报时",
            "camera.capture": "拍照",
            "light.set": "开关灯",
            "display.photo": "投一张图",
            "display.slideshow": "投一组图",
            "climate.set": "空调",
        ]
        if let hit = known[capabilityId] { return extra(hit) }
        let trimmed = description.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            let first = trimmed.split(whereSeparator: \.isNewline).first.map(String.init) ?? trimmed
            return extra(first)
        }
        let bits = [serviceId, group].filter { !$0.isEmpty }
        if bits.isEmpty { return extra("Runtime 能力") }
        return extra(bits.joined(separator: " · "))
    }

    private func extra(_ base: String) -> String {
        schedulable ? base : "\(base) · 当前不可调度"
    }

    enum CodingKeys: String, CodingKey {
        case capabilityId = "capability_id"
        case serviceId = "service_id"
        case group
        case kind
        case description
        case enabled
        case schedulable
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        capabilityId = try c.decodeIfPresent(String.self, forKey: .capabilityId) ?? ""
        serviceId = try c.decodeIfPresent(String.self, forKey: .serviceId) ?? ""
        group = try c.decodeIfPresent(String.self, forKey: .group) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? ""
        description = try c.decodeIfPresent(String.self, forKey: .description) ?? ""
        enabled = try c.decodeIfPresent(Bool.self, forKey: .enabled) ?? true
        schedulable = try c.decodeIfPresent(Bool.self, forKey: .schedulable) ?? false
    }
}

enum PolicyTargetKind: String {
    case role
    case capability
}

struct PendingDisable: Identifiable, Equatable {
    let id = UUID()
    let participantId: String
    let kind: PolicyTargetKind
    let targetId: String
    let title: String
}

enum AdminLogKind: String, Codable {
    case policy
    case connection
    case error
}

struct AdminLogEntry: Identifiable, Codable, Equatable {
    let id: String
    let at: Date
    let kind: AdminLogKind
    let summary: String

    var timeLabel: String { WireTime.absoluteLabel(at) }

    var kindLabel: String {
        switch kind {
        case .policy: return "策略"
        case .connection: return "连接"
        case .error: return "失败"
        }
    }
}

enum WireTime {
    static func decode<K: CodingKey>(_ c: KeyedDecodingContainer<K>, key: K) -> Date? {
        if let value = try? c.decode(Double.self, forKey: key) {
            return Date(timeIntervalSince1970: value)
        }
        if let value = try? c.decode(Int.self, forKey: key) {
            return Date(timeIntervalSince1970: TimeInterval(value))
        }
        if let value = try? c.decode(String.self, forKey: key), let d = Double(value) {
            return Date(timeIntervalSince1970: d)
        }
        return nil
    }

    static func absoluteLabel(_ date: Date) -> String {
        formatter.string(from: date)
    }

    private static let formatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.timeZone = TimeZone(identifier: "Asia/Shanghai")
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f
    }()
}

struct AdminIntentsResponse: Decodable {
    let ok: Bool?
    let intents: [AdminIntent]
    let error: String?
    let nextBeforeId: Int?
    let exhausted: Bool?

    enum CodingKeys: String, CodingKey {
        case ok, intents, error, exhausted
        case nextBeforeId = "next_before_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        intents = try c.decodeIfPresent([AdminIntent].self, forKey: .intents) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error)
        nextBeforeId = try c.decodeIfPresent(Int.self, forKey: .nextBeforeId)
        exhausted = try c.decodeIfPresent(Bool.self, forKey: .exhausted)
    }
}

struct AdminIntent: Identifiable, Decodable, Equatable {
    var id: Int { intentId }

    let intentId: Int
    let text: String
    let status: String
    let createdAt: Date?
    let updatedAt: Date?
    let issuerId: String
    let runtimeEdgeIds: [String]
    let msg: String
    let presentation: AdminIntentPresentation
    let executionPlan: [AdminIntentStep]
    let statusLog: [AdminIntentStatusEvent]

    var resultText: String {
        let shown = presentation.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if !shown.isEmpty { return shown }
        let fallback = msg.trimmingCharacters(in: .whitespacesAndNewlines)
        if !fallback.isEmpty { return fallback }
        return ""
    }

    var statusTitle: String {
        switch status {
        case "succeeded", "success", "completed": return "成功"
        case "failed", "error": return "失败"
        case "running", "dispatched": return "执行中"
        case "intent_parsed", "queued", "intent_received", "intent_waiting": return "排队"
        default: return status.isEmpty ? "进行中" : status
        }
    }

    var isFailure: Bool { status == "failed" || status == "error" }
    var isSuccess: Bool { status == "succeeded" || status == "success" || status == "completed" }

    var timeLabel: String {
        guard let createdAt else { return "" }
        return WireTime.absoluteLabel(createdAt)
    }

    var relativeLabel: String {
        guard let createdAt else { return "" }
        return AdminNode.relativeLabel(since: createdAt)
    }

    var issuerShort: String { Self.shortEdge(issuerId) }
    var runtimeShort: String {
        runtimeEdgeIds.map(Self.shortEdge).joined(separator: " · ")
    }

    static func shortEdge(_ raw: String) -> String {
        let id = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if id.hasPrefix("edge-node-") {
            return String(id.dropFirst("edge-node-".count))
        }
        return id
    }

    enum CodingKeys: String, CodingKey {
        case intentId = "intent_id"
        case text, status, msg, presentation
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case issuerId = "issuer_id"
        case runtimeEdgeIds = "runtime_edge_ids"
        case executionPlan = "execution_plan"
        case statusLog = "status_log"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let intId = try? c.decode(Int.self, forKey: .intentId) {
            intentId = intId
        } else if let textId = try c.decodeIfPresent(String.self, forKey: .intentId), let parsed = Int(textId) {
            intentId = parsed
        } else {
            intentId = 0
        }
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
        issuerId = try c.decodeIfPresent(String.self, forKey: .issuerId) ?? ""
        runtimeEdgeIds = try c.decodeIfPresent([String].self, forKey: .runtimeEdgeIds) ?? []
        presentation = try c.decodeIfPresent(AdminIntentPresentation.self, forKey: .presentation)
            ?? AdminIntentPresentation(type: "", text: "", from: "")
        executionPlan = try c.decodeIfPresent([AdminIntentStep].self, forKey: .executionPlan) ?? []
        statusLog = try c.decodeIfPresent([AdminIntentStatusEvent].self, forKey: .statusLog) ?? []
        createdAt = WireTime.decode(c, key: .createdAt)
        updatedAt = WireTime.decode(c, key: .updatedAt)
    }
}

struct AdminIntentPresentation: Decodable, Equatable {
    let type: String
    let text: String
    let from: String

    enum CodingKeys: String, CodingKey {
        case type, text, from
    }

    init(type: String, text: String, from: String) {
        self.type = type
        self.text = text
        self.from = from
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        from = try c.decodeIfPresent(String.self, forKey: .from) ?? ""
    }
}

struct AdminIntentStep: Identifiable, Decodable, Equatable {
    var id: String { "\(capability)|\(assignedEdgeId)|\(status)" }
    let capability: String
    let assignedEdgeId: String
    let status: String
    let msg: String
    let outputsPretty: String

    var statusTitle: String {
        switch status {
        case "succeeded", "2": return "成功"
        case "failed", "3": return "失败"
        case "running", "1": return "执行中"
        default: return status.isEmpty ? "未开始" : status
        }
    }

    enum CodingKeys: String, CodingKey {
        case capability, status, msg, outputs
        case assignedEdgeId = "assigned_edge_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        capability = try c.decodeIfPresent(String.self, forKey: .capability) ?? ""
        assignedEdgeId = try c.decodeIfPresent(String.self, forKey: .assignedEdgeId) ?? ""
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
        if let intStatus = try? c.decode(Int.self, forKey: .status) {
            status = String(intStatus)
        } else {
            status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        }
        if let value = try? c.decode(JSONValue.self, forKey: .outputs) {
            outputsPretty = value.prettyPrinted
        } else {
            outputsPretty = ""
        }
    }
}

struct AdminIntentStatusEvent: Identifiable, Decodable, Equatable {
    var id: String { "\(status)|\(ts?.timeIntervalSince1970 ?? 0)|\(msg)" }
    let status: String
    let ts: Date?
    let msg: String

    enum CodingKeys: String, CodingKey {
        case status, ts, msg
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
        if let ms = try? c.decode(Double.self, forKey: .ts), ms > 10_000_000_000 {
            ts = Date(timeIntervalSince1970: ms / 1000)
        } else {
            ts = WireTime.decode(c, key: .ts)
        }
    }
}

enum JSONValue: Decodable, Equatable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
            return
        }
        if let v = try? c.decode(Bool.self) {
            self = .bool(v)
            return
        }
        if let v = try? c.decode(Int.self) {
            self = .int(v)
            return
        }
        if let v = try? c.decode(Double.self) {
            self = .double(v)
            return
        }
        if let v = try? c.decode(String.self) {
            self = .string(v)
            return
        }
        if let v = try? c.decode([String: JSONValue].self) {
            self = .object(v)
            return
        }
        if let v = try? c.decode([JSONValue].self) {
            self = .array(v)
            return
        }
        self = .null
    }

    var jsonObject: Any {
        switch self {
        case .string(let v): return v
        case .int(let v): return v
        case .double(let v): return v
        case .bool(let v): return v
        case .object(let v): return v.mapValues(\.jsonObject)
        case .array(let v): return v.map(\.jsonObject)
        case .null: return NSNull()
        }
    }

    var prettyPrinted: String {
        let obj = jsonObject
        if obj is NSNull { return "" }
        guard JSONSerialization.isValidJSONObject(obj),
              let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]),
              let text = String(data: data, encoding: .utf8) else {
            return String(describing: obj)
        }
        return text
    }
}

struct AdminDevTasksResponse: Decodable {
    let ok: Bool?
    let tasks: [AdminDevTask]
    let error: String?
    let nextBeforeId: Int?
    let exhausted: Bool?

    enum CodingKeys: String, CodingKey {
        case ok, tasks, error, exhausted
        case nextBeforeId = "next_before_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        tasks = try c.decodeIfPresent([AdminDevTask].self, forKey: .tasks) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error)
        nextBeforeId = try c.decodeIfPresent(Int.self, forKey: .nextBeforeId)
        exhausted = try c.decodeIfPresent(Bool.self, forKey: .exhausted)
    }
}

struct AdminDevTask: Identifiable, Decodable, Equatable {
    var id: Int { intentId }

    let intentId: Int
    let text: String
    let status: String
    let createdAt: Date?
    let resultText: String
    let msg: String
    let bridgeRunId: String
    let bridgeStatus: String
    let events: [AdminDevEvent]
    let statusLog: [AdminIntentStatusEvent]

    var statusTitle: String {
        switch status {
        case "succeeded", "success", "completed": return "完成"
        case "failed", "error": return "失败"
        case "running", "dispatched": return "执行中"
        case "intent_parsed", "queued", "intent_received", "intent_waiting": return "排队"
        default: return status.isEmpty ? "进行中" : status
        }
    }

    var isTerminal: Bool {
        status == "succeeded" || status == "failed" || status == "error"
    }

    var isActive: Bool { !isTerminal }

    var timeLabel: String {
        guard let createdAt else { return "" }
        return WireTime.absoluteLabel(createdAt)
    }

    var relativeLabel: String {
        guard let createdAt else { return "" }
        return AdminNode.relativeLabel(since: createdAt)
    }

    var displayResult: String {
        let shown = resultText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !shown.isEmpty { return shown }
        let fallback = msg.trimmingCharacters(in: .whitespacesAndNewlines)
        if !fallback.isEmpty { return fallback }
        if let last = events.last(where: { !$0.text.isEmpty }) {
            return last.text
        }
        return ""
    }

    enum CodingKeys: String, CodingKey {
        case intentId = "intent_id"
        case text, status, msg
        case createdAt = "created_at"
        case resultText = "result_text"
        case devTask = "dev_task"
        case statusLog = "status_log"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let intId = try? c.decode(Int.self, forKey: .intentId) {
            intentId = intId
        } else if let textId = try c.decodeIfPresent(String.self, forKey: .intentId), let parsed = Int(textId) {
            intentId = parsed
        } else {
            intentId = 0
        }
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
        resultText = try c.decodeIfPresent(String.self, forKey: .resultText) ?? ""
        createdAt = WireTime.decode(c, key: .createdAt)
        statusLog = try c.decodeIfPresent([AdminIntentStatusEvent].self, forKey: .statusLog) ?? []
        let dev = try c.decodeIfPresent(AdminDevTaskMeta.self, forKey: .devTask) ?? AdminDevTaskMeta()
        bridgeRunId = dev.bridgeRunId
        bridgeStatus = dev.bridgeStatus
        events = dev.events
    }
}

private struct AdminDevTaskMeta: Decodable {
    let bridgeRunId: String
    let bridgeStatus: String
    let events: [AdminDevEvent]

    enum CodingKeys: String, CodingKey {
        case bridgeRunId = "bridge_run_id"
        case bridgeStatus = "bridge_status"
        case events
    }

    init() {
        bridgeRunId = ""
        bridgeStatus = ""
        events = []
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bridgeRunId = try c.decodeIfPresent(String.self, forKey: .bridgeRunId) ?? ""
        bridgeStatus = try c.decodeIfPresent(String.self, forKey: .bridgeStatus) ?? ""
        events = try c.decodeIfPresent([AdminDevEvent].self, forKey: .events) ?? []
    }
}

struct AdminDevEvent: Identifiable, Decodable, Equatable {
    var id: String { "\(type)|\(text)|\(ts?.timeIntervalSince1970 ?? 0)" }
    let type: String
    let text: String
    let ts: Date?

    enum CodingKeys: String, CodingKey {
        case type, text, ts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        if let value = try? c.decode(Double.self, forKey: .ts), value > 10_000_000_000 {
            ts = Date(timeIntervalSince1970: value / 1000)
        } else {
            ts = WireTime.decode(c, key: .ts)
        }
    }
}
