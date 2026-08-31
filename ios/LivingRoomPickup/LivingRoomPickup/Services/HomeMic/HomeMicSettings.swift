import Foundation

/// Persisted Home Mic ingest target (Mac voice.stream HAP1).
enum HomeMicSettings {
    private static let hostKey = "pickup.homeMic.host"
    private static let portKey = "pickup.homeMic.port"
    private static let energyGateKey = "pickup.homeMic.energyGate"

    static let defaultMdnsHost = "gateway.local"
    static let defaultHost = "gateway.local"
    static let defaultPort: UInt16 = 8792

    /// Discover the Mac gateway voice ingest (`_ha-gateway._tcp`) via mDNS.
    /// Persists IPv4 for TCP; UI still shows gateway.local as the identity.
    @available(iOS 13.0, *)
    static func autoDiscoverGateway() async {
        guard let gateway = await MdnsDiscovery.resolve(MdnsDiscovery.gatewayType) else { return }
        applyDiscovered(gateway)
    }

    static func applyDiscovered(_ gateway: MdnsDiscovery.Endpoint) {
        host = gateway.host
        port = gateway.voiceIngestPort
    }

    /// TCP connect host (IPv4). Empty until mDNS/probe; never use `.local` for sockets.
    static var host: String {
        get {
            let saved = UserDefaults.standard.string(forKey: hostKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if saved.isEmpty { return "" }
            if saved.lowercased().hasSuffix(".local") { return "" }
            return saved
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
