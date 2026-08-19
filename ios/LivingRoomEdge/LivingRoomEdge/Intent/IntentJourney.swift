import Foundation
import Combine

/// Wire statuses for intent logistics job (must match server).
enum IntentPhase: String, CaseIterable, Equatable {
    case uploaded = "intent_received"
    case intentParsed = "intent_parsed"
    case scheduled = "intent_scheduled"
    case assigned = "intent_dispatched"
    case running
    case succeeded
    case failed

    /// Display steps (terminal success/failure share the last slot).
    static let timelineOrder: [IntentPhase] = [
        .uploaded, .intentParsed, .scheduled, .assigned, .running, .succeeded,
    ]

    var label: String {
        switch self {
        case .uploaded: return "上传到服务器，待意图解析"
        case .intentParsed: return "意图解析完成，待下发到中控节点"
        case .scheduled: return "任务已调度（intent_scheduled）"
        case .assigned: return "任务已分发到执行节点（intent_dispatched）"
        case .running: return "任务执行中"
        case .succeeded: return "任务执行完成（成功）"
        case .failed: return "任务执行完成（失败）"
        }
    }

    var rank: Int {
        switch self {
        case .uploaded: return 0
        case .intentParsed: return 1
        case .scheduled: return 2
        case .assigned: return 3
        case .running: return 4
        case .succeeded, .failed: return 5
        }
    }

    var isTerminal: Bool {
        self == .succeeded || self == .failed
    }

    /// Map production wire `intent_status` / detail `status` → phase.
    static func fromWire(_ raw: String) -> IntentPhase? {
        switch raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
        case "intent_received":
            return .uploaded
        case "intent_parsed":
            return .intentParsed
        case "intent_scheduled":
            return .scheduled
        case "intent_dispatched":
            return .assigned
        case "running":
            return .running
        case "succeeded":
            return .succeeded
        case "failed":
            return .failed
        default:
            return nil
        }
    }

    /// Value written back to server as `intent_status`.
    var wireValue: String { rawValue }
}

enum IntentPhaseVisualState: Equatable {
    case pending
    case active
    case done
    case failed
    case timedOut
}

struct IntentPhaseState: Identifiable, Equatable {
    var id: IntentPhase { phase }
    let phase: IntentPhase
    var visual: IntentPhaseVisualState
    var detail: String
    var at: Date?
    /// Seconds spent in this phase (done/failed: frozen; active: filled at render with `now`).
    var durationSeconds: TimeInterval?
}

struct IntentJobStep: Equatable {
    let status: IntentPhase
    let at: Date?
    let detail: String
}

/// Per-capability execution progress (local Edge updates; not on the wire yet).
enum IntentPlanStepRunStatus: Equatable {
    case waiting
    case queued
    case running
    case succeeded
    case failed
    case skipped

    var label: String {
        switch self {
        case .waiting: return "等待"
        case .queued: return "排队"
        case .running: return "执行中"
        case .succeeded: return "完成"
        case .failed: return "失败"
        case .skipped: return "跳过"
        }
    }

    var isTerminal: Bool {
        self == .succeeded || self == .failed || self == .skipped
    }
}

/// One `step_log` event from intent_detail / peek.
struct IntentStepEvent: Equatable, Identifiable {
    var id: String { identityKey }
    let step: Int
    let status: Int?
    let msg: String
    let at: Date?

    var identityKey: String {
        let ts = at.map { String(Int($0.timeIntervalSince1970 * 1000)) } ?? ""
        return "\(step)|\(status.map(String.init) ?? "")|\(ts)|\(msg)"
    }

    var statusLabel: String {
        switch status {
        case 0: return "等待"
        case 1: return "执行中"
        case 2: return "完成"
        case 3: return "失败"
        default: return status.map { "status=\($0)" } ?? "记录"
        }
    }
}

/// One capability row from `execution_plan` (shown line-by-line in the UI).
struct IntentPlanStepItem: Equatable, Identifiable {
    var id: String { "\(step)-\(capability)-\(index)" }
    let index: Int
    let step: Int
    let capability: String
    let summary: String
    /// `input_constrict` (+ step-level input fields), key → value (may be `$var`).
    var inputs: [String: String]
    /// Declared `output_constrict` and/or realized `outputs` values.
    var outputs: [String: String]
    /// Updated locally as each capability runs; preserved across intent_detail refreshes.
    var runStatus: IntentPlanStepRunStatus
    var runDetail: String
    var startedAt: Date?
    var finishedAt: Date?
    var assignedEdge: String
    var events: [IntentStepEvent]
    /// Raw `execution_plan[].status` 0/1/2/3 when known.
    var wireStatusCode: Int?

    init(
        index: Int,
        step: Int,
        capability: String,
        summary: String,
        inputs: [String: String] = [:],
        outputs: [String: String] = [:],
        runStatus: IntentPlanStepRunStatus = .waiting,
        runDetail: String = "",
        startedAt: Date? = nil,
        finishedAt: Date? = nil,
        assignedEdge: String = "",
        events: [IntentStepEvent] = [],
        wireStatusCode: Int? = nil
    ) {
        self.index = index
        self.step = step
        self.capability = capability
        self.summary = summary
        self.inputs = inputs
        self.outputs = outputs
        self.runStatus = runStatus
        self.runDetail = runDetail
        self.startedAt = startedAt
        self.finishedAt = finishedAt
        self.assignedEdge = assignedEdge
        self.events = events
        self.wireStatusCode = wireStatusCode
    }

    var realizedOutputs: [String: String] {
        Dictionary(uniqueKeysWithValues: outputs.filter { !Self.isSchemaPlaceholder($0.value) })
    }

    var schemaOutputs: [String: String] {
        Dictionary(uniqueKeysWithValues: outputs.filter { Self.isSchemaPlaceholder($0.value) })
    }

    static func isSchemaPlaceholder(_ value: String) -> Bool {
        let t = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.hasPrefix("(") && t.hasSuffix(")")
    }

    func durationSeconds(now: Date = Date()) -> TimeInterval? {
        guard let start = startedAt else { return nil }
        let end = finishedAt ?? (runStatus == .running ? now : nil)
        guard let end else { return nil }
        return max(0, end.timeIntervalSince(start))
    }
}

/// Brain `intent_detail.presentation`. Endpoint renders by `type`; do not flatten to a fake reply.
struct IntentPresentation: Equatable {
    enum Kind: String, Equatable {
        case text
        case image
        case video
        case html
        case audio
    }

    let type: Kind
    let channel: String
    /// Endpoint participant_id that should render this payload (not Intent Source).
    let endpoint: String
    let text: String
    let imageURL: URL?
    let videoURL: URL?

    var hasContent: Bool {
        switch type {
        case .image:
            return imageURL != nil
        case .video:
            return videoURL != nil
        case .audio:
            return videoURL != nil || !text.isEmpty
        case .text, .html:
            return !text.isEmpty
        }
    }

    var copyText: String {
        if !text.isEmpty { return text }
        if let imageURL { return imageURL.absoluteString }
        if let videoURL { return videoURL.absoluteString }
        return ""
    }

    static func parse(_ raw: Any?) -> IntentPresentation? {
        guard let obj = raw as? [String: Any] else { return nil }
        let typeRaw = (obj["type"] as? String ?? "text")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let type: Kind = {
            switch typeRaw {
            case "image": return .image
            case "video": return .video
            case "html": return .html
            case "audio": return .audio
            default: return .text
            }
        }()
        let channel = (obj["channel"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let endpoint = (obj["endpoint"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let text = (obj["text"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let imageURL = urlValue(obj["image_url"] ?? obj["imageUrl"] ?? obj["photo_url"])
        let videoURL = urlValue(obj["video_url"] ?? obj["videoUrl"])
        let pres = IntentPresentation(
            type: type,
            channel: channel,
            endpoint: endpoint,
            text: text,
            imageURL: imageURL,
            videoURL: videoURL
        )
        return pres.hasContent ? pres : nil
    }

    private static func urlValue(_ raw: Any?) -> URL? {
        guard let s = raw as? String else { return nil }
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, let url = URL(string: t), url.scheme != nil else { return nil }
        return url
    }
}

struct IntentJobSnapshot: Equatable {
    let jobId: String
    /// Display phase (may lead the wire, but never invents terminal).
    let status: IntentPhase
    /// Raw `intent_status` / `status` from Brain. Terminal only when this is succeeded/failed.
    let wireStatus: IntentPhase
    let text: String
    let source: String
    /// Issuer Intent Source id (`jobs.edge_id`), not the Runtime `assigned_edge_id`.
    let issuerId: String
    let createdAt: Date?
    let edgeNodeId: String?
    let error: String?
    let reply: String?
    let presentation: IntentPresentation?
    let steps: [IntentJobStep]
    let planSteps: [IntentPlanStepItem]

    static func parse(data: Data) -> IntentJobSnapshot? {
        guard
            let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }
        return parse(json: obj)
    }

    static func parse(jsonText: String) -> IntentJobSnapshot? {
        let body = stripTimingSuffix(jsonText)
        guard let data = body.data(using: .utf8) else { return nil }
        return parse(data: data)
    }

    static func parse(json: [String: Any]) -> IntentJobSnapshot? {
        // POST: intent_id + intent_status; detail: id + status (+ execution_plan)
        guard let jobId = stringValue(json["intent_id"])
            ?? stringValue(json["id"]),
            !jobId.isEmpty
        else { return nil }
        let statusRaw = stringValue(json["intent_status"])
            ?? stringValue(json["status"])
            ?? "intent_received"
        let wireStatus = IntentPhase.fromWire(statusRaw) ?? .uploaded
        let text = stringValue(json["text"]) ?? ""
        let sourceRaw = (stringValue(json["source"]) ?? "text")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let source = sourceRaw == "voice" ? "voice" : "text"
        let issuerId = stringValue(json["edge_id"])
            ?? stringValue(json["participant_id"])
            ?? ""
        let createdAt = dateFromTs(json["created_at"])
            ?? dateFromTs(json["intent_base_time"] ?? json["base_time"])
        let edgeNodeId = stringValue(json["edge_node_id"])
            ?? stringValue(json["assigned_edge_id"])
            ?? stringValue(json["scheduler_node"])
        let reply = stringValue(json["reply"])
        let presentation = IntentPresentation.parse(json["presentation"])
        // Production shared bag is `ctx_param` only.
        var context = parseStringMap(json["ctx_param"])
        if context.isEmpty {
            context = parseStringMap(json["context"])
        }
        let stepOutputs = parseStepOutputsBag(json["step_outputs"])
        let stepLog = parseStepLog(json["step_log"])
        let planSteps = parsePlanSteps(
            json["execution_plan"],
            context: context,
            stepOutputs: stepOutputs,
            stepLog: stepLog
        )
        // Plan steps may lead dispatched → running. Job-level intent_status is
        // the only terminal signal; all capability steps done ≠ intent succeeded
        // (Brain may still be assembling presentation).
        let status = phaseFromPlanSteps(planSteps, fallback: wireStatus)
        let error = resolveError(
            json: json,
            status: status,
            planSteps: planSteps
        )
        var steps: [IntentJobStep] = parseStatusLog(json["status_log"])
        if steps.isEmpty, let arr = json["steps"] as? [[String: Any]] {
            for s in arr {
                let raw = stringValue(s["intent_status"])
                    ?? stringValue(s["status"])
                    ?? ""
                guard let phase = IntentPhase.fromWire(raw) else { continue }
                steps.append(
                    IntentJobStep(
                        status: phase,
                        at: dateFromTs(s["at"] ?? s["ts"]),
                        detail: stringValue(s["detail"]) ?? stringValue(s["msg"]) ?? ""
                    )
                )
            }
        }
        // Detail / POST often omit steps[] — synthesize from current status.
        if steps.isEmpty {
            var detail = reply ?? ""
            if !planSteps.isEmpty {
                // Keep phase detail short; full plan is shown line-by-line in the UI.
                let count = planSteps.count
                let hint = "\(count) step\(count == 1 ? "" : "s")"
                detail = detail.isEmpty ? hint : "\(detail) · \(hint)"
            }
            steps = [
                IntentJobStep(
                    status: status,
                    at: Date(),
                    detail: detail
                ),
            ]
        }
        return IntentJobSnapshot(
            jobId: jobId,
            status: status,
            wireStatus: wireStatus,
            text: text,
            source: source,
            issuerId: issuerId,
            createdAt: createdAt,
            edgeNodeId: edgeNodeId,
            error: error,
            reply: reply,
            presentation: presentation,
            steps: steps,
            planSteps: planSteps
        )
    }

    /// Map numeric plan step status → logistics phase when whole-job status lags.
    /// Never invent succeeded/failed: Intent Source only treats the job as done
    /// when Brain `intent_status` is succeeded or failed.
    static func phaseFromPlanSteps(
        _ planSteps: [IntentPlanStepItem],
        fallback: IntentPhase
    ) -> IntentPhase {
        if fallback.isTerminal {
            return fallback
        }
        guard !planSteps.isEmpty else { return fallback }
        let anyStarted = planSteps.contains {
            $0.runStatus == .running
                || $0.runStatus == .succeeded
                || $0.runStatus == .failed
                || $0.runStatus == .skipped
        }
        if anyStarted, fallback.rank < IntentPhase.running.rank {
            return .running
        }
        return fallback
    }

    private static func parseStringMap(_ raw: Any?) -> [String: String] {
        guard let dict = raw as? [String: Any] else { return [:] }
        var out: [String: String] = [:]
        for (k, v) in dict {
            let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, let s = displayValue(v), !s.isEmpty else { continue }
            out[key] = s
        }
        return out
    }

    private static func parseStepOutputsBag(_ raw: Any?) -> [String: [String: String]] {
        guard let dict = raw as? [String: Any] else { return [:] }
        var out: [String: [String: String]] = [:]
        for (k, v) in dict {
            let bag = parseStringMap(v)
            guard !bag.isEmpty else { continue }
            out[k.trimmingCharacters(in: .whitespacesAndNewlines)] = bag
        }
        return out
    }

    private static func parseStepLog(_ raw: Any?) -> [IntentStepEvent] {
        guard let arr = raw as? [Any] else { return [] }
        var events: [IntentStepEvent] = []
        for item in arr {
            guard let row = item as? [String: Any] else { continue }
            let step: Int = {
                if let n = row["step"] as? Int { return n }
                if let n = row["step"] as? NSNumber { return n.intValue }
                if let s = stringValue(row["step"]), let n = Int(s) { return n }
                return 0
            }()
            guard step > 0 else { continue }
            let status: Int? = {
                let raw = row["status"] ?? row["step_status"]
                if let i = raw as? Int { return i }
                if let n = raw as? NSNumber { return n.intValue }
                if let s = stringValue(raw), let i = Int(s) { return i }
                return nil
            }()
            events.append(
                IntentStepEvent(
                    step: step,
                    status: status,
                    msg: displayValue(row["msg"])
                        ?? displayValue(row["message"])
                        ?? displayValue(row["detail"])
                        ?? "",
                    at: dateFromTs(row["ts"] ?? row["at"])
                )
            )
        }
        return events
    }

    private static func parseStatusLog(_ raw: Any?) -> [IntentJobStep] {
        guard let arr = raw as? [[String: Any]], !arr.isEmpty else { return [] }
        var steps: [IntentJobStep] = []
        for s in arr {
            let rawStatus = stringValue(s["status"]) ?? stringValue(s["intent_status"]) ?? ""
            guard let phase = IntentPhase.fromWire(rawStatus) else { continue }
            steps.append(
                IntentJobStep(
                    status: phase,
                    at: dateFromTs(s["ts"] ?? s["at"]),
                    detail: stringValue(s["msg"]) ?? stringValue(s["detail"]) ?? ""
                )
            )
        }
        return steps
    }

    private static func resolveError(
        json: [String: Any],
        status: IntentPhase,
        planSteps: [IntentPlanStepItem]
    ) -> String? {
        let explicit = stringValue(json["error"])
            ?? stringValue(json["fail_reason"])
            ?? stringValue(json["failure_reason"])
        if let explicit, !explicit.isEmpty { return explicit }
        let failed = planSteps.filter { $0.runStatus == .failed }
        if !failed.isEmpty {
            return failed.map { item in
                let detail = item.runDetail.trimmingCharacters(in: .whitespacesAndNewlines)
                if detail.isEmpty {
                    return "step \(item.step) \(item.capability) 失败"
                }
                return "step \(item.step) \(item.capability)：\(detail)"
            }.joined(separator: "\n")
        }
        if status == .failed {
            if let msg = stringValue(json["msg"]) ?? stringValue(json["message"]),
               !msg.isEmpty {
                return msg
            }
            return "意图失败，服务端未返回失败原因"
        }
        return nil
    }

    private static func parsePlanSteps(
        _ raw: Any?,
        context: [String: String] = [:],
        stepOutputs: [String: [String: String]] = [:],
        stepLog: [IntentStepEvent] = []
    ) -> [IntentPlanStepItem] {
        guard let plan = raw as? [[String: Any]], !plan.isEmpty else { return [] }
        let eventsByStep: [Int: [IntentStepEvent]] = Dictionary(grouping: stepLog, by: \.step)
        var items: [IntentPlanStepItem] = []
        for (idx, row) in plan.enumerated() {
            let capabilityRaw = stringValue(row["capability"]) ?? ""
            let capability = normalizePlanCapabilityId(capabilityRaw)
            guard !capability.isEmpty else { continue }
            let stepNum: Int = {
                if let n = row["step"] as? Int { return n }
                if let n = row["step"] as? NSNumber { return n.intValue }
                return idx + 1
            }()
            let runStatus = planStepRunStatus(from: row)
            let wireCode = planStepStatusCode(from: row)
            let inputs = resolvePlaceholders(parseStepInputs(row), context: context)
            var outputs = parseStepOutputs(row)
            // Surface context keys declared by this step's output_constrict when realized.
            if let constrict = row["output_constrict"] as? [String: Any] {
                for key in constrict.keys {
                    let k = key.trimmingCharacters(in: .whitespacesAndNewlines)
                    if let v = context[k], !v.isEmpty {
                        outputs[k] = v
                    }
                }
            }
            if let bag = stepOutputs[String(stepNum)] ?? stepOutputs["\(stepNum)"] {
                for (k, v) in bag where !v.isEmpty {
                    if outputs[k] == nil || IntentPlanStepItem.isSchemaPlaceholder(outputs[k] ?? "") {
                        outputs[k] = v
                    }
                }
            }
            let assignedEdge = stringValue(row["assigned_edge_id"]) ?? ""
            let events = eventsByStep[stepNum] ?? []
            let runDetail = resolveStepRunDetail(
                row: row,
                runStatus: runStatus,
                events: events
            )
            var parts: [String] = []
            if !assignedEdge.isEmpty {
                parts.append("edge=\(assignedEdge)")
            }
            if let timing = formatExecutionTiming(row["execution_timing"]) {
                parts.append(timing)
            }
            if !inputs.isEmpty {
                parts.append("in[\(inputs.keys.sorted().joined(separator: ","))]")
            }
            let realizedKeys = outputs.filter { !IntentPlanStepItem.isSchemaPlaceholder($0.value) }.keys.sorted()
            if !realizedKeys.isEmpty {
                parts.append("out[\(realizedKeys.joined(separator: ","))]")
            }
            items.append(
                IntentPlanStepItem(
                    index: idx,
                    step: stepNum,
                    capability: capability,
                    summary: parts.joined(separator: " · "),
                    inputs: inputs,
                    outputs: outputs,
                    runStatus: runStatus,
                    runDetail: runDetail,
                    assignedEdge: assignedEdge,
                    events: events,
                    wireStatusCode: wireCode
                )
            )
        }
        return items
    }

    private static func resolveStepRunDetail(
        row: [String: Any],
        runStatus: IntentPlanStepRunStatus,
        events: [IntentStepEvent]
    ) -> String {
        if let msg = displayValue(row["msg"]) ?? displayValue(row["message"]) ?? displayValue(row["error"]),
           !msg.isEmpty {
            return msg
        }
        if let last = events.reversed().first(where: { !$0.msg.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) {
            return last.msg
        }
        if runStatus == .failed {
            return "失败（step_status=3），服务端未返回失败原因"
        }
        return ""
    }

    private static func formatExecutionTiming(_ raw: Any?) -> String? {
        guard let timing = raw as? [String: Any] else { return nil }
        let mode = (stringValue(timing["mode"]) ?? "").lowercased()
        switch mode {
        case "interval":
            let interval = stringValue(timing["interval_sec"]) ?? stringValue(timing["interval"])
            let count = stringValue(timing["count"])
            var parts: [String] = ["interval"]
            if let interval, !interval.isEmpty { parts.append("每\(interval)s") }
            if let count, !count.isEmpty { parts.append("×\(count)") }
            return parts.joined(separator: " ")
        case "delay":
            if let sec = stringValue(timing["delay_sec"]) ?? stringValue(timing["delay"]) {
                return "delay \(sec)s"
            }
            return "delay"
        case "immediate", "":
            return nil
        default:
            return mode
        }
    }

    /// `input_constrict` plus common top-level input fields on the step.
    private static func parseStepInputs(_ row: [String: Any]) -> [String: String] {
        var inputs: [String: String] = [:]
        if let constrict = row["input_constrict"] as? [String: Any] {
            for (k, v) in constrict {
                let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !key.isEmpty, let s = displayValue(v), !s.isEmpty else { continue }
                inputs[key] = s
            }
        }
        for key in ["photo_url", "song", "artist", "album"] {
            if inputs[key] == nil, let v = displayValue(row[key]), !v.isEmpty {
                inputs[key] = v
            }
        }
        return inputs
    }

    /// Realized `outputs` values, else declared `output_constrict` keys (schema preview).
    private static func parseStepOutputs(_ row: [String: Any]) -> [String: String] {
        var outputs: [String: String] = [:]
        if let realized = row["outputs"] as? [String: Any] {
            for (k, v) in realized {
                let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !key.isEmpty, let s = displayValue(v), !s.isEmpty else { continue }
                outputs[key] = s
            }
        }
        if let constrict = row["output_constrict"] as? [String: Any] {
            for (k, meta) in constrict {
                let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !key.isEmpty else { continue }
                if outputs[key] != nil { continue }
                if let obj = meta as? [String: Any] {
                    let dest = stringValue(obj["data_dest"]) ?? ""
                    let type = stringValue(obj["type"]) ?? "string"
                    if dest.isEmpty {
                        outputs[key] = "(\(type))"
                    } else {
                        outputs[key] = "(\(type) → \(dest))"
                    }
                } else {
                    outputs[key] = "(declared)"
                }
            }
        }
        // Top-level photo_url after bind is an output for camera.capture readers.
        if outputs["photo_url"] == nil || IntentPlanStepItem.isSchemaPlaceholder(outputs["photo_url"] ?? ""),
           let v = stringValue(row["photo_url"]),
           v.lowercased().hasPrefix("http") {
            outputs["photo_url"] = v
        }
        return outputs
    }

    /// Resolve whole-value `$name` / `${name}` for UI display from intent context.
    private static func resolvePlaceholders(
        _ values: [String: String],
        context: [String: String]
    ) -> [String: String] {
        guard !context.isEmpty else { return values }
        var out = values
        for (k, raw) in values {
            let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            let name: String?
            if value.hasPrefix("${"), value.hasSuffix("}"), value.count > 3 {
                name = String(value.dropFirst(2).dropLast())
            } else if value.hasPrefix("$"), value.count > 1,
                      !value.dropFirst().contains("$") {
                name = String(value.dropFirst())
            } else {
                name = nil
            }
            if let name, let resolved = context[name], !resolved.isEmpty {
                out[k] = resolved
            }
        }
        return out
    }

    /// Brain `execution_plan[].status` / `step_status`: 0 waiting · 1 running · 2 ok · 3 fail.
    private static func planStepStatusCode(from row: [String: Any]) -> Int? {
        let raw = row["status"] ?? row["step_status"]
        if let i = raw as? Int { return i }
        if let n = raw as? NSNumber { return n.intValue }
        if let s = stringValue(raw), let i = Int(s) { return i }
        return nil
    }

    private static func planStepRunStatus(from row: [String: Any]) -> IntentPlanStepRunStatus {
        switch planStepStatusCode(from: row) {
        case 1: return .running
        case 2: return .succeeded
        case 3: return .failed
        default: return .waiting
        }
    }

    private static func normalizePlanCapabilityId(_ id: String) -> String {
        id.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// Merge local + server plan rows; keep the more advanced runStatus.
    static func mergePlanStepProgress(
        existing: [IntentPlanStepItem],
        incoming: [IntentPlanStepItem]
    ) -> [IntentPlanStepItem] {
        guard !incoming.isEmpty else { return existing }
        guard !existing.isEmpty else { return incoming }
        var usedExisting = Set<Int>()
        return incoming.map { item in
            var copy = item
            let prior: IntentPlanStepItem? = {
                if let idx = existing.firstIndex(where: {
                    !usedExisting.contains($0.index) && $0.capability == item.capability
                }) {
                    usedExisting.insert(existing[idx].index)
                    return existing[idx]
                }
                if item.index < existing.count,
                   existing[item.index].capability == item.capability
                {
                    return existing[item.index]
                }
                return nil
            }()
            guard let prior else { return copy }
            copy.runStatus = preferredRunStatus(prior.runStatus, item.runStatus)
            if copy.runDetail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                copy.runDetail = prior.runDetail
            }
            copy.inputs = mergeStringMap(prior: prior.inputs, incoming: item.inputs)
            copy.outputs = mergeStringMap(prior: prior.outputs, incoming: item.outputs)
            copy.assignedEdge = item.assignedEdge.isEmpty ? prior.assignedEdge : item.assignedEdge
            copy.events = mergeStepEvents(prior.events, item.events)
            copy.wireStatusCode = item.wireStatusCode ?? prior.wireStatusCode
            copy.startedAt = prior.startedAt ?? item.startedAt
            if copy.runStatus.isTerminal {
                copy.finishedAt = prior.finishedAt ?? item.finishedAt ?? Date()
            } else {
                copy.finishedAt = prior.finishedAt ?? item.finishedAt
            }
            return copy
        }
    }

    private static func mergeStepEvents(
        _ prior: [IntentStepEvent],
        _ incoming: [IntentStepEvent]
    ) -> [IntentStepEvent] {
        var seen = Set<String>()
        var out: [IntentStepEvent] = []
        for event in prior + incoming {
            if seen.contains(event.identityKey) { continue }
            seen.insert(event.identityKey)
            out.append(event)
        }
        return out.sorted { ($0.at ?? .distantPast) < ($1.at ?? .distantPast) }
    }

    /// Prefer concrete values over schema placeholders like `(string → context)`.
    fileprivate static func mergeStringMap(
        prior: [String: String],
        incoming: [String: String]
    ) -> [String: String] {
        var out = prior
        for (k, v) in incoming {
            let trimmed = v.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let old = out[k]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let oldIsSchema = old.hasPrefix("(") && old.hasSuffix(")")
            let newIsSchema = trimmed.hasPrefix("(") && trimmed.hasSuffix(")")
            if old.isEmpty || (oldIsSchema && !newIsSchema) || (!newIsSchema && trimmed != old) {
                out[k] = trimmed
            } else if out[k] == nil {
                out[k] = trimmed
            }
        }
        return out
    }

    private static func preferredRunStatus(
        _ a: IntentPlanStepRunStatus,
        _ b: IntentPlanStepRunStatus
    ) -> IntentPlanStepRunStatus {
        if a == .failed || b == .failed { return .failed }
        if a == .succeeded || b == .succeeded { return .succeeded }
        if a == .skipped || b == .skipped { return .skipped }
        func rank(_ s: IntentPlanStepRunStatus) -> Int {
            switch s {
            case .waiting: return 0
            case .queued: return 1
            case .running: return 2
            case .succeeded, .failed, .skipped: return 3
            }
        }
        return rank(a) >= rank(b) ? a : b
    }

    /// True when JSON looks successful but has no `intent_id` / `id`.
    static func isSuccessWithoutIntentId(_ jsonText: String) -> Bool {
        let body = stripTimingSuffix(jsonText)
        guard let data = body.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return false }
        if stringValue(obj["intent_id"]) != nil
            || stringValue(obj["intentId"]) != nil
            || stringValue(obj["id"]) != nil
        {
            return false
        }
        if let ok = obj["ok"] as? Bool { return ok }
        if let okNum = obj["ok"] as? NSNumber { return okNum.boolValue }
        return stringValue(obj["reply"]) != nil || stringValue(obj["text"]) != nil
    }

    private static func stringValue(_ v: Any?) -> String? {
        switch v {
        case let s as String:
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        case let n as NSNumber:
            if CFGetTypeID(n) == CFBooleanGetTypeID() {
                return n.boolValue ? "true" : "false"
            }
            return n.stringValue
        default:
            return nil
        }
    }

    /// Nested JSON (dicts/arrays) as compact text for input/output display.
    private static func displayValue(_ v: Any?) -> String? {
        if let s = stringValue(v) { return s }
        if v is NSNull || v == nil { return nil }
        if let dict = v as? [String: Any],
           JSONSerialization.isValidJSONObject(dict),
           let data = try? JSONSerialization.data(withJSONObject: dict),
           let s = String(data: data, encoding: .utf8) {
            return s
        }
        if let arr = v as? [Any],
           JSONSerialization.isValidJSONObject(arr),
           let data = try? JSONSerialization.data(withJSONObject: arr),
           let s = String(data: data, encoding: .utf8) {
            return s
        }
        return nil
    }

    private static func dateFromTs(_ raw: Any?) -> Date? {
        let n: Double? = {
            if let d = raw as? Double { return d }
            if let i = raw as? Int { return Double(i) }
            if let num = raw as? NSNumber { return num.doubleValue }
            if let s = raw as? String, let d = Double(s) { return d }
            return nil
        }()
        guard let n, n > 0 else { return nil }
        if n >= 1_000_000_000_000 {
            return Date(timeIntervalSince1970: n / 1000.0)
        }
        return Date(timeIntervalSince1970: n)
    }

    private static func stripTimingSuffix(_ text: String) -> String {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false)
        guard let last = lines.last, last.hasPrefix("⏱") else { return text }
        return lines.dropLast().joined(separator: "\n")
    }
}

struct IntentJourney: Equatable {
    var jobId: String
    var text: String
    var phases: [IntentPhaseState]
    var current: IntentPhase
    var terminal: Bool
    var timedOut: Bool
    var edgeNodeId: String?
    var error: String?
    var reply: String?
    /// Brain-assembled user-facing result; Endpoint renders this, not step_outputs.
    var presentation: IntentPresentation?
    /// Capability rows from execution_plan (one line per step in UI).
    var planSteps: [IntentPlanStepItem]
    /// True before the first POST; all logistics steps stay pending.
    var idle: Bool

    /// Wire status string for header (e.g. intent_parsed).
    var currentWireStatus: String { current.wireValue }

    /// Empty logistics track shown on the home screen before an intent is sent.
    static var idlePlaceholder: IntentJourney {
        IntentJourney(
            jobId: "",
            text: "",
            phases: blankPhases(),
            current: .uploaded,
            terminal: false,
            timedOut: false,
            edgeNodeId: nil,
            error: nil,
            reply: nil,
            presentation: nil,
            planSteps: [],
            idle: true
        )
    }

    static func hydrated(from snapshot: IntentJobSnapshot) -> IntentJourney {
        let displayStatus = snapshot.wireStatus.isTerminal ? snapshot.wireStatus : snapshot.status
        var journey = make(
            jobId: snapshot.jobId,
            text: snapshot.text,
            status: displayStatus
        )
        journey.reply = snapshot.reply
        journey.presentation = snapshot.presentation
        journey.apply(
            status: displayStatus,
            steps: snapshot.steps,
            edgeNodeId: snapshot.edgeNodeId,
            error: snapshot.error
        )
        journey.planSteps = snapshot.planSteps
        return journey
    }

    static func make(jobId: String, text: String, status: IntentPhase) -> IntentJourney {
        var journey = IntentJourney(
            jobId: jobId,
            text: text,
            phases: Self.blankPhases(),
            current: status,
            terminal: status.isTerminal,
            timedOut: false,
            edgeNodeId: nil,
            error: nil,
            reply: nil,
            presentation: nil,
            planSteps: [],
            idle: false
        )
        journey.apply(status: status, steps: [], edgeNodeId: nil, error: nil)
        return journey
    }

    /// Apply server/local status. Builds logistics visuals from current phase rank
    /// (prior steps = done / green, current = active / yellow, later = pending / gray).
    mutating func apply(
        status: IntentPhase,
        steps: [IntentJobStep],
        edgeNodeId: String?,
        error: String?,
        failedAt: IntentPhase? = nil
    ) {
        current = status
        terminal = status.isTerminal
        timedOut = false
        if let edgeNodeId { self.edgeNodeId = edgeNodeId }
        if let error, !error.isEmpty {
            let prior = (self.error ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if prior.isEmpty || error.count >= prior.count {
                self.error = error
            }
        }

        let detailByPhase: [IntentPhase: String] = {
            var map: [IntentPhase: String] = [:]
            for s in steps {
                if !s.detail.isEmpty { map[s.status] = s.detail }
            }
            return map
        }()
        let atByPhase: [IntentPhase: Date] = {
            var map: [IntentPhase: Date] = [:]
            for s in steps {
                if let at = s.at { map[s.status] = at }
            }
            return map
        }()
        let previousAt: [IntentPhase: Date] = Dictionary(
            uniqueKeysWithValues: phases.compactMap { p in
                guard let at = p.at else { return nil }
                return (p.phase, at)
            }
        )
        let now = Date()

        let failAnchor = failedAt ?? (status == .failed ? .succeeded : nil)
        let curRank: Int = {
            if status == .failed, let failAnchor {
                return failAnchor.rank
            }
            return status.rank
        }()

        phases = IntentPhase.timelineOrder.map { phase in
            let visual: IntentPhaseVisualState
            if status == .failed {
                if phase.rank < curRank {
                    visual = .done
                } else if phase.rank == curRank || phase == .succeeded {
                    visual = .failed
                } else {
                    visual = .pending
                }
            } else if phase.rank < curRank {
                visual = .done
            } else if phase.rank == curRank {
                visual = status.isTerminal ? .done : .active
            } else {
                visual = .pending
            }

            var detail = detailByPhase[phase] ?? ""
            if status == .failed, phase.rank == curRank || phase == .succeeded {
                detail = error ?? detail
            }
            if phase == .assigned, let edgeNodeId, !edgeNodeId.isEmpty, detail.isEmpty {
                detail = "node: \(edgeNodeId)"
            }
            // Mark completed prior steps with a light default so the timeline reads as a path.
            if visual == .done, detail.isEmpty {
                detail = "已完成"
            }
            let at: Date? = {
                // Freeze once recorded so poll refreshes don't rewrite the clock.
                if let t = previousAt[phase] { return t }
                if let t = atByPhase[phase] { return t }
                // Local stamp when a phase first becomes reached (server often omits per-step times).
                switch visual {
                case .done, .active, .failed, .timedOut:
                    return now
                case .pending:
                    return nil
                }
            }()
            return IntentPhaseState(
                phase: phase,
                visual: visual,
                detail: detail,
                at: at,
                durationSeconds: nil
            )
        }
        Self.fillPhaseDurations(&phases, now: now)
    }

    /// Done/failed: time until next stamped phase (else freeze at `now`). Active: snapshot; UI also live-refreshes.
    private static func fillPhaseDurations(
        _ phases: inout [IntentPhaseState],
        now: Date
    ) {
        for i in phases.indices {
            guard let start = phases[i].at else {
                phases[i].durationSeconds = nil
                continue
            }
            switch phases[i].visual {
            case .pending:
                phases[i].durationSeconds = nil
            case .active, .timedOut:
                phases[i].durationSeconds = max(0, now.timeIntervalSince(start))
            case .done, .failed:
                let nextAt = phases.dropFirst(i + 1).compactMap(\.at).first ?? now
                phases[i].durationSeconds = max(0, nextAt.timeIntervalSince(start))
            }
        }
    }

    /// Total elapsed from first stamped phase to now (or last terminal stamp).
    func totalElapsedSeconds(now: Date = Date()) -> TimeInterval? {
        let stamps = phases.compactMap(\.at)
        guard let first = stamps.first else { return nil }
        let end: Date
        if terminal, let last = stamps.last {
            end = last
        } else {
            end = now
        }
        return max(0, end.timeIntervalSince(first))
    }

    mutating func markTimedOut() {
        guard !terminal else { return }
        timedOut = true
        if let idx = phases.firstIndex(where: { $0.visual == .active }) {
            phases[idx].visual = .timedOut
            if phases[idx].detail.isEmpty || phases[idx].detail == "已完成" {
                phases[idx].detail = "等待中/超时"
            }
        }
    }

    private static func blankPhases() -> [IntentPhaseState] {
        IntentPhase.timelineOrder.map {
            IntentPhaseState(phase: $0, visual: .pending, detail: "", at: nil, durationSeconds: nil)
        }
    }

    static func formatDuration(_ seconds: TimeInterval) -> String {
        if seconds < 1 {
            return String(format: "%.0fms", seconds * 1000)
        }
        if seconds < 10 {
            return String(format: "%.1fs", seconds)
        }
        if seconds < 60 {
            return String(format: "%.0fs", seconds)
        }
        let m = Int(seconds) / 60
        let s = Int(seconds) % 60
        return "\(m)m\(s)s"
    }
}

@MainActor
final class IntentJourneyStore: ObservableObject {
    @Published private(set) var activeJourney: IntentJourney?
    @Published private(set) var polling: Bool = false

    private var pollTask: Task<Void, Never>?
    /// Phone is an intent source only: poll Brain every 5s until terminal.
    private let pollIntervalNs: UInt64 = 5_000_000_000
    private let timeoutSeconds: TimeInterval = 600
    /// Reset idle timeout whenever detail shows progress (running / new wire status).
    private var lastProgressAt: Date?

    /// Show timeline immediately on send (before server returns intent_id).
    func startOptimistic(text: String) {
        stopPolling()
        activeJourney = IntentJourney.make(
            jobId: "pending…",
            text: text,
            status: .uploaded
        )
    }

    func markLegacyServerMissingJob(detail: String) {
        guard var journey = activeJourney else { return }
        journey.apply(
            status: .uploaded,
            steps: [
                IntentJobStep(status: .uploaded, at: Date(), detail: detail),
            ],
            edgeNodeId: nil,
            error: detail
        )
        if let idx = journey.phases.firstIndex(where: { $0.phase == .uploaded }) {
            journey.phases[idx].visual = .timedOut
            journey.phases[idx].detail = detail
        }
        journey.timedOut = true
        activeJourney = journey
    }

    func startFromPost(_ snapshot: IntentJobSnapshot) {
        // Always start a clean timeline (Brain often reuses numeric intent_id=1).
        stopPolling()
        var journey = IntentJourney.make(
            jobId: snapshot.jobId,
            text: snapshot.text.isEmpty ? "" : snapshot.text,
            status: snapshot.status
        )
        journey.reply = snapshot.reply
        journey.presentation = snapshot.presentation
        journey.apply(
            status: snapshot.status,
            steps: snapshot.steps,
            edgeNodeId: snapshot.edgeNodeId,
            error: snapshot.error
        )
        // Do not merge prior journey planSteps — that would keep old step=succeeded.
        journey.planSteps = snapshot.planSteps
        activeJourney = journey
        NSLog(
            "[IntentJourneyStore] startFromPost intent_id=%@ status=%@ planSteps=%d",
            snapshot.jobId,
            snapshot.status.wireValue,
            snapshot.planSteps.count
        )
    }

    func applyServerJob(_ snapshot: IntentJobSnapshot) {
        guard var journey = activeJourney, journey.jobId == snapshot.jobId else {
            startFromPost(snapshot)
            return
        }
        // Same intent_id reused after a finished run: early wire statuses mean a new job.
        if journey.terminal, Self.looksLikeNewIntentLifecycle(snapshot) {
            NSLog(
                "[IntentJourneyStore] reset terminal journey for reused intent_id=%@ wire=%@",
                snapshot.jobId,
                snapshot.status.wireValue
            )
            startFromPost(snapshot)
            return
        }
        if !snapshot.text.isEmpty {
            journey.text = snapshot.text
        }
        if let reply = snapshot.reply, !reply.isEmpty {
            journey.reply = reply
        }
        if let pres = snapshot.presentation {
            journey.presentation = pres
        }
        if !snapshot.planSteps.isEmpty {
            journey.planSteps = IntentJobSnapshot.mergePlanStepProgress(
                existing: journey.planSteps,
                incoming: snapshot.planSteps
            )
        }
        // Prefer elevated phase from plan step 0/1/2/3 over lagging intent_dispatched.
        // Do not invent terminal from plan: Brain may still be running after the last capability.
        let elevated = IntentJobSnapshot.phaseFromPlanSteps(
            journey.planSteps,
            fallback: snapshot.wireStatus
        )
        // A locally invented succeeded/failed must yield if Brain still says running.
        let wireStillOpen = !snapshot.wireStatus.isTerminal
        if journey.terminal, wireStillOpen {
            NSLog(
                "[IntentJourneyStore] reopen invented terminal intent_id=%@ wire=%@",
                snapshot.jobId,
                snapshot.wireStatus.wireValue
            )
        } else if journey.terminal, !elevated.isTerminal {
            activeJourney = journey
            return
        }
        if !wireStillOpen || !journey.terminal {
            if journey.current.rank > elevated.rank, !elevated.isTerminal {
                let reopenForLaterStep = elevated == .running
                    && journey.current == .succeeded
                    && journey.planSteps.contains { !$0.runStatus.isTerminal }
                if !reopenForLaterStep {
                    activeJourney = journey
                    return
                }
            }
        }
        if elevated != snapshot.status {
            NSLog(
                "[IntentJourneyStore] elevate logistics intent_id=%@ wire=%@ → %@ (from plan steps)",
                snapshot.jobId,
                snapshot.status.wireValue,
                elevated.wireValue
            )
        }
        journey.apply(
            status: elevated,
            steps: snapshot.steps,
            edgeNodeId: snapshot.edgeNodeId,
            error: snapshot.error
        )
        reconcilePlanSteps(on: &journey, intentStatus: elevated)
        activeJourney = journey
        if elevated.isTerminal, snapshot.wireStatus.isTerminal {
            stopPolling()
        }
    }

    /// Brain reuses ids; these statuses indicate a brand-new intent lifecycle.
    private static func looksLikeNewIntentLifecycle(_ snapshot: IntentJobSnapshot) -> Bool {
        switch snapshot.wireStatus {
        case .uploaded, .intentParsed:
            return true
        default:
            break
        }
        // New plan rows still waiting while UI is terminal from the previous run.
        if !snapshot.planSteps.isEmpty,
           snapshot.planSteps.allSatisfy({ $0.runStatus == .waiting || $0.runStatus == .queued })
        {
            return true
        }
        return false
    }

    private func reconcilePlanSteps(on journey: inout IntentJourney, intentStatus: IntentPhase) {
        let now = Date()
        switch intentStatus {
        case .succeeded:
            // Job-level succeeded is often reported after each capability; never mass-complete
            // later waiting steps. Only close out the step that was in flight.
            for i in journey.planSteps.indices where journey.planSteps[i].runStatus == .running {
                journey.planSteps[i].runStatus = .succeeded
                if journey.planSteps[i].finishedAt == nil {
                    journey.planSteps[i].finishedAt = now
                }
            }
            if journey.planSteps.count == 1, !journey.planSteps[0].runStatus.isTerminal {
                journey.planSteps[0].runStatus = .succeeded
                if journey.planSteps[0].startedAt == nil {
                    journey.planSteps[0].startedAt = now
                }
                journey.planSteps[0].finishedAt = journey.planSteps[0].finishedAt ?? now
            }
        case .failed:
            // Only fail in-flight rows; keep earlier succeeded steps green.
            for i in journey.planSteps.indices {
                switch journey.planSteps[i].runStatus {
                case .running, .queued:
                    journey.planSteps[i].runStatus = .failed
                    journey.planSteps[i].finishedAt = journey.planSteps[i].finishedAt ?? now
                default:
                    break
                }
            }
        case .scheduled, .assigned:
            for i in journey.planSteps.indices where journey.planSteps[i].runStatus == .waiting {
                journey.planSteps[i].runStatus = .queued
                if journey.planSteps[i].startedAt == nil {
                    journey.planSteps[i].startedAt = now
                }
            }
        default:
            break
        }
    }

    func adopt(_ journey: IntentJourney) {
        stopPolling()
        activeJourney = journey
    }

    func startPolling(
        jobId: String,
        fetch: @escaping (String) async -> IntentJobSnapshot?
    ) {
        stopPolling()
        polling = true
        lastProgressAt = Date()
        let started = Date()
        pollTask = Task { [weak self] in
            // Immediate first pull so timeline reflects intent_detail ASAP.
            if let self, !Task.isCancelled, let snap = await fetch(jobId) {
                self.applyServerJob(snap)
                self.lastProgressAt = Date()
                if snap.wireStatus.isTerminal {
                    self.stopPolling()
                    return
                }
            }
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: self?.pollIntervalNs ?? 5_000_000_000)
                guard let self, !Task.isCancelled else { return }
                let idleAnchor = self.lastProgressAt ?? started
                if Date().timeIntervalSince(idleAnchor) >= self.timeoutSeconds {
                    if let j = self.activeJourney, !j.terminal {
                        var copy = j
                        copy.markTimedOut()
                        self.activeJourney = copy
                    }
                    self.stopPolling()
                    return
                }
                if let snap = await fetch(jobId) {
                    // Fetch is not cancel-aware; skip stale apply after stopPolling.
                    guard !Task.isCancelled else { return }
                    if snap.wireStatus.isTerminal {
                        self.applyServerJob(snap)
                        self.stopPolling()
                        return
                    }
                    let before = self.activeJourney?.current
                    self.applyServerJob(snap)
                    let locallyRunning = self.activeJourney?.planSteps.contains {
                        $0.runStatus == .running || $0.runStatus == .queued
                    } ?? false
                    if self.activeJourney?.current != before
                        || snap.wireStatus == .running
                        || locallyRunning
                    {
                        self.lastProgressAt = Date()
                    }
                }
            }
        }
    }

    func stopPolling() {
        pollTask?.cancel()
        pollTask = nil
        polling = false
    }

    func clear() {
        stopPolling()
        activeJourney = nil
    }
}
