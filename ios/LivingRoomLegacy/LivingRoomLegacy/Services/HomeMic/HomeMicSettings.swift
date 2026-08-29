import Foundation

/// Persisted Home Mic ingest target (Mac voice.stream HAP1). Not video ingest (:8790).
enum HomeMicSettings {
    private static let hostKey = "legacy.homeMic.host"
    private static let portKey = "legacy.homeMic.port"
    private static let energyGateKey = "legacy.homeMic.energyGate"

    static let defaultHost = "192.168.3.73"
    static let defaultPort: UInt16 = 8792

    static var host: String {
        get {
            let saved = UserDefaults.standard.string(forKey: hostKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return saved.isEmpty ? defaultHost : saved
        }
        set {
            UserDefaults.standard.set(
                newValue.trimmingCharacters(in: .whitespacesAndNewlines),
                forKey: hostKey
            )
        }
    }

    static var port: UInt16 {
        get {
            let raw = UserDefaults.standard.object(forKey: portKey) as? Int
            guard let raw = raw, raw > 0, raw <= 65_535 else { return defaultPort }
            return UInt16(raw)
        }
        set {
            UserDefaults.standard.set(Int(newValue), forKey: portKey)
        }
    }

    /// When true, silence is not uploaded (client energy gate). Default on.
    static var energyGateEnabled: Bool {
        get {
            if UserDefaults.standard.object(forKey: energyGateKey) == nil {
                return true
            }
            return UserDefaults.standard.bool(forKey: energyGateKey)
        }
        set {
            UserDefaults.standard.set(newValue, forKey: energyGateKey)
        }
    }
}
