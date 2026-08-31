import Foundation

/// Persisted Home Mic ingest target (Mac voice.stream HAP1).
enum HomeMicSettings {
    private static let hostKey = "pickup.homeMic.host"
    private static let portKey = "pickup.homeMic.port"
    private static let energyGateKey = "pickup.homeMic.energyGate"

    static let defaultHost = "192.168.3.84"
    static let defaultPort: UInt16 = 8792

    /// Discover the Mac gateway voice ingest (`_ha-gateway._tcp`) via mDNS so the
    /// app stops depending on a fixed LAN IP.
    @available(iOS 13.0, *)
    static func autoDiscoverGateway() async {
        guard let gateway = await MdnsDiscovery.resolve(MdnsDiscovery.gatewayType) else { return }
        host = gateway.host
    }

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
