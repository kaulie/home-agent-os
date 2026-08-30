import AVFoundation
import Foundation
import UIKit

/// Connection + capture state for Home Mic screen.
enum HomeMicConnectionState: Equatable {
    case disconnected
    case connecting
    case connected
    case failed(String)

    var statusText: String {
        switch self {
        case .disconnected: return "未连接"
        case .connecting: return "连接中…"
        case .connected: return "已连接"
        case .failed(let msg): return msg
        }
    }
}

/// Orchestrates HAP1 + PCM + energy gate + local TTS for HAP1 speak downlink.
final class HomeMicController: NSObject {
    private let client = HomeMicHap1Client()
    private let capture = HomeMicPcmCapture()
    private let energyGate = HomeMicEnergyGate()
    private let speech = AVSpeechSynthesizer()

    private(set) var isListening = false
    private(set) var connectionState: HomeMicConnectionState = .disconnected
    /// True while local TTS is speaking (skip uploading that audio).
    private(set) var isSpeakingLocally = false
    private var speakWatchdog: DispatchWorkItem?

    /// 0…1, always on main.
    var onAudioLevel: ((Float) -> Void)?
    /// Connection + capture status line, always on main.
    var onStatusChange: ((String) -> Void)?
    var onConnectionStateChange: ((HomeMicConnectionState) -> Void)?

    override init() {
        super.init()
        speech.delegate = self
        client.onDisconnected = { [weak self] in
            guard let self = self else { return }
            self.isConnecting = false
            self.setConnection(.disconnected)
            if self.isListening {
                self.publishStatus("连接断开，正在重连…")
                self.connectIfNeeded()
            } else {
                self.publishStatus("未连接")
            }
        }
        client.onCommand = { [weak self] cmd in
            guard let self = self else { return }
            switch cmd.type {
            case .stop, .exit:
                self.stopListening()
                self.publishStatus("服务端要求停止")
            case .setPowerSave, .setNormal:
                break
            case .speak:
                let text = (cmd.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return }
                self.speakLocally(text)
            }
        }
    }

    deinit {
        speech.stopSpeaking(at: .immediate)
        stopListening()
        client.close()
    }

    private var isConnecting = false
    private var reconnectWorkItem: DispatchWorkItem?
    private var reconnectAttempt = 0
    private var livenessWorkItem: DispatchWorkItem?

    /// Connect (or reconnect) using `HomeMicSettings` + `PickupIdentity`.
    func connectIfNeeded() {
        if client.isConnected {
            isConnecting = false
            reconnectAttempt = 0
            reconnectWorkItem?.cancel()
            reconnectWorkItem = nil
            setConnection(.connected)
            startLivenessWatch()
            return
        }
        if isConnecting {
            return
        }
        isConnecting = true
        setConnection(.connecting)
        publishStatus("连接中…")
        let host = HomeMicSettings.host
        let port = HomeMicSettings.port
        let deviceId = PickupIdentity.deviceId
        let participantId = PickupIdentity.participantId
        client.connect(
            host: host,
            port: port,
            deviceId: deviceId,
            participantId: participantId
        ) { [weak self] error in
            guard let self = self else { return }
            self.isConnecting = false
            if let error = error {
                self.setConnection(.failed(error.localizedDescription))
                self.publishStatus(error.localizedDescription)
                if self.isListening {
                    self.scheduleReconnect()
                }
                return
            }
            self.reconnectAttempt = 0
            self.reconnectWorkItem?.cancel()
            self.reconnectWorkItem = nil
            self.setConnection(.connected)
            self.publishStatus(self.isListening ? "拾音中" : "已连接")
            self.startLivenessWatch()
        }
    }

    /// Backoff reconnect while still listening (Mac voice restart drops TCP).
    private func scheduleReconnect() {
        reconnectWorkItem?.cancel()
        reconnectAttempt = min(reconnectAttempt + 1, 8)
        let delay = min(1.5 * Double(reconnectAttempt), 8.0)
        let work = DispatchWorkItem { [weak self] in
            guard let self = self, self.isListening, !self.client.isConnected else { return }
            self.publishStatus("连接断开，正在重连…")
            self.connectIfNeeded()
        }
        reconnectWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    /// Detect half-open TCP after Mac `mac_voice` restart (no FIN to phone).
    private func startLivenessWatch() {
        livenessWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            guard let self = self else { return }
            defer { self.startLivenessWatch() }
            guard self.isListening else { return }
            if self.client.isConnected, !self.client.isLikelyAlive(maxAge: 25) {
                self.publishStatus("连接无响应，正在重连…")
                self.client.close()
                self.setConnection(.disconnected)
                self.scheduleReconnect()
                return
            }
            if !self.client.isConnected, !self.isConnecting {
                self.scheduleReconnect()
            }
        }
        livenessWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 5.0, execute: work)
    }

    /// Request mic permission, connect, start PCM → gate → HAP1.
    func startListening() {
        if isListening { return }
        requestMicPermission { [weak self] granted in
            guard let self = self else { return }
            guard granted else {
                self.publishStatus("需要麦克风权限")
                self.setConnection(.failed("需要麦克风权限"))
                return
            }
            self.beginCaptureAfterPermission()
        }
    }

    func stopListening() {
        guard isListening || capture.isRunning else {
            capture.stop()
            isListening = false
            return
        }
        isListening = false
        capture.stop()
        energyGate.reset()
        onAudioLevel?(0)
        if case .connected = connectionState {
            publishStatus("已连接")
        } else {
            publishStatus(connectionState.statusText)
        }
    }

    /// Tear down TCP as well (leave Home Mic tab / app background policy).
    func disconnect() {
        speech.stopSpeaking(at: .immediate)
        isSpeakingLocally = false
        isConnecting = false
        reconnectWorkItem?.cancel()
        reconnectWorkItem = nil
        livenessWorkItem?.cancel()
        livenessWorkItem = nil
        reconnectAttempt = 0
        stopListening()
        client.close()
        setConnection(.disconnected)
        publishStatus("未连接")
    }

    // MARK: - Local TTS (HAP1 speak)

    func speakLocally(_ text: String) {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        // iOS 12 + live AVAudioEngine: AVSpeech (even without pause/route flip)
        // still hard-crashes on several devices. Mac plays wake ack on the
        // living-room speaker instead — see MAC_VOICE_PHONE_HAP1_WAKE_ACK.
        // If a speak frame still arrives, only update UI; never synthesize.
        speakWatchdog?.cancel()
        isSpeakingLocally = true
        speech.stopSpeaking(at: .immediate)
        publishStatus("客厅已应答")
        let work = DispatchWorkItem { [weak self] in
            self?.finishSpeak()
        }
        speakWatchdog = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.0, execute: work)
    }

    private func finishSpeak() {
        speakWatchdog?.cancel()
        speakWatchdog = nil
        isSpeakingLocally = false
        energyGate.reset()
        if isListening {
            publishStatus(client.isConnected ? "拾音中" : "拾音中（等待连接）")
        }
    }

    // MARK: - Private

    private func beginCaptureAfterPermission() {
        connectIfNeeded()
        energyGate.reset()
        do {
            try capture.start(
                onPCM: { [weak self] data in
                    self?.handlePCM(data)
                },
                onLevel: { [weak self] level in
                    self?.onAudioLevel?(level)
                }
            )
            isListening = true
            publishStatus(client.isConnected ? "拾音中" : "拾音中（等待连接）")
        } catch {
            isListening = false
            publishStatus(error.localizedDescription)
            setConnection(.failed(error.localizedDescription))
        }
    }

    private func handlePCM(_ data: Data) {
        guard isListening else { return }
        // Avoid uploading phone TTS into STT while speaking locally.
        if isSpeakingLocally {
            return
        }
        let chunks: [Data]
        if HomeMicSettings.energyGateEnabled {
            chunks = energyGate.filter(data, enabled: true)
        } else {
            chunks = data.isEmpty ? [] : [data]
        }
        guard client.isConnected else { return }
        for chunk in chunks where !chunk.isEmpty {
            client.sendPCM(chunk)
        }
    }

    private func requestMicPermission(completion: @escaping (Bool) -> Void) {
        switch AVAudioSession.sharedInstance().recordPermission {
        case .granted:
            DispatchQueue.main.async { completion(true) }
        case .denied:
            DispatchQueue.main.async { completion(false) }
        case .undetermined:
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async { completion(granted) }
            }
        @unknown default:
            DispatchQueue.main.async { completion(false) }
        }
    }

    private func setConnection(_ state: HomeMicConnectionState) {
        connectionState = state
        onConnectionStateChange?(state)
    }

    private func publishStatus(_ text: String) {
        onStatusChange?(text)
    }
}

extension HomeMicController: AVSpeechSynthesizerDelegate {
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        finishSpeak()
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        finishSpeak()
    }
}
