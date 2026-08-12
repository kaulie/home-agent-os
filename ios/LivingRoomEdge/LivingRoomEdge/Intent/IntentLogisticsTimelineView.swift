import SwiftUI

/// Vertical logistics-style timeline for intent execution status.
struct IntentLogisticsTimelineView: View {
    let journey: IntentJourney

    var body: some View {
        // Refresh active-step / total elapsed every 0.5s while non-terminal.
        TimelineView(.periodic(from: .now, by: journey.terminal ? 3600 : 0.5)) { context in
            content(now: context.date)
        }
    }

    @ViewBuilder
    private func content(now: Date) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("意图执行进度")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                if let total = journey.totalElapsedSeconds(now: now) {
                    Text("总耗时 \(IntentJourney.formatDuration(total))")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                }
                Text("id \(journey.jobId)")
                    .font(.caption2.monospaced())
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            // Current status banner
            HStack(spacing: 8) {
                Circle()
                    .fill(bannerColor)
                    .frame(width: 8, height: 8)
                VStack(alignment: .leading, spacing: 2) {
                    Text(journey.current.label)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(bannerColor == .yellow ? .primary : bannerColor)
                    Text(journey.currentWireStatus)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if journey.terminal {
                    Text(journey.current == .failed ? "失败" : "完成")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(journey.current == .failed ? .red : .green)
                } else if journey.timedOut {
                    Text("等待中")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.orange)
                } else {
                    Text("进行中")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(bannerColor.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 8))

            if !journey.text.isEmpty {
                Text(journey.text)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(journey.phases.enumerated()), id: \.element.id) { index, phase in
                    IntentLogisticsStepRow(
                        phase: phase,
                        isLast: index == journey.phases.count - 1,
                        showFailedLabel: journey.current == .failed && phase.phase == .succeeded,
                        now: now
                    )
                }
            }

            if !journey.planSteps.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    Text("执行计划（按 step）")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    ForEach(journey.planSteps) { item in
                        IntentPlanStepRow(
                            item: item,
                            statusLabel: planStepStatusLabel(for: item, in: journey),
                            statusColor: planStepStatusColor(for: item, in: journey),
                            activity: planStepActivity(for: item, in: journey),
                            now: now
                        )
                    }
                }
                .padding(.top, 4)
            }

            if journey.timedOut, !journey.terminal {
                Text("等待中/超时：服务端尚未到达终态")
                    .font(.caption2)
                    .foregroundStyle(.orange)
            }
            if let err = journey.error, !err.isEmpty, journey.current == .failed {
                Text(err)
                    .font(.caption2)
                    .foregroundStyle(.red)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.tertiarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var bannerColor: Color {
        if journey.current == .failed { return .red }
        if journey.timedOut { return .orange }
        if journey.terminal { return .green }
        return .yellow
    }

    private func planStepStatusLabel(for item: IntentPlanStepItem, in journey: IntentJourney) -> String {
        // Prefer local per-capability status (logs/runtime), not whole-job intent_status.
        if item.runStatus != .waiting {
            return item.runStatus.label
        }
        if journey.current == .succeeded, journey.planSteps.count == 1 {
            return "完成"
        }
        if journey.current == .failed,
           !journey.planSteps.contains(where: { $0.runStatus == .running || $0.runStatus == .succeeded })
        {
            return "失败"
        }
        if journey.current.rank >= IntentPhase.scheduled.rank {
            // Logistics label only: means intent was dispatched but this capability
            // has not yet reported step_status=1 / local .running.
            return "排队"
        }
        return "等待"
    }

    /// What this step is doing right now (progress / who we're waiting on).
    private func planStepActivity(for item: IntentPlanStepItem, in journey: IntentJourney) -> String {
        let trimmed = item.runDetail.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        let label = planStepStatusLabel(for: item, in: journey)
        switch label {
        case "执行中":
            return "进行中（暂无细分进度）…"
        case "排队":
            if let edge = assignedEdgeHint(from: item.summary) {
                return "等待 \(edge) 领取执行"
            }
            return "等待调度 / 其他节点领取"
        case "等待":
            return "尚未开始"
        default:
            return ""
        }
    }

    private func assignedEdgeHint(from summary: String) -> String? {
        // summary looks like: edge=edge-node-xxx · in[...] · out[...]
        guard let range = summary.range(of: "edge=") else { return nil }
        let rest = summary[range.upperBound...]
        guard let token = rest.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: true).first
        else { return nil }
        let edge = String(token)
            .trimmingCharacters(in: CharacterSet(charactersIn: "·"))
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return edge.isEmpty ? nil : edge
    }

    private func planStepStatusColor(for item: IntentPlanStepItem, in journey: IntentJourney) -> Color {
        switch planStepStatusLabel(for: item, in: journey) {
        case "完成": return .green
        case "失败": return .red
        case "跳过": return .orange
        case "执行中", "排队": return .yellow
        default: return Color(.systemGray3)
        }
    }
}

private struct IntentPlanIOBlock: View {
    let title: String
    let entries: [String: String]

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
            ForEach(entries.keys.sorted(), id: \.self) { key in
                let value = entries[key] ?? ""
                HStack(alignment: .top, spacing: 4) {
                    Text("\(key):")
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                    Text(value)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.primary)
                        .textSelection(.enabled)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground).opacity(0.65))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

private struct IntentPlanStepRow: View {
    let item: IntentPlanStepItem
    let statusLabel: String
    let statusColor: Color
    let activity: String
    let now: Date

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text("\(item.step).")
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)
                .frame(width: 22, alignment: .trailing)
            VStack(alignment: .leading, spacing: 4) {
                Text(item.capability)
                    .font(.caption.monospaced().weight(.semibold))
                    .foregroundStyle(.primary)
                if !item.summary.isEmpty {
                    Text(item.summary)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !item.inputs.isEmpty {
                    IntentPlanIOBlock(title: "input", entries: item.inputs)
                }
                if !item.outputs.isEmpty {
                    IntentPlanIOBlock(title: "output", entries: item.outputs)
                }
                if !activity.isEmpty {
                    Text(activity)
                        .font(.caption2.monospaced())
                        .foregroundStyle(
                            item.runStatus == .failed ? .red.opacity(0.9) : Color.accentColor.opacity(0.95)
                        )
                        .lineLimit(4)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            VStack(alignment: .trailing, spacing: 2) {
                Text(statusLabel)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(statusColor)
                if let dur = item.durationSeconds(now: now) {
                    Text(IntentJourney.formatDuration(dur))
                        .font(.caption2.monospaced())
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(statusColor.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }
}

private struct IntentLogisticsStepRow: View {
    let phase: IntentPhaseState
    let isLast: Bool
    let showFailedLabel: Bool
    let now: Date

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(spacing: 0) {
                ZStack {
                    if phase.visual == .active {
                        Circle()
                            .stroke(dotColor.opacity(0.35), lineWidth: 4)
                            .frame(width: 16, height: 16)
                    }
                    Circle()
                        .fill(dotColor)
                        .frame(width: 10, height: 10)
                }
                .frame(width: 16, height: 16)

                if !isLast {
                    Rectangle()
                        .fill(lineColor)
                        .frame(width: 2, height: 26)
                }
            }
            .frame(width: 16, alignment: .top)

            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(titleText)
                        .font(.caption.weight(phase.visual == .active ? .semibold : .regular))
                        .foregroundStyle(titleColor)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if let at = phase.at {
                        Text(Self.timeFormatter.string(from: at))
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                    }
                    Text(durationLabel)
                        .font(.caption2.monospaced().weight(.medium))
                        .foregroundStyle(phase.visual == .pending ? Color(.systemGray3) : .secondary)
                }
                if showsDetail {
                    Text(phase.detail)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(.bottom, isLast ? 0 : 8)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    private var durationLabel: String {
        switch phase.visual {
        case .pending:
            return "[—]"
        case .active, .timedOut:
            guard let at = phase.at else { return "[—]" }
            return "[\(IntentJourney.formatDuration(max(0, now.timeIntervalSince(at))))]"
        case .done, .failed:
            if let d = phase.durationSeconds {
                return "[\(IntentJourney.formatDuration(d))]"
            }
            // Fallback if duration not frozen yet but we have a start.
            if let at = phase.at {
                return "[\(IntentJourney.formatDuration(max(0, now.timeIntervalSince(at))))]"
            }
            return "[—]"
        }
    }

    private var showsDetail: Bool {
        let d = phase.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !d.isEmpty, d != "已完成" else { return false }
        return true
    }

    private var titleText: String {
        if showFailedLabel || (phase.phase == .succeeded && phase.visual == .failed) {
            return IntentPhase.failed.label
        }
        return phase.phase.label
    }

    private var dotColor: Color {
        switch phase.visual {
        case .done: return .green
        case .active: return .yellow
        case .failed: return .red
        case .timedOut: return .orange
        case .pending: return Color(.systemGray3)
        }
    }

    private var lineColor: Color {
        switch phase.visual {
        case .done: return .green.opacity(0.55)
        case .failed: return .red.opacity(0.45)
        case .active: return Color(.systemGray4)
        default: return Color(.systemGray4)
        }
    }

    private var titleColor: Color {
        switch phase.visual {
        case .pending: return .secondary
        case .failed: return .red
        case .timedOut: return .orange
        case .active: return .primary
        case .done: return .primary
        }
    }
}
