import Foundation
import Network

/// TCP HTTP/1.1 server using NWListener on 0.0.0.0 (all interfaces, including Personal Hotspot).
final class HTTPServer {
    static let port: UInt16 = 8080

    private let queue: DispatchQueue
    private let log: (String) -> Void
    private let onState: (String, String?) -> Void
    private let onPeer: (RelayPeerEvent) -> Void

    private var listener: NWListener?
    private var connections: [ObjectIdentifier: HTTPConnection] = [:]

    private(set) var listenerState: String = "idle"
    private(set) var lastError: String?

    init(queue: DispatchQueue, log: @escaping (String) -> Void, onState: @escaping (String, String?) -> Void, onPeer: @escaping (RelayPeerEvent) -> Void) {
        self.queue = queue
        self.log = log
        self.onState = onState
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
            log("HTTP server already starting/running (state=\(listenerState))")
            dumpDiagnosticsLocked()
            return
        }

        lastError = nil
        do {
            let next = try Self.makeListener(port: Self.port, log: log)
            listener = next
            attach(next)
            next.start(queue: queue)
            log("HTTP server started; waiting for NWListener state=ready")
        } catch {
            let message = "HTTP NWListener init failed: \(error.localizedDescription) (\(error))"
            lastError = message
            listenerState = "failed"
            log(message)
            onState(listenerState, lastError)
        }
    }

    private func stopLocked(reason: String) {
        log("HTTP server stopping (\(reason))")
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
        log("HTTP server stopped")
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
            log("HTTP listener state=setup listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText)")
        case .waiting(let error):
            listenerState = "waiting"
            lastError = Self.describe(error)
            log("HTTP listener state=waiting listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText) error=\(Self.describe(error))")
            dumpDiagnosticsLocked()
        case .ready:
            listenerState = "ready"
            lastError = nil
            log("HTTP listener state=ready listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText)")
            dumpDiagnosticsLocked()
        case .failed(let error):
            listenerState = "failed"
            lastError = Self.describe(error)
            log("HTTP listener state=failed listeningAddress=0.0.0.0:\(Self.port) NWListener.port=\(portText) error=\(Self.describe(error))")
            dumpDiagnosticsLocked()
            stopLocked(reason: "listener failed")
            return
        case .cancelled:
            listenerState = "cancelled"
            log("HTTP listener state=cancelled")
        @unknown default:
            listenerState = String(describing: state)
            log("HTTP listener state=\(listenerState)")
        }
        onState(listenerState, lastError)
    }

    private func accept(_ connection: NWConnection) {
        let endpoint = String(describing: connection.endpoint)
        log("HTTP connection attempt endpoint=\(endpoint) state=\(String(describing: connection.state))")
        let session = HTTPConnection(
            connection: connection,
            queue: queue,
            log: log,
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
        log("HTTP diagnostics listenerState=\(listenerState) listeningAddress=0.0.0.0:\(Self.port) lastError=\(lastError ?? "none")")
        log("HTTP diagnostics IPv4: \(addressText.isEmpty ? "(none)" : addressText)")
        log("HTTP diagnostics \(NetworkAddressProvider.hotspotHint(from: addresses))")
        log("HTTP diagnostics activeConnections=\(connections.count)")
    }

    static func makeListener(port: UInt16, log: (String) -> Void) throws -> NWListener {
        do {
            let params = tcpParameters(port: port, bindExplicitAny: true)
            let listener = try NWListener(using: params)
            log("NWListener created requiredLocalEndpoint=0.0.0.0:\(port)")
            return listener
        } catch {
            log("requiredLocalEndpoint 0.0.0.0:\(port) failed: \(error.localizedDescription); falling back to NWListener(using:on: \(port))")
            let params = tcpParameters(port: port, bindExplicitAny: false)
            return try NWListener(using: params, on: NWEndpoint.Port(rawValue: port)!)
        }
    }

    static func tcpParameters(port: UInt16, bindExplicitAny: Bool) -> NWParameters {
        let tcp = NWProtocolTCP.Options()
        tcp.enableKeepalive = true
        tcp.noDelay = true
        let params = NWParameters(tls: nil, tcp: tcp)
        params.acceptLocalOnly = false
        params.allowLocalEndpointReuse = true
        params.includePeerToPeer = true
        if bindExplicitAny {
            params.requiredLocalEndpoint = NWEndpoint.hostPort(
                host: NWEndpoint.Host("0.0.0.0"),
                port: NWEndpoint.Port(rawValue: port)!
            )
        }
        return params
    }

    static func describe(_ error: NWError) -> String {
        let extra: String
        switch error {
        case .posix(let code):
            extra = "posix code=\(code.rawValue) \(code)"
        case .dns(let code):
            extra = "dns code=\(code)"
        case .tls(let code):
            extra = "tls code=\(code)"
        default:
            extra = String(describing: error)
        }
        return "\(extra) description=\(error.localizedDescription)"
    }
}

private final class HTTPConnection {
    let connection: NWConnection
    private let id = UUID()
    private let queue: DispatchQueue
    private let log: (String) -> Void
    private let onPeer: (RelayPeerEvent) -> Void
    private let onClose: (HTTPConnection) -> Void
    private var buffer = Data()
    private var closed = false
    private var announced = false

    init(
        connection: NWConnection,
        queue: DispatchQueue,
        log: @escaping (String) -> Void,
        onPeer: @escaping (RelayPeerEvent) -> Void,
        onClose: @escaping (HTTPConnection) -> Void
    ) {
        self.connection = connection
        self.queue = queue
        self.log = log
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
            log("HTTP connection state=setup remote=\(remote)")
        case .waiting(let error):
            log("HTTP connection state=waiting remote=\(remote) error=\(HTTPServer.describe(error))")
        case .preparing:
            log("HTTP connection state=preparing remote=\(remote)")
        case .ready:
            announcePeer()
            log("Connection from \(peer().display)")
        case .failed(let error):
            log("HTTP connection state=failed remote=\(remote) error=\(HTTPServer.describe(error))")
            finish()
        case .cancelled:
            finish()
        @unknown default:
            log("HTTP connection state=\(state) remote=\(remote)")
        }
    }

    private func peer() -> RemotePeer {
        NetworkAddressProvider.remotePeer(from: connection)
    }

    private func announcePeer() {
        let remote = peer()
        if announced {
            return
        }
        announced = true
        onPeer(.opened(id: id, ip: remote.ip, port: remote.port, kind: "HTTP"))
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
                self.log("HTTP receive error=\(error.localizedDescription) (\(error))")
                self.finish()
                return
            }
            if let data, !data.isEmpty {
                self.buffer.append(data)
            }
            if let terminator = self.buffer.range(of: HTTPRequestParser.headerTerminator) {
                let headerData = self.buffer.subdata(in: 0..<terminator.upperBound)
                self.handleRequest(headerData)
                return
            }
            if self.buffer.count > 64 * 1024 {
                self.log("HTTP request head too large; closing")
                self.finish()
                return
            }
            if isComplete {
                if !self.buffer.isEmpty {
                    self.log("HTTP connection complete before full request head")
                }
                self.finish()
                return
            }
            self.receive()
        }
    }

    private func handleRequest(_ headerData: Data) {
        guard let request = HTTPRequestParser.parse(headerData: headerData) else {
            log("HTTP parse failed; sending 400")
            send(status: 400, reason: "Bad Request", contentType: "text/plain; charset=utf-8", body: Data("bad request\n".utf8))
            return
        }

        log("\(request.method) \(request.path)")
        if let ua = request.userAgent {
            log("User-Agent: \(ua)")
        }
        print("[HomeAgentRelay][HTTP] \(request.method) \(request.path) from \(peer().display)")
        if let ua = request.userAgent {
            print("[HomeAgentRelay][HTTP] User-Agent: \(ua)")
        }
        noteActivity("\(request.method) \(request.path)", request: request)

        guard request.method == "GET" || request.method == "HEAD" else {
            send(status: 405, reason: "Method Not Allowed", contentType: "text/plain; charset=utf-8", body: Data("method not allowed\n".utf8))
            return
        }

        let includeBody = request.method == "GET"
        switch request.path {
        case "/", "":
            send(status: 200, reason: "OK", contentType: "text/html; charset=utf-8", body: Self.statusHTML, includeBody: includeBody)
        case "/receiver":
            send(status: 200, reason: "OK", contentType: "text/html; charset=utf-8", body: Self.receiverHTML, includeBody: includeBody)
        case "/health":
            send(status: 200, reason: "OK", contentType: "application/json", body: Self.healthJSON, includeBody: includeBody)
        default:
            send(status: 404, reason: "Not Found", contentType: "text/plain; charset=utf-8", body: Data("not found\n".utf8), includeBody: includeBody)
        }
    }

    private func send(status: Int, reason: String, contentType: String, body: Data, includeBody: Bool = true) {
        var header = "HTTP/1.1 \(status) \(reason)\r\n"
        header += "Content-Type: \(contentType)\r\n"
        header += "Content-Length: \(body.count)\r\n"
        header += "Connection: close\r\n"
        header += "Cache-Control: no-store\r\n"
        header += "\r\n"
        var payload = Data(header.utf8)
        if includeBody {
            payload.append(body)
        }
        connection.send(content: payload, contentContext: .defaultMessage, isComplete: true, completion: .contentProcessed { [weak self] error in
            if let error {
                self?.log("HTTP send error=\(error.localizedDescription) (\(error))")
            } else {
                self?.log("HTTP response sent")
            }
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

    private static let receiverHTML = Data("""
    <html>
    <body style="background:black;color:white;font-size:60px;text-align:center">
    Hello Tesla
    </body>
    </html>
    """.utf8)

    private static let statusHTML = Data("""
    <html>
    <body style="background:black;color:white;font-family:sans-serif">
    <h1>HomeAgentRelay</h1>
    <p>HTTP Server: Running</p>
    <p>Port: 8080</p>
    </body>
    </html>
    """.utf8)

    private static let healthJSON = Data("""
    {
      "status": "ok"
    }
    """.utf8)
}
