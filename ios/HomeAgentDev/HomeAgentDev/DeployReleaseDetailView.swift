import SwiftUI
import UIKit

struct DeployReleaseDetailView: View {
    @EnvironmentObject private var store: DevStore
    let releaseId: Int
    let seed: DeployRelease

    @State private var release: DeployRelease
    @State private var loadError: String?
    @State private var isRefreshing = false
    @State private var pendingReject = false
    @State private var rejectNote = ""
    @State private var copyToast = ""

    init(releaseId: Int, seed: DeployRelease) {
        self.releaseId = releaseId
        self.seed = seed
        _release = State(initialValue: seed)
    }

    var body: some View {
        ZStack {
            DevTheme.ink.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if let loadError, !loadError.isEmpty {
                        Text(loadError)
                            .font(.system(size: 12, design: .rounded))
                            .foregroundStyle(DevTheme.off)
                    }
                    if !copyToast.isEmpty {
                        Text(copyToast)
                            .font(.system(size: 12, design: .rounded))
                            .foregroundStyle(DevTheme.ok)
                    }
                    headerCard
                    pipelineCard
                    timelineCard
                    authorityCard
                    actionsCard
                }
                .padding(16)
            }
        }
        .navigationTitle(release.shaShort.isEmpty ? "流水线" : release.shaShort)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(DevTheme.ink, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                if isRefreshing || store.isApprovingDeploy {
                    ProgressView().tint(DevTheme.sand)
                } else {
                    Button("刷新") {
                        Task { await refresh() }
                    }
                    .foregroundStyle(DevTheme.sand)
                }
            }
        }
        .task {
            await refresh()
        }
        .refreshable {
            await refresh()
        }
        .alert("拒绝上线", isPresented: $pendingReject) {
            TextField("原因（可选）", text: $rejectNote)
            Button("取消", role: .cancel) {
                rejectNote = ""
            }
            Button("拒绝", role: .destructive) {
                let note = rejectNote
                rejectNote = ""
                Task {
                    if let updated = await store.rejectDeployRelease(releaseId: releaseId, note: note) {
                        release = updated
                    }
                }
            }
        } message: {
            Text("sha \(release.shaShort) — 拒绝后不会唤醒 @deploy")
        }
    }

    private var headerCard: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .firstTextBaseline) {
                    Text(release.statusLabel)
                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                        .foregroundStyle(statusColor(release.status))
                        .padding(.horizontal, 10)
                        .padding(.vertical, 5)
                        .background(Capsule().fill(DevTheme.chip))
                    Spacer()
                    Text("#\(release.releaseId)")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                }

                Button {
                    copyText(release.sha.isEmpty ? release.shaShort : release.sha, toast: "已复制 sha")
                } label: {
                    HStack(spacing: 8) {
                        Text(release.shaShort)
                            .font(.system(size: 22, weight: .semibold, design: .monospaced))
                            .foregroundStyle(DevTheme.sand)
                        Image(systemName: "doc.on.doc")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(DevTheme.dim)
                    }
                }
                .buttonStyle(.plain)

                if !release.sha.isEmpty, release.sha != release.shaShort {
                    Text(release.sha)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                        .textSelection(.enabled)
                }

                if !release.scope.isEmpty {
                    metaRow("Scope", release.scope)
                }
                if !release.summary.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("SUMMARY")
                            .font(.system(size: 9, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                        Text(release.summary)
                            .font(.system(size: 14, design: .rounded))
                            .foregroundStyle(DevTheme.mist)
                    }
                }
                metaRow("Target", release.target)
                if let created = release.createdAt {
                    metaRow("创建", WireTime.absoluteLabel(created))
                }
                if let updated = release.updatedAt {
                    metaRow("更新", WireTime.absoluteLabel(updated))
                }
            }
        }
    }

    private var pipelineCard: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 14) {
                DevTheme.sectionLabel("发布进度")
                HStack(alignment: .top, spacing: 0) {
                    ForEach(Array(release.pipeline.enumerated()), id: \.element.id) { index, node in
                        let failedTest = release.status == "test_failed" && node.node == "tested"
                        VStack(spacing: 8) {
                            ZStack {
                                Circle()
                                    .fill(failedTest ? DevTheme.off : (node.done ? DevTheme.ok : DevTheme.chip))
                                    .frame(width: 14, height: 14)
                                if index < release.pipeline.count - 1 {
                                    // spacer handled by flexible frames below
                                }
                            }
                            Text(shortNode(node.node))
                                .font(.system(size: 11, weight: .semibold, design: .rounded))
                                .foregroundStyle(
                                    failedTest ? DevTheme.off : (node.done ? DevTheme.mist : DevTheme.dim)
                                )
                        }
                        .frame(maxWidth: .infinity)
                        if index < release.pipeline.count - 1 {
                            Rectangle()
                                .fill(node.done ? DevTheme.ok.opacity(0.6) : DevTheme.chip)
                                .frame(height: 2)
                                .padding(.top, 6)
                                .frame(width: 18)
                        }
                    }
                }
            }
        }
    }

    private var timelineCard: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 12) {
                DevTheme.sectionLabel("阶段时间线 (\(release.orderedStages.count))")
                if release.orderedStages.isEmpty {
                    Text("暂无 [release] 节点记录")
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else {
                    ForEach(Array(release.orderedStages.enumerated()), id: \.element.id) { index, event in
                        timelineRow(event, isLast: index == release.orderedStages.count - 1)
                    }
                }
            }
        }
    }

    private func timelineRow(_ event: DeployStageEvent, isLast: Bool) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(spacing: 0) {
                Circle()
                    .fill(dotColor(event))
                    .frame(width: 10, height: 10)
                    .padding(.top, 4)
                if !isLast {
                    Rectangle()
                        .fill(DevTheme.chip)
                        .frame(width: 2)
                        .frame(maxHeight: .infinity)
                }
            }
            .frame(width: 10)

            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Text(event.stageLabel)
                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                    if !event.result.isEmpty {
                        Text(event.result.uppercased())
                            .font(.system(size: 10, weight: .bold, design: .rounded))
                            .foregroundStyle(event.result == "fail" ? DevTheme.off : DevTheme.ok)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Capsule().fill(DevTheme.chip))
                    }
                    Spacer()
                    if let at = event.at {
                        Text(WireTime.absoluteLabel(at))
                            .font(.system(size: 11, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                }
                if !event.by.isEmpty {
                    Text("@\(event.by)")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(DevTheme.sand)
                }
                if !event.note.isEmpty {
                    Text(event.note)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                }
                if event.chatMsgId > 0 {
                    Button {
                        copyText("\(event.chatMsgId)", toast: "已复制 Chat #\(event.chatMsgId)")
                    } label: {
                        Text("Chat #\(event.chatMsgId) · 复制")
                            .font(.system(size: 12, weight: .medium, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.bottom, isLast ? 0 : 14)
        }
    }

    private var authorityCard: some View {
        let hasApproval = !release.approvedBy.isEmpty || release.approvedAt != nil
        let hasReject = !release.rejectedBy.isEmpty || release.rejectedAt != nil || !release.rejectNote.isEmpty
        let hasRun = !release.deployRunId.isEmpty
        return Group {
            if hasApproval || hasReject || hasRun {
                DevPanel {
                    VStack(alignment: .leading, spacing: 12) {
                        DevTheme.sectionLabel("Deploy Authority")
                        if hasApproval {
                            if !release.approvedBy.isEmpty {
                                metaRow("批准人", release.approvedBy)
                            }
                            if let at = release.approvedAt {
                                metaRow("批准时间", WireTime.absoluteLabel(at))
                            }
                        }
                        if hasReject {
                            if !release.rejectedBy.isEmpty {
                                metaRow("拒绝人", release.rejectedBy)
                            }
                            if let at = release.rejectedAt {
                                metaRow("拒绝时间", WireTime.absoluteLabel(at))
                            }
                            if !release.rejectNote.isEmpty {
                                metaRow("拒绝原因", release.rejectNote)
                            }
                        }
                        if hasRun {
                            Button {
                                copyText(release.deployRunId, toast: "已复制 Fleet run id")
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text("FLEET RUN")
                                            .font(.system(size: 9, weight: .semibold, design: .rounded))
                                            .foregroundStyle(DevTheme.dim)
                                        Text(release.deployRunId)
                                            .font(.system(size: 12, design: .monospaced))
                                            .foregroundStyle(DevTheme.sand)
                                            .lineLimit(2)
                                    }
                                    Spacer()
                                    Text("复制")
                                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                                        .foregroundStyle(DevTheme.mist)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
    }

    private var actionsCard: some View {
        Group {
            if release.canApprove || release.canReject {
                DevPanel {
                    VStack(alignment: .leading, spacing: 10) {
                        DevTheme.sectionLabel("操作")
                        HStack(spacing: 10) {
                            if release.canApprove {
                                Button {
                                    Task {
                                        if let updated = await store.approveDeployRelease(releaseId: releaseId) {
                                            release = updated
                                        }
                                    }
                                } label: {
                                    Text("批准上线")
                                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 12)
                                        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(DevTheme.sand))
                                        .foregroundStyle(DevTheme.ink)
                                }
                                .disabled(store.isApprovingDeploy)
                            }
                            if release.canReject {
                                Button {
                                    pendingReject = true
                                } label: {
                                    Text("拒绝")
                                        .font(.system(size: 14, weight: .semibold, design: .rounded))
                                        .frame(maxWidth: .infinity)
                                        .padding(.vertical, 12)
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
            }
        }
    }

    private func refresh() async {
        isRefreshing = true
        defer { isRefreshing = false }
        let (fresh, err) = await store.loadDeployRelease(releaseId: releaseId, seed: release)
        if let fresh {
            release = fresh
        }
        loadError = err
    }

    private func metaRow(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased())
                .font(.system(size: 9, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            Text(value)
                .font(.system(size: 13, design: .rounded))
                .foregroundStyle(DevTheme.mist)
        }
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

    private func dotColor(_ event: DeployStageEvent) -> Color {
        if event.result == "fail" || event.stage == "rejected" {
            return DevTheme.off
        }
        if event.result == "pass" || ["deployed", "approved", "committed", "tested"].contains(event.stage) {
            return DevTheme.ok
        }
        return DevTheme.sand
    }

    private func copyText(_ text: String, toast: String) {
        UIPasteboard.general.string = text
        copyToast = toast
        Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            if copyToast == toast {
                copyToast = ""
            }
        }
    }
}
