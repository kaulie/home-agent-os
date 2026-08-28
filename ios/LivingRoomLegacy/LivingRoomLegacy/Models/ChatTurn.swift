import Foundation

struct ChatTurn {
    let id: String
    var userText: String
    var intentId: String
    var status: String
    var assistantText: String
    var isWaiting: Bool
    var timeline: IntentTimeline

    init(
        id: String = UUID().uuidString,
        userText: String,
        intentId: String = "",
        status: String = "",
        assistantText: String = "",
        isWaiting: Bool = false,
        timeline: IntentTimeline = IntentTimeline.posting()
    ) {
        self.id = id
        self.userText = userText
        self.intentId = intentId
        self.status = status
        self.assistantText = assistantText
        self.isWaiting = isWaiting
        self.timeline = timeline
    }

    var isTerminal: Bool {
        let s = status.lowercased()
        return s == "succeeded" || s == "failed" || s == "error" || s == "cancelled"
    }
}

struct IntentStatusLogEntry {
    let status: String
    let ts: Double?
}

struct IntentDetailSnapshot {
    let intentId: String
    let status: String
    let displayText: String
    let statusLog: [IntentStatusLogEntry]
    let errorMessage: String

    static func parse(data: Data) -> IntentDetailSnapshot? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let root = (obj["intent"] as? [String: Any]) ?? obj
        let intentId = stringId(root["intent_id"] ?? root["id"])
        guard !intentId.isEmpty else { return nil }
        let status = (root["status"] as? String ?? root["intent_status"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let display = extractDisplayText(from: root)
        let log = parseStatusLog(root["status_log"] ?? root["steps"])
        let err = (root["msg"] as? String ?? root["error"] as? String ?? root["message"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return IntentDetailSnapshot(
            intentId: intentId,
            status: status,
            displayText: display,
            statusLog: log,
            errorMessage: err
        )
    }

    static func parseIntentPost(data: Data) -> IntentDetailSnapshot? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let intentId = stringId(obj["intent_id"] ?? obj["id"])
        guard !intentId.isEmpty else { return nil }
        let status = (obj["status"] as? String ?? obj["intent_status"] as? String ?? "intent_received")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return IntentDetailSnapshot(
            intentId: intentId,
            status: status,
            displayText: extractDisplayText(from: obj),
            statusLog: [IntentStatusLogEntry(status: status, ts: nil)],
            errorMessage: ""
        )
    }

    private static func parseStatusLog(_ value: Any?) -> [IntentStatusLogEntry] {
        guard let arr = value as? [[String: Any]] else { return [] }
        return arr.compactMap { item in
            let status = (item["status"] as? String ?? item["intent_status"] as? String ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            guard !status.isEmpty else { return nil }
            let ts = (item["ts"] as? Double) ?? (item["at"] as? Double)
            return IntentStatusLogEntry(status: status, ts: ts)
        }
    }

    private static func extractDisplayText(from root: [String: Any]) -> String {
        if let presentation = root["presentation"] as? [String: Any] {
            if let text = presentation["text"] as? String, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return text.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            if let summary = presentation["summary"] as? String, !summary.isEmpty {
                return summary
            }
        }
        if let text = root["text"] as? String, !text.isEmpty {
            return text
        }
        let msg = (root["msg"] as? String ?? root["error"] as? String ?? root["message"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return msg
    }

    private static func stringId(_ value: Any?) -> String {
        if let n = value as? Int { return String(n) }
        if let n = value as? NSNumber { return n.stringValue }
        if let s = value as? String { return s.trimmingCharacters(in: .whitespacesAndNewlines) }
        return ""
    }
}
