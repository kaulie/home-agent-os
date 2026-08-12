import Foundation

/// GET queued living-room intents from the business server.
///
/// Production response shape (`scheduler_node` + per-step `assigned_edge_id`):
/// ```
/// { "intents": [ {
///     "id": 1, "status": "intent_parsed",
///     "scheduler_node": "edge-node-…",
///     "execution_plan": [{
///       "step": 1,
///       "capability": "camera.capture",
///       "status": 0,
///       "input_constrict": {},
///       "assigned_edge_id": "edge-node-…"
///     }, {
///       "step": 2,
///       "capability": "display.photo",
///       "status": 0,
///       "input_constrict": { "photo_url": "$photo_url" },
///       "assigned_edge_id": "edge-node-…"
///     }]
/// } ] }
/// ```
/// Optional `reason` is skipped. `output_constrict` controls RuntimeContext publish
/// (only fields with `data_dest: "context"`).
///
/// Pull **must** include this node's `edge_id`. Keep an intent if this node is
/// `scheduler_node` **or** any plan step's `assigned_edge_id` matches.
final class HttpCommandSource {
    var pullURL: String
    /// Appended as `?intent_status=` when the URL does not already include it.
    /// Nil = no status filter (needed so executor can pull `intent_dispatched`).
    var intentStatusFilter: String? = nil
    /// This node's Brain-issued edge id (required for pull). Defaults to [EdgeIdStore].
    var localEdgeId: String?

    static let defaultPullURL =
        "http://115.190.153.53:9527/api/v1/devices/living-room/intents"

    init(pullURL: String = HttpCommandSource.defaultPullURL, localEdgeId: String? = nil) {
        self.pullURL = pullURL
        self.localEdgeId = localEdgeId
    }

    private func resolvedLocalEdgeId() -> String? {
        let fromProp = localEdgeId?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let fromProp, !fromProp.isEmpty { return fromProp }
        return EdgeIdStore.load()
    }

    /// Raw intents relevant to this edge (scheduler and/or local executor steps).
    /// - Parameter consume: `true` = pop queue (Agent tick); `false` = `?peek=1` (UI display).
    func fetchIntents(consume: Bool = true) async throws -> [[String: Any]] {
        guard let edgeId = resolvedLocalEdgeId(), !edgeId.isEmpty else {
            return []
        }
        let text = try await fetchIntentsBody(consume: consume, edgeId: edgeId)
        switch Self.parseIntentsResult(text, localEdgeId: edgeId) {
        case .parsed(let intents):
            NSLog(
                "[HttpCommandSource] fetchIntents edge=%@ consume=%@ kept=%d bodyPrefix=%@",
                edgeId,
                consume ? "true" : "false",
                intents.count,
                String(text.prefix(180)).replacingOccurrences(of: "\n", with: " ")
            )
            return intents
        case .invalidJSON:
            throw NSError(
                domain: "HttpCommandSource",
                code: 0,
                userInfo: [NSLocalizedDescriptionKey: "intents JSON 解析失败: \(text.prefix(120))"]
            )
        }
    }

    /// - Parameter consume: `true` = pop queue (Agent tick); `false` = `?peek=1` (UI display).
    func fetch(consume: Bool = true) async throws -> [EdgeCommand] {
        guard let edgeId = resolvedLocalEdgeId(), !edgeId.isEmpty else {
            return []
        }
        let intents = try await fetchIntents(consume: consume)
        var commands: [EdgeCommand] = []
        for (index, intent) in intents.enumerated() {
            commands.append(contentsOf: Self.makeLocalStepCommands(from: intent, index: index, localEdgeId: edgeId))
        }
        return commands
    }

    private func fetchIntentsBody(consume: Bool, edgeId: String) async throws -> String {
        let trimmed = pullURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmed), !trimmed.isEmpty else {
            throw URLError(.badURL)
        }
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "peek" || $0.name == "edge_id" || $0.name == "edgeId" }
        items.append(URLQueryItem(name: "edge_id", value: edgeId))
        if !consume {
            items.append(URLQueryItem(name: "peek", value: "1"))
        }
        if let filter = intentStatusFilter?.trimmingCharacters(in: .whitespacesAndNewlines),
           !filter.isEmpty,
           !items.contains(where: { $0.name == "intent_status" || $0.name == "status" })
        {
            items.append(URLQueryItem(name: "intent_status", value: filter))
        }
        components.queryItems = items
        guard let url = components.url else {
            throw URLError(.badURL)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        let timed = try await TimedHTTP.data(for: request, label: "intents-pull")
        guard let http = timed.http else {
            throw URLError(.badServerResponse)
        }
        let text = String(data: timed.data, encoding: .utf8) ?? ""
        guard (200 ..< 300).contains(http.statusCode) else {
            throw NSError(
                domain: "HttpCommandSource",
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: "intents HTTP \(http.statusCode): \(text.prefix(200))"]
            )
        }
        return text
    }

    enum ParseResult {
        case parsed([EdgeCommand])
        case invalidJSON
    }

    enum IntentsParseResult {
        case parsed([[String: Any]])
        case invalidJSON
    }

    /// Parse UI buffer / HTTP body into commands for this edge (local steps only).
    static func parseResult(_ text: String, localEdgeId: String? = EdgeIdStore.load()) -> ParseResult {
        switch parseIntentsResult(text, localEdgeId: localEdgeId) {
        case .invalidJSON:
            return .invalidJSON
        case .parsed(let intents):
            let selfId = localEdgeId?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            var commands: [EdgeCommand] = []
            for (index, item) in intents.enumerated() {
                commands.append(contentsOf: makeLocalStepCommands(from: item, index: index, localEdgeId: selfId))
            }
            return .parsed(commands)
        }
    }

    static func parseIntentsResult(_ text: String, localEdgeId: String? = EdgeIdStore.load()) -> IntentsParseResult {
        let raw = stripTimingSuffix(text).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty, let data = raw.data(using: .utf8) else {
            return .invalidJSON
        }
        guard let json = try? JSONSerialization.jsonObject(with: data) else {
            return .invalidJSON
        }
        let list: [[String: Any]]
        if let obj = json as? [String: Any] {
            if let intents = obj["intents"] as? [Any] {
                list = intents.compactMap { asStringKeyedDict($0) }
            } else if obj["execution_plan"] != nil || (obj["id"] != nil && obj["status"] != nil) {
                list = [obj]
            } else {
                list = []
            }
        } else if let arr = json as? [Any] {
            list = arr.compactMap { asStringKeyedDict($0) }
        } else {
            return .invalidJSON
        }

        let selfId = localEdgeId?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !selfId.isEmpty else { return .parsed([]) }
        // Drop empty `{}` placeholders Brain sometimes returns in the array.
        let nonEmpty = list.filter { !$0.isEmpty }
        let relevant = nonEmpty.filter { isRelevant(intent: $0, localEdgeId: selfId) }
        NSLog(
            "[HttpCommandSource] parse raw=%d nonEmpty=%d relevant=%d self=%@",
            list.count,
            nonEmpty.count,
            relevant.count,
            selfId
        )
        for (i, intent) in nonEmpty.enumerated() {
            let iid = stringValue(intent["id"]) ?? "?"
            let sched = stringValue(intent["scheduler_node"]) ?? "-"
            let st = stringValue(intent["intent_status"]) ?? stringValue(intent["status"]) ?? "-"
            let keep = isRelevant(intent: intent, localEdgeId: selfId)
            let stepAssign = ((intent["execution_plan"] as? [Any]) ?? []).compactMap { step -> String? in
                guard let d = asStringKeyedDict(step) else { return nil }
                let n = stringValue(d["step"]) ?? "?"
                let a = stringValue(d["assigned_edge_id"]) ?? "-"
                let cap = stringValue(d["capability"]) ?? "?"
                return "\(n):\(cap)@\(a)"
            }.joined(separator: ",")
            NSLog(
                "[HttpCommandSource] intent[%d] id=%@ status=%@ scheduler=%@ steps=[%@] keep=%@",
                i, iid, st, sched, stepAssign, keep ? "yes" : "no"
            )
        }
        return .parsed(relevant)
    }

    static func parseCommandsJSON(_ text: String) -> [EdgeCommand] {
        if case let .parsed(commands) = parseResult(text) {
            return commands
        }
        return []
    }

    /// `true` when text is valid intents JSON (even if queue empty / all filtered out).
    static func isValidCommandsDocument(_ text: String) -> Bool {
        let raw = stripTimingSuffix(text).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data)
        else { return false }
        if let obj = json as? [String: Any] {
            return obj["intents"] != nil
                || obj["execution_plan"] != nil
                || (obj["id"] != nil && obj["status"] != nil)
        }
        return json is [Any]
    }

    /// Scheduler node or any locally assigned plan step. Terminal intents are never work.
    static func isRelevant(intent: [String: Any], localEdgeId: String) -> Bool {
        let selfId = localEdgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !selfId.isEmpty else { return false }
        let st = (stringValue(intent["intent_status"])
            ?? stringValue(intent["status"])
            ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if st == "succeeded" || st == "failed" {
            return false
        }
        let scheduler = (stringValue(intent["scheduler_node"])
            ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if scheduler == selfId { return true }
        let plan = intent["execution_plan"] as? [Any] ?? []
        for step in plan {
            guard let dict = asStringKeyedDict(step) else { continue }
            let assigned = (stringValue(dict["assigned_edge_id"])
                ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if assigned == selfId { return true }
        }
        return false
    }

    /// Expand only steps assigned to this edge.
    static func makeLocalStepCommands(
        from intent: [String: Any],
        index: Int,
        localEdgeId: String
    ) -> [EdgeCommand] {
        let selfId = localEdgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        let plan = intent["execution_plan"] as? [Any] ?? []
        let planDicts = plan.compactMap { asStringKeyedDict($0) }
        let localSteps = planDicts.filter { step in
            let assigned = (stringValue(step["assigned_edge_id"])
                ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return assigned == selfId
        }
        if localSteps.isEmpty {
            // Scheduler-only relevance: no local executor work.
            return []
        }
        return localSteps.map { makeCommand(fromIntent: intent, step: $0, localEdgeId: selfId, planCount: planDicts.count) }
    }

    /// Build one EdgeCommand for a plan step (used by IntentStepExecutor).
    static func makeCommand(
        fromIntent intent: [String: Any],
        step: [String: Any],
        localEdgeId: String,
        planCount: Int? = nil
    ) -> EdgeCommand {
        let intentId = stringValue(intent["id"]) ?? stringValue(intent["intent_id"]) ?? "intent"
        let status = stringValue(intent["intent_status"]) ?? stringValue(intent["status"]) ?? ""
        let plan = intent["execution_plan"] as? [Any] ?? []
        let total = planCount ?? plan.count
        let stepNum = stringValue(step["step"]) ?? "1"
        let capability = (stringValue(step["capability"]) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let mapped = splitCapability(capability)
        let assigned = (stringValue(step["assigned_edge_id"])
            ?? localEdgeId).trimmingCharacters(in: .whitespacesAndNewlines)
        var params: [String: String] = [
            "intent_id": intentId,
            "capability": capability,
            "step": stepNum,
            "plan_step_count": "\(total)",
            "assigned_edge_id": assigned,
            "step_status_api": "1",
        ]
        if !status.isEmpty { params["intent_status"] = status }
        let skipKeys: Set<String> = [
            "capability", "step", "reason", "status", "step_status",
            "input_constrict", "output_constrict",
            "assigned_edge_id", "outputs",
            "execution_timing", "delay_sec",
        ]
        for (k, v) in step {
            if skipKeys.contains(k) { continue }
            if let s = stringValue(v) { params[k] = s }
        }
        mergeInputConstrict(step, into: &params)
        let outputConstrict = parseOutputConstrict(step)
        var raw = intent
        raw["capability"] = capability
        raw["step"] = step["step"] ?? stepNum
        raw["assigned_edge_id"] = assigned
        return EdgeCommand(
            commandId: total > 1 ? "\(intentId)-\(stepNum)" : intentId,
            device: mapped.device,
            action: mapped.action,
            params: params,
            schedule: parseSchedule(intent),
            source: .server,
            raw: raw,
            outputConstrict: outputConstrict
        )
    }

    private static func mergeInputConstrict(_ step: [String: Any], into params: inout [String: String]) {
        guard let constrictAny = step["input_constrict"],
              let constrict = asStringKeyedDict(constrictAny) else { return }
        for (k, v) in constrict {
            if let s = stringValue(v) { params[k] = s }
        }
    }

    /// Parse `output_constrict`: field → { type, data_dest }.
    private static func parseOutputConstrict(_ step: [String: Any]) -> [String: OutputConstrictField] {
        guard let constrictAny = step["output_constrict"],
              let constrict = asStringKeyedDict(constrictAny) else { return [:] }
        var out: [String: OutputConstrictField] = [:]
        for (key, value) in constrict {
            let fieldKey = key.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !fieldKey.isEmpty else { continue }
            if let obj = asStringKeyedDict(value) {
                out[fieldKey] = OutputConstrictField(
                    type: stringValue(obj["type"]),
                    dataDest: stringValue(obj["data_dest"])
                )
            }
        }
        return out
    }

    private static func splitCapability(_ capability: String) -> (device: String, action: String) {
        let c = capability.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !c.isEmpty else { return ("", "") }
        // Prefer full capability_id as device for CommandDecomposer ("camera.capture").
        if c.contains(".") {
            let parts = c.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
            if parts.count >= 2 {
                return (c, parts.last ?? "")
            }
        }
        return (c, "")
    }

    private static func parseSchedule(_ cmd: [String: Any]) -> ScheduleSpec {
        let type = (stringValue(cmd["schedule_type"]) ?? "instant")
            .lowercased()
        switch type {
        case "cron":
            let expr = stringValue(cmd["cron"]) ?? stringValue(cmd["expression"]) ?? "0 * * * *"
            return .cron(expression: expr)
        case "event":
            let ev = stringValue(cmd["event"]) ?? stringValue(cmd["event_type"]) ?? "unknown"
            return .event(eventType: ev, filter: stringValue(cmd["filter"]))
        default:
            return .instant
        }
    }

    private static func asStringKeyedDict(_ any: Any) -> [String: Any]? {
        if let dict = any as? [String: Any] { return dict }
        if let dict = any as? [AnyHashable: Any] {
            var out: [String: Any] = [:]
            for (k, v) in dict {
                out[String(describing: k)] = v
            }
            return out
        }
        return nil
    }

    private static func stringValue(_ any: Any?) -> String? {
        switch any {
        case let s as String: return s
        case let n as NSNumber: return n.stringValue
        default: return nil
        }
    }

    private static func stripTimingSuffix(_ text: String) -> String {
        var lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        while let last = lines.last {
            let t = last.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.hasPrefix("⏱") || t.isEmpty {
                lines.removeLast()
                continue
            }
            break
        }
        return lines.joined(separator: "\n")
    }
}
