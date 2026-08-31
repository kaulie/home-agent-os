import Foundation

/// mDNS resolver for Home Agent well-known LAN services.
///
/// Well-known types (labels <= 15 bytes, RFC 6763 §7.1):
///   _ha-brain._tcp         Brain (server/home_brain.py)        :9527
///   _ha-gateway._tcp       Mac Edge gateway (voice/video rx)   TXT ports
///   _ha-img-server._tcp    img-server (img-server/serve.py)    :8080
///
/// Uses `NetServiceBrowser` (Foundation Bonjour) so it works on iOS 12+.
/// Usage:
///   MdnsDiscovery.resolve(MdnsDiscovery.brainType) { brain in
///       let url = brain?.baseURL   // http://<host>:9527
///   }
enum MdnsDiscovery {
    static let brainType = "_ha-brain._tcp"
    static let gatewayType = "_ha-gateway._tcp"
    static let imgServerType = "_ha-img-server._tcp"

    /// A discovered service endpoint (`host` is a Bonjour-resolvable hostname).
    struct Endpoint {
        let host: String
        let port: Int
        let txt: [String: String]

        var baseURL: String { "http://\(host):\(port)" }
    }

    /// Resolve the first service of `type`; completion fires on the main queue.
    static func resolve(_ type: String, timeout: TimeInterval = 2.5, completion: @escaping (Endpoint?) -> Void) {
        let resolver = Resolver(type: type, timeout: timeout, completion: completion)
        resolver.start()
    }

    /// Resolve the first service of `type` (async, iOS 13+).
    @available(iOS 13.0, *)
    static func resolve(_ type: String, timeout: TimeInterval = 2.5) async -> Endpoint? {
        await withCheckedContinuation { continuation in
            resolve(type, timeout: timeout) { continuation.resume(returning: $0) }
        }
    }

    // MARK: - NetService implementation

    private final class Resolver: NSObject, NetServiceBrowserDelegate, NetServiceDelegate {
        private let type: String
        private let timeout: TimeInterval
        private let completion: (Endpoint?) -> Void
        private let browser = NetServiceBrowser()
        private var service: NetService?
        private var finished = false

        init(type: String, timeout: TimeInterval, completion: @escaping (Endpoint?) -> Void) {
            self.type = type
            self.timeout = timeout
            self.completion = completion
            super.init()
        }

        func start() {
            browser.delegate = self
            browser.searchForServices(ofType: type, inDomain: "local.")
            DispatchQueue.main.asyncAfter(deadline: .now() + timeout) { [weak self] in
                self?.finish(nil)
            }
        }

        // MARK: NetServiceBrowserDelegate

        func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
            guard !finished else { return }
            self.service = service
            service.delegate = self
            service.resolve(withTimeout: timeout)
        }

        func netServiceBrowser(_ browser: NetServiceBrowser, didNotSearch errorDict: [String: NSNumber]) {
            finish(nil)
        }

        // MARK: NetServiceDelegate

        func netServiceDidResolveAddress(_ sender: NetService) {
            guard let host = sender.hostName else {
                finish(nil)
                return
            }
            var txt: [String: String] = [:]
            if let data = sender.txtRecordData() {
                let raw = NetService.dictionary(fromTXTRecord: data)
                txt = raw.compactMapValues { String(data: $0, encoding: .utf8) }
            }
            finish(Endpoint(host: host, port: sender.port, txt: txt))
        }

        func netService(_ sender: NetService, didNotResolve errorDict: [String: NSNumber]) {
            finish(nil)
        }

        // MARK: teardown

        private func finish(_ endpoint: Endpoint?) {
            guard !finished else { return }
            finished = true
            browser.stop()
            service?.stop()
            DispatchQueue.main.async {
                self.completion(endpoint)
            }
        }
    }
}
