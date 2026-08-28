import SwiftUI

struct DeployConsoleView: View {
    @EnvironmentObject private var store: DevStore
    @State private var pendingReject: DeployRelease?
    @State private var rejectNote = ""

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 16) {
                            if let err = store.deployError, !err.isEmpty {
                                Text(err)
                                    .font(.system(size: 13, design: .rounded))
                                    .foregroundStyle(DevTheme.off)
                            }
                            if store.isLoadingDeploy && store.deploySnapshot == nil {
                                ProgressView("加载 Deploy…")
                                    .tint(DevTheme.sand)
                                    .frame(maxWidth: .infinity)
                                    .padding(.vertical, 40)
                            } else {
                                legend
                                summaryBar
                                if let snap = store.deploySnapshot {
                                    let awaiting = snap.releases.filter { $0.status == "awaiting_approval" }
                                    let active = snap.releases.filter {
                                        ["in_progress", "approved", "deploying", "test_failed"].contains($0.status)
                                    }
                                    let done = snap.releases.filter {
                                        ["deployed", "rejected", "skipped"].contains($0.status)
                                    }
                                    section(title: "待批准", items: awaiting, empty: "暂无待批准版本")
                                    section(title: "进行中", items: active, empty: "暂无进行中")
                                    section(title: "历史", items: done, empty: "暂无历史记录")
                                }
                            }
                        }
                        .padding(16)
                    }
                }
            }
            .navigationTitle("Deploy")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .refreshable {
                await store.loadDeploy(showSpinner: false)
            }
            .alert("拒绝上线", isPresented: Binding(
                get: { pendingReject != nil },
                set: { if !$0 { pendingReject = nil; rejectNote = "" } }
            )) {
                TextField("原因（可选）", text: $rejectNote)
                Button("取消", role: .cancel) {
                    pendingReject = nil
                    rejectNote = ""
                }
                Button("拒绝", role: .destructive) {
                    let release = pendingReject
                    let note = rejectNote
                    pendingReject = nil
                    rejectNote = ""
                    guard let release else { return }
                    Task { await store.rejectDeployRelease(releaseId: release.releaseId, note: note) }
                }
            } message: {
                if let r = pendingReject {
                    Text("sha \(r.shaShort) — 拒绝后不会唤醒 @deploy")
                }
            }
        }
    }

    private var legend: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                DevTheme.sectionLabel("发布链路")
                Text("git 提交 → 测试 → 批准上线 → 部署")
                    .font(.system(size: 13, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                Text("点进流水线看阶段时间线；批准后唤醒 @deploy。")
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                HStack(spacing: 6) {
                    ForEach(["Commit", "Test", "Approve", "Deploy"], id: \.self) { label in
                        Text(label)
                            .font(.system(size: 11, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.sand)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 5)
                            .background(Capsule().fill(DevTheme.chip))
                        if label != "Deploy" {
                            Image(systemName: "chevron.right")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundStyle(DevTheme.dim)
                        }
                    }
                }
            }
        }
    }

    private var summaryBar: some View {
        let counts = store.deploySnapshot?.counts
        return DevPanel {
            HStack(spacing: 16) {
                metric("待批准", "\(counts?.awaitingApproval ?? 0)")
                metric("进行中", "\(counts?.inFlight ?? 0)")
                metric("列表", "\(counts?.total ?? 0)")
                Spacer()
                if store.isApprovingDeploy {
                    ProgressView().tint(DevTheme.sand)
                }
            }
        }
    }

    private func metric(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(.system(size: 9, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            Text(value)
                .font(.system(size: 18, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.mist)
        }
    }

    @ViewBuilder
    private func section(title: String, items: [DeployRelease], empty: String) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 12) {
                DevTheme.sectionLabel("\(title) (\(items.count))")
                if items.isEmpty {
                    Text(empty)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else {
                    ForEach(items) { release in
                        releaseCard(release)
                        if release.id != items.last?.id {
                            Divider().overlay(DevTheme.panelStroke)
                        }
                    }
                }
            }
        }
    }

    private func releaseCard(_ release: DeployRelease) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            NavigationLink {
                DeployReleaseDetailView(releaseId: release.releaseId, seed: release)
            } label: {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(release.shaShort)
                            .font(.system(size: 15, weight: .semibold, design: .monospaced))
                            .foregroundStyle(DevTheme.sand)
                        if !release.scope.isEmpty {
                            Text(release.scope)
                                .font(.system(size: 11, weight: .medium, design: .rounded))
                                .foregroundStyle(DevTheme.dim)
                        }
                        Spacer()
                        Text(release.statusLabel)
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(statusColor(release.status))
                        Image(systemName: "chevron.right")
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(DevTheme.dim)
                    }
                    if !release.summary.isEmpty {
                        Text(release.summary)
                            .font(.system(size: 13, design: .rounded))
                            .foregroundStyle(DevTheme.mist)
                            .lineLimit(3)
                            .multilineTextAlignment(.leading)
                    }
                    Text(release.target)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)

                    pipelineStrip(release.pipeline)

                    if let updated = release.updatedAt {
                        Text(updated.formatted(date: .abbreviated, time: .shortened))
                            .font(.system(size: 11, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if release.canApprove || release.canReject {
                HStack(spacing: 10) {
                    if release.canApprove {
                        Button {
                            Task { await store.approveDeployRelease(releaseId: release.releaseId) }
                        } label: {
                            Text("批准上线")
                                .font(.system(size: 13, weight: .semibold, design: .rounded))
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 10)
                                .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(DevTheme.sand))
                                .foregroundStyle(DevTheme.ink)
                        }
                        .disabled(store.isApprovingDeploy)
                    }
                    if release.canReject {
                        Button {
                            pendingReject = release
                        } label: {
                            Text("拒绝")
                                .font(.system(size: 13, weight: .semibold, design: .rounded))
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 10)
                                .background(
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .stroke(DevTheme.off.opacity(0.7), lineWidth: 1)
                                )
                                .foregroundStyle(DevTheme.off)
                        }
                        .disabled(store.isApprovingDeploy)
                    }
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func pipelineStrip(_ nodes: [DeployPipelineNode]) -> some View {
        HStack(spacing: 4) {
            ForEach(nodes) { node in
                VStack(spacing: 4) {
                    Circle()
                        .fill(node.done ? DevTheme.ok : DevTheme.chip)
                        .frame(width: 8, height: 8)
                    Text(shortNode(node.node))
                        .font(.system(size: 9, weight: .medium, design: .rounded))
                        .foregroundStyle(node.done ? DevTheme.mist : DevTheme.dim)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding(.vertical, 4)
    }

    private func shortNode(_ node: String) -> String {
        switch node {
        case "committed": return "Commit"
        case "tested": return "Test"
        case "approved": return "Approve"
        case "deployed": return "Deploy"
        default: return node
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "awaiting_approval": return DevTheme.sand
        case "deployed": return DevTheme.ok
        case "rejected", "test_failed": return DevTheme.off
        default: return DevTheme.mist
        }
    }
}
