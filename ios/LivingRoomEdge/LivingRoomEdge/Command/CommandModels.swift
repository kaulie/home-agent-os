import Foundation

enum ScheduleSpec: Equatable {
    case instant
    case cron(expression: String)
    case event(eventType: String, filter: String?)

    var kind: String {
        switch self {
        case .instant: return "instant"
        case .cron: return "cron"
        case .event: return "event"
        }
    }
}

enum CommandSourceKind: String {
    case server
    case ui
    case mockPlan
}

/// One field from plan-step `output_constrict` (e.g. photo_url → context).
struct OutputConstrictField: Equatable {
    let type: String?
    let dataDest: String?

    /// Only `data_dest: "context"` is written into RuntimeContext.
    var publishesToContext: Bool {
        (dataDest ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() == "context"
    }
}

struct EdgeCommand: Equatable {
    let commandId: String
    let device: String
    let action: String
    let params: [String: String]
    let schedule: ScheduleSpec
    let source: CommandSourceKind
    let raw: [String: Any]
    /// From execution_plan[].output_constrict; empty for UI / mock.
    let outputConstrict: [String: OutputConstrictField]

    init(
        commandId: String,
        device: String,
        action: String,
        params: [String: String],
        schedule: ScheduleSpec,
        source: CommandSourceKind,
        raw: [String: Any],
        outputConstrict: [String: OutputConstrictField] = [:]
    ) {
        self.commandId = commandId
        self.device = device
        self.action = action
        self.params = params
        self.schedule = schedule
        self.source = source
        self.raw = raw
        self.outputConstrict = outputConstrict
    }

    func with(params: [String: String]) -> EdgeCommand {
        EdgeCommand(
            commandId: commandId,
            device: device,
            action: action,
            params: params,
            schedule: schedule,
            source: source,
            raw: raw,
            outputConstrict: outputConstrict
        )
    }

    static func == (lhs: EdgeCommand, rhs: EdgeCommand) -> Bool {
        lhs.commandId == rhs.commandId
            && lhs.device == rhs.device
            && lhs.action == rhs.action
            && lhs.params == rhs.params
            && lhs.schedule == rhs.schedule
            && lhs.source == rhs.source
            && lhs.outputConstrict == rhs.outputConstrict
    }
}

struct EdgeTask: Equatable {
    let taskId: String
    let commandId: String
    let skillId: String?
    let action: String
    let params: [String: String]
    let schedule: ScheduleSpec
    let targetHint: String?
    let skipReason: String?
    let outputConstrict: [String: OutputConstrictField]

    init(
        taskId: String,
        commandId: String,
        skillId: String?,
        action: String,
        params: [String: String],
        schedule: ScheduleSpec,
        targetHint: String?,
        skipReason: String?,
        outputConstrict: [String: OutputConstrictField] = [:]
    ) {
        self.taskId = taskId
        self.commandId = commandId
        self.skillId = skillId
        self.action = action
        self.params = params
        self.schedule = schedule
        self.targetHint = targetHint
        self.skipReason = skipReason
        self.outputConstrict = outputConstrict
    }
}

struct TaskExecutionResult: Equatable {
    let taskId: String
    let ok: Bool
    let message: String?
    let skipped: Bool
    let outputs: [String: String]

    init(
        taskId: String,
        ok: Bool,
        message: String?,
        skipped: Bool,
        outputs: [String: String] = [:]
    ) {
        self.taskId = taskId
        self.ok = ok
        self.message = message
        self.skipped = skipped
        self.outputs = outputs
    }
}

struct EdgeRuntimeNode: Equatable {
    let nodeId: String
    let displayName: String

    init(nodeId: String, displayName: String? = nil) {
        self.nodeId = nodeId
        self.displayName = displayName ?? nodeId
    }
}
