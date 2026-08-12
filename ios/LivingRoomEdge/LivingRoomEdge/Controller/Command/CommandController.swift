import Foundation

/// Pulls queued device commands; execute path goes through [CommandHandler].
final class CommandController: DeviceController {
    let controllerId = "commands"
    let displayName = "Command Pull"

    private let gopro: GoProPluginEntry
    private let commandSource = HttpCommandSource()
    weak var commandHandler: CommandHandler?

    init(gopro: GoProPluginEntry) {
        self.gopro = gopro
    }

    /// GET intents queue from `serverURL`（默认加 `?peek=1`，不消费）.
    func pullCommands(serverURL: String) async -> ControllerResult {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return .failure("invalid server_url")
        }
        commandSource.pullURL = trimmed
        guard var components = URLComponents(string: trimmed) else {
            return .failure("invalid server_url")
        }
        guard let edgeId = EdgeIdStore.load()?.trimmingCharacters(in: .whitespacesAndNewlines),
              !edgeId.isEmpty
        else {
            return .failure("缺少本地 edge_id，请先完成 edge-register")
        }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "peek" || $0.name == "edge_id" || $0.name == "edgeId" }
        items.append(URLQueryItem(name: "edge_id", value: edgeId))
        items.append(URLQueryItem(name: "peek", value: "1"))
        // Keep caller's intent_status if present; do not force intent_parsed —
        // executor also needs intent_dispatched intents.
        components.queryItems = items
        guard let url = components.url else {
            return .failure("invalid server_url")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30

        do {
            let timed = try await TimedHTTP.data(for: request, label: "intents-pull")
            guard let http = timed.http else {
                return .failure("invalid intents response · \(timed.durationLabel)")
            }
            let textBody = String(data: timed.data, encoding: .utf8) ?? ""
            let withTime: (String) -> String = { "\($0)\n⏱ \(timed.durationLabel)" }
            if (200 ..< 300).contains(http.statusCode) {
                if case .invalidJSON = HttpCommandSource.parseResult(textBody) {
                    return .failure(withTime("响应不是合法 intents JSON: \(textBody.prefix(180))"))
                }
                let display = textBody.isEmpty ? "{\"intents\":[]}" : textBody
                return .success(withTime(display), data: timed.data)
            }
            return .failure(withTime("intents HTTP \(http.statusCode): \(textBody.prefix(200))"))
        } catch let timed as TimedHTTP.Failure {
            return pullFailure(timed.nsError, duration: timed.durationLabel)
        } catch {
            return pullFailure(error as NSError, duration: nil)
        }
    }

    /// Parse pulled JSON and run via CommandHandler (decompose → schedule → dispatch → runtime).
    func executeCommands(jsonText: String) async -> ControllerResult {
        let raw = Self.stripTimingSuffix(jsonText).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else {
            return .failure("没有可执行的指令内容，请先拉取指令")
        }
        switch HttpCommandSource.parseResult(raw) {
        case .invalidJSON:
            return .failure("指令 JSON 解析失败（请确认是 {\"intents\":[...]}）\n\(raw.prefix(180))")
        case .parsed(let commands):
            guard !commands.isEmpty else {
                // Valid document with empty queue — not a parse error.
                return .success("intents 为空，无需执行（队列可能已被 Agent 心跳消费）")
            }
            guard let handler = commandHandler else {
                return await executeCommandsLegacy(commands: commands)
            }
            let results = await handler.handle(commands)
            let lines = results.map { r in
                "[\(r.taskId)] \(r.skipped ? "SKIP" : (r.ok ? "OK" : "FAIL")) — \(r.message ?? "")"
            }
            let summary = lines.joined(separator: "\n")
            let allOk = results.allSatisfy { $0.ok || $0.skipped }
            return allOk ? .success(summary) : .failure(summary)
        }
    }

    private func executeCommandsLegacy(commands: [EdgeCommand]) async -> ControllerResult {
        var lines: [String] = []
        var allOk = true
        for cmd in commands {
            let device = cmd.device.lowercased()
            let action = cmd.action.lowercased()
            let result: ControllerResult
            switch device {
            case "gopro", "gopro_controller", "camera":
                result = await gopro.handleDeviceCommand(action: action, command: cmd.raw)
            case "":
                result = .failure("command \(cmd.commandId): missing device")
            default:
                result = .failure("command \(cmd.commandId): unsupported device '\(device)'")
            }
            if !result.ok { allOk = false }
            lines.append("[\(cmd.commandId)] \(device).\(action): \(result.ok ? "OK" : "FAIL") — \(result.message)")
        }
        let summary = lines.joined(separator: "\n")
        return allOk ? .success(summary) : .failure(summary)
    }

    private func pullFailure(_ ns: NSError, duration: String?) -> ControllerResult {
        let suffix = duration.map { "\n⏱ \($0)" } ?? ""
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNetworkConnectionLost {
            return .failure("intents pull failed: network connection was lost — 确认已离开 GoPro Wi‑Fi\(suffix)")
        }
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNotConnectedToInternet {
            return .failure("intents pull failed: no internet\(suffix)")
        }
        return .failure("intents pull failed: \(ns.localizedDescription)\(suffix)")
    }

    private func stringValue(_ any: Any?) -> String? {
        switch any {
        case let s as String:
            return s
        case let n as NSNumber:
            return n.stringValue
        default:
            return nil
        }
    }

    /// Drop trailing `⏱ …` line appended by TimedHTTP display helpers.
    private static func stripTimingSuffix(_ text: String) -> String {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard let last = lines.last, last.hasPrefix("⏱") else { return text }
        return lines.dropLast().joined(separator: "\n")
    }
}
