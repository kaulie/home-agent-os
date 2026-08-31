import Foundation

extension Notification.Name {
    static let discoveryDebugLogDidChange = Notification.Name("DiscoveryDebugLogDidChange")
}

/// Append-only discovery trace for Brain / Gateway mDNS, LAN scan, and connect decisions.
final class DiscoveryDebugLog {
    static let shared = DiscoveryDebugLog()

    static let maxLines = 300

    private(set) var text = ""
    var onUpdate: (() -> Void)?

    private var lines: [String] = []
    private let lock = NSLock()

    private init() {}

    func log(_ message: String, category: String? = nil) {
        appendFormatted(message, category: category)
    }

    func log(category: String, _ message: String) {
        appendFormatted(message, category: category)
    }

    private func appendFormatted(_ message: String, category: String?) {
        let ts = Self.timestamp()
        let line: String
        if let category, !category.isEmpty {
            line = "[\(ts)] [\(category)] \(message)"
        } else {
            line = "[\(ts)] \(message)"
        }
        lock.lock()
        lines.append(line)
        if lines.count > Self.maxLines {
            lines.removeFirst(lines.count - Self.maxLines)
        }
        text = lines.joined(separator: "\n")
        lock.unlock()
        DispatchQueue.main.async { [weak self] in
            NotificationCenter.default.post(name: .discoveryDebugLogDidChange, object: nil)
            self?.onUpdate?()
        }
    }

    func clear() {
        lock.lock()
        lines.removeAll()
        text = ""
        lock.unlock()
        DispatchQueue.main.async { [weak self] in
            NotificationCenter.default.post(name: .discoveryDebugLogDidChange, object: nil)
            self?.onUpdate?()
        }
    }

    private static func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: Date())
    }
}
