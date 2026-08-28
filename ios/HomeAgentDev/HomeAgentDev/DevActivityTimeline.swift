import SwiftUI

struct DevActivityTimeline: Decodable, Equatable {
    let threadId: Int?
    let participants: [DevActivityParticipant]
    let entries: [DevActivityEntry]
    let statusFlow: [DevActivityStatusStep]
    let roleSummaries: [DevActivityRoleSummary]

    enum CodingKeys: String, CodingKey {
        case threadId = "thread_id"
        case participants
        case entries
        case statusFlow = "status_flow"
        case roleSummaries = "role_summaries"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        threadId = try c.decodeIfPresent(Int.self, forKey: .threadId)
        participants = try c.decodeIfPresent([DevActivityParticipant].self, forKey: .participants) ?? []
        entries = try c.decodeIfPresent([DevActivityEntry].self, forKey: .entries) ?? []
        statusFlow = try c.decodeIfPresent([DevActivityStatusStep].self, forKey: .statusFlow) ?? []
        roleSummaries = try c.decodeIfPresent([DevActivityRoleSummary].self, forKey: .roleSummaries) ?? []
    }

    static let empty = DevActivityTimeline(
        threadId: nil,
        participants: [],
        entries: [],
        statusFlow: [],
        roleSummaries: []
    )

    init(
        threadId: Int?,
        participants: [DevActivityParticipant],
        entries: [DevActivityEntry],
        statusFlow: [DevActivityStatusStep],
        roleSummaries: [DevActivityRoleSummary]
    ) {
        self.threadId = threadId
        self.participants = participants
        self.entries = entries
        self.statusFlow = statusFlow
        self.roleSummaries = roleSummaries
    }
}

struct DevActivityParticipant: Identifiable, Decodable, Equatable {
    var id: String { handle }

    let handle: String
    let role: String
    let label: String
    let displayName: String

    enum CodingKeys: String, CodingKey {
        case handle, role, label
        case displayName = "display_name"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        handle = try c.decodeIfPresent(String.self, forKey: .handle) ?? ""
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? ""
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? handle
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName) ?? label
    }
}

struct DevActivityEntry: Identifiable, Decodable, Equatable {
    let id: String
    let ts: Double?
    let tsMs: Int?
    let kind: String
    let kindLabel: String
    let taskId: Int
    let threadId: Int
    let actor: String
    let actorLabel: String
    let handle: String
    let handleLabel: String
    let status: String
    let statusLabel: String
    let title: String
    let detail: String

    enum CodingKeys: String, CodingKey {
        case id, ts, kind, title, detail, actor, handle, status
        case tsMs = "ts_ms"
        case kindLabel = "kind_label"
        case taskId = "task_id"
        case threadId = "thread_id"
        case actorLabel = "actor_label"
        case handleLabel = "handle_label"
        case statusLabel = "status_label"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ts = try c.decodeIfPresent(Double.self, forKey: .ts)
        tsMs = try c.decodeIfPresent(Int.self, forKey: .tsMs)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? ""
        kindLabel = try c.decodeIfPresent(String.self, forKey: .kindLabel) ?? kind
        taskId = try c.decodeIfPresent(Int.self, forKey: .taskId) ?? 0
        threadId = try c.decodeIfPresent(Int.self, forKey: .threadId) ?? 0
        actor = try c.decodeIfPresent(String.self, forKey: .actor) ?? ""
        actorLabel = try c.decodeIfPresent(String.self, forKey: .actorLabel) ?? actor
        handle = try c.decodeIfPresent(String.self, forKey: .handle) ?? ""
        handleLabel = try c.decodeIfPresent(String.self, forKey: .handleLabel) ?? handle
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        statusLabel = try c.decodeIfPresent(String.self, forKey: .statusLabel) ?? status
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? ""
        detail = try c.decodeIfPresent(String.self, forKey: .detail) ?? ""
    }

    var timestamp: Date? {
        if let tsMs, tsMs > 0 {
            return Date(timeIntervalSince1970: Double(tsMs) / 1000.0)
        }
        if let ts, ts > 0 {
            return Date(timeIntervalSince1970: ts > 10_000_000_000 ? ts / 1000.0 : ts)
        }
        return nil
    }

    var timeLabel: String {
        guard let timestamp else { return "" }
        return WireTime.absoluteLabel(timestamp)
    }
}

struct DevActivityStatusStep: Identifiable, Decodable, Equatable {
    var id: String { "\(taskId)|\(status)|\(tsMs ?? 0)" }

    let taskId: Int
    let status: String
    let statusLabel: String
    let ts: Double?
    let tsMs: Int?
    let handle: String
    let handleLabel: String
    let actor: String
    let actorLabel: String
    let msg: String

    enum CodingKeys: String, CodingKey {
        case status, ts, msg, actor, handle
        case taskId = "task_id"
        case statusLabel = "status_label"
        case tsMs = "ts_ms"
        case handleLabel = "handle_label"
        case actorLabel = "actor_label"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        taskId = try c.decodeIfPresent(Int.self, forKey: .taskId) ?? 0
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        statusLabel = try c.decodeIfPresent(String.self, forKey: .statusLabel) ?? status
        ts = try c.decodeIfPresent(Double.self, forKey: .ts)
        tsMs = try c.decodeIfPresent(Int.self, forKey: .tsMs)
        handle = try c.decodeIfPresent(String.self, forKey: .handle) ?? ""
        handleLabel = try c.decodeIfPresent(String.self, forKey: .handleLabel) ?? handle
        actor = try c.decodeIfPresent(String.self, forKey: .actor) ?? ""
        actorLabel = try c.decodeIfPresent(String.self, forKey: .actorLabel) ?? actor
        msg = try c.decodeIfPresent(String.self, forKey: .msg) ?? ""
    }

    var timeLabel: String {
        let date: Date?
        if let tsMs, tsMs > 0 {
            date = Date(timeIntervalSince1970: Double(tsMs) / 1000.0)
        } else if let ts, ts > 0 {
            date = Date(timeIntervalSince1970: ts > 10_000_000_000 ? ts / 1000.0 : ts)
        } else {
            date = nil
        }
        guard let date else { return "" }
        return WireTime.absoluteLabel(date)
    }
}

struct DevActivityRoleSummary: Identifiable, Decodable, Equatable {
    var id: String { handle }

    let handle: String
    let role: String
    let label: String
    let displayName: String
    let taskIds: [Int]
    let entryCount: Int
    let outputCount: Int
    let statuses: [String]
    let workPreview: String

    enum CodingKeys: String, CodingKey {
        case handle, role, label, statuses
        case displayName = "display_name"
        case taskIds = "task_ids"
        case entryCount = "entry_count"
        case outputCount = "output_count"
        case workPreview = "work_preview"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        handle = try c.decodeIfPresent(String.self, forKey: .handle) ?? ""
        role = try c.decodeIfPresent(String.self, forKey: .role) ?? ""
        label = try c.decodeIfPresent(String.self, forKey: .label) ?? handle
        displayName = try c.decodeIfPresent(String.self, forKey: .displayName) ?? label
        taskIds = try c.decodeIfPresent([Int].self, forKey: .taskIds) ?? []
        entryCount = try c.decodeIfPresent(Int.self, forKey: .entryCount) ?? 0
        outputCount = try c.decodeIfPresent(Int.self, forKey: .outputCount) ?? 0
        statuses = try c.decodeIfPresent([String].self, forKey: .statuses) ?? []
        workPreview = try c.decodeIfPresent(String.self, forKey: .workPreview) ?? ""
    }
}

struct DevTaskActivityTimelineView: View {
    let timeline: DevActivityTimeline

    var body: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 16) {
                DevTheme.sectionLabel("流转时间轴")

                if !timeline.participants.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("参与角色")
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                ForEach(timeline.participants) { person in
                                    participantChip(person)
                                }
                            }
                        }
                    }
                }

                if !timeline.roleSummaries.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("分工摘要")
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                        ForEach(timeline.roleSummaries) { role in
                            roleSummaryCard(role)
                        }
                    }
                }

                if !timeline.statusFlow.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("状态流转")
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                        ForEach(timeline.statusFlow) { step in
                            statusFlowRow(step)
                        }
                    }
                }

                if !timeline.entries.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("工作时间线")
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                        ForEach(timeline.entries) { entry in
                            timelineEntryRow(entry)
                        }
                    }
                }
            }
        }
    }

    private func participantChip(_ person: DevActivityParticipant) -> some View {
        let tint: Color = person.role == "user" ? DevTheme.sand : DevTheme.ok
        return VStack(alignment: .leading, spacing: 2) {
            Text(person.label)
                .font(.system(size: 12, weight: .bold, design: .rounded))
            Text(person.role == "user" ? "Boss" : person.displayName)
                .font(.system(size: 10, design: .rounded))
                .foregroundStyle(DevTheme.dim)
        }
        .foregroundStyle(tint)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(Capsule().fill(tint.opacity(0.14)))
    }

    private func roleSummaryCard(_ role: DevActivityRoleSummary) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(role.label)
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.sand)
                Spacer()
                Text("\(role.entryCount) 条记录")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
            if !role.statuses.isEmpty {
                Text("状态：\(role.statuses.joined(separator: " → "))")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
            if !role.workPreview.isEmpty {
                Text(role.workPreview)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                    .lineLimit(4)
            } else if role.role == "user" {
                Text("下发/确认任务")
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(DevTheme.chip)
        )
    }

    private func statusFlowRow(_ step: DevActivityStatusStep) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Circle()
                .fill(statusTint(step.status))
                .frame(width: 8, height: 8)
                .padding(.top, 5)
            VStack(alignment: .leading, spacing: 3) {
                HStack {
                    Text(step.statusLabel)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                    if !step.handleLabel.isEmpty {
                        Text(step.handleLabel)
                            .font(.system(size: 11, design: .rounded))
                            .foregroundStyle(DevTheme.sand)
                    }
                    Spacer()
                    Text(step.timeLabel)
                        .font(.system(size: 10, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }
                HStack(spacing: 8) {
                    Text("#\(step.taskId)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                    if !step.actorLabel.isEmpty {
                        Text(step.actorLabel)
                            .font(.system(size: 10, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                }
                if !step.msg.isEmpty {
                    Text(step.msg)
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                        .lineLimit(2)
                }
            }
        }
    }

    private func timelineEntryRow(_ entry: DevActivityEntry) -> some View {
        HStack(alignment: .top, spacing: 10) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(kindTint(entry.kind))
                .frame(width: 3)
                .padding(.vertical, 2)
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(entry.title)
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                    Spacer()
                    Text(entry.timeLabel)
                        .font(.system(size: 10, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }
                HStack(spacing: 8) {
                    Text(entry.kindLabel)
                        .font(.system(size: 10, weight: .bold, design: .rounded))
                        .foregroundStyle(kindTint(entry.kind))
                    if !entry.actorLabel.isEmpty {
                        Text(entry.actorLabel)
                            .font(.system(size: 10, design: .rounded))
                            .foregroundStyle(DevTheme.sand)
                    }
                    Text("#\(entry.taskId)")
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                }
                if !entry.detail.isEmpty {
                    Text(entry.detail)
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(Color.white.opacity(0.88))
                        .textSelection(.enabled)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func statusTint(_ status: String) -> Color {
        switch status {
        case "succeeded", "success", "completed": return DevTheme.ok
        case "failed", "error": return DevTheme.off
        case "cancelled": return DevTheme.dim
        case "summary_pending": return DevTheme.sand
        case "open": return DevTheme.sand
        default: return DevTheme.sand.opacity(0.85)
        }
    }

    private func kindTint(_ kind: String) -> Color {
        switch kind {
        case "user_input", "user_confirm": return DevTheme.sand
        case "dispatch": return Color(red: 0.62, green: 0.55, blue: 0.92)
        case "agent_output": return DevTheme.ok
        case "status": return DevTheme.mist
        default: return DevTheme.dim
        }
    }
}
