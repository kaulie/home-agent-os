import Foundation
import UIKit

/// Local device identity for HAP1 hello (no Brain register required).
enum PickupIdentity {
    private static let deviceIdKey = "pickup.deviceId"
    private static let participantIdKey = "pickup.participantId"

    static var deviceId: String {
        if let saved = UserDefaults.standard.string(forKey: deviceIdKey), !saved.isEmpty {
            return saved
        }
        let suffix = UIDevice.current.identifierForVendor?.uuidString.prefix(8) ?? "unknown"
        let value = "living-room-pickup-\(suffix)"
        UserDefaults.standard.set(value, forKey: deviceIdKey)
        return value
    }

    static var participantId: String {
        get {
            UserDefaults.standard.string(forKey: participantIdKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        }
        set {
            UserDefaults.standard.set(
                newValue.trimmingCharacters(in: .whitespacesAndNewlines),
                forKey: participantIdKey
            )
        }
    }
}
