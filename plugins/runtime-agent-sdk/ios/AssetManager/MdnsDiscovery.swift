import Darwin
import Foundation

/// mDNS resolver for Home Agent well-known LAN services.
///
/// Well-known types (labels <= 15 bytes, RFC 6763 §7.1):
///   _ha-brain._tcp         Brain (server/home_brain.py)        :9527
///   _ha-gateway._tcp       Mac Edge gateway (voice/video rx)   TXT ports
///   _ha-img-server._tcp    img-server (img-server/serve.py)    :8080
///
/// NetServiceBrowser runs on a dedicated RunLoop thread so Bonjour browse/resolve
/// never blocks the main thread.
/// HTTP/TCP **must** use resolved IPv4 (`host`), not `.local` hostnames.
enum MdnsDiscovery {
    static let brainType = "_ha-brain._tcp"
    static let gatewayType = "_ha-gateway._tcp"
    static let imgServerType = "_ha-img-server._tcp"

    static let brainMdnsHost = "brain.local"
    static let gatewayMdnsHost = "gateway.local"
    static let imgServerMdnsHost = "img-server.local"

    /// A discovered service endpoint. `host` is IPv4 for connecting; `mdnsHost` is the well-known name for UI.
    struct Endpoint {
        let host: String
        let port: Int
        let mdnsHost: String
        let txt: [String: String]
        let serviceName: String
        let bonjourHostName: String

        var baseURL: String { "http://\(host):\(port)" }
        var mdnsBaseURL: String { "http://\(mdnsHost):\(port)" }

        var voiceIngestPort: UInt16 {
            if let raw = txt["voice_port"], let parsed = UInt16(raw), parsed > 0 {
                return parsed
            }
            return 8792
        }
    }

    /// Browse all matching services, resolve each, pick the best (Brain: ping-verified).
    /// Completion fires on the main queue.
    static func resolve(_ type: String, timeout: TimeInterval = 2.0, completion: @escaping (Endpoint?) -> Void) {
        BonjourRunLoop.async {
            let resolver = MultiResolver(type: type, timeout: timeout, completion: completion)
            resolver.start()
        }
    }

    /// Resolve the best service of `type` (async, iOS 13+).
    @available(iOS 13.0, *)
    static func resolve(_ type: String, timeout: TimeInterval = 2.0) async -> Endpoint? {
        await withCheckedContinuation { continuation in
            resolve(type, timeout: timeout) { continuation.resume(returning: $0) }
        }
    }

    static func wellKnownHost(for type: String) -> String {
        switch type {
        case brainType: return brainMdnsHost
        case gatewayType: return gatewayMdnsHost
        case imgServerType: return imgServerMdnsHost
        default: return "local"
        }
    }

    static func firstIPv4(from addresses: [Data]?) -> String? {
        guard let addresses else { return nil }
        for address in addresses {
            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let ok = address.withUnsafeBytes { raw -> Bool in
                guard let ptr = raw.baseAddress?.assumingMemoryBound(to: sockaddr.self) else {
                    return false
                }
                guard ptr.pointee.sa_family == sa_family_t(AF_INET) else { return false }
                return getnameinfo(
                    ptr,
                    socklen_t(address.count),
                    &hostname,
                    socklen_t(hostname.count),
                    nil,
                    0,
                    NI_NUMERICHOST
                ) == 0
            }
            if ok {
                let ip = String(cString: hostname)
                if !ip.isEmpty, ip != "0.0.0.0" { return ip }
            }
        }
        return nil
    }

    // MARK: - pick best among multiple Bonjour advertisements

    static func pickBestGateway(from endpoints: [Endpoint]) -> Endpoint? {
        guard !endpoints.isEmpty else { return nil }
        return endpoints.sorted { scoreGateway($0) > scoreGateway($1) }.first
    }

    private static func scoreGateway(_ ep: Endpoint) -> Int {
        var score = 0
        let host = ep.bonjourHostName.lowercased()
        let name = ep.serviceName.lowercased()
        if host.contains("gateway.local") { score += 100 }
        if name.contains("gateway") { score += 50 }
        if ep.port == 8790 { score += 10 }
        return score
    }

    @available(iOS 13.0, *)
    static func pickVerifiedBrain(from endpoints: [Endpoint]) async -> Endpoint? {
        guard !endpoints.isEmpty else { return nil }
        let ranked = endpoints.sorted { scoreBrain($0) > scoreBrain($1) }
        for ep in ranked {
            if await probeBrain(host: ep.host, port: ep.port) {
                return ep
            }
        }
        return ranked.first
    }

    private static func scoreBrain(_ ep: Endpoint) -> Int {
        var score = 0
        let host = ep.bonjourHostName.lowercased()
        let name = ep.serviceName.lowercased()
        if host.contains("brain.local") { score += 100 }
        if name.contains("home agent brain") || name.contains("brain") { score += 50 }
        if ep.port == 9527 { score += 10 }
        return score
    }

    @available(iOS 13.0, *)
    static func probeBrain(host: String, port: Int, timeout: TimeInterval = 1.5) async -> Bool {
        let ms = Int64(Date().timeIntervalSince1970 * 1000)
        guard let url = URL(string: "http://\(host):\(port)/api/v1/ping?client_time_ms=\(ms)") else {
            return false
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200 ..< 300).contains(http.statusCode) else {
                return false
            }
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return false
            }
            if json["app"] as? String == "brain" { return true }
            return json["ok"] as? Bool == true && json["server_time_ms"] != nil
        } catch {
            return false
        }
    }

    // MARK: - retain in-flight resolvers

    private static let lock = NSLock()
    private static var inflight: [ObjectIdentifier: AnyObject] = [:]

    fileprivate static func retain(_ resolver: AnyObject) {
        lock.lock()
        inflight[ObjectIdentifier(resolver)] = resolver
        lock.unlock()
    }

    fileprivate static func release(_ resolver: AnyObject) {
        lock.lock()
        inflight.removeValue(forKey: ObjectIdentifier(resolver))
        lock.unlock()
    }

    // MARK: - dedicated Bonjour RunLoop

    private enum BonjourRunLoop {
        private static let thread = BonjourThread()
        private static let startLock = NSLock()
        private static var started = false

        static func async(_ block: @escaping () -> Void) {
            startLock.lock()
            if !started {
                thread.start()
                thread.ready.wait()
                started = true
            }
            startLock.unlock()
            thread.perform(#selector(BonjourThread.runBox(_:)), on: thread, with: BlockBox(block), waitUntilDone: false)
        }
    }

    private final class BlockBox: NSObject {
        let block: () -> Void
        init(_ block: @escaping () -> Void) { self.block = block }
    }

    private final class BonjourThread: Thread {
        let ready = DispatchSemaphore(value: 0)

        override func main() {
            ready.signal()
            RunLoop.current.run()
        }

        @objc func runBox(_ box: BlockBox) {
            box.block()
        }
    }

    // MARK: - browse all → resolve all → pick best

    fileprivate final class MultiResolver: NSObject, NetServiceBrowserDelegate {
        private let type: String
        private let timeout: TimeInterval
        private let completion: (Endpoint?) -> Void
        private let browser = NetServiceBrowser()
        private var candidates: [NetService] = []
        private var finished = false
        private var timeoutTimer: Timer?
        private var resolveStarted = false

        init(type: String, timeout: TimeInterval, completion: @escaping (Endpoint?) -> Void) {
            self.type = type
            self.timeout = timeout
            self.completion = completion
            super.init()
        }

        func start() {
            MdnsDiscovery.retain(self)
            browser.delegate = self
            browser.searchForServices(ofType: type, inDomain: "local.")
            timeoutTimer = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
                self?.beginResolveAll()
            }
        }

        func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
            guard !finished else { return }
            candidates.append(service)
        }

        func netServiceBrowser(_ browser: NetServiceBrowser, didNotSearch errorDict: [String: NSNumber]) {
            beginResolveAll()
        }

        private func beginResolveAll() {
            guard !finished, !resolveStarted else { return }
            resolveStarted = true
            timeoutTimer?.invalidate()
            timeoutTimer = nil
            browser.stop()

            if candidates.isEmpty {
                finish(nil)
                return
            }

            var endpoints: [Endpoint] = []
            let group = DispatchGroup()
            let lock = NSLock()

            for service in candidates {
                group.enter()
                let one = SingleServiceResolver(type: type) { ep in
                    lock.lock()
                    if let ep { endpoints.append(ep) }
                    lock.unlock()
                    group.leave()
                }
                MdnsDiscovery.retain(one)
                one.resolve(service)
            }

            group.notify(queue: .global(qos: .userInitiated)) { [weak self] in
                guard let self else { return }
                self.pickAndFinish(endpoints)
            }
        }

        private func pickAndFinish(_ endpoints: [Endpoint]) {
            if #available(iOS 13.0, *) {
                if type == MdnsDiscovery.brainType {
                    Task {
                        let best = await MdnsDiscovery.pickVerifiedBrain(from: endpoints)
                        self.finish(best)
                    }
                    return
                }
            }
            let best: Endpoint?
            switch type {
            case MdnsDiscovery.gatewayType:
                best = MdnsDiscovery.pickBestGateway(from: endpoints)
            default:
                best = endpoints.first
            }
            finish(best)
        }

        private func finish(_ endpoint: Endpoint?) {
            guard !finished else { return }
            finished = true
            let done = completion
            MdnsDiscovery.release(self)
            DispatchQueue.main.async {
                done(endpoint)
            }
        }
    }

    fileprivate final class SingleServiceResolver: NSObject, NetServiceDelegate {
        private let type: String
        private let completion: (Endpoint?) -> Void
        private var service: NetService?
        private var finished = false

        init(type: String, completion: @escaping (Endpoint?) -> Void) {
            self.type = type
            self.completion = completion
            super.init()
        }

        func resolve(_ found: NetService) {
            let copy = NetService(domain: found.domain, type: found.type, name: found.name, port: Int32(found.port))
            service = copy
            copy.delegate = self
            copy.resolve(withTimeout: 2.0)
        }

        func netServiceDidResolveAddress(_ sender: NetService) {
            guard let ipv4 = MdnsDiscovery.firstIPv4(from: sender.addresses) else {
                finish(nil)
                return
            }
            var txt: [String: String] = [:]
            if let data = sender.txtRecordData() {
                let raw = NetService.dictionary(fromTXTRecord: data)
                txt = raw.compactMapValues { String(data: $0, encoding: .utf8) }
            }
            let hostName = (sender.hostName ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            finish(Endpoint(
                host: ipv4,
                port: sender.port,
                mdnsHost: MdnsDiscovery.wellKnownHost(for: type),
                txt: txt,
                serviceName: sender.name,
                bonjourHostName: hostName
            ))
        }

        func netService(_ sender: NetService, didNotResolve errorDict: [String: NSNumber]) {
            finish(nil)
        }

        private func finish(_ endpoint: Endpoint?) {
            guard !finished else { return }
            finished = true
            service?.stop()
            completion(endpoint)
            MdnsDiscovery.release(self)
        }
    }
}
