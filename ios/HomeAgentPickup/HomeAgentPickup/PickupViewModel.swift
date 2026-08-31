import AVFoundation
import Foundation
import UIKit

@MainActor
final class PickupViewModel: NSObject, ObservableObject {
    @Published private(set) var connectionLabel = "未连接"
    @Published private(set) var captureLabel = "待命"
    @Published private(set) var heartbeatCount = 0
    @Published private(set) var pcmBytesSent: Int = 0
    @Published private(set) var powerSaveActive = false
    @Published private(set) var modeLabel = "normal"
    @Published var lastError = ""
    @Published private(set) var feedbackBusy = false
    @Published private(set) var userListeningEnabled = false
    @Published private(set) var audioLevel: Float = 0
    @Published private(set) var micPermissionGranted = false
    @Published private(set) var isConnected = false

    private let client = AudioPickupClient()
    private let capture = PcmCaptureEngine()
    private let energyGate = PcmEnergyGate()
    private let speech = AVSpeechSynthesizer()
    private var reconnectTask: Task<Void, Never>?
    private var speakWatchdogTask: Task<Void, Never>?
    private var savedBrightness: CGFloat = UIScreen.main.brightness
    private var powerSaveBranch = "A"
    private var captureWanted = false
    /// Shared with audio send queue — keep lock-guarded.
    private let speakLock = NSLock()
    private var speakingFlag = false
    /// Audio tap thread → gate → send (not MainActor).
    private let sendQueue = DispatchQueue(label: "homeagent.pickup.sendgate")

    private var isSpeakingLocally: Bool {
        get {
            speakLock.lock()
            defer { speakLock.unlock() }
            return speakingFlag
        }
        set {
            speakLock.lock()
            speakingFlag = newValue
            speakLock.unlock()
        }
    }

    override init() {
        super.init()
    }

    var serverLabel: String {
        "\(PickupSettings.serverHost):\(PickupSettings.serverPort)"
    }

    var pcmSentLabel: String {
        if pcmBytesSent >= 1_000_000 {
            return String(format: "%.1f MB", Double(pcmBytesSent) / 1_000_000)
        }
        if pcmBytesSent >= 1000 {
            return String(format: "%.1f KB", Double(pcmBytesSent) / 1000)
        }
        return "\(pcmBytesSent) B"
    }

    var prominentErrorMessage: String? {
        if !micPermissionGranted {
            return "需要麦克风权限\n请到 iPhone「设置」里允许 Home Mic 使用麦克风"
        }
        if userListeningEnabled, captureLabel == "采集失败", !lastError.isEmpty {
            return "麦克风启动失败\n\(lastError)"
        }
        if !isConnected, !lastError.isEmpty, !userListeningEnabled {
            return "暂时连不上 Home Mic\n请确认手机和家里 Wi‑Fi 正常"
        }
        return nil
    }

    var userConnectionStatus: String {
        if isConnected { return "正常" }
        if connectionLabel.contains("连接中") || connectionLabel.contains("重连") {
            return "正在连接…"
        }
        if !lastError.isEmpty { return "连不上" }
        return "未连接"
    }

    var userCaptureStatus: String {
        if !userListeningEnabled { return "已关闭" }
        if captureLabel == "采集失败" { return "麦克风失败" }
        if !capture.isRunning { return "麦克风未启动" }
        if !isConnected { return "本地在听，等待连接" }
        if audioLevel > 0.08 { return "能听到 · \(Int(audioLevel * 100))%" }
        if pcmBytesSent > 0 { return "在听（已发送 \(pcmSentLabel)）" }
        return "正在听，请说话"
    }

    var hearingHint: String {
        guard userListeningEnabled else { return "" }
        if captureLabel == "采集失败" { return lastError.isEmpty ? "麦克风启动失败" : lastError }
        if !capture.isRunning { return "麦克风还没起来，再点一次试试" }
        if audioLevel > 0.06 { return "电平在动，说明听到了" }
        return "对着话筒说几句，看电平条会不会跳"
    }

    var statusHeadline: String {
        if !userListeningEnabled { return "话筒已关" }
        if captureLabel == "采集失败" { return "听不到" }
        if !capture.isRunning { return "准备听" }
        return "正在听"
    }

    var statusHint: String {
        if userListeningEnabled {
            if !isConnected, capture.isRunning { return "本地已在听；连上后会传到家里" }
            if !isConnected { return "正在连接，连上就开始听" }
            return hearingHint
        }
        return "点一下大按钮，开始拾音"
    }

    func toggleListening() {
        Task {
            let granted = await refreshMicPermission(requestIfNeeded: true)
            micPermissionGranted = granted
            guard granted else {
                lastError = "未授权麦克风"
                return
            }
            if userListeningEnabled {
                userListeningEnabled = false
                captureWanted = false
                stopCapture()
            } else {
                userListeningEnabled = true
                captureWanted = true
                lastError = ""
                startCaptureIfNeeded()
            }
        }
    }

    func refreshPermissions() async {
        micPermissionGranted = await refreshMicPermission(requestIfNeeded: false)
    }

    func bootstrap() async {
        micPermissionGranted = await refreshMicPermission(requestIfNeeded: true)
        guard micPermissionGranted else {
            lastError = "未授权麦克风"
            return
        }
        wireClient()
        reconnectTask?.cancel()
        reconnectTask = Task { [weak self] in
            await self?.connectionLoop()
        }
    }

    /// Rediscover gateway IPv4 and abort any hung TCP so the loop connects to the new host.
    func rediscoverGatewayAndReconnect() async {
        connectionLabel = "正在发现 gateway.local…"
        await PickupSettings.autoDiscoverGateway()
        // Abort hung SYN to the old DHCP IP so connectionLoop can use the new IPv4.
        client.close()
        if PickupSettings.serverHost.isEmpty {
            lastError = MdnsDiscovery.refuseNonIPv4TCP("") ?? "尚未发现 IPv4"
            connectionLabel = lastError
        } else {
            lastError = ""
            connectionLabel = "连接中…"
        }
    }

    private func wireClient() {
        speech.delegate = self
        client.onCommand = { [weak self] cmd in
            Task { @MainActor in self?.apply(command: cmd) }
        }
        client.onDisconnected = { [weak self] in
            Task { @MainActor in
                self?.isConnected = false
                self?.connectionLabel = "断开，重连中…"
            }
        }
        client.onHeartbeatSent = { [weak self] in
            Task { @MainActor in
                self?.heartbeatCount += 1
            }
        }
    }

    private func connectionLoop() async {
        while !Task.isCancelled {
            do {
                isConnected = false
                if PickupSettings.serverHost.isEmpty {
                    connectionLabel = "正在发现 gateway.local…"
                    await PickupSettings.autoDiscoverGateway()
                    if PickupSettings.serverHost.isEmpty {
                        lastError = MdnsDiscovery.refuseNonIPv4TCP("") ?? "尚未发现 IPv4"
                        try await Task.sleep(nanoseconds: 2_000_000_000)
                        continue
                    }
                }
                if let refuse = MdnsDiscovery.refuseNonIPv4TCP(PickupSettings.serverHost) {
                    PickupSettings.serverHost = ""
                    lastError = refuse
                    connectionLabel = refuse
                    try await Task.sleep(nanoseconds: 2_000_000_000)
                    continue
                }
                connectionLabel = "连接中…"
                try await client.connect(
                    host: PickupSettings.serverHost,
                    port: PickupSettings.serverPort,
                    deviceId: PickupSettings.deviceId,
                    participantId: PickupSettings.edgeParticipantId
                )
                connectionLabel = "已连接"
                isConnected = true
                lastError = ""
                heartbeatCount = 0
                if captureWanted {
                    startCaptureIfNeeded()
                }
                // Stay until client drops sessionReady (not flaky NWConnection.state).
                // Also force-reconnect if TCP looks half-open (Mac voice restarted).
                var deadTicks = 0
                while client.isConnected, !Task.isCancelled {
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                    if client.isLikelyAlive(maxAge: 25) {
                        deadTicks = 0
                    } else {
                        deadTicks += 1
                        if deadTicks >= 5 {
                            connectionLabel = "连接无响应，重连中…"
                            client.close()
                            break
                        }
                    }
                }
                if !Task.isCancelled {
                    isConnected = false
                    connectionLabel = "断开，重连中…"
                }
            } catch {
                isConnected = false
                lastError = error.localizedDescription
                connectionLabel = lastError.contains("取消") ? "连接中…" : "连接失败"
                // Keep last IPv4. Wiping it here would throw away a just-discovered host
                // (e.g. 84) when aborting a hung connect to the previous IP.
            }
            let backoff: UInt64 = lastError.contains("取消") ? 200_000_000 : 3_000_000_000
            try? await Task.sleep(nanoseconds: backoff)
        }
    }

    private func startCaptureIfNeeded() {
        guard captureWanted, micPermissionGranted else { return }
        if capture.isRunning { return }
        do {
            energyGate.reset()
            // Capture references for the audio tap / send queue (avoid MainActor hops).
            let gate = energyGate
            let hap1 = client
            let speakCheck = { [weak self] in self?.isSpeakingLocally ?? false }
            try capture.start(onPCM: { data in
                DispatchQueue.global(qos: .userInitiated).async {
                    if speakCheck() { return }
                    let chunks = gate.filter(
                        data,
                        enabled: PickupSettings.energyGateEnabled
                    )
                    guard !chunks.isEmpty else { return }
                    var total = 0
                    for chunk in chunks {
                        hap1.sendPCM(chunk)
                        total += chunk.count
                    }
                    let sent = total
                    Task { @MainActor [weak self] in
                        self?.pcmBytesSent += sent
                    }
                }
            }, onLevel: { [weak self] level in
                self?.audioLevel = level
            })
            captureLabel = "采集中"
            lastError = ""
        } catch {
            captureLabel = "采集失败"
            lastError = error.localizedDescription
            audioLevel = 0
        }
    }

    private func stopCapture() {
        if capture.isRunning {
            capture.stop()
        }
        sendQueue.async { [energyGate] in
            energyGate.reset()
        }
        audioLevel = 0
        captureLabel = userListeningEnabled ? "已暂停" : "待命"
    }

    private func refreshMicPermission(requestIfNeeded: Bool) async -> Bool {
        if #available(iOS 17.0, *) {
            switch AVAudioApplication.shared.recordPermission {
            case .granted:
                return true
            case .denied:
                return false
            case .undetermined:
                guard requestIfNeeded else { return false }
                return await AVAudioApplication.requestRecordPermission()
            @unknown default:
                return false
            }
        }
        let session = AVAudioSession.sharedInstance()
        switch session.recordPermission {
        case .granted:
            return true
        case .denied:
            return false
        case .undetermined:
            guard requestIfNeeded else { return false }
            return await withCheckedContinuation { cont in
                session.requestRecordPermission { granted in
                    cont.resume(returning: granted)
                }
            }
        @unknown default:
            return false
        }
    }

    private func apply(command: PickupServerCommand) {
        switch command.type {
        case .setNormal:
            modeLabel = "normal"
            powerSaveActive = false
            powerSaveBranch = "A"
            captureWanted = true
            userListeningEnabled = true
            UIScreen.main.brightness = savedBrightness
            startCaptureIfNeeded()
        case .setPowerSave:
            modeLabel = "power_save"
            powerSaveActive = true
            powerSaveBranch = (command.branch ?? "A").uppercased()
            savedBrightness = max(UIScreen.main.brightness, 0.2)
            UIScreen.main.brightness = 0.05
            if powerSaveBranch == "B" {
                captureWanted = false
                userListeningEnabled = false
                stopCapture()
            } else {
                captureWanted = true
                userListeningEnabled = true
                startCaptureIfNeeded()
            }
        case .stop:
            captureWanted = false
            userListeningEnabled = false
            stopCapture()
            modeLabel = "stop"
        case .exit:
            captureWanted = false
            userListeningEnabled = false
            stopCapture()
            modeLabel = "exit"
        case .speak:
            let text = (command.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { return }
            speakLocally(text)
        }
    }

    // MARK: - Local TTS (HAP1 speak)

    private func speakLocally(_ text: String) {
        isSpeakingLocally = true
        capture.pauseEngine()
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(
                .playAndRecord,
                mode: .default,
                options: [.defaultToSpeaker, .duckOthers]
            )
            try session.setActive(true, options: [])
            try session.overrideOutputAudioPort(.speaker)
        } catch {
            // Keep going; AVSpeech may still work.
        }
        speech.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: text)
        if let voice = AVSpeechSynthesisVoice(language: "zh-CN") {
            utterance.voice = voice
        }
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        captureLabel = "正在回复…"
        speech.speak(utterance)
        // AVSpeech sometimes never calls didFinish after route changes —
        // without this, mic stays paused forever ("成功一次后哑巴").
        speakWatchdogTask?.cancel()
        speakWatchdogTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 8_000_000_000)
            guard let self, !Task.isCancelled else { return }
            await MainActor.run {
                guard self.isSpeakingLocally else { return }
                self.speech.stopSpeaking(at: .immediate)
                self.resumeCaptureAfterSpeak()
            }
        }
    }

    private func resumeCaptureAfterSpeak() {
        speakWatchdogTask?.cancel()
        speakWatchdogTask = nil
        isSpeakingLocally = false
        energyGate.reset()
        capture.resumeEngineIfNeeded()
        if userListeningEnabled, captureWanted, !capture.isRunning {
            // Soft resume failed — hard restart capture.
            stopCapture()
            startCaptureIfNeeded()
        }
        if userListeningEnabled, captureWanted {
            captureLabel = capture.isRunning ? "采集中" : "待命"
        }
    }

    func clientSnapshot() -> [String: Any] {
        [
            "source": "pickup_terminal",
            "pickup_server": serverLabel,
            "brain_intent_url": PickupSettings.brainIntentURL,
            "device_id": PickupSettings.deviceId,
            "tcp_connection": connectionLabel,
            "capture_state": captureLabel,
            "user_listening": userListeningEnabled,
            "is_connected": isConnected,
            "audio_level": audioLevel,
            "mode": modeLabel,
            "heartbeat_count": heartbeatCount,
            "pcm_bytes_sent": pcmBytesSent,
            "power_save_active": powerSaveActive,
            "last_error": lastError,
        ]
    }

    func submitFeedback(
        problemType: PickupFeedbackProblemType,
        userSummary: String,
        attachments: [PendingPickupFeedbackAttachment] = [],
        completion: @escaping (Bool, String) -> Void
    ) {
        let participantId: String = {
            let configured = PickupSettings.feedbackParticipantId
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return configured.isEmpty ? PickupSettings.deviceId : configured
        }()
        feedbackBusy = true
        Task {
            var uploaded: [PickupFeedbackAttachment] = []
            if !attachments.isEmpty {
                for (index, pending) in attachments.enumerated() {
                    do {
                        let item = try await PickupAssetUpload.uploadFeedbackImage(
                            pending,
                            brainURL: PickupSettings.brainIntentURL,
                            intentId: "",
                            participantId: participantId
                        )
                        uploaded.append(item)
                    } catch {
                        feedbackBusy = false
                        completion(false, "图片 \(index + 1) 上传失败：\(error.localizedDescription)")
                        return
                    }
                }
            }
            let result = await PickupFeedbackClient.submit(
                brainURL: PickupSettings.brainIntentURL,
                participantId: participantId,
                problemType: problemType,
                userSummary: userSummary,
                clientSnapshot: clientSnapshot(),
                attachments: uploaded
            )
            feedbackBusy = false
            if result.ok {
                let msg = result.issueId.map { "已提交 #\($0)" } ?? result.message
                completion(true, msg)
            } else {
                completion(false, result.error.isEmpty ? "提交失败" : result.error)
            }
        }
    }
}

extension PickupViewModel: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in
            self.resumeCaptureAfterSpeak()
        }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in
            self.resumeCaptureAfterSpeak()
        }
    }
}
