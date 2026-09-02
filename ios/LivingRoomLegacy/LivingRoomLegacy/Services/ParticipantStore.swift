import Foundation
import UIKit

enum ParticipantStore {
    private static let hintKey = "legacy.clientHint"
    private static let idKey = "legacy.participantId"
    private static let brainURLKey = "legacy.brainIntentURL"
    private static let endpointKey = "legacy.brainEndpoint"
    private static let endpointUserSetKey = "legacy.brainEndpointUserSet"
    private static let registeredAtKey = "legacy.registeredAt"
    private static let lastHeartbeatOkKey = "legacy.lastHeartbeatOk"
    private static let lastHeartbeatAtKey = "legacy.lastHeartbeatAt"
    private static let macIngestKey = "legacy.macIngestURL"
    private static let homeBrainURLKey = "legacy.homeBrainIntentURL"
    private static let homeBrainResolvedKey = "legacy.homeBrainResolvedIntentURL"
    private static let macIngestResolvedKey = "legacy.macIngestResolvedURL"

    static let defaultHomeBrainIntentURL = BrainEndpoint.defaultHomeIntentURL
    static let defaultBrainIntentURL = BrainEndpoint.defaultHomeIntentURL
    /// Mac Edge video-live ingest is addressed by its well-known mDNS hostname
    /// (`_ha-gateway._tcp` → `gateway.local`), not a fixed LAN IP.
    static let defaultMacIngestURL = "http://gateway.local:8790"

    /// URL used for API calls (set after a successful register).
    private(set) static var activeIntentURL: String = BrainEndpoint.defaultHomeIntentURL

    static var clientHint: String {
        if let saved = UserDefaults.standard.string(forKey: hintKey), !saved.isEmpty {
            return saved
        }
        let suffix = UIDevice.current.identifierForVendor?.uuidString.prefix(8)
            ?? UUID().uuidString.prefix(8)
        let hint = "living-room-legacy-iphone-\(suffix)"
        UserDefaults.standard.set(hint, forKey: hintKey)
        return hint
    }

    static var participantId: String {
        get { UserDefaults.standard.string(forKey: idKey) ?? "" }
        set {
            let next = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            UserDefaults.standard.set(next, forKey: idKey)
            if next.isEmpty {
                UserDefaults.standard.removeObject(forKey: registeredAtKey)
            }
        }
    }

    /// Parent-selected target. Default 家里 unless user tapped 外面.
    static var preferredEndpoint: BrainEndpoint {
        get {
            guard UserDefaults.standard.bool(forKey: endpointUserSetKey) else {
                return .home
            }
            let raw = UserDefaults.standard.integer(forKey: endpointKey)
            return BrainEndpoint(rawValue: raw) ?? .home
        }
        set {
            UserDefaults.standard.set(true, forKey: endpointUserSetKey)
            UserDefaults.standard.set(newValue.rawValue, forKey: endpointKey)
            UserDefaults.standard.set(newValue.intentURL, forKey: brainURLKey)
        }
    }

    static var brainIntentURL: String {
        activeIntentURL
    }

    static func setActiveIntentURL(_ url: String) {
        activeIntentURL = BrainURL.normalizeIntentURL(url)
    }

    static var lastHeartbeatOk: Bool {
        get { UserDefaults.standard.bool(forKey: lastHeartbeatOkKey) }
        set { UserDefaults.standard.set(newValue, forKey: lastHeartbeatOkKey) }
    }

    static var lastHeartbeatAt: TimeInterval {
        get { UserDefaults.standard.double(forKey: lastHeartbeatAtKey) }
        set { UserDefaults.standard.set(newValue, forKey: lastHeartbeatAtKey) }
    }

    /// Parent-configured LAN Brain intent URL (家里). Identity is brain.local; HTTP uses resolved IPv4.
    static var homeBrainIntentURL: String {
        get { defaultHomeBrainIntentURL }
        set { _ = newValue }
    }

    static var homeBrainResolvedIntentURL: String {
        get {
            let saved = UserDefaults.standard.string(forKey: homeBrainResolvedKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if !saved.isEmpty { return BrainURL.normalizeIntentURL(saved) }
            let legacy = UserDefaults.standard.string(forKey: homeBrainURLKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if BrainURL.ipv4Host(from: legacy) != nil {
                return BrainURL.normalizeIntentURL(legacy)
            }
            return ""
        }
        set {
            let normalized = BrainURL.normalizeIntentURL(newValue)
            guard let host = BrainURL.ipv4Host(from: normalized),
                  MdnsDiscovery.isUsableLanIPv4(host) else {
                DiscoveryDebugLog.shared.log(
                    "home IPv4 not saved (need RFC1918, got \(newValue))",
                    category: "connect"
                )
                return
            }
            UserDefaults.standard.set(normalized, forKey: homeBrainResolvedKey)
        }
    }

    static var homeBrainConnectIntentURL: String {
        homeBrainResolvedIntentURL
    }

    static func migrateLegacyEndpointsIfNeeded() {
        let migratedKey = "legacy.endpoints.migrated.v1"
        guard !UserDefaults.standard.bool(forKey: migratedKey) else { return }
        if homeBrainResolvedIntentURL.isEmpty {
            let legacy = UserDefaults.standard.string(forKey: homeBrainURLKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if BrainURL.ipv4Host(from: legacy) != nil {
                homeBrainResolvedIntentURL = BrainURL.normalizeIntentURL(legacy)
            }
        }
        UserDefaults.standard.set(true, forKey: migratedKey)
        clearStaleLanEndpointsIfNeeded()
    }

    /// Drop link-local / public cached IPs so launch does not block on bad LAN targets.
    static func clearStaleLanEndpointsIfNeeded() {
        if let host = BrainURL.ipv4Host(from: homeBrainResolvedIntentURL),
           !MdnsDiscovery.isUsableLanIPv4(host) {
            UserDefaults.standard.removeObject(forKey: homeBrainResolvedKey)
        }
        if let host = BrainURL.ipv4Host(from: macIngestConnectURL),
           !MdnsDiscovery.isUsableLanIPv4(host) {
            UserDefaults.standard.removeObject(forKey: macIngestResolvedKey)
        }
    }

    /// IPv4 ingest URL for HTTP/TCP. Empty until mDNS / manual IP — never `gateway.local`.
    static var macIngestConnectURL: String {
        let resolved = UserDefaults.standard.string(forKey: macIngestResolvedKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if BrainURL.ipv4Host(from: resolved) != nil { return resolved }
        let saved = UserDefaults.standard.string(forKey: macIngestKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if BrainURL.ipv4Host(from: saved) != nil { return saved }
        return ""
    }

    /// Mac Edge video-live ingest (port 8790). Display identity is gateway.local; HTTP uses IPv4.
    static var macIngestURL: String {
        get {
            let resolved = UserDefaults.standard.string(forKey: macIngestResolvedKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if BrainURL.ipv4Host(from: resolved) != nil { return resolved }
            let saved = UserDefaults.standard.string(forKey: macIngestKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if BrainURL.ipv4Host(from: saved) != nil { return saved }
            return saved.isEmpty ? defaultMacIngestURL : saved
        }
        set {
            let next = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
            UserDefaults.standard.set(next, forKey: macIngestKey)
            if BrainURL.ipv4Host(from: next) != nil {
                UserDefaults.standard.set(next, forKey: macIngestResolvedKey)
            }
        }
    }

    /// Drop cached IPv4 so「自动发现」must re-browse mDNS instead of showing a stale LAN IP.
    static func clearDiscoveredEndpoints() {
        UserDefaults.standard.removeObject(forKey: homeBrainResolvedKey)
        UserDefaults.standard.removeObject(forKey: macIngestResolvedKey)
        if let legacy = UserDefaults.standard.string(forKey: homeBrainURLKey),
           BrainURL.ipv4Host(from: legacy) != nil {
            UserDefaults.standard.removeObject(forKey: homeBrainURLKey)
        }
        if let legacy = UserDefaults.standard.string(forKey: macIngestKey),
           BrainURL.ipv4Host(from: legacy) != nil {
            UserDefaults.standard.removeObject(forKey: macIngestKey)
        }
    }

    static func applyDiscoveredBrain(_ brain: MdnsDiscovery.Endpoint) {
        guard MdnsDiscovery.isUsableLanIPv4(brain.host) else {
            DiscoveryDebugLog.shared.log(
                "apply Brain skipped: host \(brain.host) is not RFC1918 IPv4",
                category: "connect"
            )
            return
        }
        let intent = brain.baseURL + "/api/v1/intent"
        homeBrainResolvedIntentURL = intent
        DiscoveryDebugLog.shared.log("apply Brain intent \(homeBrainResolvedIntentURL)", category: "connect")
    }

    static func applyDiscoveredGateway(_ gateway: MdnsDiscovery.Endpoint) {
        guard MdnsDiscovery.isUsableLanIPv4(gateway.host) else { return }
        macIngestURL = gateway.baseURL
    }

    /// Discover LAN Brain and Mac gateway independently via mDNS / LAN scan.
    static func autoDiscoverLanEndpoints(completion: @escaping () -> Void) {
        let group = DispatchGroup()
        group.enter()
        MdnsDiscovery.resolveBrainForAutoDiscover(mdnsTimeout: 8) { brain in
            if let brain {
                homeBrainResolvedIntentURL = brain.baseURL + "/api/v1/intent"
            }
            group.leave()
        }
        group.enter()
        MdnsDiscovery.resolveGatewayForAutoDiscover(mdnsTimeout: 8) { gateway in
            if let gateway {
                macIngestURL = gateway.baseURL
            }
            group.leave()
        }
        group.notify(queue: .main) { completion() }
    }

    static func registrationBody() -> [String: Any] {
        [
            "client_hint": clientHint,
            "display_name": "Legacy iPhone Console",
            "device_type": "iphone",
            "roles": ["intent_source"],
            "services": [] as [Any],
            "endpoints": [] as [Any],
        ]
    }

    static func heartbeatBody(participantId: String) -> [String: Any] {
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        return [
            "edge_id": pid,
            "participant_id": pid,
            "client_hint": clientHint,
            "client_time_ms": Int(Date().timeIntervalSince1970 * 1000),
            "online_status": "online",
            "roles": ["intent_source"],
            "services": [] as [Any],
        ]
    }
}
