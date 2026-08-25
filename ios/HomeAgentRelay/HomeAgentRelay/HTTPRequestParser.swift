import Foundation

struct HTTPRequest {
    let method: String
    let path: String
    let query: String?
    let version: String
    let headers: [String: String]
    let rawHead: String

    func header(_ name: String) -> String? {
        headers[name.lowercased()]
    }

    var isWebSocketUpgrade: Bool {
        let upgrade = header("upgrade")?.lowercased() == "websocket"
        let connection = header("connection")?.lowercased().contains("upgrade") ?? false
        return upgrade && connection
    }

    var webSocketKey: String? {
        header("sec-websocket-key")
    }

    var headerFields: [RelayHeaderField] {
        RelayHeaderField.list(from: headers)
    }

    var userAgent: String? {
        header("user-agent")
    }
}

enum HTTPRequestParser {
    static let headerTerminator = Data("\r\n\r\n".utf8)

    /// Parses a complete HTTP/1.x request head (everything up to and including `\r\n\r\n`).
    /// First version only needs `GET /path HTTP/1.1`.
    static func parse(headerData: Data) -> HTTPRequest? {
        guard let text = String(data: headerData, encoding: .utf8) ?? String(data: headerData, encoding: .ascii) else {
            return nil
        }
        let normalized = text.replacingOccurrences(of: "\r\n", with: "\n")
        let lines = normalized.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        guard let requestLine = lines.first?.trimmingCharacters(in: .whitespacesAndNewlines),
              !requestLine.isEmpty else {
            return nil
        }
        let parts = requestLine.split(separator: " ", omittingEmptySubsequences: true).map(String.init)
        guard parts.count >= 2 else { return nil }

        let method = parts[0].uppercased()
        let rawTarget = parts[1]
        let version = parts.count >= 3 ? parts[2] : "HTTP/1.1"

        let splitTarget = rawTarget.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false).map(String.init)
        var path = splitTarget.first ?? "/"
        if path.isEmpty { path = "/" }
        let query = splitTarget.count > 1 ? splitTarget[1] : nil

        var headers: [String: String] = [:]
        for line in lines.dropFirst() {
            if line.isEmpty { break }
            guard let colon = line.firstIndex(of: ":") else { continue }
            let name = line[..<colon].trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let value = line[line.index(after: colon)...].trimmingCharacters(in: .whitespacesAndNewlines)
            headers[name] = value
        }

        return HTTPRequest(
            method: method,
            path: path,
            query: query,
            version: version,
            headers: headers,
            rawHead: text
        )
    }
}
