import Foundation

struct DevPolicyResponse: Decodable {
    let ok: Bool?
    let error: String?
}

struct DevDevTasksResponse: Decodable {
    let ok: Bool?
    let tasks: [DevTask]
    let error: String?
    let nextBeforeId: Int?
    let exhausted: Bool?

    enum CodingKeys: String, CodingKey {
        case ok, tasks, error, exhausted
        case nextBeforeId = "next_before_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        tasks = try c.decodeIfPresent([DevTask].self, forKey: .tasks) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error)
        nextBeforeId = try c.decodeIfPresent(Int.self, forKey: .nextBeforeId)
        exhausted = try c.decodeIfPresent(Bool.self, forKey: .exhausted)
    }
}

struct DevIssuesResponse: Decodable {
    let ok: Bool?
    let issues: [DebugIssue]
    let error: String?
    let nextBeforeId: Int?
    let exhausted: Bool?

    enum CodingKeys: String, CodingKey {
        case ok, issues, error, exhausted
        case nextBeforeId = "next_before_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = try c.decodeIfPresent(Bool.self, forKey: .ok)
        issues = try c.decodeIfPresent([DebugIssue].self, forKey: .issues) ?? []
        error = try c.decodeIfPresent(String.self, forKey: .error)
        nextBeforeId = try c.decodeIfPresent(Int.self, forKey: .nextBeforeId)
        exhausted = try c.decodeIfPresent(Bool.self, forKey: .exhausted)
    }
}

struct DebugIssueResponse: Decodable {
    let ok: Bool?
    let issue: DebugIssue?
    let error: String?
}

struct DebugAttachment: Identifiable, Decodable, Equatable {
    var id: String { assetId }

    let assetId: String
    let kind: String
    let mimeType: String
    let filename: String

    enum CodingKeys: String, CodingKey {
        case assetId = "asset_id"
        case kind
        case mimeType = "mime_type"
        case filename
    }

    init(assetId: String, kind: String = "image", mimeType: String = "", filename: String = "") {
        self.assetId = assetId
        self.kind = kind
        self.mimeType = mimeType
        self.filename = filename
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        assetId = try c.decode(String.self, forKey: .assetId)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "other"
        mimeType = try c.decodeIfPresent(String.self, forKey: .mimeType) ?? ""
        filename = try c.decodeIfPresent(String.self, forKey: .filename) ?? ""
    }

    var isImage: Bool {
        kind == "image" || mimeType.lowercased().hasPrefix("image/")
    }

    var kindLabel: String {
        switch kind {
        case "image": return "图片"
        case "file": return "文件"
        case "audio": return "音频"
        case "video": return "视频"
        default: return "附件"
        }
    }

    var displayLabel: String {
        if !filename.isEmpty { return filename }
        return "\(kindLabel) · \(assetId)"
    }
}

struct DebugIssue: Identifiable, Decodable {
    var id: Int { issueId }

    let issueId: Int
    let intentId: Int
    let sessionId: String
    let source: String
    let participantId: String
    let status: String
    let userSummary: String
    let problemType: String
    let problemTypeLabel: String
    let attachments: [DebugAttachment]
    let taskId: Int?
    let error: String
    let createdAt: Date?
    let updatedAt: Date?
    let devTask: DevTask?

    var statusTitle: String {
        switch status {
        case "resolved", "succeeded": return "已解决"
        case "failed": return "失败"
        case "analyzing", "running": return "分析中"
        case "submitted": return "已提交"
        default: return status.isEmpty ? "进行中" : status
        }
    }

    var isActive: Bool {
        status == "submitted" || status == "analyzing" || status == "running"
    }

    var userInputPreview: String {
        if !feedbackPreview.isEmpty { return feedbackPreview }
        let ctx = contextUserInput
        if !ctx.isEmpty { return ctx }
        return "意图 #\(intentId)"
    }

    var feedbackPreview: String {
        let summary = userSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        if !summary.isEmpty { return summary }
        let label = problemTypeLabel.trimmingCharacters(in: .whitespacesAndNewlines)
        if !label.isEmpty { return label }
        return ""
    }

    var hasFeedbackDetail: Bool {
        !problemTypeLabel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !userSummary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var contextUserInput: String {
        guard let ctx = contextPayload else { return "" }
        return (ctx["user_input"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var contextError: String {
        guard let ctx = contextPayload else { return "" }
        return (ctx["error"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var contextIntentStatus: String {
        guard let ctx = contextPayload else { return "" }
        return (ctx["intent_status"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var contextSource: String {
        guard let ctx = contextPayload else { return "" }
        return (ctx["source"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var contextEdgeId: String {
        guard let ctx = contextPayload else { return "" }
        return (ctx["edge_id"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var clientSnapshot: [String: Any]? {
        contextPayload?["client_snapshot"] as? [String: Any]
    }

    var scenePrimaryBrainLines: [String] {
        guard let brain = clientSnapshot?["primary_brain"] as? [String: Any] else { return [] }
        return DebugIssueSceneFormat.dictLines(brain, preferredKeys: [
            "mode_label", "mode", "routing_label", "routing", "base_url", "intent_url", "path_kind",
        ])
    }

    var sceneHeartbeatLines: [String] {
        guard let heartbeat = clientSnapshot?["heartbeat"] as? [String: Any] else { return [] }
        var lines: [String] = []
        if let primary = heartbeat["primary_mode"] as? String, !primary.isEmpty {
            lines.append("Primary: \(primary)")
        }
        for key in ["lan", "cloud"] {
            guard let row = heartbeat[key] as? [String: Any], !row.isEmpty else { continue }
            let label = key.uppercased()
            let ok = (row["last_ok"] as? Bool) == true ? "ok" : "fail"
            let err = (row["last_error"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let attempt = (row["last_attempt_at"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            var line = "\(label): \(ok)"
            if !attempt.isEmpty { line += " · \(attempt)" }
            if !err.isEmpty { line += " · \(err)" }
            lines.append(line)
        }
        return lines
    }

    var sceneRuntimeLogLines: [String] {
        guard let runtime = clientSnapshot?["runtime_intent_log"] as? [String: Any] else { return [] }
        if let note = runtime["note"] as? String, runtime.count == 1 {
            return [note]
        }
        var lines: [String] = []
        if let logLines = runtime["lines"] as? [String], !logLines.isEmpty {
            lines.append(contentsOf: logLines)
        }
        if let keys = runtime["runtime_context_keys"] as? [String], !keys.isEmpty {
            lines.append("runtime context keys: \(keys.joined(separator: ", "))")
        }
        if let steps = runtime["plan_steps"] as? [[String: Any]], !steps.isEmpty {
            for step in steps {
                let cap = step["capability"] as? String ?? "?"
                let status = step["status"] as? String ?? step["runStatus"] as? String ?? "?"
                let detail = step["detail"] as? String ?? ""
                lines.append("step \(step["step"] ?? "?"): \(cap) · \(status)\(detail.isEmpty ? "" : " · \(detail)")")
            }
        }
        if lines.isEmpty {
            lines.append(contentsOf: DebugIssueSceneFormat.dictLines(runtime))
        }
        return lines
    }

    var contextStatusTimeline: [String] {
        guard let rows = contextPayload?["status_log"] as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            let status = (row["status"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !status.isEmpty else { return nil }
            if let ts = WireTime.parseAny(row["ts"]) {
                return "\(WireTime.absoluteLabel(ts)) · \(status)"
            }
            return status
        }
    }

    var contextStepLines: [String] {
        guard let rows = contextPayload?["step_log"] as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            let status = (row["status"] as? String ?? row["intent_status"] as? String ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = (row["detail"] as? String ?? row["msg"] as? String ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            if status.isEmpty && detail.isEmpty { return nil }
            if detail.isEmpty { return status }
            if status.isEmpty { return detail }
            return "\(status) — \(detail)"
        }
    }

    var contextPlanLines: [String] {
        guard let rows = contextPayload?["execution_plan"] as? [[String: Any]] else { return [] }
        return rows.compactMap { row in
            let capability = (row["capability"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !capability.isEmpty else { return nil }
            if let step = row["step"] as? Int {
                return "步骤 \(step)：\(capability)"
            }
            return capability
        }
    }

    var feedbackProblemLabel: String {
        let label = problemTypeLabel.trimmingCharacters(in: .whitespacesAndNewlines)
        if !label.isEmpty { return label }
        let summary = userSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        return summary
    }

    var feedbackDetailText: String {
        let summary = userSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        let label = problemTypeLabel.trimmingCharacters(in: .whitespacesAndNewlines)
        if summary.isEmpty || summary == label { return "" }
        return summary
    }

    private var contextPayload: [String: Any]? {
        guard let context = rawContext else { return nil }
        return context
    }

    private let rawContext: [String: Any]?

    var relativeLabel: String {
        guard let createdAt else { return "" }
        return DevRelativeTime.label(since: createdAt)
    }

    var timeLabel: String {
        guard let createdAt else { return "" }
        return WireTime.absoluteLabel(createdAt)
    }

    enum CodingKeys: String, CodingKey {
        case issueId = "issue_id"
        case intentId = "intent_id"
        case sessionId = "session_id"
        case source
        case participantId = "participant_id"
        case status
        case userSummary = "user_summary"
        case problemType = "problem_type"
        case problemTypeLabel = "problem_type_label"
        case attachments
        case attachmentAssetIds = "attachment_asset_ids"
        case taskId = "task_id"
        case error
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case context
        case devTask = "dev_task"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        issueId = try c.decode(Int.self, forKey: .issueId)
        intentId = try c.decodeIfPresent(Int.self, forKey: .intentId) ?? 0
        sessionId = try c.decodeIfPresent(String.self, forKey: .sessionId) ?? ""
        source = try c.decodeIfPresent(String.self, forKey: .source) ?? ""
        participantId = try c.decodeIfPresent(String.self, forKey: .participantId) ?? ""
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        userSummary = try c.decodeIfPresent(String.self, forKey: .userSummary) ?? ""
        problemType = try c.decodeIfPresent(String.self, forKey: .problemType) ?? ""
        problemTypeLabel = try c.decodeIfPresent(String.self, forKey: .problemTypeLabel) ?? ""
        if let rows = try c.decodeIfPresent([DebugAttachment].self, forKey: .attachments), !rows.isEmpty {
            attachments = rows
        } else if let legacyIds = try c.decodeIfPresent([String].self, forKey: .attachmentAssetIds) {
            attachments = legacyIds.map { DebugAttachment(assetId: $0, kind: "image", mimeType: "image/jpeg") }
        } else {
            attachments = []
        }
        taskId = try c.decodeIfPresent(Int.self, forKey: .taskId)
        error = try c.decodeIfPresent(String.self, forKey: .error) ?? ""
        createdAt = WireTime.decode(c, key: .createdAt)
        updatedAt = WireTime.decode(c, key: .updatedAt)
        if let nested = try? c.decode(JSONDictionary.self, forKey: .context) {
            rawContext = nested.value
        } else {
            rawContext = nil
        }
        devTask = try c.decodeIfPresent(DevTask.self, forKey: .devTask)
    }
}

struct DevTokenUsage: Decodable, Equatable {
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheWriteTokens: Int
    let totalTokens: Int

    static let empty = DevTokenUsage(
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheWriteTokens: 0,
        totalTokens: 0
    )

    var hasData: Bool { totalTokens > 0 || inputTokens > 0 || outputTokens > 0 }

    var compactLabel: String {
        guard hasData else { return "" }
        return "↑\(inputTokens.formatted()) ↓\(outputTokens.formatted()) Σ\(totalTokens.formatted())"
    }

    /// Short badge shown beside an agent reply header.
    var replyBadge: String {
        guard hasData else { return "" }
        return "Σ \(totalTokens.formatted())"
    }

    var detailTooltip: String {
        guard hasData else { return "" }
        return detailLines.joined(separator: " · ")
    }

    var detailLines: [String] {
        guard hasData else { return [] }
        var lines = [
            "输入 \(inputTokens.formatted())",
            "输出 \(outputTokens.formatted())",
            "合计 \(totalTokens.formatted())",
        ]
        if cacheReadTokens > 0 {
            lines.append("缓存读 \(cacheReadTokens.formatted())")
        }
        if cacheWriteTokens > 0 {
            lines.append("缓存写 \(cacheWriteTokens.formatted())")
        }
        return lines
    }

    enum CodingKeys: String, CodingKey {
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheReadTokens = "cache_read_tokens"
        case cacheWriteTokens = "cache_write_tokens"
        case totalTokens = "total_tokens"
    }

    init(
        inputTokens: Int,
        outputTokens: Int,
        cacheReadTokens: Int,
        cacheWriteTokens: Int,
        totalTokens: Int
    ) {
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cacheReadTokens = cacheReadTokens
        self.cacheWriteTokens = cacheWriteTokens
        self.totalTokens = totalTokens
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        inputTokens = try c.decodeIfPresent(Int.self, forKey: .inputTokens) ?? 0
        outputTokens = try c.decodeIfPresent(Int.self, forKey: .outputTokens) ?? 0
        cacheReadTokens = try c.decodeIfPresent(Int.self, forKey: .cacheReadTokens) ?? 0
        cacheWriteTokens = try c.decodeIfPresent(Int.self, forKey: .cacheWriteTokens) ?? 0
        totalTokens = try c.decodeIfPresent(Int.self, forKey: .totalTokens)
            ?? (inputTokens + outputTokens)
    }
}

struct DevTokenUsageResponse: Decodable {
    let ok: Bool?
    let usage: DevTokenUsageStats?
    let error: String?
}

struct DevTokenUsageStats: Decodable, Equatable {
    let periodKey: String?
    let periodLabel: String?
    let periodDays: Int?
    let timeGranularity: String?
    let timeSectionLabel: String?
    let period: DevTokenUsageBucket
    let allTime: DevTokenUsageBucket
    let byTime: [DevTokenUsageTimeBucket]
    let recentTasks: [DevStatsTaskUsage]

    enum CodingKeys: String, CodingKey {
        case periodKey = "period_key"
        case periodLabel = "period_label"
        case periodDays = "period_days"
        case timeGranularity = "time_granularity"
        case timeSectionLabel = "time_section_label"
        case period
        case allTime = "all_time"
        case byTime = "by_time"
        case recentTasks = "recent_tasks"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        periodKey = try c.decodeIfPresent(String.self, forKey: .periodKey)
        periodLabel = try c.decodeIfPresent(String.self, forKey: .periodLabel)
        periodDays = try c.decodeIfPresent(Int.self, forKey: .periodDays)
        timeGranularity = try c.decodeIfPresent(String.self, forKey: .timeGranularity)
        timeSectionLabel = try c.decodeIfPresent(String.self, forKey: .timeSectionLabel)
        period = try c.decodeIfPresent(DevTokenUsageBucket.self, forKey: .period) ?? .empty
        allTime = try c.decodeIfPresent(DevTokenUsageBucket.self, forKey: .allTime) ?? .empty
        byTime = try c.decodeIfPresent([DevTokenUsageTimeBucket].self, forKey: .byTime) ?? []
        recentTasks = try c.decodeIfPresent([DevStatsTaskUsage].self, forKey: .recentTasks) ?? []
    }

    init(
        periodKey: String? = nil,
        periodLabel: String? = nil,
        periodDays: Int? = nil,
        timeGranularity: String? = nil,
        timeSectionLabel: String? = nil,
        period: DevTokenUsageBucket,
        allTime: DevTokenUsageBucket,
        byTime: [DevTokenUsageTimeBucket] = [],
        recentTasks: [DevStatsTaskUsage] = []
    ) {
        self.periodKey = periodKey
        self.periodLabel = periodLabel
        self.periodDays = periodDays
        self.timeGranularity = timeGranularity
        self.timeSectionLabel = timeSectionLabel
        self.period = period
        self.allTime = allTime
        self.byTime = byTime
        self.recentTasks = recentTasks
    }

    var displayPeriodTitle: String {
        if let periodLabel, !periodLabel.isEmpty {
            return periodLabel
        }
        if let periodDays, periodDays > 0 {
            return "近 \(periodDays) 天"
        }
        return "全部"
    }
}

struct DevTokenUsageTimeBucket: Decodable, Equatable, Identifiable {
    var id: String { bucketKey }

    let bucketKey: String
    let bucketLabel: String
    let taskCount: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheWriteTokens: Int
    let totalTokens: Int

    enum CodingKeys: String, CodingKey {
        case bucketKey = "bucket_key"
        case bucketLabel = "bucket_label"
        case taskCount = "task_count"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheReadTokens = "cache_read_tokens"
        case cacheWriteTokens = "cache_write_tokens"
        case totalTokens = "total_tokens"
    }
}

struct DevTokenUsageCategoryRow: Decodable, Equatable, Identifiable {
    var id: String { category }

    let category: String
    let categoryLabel: String
    let taskCount: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheWriteTokens: Int
    let totalTokens: Int

    enum CodingKeys: String, CodingKey {
        case category
        case categoryLabel = "category_label"
        case taskCount = "task_count"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheReadTokens = "cache_read_tokens"
        case cacheWriteTokens = "cache_write_tokens"
        case totalTokens = "total_tokens"
    }
}

struct DevStatsTaskUsage: Decodable, Equatable, Identifiable {
    var id: Int { taskId }

    let taskId: Int
    let threadId: Int
    let text: String
    let status: String
    let category: String
    let categoryLabel: String
    let tokenUsage: DevTokenUsage

    enum CodingKeys: String, CodingKey {
        case taskId = "task_id"
        case threadId = "thread_id"
        case text, status, category
        case categoryLabel = "category_label"
        case tokenUsage = "token_usage"
    }
}

struct DevTokenUsageBucket: Decodable, Equatable {
    let taskCount: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheReadTokens: Int
    let cacheWriteTokens: Int
    let totalTokens: Int
    let byCategory: [DevTokenUsageCategoryRow]?

    enum CodingKeys: String, CodingKey {
        case taskCount = "task_count"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheReadTokens = "cache_read_tokens"
        case cacheWriteTokens = "cache_write_tokens"
        case totalTokens = "total_tokens"
        case byCategory = "by_category"
    }

    init(
        taskCount: Int,
        inputTokens: Int,
        outputTokens: Int,
        cacheReadTokens: Int,
        cacheWriteTokens: Int,
        totalTokens: Int,
        byCategory: [DevTokenUsageCategoryRow]?
    ) {
        self.taskCount = taskCount
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cacheReadTokens = cacheReadTokens
        self.cacheWriteTokens = cacheWriteTokens
        self.totalTokens = totalTokens
        self.byCategory = byCategory
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        taskCount = try c.decodeIfPresent(Int.self, forKey: .taskCount) ?? 0
        inputTokens = try c.decodeIfPresent(Int.self, forKey: .inputTokens) ?? 0
        outputTokens = try c.decodeIfPresent(Int.self, forKey: .outputTokens) ?? 0
        cacheReadTokens = try c.decodeIfPresent(Int.self, forKey: .cacheReadTokens) ?? 0
        cacheWriteTokens = try c.decodeIfPresent(Int.self, forKey: .cacheWriteTokens) ?? 0
        totalTokens = try c.decodeIfPresent(Int.self, forKey: .totalTokens) ?? 0
        byCategory = try c.decodeIfPresent([DevTokenUsageCategoryRow].self, forKey: .byCategory)
    }

    static let empty = DevTokenUsageBucket(
        taskCount: 0,
        inputTokens: 0,
        outputTokens: 0,
        cacheReadTokens: 0,
        cacheWriteTokens: 0,
        totalTokens: 0,
        byCategory: Optional<[DevTokenUsageCategoryRow]>.none
    )
}

struct DevTask: Identifiable, Decodable, Equatable {
    var id: Int { taskId }

    let taskId: Int
    let text: String
    let status: String
    let createdAt: Date?
    let updatedAt: Date?
    let resultText: String
    let msg: String
    let bridgeRunId: String
    let bridgeStatus: String
    let events: [DevEvent]
    let statusLog: [DevStatusEvent]
    let threadId: Int
    let parentTaskId: Int?
    let threadMessages: [DevTask]
    let category: String
    let categoryLabel: String
    let tokenUsage: DevTokenUsage
    let threadTokenUsage: DevTokenUsage
    let attachments: [DebugAttachment]
    let attachmentScope: String
    let targetHandle: String

    var isRoot: Bool { parentTaskId == nil }

    var statusTitle: String {
        switch status {
        case "succeeded", "success", "completed": return "完成"
        case "failed", "error": return "失败"
        case "cancelled": return "已中断"
        case "running", "dispatched": return "执行中"
        case "intent_parsed", "queued", "intent_received", "intent_waiting": return "排队"
        default: return status.isEmpty ? "进行中" : status
        }
    }

    var isTerminal: Bool {
        status == "succeeded" || status == "failed" || status == "error" || status == "cancelled"
    }

    var isActive: Bool { !isTerminal }

    var timeLabel: String {
        guard let createdAt else { return "" }
        return WireTime.absoluteLabel(createdAt)
    }

    var sentAtCaption: String {
        guard let createdAt else { return "" }
        return "发送于 \(WireTime.absoluteLabel(createdAt))"
    }

    /// Wall-clock time when this Dev Task reached a terminal status.
    var finishedAt: Date? {
        let terminalStatuses = Set(["succeeded", "success", "completed", "failed", "error", "cancelled"])
        if let fromLog = statusLog.last(where: { terminalStatuses.contains($0.status) })?.ts {
            return fromLog
        }
        if isTerminal, let updatedAt {
            return updatedAt
        }
        return nil
    }

    var finishedAtCaption: String {
        guard let finishedAt else { return "" }
        return "完成于 \(WireTime.absoluteLabel(finishedAt))"
    }

    var relativeLabel: String {
        guard let createdAt else { return "" }
        return DevRelativeTime.label(since: createdAt)
    }

    var displayResult: String {
        let shown = resultText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !shown.isEmpty { return shown }
        let fallback = msg.trimmingCharacters(in: .whitespacesAndNewlines)
        if !fallback.isEmpty { return fallback }
        if let last = events.last(where: { !$0.text.isEmpty }) {
            return last.text
        }
        return ""
    }

    enum CodingKeys: String, CodingKey {
        case taskId = "task_id"
        case intentId = "intent_id"
        case text, status, msg
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case finishedAt = "finished_at"
        case resultText = "result_text"
        case devTask = "dev_task"
        case statusLog = "status_log"
        case threadId = "thread_id"
        case parentTaskId = "parent_task_id"
        case threadMessages = "thread_messages"
        case category
        case categoryLabel = "category_label"
        case tokenUsage = "token_usage"
        case threadTokenUsage = "thread_token_usage"
        case attachments
        case attachmentAssetIds = "attachment_asset_ids"
        case attachmentScope = "attachment_scope"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let tid = try? c.decode(Int.self, forKey: .taskId) {
            taskId = tid
        } else if let iid = try? c.decode(Int.self, forKey: .intentId) {
            taskId = iid
        } else if let textId = try c.decodeIfPresent(String.self, forKey: .intentId), let parsed = Int(textId) {
            taskId = parsed
        } else {
            taskId = 0
        }
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
        resultText = try c.decodeIfPresent(String.self, forKey: .resultText) ?? ""
        createdAt = WireTime.decode(c, key: .createdAt)
        if let done = WireTime.decode(c, key: .finishedAt) {
            updatedAt = done
        } else {
            updatedAt = WireTime.decode(c, key: .updatedAt)
        }
        statusLog = try c.decodeIfPresent([DevStatusEvent].self, forKey: .statusLog) ?? []
        threadId = try c.decodeIfPresent(Int.self, forKey: .threadId) ?? taskId
        parentTaskId = try c.decodeIfPresent(Int.self, forKey: .parentTaskId)
        threadMessages = try c.decodeIfPresent([DevTask].self, forKey: .threadMessages) ?? []
        category = try c.decodeIfPresent(String.self, forKey: .category) ?? "other"
        categoryLabel = try c.decodeIfPresent(String.self, forKey: .categoryLabel)
            ?? DevTaskCategory.find(id: category).label
        let topLevelUsage = (try? c.decode(DevTokenUsage.self, forKey: .tokenUsage)) ?? .empty
        threadTokenUsage = (try? c.decode(DevTokenUsage.self, forKey: .threadTokenUsage)) ?? .empty
        if let rows = try c.decodeIfPresent([DebugAttachment].self, forKey: .attachments), !rows.isEmpty {
            attachments = rows
        } else if let legacyIds = try c.decodeIfPresent([String].self, forKey: .attachmentAssetIds) {
            attachments = legacyIds.map { DebugAttachment(assetId: $0, kind: "image", mimeType: "image/jpeg") }
        } else {
            attachments = []
        }
        attachmentScope = try c.decodeIfPresent(String.self, forKey: .attachmentScope)
            ?? "dev_task:\(taskId)"
        let dev = try c.decodeIfPresent(DevTaskMeta.self, forKey: .devTask) ?? DevTaskMeta()
        tokenUsage = topLevelUsage.hasData ? topLevelUsage : dev.tokenUsage
        bridgeRunId = dev.bridgeRunId
        bridgeStatus = dev.bridgeStatus
        events = dev.events
        targetHandle = dev.targetHandle
    }
}

private struct DevTaskMeta: Decodable {
    let bridgeRunId: String
    let bridgeStatus: String
    let events: [DevEvent]
    let tokenUsage: DevTokenUsage
    let targetHandle: String

    enum CodingKeys: String, CodingKey {
        case bridgeRunId = "bridge_run_id"
        case bridgeStatus = "bridge_status"
        case events
        case tokenUsage = "token_usage"
        case targetHandle = "target_handle"
    }

    init() {
        bridgeRunId = ""
        bridgeStatus = ""
        events = []
        tokenUsage = .empty
        targetHandle = ""
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bridgeRunId = try c.decodeIfPresent(String.self, forKey: .bridgeRunId) ?? ""
        bridgeStatus = try c.decodeIfPresent(String.self, forKey: .bridgeStatus) ?? ""
        events = try c.decodeIfPresent([DevEvent].self, forKey: .events) ?? []
        tokenUsage = (try? c.decode(DevTokenUsage.self, forKey: .tokenUsage)) ?? .empty
        targetHandle = try c.decodeIfPresent(String.self, forKey: .targetHandle) ?? ""
    }
}

struct DevEvent: Identifiable, Decodable, Equatable {
    var id: String { "\(type)|\(text)|\(ts?.timeIntervalSince1970 ?? 0)" }
    let type: String
    let text: String
    let ts: Date?

    enum CodingKeys: String, CodingKey {
        case type, text, ts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        type = try c.decodeIfPresent(String.self, forKey: .type) ?? ""
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        if let value = try? c.decode(Double.self, forKey: .ts), value > 10_000_000_000 {
            ts = Date(timeIntervalSince1970: value / 1000)
        } else {
            ts = WireTime.decode(c, key: .ts)
        }
    }
}

struct DevStatusEvent: Identifiable, Decodable, Equatable {
    var id: String { "\(status)|\(ts?.timeIntervalSince1970 ?? 0)|\(msg)" }
    let status: String
    let ts: Date?
    let msg: String

    enum CodingKeys: String, CodingKey {
        case status, ts, msg
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
        if let ms = try? c.decode(Double.self, forKey: .ts), ms > 10_000_000_000 {
            ts = Date(timeIntervalSince1970: ms / 1000)
        } else {
            ts = WireTime.decode(c, key: .ts)
        }
    }
}

private struct JSONDictionary: Decodable {
    let value: [String: Any]

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let dict = try? container.decode([String: JSONValue].self) {
            value = dict.mapValues(\.jsonObject) as? [String: Any] ?? [:]
            return
        }
        value = [:]
    }
}

private enum JSONValue: Decodable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
            return
        }
        if let v = try? c.decode(Bool.self) { self = .bool(v); return }
        if let v = try? c.decode(Int.self) { self = .int(v); return }
        if let v = try? c.decode(Double.self) { self = .double(v); return }
        if let v = try? c.decode(String.self) { self = .string(v); return }
        if let v = try? c.decode([String: JSONValue].self) { self = .object(v); return }
        if let v = try? c.decode([JSONValue].self) { self = .array(v); return }
        self = .null
    }

    var jsonObject: Any {
        switch self {
        case .string(let v): return v
        case .int(let v): return v
        case .double(let v): return v
        case .bool(let v): return v
        case .object(let v): return v.mapValues(\.jsonObject)
        case .array(let v): return v.map(\.jsonObject)
        case .null: return NSNull()
        }
    }
}

enum DebugIssueSceneFormat {
    static func dictLines(_ dict: [String: Any], preferredKeys: [String] = []) -> [String] {
        var lines: [String] = []
        var seen = Set<String>()
        for key in preferredKeys {
            guard let value = dict[key], !(value is NSNull) else { continue }
            let text = stringify(value)
            guard !text.isEmpty else { continue }
            lines.append("\(key): \(text)")
            seen.insert(key)
        }
        for (key, value) in dict.sorted(by: { $0.key < $1.key }) where !seen.contains(key) {
            if value is NSNull { continue }
            if key == "local_journey_cache" { continue }
            let text = stringify(value)
            guard !text.isEmpty else { continue }
            lines.append("\(key): \(text)")
        }
        return lines
    }

    private static func stringify(_ value: Any) -> String {
        if let text = value as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        if let flag = value as? Bool {
            return flag ? "true" : "false"
        }
        if value is NSNull {
            return ""
        }
        if JSONSerialization.isValidJSONObject(value),
           let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]),
           let text = String(data: data, encoding: .utf8) {
            return text.count > 240 ? String(text.prefix(240)) + "…" : text
        }
        return String(describing: value)
    }
}
