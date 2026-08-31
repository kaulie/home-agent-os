import Foundation
import Network

enum HomeMicHap1Command: String {
    case setNormal = "set_normal"
    case setPowerSave = "set_power_save"
    case stop
    case exit
    case speak
}

struct HomeMicHap1ServerCommand: Equatable {
    let type: HomeMicHap1Command
    let branch: String?
    let text: String?
}

enum HomeMicHap1Error: LocalizedError {
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
/// Completion-based for iOS 12 / UIKit (no async/await).
final class HomeMicHap1Client {
    private let queue = DispatchQueue(label: "livingroom.homemics.hap1")
    private var connection: NWConnection?
    private var heartbeatTimer: DispatchSourceTimer?
    private var receiving = false
    private var receiveBuffer = Data()
    /// Explicit ready flag — do not trust `NWConnection.state` off the NW queue on iOS 12.
    private var sessionReady = false
    private var closingIntentionally = false
    private var connectGeneration = 0
    private var lastReceiveAt = Date.distantPast

    var onCommand: ((HomeMicHap1ServerCommand) -> Void)?
    var onDisconnected: (() -> Void)?
    var onHeartbeatSent: (() -> Void)?

    var isConnected: Bool {
        sessionReady && connection != nil
    }

    /// Mac echoes HAP1 heartbeats; stale receive ⇒ half-open after Mac restart.
    func isLikelyAlive(maxAge: TimeInterval) -> Bool {
        var alive = false
        queue.sync {
            alive = sessionReady && Date().timeIntervalSince(lastReceiveAt) <= maxAge
        }
        return alive
    }

    /// Connect and send HAP1 hello. Callback on main queue.
    func connect(
        host: String,
        port: UInt16,
        deviceId: String,
        participantId: String = "",
        completion: @escaping (Error?) -> Void
    ) {
        close(notify: false)
        closingIntentionally = false
        sessionReady = false
        connectGeneration += 1
        let generation = connectGeneration

        if let refuse = MdnsDiscovery.refuseNonIPv4TCP(host) {
            DispatchQueue.main.async {
                completion(HomeMicHap1Error.sendFailed(refuse))
            }
            return
        }
        guard let ipv4 = IPv4Address(host.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            DispatchQueue.main.async {
                completion(HomeMicHap1Error.sendFailed("TCP 目标不是局域网 IPv4（\(host)）"))
            }
            return
        }

        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        tcp.enableKeepalive = true
        let params = NWParameters(tls: nil, tcp: tcp)
        let conn = NWConnection(
            host: .ipv4(ipv4),
            port: NWEndpoint.Port(rawValue: port) ?? 8792,
            using: params
        )
        connection = conn
        let once = ConnectOnce()
        conn.stateUpdateHandler = { [weak self] state in
            guard let self = self else { return }
            switch state {
            case .ready:
                once.finish {
                    guard generation == self.connectGeneration else { return }
                    do {
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
                        try self.sendJSONFrame(type: 4, object: hello)
                        self.sessionReady = true
                        self.lastReceiveAt = Date()
                        self.startHeartbeat(deviceId: deviceId, participantId: edgePid)
                        self.startReceiveLoop()
                        DispatchQueue.main.async { completion(nil) }
                    } catch {
                        self.sessionReady = false
                        DispatchQueue.main.async { completion(error) }
                    }
                }
            case .failed(let err):
                once.finish {
                    guard generation == self.connectGeneration else { return }
                    self.sessionReady = false
                    DispatchQueue.main.async {
                        completion(HomeMicHap1Error.sendFailed(err.localizedDescription))
                    }
                }
            case .cancelled:
                once.finish {
                    // Intentional close / superseded connect — do not fail the new attempt.
                    guard generation == self.connectGeneration, !self.closingIntentionally else { return }
                    self.sessionReady = false
                    DispatchQueue.main.async {
                        completion(HomeMicHap1Error.sendFailed("连接已取消"))
                    }
                }
            default:
                break
            }
        }
        conn.start(queue: queue)
    }

    func sendPCM(_ data: Data) {
        guard !data.isEmpty else { return }
        queue.async { [weak self] in
            guard let self = self, self.sessionReady else { return }
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
            guard let self = self else { return }
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
            throw HomeMicHap1Error.sendFailed("帧编码失败")
        }
        sendRaw(frame)
    }

    private func sendRaw(_ data: Data) {
        guard let connection = connection, connection.state == .ready else { return }
        connection.send(content: data, completion: .contentProcessed { [weak self] error in
            guard let self = self, let error = error else { return }
            self.queue.async {
                guard self.sessionReady, !self.closingIntentionally else { return }
                self.sessionReady = false
                self.receiving = false
                DispatchQueue.main.async {
                    self.onDisconnected?()
                }
                _ = error
            }
        })
    }

    private func startReceiveLoop() {
        guard !receiving else { return }
        receiving = true
        receiveNext()
    }

    private func receiveNext() {
        guard receiving, let connection = connection else { return }
        connection.receive(minimumIncompleteLength: 1, maximumLength: 65_536) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            if let data = data, !data.isEmpty {
                self.lastReceiveAt = Date()
                self.receiveBuffer.append(data)
                self.drainFrames()
            }
            if error != nil || isComplete {
                self.receiving = false
                let wasReady = self.sessionReady
                let intentional = self.closingIntentionally
                self.sessionReady = false
                // Ignore tear-down from close()/reconnect.
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
        // Data.removeFirst keeps a non-zero startIndex; subscript with absolute
        // Int (e.g. [6]) then traps. Always index from startIndex / dropFirst.
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
            // Reject absurd lengths (corruption / desync) instead of hanging.
            guard length >= 0, length <= 1_000_000 else {
                receiveBuffer.removeAll(keepingCapacity: false)
                return
            }
            let total = 10 + length
            guard receiveBuffer.count >= total else { return }
            let frameType = receiveBuffer[start + 4]
            let payload = Data(receiveBuffer[(start + 10)..<(start + total)])
            receiveBuffer = Data(receiveBuffer.dropFirst(total))
            // type 1 = Mac heartbeat echo; type 3 = command
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
            let cmd = HomeMicHap1Command(rawValue: typeRaw)
        else { return }
        let branch = obj["branch"] as? String
        let text = obj["text"] as? String
        DispatchQueue.main.async { [weak self] in
            self?.onCommand?(HomeMicHap1ServerCommand(type: cmd, branch: branch, text: text))
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
