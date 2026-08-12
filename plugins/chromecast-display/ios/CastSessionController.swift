import Foundation
import GoogleCast
import Network

/// Cast Sender helpers: discovery, session, custom HTML receiver launch,
/// photo cast via custom namespace message (`urn:x-cast:local.image`).
/// Google Cast SDK requires discovery / session APIs on the main thread.
@MainActor
final class CastSessionController: NSObject {
    static let shared = CastSessionController()

    /// Custom Cast receiver application ID (CAF / registered in Cast Developer Console).
    /// Used when starting a session — not for discovery filtering.
    static let receiverAppID = "F7649303"

    /// Custom channel for photo URLs (Receiver HTML must listen on this namespace).
    static let imageMessageNamespace = "urn:x-cast:local.image"

    /// Discovery uses the Default Media Receiver so Chromecasts appear even when the
    /// custom receiver is unpublished / not yet associated with the device.
    /// (`GCKDiscoveryCriteria(applicationID:)` only lists devices that advertise that app.)
    private static let discoveryAppID = kGCKDefaultMediaReceiverApplicationID

    /// Session options key (Cast SDK internal; documented via setDefaultSessionOptions).
    private static let sessionAppIDKey = "gck_applicationID"

    private let lastDeviceKey = "chromecast.display.lastDeviceId"
    private var configured = false
    /// GCK listeners are weak — keep bridges alive until callbacks fire.
    private var pendingSessionBridge: SessionStartBridge?
    private var pendingSessionEndBridge: SessionEndBridge?
    private var progressHandler: ((String) -> Void)?
    /// After a receiver-side load failure, next cast rebuilds the session.
    private var preferFreshSession = false
    /// Strong ref for the custom image channel (session holds channels weakly).
    private var imageChannel: LocalImageCastChannel?
    /// Keep factory alive (unregistered — used only to synthesize Cast-category devices).
    private let deviceFactory = CastDeviceFactory.shared

    /// Session start budget for launching a receiver app (custom CAF can be slow).
    private static let sessionStartTimeout: TimeInterval = 45

    private override init() {
        super.init()
    }

    /// Call once at app launch (before any cast).
    func configureIfNeeded() {
        guard !configured else { return }
        let criteria = GCKDiscoveryCriteria(applicationID: Self.discoveryAppID)
        let options = GCKCastOptions(discoveryCriteria: criteria)
        options.physicalVolumeButtonsWillControlDeviceVolume = true
        options.disableDiscoveryAutostart = false
        // Custom picker (no GCKUICastButton) — start discovery immediately, not after first tap.
        options.startDiscoveryAfterFirstTapOnCastButton = false
        // Avoid noisy timeouts to play.googleapis.com/log (often unreachable).
        options.disableAnalyticsLogging = true
        let launch = GCKLaunchOptions()
        launch.relaunchIfRunning = true
        options.launchOptions = launch
        // Avoid double-init crash if something else already configured Cast.
        if !GCKCastContext.isSharedInstanceInitialized() {
            GCKCastContext.setSharedInstanceWith(options)
        }
        configured = true
        // Sessions always launch custom receiver F7649303 (photo + launch-only paths).
        let sessions = GCKCastContext.sharedInstance().sessionManager
        sessions.setDefaultSessionOptions(
            Self.sessionOptions(appID: Self.receiverAppID),
            forDeviceCategory: kGCKCastDeviceCategory
        )
        // Do NOT register a custom GCKDeviceProvider — synthetic devices use
        // kGCKCastDeviceCategory via CastDeviceFactory so the built-in Cast provider
        // owns session creation (custom categories commonly hang on startSession).
        _ = deviceFactory
        let discovery = GCKCastContext.sharedInstance().discoveryManager
        // Active scan finds devices more reliably after Wi‑Fi changes.
        discovery.passiveScan = false
        if !discovery.discoveryActive {
            discovery.startDiscovery()
        }
        // Force iOS Local Network permission prompt via Bonjour browse (Cast alone may not).
        LocalNetworkAccessTrigger.shared.ping(keepAliveSeconds: 60)
        logDiscoveryState(reason: "configure")
        NSLog(
            "%@",
            "[CastSession] GCKCastContext configured discoveryAppID=\(Self.discoveryAppID) "
                + "sessionAppID=\(Self.receiverAppID)"
        )
    }

    /// Options that force session launch to use a specific receiver app ID.
    /// ObjC `GCKSessionOptions` is a typedef of `NSDictionary<NSString *, NSObject<NSCoding> *>`
    /// and imports in Swift as this dictionary type (not a named `GCKSessionOptions` type).
    private static func sessionOptions(appID: String) -> [String: any NSCoding & NSObjectProtocol] {
        [sessionAppIDKey: appID as NSString]
    }

    /// Explicitly trigger the system Local Network permission sheet (if still undecided),
    /// then force Cast discovery and Bonjour resolve.
    func requestLocalNetworkPermission() {
        configureIfNeeded()
        LocalNetworkAccessTrigger.shared.ping(keepAliveSeconds: 60)
        ensureDiscoveryRunning(reason: "request local network")
        logDiscoveryState(reason: "request local network")
    }

    /// How many Cast devices discovery currently sees (0 if not configured / none found).
    func discoveredDeviceCount() -> Int {
        configureIfNeeded()
        guard GCKCastContext.isSharedInstanceInitialized() else { return 0 }
        return Int(GCKCastContext.sharedInstance().discoveryManager.deviceCount)
    }

    /// Refresh discovery and return Cast SDK + raw Bonjour diagnostics for the debug UI.
    func refreshDiscovery(waitSeconds: TimeInterval = 10) async -> String {
        configureIfNeeded()
        // Keep discovery running — do not stopDiscovery (can leave SDK stuck empty).
        ensureDiscoveryRunning(reason: "manual refresh")
        LocalNetworkAccessTrigger.shared.ping(keepAliveSeconds: max(20, waitSeconds + 8))
        logDiscoveryState(reason: "refresh start")

        let deadline = Date().addingTimeInterval(max(8, waitSeconds))
        var bonjourNames: [String] = []
        while Date() < deadline {
            bonjourNames = LocalNetworkAccessTrigger.shared.seenInstanceNames
            let castNames = discoveredDeviceNames()
            if !castNames.isEmpty {
                logDiscoveryState(reason: "refresh success")
                return "Cast SDK 已发现 \(castNames.count) 台: \(castNames.joined(separator: ", "))"
            }
            // Bonjour+IP is enough for IP fallback cast even if SDK list stays empty.
            if !LocalNetworkAccessTrigger.shared.seenDevices.isEmpty {
                let hosts = LocalNetworkAccessTrigger.shared.seenDevices
                    .map { "\($0.name)@\($0.host)" }
                    .joined(separator: ", ")
                return "Bonjour/IP 可用（SDK 列表仍可为空）: \(hosts) — 投屏将走 IP 回退连接"
            }
            try? await Task.sleep(nanoseconds: 400_000_000)
        }

        let castNames = discoveredDeviceNames()
        if !castNames.isEmpty {
            return "Cast SDK 已发现 \(castNames.count) 台: \(castNames.joined(separator: ", "))"
        }
        bonjourNames = LocalNetworkAccessTrigger.shared.seenInstanceNames
        let hosts = LocalNetworkAccessTrigger.shared.seenDevices.map { "\($0.name)@\($0.host)" }
        let fallback = CastDeviceFactory.defaultFallbackHost
        logDiscoveryState(reason: "refresh empty")
        if !bonjourNames.isEmpty {
            return """
            Bonjour OK（\(bonjourNames.count) 台: \(bonjourNames.joined(separator: ", "))）\
            \(hosts.isEmpty ? "" : " IP: \(hosts.joined(separator: ", "))")，\
            内置 Cast SDK 列表仍为空。投屏将用 IP 回退（\(fallback):8009）。\
            若 session 仍失败：确认本地网络已允许；自定义 Receiver \(Self.receiverAppID) 需在 Cast Console 发布。
            """
        }
        return """
        未发现 Chromecast（Cast SDK 与 Bonjour 皆空）。
        请检查：① iPhone 与 Chromecast 同一 Wi‑Fi（不要连 GoPro）\
        ② 设置→隐私与安全性→本地网络→本 App 打开（没有条目则删 App 重装后再点「请求本地网络权限」）\
        ③ 仍可尝试直连 \(fallback):8009
        """
    }

    func discoveredDeviceNames() -> [String] {
        configureIfNeeded()
        guard GCKCastContext.isSharedInstanceInitialized() else { return [] }
        return deviceList(GCKCastContext.sharedInstance().discoveryManager).map {
            $0.friendlyName ?? $0.uniqueID
        }
    }

    /// Keep discovery continuously running after configure. Never stop during cast wait.
    private func ensureDiscoveryRunning(reason: String) {
        guard GCKCastContext.isSharedInstanceInitialized() else { return }
        let discovery = GCKCastContext.sharedInstance().discoveryManager
        discovery.passiveScan = false
        if !discovery.discoveryActive {
            discovery.startDiscovery()
            NSLog("%@", "[CastSession] discovery started (\(reason))")
        } else {
            NSLog("%@", "[CastSession] discovery already active (\(reason))")
        }
    }

    private func logDiscoveryState(reason: String) {
        guard GCKCastContext.isSharedInstanceInitialized() else {
            NSLog("%@", "[CastSession] discovery state (\(reason)): context not initialized")
            return
        }
        let discovery = GCKCastContext.sharedInstance().discoveryManager
        let bonjour = LocalNetworkAccessTrigger.shared.seenInstanceNames
        let hosts = LocalNetworkAccessTrigger.shared.seenDevices
            .map { "\($0.name)=\($0.host):\($0.port)" }
            .joined(separator: ", ")
        NSLog(
            "%@",
            "[CastSession] discovery state (\(reason)): "
                + "active=\(discovery.discoveryActive) "
                + "deviceCount=\(discovery.deviceCount) "
                + "passive=\(discovery.passiveScan) "
                + "bonjour=[\(bonjour.joined(separator: ", "))] "
                + "resolved=[\(hosts)]"
        )
    }

    /// Launch custom HTML Receiver (`F7649303`) only — no message, no DMR fallback.
    /// TV should show the static HTML registered as Receiver URL in Cast Developer Console.
    func launchCustomReceiver(
        timeoutSeconds: TimeInterval = 45,
        onProgress: ((String) -> Void)? = nil
    ) async -> ControllerResult {
        progressHandler = onProgress
        defer { progressHandler = nil }

        configureIfNeeded()
        ensureDiscoveryRunning(reason: "launchCustomReceiver")
        LocalNetworkAccessTrigger.shared.ping(keepAliveSeconds: 40)

        note("启动自定义 Receiver \(Self.receiverAppID)（仅 App ID，不发图片消息，不回退 DMR）…")
        do {
            try await ensureCastSession(timeoutSeconds: timeoutSeconds, forceRestart: true)
            preferFreshSession = false
            let deviceName = GCKCastContext.sharedInstance().sessionManager.currentCastSession?.device.friendlyName
                ?? "Chromecast"
            note("自定义 Receiver \(Self.receiverAppID) 已在 \(deviceName) 上运行")
            return .success(
                """
                自定义 Receiver \(Self.receiverAppID) 已启动 · \(deviceName)
                TV 应显示 Cast Console 登记的 Receiver URL 对应的 HTML（不是 iPhone 里填的 photo_url）。
                若画面空白：检查 Console 里 Receiver URL 是否可被 Chromecast 访问（建议 HTTPS；局域网 http:// 常被拦）。
                """
            )
        } catch {
            preferFreshSession = true
            await endCurrentSession(reason: "launch custom receiver failed")
            return .failure(Self.formatCustomReceiverFailure(error))
        }
    }

    /// Cast a photo URL to the custom HTML Receiver via `urn:x-cast:local.image` (not loadMedia / DMR).
    /// - Parameter onProgress: optional step logs for UI (discovery / session / message).
    func castPhoto(
        urlString: String,
        timeoutSeconds: TimeInterval = 35,
        onProgress: ((String) -> Void)? = nil
    ) async -> ControllerResult {
        progressHandler = onProgress
        defer { progressHandler = nil }

        configureIfNeeded()
        // Warm Bonjour / Cast discovery before URL probe (helps after GoPro Wi‑Fi switch).
        ensureDiscoveryRunning(reason: "castPhoto")
        LocalNetworkAccessTrigger.shared.ping(keepAliveSeconds: 40)

        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https" else {
            return .failure("cast failed: invalid photo_url \(urlString)")
        }

        note("1/4 解析 / 检查图片 URL…")
        var playable: URL
        do {
            playable = try await resolvePlayablePhotoURL(url)
        } catch {
            return .failure(
                """
                cast failed: \(error.localizedDescription)
                原始 url: \(trimmed)
                请使用可直接打开的图片地址（如 http://host:8080/img/xxx.JPG、/xxx.JPG 或 /latest）
                """
            )
        }
        if playable.absoluteString != url.absoluteString {
            note("1/4 已解析为直接图片 URL\n\(playable.absoluteString)")
        }
        if let probeError = await probePhotoURL(playable) {
            // home-img-server: SimpleHTTP needs /img/{file}; Flask accepts both.
            // Never strip a working /img/ path — only retry the alternate form on probe failure.
            if let alt = Self.alternateHomeImgURL(playable),
               await probePhotoURL(alt) == nil
            {
                NSLog(
                    "%@",
                    "[CastSession] probe fallback \(playable.absoluteString) → \(alt.absoluteString)"
                )
                note("1/4 路径回退成功\n\(alt.absoluteString)")
                playable = alt
            } else {
                return .failure(
                    """
                    cast failed: iPhone 无法打开图片 URL（Chromecast / Receiver 也需要能访问）
                    \(probeError)
                    url: \(playable.absoluteString)
                    """
                )
            }
        }
        note("1/4 图片 URL 可达（GET/Range probe OK）")

        do {
            let sessions = GCKCastContext.sharedInstance().sessionManager
            let canReuse = sessions.hasConnectedCastSession() && isCustomReceiverSession(sessions.currentCastSession)
            let forceRestart = preferFreshSession || !canReuse
            if forceRestart {
                note("2/4 准备自定义 Receiver session \(Self.receiverAppID)…")
            } else {
                note("2/4 复用已连接自定义 Receiver session…")
            }
            try await ensureCastSession(
                timeoutSeconds: timeoutSeconds,
                forceRestart: forceRestart
            )
            preferFreshSession = false
            let deviceName = GCKCastContext.sharedInstance().sessionManager.currentCastSession?.device.friendlyName
                ?? "Chromecast"
            note("2/4 已连接 \(deviceName) · app=\(Self.receiverAppID)")

            note("3/4 等待自定义通道 \(Self.imageMessageNamespace)…")
            let channel = try await ensureImageChannel(timeoutSeconds: 12)
            note("3/4 通道就绪（writable）")

            // Optional cache-bust so Receiver <img> reloads when re-casting the same path.
            let playURL = Self.cacheBustedURL(playable)
            note("4/4 发送图片 URL 消息…\n\(playURL.absoluteString)")
            try sendLocalImageMessage(url: playURL, on: channel)
            note("4/4 已发送 \(Self.imageMessageNamespace) {\"url\":…}")

            return .success(
                """
                cast ok · \(deviceName) · \(Self.receiverAppID)
                namespace: \(Self.imageMessageNamespace)
                payload: {"url":"\(playURL.absoluteString)"}
                提示: Receiver HTML 须监听该 namespace 并自行拉图；大 JPG 显示速度取决于 Chromecast 下载网速。
                """
            )
        } catch {
            preferFreshSession = true
            await endCurrentSession(reason: "cast failed cleanup")
            let detail = error.localizedDescription
            if Self.looksLikeApplicationNotFound(detail) {
                return .failure(Self.formatCustomReceiverFailure(error))
            }
            return .failure("cast failed: \(detail)")
        }
    }

    /// Surface exact Cast error + Console checklist when custom receiver launch fails.
    private static func formatCustomReceiverFailure(_ error: Error) -> String {
        let detail = error.localizedDescription
        return """
        自定义 Receiver \(receiverAppID) 启动失败（图片投屏不回退 Default Media Receiver；DMR 无法收 \(imageMessageNamespace)）。
        错误: \(detail)

        Cast Developer Console 检查清单：
        ① Application ID \(receiverAppID) 存在，类型为 Custom / CAF
        ② Receiver URL 指向你的静态 HTML（建议 HTTPS；局域网 http://192.168.x.x 常被 Cast 拒绝）
        ③ App 已 Published，或 Chromecast 序列号已加入测试设备（unpublished 必填）
        ④ 变更后等待数分钟传播；必要时重启 Chromecast
        ⑤ 测试时 Chromecast 登录与 Console 同一 Google 账号（若 Console 要求）
        ⑥ Receiver HTML 须监听 namespace \(imageMessageNamespace) 并处理 {"url":"…"}
        """
    }

    private static func looksLikeApplicationNotFound(_ detail: String) -> Bool {
        let lower = detail.lowercased()
        if lower.contains("application"),
           lower.contains("not found") || lower.contains("notfound") || lower.contains("could not be found")
        {
            return true
        }
        return detail.contains("Application launch failed")
    }

    /// True when the connected Cast session is running our custom receiver app.
    private func isCustomReceiverSession(_ session: GCKCastSession?) -> Bool {
        guard let session else { return false }
        guard let appID = session.applicationMetadata?.applicationID else { return false }
        return appID == Self.receiverAppID
    }

    /// Tear down Cast session (UI / recovery).
    func disconnect() {
        Task { @MainActor in
            await endCurrentSession(reason: "user disconnect")
        }
    }

    private func note(_ message: String) {
        NSLog("%@", "[CastSession] \(message)")
        progressHandler?(message)
    }

    // MARK: - Session

    private func ensureCastSession(
        timeoutSeconds: TimeInterval,
        forceRestart: Bool
    ) async throws {
        let sessions = GCKCastContext.sharedInstance().sessionManager
        if !forceRestart,
           sessions.hasConnectedCastSession(),
           isCustomReceiverSession(sessions.currentCastSession)
        {
            note("复用已有自定义 Receiver session")
            return
        }

        var restart = forceRestart || sessions.hasConnectedCastSession()
        var lastError: Error = CastError.sessionFailed("start session failed")
        // After GoPro Wi‑Fi switch, first start often times out; retry with rediscovery.
        for attempt in 1 ... 3 {
            if restart || sessions.currentSession != nil || sessions.currentCastSession != nil {
                await endCurrentSession(reason: "restart before cast (try \(attempt))")
                try await Task.sleep(nanoseconds: attempt == 1 ? 800_000_000 : 1_200_000_000)
            } else if sessions.hasConnectedCastSession(),
                      isCustomReceiverSession(sessions.currentCastSession)
            {
                note("复用已有自定义 Receiver session")
                return
            }

            // Per-attempt budget: leave room for session connect after discovery.
            let discoverBudget = min(max(timeoutSeconds, 30), attempt == 1 ? 30 : 35)
            do {
                let device = try await discoverDevice(timeoutSeconds: discoverBudget)
                let host = device.networkAddress.ipAddress
                    ?? device.ipAddress
                    ?? CastDeviceFactory.defaultFallbackHost
                note(
                    "选中设备: \(device.friendlyName ?? "(unnamed)") "
                        + "id=\(device.deviceID) cat=\(device.category) "
                        + "\(host):\(device.servicePort) (try \(attempt)/3)"
                )

                if let probeError = await probeCastPort(host: host, port: device.servicePort) {
                    throw CastError.deviceUnreachable("\(host):\(device.servicePort) — \(probeError)")
                }
                note("Cast 控制口 \(host):\(device.servicePort) 可达")

                // Brief settle so mDNS / route is stable after hotspot → home Wi‑Fi.
                try await Task.sleep(nanoseconds: 400_000_000)
                try await startCustomReceiverSession(device: device)
                UserDefaults.standard.set(device.uniqueID, forKey: lastDeviceKey)
                if GCKCastContext.sharedInstance().sessionManager.currentCastSession == nil {
                    throw CastError.sessionFailed("session callback fired but currentCastSession is nil")
                }
                return
            } catch {
                lastError = error
                note("Cast session try \(attempt)/3 failed: \(error.localizedDescription)")
                restart = true
                preferFreshSession = true
            }
        }
        throw lastError
    }

    /// Start Cast session for F7649303 only — no Default Media Receiver fallback.
    private func startCustomReceiverSession(device: GCKDevice) async throws {
        let castDevice = normalizeToCastCategoryDevice(device)
        let host = castDevice.networkAddress.ipAddress
            ?? castDevice.ipAddress
            ?? CastDeviceFactory.defaultFallbackHost

        note(
            "启动 session → 自定义 Receiver \(Self.receiverAppID) "
                + "（gck_applicationID，最多 \(Int(Self.sessionStartTimeout))s）…"
        )
        do {
            try await startSession(
                with: castDevice,
                appID: Self.receiverAppID,
                timeoutSeconds: Self.sessionStartTimeout
            )
            note("已连接自定义 Receiver \(Self.receiverAppID)")
        } catch {
            throw CastError.sessionFailed(
                """
                Application launch failed for \(Self.receiverAppID).
                \(error.localizedDescription)
                设备: \(castDevice.friendlyName ?? castDevice.deviceID) \(host):\(castDevice.servicePort)
                （未回退 Default Media Receiver）
                """
            )
        }
    }

    /// Ensure device category is Cast so SessionManager uses the built-in provider.
    private func normalizeToCastCategoryDevice(_ device: GCKDevice) -> GCKDevice {
        let resolvedHost: String = {
            if let ip = device.networkAddress.ipAddress, !ip.isEmpty { return ip }
            if !device.ipAddress.isEmpty { return device.ipAddress }
            return CastDeviceFactory.defaultFallbackHost
        }()
        let hasIP = !(device.networkAddress.ipAddress ?? "").isEmpty || !device.ipAddress.isEmpty
        if device.category == kGCKCastDeviceCategory,
           device.servicePort == CastDeviceFactory.castPort,
           hasIP
        {
            return device
        }
        return deviceFactory.makeDevice(
            deviceID: device.deviceID,
            host: resolvedHost,
            friendlyName: device.friendlyName
        )
    }

    private func startSession(
        with device: GCKDevice,
        appID: String,
        timeoutSeconds: TimeInterval
    ) async throws {
        let sessions = GCKCastContext.sharedInstance().sessionManager
        // Already connected to this device — treat as success (resume path).
        if sessions.hasConnectedCastSession(),
           sessions.currentCastSession?.device.uniqueID == device.uniqueID
        {
            note("session 已连接到目标设备")
            return
        }

        sessions.setDefaultSessionOptions(
            Self.sessionOptions(appID: appID),
            forDeviceCategory: kGCKCastDeviceCategory
        )

        let host = device.networkAddress.ipAddress ?? device.ipAddress ?? "?"
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            let bridge = SessionStartBridge(
                continuation: cont,
                sessionManager: sessions,
                timeoutSeconds: timeoutSeconds,
                contextLabel: "app=\(appID) device=\(device.friendlyName ?? device.deviceID) \(host):\(device.servicePort)"
            ) { [weak self] in
                self?.pendingSessionBridge = nil
            }
            self.pendingSessionBridge = bridge
            sessions.add(bridge)
            // If Cast already has a connecting/suspended session, startSession may resume
            // and fire didResumeCastSession instead of didStart — bridge handles both.
            let started = sessions.startSession(
                with: device,
                sessionOptions: Self.sessionOptions(appID: appID)
            )
            note("startSession(app=\(appID)) returned \(started)")
            if !started {
                // Might already be connecting; give the bridge time, or fail fast if idle.
                if sessions.hasConnectedCastSession() {
                    bridge.completeSuccess()
                } else if sessions.currentSession != nil || sessions.currentCastSession != nil {
                    note("startSession 返回 false，等待已有 session 回调…")
                } else {
                    sessions.remove(bridge)
                    self.pendingSessionBridge = nil
                    cont.resume(throwing: CastError.sessionStartRejected)
                }
            }
        }
    }

    /// Quick TCP probe to Cast control port (8009) before waiting on SDK callbacks.
    private func probeCastPort(host: String, port: UInt16) async -> String? {
        await withCheckedContinuation { cont in
            let nwPort = NWEndpoint.Port(rawValue: port) ?? 8009
            let connection = NWConnection(
                host: NWEndpoint.Host(host),
                port: nwPort,
                using: .tcp
            )
            var resumed = false
            let finish: (String?) -> Void = { result in
                guard !resumed else { return }
                resumed = true
                connection.cancel()
                cont.resume(returning: result)
            }
            connection.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    finish(nil)
                case let .failed(error):
                    finish(error.localizedDescription)
                case .cancelled:
                    break
                default:
                    break
                }
            }
            connection.start(queue: .main)
            DispatchQueue.main.asyncAfter(deadline: .now() + 4) {
                finish("TCP connect timed out (4s)")
            }
        }
    }

    private func endCurrentSession(reason: String) async {
        let sessions = GCKCastContext.sharedInstance().sessionManager
        if let channel = imageChannel, let cast = sessions.currentCastSession {
            cast.remove(channel)
        }
        imageChannel = nil
        guard sessions.currentSession != nil || sessions.currentCastSession != nil else {
            note("无活动 session（\(reason)）")
            return
        }
        note("结束 Cast session… (\(reason))")
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            let bridge = SessionEndBridge(continuation: cont, sessionManager: sessions) { [weak self] in
                self?.pendingSessionEndBridge = nil
            }
            self.pendingSessionEndBridge = bridge
            sessions.add(bridge)
            let stopped = sessions.endSessionAndStopCasting(true)
            if !stopped {
                // Already ending / no session — don't hang.
                sessions.remove(bridge)
                self.pendingSessionEndBridge = nil
                cont.resume()
            }
        }
    }

    private func discoverDevice(timeoutSeconds: TimeInterval) async throws -> GCKDevice {
        ensureDiscoveryRunning(reason: "before select device")
        LocalNetworkAccessTrigger.shared.ping(keepAliveSeconds: max(40, timeoutSeconds + 10))
        logDiscoveryState(reason: "discover start")

        let discovery = GCKCastContext.sharedInstance().discoveryManager
        let budget = max(timeoutSeconds, 35)
        let startedAt = Date()
        let deadline = startedAt.addingTimeInterval(budget)
        let preferredId = UserDefaults.standard.string(forKey: lastDeviceKey)
        var lastCount = -1
        var firstSeenAt: Date?
        var didLogFallback = false

        note("正在发现 Chromecast（最多 \(Int(budget))s，需本地网络权限）…")
        while Date() < deadline {
            let elapsed = Date().timeIntervalSince(startedAt)

            // Prefer native Cast SDK devices when available.
            var devices = deviceList(discovery)
            // After 4s (or immediately if Bonjour already has hosts), synthesize Cast-category devices.
            if devices.isEmpty, elapsed >= 4 || !LocalNetworkAccessTrigger.shared.seenDevices.isEmpty
                || !LocalNetworkAccessTrigger.shared.seenInstanceNames.isEmpty
            {
                if !didLogFallback {
                    note("内置 Cast 列表空/不足，使用 Bonjour→IP 合成 GCKDevice（category=Cast）…")
                    didLogFallback = true
                    logDiscoveryState(reason: "bonjour IP fallback")
                }
                devices = deviceFactory.makeDevicesFromBonjour()
            }

            if devices.count != lastCount {
                lastCount = devices.count
                let names = devices.map { $0.friendlyName ?? "(unnamed)" }.joined(separator: ", ")
                note("发现 \(devices.count) 台: \(names.isEmpty ? "（空）" : names)")
            }
            if !devices.isEmpty, firstSeenAt == nil {
                firstSeenAt = Date()
            }
            if let preferredId,
               let match = devices.first(where: {
                   $0.uniqueID == preferredId || $0.deviceID == preferredId
               })
            {
                return normalizeToCastCategoryDevice(match)
            }
            // Wait ~1.0s after first sighting so mDNS list can settle.
            if let first = devices.first, let seen = firstSeenAt {
                if Date().timeIntervalSince(seen) >= 1.0 || devices.count > 1 {
                    return normalizeToCastCategoryDevice(first)
                }
            }
            try await Task.sleep(nanoseconds: 300_000_000)
        }

        // Final attempt: known LAN IP even if Bonjour went quiet.
        let fallbackDevices = deviceFactory.makeDevicesFromBonjour()
        if let first = fallbackDevices.first {
            note(
                "发现超时，使用 IP 回退设备 "
                    + "\(first.friendlyName ?? first.deviceID) "
                    + "\(first.networkAddress.ipAddress ?? CastDeviceFactory.defaultFallbackHost):8009"
            )
            return first
        }

        let bonjour = LocalNetworkAccessTrigger.shared.seenInstanceNames
        logDiscoveryState(reason: "discover timeout")
        if !bonjour.isEmpty {
            throw CastError.bonjourOkSdkEmpty(bonjour.joined(separator: ", "))
        }
        throw CastError.noDeviceFound
    }

    private func deviceList(_ discovery: GCKDiscoveryManager) -> [GCKDevice] {
        var devices: [GCKDevice] = []
        let count = Int(discovery.deviceCount)
        guard count > 0 else { return devices }
        for i in 0 ..< count {
            devices.append(discovery.device(at: UInt(i)))
        }
        return devices
    }

    // MARK: - Custom image channel (`urn:x-cast:local.image`)

    private func ensureImageChannel(timeoutSeconds: TimeInterval) async throws -> LocalImageCastChannel {
        guard let castSession = GCKCastContext.sharedInstance().sessionManager.currentCastSession else {
            throw CastError.sessionFailed("no currentCastSession for image channel")
        }
        if let appID = castSession.applicationMetadata?.applicationID, appID != Self.receiverAppID {
            throw CastError.sessionFailed(
                "当前 session 是 \(appID)，图片消息需要自定义 Receiver \(Self.receiverAppID)"
            )
        }

        if let existing = imageChannel,
           existing.protocolNamespace == Self.imageMessageNamespace,
           existing.isConnected,
           existing.isWritable
        {
            return existing
        }

        if let old = imageChannel {
            castSession.remove(old)
            imageChannel = nil
        }
        let channel = LocalImageCastChannel(namespace: Self.imageMessageNamespace)
        imageChannel = channel
        castSession.add(channel)
        note("已添加 GCKCastChannel namespace=\(Self.imageMessageNamespace)")
        try await waitForChannelWritable(channel, timeoutSeconds: timeoutSeconds)
        return channel
    }

    private func waitForChannelWritable(_ channel: GCKCastChannel, timeoutSeconds: TimeInterval) async throws {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            if channel.isConnected, channel.isWritable {
                return
            }
            try await Task.sleep(nanoseconds: 150_000_000)
        }
        throw CastError.channelFailed(
            """
            自定义通道未就绪（connected=\(channel.isConnected) writable=\(channel.isWritable)，\(Int(timeoutSeconds))s）
            namespace: \(Self.imageMessageNamespace)
            Receiver HTML 必须 cast.framework 监听该 namespace，否则通道不可写
            """
        )
    }

    private func sendLocalImageMessage(url: URL, on channel: GCKCastChannel) throws {
        let payload: [String: String] = ["url": url.absoluteString]
        let data = try JSONSerialization.data(withJSONObject: payload, options: [])
        guard let message = String(data: data, encoding: .utf8) else {
            throw CastError.channelFailed("failed to encode {\"url\":…} JSON")
        }
        note("sendTextMessage \(Self.imageMessageNamespace) → \(message)")
        var sendError: GCKError?
        let ok = channel.sendTextMessage(message, error: &sendError)
        if !ok {
            throw CastError.channelFailed(
                "sendTextMessage failed: \(sendError?.localizedDescription ?? "unknown") — payload \(message)"
            )
        }
    }

    private static func cacheBustedURL(_ url: URL) -> URL {
        guard var comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return url }
        var items = comps.queryItems ?? []
        items.removeAll { $0.name == "cast_ts" }
        items.append(URLQueryItem(name: "cast_ts", value: String(Int(Date().timeIntervalSince1970))))
        comps.queryItems = items
        return comps.url ?? url
    }

    private static let imagePathExtensions: Set<String> = [
        "jpg", "jpeg", "png", "gif", "webp", "heic",
    ]

    /// Prefer a direct still URL (path ends with .JPG etc.) before sending to the Receiver.
    /// Bare `http://host:8080`, `/latest`, or `download_latest` are resolved first.
    /// home-img-server: files on disk under `./img/`. Prefer HTTP `/img/{saved_as}`
    /// (works with pna_httpd / SimpleHTTP); Flask also serves bare `/{saved_as}`.
    /// Never strip `/img/` from a user-provided still URL.
    private func resolvePlayablePhotoURL(_ url: URL) async throws -> URL {
        let path = url.path
        let ext = url.pathExtension.lowercased()
        if Self.imagePathExtensions.contains(ext) {
            return url
        }

        guard var baseComps = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            throw CastError.loadFailed("invalid photo_url")
        }
        baseComps.path = ""
        baseComps.query = nil
        baseComps.fragment = nil
        guard let base = baseComps.url else {
            throw CastError.loadFailed("invalid photo_url base")
        }

        let normalizedPath = path.hasSuffix("/") ? String(path.dropLast()) : path
        let needsResolve =
            normalizedPath.isEmpty
            || normalizedPath == "/"
            || normalizedPath.lowercased() == "/latest"
            || normalizedPath.lowercased().hasSuffix("/download_latest")
            || normalizedPath.lowercased().hasSuffix("/api/v1/photos/download_latest")
            || !Self.imagePathExtensions.contains(ext)

        guard needsResolve else { return url }

        note("URL 不是直接图片路径，解析最新图…\n\(url.absoluteString)")

        if let metaURL = URL(string: "/api/v1/photos/latest", relativeTo: base)?.absoluteURL,
           let resolved = await fetchLatestPhotoURL(from: metaURL)
        {
            return resolved
        }

        if let latestURL = URL(string: "/latest", relativeTo: base)?.absoluteURL,
           let resolved = await followRedirectToImageURL(latestURL)
        {
            return resolved
        }

        // Last resort: follow redirects from the original URL (e.g. Flask `/` → /file.JPG).
        if let resolved = await followRedirectToImageURL(url) {
            return resolved
        }

        throw CastError.loadFailed(
            """
            无法解析为图片 URL（当前像是站点根路径或非图片接口）
            请改用: \(base.absoluteString)/latest
            或直接: \(base.absoluteString)/某个文件.JPG
            并确认 Mac 上跑的是 home-img-server 的 `python app.py`（不是 http.server）
            """
        )
    }

    private func fetchLatestPhotoURL(from metaURL: URL) async -> URL? {
        var request = URLRequest(url: metaURL)
        request.httpMethod = "GET"
        request.timeoutInterval = 8
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse,
                  (200 ..< 300).contains(http.statusCode),
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let urlString = (obj["url"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines),
                  let resolved = URL(string: urlString),
                  Self.imagePathExtensions.contains(resolved.pathExtension.lowercased())
            else {
                return nil
            }
            return resolved
        } catch {
            return nil
        }
    }

    /// Follow redirects without downloading the full image body.
    private func followRedirectToImageURL(_ url: URL) async -> URL? {
        let probe = RedirectURLProbe()
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 8
        let session = URLSession(configuration: config, delegate: probe, delegateQueue: nil)
        defer { session.finishTasksAndInvalidate() }

        var request = URLRequest(url: url)
        request.httpMethod = "HEAD"
        do {
            let (_, response) = try await session.data(for: request)
            let candidate = probe.finalURL
                ?? (response as? HTTPURLResponse).flatMap { $0.url }
                ?? url
            if Self.imagePathExtensions.contains(candidate.pathExtension.lowercased()) {
                return candidate
            }
            // HEAD may be unsupported — try GET with a tiny Range.
            var getReq = URLRequest(url: url)
            getReq.httpMethod = "GET"
            getReq.setValue("bytes=0-0", forHTTPHeaderField: "Range")
            let (_, getResp) = try await session.data(for: getReq)
            let getCandidate = probe.finalURL
                ?? (getResp as? HTTPURLResponse).flatMap { $0.url }
                ?? url
            if Self.imagePathExtensions.contains(getCandidate.pathExtension.lowercased()) {
                return getCandidate
            }
            return nil
        } catch {
            return nil
        }
    }

    /// Chromecast pulls the URL itself; if iPhone cannot GET the first bytes, Cast cannot either.
    /// Uses ranged GET (not HEAD — many Flask/static setups mishandle or omit HEAD Content-Type).
    private func probePhotoURL(_ url: URL) async -> String? {
        if let err = await probePhotoURLGet(url, useRange: true) {
            // Some servers answer 416 / ignore Range poorly — retry without Range.
            if err.contains("HTTP 416") || err.contains("empty body") {
                return await probePhotoURLGet(url, useRange: false)
            }
            return err
        }
        return nil
    }

    private func probePhotoURLGet(_ url: URL, useRange: Bool) async -> String? {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalCacheData
        if useRange {
            request.setValue("bytes=0-1023", forHTTPHeaderField: "Range")
        }
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return Self.formatProbeFailure(status: nil, contentType: nil, detail: "non-HTTP response")
            }
            let status = http.statusCode
            let contentType = http.value(forHTTPHeaderField: "Content-Type")
            NSLog(
                "%@",
                "[CastSession] probe GET\(useRange ? "+Range" : "") "
                    + "status=\(status) Content-Type=\(contentType ?? "(missing)") "
                    + "bytes=\(data.count) url=\(url.absoluteString)"
            )

            if status == 416, useRange {
                return await probePhotoURLGet(url, useRange: false)
            }
            guard status == 200 || status == 206 else {
                return Self.formatProbeFailure(
                    status: status,
                    contentType: contentType,
                    detail: "unexpected status (need 200/206)"
                )
            }
            if Self.isAcceptableImageProbe(url: url, contentType: contentType, data: data) {
                return nil
            }
            return Self.formatProbeFailure(
                status: status,
                contentType: contentType,
                detail: "body 不像图片且 Content-Type 不是 image/*（可能是 HTML/JSON 首页）。请用 /xxx.JPG、/img/xxx.JPG 或 /latest"
            )
        } catch {
            NSLog("%@", "[CastSession] probe GET failed: \(error.localizedDescription) url=\(url.absoluteString)")
            return Self.formatProbeFailure(
                status: nil,
                contentType: nil,
                detail: error.localizedDescription
            )
        }
    }

    /// Accept image/* Content-Type, or missing/wrong type when URL ends with an image
    /// extension or the first bytes look like JPEG/PNG/GIF/WEBP.
    private static func isAcceptableImageProbe(url: URL, contentType: String?, data: Data) -> Bool {
        let raw = (contentType ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let mime = raw.split(separator: ";").first.map(String.init) ?? raw
        if mime.hasPrefix("image/") {
            return true
        }
        if imagePathExtensions.contains(url.pathExtension.lowercased()) {
            // Explicit still URL — do not block cast on missing/wrong Content-Type.
            return true
        }
        if !data.isEmpty, looksLikeImage(data) {
            return true
        }
        return false
    }

    private static func formatProbeFailure(status: Int?, contentType: String?, detail: String) -> String {
        let statusPart = status.map { "HTTP \($0)" } ?? "no status"
        let typePart = contentType?.trimmingCharacters(in: .whitespacesAndNewlines)
        let typeDisplay = (typePart?.isEmpty == false) ? typePart! : "(missing)"
        return "\(detail) · \(statusPart) · Content-Type=\(typeDisplay)"
    }

    /// Swap between `/{file}.JPG` and `/img/{file}.JPG` for home-img-server layout.
    /// Returns nil when the path is not a single-file still URL we can rewrite safely.
    private static func alternateHomeImgURL(_ url: URL) -> URL? {
        guard imagePathExtensions.contains(url.pathExtension.lowercased()) else { return nil }
        guard var comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        let path = comps.path
        let name = (path as NSString).lastPathComponent
        guard !name.isEmpty, !name.hasPrefix(".") else { return nil }

        if path.lowercased().hasPrefix("/img/") {
            // Only when path is exactly /img/<filename> (no nested dirs).
            let afterImg = String(path.dropFirst(5)) // drop "/img/"
            guard afterImg == name else { return nil }
            comps.path = "/\(name)"
        } else {
            let trimmed = path.hasPrefix("/") ? String(path.dropFirst()) : path
            guard trimmed == name else { return nil }
            comps.path = "/img/\(name)"
        }
        guard let alt = comps.url, alt.absoluteString != url.absoluteString else { return nil }
        return alt
    }

    private static func looksLikeImage(_ data: Data) -> Bool {
        guard data.count >= 3 else { return false }
        // JPEG
        if data[0] == 0xFF, data[1] == 0xD8, data[2] == 0xFF { return true }
        // PNG
        if data.count >= 8,
           data[0] == 0x89, data[1] == 0x50, data[2] == 0x4E, data[3] == 0x47
        {
            return true
        }
        // GIF
        if data.count >= 6, let s = String(data: data.prefix(6), encoding: .ascii),
           s.hasPrefix("GIF87a") || s.hasPrefix("GIF89a")
        {
            return true
        }
        // WEBP (RIFF....WEBP)
        if data.count >= 12,
           data[0] == 0x52, data[1] == 0x49, data[2] == 0x46, data[3] == 0x46,
           data[8] == 0x57, data[9] == 0x45, data[10] == 0x42, data[11] == 0x50
        {
            return true
        }
        return false
    }
}

// MARK: - Redirect probe

private final class RedirectURLProbe: NSObject, URLSessionTaskDelegate {
    var finalURL: URL?

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        finalURL = request.url
        completionHandler(request)
    }
}

// MARK: - Errors

private enum CastError: LocalizedError {
    case noDeviceFound
    case bonjourOkSdkEmpty(String)
    case deviceUnreachable(String)
    case sessionStartRejected
    case sessionFailed(String)
    case channelFailed(String)
    case loadFailed(String)

    var errorDescription: String? {
        switch self {
        case .noDeviceFound:
            return "未发现 Chromecast — iPhone 需与 TV 同一 Wi‑Fi（不要连 GoPro 热点）；并允许「本地网络」权限"
        case let .bonjourOkSdkEmpty(names):
            return """
            Bonjour 已看到 \(names)，但 Cast SDK 仍无设备。\
            请到 设置→隐私与安全性→本地网络 打开本 App；若无条目则删 App 重装后点「请求本地网络权限」。\
            已尝试按 IP 回退连接（\(CastDeviceFactory.defaultFallbackHost):8009）
            """
        case let .deviceUnreachable(detail):
            return """
            Chromecast 控制口不可达（\(detail)）。\
            设备在线但 iPhone 连不上 8009 — 检查同一 Wi‑Fi / 本地网络权限 / AP 隔离
            """
        case .sessionStartRejected:
            return "无法启动 Cast session（startSession 被拒绝，可能已有进行中的 session）"
        case let .sessionFailed(m):
            return "session error: \(m)"
        case let .channelFailed(m):
            return "channel error: \(m)"
        case let .loadFailed(m):
            return "load error: \(m)"
        }
    }
}

/// Custom namespace channel for photo URLs (`urn:x-cast:local.image`).
private final class LocalImageCastChannel: GCKCastChannel {
    override func didConnect() {
        super.didConnect()
        NSLog("%@", "[CastSession] LocalImageCastChannel didConnect ns=\(protocolNamespace)")
    }

    override func didDisconnect() {
        super.didDisconnect()
        NSLog("%@", "[CastSession] LocalImageCastChannel didDisconnect ns=\(protocolNamespace)")
    }
}

// MARK: - Bridges

private final class SessionStartBridge: NSObject, GCKSessionManagerListener {
    private var continuation: CheckedContinuation<Void, Error>?
    private weak var sessionManager: GCKSessionManager?
    private let onFinish: () -> Void
    private let contextLabel: String
    private var timeoutTask: Task<Void, Never>?

    init(
        continuation: CheckedContinuation<Void, Error>,
        sessionManager: GCKSessionManager,
        timeoutSeconds: TimeInterval,
        contextLabel: String = "",
        onFinish: @escaping () -> Void
    ) {
        self.continuation = continuation
        self.sessionManager = sessionManager
        self.contextLabel = contextLabel
        self.onFinish = onFinish
        super.init()
        let budget = max(20, timeoutSeconds)
        let nanos = UInt64(budget * 1_000_000_000)
        timeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: nanos)
            await MainActor.run {
                guard let self else { return }
                let label = self.contextLabel.isEmpty ? "" : " [\(self.contextLabel)]"
                self.finish(
                    .failure(
                        CastError.sessionFailed(
                            "start session timed out (\(Int(budget))s)\(label) — "
                                + "若 TCP 8009 可达则多为 Receiver App 启动失败（检查 Cast Console 发布）；"
                                + "否则为设备不可达 / SDK 卡住"
                        )
                    )
                )
            }
        }
    }

    /// Used when startSession returns false but a connected session already exists.
    func completeSuccess() {
        finish(.success(()))
    }

    private func finish(_ result: Result<Void, Error>) {
        guard let continuation else { return }
        self.continuation = nil
        timeoutTask?.cancel()
        timeoutTask = nil
        sessionManager?.remove(self)
        onFinish()
        switch result {
        case .success:
            continuation.resume()
        case let .failure(error):
            continuation.resume(throwing: error)
        }
    }

    func sessionManager(_ sessionManager: GCKSessionManager, willStart session: GCKSession) {
        NSLog("%@", "[CastSession] willStartSession \(contextLabel)")
    }

    /// Swift imports `willStartCastSession` as `willStart` with `GCKCastSession` param.
    func sessionManager(_ sessionManager: GCKSessionManager, willStart session: GCKCastSession) {
        NSLog(
            "%@",
            "[CastSession] willStartCastSession device=\(session.device.friendlyName ?? "?") \(contextLabel)"
        )
    }

    func sessionManager(_ sessionManager: GCKSessionManager, didStart session: GCKSession) {
        let name = Self.deviceName(session)
        NSLog("%@", "[CastSession] didStartSession device=\(name) \(contextLabel)")
        finish(.success(()))
    }

    /// Swift imports `didStartCastSession` as `didStart` with `GCKCastSession` param.
    /// Without this overload, Cast-only success callbacks never complete the bridge → timeout.
    func sessionManager(_ sessionManager: GCKSessionManager, didStart session: GCKCastSession) {
        let name = session.device.friendlyName ?? "(unnamed)"
        NSLog("%@", "[CastSession] didStartCastSession device=\(name) \(contextLabel)")
        finish(.success(()))
    }

    /// Cast often resumes a suspended session instead of didStart — treat as success.
    func sessionManager(_ sessionManager: GCKSessionManager, didResumeSession session: GCKSession) {
        let name = Self.deviceName(session)
        NSLog("%@", "[CastSession] didResumeSession device=\(name) \(contextLabel)")
        finish(.success(()))
    }

    func sessionManager(_ sessionManager: GCKSessionManager, didResume session: GCKCastSession) {
        let name = session.device.friendlyName ?? "(unnamed)"
        NSLog("%@", "[CastSession] didResumeCastSession device=\(name) \(contextLabel)")
        finish(.success(()))
    }

    func sessionManager(
        _ sessionManager: GCKSessionManager,
        didFailToStart session: GCKSession,
        withError error: Error
    ) {
        NSLog(
            "%@",
            "[CastSession] didFailToStartSession \(contextLabel): \(error.localizedDescription)"
        )
        finish(
            .failure(
                CastError.sessionFailed(
                    "didFailToStartSession: \(error.localizedDescription) \(contextLabel)"
                )
            )
        )
    }

    func sessionManager(
        _ sessionManager: GCKSessionManager,
        didFailToStart session: GCKCastSession,
        withError error: Error
    ) {
        NSLog(
            "%@",
            "[CastSession] didFailToStartCastSession \(contextLabel): \(error.localizedDescription)"
        )
        finish(
            .failure(
                CastError.sessionFailed(
                    "didFailToStartCastSession: \(error.localizedDescription) \(contextLabel)"
                )
            )
        )
    }

    private static func deviceName(_ session: GCKSession) -> String {
        if let cast = session as? GCKCastSession {
            return cast.device.friendlyName ?? "(unnamed)"
        }
        return String(describing: type(of: session))
    }
}

private final class SessionEndBridge: NSObject, GCKSessionManagerListener {
    private var continuation: CheckedContinuation<Void, Never>?
    private weak var sessionManager: GCKSessionManager?
    private let onFinish: () -> Void
    private var timeoutTask: Task<Void, Never>?

    init(
        continuation: CheckedContinuation<Void, Never>,
        sessionManager: GCKSessionManager,
        onFinish: @escaping () -> Void
    ) {
        self.continuation = continuation
        self.sessionManager = sessionManager
        self.onFinish = onFinish
        super.init()
        timeoutTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            await MainActor.run {
                self?.finish()
            }
        }
    }

    private func finish() {
        guard let continuation else { return }
        self.continuation = nil
        timeoutTask?.cancel()
        timeoutTask = nil
        sessionManager?.remove(self)
        onFinish()
        continuation.resume()
    }

    func sessionManager(_ sessionManager: GCKSessionManager, willEnd session: GCKSession) {
        // Prefer didEnd; willEnd is early signal only.
    }

    func sessionManager(_ sessionManager: GCKSessionManager, didEnd session: GCKSession, withError error: Error?) {
        if let error {
            NSLog("%@", "[CastSession] didEnd with error: \(error.localizedDescription)")
        } else {
            NSLog("%@", "[CastSession] didEnd session ok")
        }
        finish()
    }
}

// MARK: - Local Network permission kick

struct SeenCastBonjourDevice: Equatable {
    let name: String
    let deviceID: String
    let host: String
    let port: UInt16
}

/// iOS only shows the Local Network sheet when the app browses/advertises Bonjour.
/// Cast discovery alone sometimes skips the dialog; an explicit NWBrowser forces it
/// and also gives a raw mDNS signal when the Cast SDK list stays empty.
final class LocalNetworkAccessTrigger {
    static let shared = LocalNetworkAccessTrigger()

    private var browser: NWBrowser?
    private var secondaryBrowser: NWBrowser?
    private var cancelWorkItem: DispatchWorkItem?
    private var lastPingAt: Date?
    private var resolveConnections: [String: NWConnection] = [:]
    private var hostByName: [String: String] = [:]
    private var portByName: [String: UInt16] = [:]

    /// Friendly / instance names seen by NWBrowser during the current browse window.
    private(set) var seenInstanceNames: [String] = []
    /// Devices with resolved IPv4 (or fallback host).
    var seenDevices: [SeenCastBonjourDevice] {
        seenInstanceNames.compactMap { name in
            guard let host = hostByName[name] else { return nil }
            return SeenCastBonjourDevice(
                name: name,
                deviceID: BonjourCastDeviceProvider.deviceID(fromBonjourName: name),
                host: host,
                port: portByName[name] ?? BonjourCastDeviceProvider.castPort
            )
        }
    }

    /// Fired on main when instance names or resolved hosts change.
    var onDevicesUpdated: (() -> Void)?

    private init() {}

    func resolvedHost(forInstanceName name: String) -> String? {
        hostByName[name]
    }

    /// Start (or refresh) Bonjour browse for Cast service types.
    /// - Parameter keepAliveSeconds: how long to keep the browser alive (longer helps discovery + permission).
    func ping(keepAliveSeconds: TimeInterval = 30) {
        let keep = max(8, keepAliveSeconds)
        // Avoid cancelling a healthy browse every tap; extend lifetime instead.
        if let last = lastPingAt,
           Date().timeIntervalSince(last) < 2,
           browser != nil
        {
            scheduleCancel(after: keep)
            return
        }
        lastPingAt = Date()
        // Keep prior names across short re-pings; only clear hosts when starting fresh browse.

        cancelWorkItem?.cancel()
        browser?.cancel()
        secondaryBrowser?.cancel()

        browser = makeBrowser(type: "_googlecast._tcp")
        // Also browse Default Media Receiver subtype — matches Cast SDK Info.plist requirement.
        secondaryBrowser = makeBrowser(type: "_CC1AD845._googlecast._tcp")
        scheduleCancel(after: keep)
    }

    private func makeBrowser(type: String) -> NWBrowser {
        let descriptor = NWBrowser.Descriptor.bonjour(type: type, domain: nil)
        let params = NWParameters()
        params.includePeerToPeer = true
        let browser = NWBrowser(for: descriptor, using: params)
        browser.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                NSLog("%@", "[LocalNetwork] Bonjour browse ready (\(type))")
            case let .failed(error):
                NSLog("%@", "[LocalNetwork] Bonjour browse failed (\(type)): \(error)")
                if type == "_googlecast._tcp" {
                    self?.browser = nil
                } else {
                    self?.secondaryBrowser = nil
                }
            case .cancelled:
                break
            default:
                break
            }
        }
        browser.browseResultsChangedHandler = { [weak self] results, _ in
            self?.handleBrowseResults(results, type: type)
        }
        browser.start(queue: .main)
        return browser
    }

    private func handleBrowseResults(_ results: Set<NWBrowser.Result>, type: String) {
        var names: [String] = []
        for result in results {
            switch result.endpoint {
            case let .service(name: name, type: serviceType, domain: domain, interface: _):
                names.append(name)
                NSLog("%@", "[LocalNetwork] saw \(name) type=\(serviceType) domain=\(domain) via=\(type)")
                resolveEndpoint(result, instanceName: name)
            default:
                break
            }
        }
        if !names.isEmpty {
            var merged = Set(seenInstanceNames)
            names.forEach { merged.insert($0) }
            let sorted = merged.sorted()
            if sorted != seenInstanceNames {
                seenInstanceNames = sorted
                onDevicesUpdated?()
            }
        }
    }

    /// Resolve Bonjour service → IPv4 for Cast connect fallback.
    func resolveInstance(name: String, completion: @escaping (String?, UInt16?) -> Void) {
        if let host = hostByName[name] {
            completion(host, portByName[name] ?? BonjourCastDeviceProvider.castPort)
            return
        }
        // No live browse result — try connecting via Bonjour service endpoint string.
        let endpoint = NWEndpoint.service(name: name, type: "_googlecast._tcp", domain: "local.", interface: nil)
        resolve(endpoint: endpoint, instanceName: name, completion: completion)
    }

    private func resolveEndpoint(_ result: NWBrowser.Result, instanceName: String) {
        if hostByName[instanceName] != nil { return }
        resolve(endpoint: result.endpoint, instanceName: instanceName, completion: { _, _ in })
    }

    private func resolve(
        endpoint: NWEndpoint,
        instanceName: String,
        completion: @escaping (String?, UInt16?) -> Void
    ) {
        resolveConnections[instanceName]?.cancel()
        // TCP to Cast port forces DNS-SD resolve of the service endpoint.
        let tcp = NWParameters.tcp
        tcp.includePeerToPeer = true
        let connection = NWConnection(to: endpoint, using: tcp)
        resolveConnections[instanceName] = connection
        connection.stateUpdateHandler = { [weak self] state in
            guard let self else { return }
            switch state {
            case .ready:
                var host: String?
                var port: UInt16 = BonjourCastDeviceProvider.castPort
                if let remote = connection.currentPath?.remoteEndpoint {
                    switch remote {
                    case let .hostPort(h, p):
                        switch h {
                        case let .ipv4(v4):
                            host = "\(v4)"
                        case let .ipv6(v6):
                            // Prefer IPv4 when possible; keep IPv6 string as last resort.
                            host = "\(v6)"
                        case let .name(n, _):
                            host = n
                        @unknown default:
                            break
                        }
                        port = UInt16(p.rawValue)
                    default:
                        break
                    }
                }
                connection.cancel()
                self.resolveConnections[instanceName] = nil
                if let host {
                    // Strip zone / unexpected wrappers from IPv4 description if needed.
                    let cleaned = host.split(separator: "%").first.map(String.init) ?? host
                    let ipv4 = cleaned.contains(":") ? nil : cleaned
                    let finalHost = ipv4 ?? cleaned
                    self.hostByName[instanceName] = finalHost
                    self.portByName[instanceName] = port > 0 ? port : BonjourCastDeviceProvider.castPort
                    NSLog("%@", "[LocalNetwork] resolved \(instanceName) → \(finalHost):\(self.portByName[instanceName]!)")
                    self.onDevicesUpdated?()
                    completion(finalHost, self.portByName[instanceName])
                } else {
                    completion(nil, nil)
                }
            case .failed, .cancelled:
                self.resolveConnections[instanceName] = nil
                if case .failed = state {
                    completion(nil, nil)
                }
            default:
                break
            }
        }
        connection.start(queue: .main)
        // Don't leave half-open connects hanging.
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { [weak self, weak connection] in
            guard let self, let connection, self.resolveConnections[instanceName] === connection else { return }
            connection.cancel()
            self.resolveConnections[instanceName] = nil
            if self.hostByName[instanceName] == nil {
                completion(nil, nil)
            }
        }
    }

    private func scheduleCancel(after seconds: TimeInterval) {
        cancelWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            self?.browser?.cancel()
            self?.secondaryBrowser?.cancel()
            self?.browser = nil
            self?.secondaryBrowser = nil
            // Keep resolve maps / names for Cast fallback after browse window ends.
        }
        cancelWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
    }
}
