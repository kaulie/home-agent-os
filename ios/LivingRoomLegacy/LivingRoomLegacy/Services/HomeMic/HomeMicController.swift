import AVFoundation
import Foundation
import UIKit

/// Connection + capture state for `@ui` Home Mic screen.
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

/// Orchestrates HAP1 + PCM + energy gate. No UI — bind from HomeMicViewController.
final class HomeMicController {
    private let client = HomeMicHap1Client()
    private let capture = HomeMicPcmCapture()
    private let energyGate = HomeMicEnergyGate()

    private(set) var isListening = false
    private(set) var connectionState: HomeMicConnectionState = .disconnected

    /// 0…1, always on main.
    var onAudioLevel: ((Float) -> Void)?
    /// Connection + capture status line, always on main.
    var onStatusChange: ((String) -> Void)?
    var onConnectionStateChange: ((HomeMicConnectionState) -> Void)?

    init() {
        client.onDisconnected = { [weak self] in
            guard let self = self else { return }
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
            }
        }
    }

    deinit {
        stopListening()
        client.close()
    }

    /// Connect (or reconnect) using `HomeMicSettings` + `ParticipantStore` identity.
    func connectIfNeeded() {
        if client.isConnected {
            setConnection(.connected)
            return
        }
        setConnection(.connecting)
        publishStatus("连接中…")
        let host = HomeMicSettings.host
        let port = HomeMicSettings.port
        let deviceId = ParticipantStore.clientHint
        let participantId = ParticipantStore.participantId
        client.connect(
            host: host,
            port: port,
            deviceId: deviceId,
            participantId: participantId
        ) { [weak self] error in
            guard let self = self else { return }
            if let error = error {
                self.setConnection(.failed(error.localizedDescription))
                self.publishStatus(error.localizedDescription)
                return
            }
            self.setConnection(.connected)
            self.publishStatus(self.isListening ? "拾音中" : "已连接")
        }
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
        stopListening()
        client.close()
        setConnection(.disconnected)
        publishStatus("未连接")
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
