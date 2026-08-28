import Foundation

/// LAN / Cloud Brain slots and routing policy (aligned with LivingRoomEdge User Console).
enum DevBrainEndpoint {
    static let defaultLanBase = "http://192.168.3.73:9527"
    static let defaultCloudBase = "http://115.190.153.53:9527"

    private static let lanKey = "homeagent.dev.brain.lanURL"
    private static let cloudKey = "homeagent.dev.brain.cloudURL"
    private static let routingKey = "homeagent.dev.brain.routing"
    private static let legacyBrainKey = "homeagent.dev.brainURL"
    private static let migratedKey = "homeagent.dev.brain.migrated"

    enum Mode: String {
        case lan
        case cloud

        var displayName: String { self == .lan ? "局域网" : "云端" }
    }

    enum Routing: String, CaseIterable, Identifiable {
        case auto
        case lan
        case cloud

        var id: String { rawValue }

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
                return "始终连家里的 Brain。外出或局域网不通时 Dev API 会失败。"
            case .cloud:
                return "始终连云端 Brain。即使在家也不走局域网。"
            }
        }
    }

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

    static func migrateLegacyIfNeeded() {
        guard !UserDefaults.standard.bool(forKey: migratedKey) else { return }
        if let legacy = UserDefaults.standard.string(forKey: legacyBrainKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            !legacy.isEmpty {
            let normalized = normalizeBase(legacy)
            if normalized == normalizeBase(defaultCloudBase) {
                routing = .cloud
            } else if normalized != normalizeBase(defaultLanBase) {
                lanBaseURL = normalized
            }
        }
        UserDefaults.standard.set(true, forKey: migratedKey)
    }

    static func normalizeBase(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") {
            value.removeLast()
        }
        if !value.isEmpty {
            let lower = value.lowercased()
            if !lower.hasPrefix("http://") && !lower.hasPrefix("https://") {
                value = "http://" + value
            }
        }
        return value
    }

    private static func stored(key: String, fallback: String) -> String {
        let saved = UserDefaults.standard.string(forKey: key)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return saved.isEmpty ? fallback : normalizeBase(saved)
    }
}

enum DevBrainPathKind: String {
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

struct DevBrainEnvironment: Equatable {
    var pathKind: DevBrainPathKind = .unknown
    var looksOnHomeLAN: Bool = false
    var lanProbeOk: Bool?
    var lanProbeDetail: String = ""
    var routing: DevBrainEndpoint.Routing = .auto
    var mode: DevBrainEndpoint.Mode = .cloud
    var activeBaseURL: String = DevBrainEndpoint.defaultCloudBase

    var modeLabel: String { mode.displayName }
    var routingLabel: String { routing.title }
}

enum DevBrainProbe {
    static func ping(baseURL: String, timeout: TimeInterval = 2) async -> Bool {
        let base = DevBrainEndpoint.normalizeBase(baseURL)
        guard !base.isEmpty else { return false }
        let ms = Int64(Date().timeIntervalSince1970 * 1000)
        guard let url = URL(string: "\(base)/api/v1/ping?client_time_ms=\(ms)") else {
            return false
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200 ..< 300).contains(http.statusCode)
        } catch {
            return false
        }
    }
}
