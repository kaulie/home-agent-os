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
        finishedAt: Date? = nil
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
    }

    func durationSeconds(now: Date = Date()) -> TimeInterval? {
        guard let start = startedAt else { return nil }
        let end = finishedAt ?? (runStatus == .running ? now : nil)
        guard let end else { return nil }
        return max(0, end.timeIntervalSince(start))
    }
}

struct IntentJobSnapshot: Equatable {
    let jobId: String
    let status: IntentPhase
    let text: String
    let edgeNodeId: String?
    let error: String?
    let reply: String?
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
        let edgeNodeId = stringValue(json["edge_node_id"])
            ?? stringValue(json["edge_id"])
        let error = stringValue(json["error"])
        let reply = stringValue(json["reply"])
        // Production shared bag is `ctx_param` only.
        let context = parseStringMap(json["ctx_param"])
        let planSteps = parsePlanSteps(json["execution_plan"], context: context)
        // Cross-edge: Brain may keep intent_status at intent_dispatched while
        // execution_plan[].status is already 1/2/3 — elevate logistics from plan.
        let status = phaseFromPlanSteps(planSteps, fallback: wireStatus)
        var steps: [IntentJobStep] = []
        if let arr = json["steps"] as? [[String: Any]] {
            for s in arr {
                let raw = stringValue(s["intent_status"])
                    ?? stringValue(s["status"])
                    ?? ""
                guard let phase = IntentPhase.fromWire(raw) else { continue }
                let at: Date?
                if let ts = s["at"] as? Double {
                    at = Date(timeIntervalSince1970: ts)
                } else if let ts = s["at"] as? Int {
                    at = Date(timeIntervalSince1970: TimeInterval(ts))
                } else {
                    at = nil
                }
                steps.append(
                    IntentJobStep(
                        status: phase,
                        at: at,
                        detail: stringValue(s["detail"]) ?? ""
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
            text: text,
            edgeNodeId: edgeNodeId,
            error: error,
            reply: reply,
            steps: steps,
            planSteps: planSteps
        )
    }

    /// Map numeric plan step status → logistics phase when whole-job status lags.
    static func phaseFromPlanSteps(
        _ planSteps: [IntentPlanStepItem],
        fallback: IntentPhase
    ) -> IntentPhase {
        guard !planSteps.isEmpty else { return fallback }
        if planSteps.contains(where: { $0.runStatus == .failed }) {
            return .failed
        }
        if planSteps.contains(where: { $0.runStatus == .running }) {
            return .running
        }
        let allDone = planSteps.allSatisfy {
            $0.runStatus == .succeeded || $0.runStatus == .skipped
        }
        if allDone {
            return .succeeded
        }
        if planSteps.contains(where: { $0.runStatus == .succeeded }),
           fallback.rank < IntentPhase.running.rank
        {
            return .running
        }
        return fallback
    }

    private static func parseStringMap(_ raw: Any?) -> [String: String] {
        guard let dict = raw as? [String: Any] else { return [:] }
        var out: [String: String] = [:]
        for (k, v) in dict {
            let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, let s = stringValue(v), !s.isEmpty else { continue }
            out[key] = s
        }
        return out
    }

    private static func parsePlanSteps(
        _ raw: Any?,
        context: [String: String] = [:]
    ) -> [IntentPlanStepItem] {
        guard let plan = raw as? [[String: Any]], !plan.isEmpty else { return [] }
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
            var parts: [String] = []
            if let edge = stringValue(row["assigned_edge_id"]),
               !edge.isEmpty {
                parts.append("edge=\(edge)")
            }
            if !inputs.isEmpty {
                parts.append("in[\(inputs.keys.sorted().joined(separator: ","))]")
            }
            if !outputs.isEmpty {
                parts.append("out[\(outputs.keys.sorted().joined(separator: ","))]")
            }
            items.append(
                IntentPlanStepItem(
                    index: idx,
                    step: stepNum,
                    capability: capability,
                    summary: parts.joined(separator: " · "),
                    inputs: inputs,
                    outputs: outputs,
                    runStatus: runStatus
                )
            )
        }
        return items
    }

    /// `input_constrict` plus common top-level input fields on the step.
    private static func parseStepInputs(_ row: [String: Any]) -> [String: String] {
        var inputs: [String: String] = [:]
        if let constrict = row["input_constrict"] as? [String: Any] {
            for (k, v) in constrict {
                let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !key.isEmpty, let s = stringValue(v), !s.isEmpty else { continue }
                inputs[key] = s
            }
        }
        for key in ["photo_url", "song", "artist", "album"] {
            if inputs[key] == nil, let v = stringValue(row[key]), !v.isEmpty {
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
                guard !key.isEmpty, let s = stringValue(v), !s.isEmpty else { continue }
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
        if outputs["photo_url"] == nil || outputs["photo_url"]?.hasPrefix("(") == true,
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
    private static func planStepRunStatus(from row: [String: Any]) -> IntentPlanStepRunStatus {
        let raw = row["status"] ?? row["step_status"]
        let code: Int? = {
            if let i = raw as? Int { return i }
            if let n = raw as? NSNumber { return n.intValue }
            if let s = stringValue(raw), let i = Int(s) { return i }
            return nil
        }()
        switch code {
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
            if !prior.runDetail.isEmpty { copy.runDetail = prior.runDetail }
            copy.inputs = mergeStringMap(prior: prior.inputs, incoming: item.inputs)
            copy.outputs = mergeStringMap(prior: prior.outputs, incoming: item.outputs)
            copy.startedAt = prior.startedAt ?? item.startedAt
            if copy.runStatus.isTerminal {
                copy.finishedAt = prior.finishedAt ?? item.finishedAt ?? Date()
            } else {
                copy.finishedAt = prior.finishedAt ?? item.finishedAt
            }
            return copy
        }
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
        case let s as String: return s
        case let n as NSNumber: return n.stringValue
        default: return nil
        }
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
    /// Capability rows from execution_plan (one line per step in UI).
    var planSteps: [IntentPlanStepItem]

    /// Wire status string for header (e.g. intent_parsed).
    var currentWireStatus: String { current.wireValue }

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
            planSteps: []
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
        if let error, !error.isEmpty { self.error = error }

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
    /// Fast while steps are running/queued so Mac cast success shows up quickly on phone.
    private let pollIntervalActiveNs: UInt64 = 1_000_000_000 // 1s
    private let pollIntervalIdleNs: UInt64 = 5_000_000_000 // 5s
    /// GoPro capture+upload+cast often exceeds 60s; keep polling while job is non-terminal.
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
        if !snapshot.planSteps.isEmpty {
            journey.planSteps = IntentJobSnapshot.mergePlanStepProgress(
                existing: journey.planSteps,
                incoming: snapshot.planSteps
            )
        }
        // Prefer elevated phase from plan step 0/1/2/3 over lagging intent_dispatched.
        let elevated = IntentJobSnapshot.phaseFromPlanSteps(
            journey.planSteps,
            fallback: snapshot.status
        )
        // Never let a lagging intent_detail / in-flight poll rewind a finished journey
        // back to intent_received / intent_dispatched (looks like stuck on 上传).
        if journey.terminal, !elevated.isTerminal {
            activeJourney = journey
            return
        }
        if journey.current.rank > elevated.rank, !elevated.isTerminal {
            let reopenForLaterStep = elevated == .running
                && journey.current == .succeeded
                && journey.planSteps.contains { !$0.runStatus.isTerminal }
            if !reopenForLaterStep {
                activeJourney = journey
                return
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
            steps: snapshot.steps.map {
                IntentJobStep(status: elevated, at: $0.at, detail: $0.detail)
            },
            edgeNodeId: snapshot.edgeNodeId,
            error: snapshot.error
        )
        reconcilePlanSteps(on: &journey, intentStatus: elevated)
        activeJourney = journey
        if elevated.isTerminal {
            stopPolling()
        }
    }

    /// Brain reuses ids; these statuses indicate a brand-new intent lifecycle.
    private static func looksLikeNewIntentLifecycle(_ snapshot: IntentJobSnapshot) -> Bool {
        switch snapshot.status {
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

    /// Local Edge marks each capability as it runs (intent_status alone is whole-job).
    func updatePlanStep(
        intentId: String,
        capability: String,
        status: IntentPlanStepRunStatus,
        detail: String? = nil,
        outputs: [String: String]? = nil
    ) {
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        let cap = capability.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty, !cap.isEmpty else { return }
        let outputPatch = (outputs ?? [:]).filter { !$0.key.isEmpty && !$0.value.isEmpty }

        if activeJourney == nil || activeJourney?.jobId != id {
            var journey = IntentJourney.make(
                jobId: id,
                text: activeJourney?.text ?? "",
                status: status == .failed ? .failed : (status == .running ? .running : .assigned)
            )
            let now = Date()
            journey.planSteps = [
                IntentPlanStepItem(
                    index: 0,
                    step: 1,
                    capability: cap,
                    summary: "",
                    outputs: outputPatch,
                    runStatus: status,
                    runDetail: detail ?? "",
                    startedAt: status == .waiting ? nil : now,
                    finishedAt: status.isTerminal ? now : nil
                ),
            ]
            lastProgressAt = Date()
            activeJourney = journey
            return
        }

        guard var journey = activeJourney else { return }

        if let idx = Self.indexForPlanStepUpdate(
            capability: cap,
            status: status,
            in: journey.planSteps
        ) {
            let current = journey.planSteps[idx].runStatus
            // Stale wait_wifi / progress after the step already finished — do not
            // spawn a second camera.capture row.
            if current.isTerminal {
                if status == .running || status == .queued { return }
                if current == .succeeded, status == .failed { return }
            }
            let now = Date()
            var row = journey.planSteps[idx]
            if row.startedAt == nil, status == .running || status == .queued || status.isTerminal {
                row.startedAt = now
            }
            if status.isTerminal, row.finishedAt == nil {
                row.finishedAt = now
            }
            row.runStatus = status
            if let detail, !detail.isEmpty {
                row.runDetail = detail
            }
            if !outputPatch.isEmpty {
                row.outputs = IntentJobSnapshot.mergeStringMap(prior: row.outputs, incoming: outputPatch)
            }
            journey.planSteps[idx] = row
        } else if !journey.planSteps.contains(where: { $0.capability == cap }) {
            // Only append when this capability is not already on the plan (e.g. synthetic).
            let next = journey.planSteps.count
            let now = Date()
            journey.planSteps.append(
                IntentPlanStepItem(
                    index: next,
                    step: next + 1,
                    capability: cap,
                    summary: "",
                    outputs: outputPatch,
                    runStatus: status,
                    runDetail: detail ?? "",
                    startedAt: (status == .waiting ? nil : now),
                    finishedAt: (status.isTerminal ? now : nil)
                )
            )
        } else {
            // Same capability already present but no safe row to update — ignore.
            return
        }
        lastProgressAt = Date()
        activeJourney = journey
    }

    /// Pick the plan row to update; never returns a succeeded row for a new `.running` wave.
    private static func indexForPlanStepUpdate(
        capability: String,
        status: IntentPlanStepRunStatus,
        in steps: [IntentPlanStepItem]
    ) -> Int? {
        if status == .running || status == .queued {
            return steps.firstIndex(where: {
                $0.capability == capability && !$0.runStatus.isTerminal
            })
        }
        if status.isTerminal {
            if let i = steps.firstIndex(where: {
                $0.capability == capability && ($0.runStatus == .running || $0.runStatus == .queued)
            }) {
                return i
            }
            return steps.firstIndex(where: {
                $0.capability == capability && !$0.runStatus.isTerminal
            })
        }
        return steps.firstIndex(where: {
            $0.capability == capability && !$0.runStatus.isTerminal
        })
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

    /// Advance logistics timeline from Edge step execution.
    /// Needed when Brain keeps whole-job status at `intent_dispatched` and only
    /// updates per-step status (cross-edge path).
    func applyLocalPhase(
        intentId: String,
        phase: IntentPhase,
        detail: String = "",
        edgeNodeId: String? = nil,
        error: String? = nil
    ) {
        NSLog(
            "[IntentJourneyStore] applyLocalPhase intent_id=%@ phase=%@",
            intentId,
            phase.wireValue
        )
        let id = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !id.isEmpty else { return }

        if activeJourney == nil || activeJourney?.jobId != id {
            var journey = IntentJourney.make(jobId: id, text: activeJourney?.text ?? "", status: phase)
            journey.apply(
                status: phase,
                steps: [IntentJobStep(status: phase, at: Date(), detail: detail)],
                edgeNodeId: edgeNodeId,
                error: error,
                failedAt: phase == .failed ? .running : nil
            )
            activeJourney = journey
            return
        }

        guard var journey = activeJourney else { return }
        if !phase.isTerminal, phase.rank < journey.current.rank {
            return
        }
        journey.apply(
            status: phase,
            steps: [IntentJobStep(status: phase, at: Date(), detail: detail)],
            edgeNodeId: edgeNodeId,
            error: error,
            failedAt: phase == .failed ? (journey.current.isTerminal ? .succeeded : journey.current) : nil
        )
        activeJourney = journey
        if phase.isTerminal {
            stopPolling()
        }
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
                if snap.status.isTerminal {
                    self.stopPolling()
                    return
                }
            }
            while !Task.isCancelled {
                let busy = self?.activeJourney?.planSteps.contains {
                    $0.runStatus == .running || $0.runStatus == .queued
                } ?? false
                let sleepNs = busy
                    ? (self?.pollIntervalActiveNs ?? 1_000_000_000)
                    : (self?.pollIntervalIdleNs ?? 5_000_000_000)
                try? await Task.sleep(nanoseconds: sleepNs)
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
                    // Fetch is not cancel-aware; skip stale apply after stopPolling/success.
                    guard !Task.isCancelled else { return }
                    if self.activeJourney?.terminal == true { return }
                    let before = self.activeJourney?.current
                    self.applyServerJob(snap)
                    let locallyRunning = self.activeJourney?.planSteps.contains {
                        $0.runStatus == .running || $0.runStatus == .queued
                    } ?? false
                    if self.activeJourney?.current != before
                        || snap.status == .running
                        || locallyRunning
                    {
                        self.lastProgressAt = Date()
                    }
                    if self.activeJourney?.terminal == true || snap.status.isTerminal {
                        self.stopPolling()
                        return
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
