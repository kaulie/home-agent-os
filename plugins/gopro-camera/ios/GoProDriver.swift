import Foundation
import NetworkExtension

/// GoPro gpControl protocol capabilities (camera-side only). No upload-to-server here.
actor GoProDriver: CapabilityDriver {
    static let defaultHost = "http://10.5.5.9"

    static let pathModeVideo = "/gp/gpControl/command/mode?p=0"
    static let pathModePhoto = "/gp/gpControl/command/mode?p=1"
    static let pathSubModePhotoSingle = "/gp/gpControl/command/sub_mode?mode=1&sub_mode=0"
    static let pathStatus = "/gp/gpControl/status"
    static let pathShutterStart = "/gp/gpControl/command/shutter?p=1"
    static let pathShutterStop = "/gp/gpControl/command/shutter?p=0"
    static let pathMediaList = "/gp/gpMediaList"

    static var defaultStatusURL: String { defaultHost + pathStatus }
    static var defaultShutterURL: String { defaultHost + pathShutterStart }
    static var defaultShutterStopURL: String { defaultHost + pathShutterStop }
    static var defaultMediaListURL: String { defaultHost + pathMediaList }

    private var baseHost: String
    /// Optional SSID for `connect()` Hotspot join. Nil → probe reachability only.
    private var wifiSSID: String?
    private var wifiPassword: String?
    private var hotspotJoinedSSID: String?
    private var reachableConnected = false

    init(
        baseHost: String = GoProDriver.defaultHost,
        wifiSSID: String? = nil,
        wifiPassword: String? = nil
    ) {
        self.baseHost = baseHost.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        self.wifiSSID = wifiSSID
        self.wifiPassword = wifiPassword
    }

    func configureWiFi(ssid: String?, password: String?) {
        wifiSSID = ssid
        wifiPassword = password
    }

    struct HttpResult {
        let url: String
        let body: String
        let data: Data
        let statusCode: Int
        let elapsedMs: Double

        var durationLabel: String { GoProHTTP.formatDuration(elapsedMs) }
    }

    // MARK: - CapabilityDriver

    func identity() async -> DriverIdentity {
        DriverIdentity(
            driverId: "gopro",
            displayName: "GoPro Camera",
            endpoint: baseHost
        )
    }

    func connect() async throws {
        if let ssid = wifiSSID?.trimmingCharacters(in: .whitespacesAndNewlines), !ssid.isEmpty {
            try await joinCameraWiFi(ssid: ssid, password: wifiPassword)
            hotspotJoinedSSID = ssid
            reachableConnected = true
            return
        }
        // No SSID configured: probe camera HTTP (manual Wi‑Fi join assumed).
        _ = try await fetchStatus()
        reachableConnected = true
    }

    func disconnect() async throws {
        if let ssid = hotspotJoinedSSID {
            await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
                NEHotspotConfigurationManager.shared.removeConfiguration(forSSID: ssid)
                cont.resume()
            }
            hotspotJoinedSSID = nil
        }
        reachableConnected = false
    }

    func status() async -> DriverStatus {
        let hotspot = hotspotJoinedSSID.map { "hotspot=\($0)" } ?? "hotspot=none"
        let summary = "host=\(baseHost) connected=\(reachableConnected) \(hotspot)"
        return DriverStatus(connected: reachableConnected, summary: summary)
    }

    func capabilities() async -> [String] {
        [Capabilities.cameraCapture, Capabilities.takeVideo]
    }

    // MARK: - Named protocol APIs

    func fetchStatus() async throws -> HttpResult {
        try await get(path: Self.pathStatus)
    }

    func capturePhoto() async throws -> HttpResult {
        // If camera is recording / timelapse counting, shutter would keep video — stop first.
        if let before = try? await fetchStatus(),
           let snap = GoProStatusSnapshot.parse(jsonBody: before.body),
           snap.isBusy {
            _ = try? await get(path: Self.pathShutterStop)
            try await Task.sleep(nanoseconds: 600_000_000)
        }

        _ = try await get(path: Self.pathModePhoto)
        _ = try? await get(path: Self.pathSubModePhotoSingle)
        try await Task.sleep(nanoseconds: 500_000_000)

        let mid = try await fetchStatus()
        if let snap = GoProStatusSnapshot.parse(jsonBody: mid.body), snap.mode != .photo {
            throw GoProDriverError.requestFailed(
                "未能切到拍照模式，当前：\(snap.displayLine)。请先停止录像/延时计时后再拍。"
            )
        }

        return try await get(path: Self.pathShutterStart)
    }

    func startRecording() async throws -> HttpResult {
        _ = try await get(path: Self.pathModeVideo)
        try await Task.sleep(nanoseconds: 300_000_000)
        return try await get(path: Self.pathShutterStart)
    }

    func stopRecording() async throws -> HttpResult {
        try await get(path: Self.pathShutterStop)
    }

    func fetchMediaList() async throws -> HttpResult {
        try await get(path: Self.pathMediaList, timeout: 20)
    }

    /// Download a media file. GoPro typically serves DCIM over **:8080** while gpControl stays on :80.
    func downloadMedia(path: String) async throws -> HttpResult {
        let relative: String
        if path.hasPrefix("http://") || path.hasPrefix("https://") {
            // Absolute URL: try as-is with long timeout.
            return try await get(urlString: path, timeout: 120)
        } else {
            relative = path.hasPrefix("/") ? path : "/" + path
        }

        let primary = mediaBaseHost + relative
        do {
            return try await get(urlString: primary, timeout: 120)
        } catch {
            // Some firmwares serve files on :80 as well — fall back once.
            let fallback = baseHost + relative
            if fallback == primary { throw error }
            return try await get(urlString: fallback, timeout: 120)
        }
    }

    /// Media HTTP root (`http://10.5.5.9:8080`). Control API stays on `baseHost` without :8080.
    private var mediaBaseHost: String {
        guard let url = URL(string: baseHost), let host = url.host else {
            return baseHost.contains(":8080") ? baseHost : baseHost + ":8080"
        }
        if url.port == 8080 { return baseHost }
        let scheme = url.scheme ?? "http"
        return "\(scheme)://\(host):8080"
    }

    func joinCameraWiFi(ssid: String, password: String?) async throws {
        let trimmed = ssid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw GoProDriverError.invalidArgument("ssid is empty")
        }

        #if targetEnvironment(simulator)
        throw GoProDriverError.wifiJoinFailed(
            "模拟器不支持 Hotspot 加网，请用真机；或到「设置 → Wi‑Fi」手动加入相机热点"
        )
        #else

        let config: NEHotspotConfiguration
        if let password, !password.isEmpty {
            let pwd = password.trimmingCharacters(in: .whitespacesAndNewlines)
            // WPA/WPA2 passphrase must be 8...63 characters
            guard pwd.count >= 8, pwd.count <= 63 else {
                throw GoProDriverError.wifiJoinFailed(
                    "密码长度需 8–63 位（GoPro 相机密码一般在机身或 App 里）。也可到「设置 → Wi‑Fi」手动加入"
                )
            }
            config = NEHotspotConfiguration(ssid: trimmed, passphrase: pwd, isWEP: false)
        } else {
            // Open network (rare for GoPro). Prefer providing password.
            config = NEHotspotConfiguration(ssid: trimmed)
        }
        // Stay associated for this session; joinOnce can drop mid-download on some iOS versions.
        config.joinOnce = false

        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            NEHotspotConfigurationManager.shared.apply(config) { error in
                if let error = error as NSError? {
                    if error.domain == NEHotspotConfigurationErrorDomain,
                       error.code == NEHotspotConfigurationError.alreadyAssociated.rawValue {
                        cont.resume()
                        return
                    }
                    cont.resume(throwing: GoProDriverError.wifiJoinFailed(Self.hotspotErrorMessage(error)))
                    return
                }
                cont.resume()
            }
        }
        hotspotJoinedSSID = trimmed
        reachableConnected = true
        #endif
    }

    private static func hotspotErrorMessage(_ error: NSError) -> String {
        let code = error.code
        if error.domain == NEHotspotConfigurationErrorDomain {
            switch code {
            case NEHotspotConfigurationError.userDenied.rawValue:
                return "你取消了加入 Wi‑Fi。可重试，或到「设置 → Wi‑Fi」手动连接相机热点"
            case NEHotspotConfigurationError.invalidSSID.rawValue:
                return "SSID 无效，请核对相机热点名称（区分大小写）"
            case NEHotspotConfigurationError.invalidWPAPassphrase.rawValue,
                 NEHotspotConfigurationError.invalidWEPPassphrase.rawValue:
                return "Wi‑Fi 密码不正确（需 8–63 位）。也可到「设置 → Wi‑Fi」手动加入"
            case NEHotspotConfigurationError.internal.rawValue:
                return "自动加网不可用：免费开发账号通常没有 Hotspot Configuration 能力。请到「设置 → Wi‑Fi」手动加入相机热点后再回 App 操作"
            case NEHotspotConfigurationError.pending.rawValue:
                return "已有加网请求进行中，稍后再试"
            case NEHotspotConfigurationError.systemConfiguration.rawValue:
                return "系统配置不允许自动加网，请到「设置 → Wi‑Fi」手动加入"
            case NEHotspotConfigurationError.applicationIsNotInForeground.rawValue:
                return "请保持 App 在前台再试加网"
            case 15: // NEHotspotConfigurationError.temporary
                return "临时失败，请稍后重试；或到「设置 → Wi‑Fi」手动加入"
            default:
                break
            }
        }
        return "\(error.localizedDescription)（code=\(code)）。可到「设置 → Wi‑Fi」手动加入相机热点后再操作"
    }

    // MARK: - HTTP (debug override / internals)

    func get(urlString: String, timeout: TimeInterval = 12) async throws -> HttpResult {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed) else {
            throw GoProDriverError.invalidURL(trimmed)
        }
        return try await performGET(url, timeout: timeout)
    }

    func get(path: String, timeout: TimeInterval = 12) async throws -> HttpResult {
        let urlString: String
        if path.hasPrefix("http://") || path.hasPrefix("https://") {
            urlString = path
        } else if path.hasPrefix("/") {
            urlString = baseHost + path
        } else {
            urlString = baseHost + "/" + path
        }
        return try await get(urlString: urlString, timeout: timeout)
    }

    private func performGET(_ url: URL, timeout: TimeInterval) async throws -> HttpResult {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout

        do {
            let timed = try await GoProHTTP.data(for: request, label: "gopro")
            guard let http = timed.http else {
                throw GoProDriverError.invalidResponse
            }
            let body = String(data: timed.data, encoding: .utf8) ?? ""
            guard (200 ..< 300).contains(http.statusCode) else {
                throw GoProDriverError.httpStatus(http.statusCode, body)
            }
            reachableConnected = true
            return HttpResult(
                url: url.absoluteString,
                body: body,
                data: timed.data,
                statusCode: http.statusCode,
                elapsedMs: timed.elapsedMs
            )
        } catch let error as GoProDriverError {
            throw error
        } catch let timed as GoProHTTP.Failure {
            throw mapTransportError(timed.underlying, url: url, elapsedMs: timed.elapsedMs)
        } catch {
            throw mapTransportError(error, url: url, elapsedMs: nil)
        }
    }

    private func mapTransportError(_ error: Error, url: URL, elapsedMs: Double?) -> GoProDriverError {
        let suffix = elapsedMs.map { " · \(GoProHTTP.formatDuration($0))" } ?? ""
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorTimedOut:
                return .timeout(url.absoluteString + suffix)
            case NSURLErrorNotConnectedToInternet,
                 NSURLErrorNetworkConnectionLost,
                 NSURLErrorCannotConnectToHost,
                 NSURLErrorDNSLookupFailed:
                reachableConnected = false
                return .notConnected(
                    "未连接相机 Wi‑Fi 或主机不可达: \(error.localizedDescription)\(suffix)"
                )
            default:
                break
            }
        }
        return .requestFailed("\(error.localizedDescription)\(suffix)")
    }

    static func extractLatestStillPath(from json: String) -> String? {
        extractLatestStill(from: json)?.path
    }

    func latestStillItem(fromMediaListJSON json: String) -> GoProMediaItem? {
        Self.extractLatestStill(from: json)
    }

    func latestStillPath(fromMediaListJSON json: String) -> String? {
        Self.extractLatestStill(from: json)?.path
    }

    static func extractLatestStill(from json: String) -> GoProMediaItem? {
        guard let data = json.data(using: .utf8),
              let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let media = root["media"] as? [[String: Any]] else {
            return nil
        }

        var candidates: [(item: GoProMediaItem, order: Int)] = []
        var order = 0
        for folderEntry in media {
            let folder = (folderEntry["d"] as? String) ?? ""
            let files = folderEntry["fs"] as? [[String: Any]] ?? []
            for file in files {
                guard let name = file["n"] as? String else { continue }
                let lower = name.lowercased()
                let isStill = lower.hasSuffix(".jpg") || lower.hasSuffix(".jpeg")
                    || lower.hasSuffix(".gpr")
                let timestamp = mediaTimestamp(from: file)
                candidates.append(
                    (
                        GoProMediaItem(folder: folder, name: name, timestamp: timestamp, isStill: isStill),
                        order
                    )
                )
                order += 1
            }
        }

        let stills = candidates.filter(\.item.isStill)
        let pool = stills.isEmpty ? candidates : stills
        // GoPro `cre`/`mod` is often wrong (dead battery, unset clock, bogus future times).
        // Prefer DCIM folder + GOPR#### sequence, then list order; timestamp only as last resort.
        return pool.max { a, b in
            let fa = Self.folderSequence(a.item.folder)
            let fb = Self.folderSequence(b.item.folder)
            if fa != fb { return fa < fb }
            let na = Self.fileSequence(a.item.name)
            let nb = Self.fileSequence(b.item.name)
            if na != nb { return na < nb }
            if a.order != b.order { return a.order < b.order }
            let ta = Self.timestampValue(a.item.timestamp)
            let tb = Self.timestampValue(b.item.timestamp)
            if ta != tb { return ta < tb }
            return a.item.name < b.item.name
        }?.item
    }

    private static func mediaTimestamp(from file: [String: Any]) -> String {
        if let cre = file["cre"] {
            return numericString(cre)
        }
        if let mod = file["mod"] {
            return numericString(mod)
        }
        return ""
    }

    private static func numericString(_ any: Any) -> String {
        switch any {
        case let n as NSNumber:
            return n.stringValue
        case let s as String:
            return s.trimmingCharacters(in: .whitespacesAndNewlines)
        default:
            return String(describing: any)
        }
    }

    private static func timestampValue(_ raw: String) -> Double {
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if let d = Double(t) { return d }
        if let i = Int(t) { return Double(i) }
        return -1
    }

    /// `100GOPRO` → 100; unknown → -1.
    private static func folderSequence(_ folder: String) -> Int {
        let digits = folder.prefix(while: { $0.isNumber })
        return Int(digits) ?? -1
    }

    /// `GOPR0874.JPG` / `GPFR0875.JPG` / `GX010874.MP4` → trailing media index.
    private static func fileSequence(_ name: String) -> Int {
        let stem = (name as NSString).deletingPathExtension.uppercased()
        let digits = stem.reversed().prefix(while: { $0.isNumber }).reversed()
        return Int(String(digits)) ?? -1
    }
}

struct GoProMediaItem: Equatable {
    let folder: String
    let name: String
    let timestamp: String
    let isStill: Bool

    var path: String {
        if folder.isEmpty {
            return "/videos/DCIM/\(name)"
        }
        return "/videos/DCIM/\(folder)/\(name)"
    }

    var cacheKey: String { "\(name)|\(timestamp)" }
}

enum GoProDriverError: LocalizedError {
    case invalidURL(String)
    case invalidResponse
    case httpStatus(Int, String)
    case invalidArgument(String)
    case wifiJoinFailed(String)
    case notConnected(String)
    case timeout(String)
    case requestFailed(String)

    var errorDescription: String? {
        switch self {
        case let .invalidURL(s):
            return "invalid URL: \(s)"
        case .invalidResponse:
            return "invalid response from GoPro"
        case let .httpStatus(code, body):
            return "GoPro HTTP \(code): \(body.prefix(200))"
        case let .invalidArgument(s):
            return s
        case let .wifiJoinFailed(s):
            return s
        case let .notConnected(s):
            return s
        case let .timeout(url):
            return "请求超时: \(url)"
        case let .requestFailed(s):
            return "请求失败: \(s)"
        }
    }
}
