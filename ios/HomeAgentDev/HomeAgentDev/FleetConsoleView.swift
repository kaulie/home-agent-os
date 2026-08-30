import SwiftUI

struct FleetConsoleView: View {
    @EnvironmentObject private var store: DevStore
    @State private var wakeHandle: FleetAgent?
    @State private var wakeText = ""

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            if let err = store.fleetError, !err.isEmpty {
                                Text(err)
                                    .font(.system(size: 13, design: .rounded))
                                    .foregroundStyle(DevTheme.off)
                            }
                            if store.isLoadingFleet && store.fleetSnapshot == nil {
                                ProgressView("加载 Fleet…")
                                    .tint(DevTheme.sand)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 40)
                            } else if let snap = store.fleetSnapshot {
                                bridgeSummary(snap)
                                agentsSection(snap.agents)
                                runsSection(snap.runs)
                            }
                        }
                        .padding(16)
                    }
                }
            }
            .navigationTitle("Fleet")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .refreshable {
                await store.loadFleet(showSpinner: false)
            }
            .alert("唤醒 @\(wakeHandle?.handle ?? "")", isPresented: Binding(
                get: { wakeHandle != nil },
                set: { if !$0 { wakeHandle = nil; wakeText = "" } }
            )) {
                TextField("任务说明（可选）", text: $wakeText)
                Button("取消", role: .cancel) {
                    wakeHandle = nil
                    wakeText = ""
                }
                Button("唤醒") {
                    let agent = wakeHandle
                    let text = wakeText
                    wakeHandle = nil
                    wakeText = ""
                    guard let agent else { return }
                    Task { await store.wakeFleetAgent(handle: agent.handle, text: text) }
                }
            } message: {
                Text(wakeHandle?.displayName ?? "")
            }
        }
    }

    @ViewBuilder
    private func bridgeSummary(_ snap: FleetSnapshot) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                DevTheme.sectionLabel("Bridge")
                HStack {
                    Circle()
                        .fill(snap.bridgeOk == true ? DevTheme.ok : DevTheme.off)
                        .frame(width: 8, height: 8)
                    Text(snap.bridgeOk == true ? "在线" : "不可用")
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                    Spacer(minLength: 8)
                    alignmentChip(aligned: snap.workAligned != false, desync: snap.desyncHandles)
                }
                if let url = snap.bridgeURL, !url.isEmpty {
                    Text(url)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                }
                if let status = snap.status {
                    HStack(spacing: 12) {
                        if let model = status.model, !model.isEmpty {
                            metaChip("模型", model)
                        }
                        if let backend = status.backend, !backend.isEmpty {
                            metaChip("后端", backend)
                        }
                        if let depth = status.queueDepth {
                            metaChip("队列", "\(depth)")
                        }
                    }
                }
                if snap.workAligned == false, !snap.desyncHandles.isEmpty {
                    Text("状态不一致：@" + snap.desyncHandles.joined(separator: " @"))
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(Color(red: 0.95, green: 0.55, blue: 0.35))
                }
            }
        }
    }

    private func alignmentChip(aligned: Bool, desync: [String]) -> some View {
        Text(aligned ? "Chat⇄Fleet 一致" : "Chat⇄Fleet 不一致")
            .font(.system(size: 11, weight: .semibold, design: .rounded))
            .foregroundStyle(aligned ? DevTheme.ink : Color(red: 0.2, green: 0.08, blue: 0.05))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(
                Capsule().fill(
                    aligned
                        ? DevTheme.ok.opacity(0.85)
                        : Color(red: 0.95, green: 0.55, blue: 0.35)
                )
            )
            .accessibilityLabel(aligned ? "状态一致" : "状态不一致 \(desync.joined(separator: ","))")
    }

    @ViewBuilder
    private func agentsSection(_ agents: [FleetAgent]) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 12) {
                DevTheme.sectionLabel("Agents (\(agents.count))")
                ForEach(agents) { agent in
                    agentRow(agent)
                    if agent.id != agents.last?.id {
                        Divider().overlay(DevTheme.panelStroke)
                    }
                }
            }
        }
    }

    private func agentRow(_ agent: FleetAgent) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text("@\(agent.handle)")
                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.sand)
                    phaseBadge(agent)
                    if agent.aligned == false {
                        Text("!")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundStyle(Color(red: 0.95, green: 0.55, blue: 0.35))
                    }
                }
                Text(agent.displayName)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                if let runId = agent.activeRunId ?? agent.runningRunId, !runId.isEmpty {
                    Text("run \(runId.prefix(8))…\(agent.activeStatus.map { " · \($0)" } ?? "")")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                }
                if let mid = agent.sourceMessageId, mid > 0 {
                    Text("chat #\(mid)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                }
                if let desync = agent.desync, !desync.isEmpty {
                    Text(desync)
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(Color(red: 0.95, green: 0.55, blue: 0.35))
                        .fixedSize(horizontal: false, vertical: true)
                } else if let open = agent.chatOpenCount, open > 0, !agent.chatAwaitingRecv.isEmpty {
                    Text("待签收 #\(agent.chatAwaitingRecv.map { String($0.id) }.joined(separator: ", #"))")
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(DevTheme.mist.opacity(0.85))
                }
            }
            Spacer(minLength: 8)
            Button {
                wakeHandle = agent
            } label: {
                Text("唤醒")
                    .font(.system(size: 13, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.ink)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 7)
                    .background(Capsule().fill(DevTheme.sand))
            }
            .disabled(store.isWakingFleet || store.fleetSnapshot?.bridgeOk != true)
        }
    }

    private func phaseBadge(_ agent: FleetAgent) -> some View {
        let key = (agent.phase ?? "").lowercased()
        let fill: Color = {
            switch key {
            case "running": return DevTheme.ok
            case "queued": return DevTheme.sand.opacity(0.9)
            case "awaiting_recv", "awaiting_ide": return Color(red: 0.95, green: 0.55, blue: 0.35)
            case "acked": return DevTheme.sand.opacity(0.55)
            default:
                return agent.phaseIsActive ? DevTheme.sand.opacity(0.45) : DevTheme.chip
            }
        }()
        let fg: Color = (key == "running" || key == "queued") ? DevTheme.ink : DevTheme.mist
        return Text(agent.phaseBadgeText)
            .font(.system(size: 11, weight: .bold, design: .rounded))
            .foregroundStyle(fg)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Capsule().fill(fill))
    }

    @ViewBuilder
    private func runsSection(_ runs: [FleetRun]) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                DevTheme.sectionLabel("最近 Run")
                if runs.isEmpty {
                    Text("暂无记录")
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else {
                    ForEach(runs.prefix(12)) { run in
                        runRow(run)
                    }
                }
            }
        }
    }

    private func runRow(_ run: FleetRun) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if let handle = run.targetHandle, !handle.isEmpty {
                    Text("@\(handle)")
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.sand)
                }
                Text(run.status)
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                Spacer()
                Text(run.runId.prefix(8) + "…")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(DevTheme.dim)
            }
            if let text = run.text, !text.isEmpty {
                Text(text)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                    .lineLimit(2)
            }
            if let mid = run.sourceMessageId, mid > 0 {
                Text("← chat #\(mid)")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(DevTheme.dim)
            }
        }
        .padding(.vertical, 4)
    }

    private func metaChip(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(.system(size: 9, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            Text(value)
                .font(.system(size: 12, weight: .medium, design: .rounded))
                .foregroundStyle(DevTheme.mist)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(DevTheme.chip))
    }
}
