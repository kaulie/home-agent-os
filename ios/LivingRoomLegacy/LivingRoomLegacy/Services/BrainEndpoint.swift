import Foundation

/// Kid-friendly Brain presets — no manual URL typing.
enum BrainEndpoint: Int {
    case home = 0
    case cloud = 1

    static let homeIntentURL = "http://192.168.3.73:9527/api/v1/intent"
    static let cloudIntentURL = "http://115.190.153.53:9527/api/v1/intent"

    var intentURL: String {
        switch self {
        case .home: return BrainEndpoint.homeIntentURL
        case .cloud: return BrainEndpoint.cloudIntentURL
        }
    }

    var segmentTitle: String {
        switch self {
        case .home: return "家里"
        case .cloud: return "外面"
        }
    }

    var statusHint: String {
        switch self {
        case .home: return "家里 WiFi"
        case .cloud: return "外面网络"
        }
    }

    var opposite: BrainEndpoint {
        self == .home ? .cloud : .home
    }

    static func matching(savedURL: String) -> BrainEndpoint {
        let normalized = BrainURL.normalizeIntentURL(savedURL)
        if normalized.contains("115.190.153.53") {
            return .cloud
        }
        return .home
    }
}
