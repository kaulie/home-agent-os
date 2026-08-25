import Foundation

/// GoPro gpControl on iPhone (camera HTTP only). No Wi‑Fi join/switch.
actor GoProDriver {
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
    private var reachableConnected = false

    init(baseHost: String = GoProDriver.defaultHost) {
        self.baseHost = baseHost.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    struct HttpResult {
        let url: String
        let body: String
        let data: Data
        let statusCode: Int
        let elapsedMs: Double

        var durationLabel: String { GoProHTTP.formatDuration(elapsedMs) }
    }

    // MARK: - Driver

    func identity() async -> (driverId: String, displayName: String, endpoint: String) {
        (driverId: "gopro", displayName: "GoPro Camera", endpoint: baseHost)
    }

    func connect() async throws {
        do {
            _ = try await fetchStatus()
            reachableConnected = true
        } catch {
            throw GoProDriverError.unreachable(
                "连不上 GoPro（\(error.localizedDescription)）"
            )
        }
    }

    /// Cheap preflight for Runtime `isAvailable` — short status GET, no shutter.
    func probeAvailable(timeoutSeconds: TimeInterval = 2.0) async -> (ok: Bool, message: String) {
        do {
            var req = URLRequest(url: URL(string: baseHost + Self.pathStatus)!)
            req.timeoutInterval = timeoutSeconds
            req.httpMethod = "GET"
            let result = try await GoProHTTP.data(for: req, label: "isAvailable")
            if (200..<300).contains(result.statusCode) {
                reachableConnected = true
                return (true, "available")
            }
            return (false, "拍照不可用：GoPro HTTP \(result.statusCode)。请确认已连相机热点且相机开机。")
        } catch {
            return (false, "拍照不可用：连不上 GoPro（\(error.localizedDescription)）。请确认已连相机热点且相机开机。")
        }
    }

    func disconnect() async throws {
        reachableConnected = false
    }

    func status() async -> (connected: Bool, summary: String) {
        let summary = "host=\(baseHost) connected=\(reachableConnected)"
        return (connected: reachableConnected, summary: summary)
    }

    func capabilities() async -> [String] {
        ["camera.capture"]
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
    case unreachable(String)
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
        case let .unreachable(s):
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
