import Foundation

enum DebugReportStore {
    private static let key = "legacy.debugReportSubmitted.v1"

    static func isSubmitted(intentId: String) -> Bool {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return false }
        let set = UserDefaults.standard.array(forKey: key) as? [String] ?? []
        return set.contains(id)
    }

    static func markSubmitted(intentId: String) {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }
        var set = Set(UserDefaults.standard.array(forKey: key) as? [String] ?? [])
        set.insert(id)
        UserDefaults.standard.set(Array(set), forKey: key)
    }
}

struct DebugReportResult {
    let ok: Bool
    let issueId: Int?
    let message: String
    let error: String
}

enum LegacyDebugSnapshot {
    static func build(turn: ChatTurn) -> [String: Any] {
        [
            "app": "LivingRoomLegacy",
            "platform": "ios",
            "client_hint": ParticipantStore.clientHint,
            "brain_url": ParticipantStore.brainIntentURL,
            "heartbeat_ok": ParticipantStore.lastHeartbeatOk,
            "user_text": turn.userText,
            "intent_status": turn.status,
            "timeline_banner": turn.timeline.simpleBanner,
            "timeline_wire": turn.timeline.currentWireStatus,
        ]
    }
}
