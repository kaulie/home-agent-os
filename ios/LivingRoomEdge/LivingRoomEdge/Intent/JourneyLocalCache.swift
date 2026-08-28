import Foundation

/// Offline copy of progress UI fields (step_log / action timings / phase stamps).
enum JourneyLocalCache {
    private static let indexKey = "livingroom.journeyProgress.index.v1"
    private static let maxEntries = 80

    struct Record: Codable {
        var planSteps: [PlanStepRecord]
        var phases: [PhaseRecord]
        var savedAt: Date
        var clientStartedAt: Date?
        var clientFinishedAt: Date?
        var serverStartedAt: Date?
        var serverFinishedAt: Date?
    }

    struct PlanStepRecord: Codable {
        var index: Int
        var step: Int
        var capability: String
        var runStatus: String
        var runDetail: String
        var startedAt: Date?
        var finishedAt: Date?
        var assignedEdge: String
        var events: [StepEventRecord]
        var actionTimings: [ActionTimingRecord]
    }

    struct StepEventRecord: Codable {
        var step: Int
        var status: Int?
        var msg: String
        var at: Date?
        var edgeId: String?
    }

    struct ActionTimingRecord: Codable {
        var name: String
        var durationMs: Int?
        var at: Date?
    }

    struct PhaseRecord: Codable {
        var phase: String
        var visual: String
        var detail: String
        var at: Date?
        var durationSeconds: Double?
    }

    static func save(_ journey: IntentJourney) {
        let jobId = journey.jobId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !jobId.isEmpty, jobId != "pending…" else { return }
        guard !journey.planSteps.isEmpty || journey.phases.contains(where: { $0.at != nil }) else { return }
        let record = Record(
            planSteps: journey.planSteps.map(PlanStepRecord.init(item:)),
            phases: journey.phases.map(PhaseRecord.init(phase:)),
            savedAt: Date(),
            clientStartedAt: journey.clientStartedAt,
            clientFinishedAt: journey.clientFinishedAt,
            serverStartedAt: journey.serverStartedAt,
            serverFinishedAt: journey.serverFinishedAt
        )
        guard let data = try? JSONEncoder().encode(record) else { return }
        var index = loadIndex()
        index.removeAll { $0 == jobId }
        index.append(jobId)
        while index.count > maxEntries, let drop = index.first {
            index.removeFirst()
            UserDefaults.standard.removeObject(forKey: storageKey(drop))
        }
        UserDefaults.standard.set(index, forKey: indexKey)
        UserDefaults.standard.set(data, forKey: storageKey(jobId))
    }

    static func load(_ intentId: String) -> Record? {
        let key = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty,
              let data = UserDefaults.standard.data(forKey: storageKey(key)),
              let record = try? JSONDecoder().decode(Record.self, from: data)
        else { return nil }
        return record
    }

    static func snapshotDictionary(_ intentId: String) -> [String: Any]? {
        guard let record = load(intentId),
              let data = try? JSONEncoder().encode(record),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        return obj
    }

    static func clear() {
        for key in loadIndex() {
            UserDefaults.standard.removeObject(forKey: storageKey(key))
        }
        UserDefaults.standard.removeObject(forKey: indexKey)
    }

    static func enrich(_ journey: IntentJourney) -> IntentJourney {
        guard let saved = load(journey.jobId) else { return journey }
        var copy = journey
        let savedSteps = saved.planSteps.map { $0.toItem() }
        if !savedSteps.isEmpty {
            if copy.planSteps.isEmpty {
                copy.planSteps = savedSteps
            } else {
                copy.planSteps = IntentJobSnapshot.mergePlanStepProgress(
                    existing: savedSteps,
                    incoming: copy.planSteps
                )
            }
        }
        let savedPhaseStamps = saved.phases.compactMap(\.at).count
        let currentPhaseStamps = copy.phases.compactMap(\.at).count
        // Prefer live journey when it already has Brain status_log span; don't restore inflated local stamps.
        if copy.serverFinishedAt == nil, savedPhaseStamps > currentPhaseStamps {
            copy.phases = saved.phases.map { $0.toPhaseState() }
        }
        if copy.clientStartedAt == nil {
            copy.clientStartedAt = saved.clientStartedAt
        }
        if copy.clientFinishedAt == nil {
            copy.clientFinishedAt = saved.clientFinishedAt
        }
        if copy.serverStartedAt == nil {
            copy.serverStartedAt = saved.serverStartedAt
        }
        if copy.serverFinishedAt == nil {
            copy.serverFinishedAt = saved.serverFinishedAt
        }
        return copy
    }

    private static func storageKey(_ intentId: String) -> String {
        "livingroom.journeyProgress.body.\(intentId)"
    }

    private static func loadIndex() -> [String] {
        UserDefaults.standard.stringArray(forKey: indexKey) ?? []
    }
}

private extension JourneyLocalCache.PlanStepRecord {
    init(item: IntentPlanStepItem) {
        index = item.index
        step = item.step
        capability = item.capability
        runStatus = item.runStatus.label
        runDetail = item.runDetail
        startedAt = item.startedAt
        finishedAt = item.finishedAt
        assignedEdge = item.assignedEdge
        events = item.events.map(JourneyLocalCache.StepEventRecord.init(event:))
        actionTimings = item.actionTimings.map(JourneyLocalCache.ActionTimingRecord.init(timing:))
    }

    func toItem() -> IntentPlanStepItem {
        IntentPlanStepItem(
            index: index,
            step: step,
            capability: capability,
            summary: "",
            runStatus: IntentPlanStepRunStatus.fromLabel(runStatus),
            runDetail: runDetail,
            startedAt: startedAt,
            finishedAt: finishedAt,
            assignedEdge: assignedEdge,
            events: events.map { $0.toEvent(step: step) },
            actionTimings: actionTimings.map { $0.toTiming() }
        )
    }
}

private extension JourneyLocalCache.StepEventRecord {
    init(event: IntentStepEvent) {
        step = event.step
        status = event.status
        msg = event.msg
        at = event.at
        edgeId = event.edgeId
    }

    func toEvent(step: Int) -> IntentStepEvent {
        IntentStepEvent(step: step, status: status, msg: msg, at: at, edgeId: edgeId)
    }
}

private extension JourneyLocalCache.ActionTimingRecord {
    init(timing: IntentStepActionTiming) {
        name = timing.name
        durationMs = timing.durationMs
        at = timing.at
    }

    func toTiming() -> IntentStepActionTiming {
        IntentStepActionTiming(name: name, durationMs: durationMs, at: at)
    }
}

private extension JourneyLocalCache.PhaseRecord {
    init(phase: IntentPhaseState) {
        self.phase = phase.phase.rawValue
        visual = phase.visual.storageLabel
        detail = phase.detail
        at = phase.at
        durationSeconds = phase.durationSeconds
    }

    func toPhaseState() -> IntentPhaseState {
        IntentPhaseState(
            phase: IntentPhase.fromWire(phase) ?? .uploaded,
            visual: IntentPhaseVisualState.from(storageLabel: visual),
            detail: detail,
            at: at,
            durationSeconds: durationSeconds
        )
    }
}

private extension IntentPlanStepRunStatus {
    static func fromLabel(_ label: String) -> IntentPlanStepRunStatus {
        switch label {
        case "排队": return .queued
        case "执行中": return .running
        case "完成": return .succeeded
        case "失败": return .failed
        case "跳过": return .skipped
        default: return .waiting
        }
    }
}

private extension IntentPhaseVisualState {
    var storageLabel: String {
        switch self {
        case .pending: return "pending"
        case .active: return "active"
        case .done: return "done"
        case .failed: return "failed"
        case .timedOut: return "timedOut"
        }
    }

    static func from(storageLabel: String) -> IntentPhaseVisualState {
        switch storageLabel {
        case "active": return .active
        case "done": return .done
        case "failed": return .failed
        case "timedOut": return .timedOut
        default: return .pending
        }
    }
}
