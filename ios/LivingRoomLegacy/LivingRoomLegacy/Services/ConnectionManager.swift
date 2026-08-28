import Foundation

final class ConnectionManager {
    static let shared = ConnectionManager()

    /// Heartbeat interval shown in UI countdown (seconds).
    static let heartbeatInterval: TimeInterval = 30

    private var heartbeatTimer: Timer?
    private var pendingIntentURL: String = ""
    private var pendingParticipantId: String = ""
    private var allowEndpointFallback = false
    private var triedEndpointFallback = false

    private(set) var isConnecting = false
    private(set) var lastError: String = ""
    private(set) var nextHeartbeatAt: Date?
    /// Endpoint that actually succeeded (may differ from preferred during auto-fallback).
    private(set) var activeEndpoint: BrainEndpoint = .home

    var onStatusChange: (() -> Void)?

    private init() {}

    /// Launch / foreground: try preferred (default 家里), optionally fall back once without saving.
    func startAutoConnect() {
        allowEndpointFallback = true
        triedEndpointFallback = false
        start(intentURL: ParticipantStore.preferredEndpoint.intentURL)
    }

    /// Parent picked 家里 / 外面 — connect to that endpoint only.
    func switchToEndpoint(_ endpoint: BrainEndpoint) {
        allowEndpointFallback = false
        triedEndpointFallback = false
        ParticipantStore.preferredEndpoint = endpoint
        ParticipantStore.participantId = ""
        ParticipantStore.lastHeartbeatOk = false
        start(intentURL: endpoint.intentURL)
    }

    func start(intentURL: String) {
        stopHeartbeatTimer()
        nextHeartbeatAt = nil
        isConnecting = true
        lastError = ""
        notify()
        connect(intentURL: intentURL)
    }

    func stopHeartbeatTimer() {
        heartbeatTimer?.invalidate()
        heartbeatTimer = nil
        nextHeartbeatAt = nil
    }

    func connect(intentURL: String) {
        let url = BrainURL.normalizeIntentURL(intentURL)
        BrainAPI.register(intentURL: url) { [weak self] registerResult in
            guard let self = self else { return }
            switch registerResult {
            case .failure(let err):
                if self.tryFallbackEndpoint(after: err, failedURL: url) {
                    return
                }
                self.isConnecting = false
                self.lastError = err.message
                ParticipantStore.lastHeartbeatOk = false
                self.nextHeartbeatAt = nil
                self.notify()
            case .success(let pid):
                self.activeEndpoint = BrainEndpoint.matching(savedURL: url)
                ParticipantStore.setActiveIntentURL(url)
                self.lastError = ""
                self.sendHeartbeat(intentURL: url, participantId: pid, scheduleLoop: true)
            }
        }
    }

    private func tryFallbackEndpoint(after error: BrainFailure, failedURL: String) -> Bool {
        guard allowEndpointFallback, !triedEndpointFallback, isNetworkError(error.message) else {
            return false
        }
        triedEndpointFallback = true
        let current = BrainEndpoint.matching(savedURL: failedURL)
        let other = current.opposite
        ParticipantStore.participantId = ""
        connect(intentURL: other.intentURL)
        return true
    }

    private func isNetworkError(_ message: String) -> Bool {
        let msg = message.lowercased()
        return msg.contains("could not connect")
            || msg.contains("timed out")
            || msg.contains("timeout")
            || msg.contains("network connection was lost")
            || msg.contains("not connected to internet")
            || msg.contains("无法连接")
            || msg.contains("请求超时")
    }

    private func shouldReregister(after error: String) -> Bool {
        let msg = error.lowercased()
        return msg.contains("unknown edge_id")
            || msg.contains("register first")
            || msg.contains("not registered")
    }

    private func sendHeartbeat(intentURL: String, participantId: String, scheduleLoop: Bool) {
        pendingIntentURL = intentURL
        pendingParticipantId = participantId
        nextHeartbeatAt = nil
        notify()

        BrainAPI.heartbeat(intentURL: intentURL, participantId: participantId) { [weak self] result in
            guard let self = self else { return }
            self.isConnecting = false
            switch result {
            case .failure(let err):
                self.lastError = err.message
                self.nextHeartbeatAt = nil
                if self.shouldReregister(after: err.message) {
                    ParticipantStore.participantId = ""
                    self.connect(intentURL: intentURL)
                    return
                }
            case .success:
                self.lastError = ""
                if scheduleLoop {
                    self.scheduleHeartbeat(intentURL: intentURL, participantId: participantId)
                } else if self.heartbeatTimer != nil {
                    self.armNextHeartbeat()
                }
            }
            self.notify()
        }
    }

    private func scheduleHeartbeat(intentURL: String, participantId: String) {
        stopHeartbeatTimer()
        pendingIntentURL = intentURL
        pendingParticipantId = participantId
        armNextHeartbeat()
        heartbeatTimer = Timer.scheduledTimer(withTimeInterval: ConnectionManager.heartbeatInterval, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.sendHeartbeat(
                intentURL: self.pendingIntentURL,
                participantId: self.pendingParticipantId,
                scheduleLoop: false
            )
        }
        if let timer = heartbeatTimer {
            RunLoop.main.add(timer, forMode: .common)
        }
    }

    private func armNextHeartbeat() {
        nextHeartbeatAt = Date().addingTimeInterval(ConnectionManager.heartbeatInterval)
    }

    func secondsUntilNextHeartbeat() -> Int? {
        guard let target = nextHeartbeatAt else { return nil }
        let remain = Int(ceil(target.timeIntervalSinceNow))
        return max(0, remain)
    }

    func countdownText() -> String {
        if isConnecting {
            return "下次心跳：连接中…"
        }
        if heartbeatTimer == nil, ParticipantStore.participantId.isEmpty {
            return "下次心跳：未登记"
        }
        if heartbeatTimer == nil {
            return "下次心跳：已暂停"
        }
        guard let sec = secondsUntilNextHeartbeat() else {
            return "下次心跳：发送中…"
        }
        return "下次心跳：\(sec)s"
    }

    func applicationDidBecomeActive() {
        let pid = ParticipantStore.participantId
        guard !pid.isEmpty, ParticipantStore.lastHeartbeatOk else {
            startAutoConnect()
            return
        }
        pendingIntentURL = ParticipantStore.brainIntentURL
        pendingParticipantId = pid
        if heartbeatTimer == nil {
            scheduleHeartbeat(intentURL: pendingIntentURL, participantId: pid)
        }
        sendHeartbeat(intentURL: pendingIntentURL, participantId: pid, scheduleLoop: false)
    }

    func applicationDidEnterBackground() {
        stopHeartbeatTimer()
    }

    private func notify() {
        onStatusChange?()
    }
}
