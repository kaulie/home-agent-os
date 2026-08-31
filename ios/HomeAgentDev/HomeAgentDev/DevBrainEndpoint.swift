import Foundation

/// LAN / Cloud Brain slots and routing policy (aligned with LivingRoomEdge User Console).
enum DevBrainEndpoint {
    /// LAN identity shown in settings. HTTP uses resolved IPv4 (`lastSuccessfulLanHost`).
    static let defaultLanBase = "http://brain.local:9527"
    static let defaultCloudBase = "http://115.190.153.53:9527"

    private static let lanKey = "homeagent.dev.brain.lanURL"
    private static let cloudKey = "homeagent.dev.brain.cloudURL"
    private static let routingKey = "homeagent.dev.brain.routing"
    private static let legacyBrainKey = "homeagent.dev.brainURL"
    private static let migratedKey = "homeagent.dev.brain.migrated"
    private static let lastLanHostKey = "homeagent.dev.brain.lastLanHost"

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

    /// IPv4 Brain base for HTTP after mDNS / probe.
    static var lanResolvedBaseURL: String {
        get {
            if let ip = lastSuccessfulLanHost, DevBrainLANHostOrder.ipv4(from: ip) != nil {
                return "http://\(ip):9527"
            }
            return ""
        }
        set {
            if let ip = DevBrainLANHostOrder.ipv4(from: newValue) {
                lastSuccessfulLanHost = ip
            }
        }
    }

    static var cloudBaseURL: String {
        get { stored(key: cloudKey, fallback: defaultCloudBase) }
        set { UserDefaults.standard.set(normalizeBase(newValue), forKey: cloudKey) }
    }

    /// Last octet host that successfully answered Brain ping (e.g. "84" or full "192.168.3.84").
    static var lastSuccessfulLanHost: String? {
        get {
            let raw = UserDefaults.standard.string(forKey: lastLanHostKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return raw.isEmpty ? nil : raw
        }
        set {
            guard let newValue, !newValue.isEmpty else {
                UserDefaults.standard.removeObject(forKey: lastLanHostKey)
                return
            }
            if let ip = DevBrainLANHostOrder.ipv4(from: newValue) {
                UserDefaults.standard.set(ip, forKey: lastLanHostKey)
            } else {
                UserDefaults.standard.set(newValue, forKey: lastLanHostKey)
            }
        }
    }

    static func rememberSuccessfulLAN(_ baseURL: String) {
        if let ip = DevBrainLANHostOrder.ipv4(from: baseURL) {
            lastSuccessfulLanHost = ip
        }
    }

    static func lanConnectBase(identity: String? = nil) -> String {
        migrateLegacyIfNeeded()
        if let ip = lastSuccessfulLanHost, DevBrainLANHostOrder.ipv4(from: ip) != nil {
            return "http://\(ip):9527"
        }
        let identity = identity ?? lanBaseURL
        if DevBrainLANHostOrder.ipv4(from: identity) != nil {
            return normalizeBase(identity)
        }
        return normalizeBase(identity)
    }

    /// Discover LAN Brain via mDNS (A records + ping) and remember IPv4.
    static func autoDiscoverLanBrain() async {
        guard let brain = await MdnsDiscovery.resolveBrainForAutoDiscover(mdnsTimeout: 8) else { return }
        rememberSuccessfulLAN(brain.baseURL)
        if DevBrainLANHostOrder.ipv4(from: lanBaseURL) != nil {
            lanBaseURL = defaultLanBase
        }
    }

    static func migrateLegacyIfNeeded() {
        if !UserDefaults.standard.bool(forKey: migratedKey) {
            if let legacy = UserDefaults.standard.string(forKey: legacyBrainKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
                !legacy.isEmpty {
                let normalized = normalizeBase(legacy)
                if normalized == normalizeBase(defaultCloudBase) {
                    routing = .cloud
                } else if let ip = DevBrainLANHostOrder.ipv4(from: normalized) {
                    rememberSuccessfulLAN(normalized)
                    lanBaseURL = defaultLanBase
                } else if normalized != normalizeBase(defaultLanBase) {
                    lanBaseURL = normalized
                }
            }
            UserDefaults.standard.set(true, forKey: migratedKey)
        }
        if let ip = DevBrainLANHostOrder.ipv4(from: lanBaseURL) {
            rememberSuccessfulLAN(lanBaseURL)
            lanBaseURL = defaultLanBase
        }
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
        await probeBrain(baseURL: baseURL, timeout: timeout)
    }

    static func probeBrain(baseURL: String, timeout: TimeInterval = 2) async -> Bool {
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
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            guard (200 ..< 300).contains(http.statusCode) else { return false }
            return DevBrainPingParser.isBrainResponse(data)
        } catch {
            return false
        }
    }
}
