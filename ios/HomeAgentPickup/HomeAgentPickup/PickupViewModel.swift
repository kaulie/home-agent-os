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

    private let client = AudioPickupClient()
    private let capture = PcmCaptureEngine()
    private var reconnectTask: Task<Void, Never>?
    private var savedBrightness: CGFloat = UIScreen.main.brightness
    private var powerSaveBranch = "A"
    private var captureWanted = true
    private var micPermissionGranted = false

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
                self?.connectionLabel = "断开，重连中…"
                self?.stopCapture()
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
                connectionLabel = "连接中…"
                try await client.connect(
                    host: PickupSettings.serverHost,
                    port: PickupSettings.serverPort,
                    deviceId: PickupSettings.deviceId
                )
                connectionLabel = "已连接"
                lastError = ""
                heartbeatCount = 0
                if captureWanted {
                    startCaptureIfNeeded()
                }
                while client.isConnected, !Task.isCancelled {
                    try await Task.sleep(nanoseconds: 1_000_000_000)
                }
            } catch {
                connectionLabel = "连接失败"
                lastError = error.localizedDescription
            }
            try? await Task.sleep(nanoseconds: 3_000_000_000)
        }
    }

    private func startCaptureIfNeeded() {
        guard captureWanted, micPermissionGranted, !capture.isRunning else { return }
        do {
            try capture.start { [weak self] data in
                guard let self else { return }
                self.client.sendPCM(data)
                Task { @MainActor in
                    self.pcmBytesSent += data.count
                }
            }
            captureLabel = "采集中"
        } catch {
            captureLabel = "采集失败"
            lastError = error.localizedDescription
        }
    }

    private func stopCapture() {
        if capture.isRunning {
            capture.stop()
        }
        captureLabel = captureWanted ? "已暂停" : "停止"
    }

    private func apply(command: PickupServerCommand) {
        switch command.type {
        case .setNormal:
            modeLabel = "normal"
            powerSaveActive = false
            powerSaveBranch = "A"
            captureWanted = true
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
                stopCapture()
            } else {
                captureWanted = true
                startCaptureIfNeeded()
            }
        case .stop:
            captureWanted = false
            stopCapture()
            modeLabel = "stop"
        case .exit:
            captureWanted = false
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
