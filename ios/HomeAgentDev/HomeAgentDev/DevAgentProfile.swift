import Foundation
import SwiftUI

enum DevAgentRoster {
    static let duties: [String: String] = [
        "coordinator": "跨层仲裁、催办、日报收口；默认静默，结案用 cc。",
        "controller": "唯一常驻 IDE；wake Fleet、汇总进度、Dev Task 入口。",
        "brain": "规划、选边、入队、对外 Brain API。",
        "runtime": "调度 / hydrate / 前序门；Mac/Android edge runtime。",
        "ui": "全部用户交互面：Intent、物流 UI、Cast、Receiver、管理端 UI。",
        "capability": "Plugin 契约与实现（非 UI 呈现面）。",
        "quality": "黑盒 API 验收 + App UI 自动化（XCUITest）。",
        "deploy": "云 Brain 部署（rsync + restart）。",
        "sre": "本机/边缘运维、双 Brain、local-rt、架构 runbook。",
        "dba": "schema / SQL（Brain SQLite）。",
        "boss": "产品方；派活与验收。",
    ]

    static func normalize(_ handle: String) -> String {
        let h = handle.lowercased()
        if h == "user" || h == "owner" { return "boss" }
        if h == "intent" || h == "endpoint" { return "ui" }
        return h
    }

    static func displayName(for handle: String) -> String {
        let h = normalize(handle)
        return ChatMentionCatalog.agent(handle: h)?.displayName ?? h
    }

    static func duty(for handle: String) -> String {
        duties[normalize(handle)] ?? "—"
    }

    static func phaseLabel(agent: FleetAgent?) -> String {
        if let agent {
            if let phaseLabel = agent.phaseLabel, !phaseLabel.isEmpty { return phaseLabel }
            if let phase = agent.phase, !phase.isEmpty {
                switch phase {
                case "idle": return "空闲"
                case "awaiting_recv": return "待签收"
                case "awaiting_ide": return "待 IDE"
                case "queued": return "队列中"
                case "running": return "执行中"
                case "acked": return "已签收"
                default: return phase
                }
            }
            return agent.phaseBadgeText
        }
        return "空闲"
    }

    static func taskSummary(handle: String, fleet: FleetSnapshot?) -> String {
        let h = normalize(handle)
        guard let fleet else { return "空闲 / 无进行中任务" }
        let agent = fleet.agents.first(where: { $0.handle == h })
        var run: FleetRun?
        if let rid = agent?.runningRunId {
            run = fleet.runs.first(where: { $0.runId == rid })
        }
        if run == nil {
            run = fleet.runs.first(where: {
                $0.targetHandle == h && ($0.status == "running" || $0.status == "queued")
            })
        }
        if let run {
            let text = (run.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let short = text.count > 100 ? String(text.prefix(99)) + "…" : text
            if short.isEmpty { return "Dev Task \(run.runId)" }
            return "Dev Task \(run.runId) · \(short)"
        }
        if let agent, let item = agent.chatAwaitingRecv.first {
            let preview = (item.preview ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let short = preview.count > 80 ? String(preview.prefix(79)) + "…" : preview
            return "Chat #\(item.id) 待签收 · \(short)"
        }
        return "空闲 / 无进行中任务"
    }

    static func phaseIsActive(agent: FleetAgent?) -> Bool {
        guard let agent else { return false }
        let key = (agent.phase ?? "").lowercased()
        return agent.phaseIsActive || key == "running" || key == "queued" || key == "awaiting_recv" || key == "acked"
    }
}

struct DevAgentProfileSheet: View {
    let handle: String
    @EnvironmentObject private var store: DevStore
    @Environment(\.dismiss) private var dismiss

    private var normalized: String { DevAgentRoster.normalize(handle) }
    private var agent: FleetAgent? {
        store.fleetSnapshot?.agents.first(where: { $0.handle == normalized })
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .top, spacing: 12) {
                        avatarGlyph
                        VStack(alignment: .leading, spacing: 4) {
                            Text("@\(normalized)")
                                .font(.system(size: 15, weight: .bold, design: .rounded))
                                .foregroundStyle(DevTheme.ok)
                            Text(DevAgentRoster.displayName(for: normalized))
                                .font(.system(size: 14, weight: .semibold, design: .rounded))
                                .foregroundStyle(DevTheme.sand)
                        }
                    }
                    Text(DevAgentRoster.duty(for: normalized))
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                        .fixedSize(horizontal: false, vertical: true)

                    profileRow(title: "当前忙闲") {
                        Text(DevAgentRoster.phaseLabel(agent: agent))
                            .foregroundStyle(DevAgentRoster.phaseIsActive(agent: agent) ? DevTheme.ok : DevTheme.dim)
                            .fontWeight(DevAgentRoster.phaseIsActive(agent: agent) ? .semibold : .regular)
                    }
                    profileRow(title: "目前正在处理") {
                        Text(DevAgentRoster.taskSummary(handle: normalized, fleet: store.fleetSnapshot))
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(16)
            }
            .background(DevTheme.ink)
            .navigationTitle("Agent 资料")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("关闭") { dismiss() }
                        .foregroundStyle(DevTheme.sand)
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
        .task { await store.loadFleet(showSpinner: false) }
    }

    private var avatarGlyph: some View {
        Text(String(normalized.prefix(1)).uppercased())
            .font(.system(size: 16, weight: .bold, design: .rounded))
            .foregroundStyle(DevTheme.ink)
            .frame(width: 40, height: 40)
            .background(Circle().fill(DevTheme.sand.opacity(0.9)))
    }

    private func profileRow<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.system(size: 10, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            content()
                .font(.system(size: 13, design: .rounded))
                .foregroundStyle(DevTheme.sand)
        }
    }
}
