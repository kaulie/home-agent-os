import Darwin
import Foundation
import Network

struct RemotePeer: Equatable {
    let ip: String
    let port: String

    var display: String {
        port.isEmpty ? ip : "\(ip):\(port)"
    }
}

struct IPv4InterfaceAddress: Identifiable, Equatable {
    var id: String { "\(interface)-\(address)" }
    let interface: String
    let address: String
    let flags: Int32

    var isLoopback: Bool {
        (flags & Int32(IFF_LOOPBACK)) != 0
    }

    var looksLikePersonalHotspot: Bool {
        address.hasPrefix("172.20.10.")
            || interface.hasPrefix("bridge")
            || interface == "ap1"
            || interface.hasPrefix("ap")
    }
}

enum NetworkAddressProvider {
    /// Current IPv4 addresses from `getifaddrs`. Does not assume a fixed IP.
    static func ipv4Addresses(includeLoopback: Bool = false) -> [IPv4InterfaceAddress] {
        var result: [IPv4InterfaceAddress] = []
        var ifaddrPointer: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&ifaddrPointer) == 0, let first = ifaddrPointer else {
            return []
        }
        defer { freeifaddrs(ifaddrPointer) }

        var cursor: UnsafeMutablePointer<ifaddrs>? = first
        while let current = cursor {
            let interface = current.pointee
            defer { cursor = interface.ifa_next }

            guard let addr = interface.ifa_addr else { continue }
            guard addr.pointee.sa_family == UInt8(AF_INET) else { continue }

            let flags = Int32(interface.ifa_flags)
            guard (flags & Int32(IFF_UP)) != 0 else { continue }

            let name = String(cString: interface.ifa_name)
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            let length = socklen_t(addr.pointee.sa_len)
            let gai = getnameinfo(
                addr,
                length,
                &host,
                socklen_t(host.count),
                nil,
                0,
                NI_NUMERICHOST
            )
            guard gai == 0 else { continue }
            let ip = String(cString: host)
            guard !ip.isEmpty else { continue }

            let item = IPv4InterfaceAddress(interface: name, address: ip, flags: flags)
            if item.isLoopback && !includeLoopback { continue }
            result.append(item)
        }

        var seen = Set<String>()
        return result.filter { seen.insert($0.id).inserted }
    }

    static func hotspotHint(from addresses: [IPv4InterfaceAddress]) -> String {
        if addresses.contains(where: { $0.looksLikePersonalHotspot }) {
            return "Personal Hotspot likely ON (172.20.10.x or bridge/ap interface present)."
        }
        return "No 172.20.10.x / bridge interface yet. Turn on Personal Hotspot and keep this app in the foreground."
    }

    static func remotePeer(from connection: NWConnection) -> RemotePeer {
        if let remote = connection.currentPath?.remoteEndpoint {
            return parse(remote)
        }
        return parse(connection.endpoint)
    }

    static func parse(_ endpoint: NWEndpoint) -> RemotePeer {
        switch endpoint {
        case .hostPort(let host, let port):
            return RemotePeer(ip: normalizeIP("\(host)"), port: "\(port)")
        default:
            return parse(String(describing: endpoint))
        }
    }

    static func parse(_ raw: String) -> RemotePeer {
        let normalized = normalizeIP(raw)
        if let ipv4 = firstIPv4(in: normalized) {
            let port = portAfterIP(ipv4, in: normalized) ?? ""
            return RemotePeer(ip: ipv4, port: port)
        }
        return RemotePeer(ip: normalized.isEmpty ? "unknown" : normalized, port: "")
    }

    static func normalizeIP(_ raw: String) -> String {
        var ip = raw
        if let mapped = ip.range(of: "::ffff:") {
            ip = String(ip[mapped.upperBound...])
        }
        if let pct = ip.firstIndex(of: "%") {
            ip = String(ip[..<pct])
        }
        return ip.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func firstIPv4(in text: String) -> String? {
        let pattern = #"(\d{1,3}(?:\.\d{1,3}){3})"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(text.startIndex..<text.endIndex, in: text)
        guard let match = regex.firstMatch(in: text, range: range),
              let swiftRange = Range(match.range(at: 1), in: text) else {
            return nil
        }
        return String(text[swiftRange])
    }

    private static func portAfterIP(_ ip: String, in text: String) -> String? {
        guard let ipRange = text.range(of: ip) else { return nil }
        let rest = text[ipRange.upperBound...]
        guard rest.first == ":" else { return nil }
        let digits = rest.dropFirst().prefix { $0.isNumber }
        return digits.isEmpty ? nil : String(digits)
    }
}
