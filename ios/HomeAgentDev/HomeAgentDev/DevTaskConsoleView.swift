import SwiftUI

struct DevTaskConsoleView: View {
    @EnvironmentObject private var store: DevStore
    @State private var showNewTaskSheet = false

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    taskList
                }
            }
            .navigationTitle("Dev Task")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .sheet(isPresented: $showNewTaskSheet) {
                DevNewTaskSheet()
                    .environmentObject(store)
            }
        }
    }

    private var taskList: some View {
        List {
            Section {
                DevCategoryChipRow(selection: $store.devTaskCategoryFilter, includeAll: true)
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    .listRowBackground(Color.clear)
                    .onChange(of: store.devTaskCategoryFilter) { _ in
                        Task { await store.loadDevTasks(reset: true, showSpinner: true) }
                    }
            } header: {
                Text("筛选")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                    .textCase(nil)
            }

            Section {
                newTaskButton
                    .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 4, trailing: 16))
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }

            if let err = store.devTasksError, !err.isEmpty {
                Section {
                    Text(err)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.off)
                        .listRowBackground(Color.clear)
                }
            }

            Section {
                if store.isLoadingDevTasks && store.devTasks.isEmpty {
                    HStack {
                        Spacer()
                        ProgressView("加载中…")
                            .tint(DevTheme.sand)
                        Spacer()
                    }
                    .listRowBackground(Color.clear)
                } else if store.devTasks.isEmpty {
                    VStack(spacing: 14) {
                        Image(systemName: "terminal")
                            .font(.system(size: 36))
                            .foregroundStyle(DevTheme.sand.opacity(0.7))
                        Text("还没有 Dev Task")
                            .font(.system(size: 17, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.mist)
                        Text("点下方「新增 Dev Task」下发任务到 Mac Cursor Agent。")
                            .font(.system(size: 14, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                            .multilineTextAlignment(.center)
                        Button("新增任务") { showNewTaskSheet = true }
                            .buttonStyle(.borderedProminent)
                            .tint(DevTheme.sand)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 28)
                    .listRowBackground(Color.clear)
                } else {
                    ForEach(store.devTasks) { task in
                        NavigationLink {
                            DevTaskDetailView(taskId: task.taskId)
                        } label: {
                            DevTaskRowView(task: task)
                        }
                        .listRowBackground(DevTheme.panel)
                        .listRowSeparatorTint(DevTheme.panelStroke)
                        .onAppear {
                            if task.taskId == store.devTasks.last?.taskId,
                               !store.devTasksExhausted,
                               !store.isLoadingDevTasks {
                                Task { await store.loadDevTasks(reset: false, showSpinner: false) }
                            }
                        }
                    }
                }
            } header: {
                Text("任务列表")
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                    .textCase(nil)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .refreshable {
            await store.loadDevTasks(reset: true, showSpinner: false)
        }
    }

    private var newTaskButton: some View {
        Button {
            showNewTaskSheet = true
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 18, weight: .semibold))
                Text("新增 Dev Task")
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DevTheme.ink.opacity(0.45))
            }
            .foregroundStyle(DevTheme.ink)
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(DevTheme.sand)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("新增 Dev Task")
    }
}

struct DevNewTaskSheet: View {
    @EnvironmentObject private var store: DevStore
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var category = "tech_discuss"
    @State private var targetHandle = "controller"
    @State private var localError = ""
    @State private var pendingAttachments: [PendingDevAttachment] = []
    @FocusState private var inputFocused: Bool

    private var canSubmit: Bool {
        let hasText = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        let hasAttachments = !pendingAttachments.isEmpty
        return (hasText || hasAttachments) && !store.isSendingDevTask
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        Text("描述要交给 Mac Cursor Agent 处理的问题。User 一键反馈也会自动创建 Dev Task。")
                            .font(.system(size: 14, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                            .fixedSize(horizontal: false, vertical: true)

                        VStack(alignment: .leading, spacing: 12) {
                            DevTheme.sectionLabel("任务类型")
                            DevCategoryPickerGrid(selection: $category)
                        }

                        VStack(alignment: .leading, spacing: 12) {
                            DevTheme.sectionLabel("派给")
                            Picker("Handle", selection: $targetHandle) {
                                ForEach(ChatMentionCatalog.fleetAssignees) { agent in
                                    Text(agent.pickerLabel).tag(agent.handle)
                                }
                            }
                            .pickerStyle(.menu)
                            .tint(DevTheme.sand)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(
                                RoundedRectangle(cornerRadius: 14, style: .continuous)
                                    .fill(DevTheme.chip)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                                            .stroke(DevTheme.panelStroke, lineWidth: 1)
                                    )
                            )
                        }

                        VStack(alignment: .leading, spacing: 12) {
                            DevTheme.sectionLabel("附件")
                            DevAttachmentComposer(pending: $pendingAttachments)
                        }

                        if !localError.isEmpty {
                            Text(localError)
                                .font(.system(size: 13, design: .rounded))
                                .foregroundStyle(DevTheme.off)
                        }
                    }
                    .padding(20)
                }
                .devDismissKeyboardOnTap($inputFocused)

                newTaskComposer
            }
            .background(DevTheme.ink.ignoresSafeArea())
            .navigationTitle("新建 Dev Task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                        .disabled(store.isSendingDevTask)
                }
            }
            .devKeyboardDoneToolbar($inputFocused)
        }
        .presentationDetents([.fraction(0.88), .large])
        .presentationDragIndicator(.visible)
        .onAppear {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                inputFocused = true
            }
        }
        .onChange(of: category) { _ in
            inputFocused = false
        }
    }

    private var newTaskComposer: some View {
        VStack(alignment: .leading, spacing: 12) {
            DevTheme.sectionLabel("问题内容")
            TextField(
                "例如：分析 intent 1475 失败原因，给出修复建议",
                text: $text,
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .lineLimit(3...8)
            .focused($inputFocused)
            .foregroundStyle(DevTheme.mist)
            .padding(14)
            .frame(minHeight: 120, maxHeight: 180, alignment: .topLeading)
            .background(
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(DevTheme.chip)
                    .overlay(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .stroke(DevTheme.panelStroke, lineWidth: 1)
                    )
            )

            Button {
                submit()
            } label: {
                HStack(spacing: 8) {
                    if store.isSendingDevTask {
                        ProgressView().tint(DevTheme.ink)
                    }
                    Text(store.isSendingDevTask ? "下发中…" : "下发到 @\(targetHandle)")
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(canSubmit ? DevTheme.sand : DevTheme.sand.opacity(0.35))
                )
                .foregroundStyle(DevTheme.ink)
            }
            .disabled(!canSubmit)
        }
        .padding(.horizontal, 20)
        .padding(.top, 12)
        .padding(.bottom, 16)
        .background(
            DevTheme.panel
                .overlay(alignment: .top) {
                    Rectangle()
                        .fill(DevTheme.panelStroke)
                        .frame(height: 1)
                }
                .ignoresSafeArea(edges: .bottom)
        )
    }

    private func submit() {
        localError = ""
        inputFocused = false
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !pendingAttachments.isEmpty else {
            localError = "请填写问题内容或添加附件"
            return
        }
        Task {
            if await store.sendDevTask(
                text: trimmed,
                category: category,
                targetHandle: targetHandle,
                pendingAttachments: pendingAttachments
            ) != nil {
                pendingAttachments = []
                dismiss()
            } else {
                localError = store.devTasksError ?? "下发失败"
            }
        }
    }
}

struct DevTaskRowView: View {
    let task: DevTask

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                DevCategoryBadge(
                    categoryId: task.category,
                    categoryLabel: task.categoryLabel,
                    prominent: true
                )
                Spacer()
                Text(task.relativeLabel)
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
            HStack {
                Text(task.statusTitle)
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .foregroundStyle(statusColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Capsule().fill(statusColor.opacity(0.16)))
                Spacer()
                if !task.finishedAtCaption.isEmpty {
                    Text(task.finishedAtCaption)
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                } else if task.isActive {
                    Text("执行中…")
                        .font(.system(size: 11, design: .rounded))
                        .foregroundStyle(DevTheme.sand.opacity(0.85))
                }
            }
            Text(task.text)
                .font(.system(size: 15, weight: .medium, design: .rounded))
                .foregroundStyle(DevTheme.mist)
                .lineLimit(3)
            if !task.targetHandle.isEmpty {
                Text("@\(task.targetHandle)")
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.sand.opacity(0.9))
            }
            Text("会话 #\(task.threadId)")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(DevTheme.dim)
            if task.tokenUsage.hasData && task.displayResult.isEmpty {
                Text(task.tokenUsage.compactLabel)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(DevTheme.dim)
            }
            if !task.displayResult.isEmpty {
                HStack(spacing: 8) {
                    Text(task.displayResult)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                        .lineLimit(2)
                    Spacer(minLength: 0)
                    DevTokenBadge(usage: task.tokenUsage)
                }
            } else if task.isActive {
                Text("Agent 执行中…")
                    .font(.system(size: 12, design: .rounded))
                    .foregroundStyle(DevTheme.sand.opacity(0.85))
            }
        }
        .padding(.vertical, 4)
    }

    private var statusColor: Color {
        if task.status == "failed" || task.status == "error" { return DevTheme.off }
        if task.status == "cancelled" { return DevTheme.dim }
        if task.status == "succeeded" { return DevTheme.ok }
        return DevTheme.sand
    }
}

struct DevTaskDetailView: View {
    @EnvironmentObject private var store: DevStore
    let taskId: Int
    @State private var thread: DevTask?
    @State private var followUp = ""
    @State private var followUpAttachments: [PendingDevAttachment] = []
    @State private var loadError: String?
    @FocusState private var inputFocused: Bool

    private enum ScrollAnchor {
        static let top = "dev-task-scroll-top"
    }

    private var bottomScrollTarget: Int? {
        messages.last?.taskId
    }

    private var messages: [DevTask] {
        if let thread, !thread.threadMessages.isEmpty {
            return thread.threadMessages
        }
        if let thread {
            return [thread]
        }
        return []
    }

    var body: some View {
        ZStack {
            DevTheme.ink.ignoresSafeArea()
            VStack(spacing: 0) {
                if let err = loadError, !err.isEmpty {
                    Text(err)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.off)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                }
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            if let thread {
                                categoryHeader(thread)
                                    .id(ScrollAnchor.top)
                            } else {
                                Color.clear
                                    .frame(height: 1)
                                    .id(ScrollAnchor.top)
                            }
                            ForEach(messages, id: \.taskId) { msg in
                                DevThreadMessageBlock(
                                    message: msg,
                                    onCancel: msg.isActive
                                        ? {
                                            Task {
                                                if let updated = await store.cancelDevTask(taskId: msg.taskId) {
                                                    thread = await store.fetchDevTask(taskId: updated.threadId) ?? updated
                                                }
                                            }
                                        }
                                        : nil
                                )
                                .id(msg.taskId)
                            }
                        }
                        .padding(16)
                    }
                    .devDismissKeyboardOnTap($inputFocused)
                    .overlay(alignment: .bottomTrailing) {
                        scrollJumpControls(proxy: proxy)
                            .padding(.trailing, 10)
                            .padding(.bottom, 10)
                    }
                }
                followUpComposer
            }
        }
        .navigationTitle(threadTitle)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(DevTheme.ink, for: .navigationBar)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .devKeyboardDoneToolbar($inputFocused)
        .task(id: taskId) {
            await reload()
        }
        .onReceive(Timer.publish(every: 3, on: .main, in: .common).autoconnect()) { _ in
            if thread?.isActive == true || messages.contains(where: \.isActive) {
                Task { await reload() }
            }
        }
    }

    private var threadTitle: String {
        guard let thread else { return "#\(taskId)" }
        return "会话 #\(thread.threadId)"
    }

    private func scrollJumpControls(proxy: ScrollViewProxy) -> some View {
        VStack(spacing: 8) {
            scrollJumpButton(title: "顶部", systemImage: "arrow.up.to.line") {
                withAnimation(.easeInOut(duration: 0.25)) {
                    proxy.scrollTo(ScrollAnchor.top, anchor: .top)
                }
            }
            scrollJumpButton(title: "底部", systemImage: "arrow.down.to.line") {
                scrollToBottom(proxy: proxy)
            }
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(DevTheme.panel.opacity(0.94))
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .stroke(DevTheme.panelStroke, lineWidth: 1)
                )
        )
    }

    private func scrollJumpButton(
        title: String,
        systemImage: String,
        action: @escaping () -> Void
    ) -> some View {
        Button {
            inputFocused = false
            action()
        } label: {
            VStack(spacing: 3) {
                Image(systemName: systemImage)
                    .font(.system(size: 13, weight: .semibold))
                Text(title)
                    .font(.system(size: 10, weight: .semibold, design: .rounded))
            }
            .foregroundStyle(DevTheme.sand)
            .frame(width: 44, height: 44)
            .background(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(DevTheme.chip)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel("回到\(title)")
    }

    private func scrollToBottom(proxy: ScrollViewProxy) {
        guard let target = bottomScrollTarget else {
            withAnimation(.easeInOut(duration: 0.25)) {
                proxy.scrollTo(ScrollAnchor.top, anchor: .top)
            }
            return
        }
        withAnimation(.easeInOut(duration: 0.25)) {
            proxy.scrollTo(target, anchor: .bottom)
        }
    }

    private func categoryHeader(_ thread: DevTask) -> some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                DevTheme.sectionLabel("会话类别")
                HStack {
                    DevCategoryBadge(
                        categoryId: thread.category,
                        categoryLabel: thread.categoryLabel,
                        prominent: true
                    )
                    Spacer()
                }
                DevCategoryChipRow(selection: Binding(
                    get: { thread.category },
                    set: { newCat in
                        inputFocused = false
                        Task {
                            if let updated = await store.updateThreadCategory(
                                taskId: thread.threadId,
                                category: newCat
                            ) {
                                self.thread = updated
                            }
                        }
                    }
                ))
                Text("修改类别只影响本会话归类，续聊消息自动沿用。")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                if thread.threadTokenUsage.hasData {
                    DevTheme.sectionLabel("会话 Token")
                    Text(thread.threadTokenUsage.compactLabel)
                        .font(.system(size: 13, weight: .semibold, design: .monospaced))
                        .foregroundStyle(DevTheme.sand)
                }
            }
        }
    }

    private var followUpComposer: some View {
        DevPanel {
            VStack(alignment: .leading, spacing: 10) {
                DevTheme.sectionLabel("继续讨论")
                Text("同一线程会续接 Mac 上 Cursor Agent 上下文，不会散成多条无关任务。")
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
                    .onTapGesture {
                        inputFocused = false
                    }
                TextField("追问或补充说明…", text: $followUp, axis: .vertical)
                    .textFieldStyle(.plain)
                    .lineLimit(2...5)
                    .focused($inputFocused)
                    .foregroundStyle(DevTheme.mist)
                DevAttachmentComposer(pending: $followUpAttachments)
                    .onTapGesture {
                        inputFocused = false
                    }
                Button {
                    inputFocused = false
                    let parentId = messages.last?.taskId ?? taskId
                    let trimmed = followUp.trimmingCharacters(in: .whitespacesAndNewlines)
                    let pending = followUpAttachments
                    guard !trimmed.isEmpty || !pending.isEmpty else { return }
                    Task {
                        if let fresh = await store.sendDevTaskFollowUp(
                            threadRootTaskId: parentId,
                            text: trimmed,
                            pendingAttachments: pending
                        ) {
                            followUp = ""
                            followUpAttachments = []
                            let rootId = thread?.threadId ?? taskId
                            if let full = await store.fetchDevTask(taskId: rootId) {
                                thread = full
                            } else if let partial = await store.fetchDevTask(taskId: fresh.taskId) {
                                thread = partial
                            } else {
                                thread = fresh
                            }
                        }
                    }
                } label: {
                    HStack {
                        if store.isSendingDevTask {
                            ProgressView().tint(DevTheme.ink)
                        }
                        Text(store.isSendingDevTask ? "发送中…" : "发送")
                            .font(.system(size: 15, weight: .semibold, design: .rounded))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 10)
                    .background(RoundedRectangle(cornerRadius: 12).fill(DevTheme.sand))
                    .foregroundStyle(DevTheme.ink)
                }
                .disabled(
                    store.isSendingDevTask
                        || (followUp.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            && followUpAttachments.isEmpty)
                )
            }
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
    }

    private func reload() async {
        if let fresh = await store.fetchDevTask(taskId: taskId) {
            thread = fresh
            loadError = nil
        } else if loadError == nil {
            loadError = store.devTasksError ?? "加载失败"
        }
    }
}

struct DevThreadMessageBlock: View {
    @EnvironmentObject private var store: DevStore
    let message: DevTask
    var onCancel: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(message.isRoot ? "你" : "你 · 续聊")
                    .font(.system(size: 11, weight: .bold, design: .rounded))
                    .foregroundStyle(DevTheme.sand)
                Spacer()
                Text(message.sentAtCaption.isEmpty ? message.timeLabel : message.sentAtCaption)
                    .font(.system(size: 11, design: .rounded))
                    .foregroundStyle(DevTheme.dim)
            }
            if !message.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(message.text)
                    .font(.system(size: 15, weight: .medium, design: .rounded))
                    .foregroundStyle(DevTheme.mist)
                    .textSelection(.enabled)
            }
            if !message.attachments.isEmpty {
                DevAttachmentGallery(
                    attachments: message.attachments,
                    scopeId: message.attachmentScope,
                    brainURL: store.activeBrainURL
                )
            }
            if !message.displayResult.isEmpty || message.tokenUsage.hasData {
                DevPanel {
                    VStack(alignment: .leading, spacing: 6) {
                        HStack(spacing: 8) {
                            Text("Agent · \(message.statusTitle)")
                                .font(.system(size: 11, weight: .semibold, design: .rounded))
                                .foregroundStyle(DevTheme.sand)
                            DevTokenBadge(usage: message.tokenUsage)
                            Spacer(minLength: 4)
                            if message.isActive, let onCancel {
                                agentCancelButton(action: onCancel)
                            } else if !message.finishedAtCaption.isEmpty {
                                Text(message.finishedAtCaption)
                                    .font(.system(size: 11, design: .rounded))
                                    .foregroundStyle(DevTheme.dim)
                            }
                        }
                        if !message.displayResult.isEmpty {
                            Text(message.displayResult)
                                .font(.system(size: 13, design: .rounded))
                                .foregroundStyle(Color.white.opacity(0.9))
                                .textSelection(.enabled)
                        }
                        if message.tokenUsage.hasData {
                            Text(message.tokenUsage.detailTooltip)
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(DevTheme.dim)
                        }
                    }
                }
            } else if message.isActive {
                HStack(alignment: .center, spacing: 10) {
                    Text("Agent 执行中…")
                        .font(.system(size: 12, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                    Spacer(minLength: 0)
                    if let onCancel {
                        agentCancelButton(action: onCancel)
                    }
                }
            }
        }
    }

    private func agentCancelButton(action: @escaping () -> Void) -> some View {
        Button(role: .destructive, action: action) {
            if store.isCancellingDevTask {
                ProgressView()
                    .controlSize(.small)
                    .tint(DevTheme.off)
            } else {
                Text(cancelLabel)
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.mini)
        .tint(DevTheme.off)
        .disabled(store.isCancellingDevTask)
        .accessibilityLabel(cancelHint)
    }

    private var cancelLabel: String {
        let status = message.status.lowercased()
        if status.contains("queued") || status.contains("waiting") || status.contains("parsed") {
            return "撤销"
        }
        return "中断"
    }

    private var cancelHint: String {
        let status = message.status.lowercased()
        if status.contains("queued") || status.contains("waiting") || status.contains("parsed") {
            return "撤销排队中的任务"
        }
        return "中断正在执行的 Agent"
    }
}

struct DevTokenBadge: View {
    let usage: DevTokenUsage

    var body: some View {
        if usage.hasData {
            Text(usage.replyBadge)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .foregroundStyle(DevTheme.ink)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(Capsule().fill(DevTheme.sand.opacity(0.9)))
                .accessibilityLabel(usage.detailTooltip)
        }
    }
}
