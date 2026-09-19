import AVFoundation
import AudioToolbox
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

/// Orchestrates HAP1 + PCM + energy gate + local wake-ack playback for HAP1 speak.
final class HomeMicController: NSObject {
    private let client = HomeMicHap1Client()
    private let capture = HomeMicPcmCapture()
    private let energyGate = HomeMicEnergyGate()
    private var player: AVAudioPlayer?
    private var preparedAckPlayers: [String: AVAudioPlayer] = [:]
    private var systemSoundID: SystemSoundID = 0
    private var speechSynth: AVSpeechSynthesizer?

    private(set) var isListening = false
    private(set) var connectionState: HomeMicConnectionState = .disconnected
    /// True while local TTS is speaking (skip uploading that audio).
    private(set) var isSpeakingLocally = false
    private var speakWatchdog: DispatchWorkItem?
    private var finishingSpeak = false

    /// 0…1, always on main.
    var onAudioLevel: ((Float) -> Void)?
    /// Connection + capture status line, always on main.
    var onStatusChange: ((String) -> Void)?
    var onConnectionStateChange: ((HomeMicConnectionState) -> Void)?

    override init() {
        super.init()
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
        disposeSystemSound()
        player?.stop()
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
        if let refuse = MdnsDiscovery.refuseNonIPv4TCP(host) {
            HomeMicSettings.host = ""
            publishStatus("正在发现 \(HomeMicSettings.defaultMdnsHost)…")
            HomeMicSettings.autoDiscoverGateway { [weak self] gateway in
                guard let self = self else { return }
                self.isConnecting = false
                if gateway == nil {
                    self.setConnection(.failed(refuse))
                    if self.isListening {
                        self.scheduleReconnect()
                    }
                    return
                }
                self.connectIfNeeded()
            }
            return
        }
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
                HomeMicSettings.host = ""
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
        disposeSystemSound()
        player?.stop()
        player = nil
        preparedAckPlayers.removeAll()
        isSpeakingLocally = false
        finishingSpeak = false
        speakWatchdog?.cancel()
        speakWatchdog = nil
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

    // MARK: - Local wake ack (HAP1 speak)

    func speakLocally(_ text: String) {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        // HAP1 crash was frame parsing, not audio — keep capture running and
        // only mute uplink. Preloaded AVAudioPlayer cuts ack latency.
        speakWatchdog?.cancel()
        finishingSpeak = false
        isSpeakingLocally = true
        player?.stop()
        player = nil
        disposeSystemSound()

        publishStatus("正在回复…")
        // iOS 12: AVAudioPlayer is often silent while AVAudioEngine holds I/O.
        capture.pauseEngine()
        do {
            try AVAudioSession.sharedInstance().overrideOutputAudioPort(.speaker)
        } catch {
            // defaultToSpeaker usually covers this.
        }

        guard let url = Self.bundledAckURL(for: body) else {
            // Missing bundle asset (bad deploy) — still give audible feedback.
            speakWithSpeechSynthesizer(body)
            return
        }

        let key = url.lastPathComponent
        let p: AVAudioPlayer
        if let warmed = preparedAckPlayers[key] {
            warmed.stop()
            warmed.currentTime = 0
            p = warmed
        } else if let created = try? AVAudioPlayer(contentsOf: url) {
            created.prepareToPlay()
            preparedAckPlayers[key] = created
            p = created
        } else {
            speakWithSpeechSynthesizer(body)
            return
        }
        p.delegate = self
        p.volume = 1.0
        player = p
        if !p.play() {
            speakWithSpeechSynthesizer(body)
            return
        }

        let work = DispatchWorkItem { [weak self] in
            guard let self = self, self.isSpeakingLocally else { return }
            self.player?.stop()
            self.finishSpeak()
        }
        speakWatchdog = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 4.0, execute: work)
    }

    private static func bundledAckURL(for text: String) -> URL? {
        let compact = text
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "，", with: "")
            .replacingOccurrences(of: "。", with: "")
            .replacingOccurrences(of: "？", with: "")
            .replacingOccurrences(of: "!", with: "")
        let name: String
        if compact.contains("我在呢") || compact == "在呢" {
            name = "wake_ack_wozaine"
        } else if compact.contains("又咋了") || compact.contains("咋了") {
            name = "wake_ack_youzale"
        } else {
            name = "wake_ack_wozaine"
        }
        return Bundle.main.url(forResource: name, withExtension: "caf")
    }

    private func scheduleFinishSpeak(after delay: TimeInterval) {
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.finishSpeak()
        }
    }

    private func finishSpeak() {
        guard !finishingSpeak else { return }
        finishingSpeak = true
        speakWatchdog?.cancel()
        speakWatchdog = nil
        player?.stop()
        player = nil
        speechSynth?.stopSpeaking(at: .immediate)
        speechSynth = nil
        disposeSystemSound()
        try? AVAudioSession.sharedInstance().overrideOutputAudioPort(.none)
        isSpeakingLocally = false
        // Soft-resume mic after local ack; do not reset energyGate (onset chop).
        capture.resumeEngineIfNeeded()
        finishingSpeak = false
        if isListening {
            publishStatus(client.isConnected ? "拾音中" : "拾音中（等待连接）")
        }
    }

    private func speakWithSpeechSynthesizer(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        if let voice = AVSpeechSynthesisVoice(language: "zh-CN") {
            utterance.voice = voice
        }
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
        let synth = AVSpeechSynthesizer()
        speechSynth = synth
        synth.speak(utterance)
        scheduleFinishSpeak(after: max(1.2, Double(text.count) * 0.35))
    }

    private func disposeSystemSound() {
        if systemSoundID != 0 {
            AudioServicesDisposeSystemSoundID(systemSoundID)
            systemSoundID = 0
        }
    }

    private func preloadAckPlayers() {
        for name in ["wake_ack_wozaine", "wake_ack_youzale"] {
            guard let url = Bundle.main.url(forResource: name, withExtension: "caf") else { continue }
            let key = url.lastPathComponent
            if preparedAckPlayers[key] != nil { continue }
            if let p = try? AVAudioPlayer(contentsOf: url) {
                p.prepareToPlay()
                preparedAckPlayers[key] = p
            }
        }
    }

    // MARK: - Private

    private func beginCaptureAfterPermission() {
        connectIfNeeded()
        energyGate.reset()
        preloadAckPlayers()
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
        // Keep uploading during local wake-ack. Muting here chopped the start of
        // the follow-up command (打开 → 开 / 客厅空调).「我在呢」echo is dropped
        // by the Mac wake gate.
        let chunks = energyGate.filter(data, enabled: HomeMicSettings.energyGateEnabled)
        guard client.isConnected else { return }
        for chunk in chunks where !chunk.isEmpty {
            client.sendPCM(chunk)
        }
        // The Mac only ever sees uploaded speech, so tell it how long the room has
        // been quiet: without this the segmenter cannot endpoint and every clip
        // runs to the 2.8s wake max (「面条面条 → 我在呢」 feels slow).
        let quietMs = energyGate.takeQuietReportMs()
        if quietMs > 0 {
            client.sendQuietGap(ms: Int(quietMs.rounded()))
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

extension HomeMicController: AVAudioPlayerDelegate {
    func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        finishSpeak()
    }

    func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        finishSpeak()
    }
}
