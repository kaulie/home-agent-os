import SwiftUI
import UIKit

struct IssueListView: View {
    @EnvironmentObject private var store: DevStore

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    List {
                    if let err = store.issuesError, !err.isEmpty {
                        Text(err)
                            .foregroundStyle(DevTheme.off)
                            .listRowBackground(Color.clear)
                    }
                    if store.isLoadingIssues && store.issues.isEmpty {
                        Text("加载中…")
                            .foregroundStyle(DevTheme.dim)
                            .listRowBackground(Color.clear)
                    } else if store.issues.isEmpty {
                        Text("还没有 Issue。User Console 一键报 Bug 后会出现在这里。")
                            .foregroundStyle(DevTheme.dim)
                            .listRowBackground(Color.clear)
                    } else {
                        ForEach(store.issues) { issue in
                            NavigationLink {
                                IssueDetailView(issueId: issue.issueId)
                            } label: {
                                IssueRowView(issue: issue)
                            }
                            .listRowBackground(DevTheme.panel)
                            .listRowSeparatorTint(DevTheme.panelStroke)
                            .onAppear {
                                if issue.issueId == store.issues.last?.issueId,
                                   !store.issuesExhausted,
                                   !store.isLoadingIssues {
                                    Task { await store.loadIssues(reset: false, showSpinner: false) }
                                }
                            }
                        }
                    }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .refreshable {
                        await store.loadIssues(reset: true, showSpinner: false)
                    }
                }
            }
            .navigationTitle("Issue")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }
}

struct IssueRowView: View {
    let issue: DebugIssue

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Issue #\(issue.issueId)")
                    .font(.system(size: 12, weight: .bold, design: .monospaced))
                    .foregroundStyle(DevTheme.sand)
                Spacer()
                Text(issue.relativeLabel)
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
            Text(issue.statusTitle)
                .font(.system(size: 11, weight: .bold, design: .rounded))
                .foregroundStyle(statusColor)
            if !issue.feedbackProblemLabel.isEmpty {
                Text(issue.feedbackProblemLabel)
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.sand)
                    .lineLimit(2)
            }
            if !issue.contextUserInput.isEmpty {
                Text(issue.contextUserInput)
                    .font(.system(size: 14, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                    .lineLimit(2)
            } else if issue.feedbackProblemLabel.isEmpty {
                Text(issue.userInputPreview)
                    .font(.system(size: 15, weight: .medium, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                    .lineLimit(2)
            }
            HStack(spacing: 8) {
                Text("intent #\(issue.intentId)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(DevTheme.dim)
                if let taskId = issue.taskId {
                    Text("task \(taskId)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                }
            }
            if !issue.contextError.isEmpty {
                Text(issue.contextError)
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.off.opacity(0.9))
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 4)
    }

    private var statusColor: Color {
        if issue.status == "failed" { return DevTheme.off }
        if issue.isActive { return DevTheme.sand }
        return DevTheme.ok
    }
}

struct IssueDetailView: View {
    @EnvironmentObject private var store: DevStore
    let issueId: Int
    @State private var issue: DebugIssue?
    @State private var error: String?

    var body: some View {
        ZStack {
            DevTheme.ink.ignoresSafeArea()
            ScrollView {
                if let issue {
                    VStack(alignment: .leading, spacing: 16) {
                        issueHeader(issue)
                        feedbackTargetSection(issue)
                        feedbackProblemSection(issue)
                        executionSceneSection(issue)
                        rootCauseSection(issue)
                        fixRecommendationSection(issue)
                        if !issue.error.isEmpty {
                            gatewayErrorSection(issue)
                        }
                    }
                    .padding(16)
                } else if let error {
                    Text(error)
                        .foregroundStyle(DevTheme.off)
                        .padding(16)
                } else {
                    ProgressView()
                        .tint(DevTheme.sand)
                }
            }
        }
        .navigationTitle("Issue #\(issueId)")
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(DevTheme.ink, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .task(id: issueId) {
            await reload()
        }
        .refreshable {
            await reload()
        }
    }

    private func issueHeader(_ issue: DebugIssue) -> some View {
        HStack(spacing: 10) {
            Text(issue.statusTitle)
                .font(.system(size: 12, weight: .bold, design: .rounded))
                .foregroundStyle(issue.isActive ? DevTheme.sand : DevTheme.ok)
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(Capsule().fill((issue.isActive ? DevTheme.sand : DevTheme.ok).opacity(0.16)))
            Spacer()
            Text(issue.timeLabel)
                .font(.system(size: 12, design: .rounded))
                .foregroundStyle(DevTheme.dim)
        }
    }

    private func feedbackTargetSection(_ issue: DebugIssue) -> some View {
        issueSection(title: "1. 反馈标的", subtitle: "这次反馈对应哪条 Intent") {
            detailRow(label: "Intent", value: "#\(issue.intentId)", mono: true)
            if !issue.contextUserInput.isEmpty {
                detailRow(label: "用户原话", value: issue.contextUserInput)
            }
            if !issue.contextSource.isEmpty {
                detailRow(label: "输入来源", value: issue.contextSource)
            }
            if !issue.participantId.isEmpty {
                detailRow(label: "上报节点", value: issue.participantId, mono: true)
            }
            if !issue.contextEdgeId.isEmpty, issue.contextEdgeId != issue.participantId {
                detailRow(label: "执行节点", value: issue.contextEdgeId, mono: true)
            }
            if !issue.sessionId.isEmpty {
                detailRow(label: "Session", value: issue.sessionId, mono: true)
            }
            detailRow(label: "上报渠道", value: issue.source.isEmpty ? "user_console" : issue.source)
        }
    }

    private func feedbackProblemSection(_ issue: DebugIssue) -> some View {
        issueSection(title: "2. 反馈问题", subtitle: "用户认为哪里不对") {
            if !issue.feedbackProblemLabel.isEmpty {
                detailRow(label: "问题类型", value: issue.feedbackProblemLabel, prominent: true)
            } else {
                detailRow(label: "问题类型", value: "未标注", muted: true)
            }
            if !issue.feedbackDetailText.isEmpty {
                detailRow(label: "补充说明", value: issue.feedbackDetailText)
            }
            if !issue.attachments.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("附件")
                        .font(.system(size: 11, weight: .semibold, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                    IssueAttachmentGallery(
                        attachments: issue.attachments,
                        intentId: issue.intentId,
                        brainURL: store.activeBrainURL
                    )
                }
            }
        }
    }

    private func executionSceneSection(_ issue: DebugIssue) -> some View {
        issueSection(title: "3. 执行现场", subtitle: "提交反馈瞬间抓到的 Intent 状态") {
            if !issue.contextIntentStatus.isEmpty {
                detailRow(label: "Intent 状态", value: issue.contextIntentStatus, mono: true)
            }
            if !issue.contextError.isEmpty {
                detailRow(label: "执行错误", value: issue.contextError, accent: DevTheme.off)
            }
            if !issue.contextPlanLines.isEmpty {
                bulletBlock(label: "执行计划", lines: issue.contextPlanLines)
            }
            if !issue.contextStatusTimeline.isEmpty {
                bulletBlock(label: "状态时间线", lines: issue.contextStatusTimeline)
            }
            if !issue.contextStepLines.isEmpty {
                bulletBlock(label: "步骤日志", lines: issue.contextStepLines)
            }
            if !issue.scenePrimaryBrainLines.isEmpty {
                bulletBlock(label: "Primary Brain", lines: issue.scenePrimaryBrainLines)
            }
            if !issue.sceneHeartbeatLines.isEmpty {
                bulletBlock(label: "最近心跳", lines: issue.sceneHeartbeatLines)
            }
            if !issue.sceneRuntimeLogLines.isEmpty {
                bulletBlock(label: "本地 Runtime 日志", lines: issue.sceneRuntimeLogLines)
            }
            if issue.contextIntentStatus.isEmpty
                && issue.contextError.isEmpty
                && issue.contextPlanLines.isEmpty
                && issue.contextStatusTimeline.isEmpty
                && issue.contextStepLines.isEmpty
                && issue.scenePrimaryBrainLines.isEmpty
                && issue.sceneHeartbeatLines.isEmpty
                && issue.sceneRuntimeLogLines.isEmpty {
                Text("暂无现场快照。")
                    .font(.system(size: 13, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
        }
    }

    private func agentAnalysisParts(for issue: DebugIssue) -> IssueAgentAnalysisParts {
        guard let text = issue.devTask?.displayResult else { return .empty }
        return IssueAgentAnalysisParser.parse(text)
    }

    @ViewBuilder
    private func rootCauseSection(_ issue: DebugIssue) -> some View {
        let parts = agentAnalysisParts(for: issue)
        issueSection(title: "4. Agent 分析", subtitle: "根因定位与证据") {
            if let task = issue.devTask {
                agentTaskMeta(task: task, issue: issue)
                if task.isActive && parts.rootCause.isEmpty {
                    HStack(spacing: 8) {
                        ProgressView()
                            .controlSize(.small)
                            .tint(DevTheme.sand)
                        Text("Agent 正在分析…")
                            .font(.system(size: 13, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                } else if !parts.rootCause.isEmpty {
                    analysisBody(parts.rootCause)
                } else if !task.displayResult.isEmpty {
                    analysisBody(task.displayResult)
                } else {
                    Text("分析已完成，但暂无根因结论。")
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }
            } else if issue.taskId != nil {
                Text("Dev Task 详情尚未加载。")
                    .font(.system(size: 13, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            } else {
                Text("尚未创建 Agent 分析任务。")
                    .font(.system(size: 13, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
        }
    }

    @ViewBuilder
    private func fixRecommendationSection(_ issue: DebugIssue) -> some View {
        let parts = agentAnalysisParts(for: issue)
        issueSection(title: "5. 修复建议", subtitle: "具体改法与后续动作") {
            if let task = issue.devTask {
                if task.isActive && parts.fixRecommendation.isEmpty {
                    Text("等待 Agent 给出修复建议…")
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else if !parts.fixRecommendation.isEmpty {
                    FixRecommendationCardsView(
                        items: parts.fixItems,
                        fallbackText: parts.fixRecommendation
                    )
                } else if !parts.hasExplicitSplit, !parts.rootCause.isEmpty {
                    Text("Agent 未单独分段，请先看上方「Agent 分析」。")
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else {
                    Text("暂无修复建议。")
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }
            } else {
                Text("分析任务创建后将显示修复建议。")
                    .font(.system(size: 13, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
        }
    }

    private func analysisBody(_ text: String) -> some View {
        DevSelectableText(text: text, color: Color.white.opacity(0.92))
    }

    @ViewBuilder
    private func agentTaskMeta(task: DevTask, issue: DebugIssue) -> some View {
        HStack(spacing: 8) {
            Text(task.statusTitle)
                .font(.system(size: 12, weight: .bold, design: .rounded))
                .foregroundStyle(task.isActive ? DevTheme.sand : DevTheme.ok)
            DevTokenBadge(usage: task.tokenUsage)
            Spacer()
            if let taskId = issue.taskId {
                Text("task #\(taskId)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(DevTheme.dim)
            }
        }
        if !task.finishedAtCaption.isEmpty {
            Text(task.finishedAtCaption)
                .font(.system(size: 11, design: .rounded))
                .foregroundStyle(DevTheme.dim)
        }
    }

    private func gatewayErrorSection(_ issue: DebugIssue) -> some View {
        issueSection(title: "Gateway", subtitle: "Issue 网关错误") {
            DevSelectableText(text: issue.error, color: DevTheme.off)
        }
    }

    private func issueSection<Content: View>(
        title: String,
        subtitle: String,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 15, weight: .bold, design: .rounded))
                        .foregroundStyle(DevTheme.sand)
                    Text(subtitle)
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }
                content()
            }
        }
    }

    private func detailRow(
        label: String,
        value: String,
        mono: Bool = false,
        prominent: Bool = false,
        muted: Bool = false,
        accent: Color? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            DevSelectableText(
                text: value,
                font: mono ? .system(size: 13, design: .monospaced) : .system(size: prominent ? 16 : 14, design: .rounded),
                weight: prominent ? .semibold : .medium,
                mono: mono,
                color: accent ?? (muted ? DevTheme.dim : DevTheme.mist),
                prominent: prominent
            )
        }
    }

    private func bulletBlock(label: String, lines: [String]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.system(size: 11, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.dim)
            VStack(alignment: .leading, spacing: 4) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    HStack(alignment: .top, spacing: 8) {
                        Text("•")
                            .foregroundStyle(DevTheme.sand.opacity(0.8))
                        DevSelectableText(text: line, font: .system(size: 13, design: .rounded))
                    }
                }
            }
        }
    }

    private func reload() async {
        do {
            issue = try await DevClient.fetchIssue(
                brainURL: store.activeBrainURL,
                token: DevSettings.adminToken,
                issueId: issueId
            )
            error = nil
        } catch let err {
            self.error = err.localizedDescription
        }
    }
}

struct IssueAttachmentGallery: View {
    let attachments: [DebugAttachment]
    let intentId: Int
    let brainURL: String

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(attachments) { attachment in
                    IssueAttachmentThumbnail(
                        attachment: attachment,
                        intentId: intentId,
                        brainURL: brainURL
                    )
                }
            }
        }
    }
}

private struct IssueAttachmentThumbnail: View {
    let attachment: DebugAttachment
    let intentId: Int
    let brainURL: String

    @State private var image: UIImage?
    @State private var failed = false

    var body: some View {
        Group {
            if attachment.isImage, let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else if attachment.isImage {
                loadingOrFailedPlaceholder
            } else {
                nonImagePlaceholder
            }
        }
        .frame(width: 120, height: 120)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .task(id: "\(attachment.assetId)|\(intentId)|\(brainURL)|\(attachment.kind)") {
            guard attachment.isImage else { return }
            await load()
        }
    }

    private var loadingOrFailedPlaceholder: some View {
        ZStack {
            DevTheme.chip
            if failed {
                VStack(spacing: 4) {
                    Image(systemName: "photo")
                        .foregroundStyle(DevTheme.dim)
                    Text(attachment.assetId)
                        .font(.system(size: 9, design: .monospaced))
                        .foregroundStyle(DevTheme.dim)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
                .padding(6)
            } else {
                ProgressView()
                    .tint(DevTheme.sand)
            }
        }
    }

    private var nonImagePlaceholder: some View {
        ZStack {
            DevTheme.chip
            VStack(spacing: 6) {
                Image(systemName: iconName)
                    .font(.system(size: 22))
                    .foregroundStyle(DevTheme.sand)
                Text(attachment.displayLabel)
                    .font(.system(size: 10, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                    .lineLimit(3)
                    .multilineTextAlignment(.center)
            }
            .padding(8)
        }
    }

    private var iconName: String {
        switch attachment.kind {
        case "audio": return "waveform"
        case "video": return "film"
        case "file": return "doc"
        default: return "paperclip"
        }
    }

    private func load() async {
        do {
            let data = try await DevClient.fetchIssueAttachmentData(
                brainURL: brainURL,
                assetId: attachment.assetId,
                intentId: intentId
            )
            if let loaded = UIImage(data: data) {
                image = loaded
                failed = false
            } else {
                failed = true
            }
        } catch {
            failed = true
        }
    }
}
