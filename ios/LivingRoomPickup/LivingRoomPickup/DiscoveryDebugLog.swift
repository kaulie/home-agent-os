import Foundation

extension Notification.Name {
    static let discoveryDebugLogDidChange = Notification.Name("DiscoveryDebugLogDidChange")
}

/// Append-only discovery trace. Recording is off until the settings switch is on.
final class DiscoveryDebugLog {
    static let shared = DiscoveryDebugLog()

    static let maxLines = 400
    private static let enabledKey = "ha.discoveryDebugLog.enabled"

    private(set) var text = ""
    var onUpdate: (() -> Void)?

    private var lines: [String] = []
    private let lock = NSLock()

    private init() {}

    var isEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: Self.enabledKey) }
        set {
            UserDefaults.standard.set(newValue, forKey: Self.enabledKey)
            notify()
            if newValue {
                log("探测日志已打开", category: "connect")
            }
        }
    }

    func log(_ message: String, category: String? = nil) {
        appendFormatted(message, category: category)
    }

    func log(category: String, _ message: String) {
        appendFormatted(message, category: category)
    }

    private func appendFormatted(_ message: String, category: String?) {
        guard isEnabled else { return }
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
        notify()
    }

    func clear() {
        lock.lock()
        lines.removeAll()
        text = ""
        lock.unlock()
        notify()
    }

    private func notify() {
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
