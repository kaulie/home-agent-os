import Combine
import Foundation
import Network

final class RelayServer: ObservableObject {
    static let shared = RelayServer()

    static let httpPort = HTTPServer.port
    static let webSocketPort = WebSocketServer.port

    @Published private(set) var httpStatus: String = "Stopped"
    @Published private(set) var webSocketStatus: String = "Stopped"
    @Published private(set) var httpListenerState: String = "idle"
    @Published private(set) var webSocketListenerState: String = "idle"
    @Published private(set) var httpLastError: String?
    @Published private(set) var webSocketLastError: String?
    @Published private(set) var addresses: [IPv4InterfaceAddress] = []
    @Published private(set) var hotspotHint: String = ""
    @Published private(set) var lastWebSocketMessage: String = ""
    @Published private(set) var logs: [RelayLogEntry] = []
    @Published private(set) var peerConnections: [RelayPeerConnection] = []
    /// Start/Stop 互斥：点 Start 后立刻为 true，点 Stop 后立刻为 false。
    @Published private(set) var isServerActive = false

    var peerGroups: [RelayPeerGroup] {
        let grouped = Dictionary(grouping: peerConnections, by: \.ip)
        return grouped.keys.sorted { left, right in
            let leftSeen = grouped[left]?.map(\.lastActivityAt).max() ?? .distantPast
            let rightSeen = grouped[right]?.map(\.lastActivityAt).max() ?? .distantPast
            return leftSeen > rightSeen
        }.map { ip in
            let connections = (grouped[ip] ?? []).sorted { $0.lastActivityAt > $1.lastActivityAt }
            return RelayPeerGroup(ip: ip, connections: connections)
        }
    }

    var httpRunning: Bool { httpStatus == "Running" }
    var webSocketRunning: Bool { webSocketStatus == "Running" }

    var teslaURLs: [String] {
        addresses.map { "http://\($0.address):\(Self.httpPort)/receiver" }
    }

    var webSocketURLs: [String] {
        addresses.map { "ws://\($0.address):\(Self.webSocketPort)/present" }
    }

    private let queue = DispatchQueue(label: "com.gaolei.homeagent.relay.server")
    private var httpServer: HTTPServer!
    private var webSocketServer: WebSocketServer!
    private var addressTimer: Timer?

    private init() {
        httpServer = HTTPServer(
            queue: queue,
            log: { [weak self] message in self?.appendLog(message) },
            onState: { [weak self] state, error in
                self?.publishHTTP(state: state, error: error)
            },
            onPeer: { [weak self] event in
                self?.handlePeer(event)
            }
        )
        webSocketServer = WebSocketServer(
            queue: queue,
            log: { [weak self] message in self?.appendLog(message) },
            onState: { [weak self] state, error in
                self?.publishWebSocket(state: state, error: error)
            },
            onTextMessage: { [weak self] text in
                DispatchQueue.main.async {
                    self?.lastWebSocketMessage = text
                }
            },
            onPeer: { [weak self] event in
                self?.handlePeer(event)
            }
        )
        refreshAddresses()
    }

    func start() {
        setActive(true)
        DispatchQueue.main.async { [weak self] in
            self?.peerConnections = []
        }
        appendLog("Start Server")
        refreshAddresses()
        dumpDiagnostics()
        httpServer.start()
        webSocketServer.start()
        startAddressRefresh()
    }

    func stop() {
        setActive(false)
        appendLog("Stop Server")
        httpServer.stop()
        webSocketServer.stop()
        DispatchQueue.main.async { [weak self] in
            self?.httpStatus = "Stopped"
            self?.webSocketStatus = "Stopped"
        }
    }

    private func setActive(_ active: Bool) {
        if Thread.isMainThread {
            isServerActive = active
        } else {
            DispatchQueue.main.async { [weak self] in
                self?.isServerActive = active
            }
        }
    }

    func dumpDiagnostics() {
        let snapshot = NetworkAddressProvider.ipv4Addresses()
        let addressText = snapshot.map { "\($0.interface)=\($0.address)" }.joined(separator: ", ")
        appendLog("Diagnostics IPv4: \(addressText.isEmpty ? "(none)" : addressText)")
        appendLog("Diagnostics \(NetworkAddressProvider.hotspotHint(from: snapshot))")
        appendLog("Diagnostics HTTP listenerState=\(httpListenerState) listeningAddress=0.0.0.0:\(Self.httpPort) error=\(httpLastError ?? "none")")
        appendLog("Diagnostics WebSocket listenerState=\(webSocketListenerState) listeningAddress=0.0.0.0:\(Self.webSocketPort) error=\(webSocketLastError ?? "none")")
        httpServer.dumpDiagnostics()
        webSocketServer.dumpDiagnostics()
    }

    private func startAddressRefresh() {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.addressTimer?.invalidate()
            self.addressTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
                self?.refreshAddresses()
            }
            if let timer = self.addressTimer {
                RunLoop.main.add(timer, forMode: .common)
            }
        }
    }

    func refreshAddresses() {
        let snapshot = NetworkAddressProvider.ipv4Addresses()
        let hint = NetworkAddressProvider.hotspotHint(from: snapshot)
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if self.addresses != snapshot {
                self.addresses = snapshot
                let text = snapshot.map { "\($0.interface) \($0.address)" }.joined(separator: ", ")
                self.appendLog("Local IPv4 updated: \(text.isEmpty ? "(none)" : text)")
            }
            self.hotspotHint = hint
        }
    }

    private func publishHTTP(state: String, error: String?) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.httpListenerState = state
            self.httpLastError = error
            self.httpStatus = (state == "ready") ? "Running" : ((state == "stopped" || state == "cancelled" || state == "idle") ? "Stopped" : state.capitalized)
        }
    }

    private func publishWebSocket(state: String, error: String?) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            self.webSocketListenerState = state
            self.webSocketLastError = error
            self.webSocketStatus = (state == "ready") ? "Running" : ((state == "stopped" || state == "cancelled" || state == "idle") ? "Stopped" : state.capitalized)
        }
    }

    private func handlePeer(_ event: RelayPeerEvent) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            switch event {
            case let .opened(id, ip, port, kind):
                if let index = self.peerConnections.firstIndex(where: { $0.id == id }) {
                    self.peerConnections[index].ip = ip
                    self.peerConnections[index].remotePort = port
                    self.peerConnections[index].kind = kind
                    self.peerConnections[index].isActive = true
                    self.peerConnections[index].lastActivityAt = Date()
                } else {
                    self.peerConnections.insert(
                        RelayPeerConnection(
                            id: id,
                            ip: ip,
                            remotePort: port,
                            kind: kind,
                            detail: "connected",
                            isActive: true,
                            connectedAt: Date(),
                            lastActivityAt: Date()
                        ),
                        at: 0
                    )
                    if self.peerConnections.count > RelayLog.maxPeerConnections {
                        self.peerConnections.removeLast(self.peerConnections.count - RelayLog.maxPeerConnections)
                    }
                }
            case let .activity(id, detail, ip, port, headers):
                if let index = self.peerConnections.firstIndex(where: { $0.id == id }) {
                    self.peerConnections[index].detail = detail
                    self.peerConnections[index].lastActivityAt = Date()
                    if ip != "unknown" {
                        self.peerConnections[index].ip = ip
                    }
                    if !port.isEmpty {
                        self.peerConnections[index].remotePort = port
                    }
                    if !headers.isEmpty {
                        self.peerConnections[index].headers = headers
                    }
                }
            case let .closed(id):
                if let index = self.peerConnections.firstIndex(where: { $0.id == id }) {
                    self.peerConnections[index].isActive = false
                    self.peerConnections[index].lastActivityAt = Date()
                }
            }
        }
    }

    private func appendLog(_ message: String) {
        let entry = RelayLogEntry(id: UUID(), date: Date(), message: message)
        print("[HomeAgentRelay] \(entry.line)")
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            var next = self.logs
            next.append(entry)
            if next.count > RelayLog.maxEntries {
                next.removeFirst(next.count - RelayLog.maxEntries)
            }
            self.logs = next
        }
    }
}
