import Foundation

struct RelayLogEntry: Identifiable, Equatable {
    let id: UUID
    let date: Date
    let message: String

    var line: String {
        let formatter = RelayLog.timeFormatter
        return "[\(formatter.string(from: date))] \(message)"
    }
}

struct RelayHeaderField: Identifiable, Equatable {
    var id: String { name }
    let name: String
    let value: String

    private static let preferredOrder = [
        "user-agent",
        "host",
        "accept",
        "accept-language",
        "accept-encoding",
        "connection",
        "upgrade",
        "origin",
        "referer",
        "content-type",
        "sec-websocket-version",
        "sec-websocket-protocol",
    ]

    static func list(from headers: [String: String]) -> [RelayHeaderField] {
        var used = Set<String>()
        var result: [RelayHeaderField] = []
        for key in preferredOrder {
            if let value = headers[key], !value.isEmpty {
                result.append(RelayHeaderField(name: displayName(key), value: value))
                used.insert(key)
            }
        }
        for key in headers.keys.sorted() where !used.contains(key) {
            let value = headers[key] ?? ""
            guard !value.isEmpty else { continue }
            result.append(RelayHeaderField(name: displayName(key), value: value))
        }
        return result
    }

    private static func displayName(_ key: String) -> String {
        key.split(separator: "-").map { part in
            part.uppercased() == "WEBSOCKET" ? "WebSocket" : part.capitalized
        }.joined(separator: "-")
    }
}

struct RelayPeerConnection: Identifiable, Equatable {
    let id: UUID
    var ip: String
    var remotePort: String
    var kind: String
    var detail: String
    var isActive: Bool
    let connectedAt: Date
    var lastActivityAt: Date
    var headers: [RelayHeaderField] = []

    var userAgent: String? {
        headers.first(where: { $0.name.lowercased() == "user-agent" })?.value
    }
}

struct RelayPeerGroup: Identifiable {
    var id: String { ip }
    let ip: String
    let connections: [RelayPeerConnection]

    var activeCount: Int { connections.filter(\.isActive).count }

    var userAgent: String? {
        connections.compactMap(\.userAgent).first
    }
}

enum RelayPeerEvent {
    case opened(id: UUID, ip: String, port: String, kind: String)
    case activity(id: UUID, detail: String, ip: String, port: String, headers: [RelayHeaderField])
    case closed(id: UUID)
}

enum RelayLog {
    static let maxEntries = 50
    static let maxPeerConnections = 50

    static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()
}
