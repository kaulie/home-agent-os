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

    static let defaultBrainIntentURL = BrainEndpoint.homeIntentURL

    /// URL used for API calls (set after a successful register).
    private(set) static var activeIntentURL: String = BrainEndpoint.homeIntentURL

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
