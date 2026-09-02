import Foundation

/// Persisted Home Mic ingest target (Mac voice.stream HAP1).
enum HomeMicSettings {
    private static let hostKey = "pickup.homeMic.host"
    private static let portKey = "pickup.homeMic.port"
    private static let energyGateKey = "pickup.homeMic.energyGate"

    static let defaultMdnsHost = "gateway.local"
    static let defaultPort: UInt16 = 8792

    /// Browse `_ha-gateway._tcp`, take A-record IPv4, persist for TCP (never `.local`).
    static func autoDiscoverGateway(completion: @escaping (MdnsDiscovery.Endpoint?) -> Void) {
        MdnsDiscovery.resolveGatewayForAutoDiscover(mdnsTimeout: 8) { gateway in
            if let gateway, MdnsDiscovery.refuseNonIPv4TCP(gateway.host) == nil {
                applyDiscovered(gateway)
                DiscoveryDebugLog.shared.log(
                    "saved gateway TCP \(gateway.host):\(gateway.voiceIngestPort)",
                    category: "connect"
                )
                completion(gateway)
            } else {
                DiscoveryDebugLog.shared.log(
                    "discover result not applied host=\(gateway?.host ?? "nil")",
                    category: "connect"
                )
                completion(nil)
            }
        }
    }

    static func applyDiscovered(_ gateway: MdnsDiscovery.Endpoint) {
        guard MdnsDiscovery.refuseNonIPv4TCP(gateway.host) == nil else { return }
        host = gateway.host
        port = gateway.voiceIngestPort
    }

    /// TCP connect host (IPv4). Empty until mDNS/probe; never use `.local` for sockets.
    static var host: String {
        get {
            let saved = UserDefaults.standard.string(forKey: hostKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if MdnsDiscovery.refuseNonIPv4TCP(saved) == nil { return saved }
            return ""
        }
        set {
            let trimmed = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            if MdnsDiscovery.refuseNonIPv4TCP(trimmed) == nil {
                UserDefaults.standard.set(trimmed, forKey: hostKey)
            } else {
                UserDefaults.standard.set("", forKey: hostKey)
            }
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
