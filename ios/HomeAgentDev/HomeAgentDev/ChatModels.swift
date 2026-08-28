import Foundation

/// Reaction icons shown in the long-press float. Extend with more cases later.
enum ChatReactionKind: String, CaseIterable, Identifiable {
    case ok

    var id: String { rawValue }

    var emoji: String {
        switch self {
        case .ok: return "👌"
        }
    }

    var title: String {
        switch self {
        case .ok: return "知道了"
        }
    }
}

struct ChatMessageAck: Decodable, Equatable, Hashable {
    let handle: String
    let ackType: String
    let timestampLabel: String

    enum CodingKeys: String, CodingKey {
        case handle
        case ackType = "ack_type"
        case timestampLabel = "ts"
    }

    var badgeLabel: String {
        let key = ackType.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if key == "got" { return "GET" }
        return "OK"
    }

    var isBossHandle: Bool {
        let h = handle.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return h == "boss" || h == "owner" || h == "user"
    }

    /// Name shown after the shared OK marker (boss →「你」).
    var participantLabel: String {
        if isBossHandle { return "你" }
        let h = handle.trimmingCharacters(in: .whitespacesAndNewlines)
        return h.isEmpty ? "?" : h
    }
}

struct AgentChatMessage: Identifiable, Decodable, Equatable {
    let id: Int
    let fromHandle: String
    let body: String
    let kind: String
    let replyToId: Int?
    let createdAt: Double?
    let timestampLabel: String
    let mentions: [String]
    let audience: [String]
    let recalled: Bool
    let isPending: Bool
    let acks: [ChatMessageAck]

    enum CodingKeys: String, CodingKey {
        case id
        case fromHandle = "from"
        case body
        case kind
        case replyToId = "reply_to_id"
        case createdAt = "created_at"
        case timestampLabel = "ts"
        case mentions
        case audience
        case recalled
        case acks
    }

    init(
        id: Int,
        fromHandle: String,
        body: String,
        kind: String = "chat",
        replyToId: Int? = nil,
        createdAt: Double? = nil,
        timestampLabel: String = "",
        mentions: [String] = [],
        audience: [String] = [],
        recalled: Bool = false,
        isPending: Bool = false,
        acks: [ChatMessageAck] = []
    ) {
        self.id = id
        self.fromHandle = fromHandle
        self.body = body
        self.kind = kind
        self.replyToId = replyToId
        self.createdAt = createdAt
        self.timestampLabel = timestampLabel
        self.mentions = mentions
        self.audience = audience
        self.recalled = recalled
        self.isPending = isPending
        self.acks = acks
    }

    static func pendingBoss(body: String, id: Int) -> AgentChatMessage {
        AgentChatMessage(
            id: id,
            fromHandle: "boss",
            body: body,
            createdAt: Date().timeIntervalSince1970,
            isPending: true
        )
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let intId = try? c.decode(Int.self, forKey: .id) {
            id = intId
        } else if let strId = try? c.decode(String.self, forKey: .id), let intId = Int(strId) {
            id = intId
        } else {
            id = 0
        }
        fromHandle = try c.decodeIfPresent(String.self, forKey: .fromHandle) ?? ""
        body = try c.decodeIfPresent(String.self, forKey: .body) ?? ""
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "chat"
        replyToId = try c.decodeIfPresent(Int.self, forKey: .replyToId)
        if let v = try? c.decode(Double.self, forKey: .createdAt) {
            createdAt = v
        } else if let s = try? c.decode(String.self, forKey: .createdAt), let v = Double(s) {
            createdAt = v
        } else {
            createdAt = nil
        }
        timestampLabel = try c.decodeIfPresent(String.self, forKey: .timestampLabel) ?? ""
        mentions = try c.decodeIfPresent([String].self, forKey: .mentions) ?? []
        audience = try c.decodeIfPresent([String].self, forKey: .audience) ?? []
        recalled = try c.decodeIfPresent(Bool.self, forKey: .recalled) ?? false
        acks = try c.decodeIfPresent([ChatMessageAck].self, forKey: .acks) ?? []
        isPending = false
    }

    var isFromBoss: Bool {
        let key = fromHandle.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return key == "boss" || key == "owner" || key == "user"
    }

    var isComplete: Bool {
        kind.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "complete"
    }

    var bossHasAcked: Bool {
        acks.contains(where: \.isBossHandle)
    }

    /// Shared reaction: one OK marker + everyone who acked (empty → marker hidden).
    var sharedAckParticipantLabels: [String] {
        acks.map(\.participantLabel)
    }

    var senderLabel: String {
        if isFromBoss { return "你" }
        let handle = fromHandle.trimmingCharacters(in: .whitespacesAndNewlines)
        return handle.isEmpty ? "?" : "@\(handle)"
    }

    var audienceLabel: String {
        if audience.isEmpty {
            return isFromBoss ? "仅自己可见的笔记" : ""
        }
        if audience.contains("all") {
            return "@all"
        }
        return audience.map { "@\($0)" }.joined(separator: " ")
    }

    var timeLabel: String {
        if !timestampLabel.isEmpty { return timestampLabel }
        guard let createdAt else { return "" }
        return WireTime.absoluteLabel(Date(timeIntervalSince1970: createdAt))
    }
}

struct AgentChatSnapshot: Decodable, Equatable {
    let ok: Bool?
    let error: String?
    let chatURL: String?
    let chatOk: Bool?
    let messages: [AgentChatMessage]
    let ackPatches: [AgentChatAckPatch]
    let latestAckAt: Double?

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case chatURL = "chat_url"
        case chatOk = "chat_ok"
        case messages
        case ackPatches = "ack_patches"
        case latestAckAt = "latest_ack_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        error = try c.decodeIfPresent(String.self, forKey: .error)
        chatURL = try c.decodeIfPresent(String.self, forKey: .chatURL)
        chatOk = try c.decodeIfPresent(Bool.self, forKey: .chatOk)
        if let rows = try? c.decode([AgentChatMessage].self, forKey: .messages) {
            messages = rows
        } else if var nested = try? c.nestedUnkeyedContainer(forKey: .messages) {
            var rows: [AgentChatMessage] = []
            while !nested.isAtEnd {
                if let row = try? nested.decode(AgentChatMessage.self) {
                    rows.append(row)
                } else {
                    _ = try? nested.decode(AgentChatSkipped.self)
                }
            }
            messages = rows
        } else {
            messages = []
        }
        ackPatches = try c.decodeIfPresent([AgentChatAckPatch].self, forKey: .ackPatches) ?? []
        if let v = try? c.decode(Double.self, forKey: .latestAckAt) {
            latestAckAt = v
        } else if let s = try? c.decode(String.self, forKey: .latestAckAt), let v = Double(s) {
            latestAckAt = v
        } else {
            latestAckAt = nil
        }
    }
}

struct AgentChatAckPatch: Decodable, Equatable {
    let id: Int
    let acks: [ChatMessageAck]
}

private struct AgentChatSkipped: Decodable {}

struct AgentChatSendResponse: Decodable {
    let ok: Bool?
    let error: String?
    let message: AgentChatMessage?

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case message
    }
}

struct AgentChatPromoteResponse: Decodable {
    let ok: Bool?
    let error: String?
    let taskId: Int?

    enum CodingKeys: String, CodingKey {
        case ok
        case error
        case taskId = "task_id"
    }
}
