import XCTest

/// Pure-function regression tests for LAN discovery helpers.
/// (UITest bundle cannot `@testable import` the app; logic mirrored here.)
final class DevBrainLANDiscoveryTests: XCTestCase {
    func testSubnetFromIPv4() {
        let subnet = LANTestHelpers.subnet(from: "192.168.3.84")
        XCTAssertEqual(subnet?.prefix, "192.168.3")
        XCTAssertEqual(subnet?.localHostOctet, 84)
    }

    func testCandidateHostsPrioritizeLastAndConfigured() {
        let subnet = LANTestHelpers.Subnet(prefix: "192.168.3", localHostOctet: 22)
        let hosts = LANTestHelpers.candidateHosts(
            subnet: subnet,
            configuredHost: 73,
            lastSuccessHost: 84
        )
        XCTAssertEqual(hosts.first, "192.168.3.84")
        XCTAssertEqual(hosts[1], "192.168.3.73")
        XCTAssertEqual(hosts[2], "192.168.3.1")
        XCTAssertTrue(hosts.contains("192.168.3.22"))
        XCTAssertEqual(hosts.count, 254)
    }

    func testPingParserAcceptsBrainJSON() {
        let json = #"{"ok":true,"app":"brain","server_time_ms":123}"#.data(using: .utf8)!
        XCTAssertTrue(LANTestHelpers.isBrainResponse(json))
    }

    func testPingParserRejectsArbitraryJSON() {
        let json = #"{"ok":true,"app":"other"}"#.data(using: .utf8)!
        XCTAssertFalse(LANTestHelpers.isBrainResponse(json))
    }

    func testHostOctetFromURL() {
        XCTAssertEqual(
            LANTestHelpers.hostOctet(from: "http://192.168.3.84:9527"),
            84
        )
    }
}

private enum LANTestHelpers {
    struct Subnet: Equatable {
        let prefix: String
        let localHostOctet: UInt8
    }

    static func hostOctet(from ipOrURL: String) -> UInt8? {
        guard let ip = ipv4(from: ipOrURL),
              let last = ip.split(separator: ".").last,
              let octet = UInt8(last) else { return nil }
        return octet
    }

    static func ipv4(from raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if let url = URL(string: trimmed), let host = url.host, !host.isEmpty {
            return subnet(from: host) != nil ? host : nil
        }
        return subnet(from: trimmed) != nil ? trimmed : nil
    }

    static func subnet(from ipv4: String) -> Subnet? {
        let parts = ipv4.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ UInt8($0) != nil }) else { return nil }
        let host = UInt8(parts[3])!
        guard (1 ... 254).contains(host) else { return nil }
        return Subnet(prefix: parts.prefix(3).joined(separator: "."), localHostOctet: host)
    }

    static func candidateHosts(
        subnet: Subnet,
        configuredHost: UInt8?,
        lastSuccessHost: UInt8?,
        commonSuffixes: [UInt8] = [1]
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
        if !ordered.contains(subnet.localHostOctet) { add(subnet.localHostOctet) }
        for hostOctet in 1 ... 254 { add(UInt8(hostOctet)) }
        return ordered.map { "\(subnet.prefix).\($0)" }
    }

    static func isBrainResponse(_ data: Data) -> Bool {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return false
        }
        if let app = json["app"] as? String, app == "brain" { return true }
        if json["ok"] as? Bool == true, json["server_time_ms"] != nil { return true }
        return false
    }
}
