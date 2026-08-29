import Foundation
import Network

/// Two persisted Brain slots (LAN / Cloud) plus helpers to turn a base into `/api/v1/intent`.
/// Fresh-install defaults come from `config/endpoints.json` via `python3 tools/sync_endpoints.py`.
enum BrainEndpoint {
    static let defaultLanBase = "http://192.168.3.73:9527"
    static let defaultCloudBase = "http://115.190.153.53:9527"

    static let defaultLanIntentURL = intentURL(from: defaultLanBase)
    static let defaultCloudIntentURL = intentURL(from: defaultCloudBase)

    private static let lanKey = "livingroom.brain.lanURL"
    private static let cloudKey = "livingroom.brain.cloudURL"

    enum Mode: String {
        case lan
        case cloud

        var displayName: String { self == .lan ? "局域网" : "云端" }
    }

    /// How the phone chooses between the two saved Brain slots.
    enum Routing: String, CaseIterable, Identifiable {
        case auto
        case lan
        case cloud

        var id: String { rawValue }

        var pickerLabel: String { title }

        var title: String {
            switch self {
            case .auto: return "按网络自动"
            case .lan: return "锁定局域网"
            case .cloud: return "锁定云端"
            }
        }

        var subtitle: String {
            switch self {
            case .auto:
                return "在家 Wi‑Fi 且局域网 Brain 可达时走局域网，否则走云端。"
            case .lan:
                return "始终连家里的 Brain。外出或局域网不通时对话会失败。"
            case .cloud:
                return "始终连云端 Brain。即使在家也不走局域网。"
            }
        }
    }

    private static let routingKey = "livingroom.brain.routing"

    static var routing: Routing {
        get {
            let raw = UserDefaults.standard.string(forKey: routingKey) ?? ""
            return Routing(rawValue: raw) ?? .auto
        }
        set { UserDefaults.standard.set(newValue.rawValue, forKey: routingKey) }
    }

    static var lanBaseURL: String {
        get { stored(key: lanKey, fallback: defaultLanBase) }
        set { UserDefaults.standard.set(normalizeBase(newValue), forKey: lanKey) }
    }

    static var cloudBaseURL: String {
        get { stored(key: cloudKey, fallback: defaultCloudBase) }
        set { UserDefaults.standard.set(normalizeBase(newValue), forKey: cloudKey) }
    }

    static var lanIntentURL: String { intentURL(from: lanBaseURL) }
    static var cloudIntentURL: String { intentURL(from: cloudBaseURL) }

    static func intentURL(from raw: String) -> String {
        let base = normalizeBase(raw)
        if base.hasSuffix("/api/v1/intent") { return base }
        if base.contains("/api/v1/") { return base }
        return base + "/api/v1/intent"
    }

    static func displayBase(from raw: String) -> String {
        var value = normalizeBase(raw)
        if value.hasSuffix("/api/v1/intent") {
            value = String(value.dropLast("/api/v1/intent".count))
        }
        return normalizeBase(value)
    }

    static func normalizeBase(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") {
            value.removeLast()
        }
        return value
    }

    private static func stored(key: String, fallback: String) -> String {
        let saved = UserDefaults.standard.string(forKey: key)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return saved.isEmpty ? fallback : normalizeBase(saved)
    }
}

enum BrainPathKind: String {
    case wifi
    case wired
    case cellular
    case none
    case unknown

    var looksOnHomeLAN: Bool {
        self == .wifi || self == .wired
    }

    var label: String {
        switch self {
        case .wifi: return "Wi‑Fi"
        case .wired: return "有线"
        case .cellular: return "蜂窝"
        case .none: return "无网络"
        case .unknown: return "未知"
        }
    }
}

struct BrainNetworkEnvironment: Equatable {
    var pathKind: BrainPathKind = .unknown
    var looksOnHomeLAN: Bool = false
    var lanProbeOk: Bool?
    var lanProbeDetail: String = ""
    var routing: BrainEndpoint.Routing = .auto
    var mode: BrainEndpoint.Mode = .cloud
    var activeIntentURL: String = BrainEndpoint.defaultCloudIntentURL

    var modeLabel: String { mode.displayName }

    var routingLabel: String { routing.title }

    var activeBaseURL: String { BrainEndpoint.displayBase(from: activeIntentURL) }

    var summaryLine: String {
        let path = looksOnHomeLAN ? "像在家庭局域网（\(pathKind.label)）" : "不在家庭局域网（\(pathKind.label)）"
        let probe: String
        switch lanProbeOk {
        case true: probe = "LAN 探测成功"
        case false: probe = "LAN 探测失败"
        case nil: probe = "尚未探测 LAN"
        }
        return "\(path) · \(probe) · 路由 \(routingLabel) · 当前 \(modeLabel) \(activeBaseURL)"
    }
}
