import Foundation

enum PickupSettings {
    private static let hostKey = "pickup.server.host"
    private static let portKey = "pickup.server.port"
    private static let deviceKey = "pickup.device.id"
    private static let brainURLKey = "pickup.brain.intent.url"
    private static let feedbackParticipantKey = "pickup.feedback.participant.id"
    private static let defaultIntentKey = "pickup.feedback.default.intent.id"

    static var serverHost: String {
        get {
            let stored = UserDefaults.standard.string(forKey: hostKey)?.trimmingCharacters(in: .whitespacesAndNewlines)
            if let stored, !stored.isEmpty { return stored }
            return "192.168.3.73"
        }
        set { UserDefaults.standard.set(newValue, forKey: hostKey) }
    }

    static var serverPort: UInt16 {
        get {
            let raw = UserDefaults.standard.integer(forKey: portKey)
            return raw > 0 ? UInt16(raw) : 8791
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

    /// Must match the intent issuer participant (e.g. LivingRoom Edge id), not pickup device_id.
    static var feedbackParticipantId: String {
        get { UserDefaults.standard.string(forKey: feedbackParticipantKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: feedbackParticipantKey) }
    }

    static var defaultFeedbackIntentId: String {
        get { UserDefaults.standard.string(forKey: defaultIntentKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: defaultIntentKey) }
    }
}
