import Foundation
import Network

enum HomeMicHap1Command: String {
    case setNormal = "set_normal"
    case setPowerSave = "set_power_save"
    case stop
    case exit
}

struct HomeMicHap1ServerCommand: Equatable {
    let type: HomeMicHap1Command
    let branch: String?
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

    var onCommand: ((HomeMicHap1ServerCommand) -> Void)?
    var onDisconnected: (() -> Void)?
    var onHeartbeatSent: (() -> Void)?

    var isConnected: Bool {
        connection?.state == .ready
    }

    /// Connect and send HAP1 hello. Callback on main queue.
    func connect(
        host: String,
        port: UInt16,
        deviceId: String,
        participantId: String = "",
        completion: @escaping (Error?) -> Void
    ) {
        close()
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
        let once = ConnectOnce()
        conn.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                once.finish {
                    guard let self = self else {
                        DispatchQueue.main.async { completion(HomeMicHap1Error.sendFailed("已释放")) }
                        return
                    }
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
                        self.startHeartbeat(deviceId: deviceId, participantId: edgePid)
                        self.startReceiveLoop()
                        DispatchQueue.main.async { completion(nil) }
                    } catch {
                        DispatchQueue.main.async { completion(error) }
                    }
                }
            case .failed(let err):
                once.finish {
                    DispatchQueue.main.async {
                        completion(HomeMicHap1Error.sendFailed(err.localizedDescription))
                    }
                }
            case .cancelled:
                once.finish {
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
            guard let self = self, let frame = Self.packFrame(type: 2, payload: data) else { return }
            self.sendRaw(frame)
        }
    }

    func close() {
        heartbeatTimer?.cancel()
        heartbeatTimer = nil
        receiving = false
        receiveBuffer.removeAll()
        connection?.cancel()
        connection = nil
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
        connection.send(content: data, completion: .contentProcessed { _ in })
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
                self.receiveBuffer.append(data)
                self.drainFrames()
            }
            if error != nil || isComplete {
                self.receiving = false
                DispatchQueue.main.async { [weak self] in
                    self?.onDisconnected?()
                }
                return
            }
            self.receiveNext()
        }
    }

    private func drainFrames() {
        while true {
            guard receiveBuffer.count >= 10 else { return }
            guard receiveBuffer.prefix(4) == Data("HAP1".utf8) else {
                receiveBuffer.removeAll()
                return
            }
            let length = Int(receiveBuffer[6]) << 24
                | Int(receiveBuffer[7]) << 16
                | Int(receiveBuffer[8]) << 8
                | Int(receiveBuffer[9])
            let total = 10 + length
            guard receiveBuffer.count >= total else { return }
            let frameType = receiveBuffer[4]
            let payload = receiveBuffer.subdata(in: 10 ..< total)
            receiveBuffer.removeFirst(total)
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
        DispatchQueue.main.async { [weak self] in
            self?.onCommand?(HomeMicHap1ServerCommand(type: cmd, branch: branch))
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
