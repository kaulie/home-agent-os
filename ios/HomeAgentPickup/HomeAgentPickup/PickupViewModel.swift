import AVFoundation
import Foundation
import UIKit

@MainActor
final class PickupViewModel: ObservableObject {
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
    private var reconnectTask: Task<Void, Never>?
    private var savedBrightness: CGFloat = UIScreen.main.brightness
    private var powerSaveBranch = "A"
    private var captureWanted = false

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
            return "需要麦克风权限\n请到 iPhone「设置」里允许本 App 使用麦克风"
        }
        if !isConnected, !lastError.isEmpty {
            return "暂时连不上拾音服务\n请确认手机和家里 Wi‑Fi 正常"
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
        if !isConnected { return "等待连接" }
        if audioLevel > 0.06 { return "能听到你说话" }
        return "正在听，请说话"
    }

    var hearingHint: String {
        guard userListeningEnabled, isConnected else { return "" }
        if audioLevel > 0.06 { return "电平在动，说明听到了" }
        return "对着话筒说几句，看电平条会不会跳"
    }

    var statusHeadline: String {
        if userListeningEnabled {
            return isConnected ? "正在听" : "准备听"
        }
        return "话筒已关"
    }

    var statusHint: String {
        if userListeningEnabled {
            if !isConnected { return "正在连接，连上就开始听" }
            return hearingHint
        }
        return "点一下大按钮，开始拾音"
    }

    func toggleListening() {
        guard micPermissionGranted else { return }
        if userListeningEnabled {
            userListeningEnabled = false
            captureWanted = false
            stopCapture()
        } else {
            userListeningEnabled = true
            captureWanted = true
            startCaptureIfNeeded()
        }
    }

    func bootstrap() async {
        micPermissionGranted = await requestMicPermission()
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

    private func requestMicPermission() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
    }

    private func wireClient() {
        client.onCommand = { [weak self] cmd in
            Task { @MainActor in self?.apply(command: cmd) }
        }
        client.onDisconnected = { [weak self] in
            Task { @MainActor in
                self?.isConnected = false
                self?.connectionLabel = "断开，重连中…"
                self?.stopCapture(resumeWhenConnected: true)
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
                connectionLabel = "连接中…"
                try await client.connect(
                    host: PickupSettings.serverHost,
                    port: PickupSettings.serverPort,
                    deviceId: PickupSettings.deviceId
                )
                connectionLabel = "已连接"
                isConnected = true
                lastError = ""
                heartbeatCount = 0
                if captureWanted {
                    startCaptureIfNeeded()
                }
                while client.isConnected, !Task.isCancelled {
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                }
            } catch {
                isConnected = false
                connectionLabel = "连接失败"
                lastError = error.localizedDescription
            }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
        }
    }

    private func startCaptureIfNeeded() {
        guard captureWanted, micPermissionGranted, !capture.isRunning else { return }
        do {
            try capture.start(onPCM: { [weak self] data in
                guard let self else { return }
                self.client.sendPCM(data)
                Task { @MainActor in
                    self.pcmBytesSent += data.count
                }
            }, onLevel: { [weak self] level in
                Task { @MainActor in
                    self?.audioLevel = level
                }
            })
            captureLabel = "采集中"
        } catch {
            captureLabel = "采集失败"
            lastError = error.localizedDescription
            userListeningEnabled = false
            captureWanted = false
        }
    }

    private func stopCapture(resumeWhenConnected: Bool = false) {
        if capture.isRunning {
            capture.stop()
        }
        audioLevel = 0
        if resumeWhenConnected, userListeningEnabled {
            captureLabel = "等待连接"
        } else if userListeningEnabled {
            captureLabel = "已暂停"
        } else {
            captureLabel = "待命"
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
        intentIdText: String,
        userSummary: String,
        completion: @escaping (Bool, String) -> Void
    ) {
        let intentId = Int(intentIdText.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
        feedbackBusy = true
        Task {
            let result = await PickupFeedbackClient.submit(
                brainURL: PickupSettings.brainIntentURL,
                intentId: intentId,
                participantId: PickupSettings.feedbackParticipantId,
                problemType: problemType,
                userSummary: userSummary,
                clientSnapshot: clientSnapshot()
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
