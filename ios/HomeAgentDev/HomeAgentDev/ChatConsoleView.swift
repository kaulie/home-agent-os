import SwiftUI

struct ChatConsoleView: View {
    @EnvironmentObject private var store: DevStore
    @State private var draft = ""
    @State private var promoteMessage: AgentChatMessage?
    @State private var promoteText = ""
    @State private var promoteHandle = "brain"
    @State private var promoteCategory = "feature"
    @State private var selectedBackgroundIds: Set<Int> = []
    @FocusState private var inputFocused: Bool
    @State private var mentionQuery: String?
    @State private var showMentionPicker = false
    /// Long-press reaction float target (nil = hidden).
    @State private var reactionMessageId: Int?

    var body: some View {
        NavigationStack {
            ZStack {
                DevTheme.ink.ignoresSafeArea()
                DevTabRootLayout {
                    VStack(spacing: 0) {
                        if let err = store.chatError, !err.isEmpty {
                            Text(err)
                                .font(.system(size: 13, design: .rounded))
                                .foregroundStyle(DevTheme.off)
                                .padding(.horizontal, 16)
                                .padding(.top, 8)
                        }
                        if store.isLoadingChat && store.chatMessages.isEmpty {
                            Spacer()
                            ProgressView("加载 Chat…")
                                .tint(DevTheme.sand)
                            Spacer()
                        } else if store.chatMessages.isEmpty {
                            emptyState
                        } else {
                            messageList
                        }
                        composer
                            .zIndex(2)
                    }
                    .overlay(alignment: .bottom) {
                        if showMentionPicker, let query = mentionQuery {
                            mentionSuggestions(query: query)
                                .frame(maxWidth: .infinity)
                                .padding(.horizontal, 10)
                                .padding(.bottom, composerBarHeight + 8)
                                .zIndex(3)
                        }
                    }
                }
                if let reactionId = reactionMessageId,
                   let reactionMsg = store.chatMessages.first(where: { $0.id == reactionId }) {
                    Color.black.opacity(0.28)
                        .ignoresSafeArea()
                        .onTapGesture {
                            withAnimation(.easeOut(duration: 0.15)) {
                                reactionMessageId = nil
                            }
                        }
                    reactionFloat(for: reactionMsg)
                        .padding(.horizontal, 28)
                        .transition(.scale(scale: 0.92).combined(with: .opacity))
                }
            }
            .navigationTitle("Chat")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(DevTheme.ink, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .onChange(of: draft) { _ in
                syncMentionPicker()
            }
            .refreshable {
                await store.loadChat(reset: true, showSpinner: false)
            }
            .sheet(item: $promoteMessage) { msg in
                promoteSheet(message: msg)
            }
            .devDismissKeyboardOnTap($inputFocused)
            .devKeyboardDoneToolbar($inputFocused)
        }
    }

    private var emptyState: some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 40))
                .foregroundStyle(DevTheme.sand.opacity(0.75))
            Text("Agent 群聊")
                .font(.system(size: 18, weight: .semibold, design: .rounded))
                .foregroundStyle(DevTheme.mist)
            Text("发消息用 @ 选择 Agent；未 @ 的消息仅自己可见。\n在家连 LAN Brain；在外连云端 Brain（需家里 Mac 开 chat + 隧道）。")
                .font(.system(size: 13, design: .rounded))
                .foregroundStyle(DevTheme.dim)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 28)
            Spacer()
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 14) {
                    ForEach(store.chatMessages) { msg in
                        chatRow(msg)
                            .id(msg.id)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 16)
            }
                            .onChange(of: store.chatMessages.count) { _ in
                                scrollToBottom(proxy: proxy)
                            }
                            .onChange(of: store.chatMessages.last?.id) { _ in
                                scrollToBottom(proxy: proxy)
                            }
            .onAppear {
                scrollToBottom(proxy: proxy)
            }
        }
    }

    private func scrollToBottom(proxy: ScrollViewProxy) {
        if let last = store.chatMessages.last {
            withAnimation(.easeOut(duration: 0.2)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    @ViewBuilder
    private func chatRow(_ msg: AgentChatMessage) -> some View {
        HStack(alignment: .bottom, spacing: 8) {
            if msg.isFromBoss {
                Spacer(minLength: 36)
            } else {
                avatar(for: msg.fromHandle)
            }

            VStack(alignment: msg.isFromBoss ? .trailing : .leading, spacing: 6) {
                HStack(spacing: 8) {
                    if !msg.isFromBoss {
                        Text(msg.senderLabel)
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                            .foregroundStyle(DevTheme.sand)
                    }
                    Spacer(minLength: 0)
                    Text(msg.timeLabel)
                        .font(.system(size: 10, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }

                Group {
                    if msg.recalled {
                        Text("（已撤回）")
                            .font(.system(size: 14, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    } else {
                        Text(msg.body)
                            .font(.system(size: 15, design: .rounded))
                            .foregroundStyle(msg.isFromBoss ? DevTheme.ink : DevTheme.mist)
                            .textSelection(.enabled)
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(msg.isFromBoss ? DevTheme.sand : DevTheme.panel)
                        .opacity(msg.isPending ? 0.72 : 1)
                )
                .onLongPressGesture(minimumDuration: 1.0) {
                    guard !msg.isPending, !msg.recalled else { return }
                    inputFocused = false
                    DevKeyboard.dismiss()
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.86)) {
                        reactionMessageId = msg.id
                    }
                }

                if !msg.acks.isEmpty {
                    sharedAckChip(
                        names: msg.sharedAckParticipantLabels,
                        messageId: msg.id,
                        bossHasAcked: msg.bossHasAcked,
                        canToggle: !msg.isFromBoss && !msg.recalled
                    )
                }

                if !msg.audienceLabel.isEmpty || msg.isPending {
                    Text(msg.isPending ? "发送中…" : msg.audienceLabel)
                        .font(.system(size: 10, design: .rounded))
                        .foregroundStyle(DevTheme.dim)
                }

                Text("#\(msg.id)")
                    .font(.system(size: 9, design: .monospaced))
                    .foregroundStyle(DevTheme.dim.opacity(0.7))
            }
            .frame(maxWidth: 320, alignment: msg.isFromBoss ? .trailing : .leading)

            if msg.isFromBoss {
                avatar(for: "boss")
            } else {
                Spacer(minLength: 36)
            }
        }
    }

    private func avatar(for handle: String) -> some View {
        let label = handle.prefix(1).uppercased()
        return Text(String(label))
            .font(.system(size: 13, weight: .bold, design: .rounded))
            .foregroundStyle(DevTheme.ink)
            .frame(width: 32, height: 32)
            .background(Circle().fill(DevTheme.sand.opacity(0.9)))
    }

    private func reactionFloat(for msg: AgentChatMessage) -> some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                ForEach(ChatReactionKind.allCases) { kind in
                    let selected = kind == .ok && msg.bossHasAcked
                    Button {
                        Task {
                            if kind == .ok {
                                if msg.isFromBoss { return }
                                if msg.bossHasAcked {
                                    await store.unackChatMessage(msg.id)
                                } else {
                                    await store.ackChatMessage(msg.id)
                                }
                            }
                            withAnimation(.easeOut(duration: 0.12)) {
                                reactionMessageId = nil
                            }
                        }
                    } label: {
                        VStack(spacing: 4) {
                            Text(kind.emoji)
                                .font(.system(size: 22))
                            Text(kind.title)
                                .font(.system(size: 10, weight: .medium, design: .rounded))
                                .foregroundStyle(DevTheme.mist.opacity(0.9))
                        }
                        .frame(width: 56)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(selected ? DevTheme.sand.opacity(0.28) : DevTheme.panel)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(
                                    DevTheme.sand.opacity(selected ? 0.65 : 0.2),
                                    lineWidth: 1
                                )
                        )
                    }
                    .buttonStyle(.plain)
                    .disabled(kind == .ok && msg.isFromBoss)
                    .opacity(kind == .ok && msg.isFromBoss ? 0.35 : 1)
                }
            }

            Button {
                reactionMessageId = nil
                promoteMessage = msg
                promoteText = msg.body
                selectedBackgroundIds = defaultBackgroundSelection(anchor: msg)
            } label: {
                Text("转为 Dev Task")
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.sand)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
            }
            .buttonStyle(.plain)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(DevTheme.ink.opacity(0.96))
                .shadow(color: .black.opacity(0.35), radius: 12, y: 4)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(DevTheme.sand.opacity(0.25), lineWidth: 1)
        )
    }

    private func sharedAckChip(
        names: [String],
        messageId: Int,
        bossHasAcked: Bool,
        canToggle: Bool
    ) -> some View {
        Button {
            guard canToggle else { return }
            Task {
                if bossHasAcked {
                    await store.unackChatMessage(messageId)
                } else {
                    await store.ackChatMessage(messageId)
                }
            }
        } label: {
            HStack(spacing: 6) {
                Text("👌")
                    .font(.system(size: 13))
                Text(names.joined(separator: "、"))
                    .font(.system(size: 11, weight: .medium, design: .rounded))
                    .foregroundStyle(DevTheme.sand.opacity(0.95))
                    .lineLimit(2)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(
                Capsule().fill(
                    bossHasAcked
                        ? DevTheme.sand.opacity(0.28)
                        : DevTheme.sand.opacity(0.16)
                )
            )
            .overlay(
                Capsule().stroke(
                    DevTheme.sand.opacity(bossHasAcked ? 0.55 : 0.22),
                    lineWidth: 1
                )
            )
        }
        .buttonStyle(.plain)
        .disabled(!canToggle)
    }

    private var composer: some View {
        inputBar
            .background(DevTheme.ink)
    }

    private func syncMentionPicker() {
        if let query = ChatMentionAutocomplete.activeQuery(in: draft) {
            mentionQuery = query
            showMentionPicker = true
            return
        }
        showMentionPicker = false
        mentionQuery = nil
    }

    private let composerBarHeight: CGFloat = 64

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField("消息… 输入 @ 选择 Agent", text: $draft, axis: .vertical)
                .lineLimit(1...6)
                .focused($inputFocused)
                .font(.system(size: 15, design: .rounded))
                .foregroundStyle(DevTheme.mist)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 12).fill(DevTheme.panel))
            Button {
                let text = draft
                draft = ""
                inputFocused = false
                DevKeyboard.dismiss()
                Task {
                    await store.sendChatMessage(text)
                }
            } label: {
                Group {
                    if store.isSendingChat {
                        ProgressView().tint(DevTheme.ink)
                    } else {
                        Image(systemName: "paperplane.fill")
                            .foregroundStyle(DevTheme.ink)
                    }
                }
                .padding(12)
                .background(Circle().fill(DevTheme.sand))
            }
            .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || store.isSendingChat)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    @ViewBuilder
    private func mentionSuggestions(query: String) -> some View {
        let matches = ChatMentionCatalog.filtered(query: query)
        if matches.isEmpty {
            EmptyView()
        } else {
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(matches) { agent in
                        Button {
                            ChatMentionAutocomplete.apply(handle: agent.handle, to: &draft)
                            syncMentionPicker()
                            inputFocused = true
                        } label: {
                            HStack(spacing: 12) {
                                Text(String(agent.handle.prefix(1)).uppercased())
                                    .font(.system(size: 12, weight: .bold, design: .rounded))
                                    .foregroundStyle(DevTheme.ink)
                                    .frame(width: 28, height: 28)
                                    .background(Circle().fill(DevTheme.sand))
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(agent.mentionToken)
                                        .font(.system(size: 15, weight: .semibold, design: .rounded))
                                        .foregroundStyle(DevTheme.sand)
                                    Text(agent.displayName)
                                        .font(.system(size: 12, design: .rounded))
                                        .foregroundStyle(DevTheme.dim)
                                        .lineLimit(1)
                                        .minimumScaleFactor(0.85)
                                }
                                Spacer(minLength: 0)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 11)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if agent.id != matches.last?.id {
                            Divider().overlay(DevTheme.panelStroke)
                        }
                    }
                }
            }
            .frame(maxWidth: .infinity)
            .frame(maxHeight: 260)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(DevTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16, style: .continuous)
                            .stroke(DevTheme.panelStroke, lineWidth: 1)
                    )
                    .shadow(color: .black.opacity(0.42), radius: 16, y: 8)
            )
        }
    }

    @ViewBuilder
    private func promoteSheet(message: AgentChatMessage) -> some View {
        let candidates = backgroundCandidates(anchor: message)
        NavigationStack {
            Form {
                Section("任务") {
                    TextField("可执行描述", text: $promoteText, axis: .vertical)
                        .lineLimit(3...8)
                }
                Section("派给") {
                    Picker("Handle", selection: $promoteHandle) {
                        ForEach(ChatMentionCatalog.agents.filter { $0.handle != "all" }, id: \.handle) { agent in
                            Text(agent.pickerLabel).tag(agent.handle)
                        }
                    }
                }
                Section("分类") {
                    Picker("分类", selection: $promoteCategory) {
                        ForEach(DevTaskCategory.all) { cat in
                            Text(cat.label).tag(cat.id)
                        }
                    }
                }
                if !candidates.isEmpty {
                    Section {
                        HStack(spacing: 16) {
                            Button("全选") {
                                selectedBackgroundIds = Set(candidates.map(\.id))
                            }
                            Button("全不选") {
                                selectedBackgroundIds = []
                            }
                            Spacer()
                            Text("\(selectedBackgroundIds.count)/\(candidates.count)")
                                .font(.system(size: 12, design: .rounded))
                                .foregroundStyle(DevTheme.dim)
                        }
                        ForEach(candidates) { msg in
                            backgroundPickerRow(msg)
                        }
                    } header: {
                        Text("附带 Chat 背景")
                    } footer: {
                        Text("勾选的消息仅作为 Dev Task 上下文发给 Agent，不写入 Chat 记录。默认选中该条之前最近 8 条。")
                    }
                }
            }
            .navigationTitle("转为 Dev Task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { promoteMessage = nil }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("创建") {
                        let text = promoteText
                        let handle = promoteHandle
                        let category = promoteCategory
                        let anchor = message.id
                        let backgroundIds = candidates
                            .filter { selectedBackgroundIds.contains($0.id) }
                            .map(\.id)
                        promoteMessage = nil
                        Task {
                            await store.promoteChatToDevTask(
                                text: text,
                                targetHandle: handle,
                                category: category,
                                anchorMessageId: anchor,
                                backgroundMessageIds: backgroundIds
                            )
                        }
                    }
                    .disabled(promoteText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear {
                if selectedBackgroundIds.isEmpty {
                    selectedBackgroundIds = defaultBackgroundSelection(anchor: message)
                }
            }
        }
        .presentationDetents([.large])
    }

    private func backgroundCandidates(anchor: AgentChatMessage) -> [AgentChatMessage] {
        store.chatMessages
            .filter { row in
                row.id <= anchor.id
                    && !row.recalled
                    && !row.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            .sorted { $0.id < $1.id }
    }

    private func defaultBackgroundSelection(anchor: AgentChatMessage) -> Set<Int> {
        let candidates = backgroundCandidates(anchor: anchor)
        let picked = candidates.suffix(8)
        return Set(picked.map(\.id))
    }

    private func backgroundPickerRow(_ msg: AgentChatMessage) -> some View {
        let selected = selectedBackgroundIds.contains(msg.id)
        return Button {
            if selected {
                selectedBackgroundIds.remove(msg.id)
            } else {
                selectedBackgroundIds.insert(msg.id)
            }
        } label: {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20))
                    .foregroundStyle(selected ? DevTheme.sand : DevTheme.dim)
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(msg.senderLabel)
                            .font(.system(size: 12, weight: .semibold, design: .rounded))
                        Spacer()
                        Text("#\(msg.id)")
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(DevTheme.dim)
                    }
                    Text(msg.body)
                        .font(.system(size: 13, design: .rounded))
                        .foregroundStyle(DevTheme.mist)
                        .lineLimit(3)
                        .multilineTextAlignment(.leading)
                    if !msg.timeLabel.isEmpty {
                        Text(msg.timeLabel)
                            .font(.system(size: 10, design: .rounded))
                            .foregroundStyle(DevTheme.dim)
                    }
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

extension AgentChatMessage: Hashable {
    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
}
