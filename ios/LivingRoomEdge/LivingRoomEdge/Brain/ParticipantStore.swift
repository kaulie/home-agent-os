import Foundation
import UIKit

/// Stable Intent Source + Endpoint identity for this install.
/// Not a Runtime: no services, no camera.capture / display.photo.
enum ParticipantStore {
    private static let hintKey = "livingroom.clientHint"
    private static let idKey = "livingroom.participantId"
    private static let brainKey = "livingroom.registeredBrainURL"

    static var clientHint: String {
        if let saved = UserDefaults.standard.string(forKey: hintKey), !saved.isEmpty {
            return saved
        }
        let suffix = UIDevice.current.identifierForVendor?.uuidString.prefix(8)
            ?? UUID().uuidString.prefix(8)
        let hint = "living-room-iphone-\(suffix)"
        UserDefaults.standard.set(hint, forKey: hintKey)
        return hint
    }

    static var participantId: String {
        get { UserDefaults.standard.string(forKey: idKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: idKey) }
    }

    static var lastRegisteredBrainURL: String {
        get { UserDefaults.standard.string(forKey: brainKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: brainKey) }
    }

    static var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.2.0"
    }

    static func registrationBody() -> [String: Any] {
        var body: [String: Any] = [
            "client_hint": clientHint,
            "display_name": "客厅 iPhone",
            "device_type": "iphone",
            "location": "living-room",
            "room": "living-room",
            "app_version": appVersion,
            "roles": ["intent_source", "endpoint"],
            "role_intent_source": true,
            "role_endpoint": true,
            "role_runtime": false,
            "services": [] as [Any],
            "intent_sources": [
                ["source_id": "iphone.keyboard", "channel": "text"],
                ["source_id": "iphone.microphone", "channel": "voice"],
            ],
            "endpoints": [
                [
                    "endpoint_id": "iphone.display",
                    "supported_presentation": ["image", "text"],
                ],
            ],
        ]
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        if !pid.isEmpty {
            body["participant_id"] = pid
            body["edge_id"] = pid
        }
        return body
    }
}
