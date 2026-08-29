import Foundation

enum PickupSettings {
    private static let hostKey = "pickup.server.host"
    private static let portKey = "pickup.server.port"
    private static let deviceKey = "pickup.device.id"
    private static let brainURLKey = "pickup.brain.intent.url"
    private static let feedbackParticipantKey = "pickup.feedback.participant.id"
    private static let energyGateKey = "pickup.energy.gate.enabled"

    static var serverHost: String {
        get {
            let stored = UserDefaults.standard.string(forKey: hostKey)?.trimmingCharacters(in: .whitespacesAndNewlines)
            if let stored, !stored.isEmpty { return stored }
            // Living-room Mac LAN IP (voice.stream HAP1 ingest).
            return "192.168.3.73"
        }
        set { UserDefaults.standard.set(newValue, forKey: hostKey) }
    }

    /// Mac voice.stream Home Mic ingest (HAP1), not Brain.
    static var serverPort: UInt16 {
        get {
            let raw = UserDefaults.standard.integer(forKey: portKey)
            // Legacy default pointed at Brain :8791 — migrate to Mac ingest :8792.
            if raw == 8791 {
                UserDefaults.standard.set(8792, forKey: portKey)
                return 8792
            }
            return raw > 0 ? UInt16(raw) : 8792
        }
        set { UserDefaults.standard.set(Int(newValue), forKey: portKey) }
    }

    static var deviceId: String {
        get {
            if let stored = UserDefaults.standard.string(forKey: deviceKey), !stored.isEmpty {
                return stored
            }
            let generated = "pickup-iphone-\(UUID().uuidString.prefix(8))"
            UserDefaults.standard.set(generated, forKey: deviceKey)
            return generated
        }
        set { UserDefaults.standard.set(newValue, forKey: deviceKey) }
    }

    /// Brain intent API base URL (for POST /api/v1/debug/report), separate from TCP pickup host.
    static var brainIntentURL: String {
        get {
            let stored = UserDefaults.standard.string(forKey: brainURLKey)?.trimmingCharacters(in: .whitespacesAndNewlines)
            if let stored, !stored.isEmpty { return stored }
            return "http://192.168.3.73:9527/api/v1/intent"
        }
        set { UserDefaults.standard.set(newValue, forKey: brainURLKey) }
    }

    /// Optional override; empty → use deviceId for intent-less Home Mic feedback.
    static var feedbackParticipantId: String {
        get { UserDefaults.standard.string(forKey: feedbackParticipantKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: feedbackParticipantKey) }
    }

    /// iPhone Runtime participant_id (same as LivingRoomEdge heartbeat registration).
    /// Prefer Settings override; otherwise fall back to deviceId until Edge shares via App Group.
    static var edgeParticipantId: String {
        let configured = feedbackParticipantId.trimmingCharacters(in: .whitespacesAndNewlines)
        return configured.isEmpty ? deviceId : configured
    }

    /// Drop near-silence before HAP1 send (pre-roll + hangover). Default on.
    static var energyGateEnabled: Bool {
        get {
            if UserDefaults.standard.object(forKey: energyGateKey) == nil { return true }
            return UserDefaults.standard.bool(forKey: energyGateKey)
        }
        set { UserDefaults.standard.set(newValue, forKey: energyGateKey) }
    }
}
