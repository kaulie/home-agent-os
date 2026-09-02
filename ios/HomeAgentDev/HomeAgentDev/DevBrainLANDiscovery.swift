import Darwin
import Foundation

struct DevBrainLANSubnet: Equatable {
    let prefix: String
    let localHostOctet: UInt8
}

enum DevBrainPingParser {
    static func isBrainResponse(_ data: Data) -> Bool {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return false
        }
        if let app = json["app"] as? String, app == "brain" { return true }
        if json["ok"] as? Bool == true, json["server_time_ms"] != nil { return true }
        return false
    }
}

enum DevBrainLANHostOrder {
    /// Prefer last-known ping-verified octet and this phone; do not hardcode home hosts.
    static let commonSuffixes: [UInt8] = [1]

    static func hostOctet(from ipOrURL: String) -> UInt8? {
        let ip = DevBrainLANHostOrder.ipv4(from: ipOrURL)
        guard let ip, let last = ip.split(separator: ".").last, let octet = UInt8(last) else {
            return nil
        }
        return octet
    }

    static func ipv4(from raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if let url = URL(string: trimmed), let host = url.host, !host.isEmpty {
            return isIPv4(host) ? host : nil
        }
        return isIPv4(trimmed) ? trimmed : nil
    }

    static func subnet(from ipv4: String) -> DevBrainLANSubnet? {
        let parts = ipv4.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ UInt8($0) != nil }) else { return nil }
        let host = UInt8(parts[3])!
        guard (1 ... 254).contains(host) else { return nil }
        let prefix = parts.prefix(3).joined(separator: ".")
        return DevBrainLANSubnet(prefix: prefix, localHostOctet: host)
    }

    static func candidateHosts(
        subnet: DevBrainLANSubnet,
        configuredHost: UInt8?,
        lastSuccessHost: UInt8?,
        commonSuffixes: [UInt8] = commonSuffixes
    ) -> [String] {
        var ordered: [UInt8] = []
        func add(_ octet: UInt8) {
            guard (1 ... 254).contains(octet), !ordered.contains(octet) else { return }
            ordered.append(octet)
        }

        if let lastSuccessHost { add(lastSuccessHost) }
        if let configuredHost { add(configuredHost) }
        add(1)
        for suffix in commonSuffixes { add(suffix) }
        if !ordered.contains(subnet.localHostOctet) {
            add(subnet.localHostOctet)
        }
        for hostOctet in 1 ... 254 {
            add(UInt8(hostOctet))
        }

        return ordered.map { "\(subnet.prefix).\($0)" }
    }

    private static func isIPv4(_ value: String) -> Bool {
        subnet(from: value) != nil
    }
}

enum DevBrainLANInterface {
    struct IPv4Address: Equatable {
        let interface: String
        let address: String
    }

    static func ipv4Addresses() -> [IPv4Address] {
        var result: [IPv4Address] = []
        var ifaddrPointer: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddrPointer) == 0, let first = ifaddrPointer else { return [] }
        defer { freeifaddrs(ifaddrPointer) }

        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let current = cursor {
            let iface = current.pointee
            defer { cursor = iface.ifa_next }

            guard let addr = iface.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET) else { continue }
            let flags = Int32(iface.ifa_flags)
            guard (flags & Int32(IFF_UP)) != 0, (flags & Int32(IFF_LOOPBACK)) == 0 else { continue }

            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let gai = getnameinfo(
                addr,
                socklen_t(addr.pointee.sa_len),
                &host,
                socklen_t(host.count),
                nil,
                0,
                NI_NUMERICHOST
            )
            guard gai == 0 else { continue }
            let ip = String(cString: host)
            guard DevBrainLANHostOrder.subnet(from: ip) != nil else { continue }
            result.append(IPv4Address(interface: String(cString: iface.ifa_name), address: ip))
        }

        var seen = Set<String>()
        return result.filter { seen.insert($0.address).inserted }
    }

    static func preferredSubnets() -> [DevBrainLANSubnet] {
        let addresses = ipv4Addresses()
        let wifiFirst = addresses.sorted { lhs, rhs in
            score(lhs.interface, address: lhs.address) > score(rhs.interface, address: rhs.address)
        }
        var subnets: [DevBrainLANSubnet] = []
        var seen = Set<String>()
        for item in wifiFirst {
            guard let subnet = DevBrainLANHostOrder.subnet(from: item.address) else { continue }
            guard seen.insert(subnet.prefix).inserted else { continue }
            subnets.append(subnet)
        }
        return subnets
    }

    private static func score(_ interface: String, address: String) -> Int {
        var score = 0
        if address.hasPrefix("192.168.") { score += 200 }
        if interface == "en0" { score += 100 }
        else if interface.hasPrefix("en") { score += 80 }
        else if interface.hasPrefix("bridge") { score += 10 }
        else { score += 50 }
        return score
    }
}

enum DevBrainLANDiscovery {
    struct Options {
        var port: Int = 9527
        var maxConcurrent: Int = 32
        var hostTimeout: TimeInterval = 0.5
        var totalBudget: TimeInterval = 4.0
    }

    static func discover(
        configuredLAN: String,
        lastSuccessHost: String?,
        options: Options = Options()
    ) async -> String? {
        let subnets = DevBrainLANInterface.preferredSubnets()
        guard !subnets.isEmpty else { return nil }

        let configuredOctet = DevBrainLANHostOrder.hostOctet(from: configuredLAN)
        let lastOctet = lastSuccessHost.flatMap { DevBrainLANHostOrder.hostOctet(from: $0) }
        let deadline = Date().addingTimeInterval(options.totalBudget)

        for subnet in subnets {
            if Date() >= deadline { break }
            let hosts = DevBrainLANHostOrder.candidateHosts(
                subnet: subnet,
                configuredHost: configuredOctet,
                lastSuccessHost: lastOctet
            )
            if let found = await scan(
                hosts: hosts,
                port: options.port,
                maxConcurrent: options.maxConcurrent,
                hostTimeout: options.hostTimeout,
                deadline: deadline
            ) {
                return found
            }
        }
        return nil
    }

    private static func scan(
        hosts: [String],
        port: Int,
        maxConcurrent: Int,
        hostTimeout: TimeInterval,
        deadline: Date
    ) async -> String? {
        guard !hosts.isEmpty else { return nil }
        let chunkSize = max(1, maxConcurrent)
        var index = 0

        while index < hosts.count, Date() < deadline {
            let end = min(index + chunkSize, hosts.count)
            let chunk = Array(hosts[index ..< end])
            index = end

            let found: String? = await withTaskGroup(of: String?.self) { group in
                for host in chunk {
                    group.addTask {
                        if Date() >= deadline { return nil }
                        let base = "http://\(host):\(port)"
                        let ok = await DevBrainProbe.probeBrain(baseURL: base, timeout: hostTimeout)
                        return ok ? base : nil
                    }
                }
                for await result in group {
                    if let base = result {
                        group.cancelAll()
                        return base
                    }
                }
                return nil
            }
            if let found { return found }
        }
        return nil
    }
}
