import Foundation
import Network

/// Two persisted Brain slots (LAN / Cloud) plus helpers to turn a base into `/api/v1/intent`.
/// Fresh-install defaults come from `config/endpoints.json` via `python3 tools/sync_endpoints.py`.
enum BrainEndpoint {
    /// LAN identity (settings). HTTP uses `lanResolvedBaseURL` (IPv4 from mDNS/probe).
    static let defaultLanBase = "http://brain.local:9527"
    static let defaultCloudBase = "http://115.190.153.53:9527"

    static let defaultLanIntentURL = intentURL(from: defaultLanBase)
    static let defaultCloudIntentURL = intentURL(from: defaultCloudBase)

    private static let lanKey = "livingroom.brain.lanURL"
    private static let cloudKey = "livingroom.brain.cloudURL"
    private static let lanResolvedKey = "livingroom.brain.lanResolvedBase"
    private static let identityMigratedKey = "livingroom.brain.lanIdentityMigrated"

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

    /// IPv4 Brain base used for HTTP (`http://192.168.x.x:9527`). Empty until discovery/probe.
    static var lanResolvedBaseURL: String {
        get { stored(key: lanResolvedKey, fallback: "") }
        set {
            let next = normalizeBase(newValue)
            if next.isEmpty {
                UserDefaults.standard.removeObject(forKey: lanResolvedKey)
            } else {
                UserDefaults.standard.set(next, forKey: lanResolvedKey)
            }
        }
    }

    static var cloudBaseURL: String {
        get { stored(key: cloudKey, fallback: defaultCloudBase) }
        set { UserDefaults.standard.set(normalizeBase(newValue), forKey: cloudKey) }
    }

    /// URL actually used to talk to LAN Brain. Never prefer `.local` when an IPv4 is known.
    static var lanConnectBaseURL: String {
        migrateLanIdentityIfNeeded()
        let resolved = lanResolvedBaseURL
        if !resolved.isEmpty, ipv4Host(from: resolved) != nil { return resolved }
        if ipv4Host(from: lanBaseURL) != nil { return lanBaseURL }
        return lanBaseURL
    }

    static var lanIntentURL: String { intentURL(from: lanConnectBaseURL) }
    static var cloudIntentURL: String { intentURL(from: cloudBaseURL) }

    static func migrateLanIdentityIfNeeded() {
        guard !UserDefaults.standard.bool(forKey: identityMigratedKey) else {
            if ipv4Host(from: lanBaseURL) != nil, lanResolvedBaseURL.isEmpty {
                lanResolvedBaseURL = lanBaseURL
                lanBaseURL = defaultLanBase
            }
            return
        }
        if let ipBase = ipv4Base(from: lanBaseURL) {
            if lanResolvedBaseURL.isEmpty {
                lanResolvedBaseURL = ipBase
            }
            lanBaseURL = defaultLanBase
        } else if lanBaseURL.isEmpty {
            lanBaseURL = defaultLanBase
        }
        UserDefaults.standard.set(true, forKey: identityMigratedKey)
    }

    static func ipv4Host(from raw: String) -> String? {
        let trimmed = normalizeBase(raw)
        let host: String
        if let url = URL(string: trimmed), let urlHost = url.host, !urlHost.isEmpty {
            host = urlHost
        } else {
            host = trimmed
        }
        let parts = host.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ UInt8($0) != nil }) else { return nil }
        return host
    }

    static func ipv4Base(from raw: String) -> String? {
        guard let host = ipv4Host(from: raw) else { return nil }
        let port: Int
        if let url = URL(string: normalizeBase(raw)), let urlPort = url.port {
            port = urlPort
        } else {
            port = 9527
        }
        return "http://\(host):\(port)"
    }

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
