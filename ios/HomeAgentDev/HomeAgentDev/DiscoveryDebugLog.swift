import Foundation
import SwiftUI
import UIKit

extension Notification.Name {
    static let discoveryDebugLogDidChange = Notification.Name("DiscoveryDebugLogDidChange")
}

/// Append-only discovery trace for Brain / Gateway mDNS, LAN scan, and connect decisions.
/// Recording is **off** until the settings toggle is on (avoids constant UI refresh).
final class DiscoveryDebugLog {
    static let shared = DiscoveryDebugLog()

    static let maxLines = 400
    private static let enabledKey = "ha.discoveryDebugLog.enabled"

    private(set) var text = ""
    private(set) var lineCount = 0

    private var lines: [String] = []
    private let lock = NSLock()

    private init() {}

    /// Default false: do not append or notify until the user turns it on.
    var isEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: Self.enabledKey) }
        set {
            UserDefaults.standard.set(newValue, forKey: Self.enabledKey)
            DispatchQueue.main.async {
                NotificationCenter.default.post(name: .discoveryDebugLogDidChange, object: nil)
            }
            if newValue {
                log("探测日志已打开", category: "connect")
            }
        }
    }

    func log(_ message: String, category: String? = nil) {
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
        lineCount = lines.count
        lock.unlock()
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: .discoveryDebugLogDidChange, object: nil)
        }
    }

    func clear() {
        lock.lock()
        lines.removeAll()
        text = ""
        lineCount = 0
        lock.unlock()
        DispatchQueue.main.async {
            NotificationCenter.default.post(name: .discoveryDebugLogDidChange, object: nil)
        }
    }

    private static func timestamp() -> String {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss.SSS"
        return formatter.string(from: Date())
    }
}

struct DiscoveryDebugLogView: View {
    var onRefresh: (() async -> Void)?

    @State private var logText = DiscoveryDebugLog.shared.text
    @State private var lineCount = DiscoveryDebugLog.shared.lineCount
    @State private var copyHint = ""
    @State private var refreshing = false

    @State private var enabled = DiscoveryDebugLog.shared.isEnabled

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Toggle("记录探测日志", isOn: $enabled)
                .font(.subheadline)
                .onChange(of: enabled) { value in
                    DiscoveryDebugLog.shared.isEnabled = value
                }
            if enabled {
                HStack {
                    Text("\(lineCount) 行")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Spacer()
                    if refreshing {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                ScrollViewReader { proxy in
                    ScrollView {
                        Text(displayText)
                            .font(.caption2.monospaced())
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .textSelection(.enabled)
                            .id("log-bottom")
                    }
                    .frame(minHeight: 160, maxHeight: 360)
                    .onChange(of: lineCount) { _ in
                        withAnimation(.easeOut(duration: 0.15)) {
                            proxy.scrollTo("log-bottom", anchor: .bottom)
                        }
                    }
                    .onAppear {
                        proxy.scrollTo("log-bottom", anchor: .bottom)
                    }
                }
                HStack(spacing: 12) {
                    Button("清空") {
                        DiscoveryDebugLog.shared.clear()
                    }
                    Button("复制") { copyLog() }
                    if let onRefresh {
                        Button("重新探测") {
                            guard !refreshing else { return }
                            refreshing = true
                            DiscoveryDebugLog.shared.log("manual refresh from settings", category: "connect")
                            Task {
                                await onRefresh()
                                refreshing = false
                            }
                        }
                        .disabled(refreshing)
                    }
                    if !copyHint.isEmpty {
                        Text(copyHint)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.caption)
            } else {
                Text("需要排查局域网发现时再打开。关闭时不写日志、界面也不刷新。")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .discoveryDebugLogDidChange)) { _ in
            enabled = DiscoveryDebugLog.shared.isEnabled
            logText = DiscoveryDebugLog.shared.text
            lineCount = DiscoveryDebugLog.shared.lineCount
        }
    }

    private var displayText: String {
        if logText.isEmpty {
            return "（尚无日志；打开开关后点「重新探测」/「自动发现」）"
        }
        return logText
    }

    private func copyLog() {
        UIPasteboard.general.string = logText
        copyHint = "已复制"
    }
}
