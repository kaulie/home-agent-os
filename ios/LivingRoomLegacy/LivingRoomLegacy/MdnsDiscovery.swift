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
    private static func dlog(_ message: String, category: String) {
        DiscoveryDebugLog.shared.log(message, category: category)
    }

    private static func describeEndpoint(_ ep: Endpoint) -> String {
        let txtSummary = ep.txt.isEmpty
            ? "—"
            : ep.txt.sorted(by: { $0.key < $1.key }).map { "\($0.key)=\($0.value)" }.joined(separator: ", ")
        return "\(ep.serviceName) → \(ep.host):\(ep.port) bonjour=\(ep.bonjourHostName) txt={\(txtSummary)}"
    }

    static func logLaunchNetworkContext() {
        let subnets = LANInterface.scanSubnets()
        if subnets.isEmpty {
            dlog("no RFC1918 Wi‑Fi interface detected", category: "launch")
        } else {
            let desc = subnets.map { "\($0.prefix).x self=.\($0.hostOctet)" }.joined(separator: ", ")
            dlog("Wi‑Fi subnets: \(desc)", category: "launch")
        }
        dlog("local network permission: check Settings → LivingRoomLegacy → Local Network if browse fails", category: "launch")
    }

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
        dlog("browse start type=\(type) timeout=\(timeout)s", category: "mDNS browse")
        BonjourRunLoop.async {
            let resolver = MultiResolver(type: type, timeout: timeout, completion: completion)
            resolver.start()
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

    /// NetServiceBrowser expects `_service._tcp.` (trailing dot).
    static func bonjourBrowseType(_ type: String) -> String {
        if type.hasSuffix(".") { return type }
        return type + "."
    }

    /// Collect all usable RFC1918 IPv4s from getaddrinfo for a hostname.
    static func resolveIPv4Candidates(_ raw: String) -> [String] {
        let host = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
        if host.isEmpty { return [] }
        if let ip = firstIPv4(fromHostString: host) { return [ip] }

        var hints = addrinfo()
        hints.ai_family = Int32(AF_INET)
        hints.ai_socktype = SOCK_STREAM
        var head: UnsafeMutablePointer<addrinfo>?
        guard getaddrinfo(host, nil, &hints, &head) == 0, let head else { return [] }
        defer { freeaddrinfo(head) }

        var result: [String] = []
        var cursor: UnsafeMutablePointer<addrinfo>? = head
        while let node = cursor {
            if node.pointee.ai_family == sa_family_t(AF_INET),
               let addr = node.pointee.ai_addr {
                var name = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                let len = socklen_t(node.pointee.ai_addrlen)
                if getnameinfo(addr, len, &name, socklen_t(name.count), nil, 0, NI_NUMERICHOST) == 0 {
                    let ip = String(cString: name)
                    if isUsableLanIPv4(ip), !result.contains(ip) { result.append(ip) }
                }
            }
            cursor = node.pointee.ai_next
        }
        return result
    }

    /// Resolve `.local` or numeric host to the best IPv4 for HTTP/TCP.
    static func resolveIPv4Host(_ raw: String) -> String? {
        bestUsableIPv4(candidates: resolveIPv4Candidates(raw))
    }

    private static func firstIPv4(fromHostString host: String) -> String? {
        let parts = host.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ UInt8($0) != nil }) else { return nil }
        guard isUsableLanIPv4(host) else { return nil }
        return host
    }

    /// RFC1918 only — rejects link-local (169.254.x.x), loopback, and public IPs.
    static func isUsableLanIPv4(_ ip: String) -> Bool {
        let parts = ip.split(separator: ".")
        guard parts.count == 4,
              let a = UInt8(parts[0]),
              let b = UInt8(parts[1]) else { return false }
        if a == 10 { return true }
        if a == 172, (16 ... 31).contains(b) { return true }
        if a == 192, b == 168 { return true }
        return false
    }

    static func scoreIPv4ForDiscovery(_ ip: String, txtLanIp: String? = nil) -> Int {
        var score = 0
        if isOnPreferredLAN(ip) { score += 200 }
        if let mine = LANInterface.preferredSubnets().first?.hostOctet {
            let parts = ip.split(separator: ".")
            if parts.count == 4, UInt8(parts[3]) == mine { score += 30 }
        }
        if let lanIp = txtLanIp, !lanIp.isEmpty, ip == lanIp { score += 400 }
        return score
    }

    static func bestUsableIPv4(candidates: [String], txtLanIp: String? = nil) -> String? {
        let usable = candidates.filter { isUsableLanIPv4($0) }
        guard !usable.isEmpty else { return nil }
        return usable.max {
            scoreIPv4ForDiscovery($0, txtLanIp: txtLanIp) < scoreIPv4ForDiscovery($1, txtLanIp: txtLanIp)
        }
    }

    /// Collect candidates from TXT, hostname A records, and Bonjour addresses; pick best-scored.
    static func preferredIPv4(txt: [String: String], hostName: String, addresses: [Data]?) -> String? {
        let txtLanIp = txt["lan_ip"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        var candidates: [String] = []
        for key in ["lan_ip", "ipv4", "ip"] {
            if let raw = txt[key]?.trimmingCharacters(in: .whitespacesAndNewlines),
               let ip = firstIPv4(fromHostString: raw) {
                candidates.append(ip)
            }
        }
        let host = hostName.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
        if !host.isEmpty {
            candidates.append(contentsOf: resolveIPv4Candidates(host))
        }
        candidates.append(contentsOf: allIPv4(from: addresses))
        let chosen = bestUsableIPv4(candidates: candidates, txtLanIp: txtLanIp)
        let scored = candidates.filter { isUsableLanIPv4($0) }.map {
            "\($0)(score=\(scoreIPv4ForDiscovery($0, txtLanIp: txtLanIp)))"
        }.joined(separator: ", ")
        dlog(
            "host=\(hostName) txtLanIp=\(txtLanIp ?? "—") candidates=[\(scored)] → \(chosen ?? "nil")",
            category: "preferredIPv4"
        )
        return chosen
    }

    /// Probe order for /24 fallback: iPhone, router (.1), then remaining host octets.
    private static func lanScanHostOctets(for subnet: LANInterface.Subnet) -> [UInt8] {
        var octets: [UInt8] = []
        func add(_ o: UInt8) {
            guard (1 ... 254).contains(o), !octets.contains(o) else { return }
            octets.append(o)
        }
        add(subnet.hostOctet)
        add(1)
        for o in 2 ... 254 { add(UInt8(o)) }
        return octets
    }

    private static func probeServiceBatchSync(
        prefix: String,
        octets: [UInt8],
        port: Int,
        timeout: TimeInterval,
        probe: (_ host: String, _ port: Int, _ timeout: TimeInterval, _ completion: @escaping (Bool) -> Void) -> Void,
        completion: @escaping (String?) -> Void
    ) {
        let group = DispatchGroup()
        let lock = NSLock()
        var found: String?
        for hostOctet in octets {
            group.enter()
            let ip = "\(prefix).\(hostOctet)"
            probe(ip, port, timeout) { ok in
                if ok {
                    lock.lock()
                    if found == nil { found = ip }
                    lock.unlock()
                }
                group.leave()
            }
        }
        group.notify(queue: .global(qos: .utility)) {
            completion(found)
        }
    }

    /// Fallback when Bonjour browse finds nothing (AP isolation / mDNS blocked on Wi‑Fi).
    static func discoverBrainByLANScan(budget: TimeInterval = 5.0, completion: @escaping (Endpoint?) -> Void) {
        let subnets = LANInterface.scanSubnets()
        guard !subnets.isEmpty else {
            dlog("brain: no local subnets", category: "LAN scan")
            DispatchQueue.main.async { completion(nil) }
            return
        }
        dlog("brain scan start budget=\(budget)s subnets=\(subnets.map { "\($0.prefix).x" }.joined(separator: ", "))", category: "LAN scan")
        DispatchQueue.global(qos: .utility).async {
            let deadline = Date().addingTimeInterval(budget)
            let probeTimeout = 0.3
            let batchSize = 8

            func finish(_ ep: Endpoint?) {
                DispatchQueue.main.async { completion(ep) }
            }

            for subnet in subnets {
                if Date() >= deadline { break }
                let octets = lanScanHostOctets(for: subnet)
                var idx = 0
                while idx < octets.count, Date() < deadline {
                    let end = min(idx + batchSize, octets.count)
                    let batch = Array(octets[idx ..< end])
                    idx = end
                    let sem = DispatchSemaphore(value: 0)
                    var foundIP: String?
                    probeServiceBatchSync(
                        prefix: subnet.prefix,
                        octets: batch,
                        port: 9527,
                        timeout: probeTimeout,
                        probe: probeBrain
                    ) { ip in
                        foundIP = ip
                        sem.signal()
                    }
                    _ = sem.wait(timeout: .now() + probeTimeout + 0.5)
                    if let ip = foundIP {
                        dlog("brain HIT \(ip):9527 on \(subnet.prefix).x", category: "LAN scan")
                        finish(Endpoint(
                            host: ip,
                            port: 9527,
                            mdnsHost: brainMdnsHost,
                            txt: ["role": "brain"],
                            serviceName: "LAN scan",
                            bonjourHostName: brainMdnsHost
                        ))
                        return
                    }
                }
            }
            dlog("brain scan finished: no endpoint", category: "LAN scan")
            finish(nil)
        }
    }

    private enum LANInterface {
        struct Subnet {
            let prefix: String
            let hostOctet: UInt8
        }

        static func preferredSubnets() -> [Subnet] {
            var result: [Subnet] = []
            var seen = Set<String>()
            var ifaddrPointer: UnsafeMutablePointer<ifaddrs>?
            guard getifaddrs(&ifaddrPointer) == 0, let first = ifaddrPointer else { return [] }
            defer { freeifaddrs(ifaddrPointer) }

            var cursor: UnsafeMutablePointer<ifaddrs>? = first
            while let current = cursor {
                let iface = current.pointee
                defer { cursor = iface.ifa_next }
                guard let addr = iface.ifa_addr, addr.pointee.sa_family == sa_family_t(AF_INET) else { continue }
                let flags = Int32(iface.ifa_flags)
                guard (flags & IFF_UP) != 0, (flags & IFF_LOOPBACK) == 0 else { continue }
                var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                guard getnameinfo(addr, socklen_t(addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 else {
                    continue
                }
                let ip = String(cString: host)
                guard isUsableLanIPv4(ip) else { continue }
                let parts = ip.split(separator: ".")
                guard parts.count == 4, let last = UInt8(parts[3]), (1 ... 254).contains(last) else { continue }
                let prefix = parts.prefix(3).joined(separator: ".")
                guard seen.insert(prefix).inserted else { continue }
                let name = String(cString: iface.ifa_name)
                if name == "en0" || name.hasPrefix("en") {
                    result.insert(Subnet(prefix: prefix, hostOctet: last), at: 0)
                } else {
                    result.append(Subnet(prefix: prefix, hostOctet: last))
                }
            }
            return result
        }

        static func scanSubnets() -> [Subnet] {
            let live = preferredSubnets()
            if live.isEmpty {
                return [
                    Subnet(prefix: "192.168.3", hostOctet: 1),
                    Subnet(prefix: "192.168.1", hostOctet: 1),
                ]
            }
            // Prefer 192.168 (home Wi‑Fi) over 10.x (USB/VPN) so gateway scan doesn't burn the budget.
            return live.sorted { a, b in
                let aHome = a.prefix.hasPrefix("192.168.")
                let bHome = b.prefix.hasPrefix("192.168.")
                if aHome != bHome { return aHome && !bHome }
                return false
            }
        }
    }

    static func allIPv4(from addresses: [Data]?) -> [String] {
        guard let addresses else { return [] }
        var result: [String] = []
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
                if isUsableLanIPv4(ip), !result.contains(ip) { result.append(ip) }
            }
        }
        return result
    }

    static func firstIPv4(from addresses: [Data]?) -> String? {
        bestUsableIPv4(candidates: allIPv4(from: addresses))
    }

    // MARK: - pick best among multiple Bonjour advertisements

    static func pickBestGateway(from endpoints: [Endpoint]) -> Endpoint? {
        guard !endpoints.isEmpty else { return nil }
        return endpoints.sorted { scoreGateway($0) > scoreGateway($1) }.first
    }

    /// Ping-verified RFC1918 is enough. TXT `lan_ip` is a hint and is often stale after DHCP.
    static func isTrustworthyGateway(_ ep: Endpoint) -> Bool {
        if ep.serviceName == "LAN scan" { return true }
        return isUsableLanIPv4(ep.host)
    }

    private static func scoreGateway(_ ep: Endpoint) -> Int {
        var score = 0
        let host = ep.bonjourHostName.lowercased()
        let name = ep.serviceName.lowercased()
        if host.contains("gateway.local") { score += 100 }
        if name.contains("gateway") { score += 50 }
        if ep.port == 8790 { score += 10 }
        if ep.serviceName == "LAN scan" { score += 500 }
        if isOnPreferredLAN(ep.host) { score += 200 }
        if let lanIp = ep.txt["lan_ip"], ep.host == lanIp { score += 400 }
        if let mine = LANInterface.preferredSubnets().first?.hostOctet {
            let parts = ep.host.split(separator: ".")
            if parts.count == 4, UInt8(parts[3]) == mine { score += 30 }
        }
        return score
    }

    static func pickVerifiedGateway(
        from endpoints: [Endpoint],
        maxProbes: Int = 8,
        probeTimeout: TimeInterval = 1.0,
        completion: @escaping (Endpoint?) -> Void
    ) {
        let ranked = endpoints.filter { isUsableLanIPv4($0.host) && isTrustworthyGateway($0) }
            .sorted { scoreGateway($0) > scoreGateway($1) }
        guard !ranked.isEmpty else {
            dlog("gateway verify: no trustworthy candidates (total=\(endpoints.count))", category: "ping verify")
            DispatchQueue.main.async { completion(nil) }
            return
        }
        dlog("gateway verify: \(ranked.count) ranked → \(ranked.prefix(maxProbes).map { describeEndpoint($0) }.joined(separator: " | "))", category: "ping verify")
        var verified: [Endpoint] = []
        let lock = NSLock()
        let group = DispatchGroup()
        for ep in ranked.prefix(maxProbes) {
            group.enter()
            probeGateway(host: ep.host, port: ep.port, timeout: probeTimeout) { ok in
                MdnsDiscovery.dlog("gateway probe GET http://\(ep.host):\(ep.port)/api/v1/video-live/status → \(ok ? "PASS" : "FAIL")", category: "ping verify")
                if ok {
                    lock.lock()
                    verified.append(ep)
                    lock.unlock()
                }
                group.leave()
            }
        }
        group.notify(queue: .global(qos: .userInitiated)) {
            let best = verified.max(by: { scoreGateway($0) < scoreGateway($1) })
            DispatchQueue.main.async { completion(best) }
        }
    }

    static func discoverGatewayByLANScan(budget: TimeInterval = 5.0, completion: @escaping (Endpoint?) -> Void) {
        let subnets = LANInterface.scanSubnets()
        guard !subnets.isEmpty else {
            dlog("gateway: no local subnets", category: "LAN scan")
            DispatchQueue.main.async { completion(nil) }
            return
        }
        dlog("gateway scan start budget=\(budget)s subnets=\(subnets.map { "\($0.prefix).x" }.joined(separator: ", "))", category: "LAN scan")
        DispatchQueue.global(qos: .utility).async {
            let deadline = Date().addingTimeInterval(budget)
            let probeTimeout = 0.3
            let batchSize = 8

            func finish(_ ep: Endpoint?) {
                DispatchQueue.main.async { completion(ep) }
            }

            for subnet in subnets {
                if Date() >= deadline { break }
                let octets = lanScanHostOctets(for: subnet)
                var idx = 0
                while idx < octets.count, Date() < deadline {
                    let end = min(idx + batchSize, octets.count)
                    let batch = Array(octets[idx ..< end])
                    idx = end
                    let sem = DispatchSemaphore(value: 0)
                    var foundIP: String?
                    probeServiceBatchSync(
                        prefix: subnet.prefix,
                        octets: batch,
                        port: 8790,
                        timeout: probeTimeout,
                        probe: probeGateway
                    ) { ip in
                        foundIP = ip
                        sem.signal()
                    }
                    _ = sem.wait(timeout: .now() + probeTimeout + 0.5)
                    if let ip = foundIP {
                        dlog("gateway HIT \(ip):8790 on \(subnet.prefix).x", category: "LAN scan")
                        finish(Endpoint(
                            host: ip,
                            port: 8790,
                            mdnsHost: gatewayMdnsHost,
                            txt: ["role": "gateway"],
                            serviceName: "LAN scan",
                            bonjourHostName: gatewayMdnsHost
                        ))
                        return
                    }
                }
            }
            dlog("gateway scan finished: no endpoint", category: "LAN scan")
            finish(nil)
        }
    }

    /// Discover `_ha-gateway._tcp` independently (may run on a different host from Brain).
    static func resolveGatewayForAutoDiscover(mdnsTimeout: TimeInterval = 8, completion: @escaping (Endpoint?) -> Void) {
        dlog("gateway auto-discover start mdnsTimeout=\(mdnsTimeout)s (mDNS ∥ LAN scan)", category: "mDNS browse")
        let lock = NSLock()
        var candidates: [Endpoint] = []
        let group = DispatchGroup()

        group.enter()
        resolve(gatewayType, timeout: min(mdnsTimeout, 3)) { ep in
            if let ep, isUsableLanIPv4(ep.host) {
                dlog("gateway auto-discover: mDNS → \(describeEndpoint(ep))", category: "mDNS browse")
                lock.lock()
                candidates.append(ep)
                lock.unlock()
            } else {
                dlog("gateway auto-discover: mDNS nil/unusable", category: "mDNS browse")
            }
            group.leave()
        }

        group.enter()
        discoverGatewayByLANScan(budget: 6) { ep in
            if let ep {
                dlog("gateway auto-discover: LAN scan → \(describeEndpoint(ep))", category: "mDNS browse")
                lock.lock()
                if !candidates.contains(where: { $0.host == ep.host }) {
                    candidates.append(ep)
                }
                lock.unlock()
            }
            group.leave()
        }

        group.notify(queue: .global(qos: .userInitiated)) {
            pickVerifiedGateway(from: candidates, completion: completion)
        }
    }

    static func probeGateway(host: String, port: Int = 8790, timeout: TimeInterval = 1.0, completion: @escaping (Bool) -> Void) {
        guard isUsableLanIPv4(host),
              let url = URL(string: "http://\(host):\(port)/api/v1/video-live/status") else {
            completion(false)
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        URLSession.shared.dataTask(with: request) { data, response, error in
            let ok: Bool
            if error != nil {
                ok = false
            } else if let http = response as? HTTPURLResponse,
                      (200 ..< 300).contains(http.statusCode),
                      let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      json["status"] != nil {
                ok = true
            } else {
                ok = false
            }
            completion(ok)
        }.resume()
    }

    static func pickVerifiedBrain(
        from endpoints: [Endpoint],
        maxProbes: Int = 8,
        probeTimeout: TimeInterval = 1.0,
        completion: @escaping (Endpoint?) -> Void
    ) {
        let ranked = endpoints.filter { isUsableLanIPv4($0.host) }
            .sorted { scoreBrain($0) > scoreBrain($1) }
        guard !ranked.isEmpty else {
            dlog("brain verify: no usable candidates (total=\(endpoints.count))", category: "ping verify")
            DispatchQueue.main.async { completion(nil) }
            return
        }
        dlog("brain verify: \(ranked.count) ranked → \(ranked.prefix(maxProbes).map { describeEndpoint($0) }.joined(separator: " | "))", category: "ping verify")
        var verified: [Endpoint] = []
        let lock = NSLock()
        let group = DispatchGroup()
        for ep in ranked.prefix(maxProbes) {
            group.enter()
            probeBrain(host: ep.host, port: ep.port, timeout: probeTimeout) { ok in
                MdnsDiscovery.dlog("brain probe GET http://\(ep.host):\(ep.port)/api/v1/ping → \(ok ? "PASS" : "FAIL")", category: "ping verify")
                if ok {
                    lock.lock()
                    verified.append(ep)
                    lock.unlock()
                }
                group.leave()
            }
        }
        group.notify(queue: .global(qos: .userInitiated)) {
            let best = verified.max(by: { scoreBrain($0) < scoreBrain($1) })
            DispatchQueue.main.async { completion(best) }
        }
    }

    private static func scoreBrain(_ ep: Endpoint) -> Int {
        var score = 0
        let host = ep.bonjourHostName.lowercased()
        let name = ep.serviceName.lowercased()
        if host.contains("brain.local") { score += 100 }
        if name.contains("home agent brain") || name.contains("brain") { score += 50 }
        if ep.port == 9527 { score += 10 }
        if isOnPreferredLAN(ep.host) { score += 200 }
        if let lanIp = ep.txt["lan_ip"], ep.host == lanIp { score += 400 }
        if let mine = LANInterface.preferredSubnets().first?.hostOctet {
            let parts = ep.host.split(separator: ".")
            if parts.count == 4, UInt8(parts[3]) == mine { score += 30 }
        }
        return score
    }

    static func isOnPreferredLAN(_ host: String) -> Bool {
        guard let prefix = LANInterface.preferredSubnets().first?.prefix else { return true }
        return host.hasPrefix(prefix + ".")
    }

    /// Best-effort Brain: LAN scan + Bonjour in parallel; prefer TXT `lan_ip` / ping-verified.
    static func resolveBrainForAutoDiscover(mdnsTimeout: TimeInterval = 8, completion: @escaping (Endpoint?) -> Void) {
        dlog("brain auto-discover start mdnsTimeout=\(mdnsTimeout)s (LAN scan ∥ mDNS)", category: "mDNS browse")
        let lock = NSLock()
        var candidates: [Endpoint] = []
        let group = DispatchGroup()

        group.enter()
        discoverBrainByLANScan(budget: 6) { ep in
            if let ep {
                dlog("brain auto-discover: LAN scan → \(describeEndpoint(ep))", category: "mDNS browse")
                lock.lock()
                candidates.append(ep)
                lock.unlock()
            }
            group.leave()
        }

        group.enter()
        resolve(brainType, timeout: mdnsTimeout) { ep in
            if let ep, isUsableLanIPv4(ep.host) {
                dlog("brain auto-discover: mDNS → \(describeEndpoint(ep))", category: "mDNS browse")
                lock.lock()
                if !candidates.contains(where: { $0.host == ep.host }) {
                    candidates.append(ep)
                }
                lock.unlock()
            } else if ep == nil {
                dlog("brain auto-discover: mDNS browse returned nil", category: "mDNS browse")
            }
            group.leave()
        }

        group.notify(queue: .global(qos: .userInitiated)) {
            pickVerifiedBrain(from: candidates) { best in
                if let best {
                    dlog("brain chosen: \(describeEndpoint(best))", category: "ping verify")
                } else {
                    dlog("brain verify: no endpoint", category: "ping verify")
                }
                completion(best)
            }
        }
    }

    static func probeBrain(host: String, port: Int, timeout: TimeInterval = 1.5, completion: @escaping (Bool) -> Void) {
        guard isUsableLanIPv4(host) else {
            completion(false)
            return
        }
        let ms = Int64(Date().timeIntervalSince1970 * 1000)
        guard let url = URL(string: "http://\(host):\(port)/api/v1/ping?client_time_ms=\(ms)") else {
            completion(false)
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        URLSession.shared.dataTask(with: request) { data, response, error in
            let ok: Bool
            if error != nil {
                ok = false
            } else if let http = response as? HTTPURLResponse,
                      (200 ..< 300).contains(http.statusCode),
                      let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                if json["app"] as? String == "brain" {
                    ok = true
                } else {
                    ok = json["ok"] as? Bool == true && json["server_time_ms"] != nil
                }
            } else {
                ok = false
            }
            completion(ok)
        }.resume()
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
            let schedule = {
                thread.perform(
                    #selector(BonjourThread.runBox(_:)),
                    on: thread,
                    with: BlockBox(block),
                    waitUntilDone: false
                )
            }
            if started {
                schedule()
                return
            }
            // Never block UIKit main thread while starting the Bonjour RunLoop thread.
            DispatchQueue.global(qos: .userInitiated).async {
                startLock.lock()
                if !started {
                    thread.start()
                    thread.ready.wait()
                    started = true
                }
                startLock.unlock()
                schedule()
            }
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
        private var resolveWatchdog: Timer?

        init(type: String, timeout: TimeInterval, completion: @escaping (Endpoint?) -> Void) {
            self.type = type
            self.timeout = timeout
            self.completion = completion
            super.init()
        }

        func start() {
            MdnsDiscovery.retain(self)
            browser.delegate = self
            let browseType = MdnsDiscovery.bonjourBrowseType(type)
            MdnsDiscovery.dlog("browser START type=\(browseType) domain=local. timeout=\(timeout)s", category: "mDNS browse")
            browser.searchForServices(ofType: browseType, inDomain: "local.")
            timeoutTimer = Timer.scheduledTimer(withTimeInterval: timeout, repeats: false) { [weak self] _ in
                MdnsDiscovery.dlog("browse TIMEOUT type=\(self?.type ?? "?") → resolve phase", category: "mDNS browse")
                self?.beginResolveAll()
            }
        }

        func netServiceBrowser(_ browser: NetServiceBrowser, didFind service: NetService, moreComing: Bool) {
            guard !finished else { return }
            candidates.append(service)
            MdnsDiscovery.dlog(
                "browse FOUND name=\(service.name) type=\(service.type) domain=\(service.domain) port=\(service.port) moreComing=\(moreComing)",
                category: "mDNS browse"
            )
            if !moreComing {
                MdnsDiscovery.dlog("browse moreComing=false → resolve now type=\(type)", category: "mDNS browse")
                beginResolveAll()
            }
        }

        func netServiceBrowser(_ browser: NetServiceBrowser, didNotSearch errorDict: [String: NSNumber]) {
            let code = errorDict[NetService.errorCode]?.intValue ?? -1
            MdnsDiscovery.dlog("browse failed type=\(type) error=\(code)", category: "mDNS browse")
            beginResolveAll()
        }

        private func beginResolveAll() {
            guard !finished, !resolveStarted else { return }
            resolveStarted = true
            timeoutTimer?.invalidate()
            timeoutTimer = nil
            browser.stop()

            if candidates.isEmpty {
                MdnsDiscovery.dlog("browse done type=\(type): 0 services", category: "mDNS browse")
                finish(nil)
                return
            }

            let names = candidates.map(\.name).joined(separator: ", ")
            MdnsDiscovery.dlog("browse done type=\(type): \(candidates.count) service(s) [\(names)]", category: "mDNS browse")

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

            resolveWatchdog = Timer.scheduledTimer(withTimeInterval: timeout + 3.0, repeats: false) { [weak self] _ in
                self?.finish(nil)
            }

            group.notify(queue: .global(qos: .userInitiated)) { [weak self] in
                guard let self = self else { return }
                self.pickAndFinish(endpoints)
            }
        }

        private func pickAndFinish(_ endpoints: [Endpoint]) {
            if type == MdnsDiscovery.brainType {
                MdnsDiscovery.pickVerifiedBrain(from: endpoints) { [weak self] best in
                    let fallback = endpoints.max(by: { MdnsDiscovery.scoreBrain($0) < MdnsDiscovery.scoreBrain($1) })
                    self?.finish(best ?? fallback)
                }
                return
            }
            if type == MdnsDiscovery.gatewayType {
                MdnsDiscovery.pickVerifiedGateway(from: endpoints) { [weak self] best in
                    self?.finish(best ?? MdnsDiscovery.pickBestGateway(from: endpoints))
                }
                return
            }
            finish(endpoints.first)
        }

        private func finish(_ endpoint: Endpoint?) {
            guard !finished else { return }
            finished = true
            resolveWatchdog?.invalidate()
            resolveWatchdog = nil
            timeoutTimer?.invalidate()
            timeoutTimer = nil
            if let endpoint {
                MdnsDiscovery.dlog("pick type=\(type): \(MdnsDiscovery.describeEndpoint(endpoint))", category: "mDNS resolve")
            } else {
                MdnsDiscovery.dlog("pick type=\(type): nil", category: "mDNS resolve")
            }
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
            MdnsDiscovery.dlog(
                "resolve START name=\(found.name) type=\(found.type) domain=\(found.domain) port=\(found.port)",
                category: "mDNS resolve"
            )
            let copy = NetService(domain: found.domain, type: found.type, name: found.name, port: Int32(found.port))
            service = copy
            copy.delegate = self
            copy.resolve(withTimeout: 2.0)
        }

        func netServiceDidResolveAddress(_ sender: NetService) {
            var txt: [String: String] = [:]
            if let data = sender.txtRecordData() {
                let raw = NetService.dictionary(fromTXTRecord: data)
                txt = raw.compactMapValues { String(data: $0, encoding: .utf8) }
            }
            let hostName = (sender.hostName ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard let ipv4 = MdnsDiscovery.preferredIPv4(
                txt: txt,
                hostName: hostName,
                addresses: sender.addresses
            ) else {
                MdnsDiscovery.dlog("resolve FAIL name=\(sender.name) port=\(sender.port) host=\(hostName)", category: "mDNS resolve")
                finish(nil)
                return
            }
            let ep = Endpoint(
                host: ipv4,
                port: sender.port,
                mdnsHost: MdnsDiscovery.wellKnownHost(for: type),
                txt: txt,
                serviceName: sender.name,
                bonjourHostName: hostName
            )
            MdnsDiscovery.dlog("resolve OK \(MdnsDiscovery.describeEndpoint(ep))", category: "mDNS resolve")
            finish(ep)
        }

        func netService(_ sender: NetService, didNotResolve errorDict: [String: NSNumber]) {
            let code = errorDict[NetService.errorCode]?.intValue ?? -1
            MdnsDiscovery.dlog("resolve FAIL name=\(sender.name) error=\(code)", category: "mDNS resolve")
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
