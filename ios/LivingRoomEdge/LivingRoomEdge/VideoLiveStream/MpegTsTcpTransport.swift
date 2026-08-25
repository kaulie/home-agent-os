import Foundation
import Network

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

enum MpegTsTcpTransportError: LocalizedError {
    case failed(String)
    var errorDescription: String? {
        switch self {
        case .failed(let msg): return msg
        }
    }
}

/// Transport Adapter v1: MPEG-TS over TCP (same wire Larix Broadcaster uses).
final class MpegTsTcpTransport {
    private var connection: NWConnection?
    private let queue = DispatchQueue(label: "homeagent.video.live.tcp")
    private var pending: [Data] = []
    private var inFlight = false
    private var pendingBytes = 0
    private let maxQueueBytes = 2_000_000

    var isReady: Bool {
        connection?.state == .ready
    }

    func connect(host: String, port: UInt16) async throws {
        close()
        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        tcp.enableKeepalive = true
        let params = NWParameters(tls: nil, tcp: tcp)
        let conn = NWConnection(
            host: NWEndpoint.Host(host),
            port: NWEndpoint.Port(rawValue: port) ?? 5004,
            using: params
        )
        connection = conn
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            let once = ConnectOnce()
            conn.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    once.finish { cont.resume() }
                case .failed(let err):
                    once.finish {
                        cont.resume(throwing: MpegTsTcpTransportError.failed("连接 Mac 失败：\(err.localizedDescription)"))
                    }
                case .cancelled:
                    once.finish {
                        cont.resume(throwing: MpegTsTcpTransportError.failed("连接已取消。"))
                    }
                default:
                    break
                }
            }
            conn.start(queue: queue)
        }
    }

    func send(_ data: Data) {
        guard !data.isEmpty else { return }
        queue.async { [weak self] in
            guard let self else { return }
            if self.pendingBytes > self.maxQueueBytes {
                self.pending.removeAll()
                self.pendingBytes = 0
            }
            self.pending.append(data)
            self.pendingBytes += data.count
            self.pump()
        }
    }

    func close() {
        queue.sync { [weak self] in
            guard let self else { return }
            self.pending.removeAll()
            self.pendingBytes = 0
            self.inFlight = false
            self.connection?.cancel()
            self.connection = nil
        }
    }

    private func pump() {
        guard !inFlight, let connection, connection.state == .ready else { return }
        guard !pending.isEmpty else { return }
        let chunk = pending.removeFirst()
        pendingBytes = max(0, pendingBytes - chunk.count)
        inFlight = true
        connection.send(content: chunk, completion: .contentProcessed { [weak self] _ in
            guard let self else { return }
            self.queue.async {
                self.inFlight = false
                self.pump()
            }
        })
    }
}
