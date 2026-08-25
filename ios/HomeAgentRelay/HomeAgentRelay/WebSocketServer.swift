import CryptoKit
import Foundation
import Network

/// Minimal WebSocket server on 0.0.0.0:8081, path `/present`.
/// Handshake + text frames only. No third-party libraries.
final class WebSocketServer {
    static let port: UInt16 = 8081
    static let path = "/present"

    private let queue: DispatchQueue
    private let log: (String) -> Void
    private let onState: (String, String?) -> Void
    private let onTextMessage: (String) -> Void
    private let onPeer: (RelayPeerEvent) -> Void

    private var listener: NWListener?
    private var connections: [ObjectIdentifier: WebSocketConnection] = [:]

    private(set) var listenerState: String = "idle"
    private(set) var lastError: String?

    init(
        queue: DispatchQueue,
        log: @escaping (String) -> Void,
        onState: @escaping (String, String?) -> Void,
        onTextMessage: @escaping (String) -> Void,
        onPeer: @escaping (RelayPeerEvent) -> Void
    ) {
        self.queue = queue
        self.log = log
        self.onState = onState
        self.onTextMessage = onTextMessage
        self.onPeer = onPeer
    }

    var isRunning: Bool {
        listener != nil && (listenerState == "ready" || listenerState == "setup")
    }

    func start() {
        queue.async { [weak self] in
            self?.startLocked()
        }
    }

    func stop() {
        queue.async { [weak self] in
            self?.stopLocked(reason: "stop requested")
        }
    }

    private func startLocked() {
        if listener != nil {
            log("WebSocket server already starting/running (state=\(listenerState))")
            dumpDiagnosticsLocked()
            return
        }

        lastError = nil
        do {
            let next = try HTTPServer.makeListener(port: Self.port, log: log)
            listener = next
            log("WebSocket path=\(Self.path)")
            attach(next)
            next.start(queue: queue)
            log("WebSocket server started; waiting for NWListener state=ready")
        } catch {
            let message = "WebSocket NWListener init failed: \(error.localizedDescription) (\(error))"
            lastError = message
            listenerState = "failed"
            log(message)
            onState(listenerState, lastError)
        }
    }

    private func stopLocked(reason: String) {
        log("WebSocket server stopping (\(reason))")
        for connection in connections.values {
            connection.cancel()
        }
        connections.removeAll()
        listener?.stateUpdateHandler = nil
        listener?.newConnectionHandler = nil
        listener?.cancel()
        listener = nil
        listenerState = "stopped"
        onState(listenerState, lastError)
        log("WebSocket server stopped")
    }

    private func attach(_ listener: NWListener) {
        listener.stateUpdateHandler = { [weak self] state in
            self?.handleListenerState(state, listener: listener)
        }
        listener.newConnectionHandler = { [weak self] connection in
            self?.accept(connection)
        }
    }

    private func handleListenerState(_ state: NWListener.State, listener: NWListener) {
        let portText = listener.port.map { String(describing: $0) } ?? "nil"
        switch state {
        case .setup:
            listenerState = "setup"
            lastError = nil
            log("WebSocket listener state=setup listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText)")
        case .waiting(let error):
            listenerState = "waiting"
            lastError = HTTPServer.describe(error)
            log("WebSocket listener state=waiting listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText) error=\(HTTPServer.describe(error))")
            dumpDiagnosticsLocked()
        case .ready:
            listenerState = "ready"
            lastError = nil
            log("WebSocket listener state=ready listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText)")
            dumpDiagnosticsLocked()
        case .failed(let error):
            listenerState = "failed"
            lastError = HTTPServer.describe(error)
            log("WebSocket listener state=failed listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText) error=\(HTTPServer.describe(error))")
            dumpDiagnosticsLocked()
            stopLocked(reason: "listener failed")
            return
        case .cancelled:
            listenerState = "cancelled"
            log("WebSocket listener state=cancelled")
        @unknown default:
            listenerState = String(describing: state)
            log("WebSocket listener state=\(listenerState)")
        }
        onState(listenerState, lastError)
    }

    private func accept(_ connection: NWConnection) {
        let endpoint = String(describing: connection.endpoint)
        log("WebSocket connection attempt endpoint=\(endpoint) state=\(String(describing: connection.state))")
        let session = WebSocketConnection(
            connection: connection,
            queue: queue,
            log: log,
            onTextMessage: onTextMessage,
            onPeer: onPeer,
            onClose: { [weak self] session in
                self?.connections.removeValue(forKey: ObjectIdentifier(session))
            }
        )
        connections[ObjectIdentifier(session)] = session
        session.start()
    }

    func dumpDiagnostics() {
        queue.async { [weak self] in
            self?.dumpDiagnosticsLocked()
        }
    }

    private func dumpDiagnosticsLocked() {
        let addresses = NetworkAddressProvider.ipv4Addresses()
        let addressText = addresses.map { "\($0.interface)=\($0.address)" }.joined(separator: ", ")
        log("WebSocket diagnostics listenerState=\(listenerState) listeningAddress=0.0.0.0:\(Self.port) lastError=\(lastError ?? "none")")
        log("WebSocket diagnostics IPv4: \(addressText.isEmpty ? "(none)" : addressText)")
        log("WebSocket diagnostics \(NetworkAddressProvider.hotspotHint(from: addresses))")
        log("WebSocket diagnostics activeConnections=\(connections.count)")
    }
}

private final class WebSocketConnection {
    private enum Phase {
        case handshake
        case frames
    }

    let connection: NWConnection
    private let id = UUID()
    private let queue: DispatchQueue
    private let log: (String) -> Void
    private let onTextMessage: (String) -> Void
    private let onPeer: (RelayPeerEvent) -> Void
    private let onClose: (WebSocketConnection) -> Void
    private var buffer = Data()
    private var phase: Phase = .handshake
    private var closed = false
    private var announced = false

    init(
        connection: NWConnection,
        queue: DispatchQueue,
        log: @escaping (String) -> Void,
        onTextMessage: @escaping (String) -> Void,
        onPeer: @escaping (RelayPeerEvent) -> Void,
        onClose: @escaping (WebSocketConnection) -> Void
    ) {
        self.connection = connection
        self.queue = queue
        self.log = log
        self.onTextMessage = onTextMessage
        self.onPeer = onPeer
        self.onClose = onClose
    }

    func start() {
        connection.stateUpdateHandler = { [weak self] state in
            self?.handleState(state)
        }
        connection.start(queue: queue)
        receive()
    }

    func cancel() {
        finish()
    }

    private func handleState(_ state: NWConnection.State) {
        let remote = remoteDescription()
        switch state {
        case .setup:
            log("WebSocket connection state=setup remote=\(remote)")
        case .waiting(let error):
            log("WebSocket connection state=waiting remote=\(remote) error=\(HTTPServer.describe(error))")
        case .preparing:
            log("WebSocket connection state=preparing remote=\(remote)")
        case .ready:
            announcePeer()
            log("WebSocket TCP ready remote=\(peer().display)")
        case .failed(let error):
            log("WebSocket connection state=failed remote=\(remote) error=\(HTTPServer.describe(error))")
            finish()
        case .cancelled:
            finish()
        @unknown default:
            log("WebSocket connection state=\(state) remote=\(remote)")
        }
    }

    private func peer() -> RemotePeer {
        NetworkAddressProvider.remotePeer(from: connection)
    }

    private func announcePeer() {
        guard !announced else { return }
        announced = true
        let remote = peer()
        onPeer(.opened(id: id, ip: remote.ip, port: remote.port, kind: "WebSocket"))
    }

    private func noteActivity(_ detail: String, request: HTTPRequest? = nil) {
        announcePeer()
        let remote = peer()
        onPeer(.activity(
            id: id,
            detail: detail,
            ip: remote.ip,
            port: remote.port,
            headers: request?.headerFields ?? []
        ))
    }

    private func remoteDescription() -> String {
        if let path = connection.currentPath, let remote = path.remoteEndpoint {
            return String(describing: remote)
        }
        return String(describing: connection.endpoint)
    }

    private func receive() {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 64 * 1024) { [weak self] data, _, isComplete, error in
            guard let self else { return }
            if let error {
                self.log("WebSocket receive error=\(error.localizedDescription) (\(error))")
                self.finish()
                return
            }
            if let data, !data.isEmpty {
                self.buffer.append(data)
            }
            self.processBuffer()
            if self.closed { return }
            if isComplete {
                self.finish()
                return
            }
            self.receive()
        }
    }

    private func processBuffer() {
        switch phase {
        case .handshake:
            guard let terminator = buffer.range(of: HTTPRequestParser.headerTerminator) else {
                if buffer.count > 16 * 1024 {
                    log("WebSocket handshake too large; closing")
                    finish()
                }
                return
            }
            let headerData = buffer.subdata(in: 0..<terminator.upperBound)
            buffer.removeSubrange(0..<terminator.upperBound)
            completeHandshake(headerData)
        case .frames:
            while let frame = WebSocketFraming.decode(from: &buffer) {
                handleFrame(frame)
                if closed { return }
            }
            if buffer.count > 1_000_000 {
                log("WebSocket buffer overflow; closing")
                finish()
            }
        }
    }

    private func completeHandshake(_ headerData: Data) {
        guard let request = HTTPRequestParser.parse(headerData: headerData) else {
            log("WebSocket handshake parse failed")
            sendHTTP(status: 400, reason: "Bad Request", body: Data("bad request\n".utf8), contentType: "text/plain")
            return
        }

        log("\(request.method) \(request.path) (WebSocket handshake)")
        guard request.method == "GET", request.path == WebSocketServer.path else {
            log("WebSocket rejected path=\(request.path); expected \(WebSocketServer.path)")
            sendHTTP(status: 404, reason: "Not Found", body: Data("not found\n".utf8), contentType: "text/plain")
            return
        }
        guard request.isWebSocketUpgrade, let key = request.webSocketKey, !key.isEmpty else {
            log("WebSocket upgrade headers missing; closing")
            sendHTTP(status: 400, reason: "Bad Request", body: Data("expected websocket upgrade\n".utf8), contentType: "text/plain")
            return
        }

        let accept = WebSocketFraming.acceptKey(for: key)
        let response = """
        HTTP/1.1 101 Switching Protocols\r
        Upgrade: websocket\r
        Connection: Upgrade\r
        Sec-WebSocket-Accept: \(accept)\r
        \r

        """
        connection.send(content: Data(response.utf8), completion: .contentProcessed { [weak self] error in
            guard let self else { return }
            if let error {
                self.log("WebSocket handshake send error=\(error.localizedDescription)")
                self.finish()
                return
            }
            self.phase = .frames
            self.noteActivity("GET /present", request: request)
            self.log("WebSocket client connected")
            if let ua = request.userAgent {
                self.log("User-Agent: \(ua)")
            }
            print("[HomeAgentRelay][WebSocket] client connected \(self.peer().display)")
            self.processBuffer()
        })
    }

    private func handleFrame(_ frame: WebSocketFraming.Frame) {
        switch frame.opcode {
        case .text:
            let text = String(data: frame.payload, encoding: .utf8) ?? ""
            log("Message received")
            print("[HomeAgentRelay][WebSocket] Message received: \(text)")
            noteActivity("message")
            onTextMessage(text)
            let presentId = WebSocketFraming.presentId(from: text) ?? ""
            let ack = "{\"event\":\"ack\",\"presentId\":\"\(Self.escapeJSON(presentId))\"}"
            sendFrame(opcode: .text, payload: Data(ack.utf8))
            log("ACK sent")
            print("[HomeAgentRelay][WebSocket] ACK sent presentId=\(presentId)")
        case .binary:
            log("WebSocket binary frame ignored (\(frame.payload.count) bytes)")
        case .ping:
            sendFrame(opcode: .pong, payload: frame.payload)
        case .pong:
            break
        case .close:
            log("WebSocket close frame received")
            sendFrame(opcode: .close, payload: Data())
            finish()
        case .continuation:
            log("WebSocket continuation/fragmented frames not supported in v1")
        }
        if !frame.fin && frame.opcode == .text {
            log("WebSocket fragmented text not supported in v1")
        }
    }

    private func sendFrame(opcode: WebSocketFraming.Opcode, payload: Data) {
        let data = WebSocketFraming.encode(opcode: opcode, payload: payload)
        connection.send(content: data, completion: .contentProcessed { [weak self] error in
            if let error {
                self?.log("WebSocket send error=\(error.localizedDescription)")
                self?.finish()
            }
        })
    }

    private func sendHTTP(status: Int, reason: String, body: Data, contentType: String) {
        var header = "HTTP/1.1 \(status) \(reason)\r\n"
        header += "Content-Type: \(contentType)\r\n"
        header += "Content-Length: \(body.count)\r\n"
        header += "Connection: close\r\n\r\n"
        var payload = Data(header.utf8)
        payload.append(body)
        connection.send(content: payload, contentContext: .defaultMessage, isComplete: true, completion: .contentProcessed { [weak self] _ in
            self?.finish()
        })
    }

    private func finish() {
        guard !closed else { return }
        closed = true
        if announced {
            onPeer(.closed(id: id))
        }
        connection.cancel()
        onClose(self)
    }

    private static func escapeJSON(_ value: String) -> String {
        value
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
            .replacingOccurrences(of: "\n", with: "\\n")
    }
}

enum WebSocketFraming {
    static let magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    enum Opcode: UInt8 {
        case continuation = 0x0
        case text = 0x1
        case binary = 0x2
        case close = 0x8
        case ping = 0x9
        case pong = 0xA
    }

    struct Frame {
        let fin: Bool
        let opcode: Opcode
        let payload: Data
    }

    static func acceptKey(for clientKey: String) -> String {
        let combined = clientKey + magic
        let digest = Insecure.SHA1.hash(data: Data(combined.utf8))
        return Data(digest).base64EncodedString()
    }

    static func presentId(from text: String) -> String? {
        guard let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        if let present = object["present"] as? [String: Any], let id = present["id"] as? String {
            return id
        }
        if let id = object["presentId"] as? String {
            return id
        }
        return nil
    }

    static func decode(from buffer: inout Data) -> Frame? {
        guard buffer.count >= 2 else { return nil }
        let b0 = buffer[buffer.startIndex]
        let b1 = buffer[buffer.startIndex + 1]
        let fin = (b0 & 0x80) != 0
        let opcodeRaw = b0 & 0x0F
        let opcode = Opcode(rawValue: opcodeRaw) ?? .close
        let masked = (b1 & 0x80) != 0
        var payloadLength = Int(b1 & 0x7F)
        var offset = 2

        if payloadLength == 126 {
            guard buffer.count >= 4 else { return nil }
            payloadLength = Int(buffer[buffer.startIndex + 2]) << 8 | Int(buffer[buffer.startIndex + 3])
            offset = 4
        } else if payloadLength == 127 {
            guard buffer.count >= 10 else { return nil }
            var length: UInt64 = 0
            for i in 0..<8 {
                length = (length << 8) | UInt64(buffer[buffer.startIndex + 2 + i])
            }
            if length > UInt64(Int.max) { return nil }
            payloadLength = Int(length)
            offset = 10
        }

        var maskKey = [UInt8](repeating: 0, count: 4)
        if masked {
            guard buffer.count >= offset + 4 else { return nil }
            for i in 0..<4 {
                maskKey[i] = buffer[buffer.startIndex + offset + i]
            }
            offset += 4
        }

        guard buffer.count >= offset + payloadLength else { return nil }
        var payload = Data(buffer[(buffer.startIndex + offset)..<(buffer.startIndex + offset + payloadLength)])
        if masked {
            for i in 0..<payload.count {
                payload[i] ^= maskKey[i % 4]
            }
        }
        buffer.removeSubrange(buffer.startIndex..<(buffer.startIndex + offset + payloadLength))
        return Frame(fin: fin, opcode: opcode, payload: payload)
    }

    static func encode(opcode: Opcode, payload: Data) -> Data {
        var data = Data()
        data.append(0x80 | opcode.rawValue)
        let length = payload.count
        if length < 126 {
            data.append(UInt8(length))
        } else if length <= 65_535 {
            data.append(126)
            data.append(UInt8((length >> 8) & 0xFF))
            data.append(UInt8(length & 0xFF))
        } else {
            data.append(127)
            var big = UInt64(length).bigEndian
            withUnsafeBytes(of: &big) { data.append(contentsOf: $0) }
        }
        data.append(payload)
        return data
    }
}
