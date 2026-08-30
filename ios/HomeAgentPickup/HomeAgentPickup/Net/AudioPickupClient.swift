import Foundation
import Network

enum PickupCommand: String {
    case setNormal = "set_normal"
    case setPowerSave = "set_power_save"
    case stop
    case exit
    case speak
}

struct PickupServerCommand: Equatable {
    let type: PickupCommand
    let branch: String?
    let text: String?
}

enum AudioPickupClientError: LocalizedError {
    case notConnected
    case sendFailed(String)

    var errorDescription: String? {
        switch self {
        case .notConnected: return "TCP 未连接"
        case .sendFailed(let msg): return msg
        }
    }
}

/// HAP1 multiplexed TCP client (heartbeat + PCM upstream, JSON commands downstream).
final class AudioPickupClient {
    private let queue = DispatchQueue(label: "homeagent.pickup.tcp")
    private var connection: NWConnection?
    private var heartbeatTimer: DispatchSourceTimer?
    private var receiving = false
    private var receiveBuffer = Data()
    /// Explicit ready flag — do not trust `NWConnection.state` off the NW queue.
    private var sessionReady = false
    private var closingIntentionally = false
    private var connectGeneration = 0
    private var lastActivityAt = Date.distantPast
    private var lastReceiveAt = Date.distantPast

    var onCommand: ((PickupServerCommand) -> Void)?
    var onDisconnected: (() -> Void)?
    var onHeartbeatSent: (() -> Void)?

    var isConnected: Bool {
        sessionReady && connection != nil
    }

    /// True if we recently received bytes from Mac (heartbeat echo / speak).
    func isLikelyAlive(maxAge: TimeInterval) -> Bool {
        queue.sync {
            sessionReady && Date().timeIntervalSince(lastReceiveAt) <= maxAge
        }
    }

    func connect(host: String, port: UInt16, deviceId: String, participantId: String = "") async throws {
        close(notify: false)
        closingIntentionally = false
        sessionReady = false
        connectGeneration += 1
        let generation = connectGeneration

        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        tcp.enableKeepalive = true
        let params = NWParameters(tls: nil, tcp: tcp)
        let conn = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port) ?? 8792,
            using: params
        )
        connection = conn

        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            let once = ConnectOnce()
            conn.stateUpdateHandler = { [weak self] state in
                guard let self else { return }
                switch state {
                case .ready:
                    once.finish {
                        guard generation == self.connectGeneration else { return }
                        self.sessionReady = true
                        self.lastActivityAt = Date()
                        self.lastReceiveAt = Date()
                        cont.resume()
                    }
                case .failed(let err):
                    once.finish {
                        guard generation == self.connectGeneration else { return }
                        self.sessionReady = false
                        cont.resume(throwing: AudioPickupClientError.sendFailed(err.localizedDescription))
                    }
                case .cancelled:
                    once.finish {
                        guard generation == self.connectGeneration, !self.closingIntentionally else { return }
                        self.sessionReady = false
                        cont.resume(throwing: AudioPickupClientError.sendFailed("连接已取消"))
                    }
                default:
                    break
                }
            }
            conn.start(queue: queue)
        }

        let edgePid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        var hello: [String: Any] = [
            "type": "hello",
            "device_id": deviceId,
            "sample_rate": 44_100,
            "channels": 1,
            "sample_format": "s16le",
        ]
        if !edgePid.isEmpty {
            hello["participant_id"] = edgePid
            hello["edge_id"] = edgePid
        }
        try sendJSONFrame(type: 4, object: hello)
        startHeartbeat(deviceId: deviceId, participantId: edgePid)
        startReceiveLoop()
    }

    func sendPCM(_ data: Data) {
        guard !data.isEmpty else { return }
        queue.async { [weak self] in
            guard let self, self.sessionReady else { return }
            guard let frame = Self.packFrame(type: 2, payload: data) else { return }
            self.sendRaw(frame)
        }
    }

    func close() {
        close(notify: false)
    }

    private func close(notify: Bool) {
        closingIntentionally = true
        sessionReady = false
        heartbeatTimer?.cancel()
        heartbeatTimer = nil
        receiving = false
        receiveBuffer.removeAll()
        let conn = connection
        connection = nil
        conn?.cancel()
        if notify {
            DispatchQueue.main.async { [weak self] in
                self?.onDisconnected?()
            }
        }
    }

    private func startHeartbeat(deviceId: String, participantId: String = "") {
        heartbeatTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 8, repeating: 8)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            var payload: [String: Any] = [
                "type": "heartbeat",
                "device_id": deviceId,
                "ts": Int(Date().timeIntervalSince1970),
            ]
            if !participantId.isEmpty {
                payload["participant_id"] = participantId
                payload["edge_id"] = participantId
            }
            try? self.sendJSONFrame(type: 1, object: payload)
            DispatchQueue.main.async { [weak self] in
                self?.onHeartbeatSent?()
            }
        }
        timer.resume()
        heartbeatTimer = timer
    }

    private func sendJSONFrame(type: UInt8, object: [String: Any]) throws {
        guard let body = try? JSONSerialization.data(withJSONObject: object) else { return }
        guard let frame = Self.packFrame(type: type, payload: body) else {
            throw AudioPickupClientError.sendFailed("帧编码失败")
        }
        sendRaw(frame)
    }

    private func sendRaw(_ data: Data) {
        guard sessionReady, let connection else { return }
        connection.send(content: data, completion: .contentProcessed { [weak self] error in
            guard let self else { return }
            if let error {
                self.queue.async {
                    guard self.sessionReady, !self.closingIntentionally else { return }
                    self.sessionReady = false
                    self.receiving = false
                    DispatchQueue.main.async {
                        self.onDisconnected?()
                    }
                    _ = error
                }
                return
            }
            self.queue.async {
                self.lastActivityAt = Date()
            }
        })
    }

    private func startReceiveLoop() {
        guard !receiving else { return }
        receiving = true
        receiveNext()
    }

    private func receiveNext() {
        guard receiving, let connection else { return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let data, !data.isEmpty {
                self.lastActivityAt = Date()
                self.lastReceiveAt = Date()
                self.receiveBuffer.append(data)
                self.drainFrames()
            }
            if error != nil || isComplete {
                self.receiving = false
                let wasReady = self.sessionReady
                let intentional = self.closingIntentionally
                self.sessionReady = false
                guard wasReady, !intentional else { return }
                DispatchQueue.main.async { [weak self] in
                    self?.onDisconnected?()
                }
                return
            }
            self.receiveNext()
        }
    }

    private func drainFrames() {
        // Data.removeFirst keeps a non-zero startIndex; absolute Int subscript traps.
        while true {
            guard receiveBuffer.count >= 10 else { return }
            let start = receiveBuffer.startIndex
            let magicEnd = start + 4
            guard receiveBuffer[start..<magicEnd].elementsEqual("HAP1".utf8) else {
                receiveBuffer.removeAll(keepingCapacity: false)
                return
            }
            let length = Int(receiveBuffer[start + 6]) << 24
                | Int(receiveBuffer[start + 7]) << 16
                | Int(receiveBuffer[start + 8]) << 8
                | Int(receiveBuffer[start + 9])
            guard length >= 0, length <= 1_000_000 else {
                receiveBuffer.removeAll(keepingCapacity: false)
                return
            }
            let total = 10 + length
            guard receiveBuffer.count >= total else { return }
            let frameType = receiveBuffer[start + 4]
            let payload = Data(receiveBuffer[(start + 10)..<(start + total)])
            receiveBuffer = Data(receiveBuffer.dropFirst(total))
            // type 1 = heartbeat echo from Mac; type 3 = command
            if frameType == 1 || frameType == 3 {
                lastReceiveAt = Date()
            }
            if frameType == 3 {
                handleCommandPayload(payload)
            }
        }
    }

    private func handleCommandPayload(_ payload: Data) {
        guard
            let obj = try? JSONSerialization.jsonObject(with: payload) as? [String: Any],
            let typeRaw = obj["type"] as? String,
            let cmd = PickupCommand(rawValue: typeRaw)
        else { return }
        let branch = obj["branch"] as? String
        let text = obj["text"] as? String
        DispatchQueue.main.async { [weak self] in
            self?.onCommand?(PickupServerCommand(type: cmd, branch: branch, text: text))
        }
    }

    private static func packFrame(type: UInt8, payload: Data) -> Data? {
        guard payload.count <= 8_000_000 else { return nil }
        var data = Data("HAP1".utf8)
        data.append(type)
        data.append(0)
        var len = UInt32(payload.count).bigEndian
        withUnsafeBytes(of: &len) { data.append(contentsOf: $0) }
        data.append(payload)
        return data
    }
}

private final class ConnectOnce {
    private let lock = NSLock()
    private var done = false

    func finish(_ body: () -> Void) {
        lock.lock()
        if done {
            lock.unlock()
            return
        }
        done = true
        lock.unlock()
        body()
    }
}
