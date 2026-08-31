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
        return "\(ep.serviceName) → \(ep.host):\(ep.port) score=\(scoreEndpoint(ep)) bonjour=\(ep.bonjourHostName) txt={\(txtSummary)}"
    }

    private static func scoreEndpoint(_ ep: Endpoint) -> Int {
        if ep.serviceName == "LAN scan" { return 500 }
        if ep.port == 9527 { return scoreBrain(ep) }
        if ep.port == 8790 { return scoreGateway(ep) }
        return scoreIPv4ForDiscovery(ep.host, txtLanIp: ep.txt["lan_ip"])
    }

    /// Log Wi‑Fi subnets and hints at app launch (call from AppModel bootstrap).
    static func logLaunchNetworkContext() {
        let subnets = LANInterface.scanSubnets()
        if subnets.isEmpty {
            dlog("no RFC1918 Wi‑Fi interface detected (fallback subnets may be used)", category: "launch")
        } else {
            let desc = subnets.map { "\($0.prefix).x self=.\($0.hostOctet) iface=\($0.ifaceName)" }.joined(separator: ", ")
            dlog("Wi‑Fi subnets: \(desc)", category: "launch")
        }
        dlog(
            "local network permission: not directly readable; if browse error=-65570 or 0 results, check Settings → LivingRoomEdge → Local Network",
            category: "launch"
        )
    }

    private static func decodeAllIPv4(from addresses: [Data]?) -> [(ip: String, usable: Bool)] {
        guard let addresses else { return [] }
        var result: [(String, Bool)] = []
        for address in addresses {
            var hostname = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let ok = address.withUnsafeBytes { raw -> Bool in
                guard let ptr = raw.baseAddress?.assumingMemoryBound(to: sockaddr.self) else { return false }
                guard ptr.pointee.sa_family == sa_family_t(AF_INET) else { return false }
                return getnameinfo(ptr, socklen_t(address.count), &hostname, socklen_t(hostname.count), nil, 0, NI_NUMERICHOST) == 0
            }
            if ok {
                let ip = String(cString: hostname)
                result.append((ip, isUsableLanIPv4(ip)))
            }
        }
        return result
    }

    private static func logGetaddrinfoChain(host raw: String, category: String = "getaddrinfo") {
        let host = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
        if host.isEmpty {
            dlog("getaddrinfo skipped: empty host", category: category)
            return
        }
        if let ip = firstIPv4(fromHostString: host) {
            dlog("getaddrinfo \(host) → literal \(ip) usable=\(isUsableLanIPv4(ip))", category: category)
            return
        }
        var hints = addrinfo()
        hints.ai_family = Int32(AF_INET)
        hints.ai_socktype = SOCK_STREAM
        var head: UnsafeMutablePointer<addrinfo>?
        let rc = getaddrinfo(host, nil, &hints, &head)
        guard rc == 0, let head else {
            dlog("getaddrinfo \(host) failed rc=\(rc)", category: category)
            return
        }
        defer { freeaddrinfo(head) }
        var idx = 0
        var cursor: UnsafeMutablePointer<addrinfo>? = head
        while let node = cursor {
            if node.pointee.ai_family == sa_family_t(AF_INET), let addr = node.pointee.ai_addr {
                var name = [CChar](repeating: 0, count: Int(NI_MAXHOST))
                let len = socklen_t(node.pointee.ai_addrlen)
                if getnameinfo(addr, len, &name, socklen_t(name.count), nil, 0, NI_NUMERICHOST) == 0 {
                    let ip = String(cString: name)
                    let usable = isUsableLanIPv4(ip)
                    dlog("getaddrinfo \(host) A[\(idx)] \(ip) usable=\(usable)", category: category)
                    idx += 1
                }
            }
            cursor = node.pointee.ai_next
        }
        if idx == 0 {
            dlog("getaddrinfo \(host) returned 0 IPv4 A records", category: category)
        }
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

    /// Resolve the best service of `type` (async, iOS 13+).
    @available(iOS 13.0, *)
    static func resolve(_ type: String, timeout: TimeInterval = 2.0) async -> Endpoint? {
        let budget = timeout + (type == brainType ? 4.0 : 2.5)
        return await withTaskCancellationHandler {
            await withCheckedContinuation { continuation in
                let lock = NSLock()
                var resumed = false
                func resumeOnce(_ value: Endpoint?) {
                    lock.lock()
                    defer { lock.unlock() }
                    guard !resumed else { return }
                    resumed = true
                    continuation.resume(returning: value)
                }
                resolve(type, timeout: timeout) { resumeOnce($0) }
                DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + budget) {
                    resumeOnce(nil)
                }
            }
        } onCancel: {}
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
        logGetaddrinfoChain(host: raw)
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
        dlog("resolveIPv4Host start host=\(raw)", category: "getaddrinfo")
        let chosen = bestUsableIPv4(candidates: resolveIPv4Candidates(raw))
        dlog("resolveIPv4Host host=\(raw) → \(chosen ?? "nil")", category: "getaddrinfo")
        return chosen
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
        // Do not boost TXT lan_ip: it can lag DHCP while A records / last ping-verified IP are live.
        return score
    }

    static func bestUsableIPv4(candidates: [String], txtLanIp: String? = nil) -> String? {
        uniqueUsableIPv4s(candidates).max {
            scoreIPv4ForDiscovery($0, txtLanIp: txtLanIp) < scoreIPv4ForDiscovery($1, txtLanIp: txtLanIp)
        }
    }

    static func uniqueUsableIPv4s(_ candidates: [String]) -> [String] {
        var seen = Set<String>()
        var out: [String] = []
        for ip in candidates where isUsableLanIPv4(ip) {
            if seen.insert(ip).inserted { out.append(ip) }
        }
        return out
    }

    /// TXT `lan_ip` can be stale after Wi‑Fi DHCP change; Bonjour A records are the live hostname.
    static func allResolvedIPv4s(txt: [String: String], hostName: String, addresses: [Data]?) -> [String] {
        var candidates: [String] = []
        candidates.append(contentsOf: allIPv4(from: addresses))
        let host = hostName.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
        if !host.isEmpty {
            candidates.append(contentsOf: resolveIPv4Candidates(host))
        }
        for key in ["lan_ip", "ipv4", "ip"] {
            if let raw = txt[key]?.trimmingCharacters(in: .whitespacesAndNewlines),
               let ip = firstIPv4(fromHostString: raw) {
                candidates.append(ip)
            }
        }
        return uniqueUsableIPv4s(candidates)
    }

    /// Collect candidates from TXT, hostname A records, and Bonjour addresses; pick best-scored.
    static func preferredIPv4(txt: [String: String], hostName: String, addresses: [Data]?) -> String? {
        let txtLanIp = txt["lan_ip"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        var candidates: [String] = []
        var sources: [String] = []

        if !txt.isEmpty {
            let txtPairs = txt.sorted(by: { $0.key < $1.key }).map { "\($0.key)=\($0.value)" }.joined(separator: ", ")
            dlog("TXT all: {\(txtPairs)}", category: "preferredIPv4")
        } else {
            dlog("TXT all: (empty)", category: "preferredIPv4")
        }

        for key in ["lan_ip", "ipv4", "ip"] {
            if let raw = txt[key]?.trimmingCharacters(in: .whitespacesAndNewlines),
               let ip = firstIPv4(fromHostString: raw) {
                candidates.append(ip)
                sources.append("txt[\(key)]=\(ip)")
            }
        }
        let host = hostName.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
        if !host.isEmpty {
            let fromHost = resolveIPv4Candidates(host)
            candidates.append(contentsOf: fromHost)
            if !fromHost.isEmpty {
                sources.append("getaddrinfo(\(host))=[\(fromHost.joined(separator: ","))]")
            }
        }
        let decoded = decodeAllIPv4(from: addresses)
        if !decoded.isEmpty {
            let addrDesc = decoded.map { "\($0.ip) usable=\($0.usable)" }.joined(separator: ", ")
            dlog("NetService.addresses: [\(addrDesc)]", category: "preferredIPv4")
        }
        let fromAddrs = allIPv4(from: addresses)
        candidates.append(contentsOf: fromAddrs)
        if !fromAddrs.isEmpty {
            sources.append("addresses=[\(fromAddrs.joined(separator: ","))]")
        }

        let liveFirst = uniqueUsableIPv4s(fromAddrs + (host.isEmpty ? [] : resolveIPv4Candidates(host)))
        let chosen = liveFirst.first ?? bestUsableIPv4(candidates: candidates, txtLanIp: txtLanIp)
        let all = allResolvedIPv4s(txt: txt, hostName: hostName, addresses: addresses)
        let scored = all.map { ip in
            "\(ip)(score=\(scoreIPv4ForDiscovery(ip, txtLanIp: nil)))"
        }.joined(separator: ", ")
        let why: String
        if let chosen {
            why = "picked \(chosen) (A-record first; TXT lan_ip only if no A) sources=\(sources.joined(separator: "; ")) all=[\(scored)]"
        } else {
            why = "no usable RFC1918 candidate; sources=\(sources.joined(separator: "; "))"
        }
        dlog(
            "host=\(hostName) txtLanIp=\(txtLanIp ?? "—") → \(chosen ?? "nil") (\(why))",
            category: "preferredIPv4"
        )
        return chosen
    }

    /// Last IPs that answered ping — probed first on LAN scan.
    private static let lastKnownLock = NSLock()
    private static var lastKnownBrainIPs: [String] = []
    private static var lastKnownGatewayIPs: [String] = []

    static func rememberBrainIP(_ ip: String) {
        guard isUsableLanIPv4(ip) else { return }
        lastKnownLock.lock()
        lastKnownBrainIPs = [ip]
        lastKnownLock.unlock()
    }

    static func forgetRememberedBrainIPs() {
        lastKnownLock.lock()
        lastKnownBrainIPs.removeAll()
        lastKnownLock.unlock()
    }

    /// Ping-verified Brain IPv4s, most recent first.
    static func rememberedBrainIPs() -> [String] {
        lastKnownLock.lock()
        defer { lastKnownLock.unlock() }
        return lastKnownBrainIPs
    }

    static func rememberGatewayIP(_ ip: String) {
        guard isUsableLanIPv4(ip) else { return }
        lastKnownLock.lock()
        lastKnownGatewayIPs.removeAll { $0 == ip }
        lastKnownGatewayIPs.insert(ip, at: 0)
        if lastKnownGatewayIPs.count > 4 { lastKnownGatewayIPs.removeLast() }
        lastKnownLock.unlock()
    }

    /// Probe order: last-known successful IPs, this iPhone, router (.1), then rest of /24.
    private static func lanScanHostOctets(for subnet: LANInterface.Subnet, hints: [String] = []) -> [UInt8] {
        var octets: [UInt8] = []
        func add(_ o: UInt8) {
            guard (1 ... 254).contains(o), !octets.contains(o) else { return }
            octets.append(o)
        }
        for ip in hints {
            let parts = ip.split(separator: ".")
            if parts.count == 4,
               ip.hasPrefix(subnet.prefix + "."),
               let o = UInt8(parts[3]) {
                add(o)
            }
        }
        add(subnet.hostOctet)
        add(1)
        for o in 2 ... 254 { add(UInt8(o)) }
        return octets
    }

    /// Fallback when Bonjour browse finds nothing (AP isolation / mDNS blocked on Wi‑Fi).
    @available(iOS 13.0, *)
    static func discoverBrainByLANScan(budget: TimeInterval = 5.0) async -> Endpoint? {
        let subnets = LANInterface.scanSubnets()
        guard !subnets.isEmpty else {
            dlog("brain: no local subnets", category: "LAN scan")
            return nil
        }
        dlog(
            "brain scan start budget=\(budget)s subnets=\(subnets.map { "\($0.prefix).x (self=.\($0.hostOctet))" }.joined(separator: ", "))",
            category: "LAN scan"
        )
        let deadline = Date().addingTimeInterval(budget)
        let probeTimeout = 0.3
        let batchSize = 8

        for subnet in subnets {
            if Date() >= deadline { break }
            lastKnownLock.lock()
            let hints = lastKnownBrainIPs
            lastKnownLock.unlock()
            let octets = lanScanHostOctets(for: subnet, hints: hints)
            dlog("brain probing \(subnet.prefix).x (\(octets.count) hosts, batches of \(batchSize))", category: "LAN scan")
            var idx = 0
            var batches = 0
            while idx < octets.count, Date() < deadline {
                let end = min(idx + batchSize, octets.count)
                let batch = Array(octets[idx ..< end])
                idx = end
                batches += 1
                if let ip = await probeServiceBatch(
                    prefix: subnet.prefix,
                    octets: batch,
                    port: 9527,
                    batchIndex: batches,
                    serviceLabel: "brain",
                    probe: { await probeBrainLogged(host: $0, port: 9527, timeout: probeTimeout) }
                ) {
                    dlog("brain HIT \(ip):9527 on \(subnet.prefix).x after \(batches) batches", category: "LAN scan")
                    return Endpoint(
                        host: ip,
                        port: 9527,
                        mdnsHost: brainMdnsHost,
                        txt: ["role": "brain"],
                        serviceName: "LAN scan",
                        bonjourHostName: brainMdnsHost
                    )
                }
            }
            dlog("brain no hit on \(subnet.prefix).x (\(batches) batches)", category: "LAN scan")
        }
        dlog("brain scan finished: no endpoint", category: "LAN scan")
        return nil
    }

    @available(iOS 13.0, *)
    private static func probeServiceBatch(
        prefix: String,
        octets: [UInt8],
        port: Int,
        batchIndex: Int,
        serviceLabel: String,
        probe: @escaping (String) async -> (Bool, String)
    ) async -> String? {
        var results: [(String, Bool, String)] = []
        await withTaskGroup(of: (String, Bool, String).self) { group in
            for hostOctet in octets {
                group.addTask {
                    let ip = "\(prefix).\(hostOctet)"
                    let (ok, detail) = await probe(ip)
                    return (ip, ok, detail)
                }
            }
            for await result in group {
                results.append(result)
                if result.1 {
                    group.cancelAll()
                }
            }
        }
        let hits = results.filter(\.1)
        if hits.isEmpty {
            dlog("\(serviceLabel) batch #\(batchIndex): \(results.count) hosts, 0 pass", category: "LAN scan")
        } else {
            let summary = results.map { "\($0.0):\(port) → \($0.1 ? "PASS" : "FAIL")" }.joined(separator: ", ")
            dlog("\(serviceLabel) batch #\(batchIndex) [\(summary)]", category: "LAN scan")
        }
        return hits.first?.0
    }

    @available(iOS 13.0, *)
    private static func probeBrainLogged(host: String, port: Int, timeout: TimeInterval) async -> (Bool, String) {
        let (ok, detail) = await probeBrainDetailed(host: host, port: port, timeout: timeout)
        if ok {
            dlog("brain probe HIT \(host):\(port) \(detail)", category: "LAN scan")
        }
        return (ok, detail)
    }

    @available(iOS 13.0, *)
    private static func probeGatewayLogged(host: String, port: Int, timeout: TimeInterval) async -> (Bool, String) {
        let (ok, detail) = await probeGatewayDetailed(host: host, port: port, timeout: timeout)
        if ok {
            dlog("gateway probe HIT \(host):\(port) \(detail)", category: "LAN scan")
        }
        return (ok, detail)
    }

    private enum LANInterface {
        struct Subnet {
            let prefix: String
            let hostOctet: UInt8
            let ifaceName: String
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
                let subnet = Subnet(prefix: prefix, hostOctet: last, ifaceName: name)
                if name == "en0" || name.hasPrefix("en") {
                    result.insert(subnet, at: 0)
                } else {
                    result.append(subnet)
                }
            }
            return result
        }

        static func scanSubnets() -> [Subnet] {
            let live = preferredSubnets()
            if !live.isEmpty { return live }
            return [
                Subnet(prefix: "192.168.3", hostOctet: 1, ifaceName: "fallback"),
                Subnet(prefix: "192.168.1", hostOctet: 1, ifaceName: "fallback"),
            ]
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

    /// Trust LAN scan or Bonjour when TXT `lan_ip` matches the resolved host.
    static func isTrustworthyGateway(_ ep: Endpoint) -> Bool {
        if ep.serviceName == "LAN scan" { return true }
        if isUsableLanIPv4(ep.host) { return true }
        return false
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
        if let lanIp = ep.txt["lan_ip"], ep.host == lanIp { score += 50 }
        if let mine = LANInterface.preferredSubnets().first?.hostOctet {
            let parts = ep.host.split(separator: ".")
            if parts.count == 4, UInt8(parts[3]) == mine { score += 30 }
        }
        return score
    }

    @available(iOS 13.0, *)
    static func pickVerifiedGateway(from endpoints: [Endpoint], maxProbes: Int = 8, probeTimeout: TimeInterval = 1.0) async -> Endpoint? {
        let ranked = endpoints.filter { isUsableLanIPv4($0.host) && isTrustworthyGateway($0) }
            .sorted { scoreGateway($0) > scoreGateway($1) }
        guard !ranked.isEmpty else {
            dlog("gateway verify: no trustworthy candidates (total=\(endpoints.count))", category: "ping verify")
            return nil
        }
        dlog(
            "gateway verify: \(ranked.count) ranked → \(ranked.prefix(maxProbes).map { "\(describeEndpoint($0)) trustworthy=\(isTrustworthyGateway($0))" }.joined(separator: " | "))",
            category: "ping verify"
        )
        var verified: [Endpoint] = []
        for ep in ranked.prefix(maxProbes) {
            let (ok, detail) = await probeGatewayDetailed(host: ep.host, port: ep.port, timeout: probeTimeout)
            dlog("gateway probe GET http://\(ep.host):\(ep.port)/api/v1/video-live/status → \(ok ? "PASS" : "FAIL") \(detail)", category: "ping verify")
            if ok { verified.append(ep) }
        }
        let best = verified.max(by: { scoreGateway($0) < scoreGateway($1) })
        if let best {
            rememberGatewayIP(best.host)
            dlog("gateway chosen: \(describeEndpoint(best))", category: "ping verify")
        } else {
            dlog("gateway verify: all probes failed", category: "ping verify")
        }
        return best
    }

    @available(iOS 13.0, *)
    static func discoverGatewayByLANScan(budget: TimeInterval = 5.0) async -> Endpoint? {
        let subnets = LANInterface.scanSubnets()
        guard !subnets.isEmpty else {
            dlog("gateway: no local subnets", category: "LAN scan")
            return nil
        }
        dlog(
            "gateway scan start budget=\(budget)s subnets=\(subnets.map { "\($0.prefix).x" }.joined(separator: ", "))",
            category: "LAN scan"
        )
        let deadline = Date().addingTimeInterval(budget)
        let probeTimeout = 0.3
        let batchSize = 8

        for subnet in subnets {
            if Date() >= deadline { break }
            lastKnownLock.lock()
            let hints = lastKnownGatewayIPs
            lastKnownLock.unlock()
            let octets = lanScanHostOctets(for: subnet, hints: hints)
            dlog("gateway probing \(subnet.prefix).x (\(octets.count) hosts)", category: "LAN scan")
            var idx = 0
            var batches = 0
            while idx < octets.count, Date() < deadline {
                let end = min(idx + batchSize, octets.count)
                let batch = Array(octets[idx ..< end])
                idx = end
                batches += 1
                if let ip = await probeServiceBatch(
                    prefix: subnet.prefix,
                    octets: batch,
                    port: 8790,
                    batchIndex: batches,
                    serviceLabel: "gateway",
                    probe: { await probeGatewayLogged(host: $0, port: 8790, timeout: probeTimeout) }
                ) {
                    dlog("gateway HIT \(ip):8790 on \(subnet.prefix).x after \(batches) batches", category: "LAN scan")
                    return Endpoint(
                        host: ip,
                        port: 8790,
                        mdnsHost: gatewayMdnsHost,
                        txt: ["role": "gateway"],
                        serviceName: "LAN scan",
                        bonjourHostName: gatewayMdnsHost
                    )
                }
            }
            dlog("gateway no hit on \(subnet.prefix).x (\(batches) batches)", category: "LAN scan")
        }
        dlog("gateway scan finished: no endpoint", category: "LAN scan")
        return nil
    }

    /// Discover `_ha-gateway._tcp` independently (may run on a different host from Brain).
    @available(iOS 13.0, *)
    static func resolveGatewayForAutoDiscover(mdnsTimeout: TimeInterval = 8) async -> Endpoint? {
        dlog("gateway auto-discover start mdnsTimeout=\(mdnsTimeout)s (mDNS first, LAN scan fallback)", category: "mDNS browse")
        let start = Date()
        if let browsed = await resolve(gatewayType, timeout: min(mdnsTimeout, 3)),
           isUsableLanIPv4(browsed.host),
           isTrustworthyGateway(browsed) {
            dlog("gateway auto-discover: mDNS finished in \(String(format: "%.2f", Date().timeIntervalSince(start)))s → \(describeEndpoint(browsed))", category: "mDNS browse")
            rememberGatewayIP(browsed.host)
            return browsed
        }
        dlog("gateway auto-discover: mDNS missed, LAN scan fallback…", category: "mDNS browse")
        if let scanned = await discoverGatewayByLANScan(budget: 6) {
            dlog("gateway auto-discover: LAN scan → \(describeEndpoint(scanned))", category: "mDNS browse")
            rememberGatewayIP(scanned.host)
            return scanned
        }
        dlog("gateway auto-discover: nothing found", category: "mDNS browse")
        return nil
    }

    @available(iOS 13.0, *)
    static func probeGateway(host: String, port: Int = 8790, timeout: TimeInterval = 1.0) async -> Bool {
        await probeGatewayDetailed(host: host, port: port, timeout: timeout).0
    }

    @available(iOS 13.0, *)
    private static func probeGatewayDetailed(host: String, port: Int = 8790, timeout: TimeInterval = 1.0) async -> (Bool, String) {
        guard isUsableLanIPv4(host) else { return (false, "not RFC1918") }
        guard let url = URL(string: "http://\(host):\(port)/api/v1/video-live/status") else {
            return (false, "bad URL")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return (false, "non-HTTP response")
            }
            guard (200 ..< 300).contains(http.statusCode) else {
                return (false, "HTTP \(http.statusCode)")
            }
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return (false, "HTTP \(http.statusCode) invalid JSON")
            }
            if json["status"] != nil {
                return (true, "HTTP \(http.statusCode) status OK")
            }
            return (false, "HTTP \(http.statusCode) missing status field")
        } catch {
            return (false, "error: \(error.localizedDescription)")
        }
    }

    @available(iOS 13.0, *)
    static func pickVerifiedBrain(from endpoints: [Endpoint], maxProbes: Int = 8, probeTimeout: TimeInterval = 1.0) async -> Endpoint? {
        var pool = endpoints
        for ip in rememberedBrainIPs() where !pool.contains(where: { $0.host == ip }) {
            pool.append(
                Endpoint(
                    host: ip,
                    port: 9527,
                    mdnsHost: brainMdnsHost,
                    txt: [:],
                    serviceName: "last-known",
                    bonjourHostName: brainMdnsHost
                )
            )
        }
        let ranked = pool.filter { isUsableLanIPv4($0.host) }
            .sorted { scoreBrain($0) > scoreBrain($1) }
        guard !ranked.isEmpty else {
            dlog("brain verify: no usable candidates (total=\(endpoints.count))", category: "ping verify")
            return nil
        }
        dlog(
            "brain verify: \(ranked.count) ranked → \(ranked.prefix(maxProbes).map { describeEndpoint($0) }.joined(separator: " | "))",
            category: "ping verify"
        )
        var verified: [Endpoint] = []
        await withTaskGroup(of: (Endpoint, Bool, String).self) { group in
            for ep in ranked.prefix(maxProbes) {
                group.addTask {
                    let (ok, detail) = await probeBrainDetailed(host: ep.host, port: ep.port, timeout: probeTimeout)
                    return (ep, ok, detail)
                }
            }
            for await (ep, ok, detail) in group {
                dlog("brain probe GET http://\(ep.host):\(ep.port)/api/v1/ping → \(ok ? "PASS" : "FAIL") \(detail)", category: "ping verify")
                if ok { verified.append(ep) }
            }
        }
        let best = verified.max(by: { scoreBrain($0) < scoreBrain($1) })
        if let best {
            rememberBrainIP(best.host)
            dlog("brain chosen: \(describeEndpoint(best))", category: "ping verify")
        } else {
            dlog("brain verify: all probes failed", category: "ping verify")
        }
        return best
    }

    private static func scoreBrain(_ ep: Endpoint) -> Int {
        var score = 0
        let host = ep.bonjourHostName.lowercased()
        let name = ep.serviceName.lowercased()
        if host.contains("brain.local") { score += 100 }
        if name.contains("home agent brain") || name.contains("brain") { score += 50 }
        if ep.port == 9527 { score += 10 }
        if isOnPreferredLAN(ep.host) { score += 200 }
        lastKnownLock.lock()
        let known = lastKnownBrainIPs
        lastKnownLock.unlock()
        if let idx = known.firstIndex(of: ep.host) {
            score += 80 - (idx * 10)
        }
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

    /// Best-effort Brain: Bonjour first (Mac `dns-sd -L` then A records), LAN scan only if that fails.
    @available(iOS 13.0, *)
    static func resolveBrainForAutoDiscover(mdnsTimeout: TimeInterval = 8) async -> Endpoint? {
        dlog("brain auto-discover start mdnsTimeout=\(mdnsTimeout)s (mDNS first, LAN scan fallback)", category: "mDNS browse")
        let start = Date()
        let browsed = await resolve(brainType, timeout: min(mdnsTimeout, 3))
        if let b = browsed, isUsableLanIPv4(b.host) {
            dlog("brain auto-discover: mDNS finished in \(String(format: "%.2f", Date().timeIntervalSince(start)))s → \(describeEndpoint(b))", category: "mDNS browse")
            rememberBrainIP(b.host)
            return b
        }
        dlog("brain auto-discover: mDNS missed, LAN scan fallback…", category: "mDNS browse")
        if let s = await discoverBrainByLANScan(budget: 6) {
            dlog("brain auto-discover: LAN scan → \(describeEndpoint(s))", category: "mDNS browse")
            rememberBrainIP(s.host)
            return s
        }
        dlog("brain auto-discover: nothing found", category: "mDNS browse")
        return nil
    }

    @available(iOS 13.0, *)
    static func probeBrain(host: String, port: Int, timeout: TimeInterval = 1.5) async -> Bool {
        await probeBrainDetailed(host: host, port: port, timeout: timeout).0
    }

    @available(iOS 13.0, *)
    private static func probeBrainDetailed(host: String, port: Int, timeout: TimeInterval = 1.5) async -> (Bool, String) {
        guard isUsableLanIPv4(host) else { return (false, "not RFC1918") }
        let ms = Int64(Date().timeIntervalSince1970 * 1000)
        guard let url = URL(string: "http://\(host):\(port)/api/v1/ping?client_time_ms=\(ms)") else {
            return (false, "bad URL")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return (false, "non-HTTP response")
            }
            guard (200 ..< 300).contains(http.statusCode) else {
                return (false, "HTTP \(http.statusCode)")
            }
            guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return (false, "HTTP \(http.statusCode) invalid JSON")
            }
            if json["app"] as? String == "brain" {
                return (true, "HTTP \(http.statusCode) app=brain")
            }
            if json["ok"] as? Bool == true, json["server_time_ms"] != nil {
                return (true, "HTTP \(http.statusCode) ok=true")
            }
            return (false, "HTTP \(http.statusCode) unexpected JSON")
        } catch {
            return (false, "error: \(error.localizedDescription)")
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
                MdnsDiscovery.dlog("browse TIMEOUT type=\(self?.type ?? "?") after \(self?.timeout ?? 0)s → resolve phase", category: "mDNS browse")
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
            // Don't wait the full browse timeout — Mac dns-sd -L also proceeds as soon as the PTR is in.
            if !moreComing {
                beginResolveAll()
            } else if timeoutTimer != nil {
                timeoutTimer?.invalidate()
                timeoutTimer = Timer.scheduledTimer(withTimeInterval: 0.4, repeats: false) { [weak self] _ in
                    MdnsDiscovery.dlog("browse settle 0.4s after FOUND → resolve phase", category: "mDNS browse")
                    self?.beginResolveAll()
                }
            }
        }

        func netServiceBrowser(_ browser: NetServiceBrowser, didNotSearch errorDict: [String: NSNumber]) {
            let code = errorDict[NetService.errorCode]?.intValue ?? -1
            let hint = code == -65570 ? " (likely Local Network denied)" : ""
            MdnsDiscovery.dlog("browse FAILED type=\(type) error=\(code)\(hint)", category: "mDNS browse")
            beginResolveAll()
        }

        private func beginResolveAll() {
            guard !finished, !resolveStarted else { return }
            resolveStarted = true
            timeoutTimer?.invalidate()
            timeoutTimer = nil
            browser.stop()
            MdnsDiscovery.dlog("browser STOP type=\(type)", category: "mDNS browse")

            if candidates.isEmpty {
                MdnsDiscovery.dlog("browse done type=\(type): 0 services (timeout or AP isolation?)", category: "mDNS browse")
                finish(nil)
                return
            }

            let names = candidates.map { "\($0.name)@\($0.domain)" }.joined(separator: ", ")
            MdnsDiscovery.dlog("browse done type=\(type): \(candidates.count) service(s) → resolving [\(names)]", category: "mDNS browse")

            var endpoints: [Endpoint] = []
            let group = DispatchGroup()
            let lock = NSLock()

            for service in candidates {
                group.enter()
                let one = SingleServiceResolver(type: type) { eps in
                    lock.lock()
                    endpoints.append(contentsOf: eps)
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
                guard let self else { return }
                self.pickAndFinish(endpoints)
            }
        }

        private func pickAndFinish(_ endpoints: [Endpoint]) {
            if endpoints.isEmpty {
                MdnsDiscovery.dlog("resolve type=\(type): 0 endpoints after resolve", category: "mDNS resolve")
            } else {
                MdnsDiscovery.dlog(
                    "resolve type=\(type): \(endpoints.count) endpoint(s) → \(endpoints.map { MdnsDiscovery.describeEndpoint($0) }.joined(separator: " | "))",
                    category: "mDNS resolve"
                )
            }
            if #available(iOS 13.0, *) {
                if type == MdnsDiscovery.brainType {
                    Task {
                        let best = await MdnsDiscovery.pickVerifiedBrain(from: endpoints)
                        self.finish(best)
                    }
                    return
                }
                if type == MdnsDiscovery.gatewayType {
                    Task {
                        let best = await MdnsDiscovery.pickVerifiedGateway(from: endpoints)
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
        private let completion: ([Endpoint]) -> Void
        private var service: NetService?
        private var finished = false

        init(type: String, completion: @escaping ([Endpoint]) -> Void) {
            self.type = type
            self.completion = completion
            super.init()
        }

        func resolve(_ found: NetService) {
            MdnsDiscovery.dlog(
                "resolve START name=\(found.name) type=\(found.type) domain=\(found.domain) port=\(found.port) timeout=2.0s",
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
            MdnsDiscovery.dlog("resolve hostName=\(hostName) port=\(sender.port) from name=\(sender.name)", category: "mDNS resolve")
            _ = MdnsDiscovery.preferredIPv4(
                txt: txt,
                hostName: hostName,
                addresses: sender.addresses
            )
            let ips = MdnsDiscovery.allResolvedIPv4s(
                txt: txt,
                hostName: hostName,
                addresses: sender.addresses
            )
            guard !ips.isEmpty else {
                MdnsDiscovery.dlog("resolve FAIL name=\(sender.name) port=\(sender.port) host=\(hostName) (no usable IPv4)", category: "mDNS resolve")
                finish([])
                return
            }
            let eps = ips.map { ip in
                Endpoint(
                    host: ip,
                    port: sender.port,
                    mdnsHost: MdnsDiscovery.wellKnownHost(for: type),
                    txt: txt,
                    serviceName: sender.name,
                    bonjourHostName: hostName
                )
            }
            MdnsDiscovery.dlog(
                "resolve OK name=\(sender.name) ips=[\(ips.joined(separator: ", "))] port=\(sender.port)",
                category: "mDNS resolve"
            )
            finish(eps)
        }

        func netService(_ sender: NetService, didNotResolve errorDict: [String: NSNumber]) {
            let code = errorDict[NetService.errorCode]?.intValue ?? -1
            MdnsDiscovery.dlog("resolve FAIL name=\(sender.name) error=\(code)", category: "mDNS resolve")
            finish([])
        }

        private func finish(_ endpoints: [Endpoint]) {
            guard !finished else { return }
            finished = true
            service?.stop()
            completion(endpoints)
            MdnsDiscovery.release(self)
        }
    }
}
