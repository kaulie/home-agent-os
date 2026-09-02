import Foundation

enum BrainURL {
    static func normalizeIntentURL(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") {
            value.removeLast()
        }
        if value.isEmpty {
            return ParticipantStore.defaultBrainIntentURL
        }
        if value.hasSuffix("/api/v1/intent") {
            return value
        }
        if value.contains("/api/v1/") {
            return value
        }
        return value + "/api/v1/intent"
    }

    static func displayBase(from intentURL: String) -> String {
        var value = normalizeIntentURL(intentURL)
        if value.hasSuffix("/api/v1/intent") {
            value = String(value.dropLast("/api/v1/intent".count))
        }
        while value.hasSuffix("/") {
            value.removeLast()
        }
        return value
    }

    static func apiURL(fromIntentURL intentURL: String, leaf: String) -> URL? {
        let trimmed = normalizeIntentURL(intentURL)
        guard var components = URLComponents(string: trimmed) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + leaf
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + leaf
        } else {
            path = "/api/v1/" + leaf
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func intentDetailURL(fromIntentURL intentURL: String, intentId: String) -> URL? {
        guard var components = URLComponents(string: normalizeIntentURL(intentURL)) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "intent_detail"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "intent_detail"
        } else {
            path = "/api/v1/intent_detail"
        }
        components.path = path
        components.queryItems = [URLQueryItem(name: "intent_id", value: intentId)]
        return components.url
    }

    static func assetsUploadURL(fromIntentURL intentURL: String) -> URL? {
        apiURL(fromIntentURL: intentURL, leaf: "assets/upload")
    }

    static func debugReportURL(fromIntentURL intentURL: String) -> URL? {
        apiURL(fromIntentURL: intentURL, leaf: "debug/report")
    }

    static func ipv4Host(from raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let host: String
        if let url = URL(string: trimmed), let urlHost = url.host, !urlHost.isEmpty {
            host = urlHost
        } else {
            host = trimmed
        }
        let parts = host.split(separator: ".")
        guard parts.count == 4, parts.allSatisfy({ UInt8($0) != nil }) else { return nil }
        return host
    }

    /// Timeout ≠ DNS; both are NSURLErrorDomain.
    static func describeTransportError(_ error: Error, url: URL) -> String {
        let ns = error as NSError
        let host = url.host ?? "?"
        let viaIP = ipv4Host(from: url.absoluteString) != nil
        let target = viaIP ? "IPv4 \(host)" : "主机名 \(host)"
        guard ns.domain == NSURLErrorDomain else {
            return "\(ns.localizedDescription) · \(target)"
        }
        switch ns.code {
        case NSURLErrorTimedOut:
            return "请求超时（不是 DNS）· \(target)"
        case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed:
            return "DNS/mDNS 解析失败 · \(target)"
        case NSURLErrorCannotConnectToHost:
            return "TCP 连不上 · \(target)"
        case NSURLErrorNetworkConnectionLost:
            return "连接中断 · \(target)"
        case NSURLErrorNotConnectedToInternet:
            return "无网络 · \(target)"
        default:
            return "NSURLError \(ns.code) \(ns.localizedDescription) · \(target)"
        }
    }
}
