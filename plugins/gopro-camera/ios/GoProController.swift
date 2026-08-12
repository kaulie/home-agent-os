import Foundation

/// Unified GoPro interaction node: orchestrates Driver (camera protocol) and owns non-camera logic (upload / server download).
final class GoProController: DeviceController {
    let controllerId = "gopro"
    let displayName = "GoPro Camera"

    private let driver: GoProDriver
    /// Last photo bytes from fetchLatestPhoto / capture flows for upload_photo without local_path.
    private(set) var lastPhotoData: Data?
    private(set) var lastPhotoLocalPath: String?
    /// Last parsed camera status line (from `/gp/gpControl/status`).
    private(set) var lastStatusSummary: String = "暂时未知"
    private(set) var lastStatusSnapshot: GoProStatusSnapshot?
    /// Host-visible progress (wait-for-Wi‑Fi prompts, etc.).
    var onProgress: ((String) -> Void)?

    init(driver: GoProDriver = GoProDriver()) {
        self.driver = driver
    }

    // MARK: - Camera capabilities (via Driver)

    func fetchStatus() async -> ControllerResult {
        do {
            let http = try await driver.fetchStatus()
            if let snap = GoProStatusSnapshot.parse(jsonBody: http.body) {
                lastStatusSnapshot = snap
                lastStatusSummary = snap.displayLine
                return .success(
                    "\(snap.displayText)\n\n—— 原始 JSON ——\n\(http.body)\n⏱ \(http.durationLabel)",
                    data: http.data
                )
            }
            return .success(
                "\(http.body.isEmpty ? "(empty)" : http.body)\n⏱ \(http.durationLabel)",
                data: http.data
            )
        } catch {
            return .failure("\(error.localizedDescription). Join GoPro Wi‑Fi first.")
        }
    }

    func capturePhoto() async -> ControllerResult {
        await capturePhotoPipeline()
    }

    /// Full wire pipeline: shutter → wait 2s → download → wait home Wi‑Fi → upload.
    /// Cast is a separate `display.photo` plan step (not folded into camera.capture).
    func capturePhotoPipeline() async -> ControllerResult {
        emitProgress("① 快门：连接 GoPro 并拍照…")
        let shutter = await map { try await driver.capturePhoto() }
        if !shutter.ok {
            emitProgress("① 快门失败：\(shutter.message)")
            return .failure("shutter failed: \(shutter.message)")
        }
        emitProgress("① 快门完成，读取相机状态…")

        if let st = try? await driver.fetchStatus(),
           let snap = GoProStatusSnapshot.parse(jsonBody: st.body) {
            lastStatusSnapshot = snap
            lastStatusSummary = snap.displayLine
        }

        // Give the camera a moment to flush the new still into the media list.
        emitProgress("② 等待 2s，让新照片写入媒体库…")
        try? await Task.sleep(nanoseconds: 2_000_000_000)

        emitProgress("③ 下载：拉取最新照片到手机…")
        let fetch = await fetchLatestPhoto(forceRedownload: true)
        let fetchResult = fetch.controllerResult
        guard fetchResult.ok else {
            emitProgress("③ 下载失败：\(fetchResult.message)")
            return .failure("download failed after shutter: \(fetchResult.message)")
        }
        guard let localPath = lastPhotoLocalPath?.trimmingCharacters(in: .whitespacesAndNewlines),
              !localPath.isEmpty else {
            emitProgress("③ 下载失败：无本地路径")
            return .failure("download failed after shutter: no local photo path")
        }
        emitProgress("③ 下载完成：\(URL(fileURLWithPath: localPath).lastPathComponent)")

        // Stay on GoPro AP: cloud upload/download uses cellular (no wait_wifi / home Wi‑Fi switch).
        emitProgress("④ 上传：仍在 GoPro 网，经蜂窝传到云…")
        let uploaded = await uploadPhoto(localPath: localPath)
        if !uploaded.ok {
            emitProgress("④ 上传失败：\(uploaded.message)")
            return .failure("upload failed: \(uploaded.message)\n(local: \(localPath))")
        }

        var outputs: [String: String] = ["photo_local_path": localPath]
        if let outs = uploaded.outputs {
            for (k, v) in outs {
                outputs[k] = v
            }
        }
        guard let photoURL = Self.cloudPhotoURL(outputs["photo_url"]) else {
            emitProgress("④ 上传成功但 photo_url 无效")
            return .failure(
                "upload ok but photo_url is not a cloud http(s) link "
                    + "(refusing local path)\n(local: \(localPath))\n\(uploaded.message)"
            )
        }
        outputs["photo_url"] = photoURL
        emitProgress("④ 上传完成：\(photoURL)")

        let message = """
        step shutter: ok
        step download: \(localPath)
        step upload: \(photoURL)
        """
        return .success(message, data: lastPhotoData, outputs: outputs)
    }

    private func emitProgress(_ message: String) {
        NSLog("%@", "[GoPro] \(message)")
        onProgress?(message)
        NotificationCenter.default.post(
            name: .goProPipelineProgress,
            object: nil,
            userInfo: ["message": message]
        )
    }

    /// Execute a queued server command for this device (e.g. `action=shutter` → photo capture).
    func executeCommand(action: String, command: [String: Any] = [:]) async -> ControllerResult {
        let normalizedAction = action.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch normalizedAction {
        case "shutter", "capture", "capture_photo", "photo":
            return await capturePhotoPipeline()
        case "start_recording", "record_start", "video_start":
            return await startRecording()
        case "stop_recording", "record_stop", "video_stop":
            return await stopRecording()
        case "status":
            return await fetchStatus()
        case "":
            return .failure("gopro executeCommand: missing action")
        default:
            let id = command["id"].map { "\($0)" } ?? "-"
            return .failure("gopro executeCommand: unsupported action '\(normalizedAction)' (id=\(id))")
        }
    }

    func startRecording() async -> ControllerResult {
        await map { try await driver.startRecording() }
    }

    func stopRecording() async -> ControllerResult {
        await map { try await driver.stopRecording() }
    }

    func joinCameraWiFi(ssid: String, password: String? = nil) async -> ControllerResult {
        do {
            try await driver.joinCameraWiFi(ssid: ssid, password: password)
            return .success("joined Wi‑Fi \(ssid)")
        } catch {
            return .failure(error.localizedDescription)
        }
    }

    // MARK: - CapabilityDriver surface (thin)

    func driverIdentity() async -> ControllerResult {
        let id = await driver.identity()
        let endpoint = id.endpoint ?? ""
        return .success("\(id.driverId) · \(id.displayName) · \(endpoint)")
    }

    func connectDriver() async -> ControllerResult {
        do {
            try await driver.connect()
            let st = await driver.status()
            return .success(st.summary)
        } catch {
            return .failure(error.localizedDescription)
        }
    }

    func disconnectDriver() async -> ControllerResult {
        do {
            try await driver.disconnect()
            let st = await driver.status()
            return .success(st.summary)
        } catch {
            return .failure(error.localizedDescription)
        }
    }

    func driverStatus() async -> ControllerResult {
        let st = await driver.status()
        return .success(st.summary)
    }

    func driverCapabilities() async -> ControllerResult {
        let caps = await driver.capabilities()
        return .success(caps.joined(separator: ", "))
    }

    /// Media list + download newest still via Driver; optional local save in Controller.
    /// - Parameters:
    ///   - forceRedownload: if false and (name+timestamp) already cached locally, returns `.alreadyDownloaded` without network download.
    func fetchLatestPhoto(forceRedownload: Bool = false) async -> LatestPhotoFetchResult {
        do {
            emitProgress("③ 下载：列出相机媒体…")
            let list = try await driver.fetchMediaList()
            guard let item = await driver.latestStillItem(fromMediaListJSON: list.body) else {
                return .failure("no media found on camera")
            }

            if !forceRedownload,
               let cached = Self.cachedLocalPath(for: item),
               FileManager.default.fileExists(atPath: cached) {
                lastPhotoLocalPath = cached
                lastPhotoData = try? Data(contentsOf: URL(fileURLWithPath: cached))
                emitProgress("③ 下载：使用本地缓存 \(item.name)")
                return .alreadyDownloaded(item: item, localPath: cached)
            }

            emitProgress("③ 下载：拉取 \(item.name.isEmpty ? "最新照片" : item.name)…")
            let file = try await driver.downloadMedia(path: item.path)
            let saved = try saveLocally(
                data: file.data,
                suggestedName: item.name.isEmpty ? "latest.jpg" : item.name
            )
            Self.rememberDownload(item: item, localPath: saved.path)
            lastPhotoData = file.data
            lastPhotoLocalPath = saved.path
            return .downloaded(
                ControllerResult.success(
                    "saved \(saved.path) · \(item.name) · ts=\(item.timestamp) · \(file.url)\n⏱ list \(list.durationLabel) · download \(file.durationLabel)",
                    data: file.data
                )
            )
        } catch {
            return .failure("fetchLatestPhoto failed: \(error.localizedDescription)")
        }
    }

    // MARK: - Non-camera (via RuntimeAgentSDK AssetManager)

    /// Prefer `localPath`, else `lastPhotoData` / `lastPhotoLocalPath`. Uploads through RuntimeAgentSDK.
    func uploadPhoto(localPath: String? = nil) async -> ControllerResult {
        do {
            let path = try await resolveLocalPhotoPath(preferred: localPath)
            let asset = Asset.make(type: .photo, location: path)
            let published = try await RuntimeAgentSDK.getEdgeRuntimeContext().assets.publish(asset)
            let assets = RuntimeAgentSDK.getEdgeRuntimeContext().assets
            let message = assets.lastMessage
            var outputs: [String: String] = ["photo_local_path": path]
            // photo_url must be the cloud public http(s) link — never a local file path.
            if let url = Self.cloudPhotoURL(assets.lastPublishUrl) {
                outputs["photo_url"] = url
            } else if let url = Self.cloudPhotoURL(published.id) {
                outputs["photo_url"] = url
            } else {
                return .failure(
                    "upload ok but no cloud photo_url (got local/empty); "
                        + "need http(s) from :8080\n(local: \(path))\n\(message)"
                )
            }
            if let savedAs = assets.lastPublishSavedAs, !savedAs.isEmpty {
                outputs["saved_as"] = savedAs
            }
            return .success(
                message.isEmpty ? "upload ok · \(path)" : message,
                outputs: outputs
            )
        } catch {
            return .failure(error.localizedDescription)
        }
    }

    /// Download newest photo via RuntimeAgentSDK AssetManager.
    func downloadLatestFromServer() async -> ControllerResult {
        do {
            let asset = try await RuntimeAgentSDK.getEdgeRuntimeContext().assets.fetchLatest(type: .photo)
            let path = asset.location
            lastPhotoLocalPath = path
            lastPhotoData = try? Data(contentsOf: URL(fileURLWithPath: path))
            let message = RuntimeAgentSDK.getEdgeRuntimeContext().assets.lastMessage
            return .success(
                message.isEmpty ? "downloaded → \(path)" : message,
                data: lastPhotoData
            )
        } catch {
            return .failure(error.localizedDescription)
        }
    }

    /// Resolve a local file path for publish; may materialize `lastPhotoData` to disk.
    private func resolveLocalPhotoPath(preferred: String?) async throws -> String {
        if let path = preferred?.trimmingCharacters(in: .whitespacesAndNewlines), !path.isEmpty {
            return path
        }
        if let existing = lastPhotoLocalPath?.trimmingCharacters(in: .whitespacesAndNewlines),
           !existing.isEmpty,
           FileManager.default.fileExists(atPath: existing) {
            return existing
        }
        if let data = lastPhotoData, !data.isEmpty {
            let name = lastPhotoLocalPath.map { ($0 as NSString).lastPathComponent } ?? "photo.jpg"
            let saved = try saveLocally(data: data, suggestedName: name)
            lastPhotoLocalPath = saved.path
            return saved.path
        }
        throw NSError(
            domain: "GoProController",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "no photo to upload; fetch latest photo first or pass local_path"]
        )
    }

    // MARK: - Helpers

    private func map(_ work: () async throws -> GoProDriver.HttpResult) async -> ControllerResult {
        do {
            let result = try await work()
            let body = result.body.isEmpty
                ? "(empty body, HTTP \(result.statusCode))"
                : result.body
            return .success("\(body)\n⏱ \(result.durationLabel)", data: result.data)
        } catch {
            return .failure("\(error.localizedDescription). Join GoPro Wi‑Fi first.")
        }
    }

    private func saveLocally(data: Data, suggestedName: String) throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let dir = docs.appendingPathComponent("GoProMedia", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let safe = suggestedName.replacingOccurrences(of: "/", with: "_")
        // Unique path each download so SwiftUI previews invalidate (same camera filename would overwrite).
        let stamped = "\(Int(Date().timeIntervalSince1970))_\(safe)"
        let url = dir.appendingPathComponent(stamped)
        try data.write(to: url, options: .atomic)
        return url
    }

    private static var downloadIndexURL: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        return docs.appendingPathComponent("GoProMedia/download_index.json")
    }

    private static func loadDownloadIndex() -> [String: String] {
        guard let data = try? Data(contentsOf: downloadIndexURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
            return [:]
        }
        return obj
    }

    private static func cachedLocalPath(for item: GoProMediaItem) -> String? {
        loadDownloadIndex()[item.cacheKey]
    }

    private static func rememberDownload(item: GoProMediaItem, localPath: String) {
        var index = loadDownloadIndex()
        index[item.cacheKey] = localPath
        if let data = try? JSONSerialization.data(withJSONObject: index, options: [.prettyPrinted]) {
            try? FileManager.default.createDirectory(
                at: downloadIndexURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try? data.write(to: downloadIndexURL, options: .atomic)
        }
    }

    /// Accept only cloud http(s) photo URLs — never `file://` or sandbox paths.
    private static func cloudPhotoURL(_ raw: String?) -> String? {
        let value = (raw ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        let lower = value.lowercased()
        guard lower.hasPrefix("http://") || lower.hasPrefix("https://") else { return nil }
        // GoPro AP media root is not a cloud link.
        if lower.contains("10.5.5.9") { return nil }
        return value
    }
}

extension Notification.Name {
    /// Posted while `camera.capture` waits for the user to leave GoPro Wi‑Fi.
    static let goProPipelineProgress = Notification.Name("LivingRoomEdge.GoProPipelineProgress")
}

/// Result of resolving / downloading the newest still.
enum LatestPhotoFetchResult {
    case downloaded(ControllerResult)
    case alreadyDownloaded(item: GoProMediaItem, localPath: String)
    case failed(String)

    static func failure(_ message: String) -> LatestPhotoFetchResult { .failed(message) }

    var controllerResult: ControllerResult {
        switch self {
        case let .downloaded(r):
            return r
        case let .alreadyDownloaded(item, path):
            return .success("already downloaded \(item.name) ts=\(item.timestamp) · \(path)")
        case let .failed(m):
            return .failure(m)
        }
    }
}
