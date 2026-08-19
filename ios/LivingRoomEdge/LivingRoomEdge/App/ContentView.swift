import SwiftUI
import UIKit

struct ContentView: View {
    @EnvironmentObject private var model: AppModel
    @StateObject private var speech = SpeechRecognizer()
    @StateObject private var clicks = ClickGuard()

    @State private var draft = ""
    @State private var intentSource = "text"
    @State private var hint = ""
    @State private var acceptTranscript = true
    @State private var showSettings = false
    @State private var progressTurnId: UUID?
    @FocusState private var isComposerFocused: Bool

    var body: some View {
        NavigationStack {
            ZStack {
                VStack(spacing: 0) {
                    chatList
                    composer
                }
                if let turnId = progressTurnId,
                   let journey = model.journey(for: turnId) {
                    IntentProgressOverlay(journey: journey) {
                        withAnimation(.easeOut(duration: 0.18)) {
                            progressTurnId = nil
                        }
                    }
                    .ignoresSafeArea(.keyboard)
                }
            }
            .animation(.easeOut(duration: 0.18), value: progressTurnId)
            .navigationTitle("home agent edge")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("新对话") {
                        guard clicks.tryTap(cooldown: 0.4) else { return }
                        dismissComposerKeyboard()
                        resetComposer()
                        model.clearSession()
                    }
                    .disabled(model.inputLocked || speech.isRecording)
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        dismissComposerKeyboard()
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("设置")
                }
            }
            .sheet(isPresented: $showSettings) {
                ChatSettingsSheet()
                    .environmentObject(model)
            }
            .onDisappear {
                if speech.isRecording { speech.stop() }
            }
            .onChange(of: model.inputLocked) { locked in
                if locked, speech.isRecording {
                    speech.stop()
                }
                if !locked, hint == Self.waitPreviousHint {
                    hint = ""
                }
            }
        }
    }

    private var chatList: some View {
        GeometryReader { geo in
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 14) {
                        if !model.historyNotice.isEmpty {
                            Text(model.historyNotice)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .center)
                                .padding(.top, 4)
                        }
                        if model.turns.isEmpty {
                            emptyState
                                .padding(.top, 48)
                        }
                        ForEach(model.turns) { turn in
                            ChatTurnView(
                                turn: turn,
                                onOpenProgress: {
                                    dismissComposerKeyboard()
                                    withAnimation(.easeOut(duration: 0.18)) {
                                        progressTurnId = turn.id
                                    }
                                }
                            )
                            .id(turn.id)
                        }
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .frame(maxWidth: .infinity, minHeight: geo.size.height, alignment: .top)
                }
                .scrollDismissesKeyboard(.immediately)
                .refreshable {
                    dismissComposerKeyboard()
                    await model.loadOlderHistory(serverURL: model.intentServerURL)
                }
                .simultaneousGesture(
                    TapGesture().onEnded {
                        dismissComposerKeyboard()
                    }
                )
                .onChange(of: model.turns.count) { _ in
                    if model.consumeSkipScrollToLatest() { return }
                    scrollToLatest(proxy)
                }
                .onChange(of: model.turns.last?.journey.presentation?.copyText) { _ in
                    scrollToLatest(proxy)
                }
                .onChange(of: model.turns.last?.assistantText) { _ in
                    scrollToLatest(proxy)
                }
                .onChange(of: model.turns.last?.awaitingTerminal) { _ in
                    scrollToLatest(proxy)
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
            Text("对客厅说一句话")
                .font(.headline)
            Text("文本或语音发出意图，完成后可继续下一轮。下拉可加载本机历史。")
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 6) {
            if !hint.isEmpty {
                Text(hint)
                    .font(.caption2)
                    .foregroundStyle(.orange)
            } else if !speech.lastError.isEmpty {
                Text(speech.lastError)
                    .font(.caption2)
                    .foregroundStyle(.red)
            } else if speech.isRecording {
                Text(speech.statusMessage.isEmpty ? "正在聆听…" : speech.statusMessage)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            HStack(alignment: .bottom, spacing: 10) {
                Button {
                    guard clicks.tryTap(cooldown: 0.5) else { return }
                    dismissComposerKeyboard()
                    Task { await toggleSpeech() }
                } label: {
                    Image(systemName: speech.isRecording ? "stop.circle.fill" : "mic.circle.fill")
                        .font(.system(size: 36))
                        .foregroundStyle(speech.isRecording ? Color.red : Color.accentColor)
                }
                .accessibilityLabel(speech.isRecording ? "停止录音" : "开始录音")

                TextField("输入指令…", text: $draft, axis: .vertical)
                    .font(.system(size: 22))
                    .lineLimit(1 ... 5)
                    .textFieldStyle(.roundedBorder)
                    .focused($isComposerFocused)
                    .submitLabel(.send)
                    .onChange(of: draft) { newValue in
                        if !speech.isRecording,
                           intentSource == "voice",
                           !speech.transcript.isEmpty,
                           newValue != speech.transcript,
                           !newValue.hasPrefix(speech.transcript) {
                            intentSource = "text"
                        }
                    }
                    .onChange(of: speech.transcript) { newValue in
                        guard acceptTranscript else { return }
                        if speech.isRecording || !newValue.isEmpty {
                            draft = newValue
                            if speech.isRecording {
                                intentSource = "voice"
                            }
                        }
                    }
                    .onSubmit { beginSend() }
                    .toolbar {
                        ToolbarItemGroup(placement: .keyboard) {
                            Spacer()
                            Button("完成") {
                                dismissComposerKeyboard()
                            }
                        }
                    }

                Button {
                    guard clicks.tryTap() else { return }
                    beginSend()
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 36))
                }
                .disabled(!model.inputLocked && draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("发出")
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .background(Color(.secondarySystemBackground))
    }

    private func scrollToLatest(_ proxy: ScrollViewProxy) {
        guard let last = model.turns.last else { return }
        DispatchQueue.main.async {
            withAnimation(.easeOut(duration: 0.2)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    private func toggleSpeech() async {
        if model.inputLocked {
            hint = Self.waitPreviousHint
            return
        }
        if speech.isRecording {
            speech.stop()
            intentSource = "voice"
            if !speech.transcript.isEmpty {
                draft = speech.transcript
            }
            hint = speech.transcript.isEmpty ? "未识别到内容" : ""
            return
        }
        acceptTranscript = true
        speech.clearTranscript()
        intentSource = "voice"
        hint = ""
        await speech.start()
    }

    private func beginSend() {
        if model.inputLocked {
            hint = Self.waitPreviousHint
            return
        }
        if speech.isRecording {
            speech.stop()
            if !speech.transcript.isEmpty {
                draft = speech.transcript
                intentSource = "voice"
            }
        }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            hint = "请先输入文字或完成语音识别"
            return
        }
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            hint = "请先在设置里填写 Brain URL"
            showSettings = true
            return
        }
        let source: String
        if intentSource == "voice", !speech.transcript.isEmpty {
            source = "voice"
        } else {
            source = "text"
        }
        acceptTranscript = false
        hint = ""
        dismissComposerKeyboard()
        draft = ""
        intentSource = "text"
        speech.clearTranscript()
        Task {
            await model.sendIntent(text: text, source: source, serverURL: server)
        }
    }

    private func dismissComposerKeyboard() {
        isComposerFocused = false
        UIApplication.shared.sendAction(
            #selector(UIResponder.resignFirstResponder),
            to: nil,
            from: nil,
            for: nil
        )
    }

    private func resetComposer() {
        acceptTranscript = true
        draft = ""
        intentSource = "text"
        hint = ""
        dismissComposerKeyboard()
        speech.clearTranscript()
        progressTurnId = nil
    }

    private static let waitPreviousHint = "请先等待上个指令执行结束"
}

private struct ChatTurnView: View {
    let turn: ChatTurn
    let onOpenProgress: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(Self.timeFormatter.string(from: turn.createdAt))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.bottom, 10)

            HStack(alignment: .center) {
                Spacer(minLength: 40)
                if isExecutionComplete {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.body)
                        .foregroundStyle(.green)
                        .accessibilityLabel("已执行完成")
                }
                VStack(alignment: .trailing, spacing: 4) {
                    CopyableBubble(
                        text: turn.userText,
                        foreground: .white,
                        background: Color.accentColor
                    )

                    HStack(spacing: 6) {
                        Button(action: onOpenProgress) {
                            HStack(spacing: 4) {
                                if turn.awaitingTerminal {
                                    ProgressView()
                                        .scaleEffect(0.65)
                                        .frame(width: 12, height: 12)
                                } else {
                                    Image(systemName: "point.topleft.down.curvedto.point.bottomright.up")
                                        .font(.caption2)
                                }
                                Text("进度")
                            }
                            .font(.caption2.weight(.medium))
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.mini)
                        .tint(turn.awaitingTerminal ? .orange : .secondary)

                        elapsedDurationView
                    }
                }
            }

            HStack {
                assistantBubble
                Spacer(minLength: 56)
            }
        }
    }

    @ViewBuilder
    private var elapsedDurationView: some View {
        if turn.awaitingTerminal {
            TimelineView(.periodic(from: .now, by: 0.5)) { context in
                Text(elapsedLabel(now: context.date))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .monospacedDigit()
            }
        } else {
            Text(elapsedLabel(now: Date()))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .monospacedDigit()
        }
    }

    private func elapsedLabel(now: Date) -> String {
        let seconds = turn.journey.totalElapsedSeconds(now: now)
            ?? max(0, now.timeIntervalSince(turn.createdAt))
        return IntentJourney.formatDuration(seconds)
    }

    private var isExecutionComplete: Bool {
        !turn.awaitingTerminal && turn.journey.terminal && turn.journey.current == .succeeded
    }

    @ViewBuilder
    private var assistantBubble: some View {
        if turn.journey.current == .failed || (turn.journey.timedOut && !turn.journey.terminal) {
            CopyableBubble(
                text: turn.assistantText?.isEmpty == false ? turn.assistantText! : (turn.journey.error ?? "意图失败"),
                foreground: .red,
                background: Color(.tertiarySystemBackground)
            )
        } else if let pres = turn.journey.presentation, pres.hasContent {
            PresentationBubble(presentation: pres, stillRunning: turn.awaitingTerminal)
        } else if turn.awaitingTerminal {
            HStack(spacing: 8) {
                ProgressView()
                Text("正在执行…")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(Color(.tertiarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        } else if let text = turn.assistantText, !text.isEmpty {
            CopyableBubble(
                text: text,
                foreground: Color.primary,
                background: Color(.tertiarySystemBackground)
            )
        }
    }

    private static let timeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()
}

private struct CopyableBubble: View {
    let text: String
    let foreground: Color
    let background: Color

    var body: some View {
        Text(text)
            .font(.body)
            .foregroundStyle(foreground)
            .textSelection(.enabled)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(background)
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .contextMenu {
                Button {
                    UIPasteboard.general.string = text
                } label: {
                    Label("复制", systemImage: "doc.on.doc")
                }
            }
    }
}

private struct PresentationBubble: View {
    let presentation: IntentPresentation
    var stillRunning: Bool = false
    @State private var showFullImage = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            switch presentation.type {
            case .image:
                if let url = presentation.imageURL {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .empty:
                            ProgressView()
                                .frame(maxWidth: .infinity, minHeight: 140)
                        case .success(let image):
                            Button {
                                showFullImage = true
                            } label: {
                                image
                                    .resizable()
                                    .scaledToFit()
                                    .frame(maxWidth: 280, maxHeight: 320)
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("查看大图")
                        case .failure:
                            VStack(alignment: .leading, spacing: 4) {
                                Text("图片无法加载")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Text(url.absoluteString)
                                    .font(.caption2)
                                    .foregroundStyle(.tertiary)
                                    .textSelection(.enabled)
                            }
                        @unknown default:
                            EmptyView()
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .fullScreenCover(isPresented: $showFullImage) {
                        ImageLightbox(url: url)
                    }
                }
                if !presentation.text.isEmpty {
                    Text(presentation.text)
                        .font(.body)
                        .textSelection(.enabled)
                }
            case .video:
                if let url = presentation.videoURL {
                    Link(destination: url) {
                        Label("打开视频", systemImage: "play.circle.fill")
                    }
                    .font(.body)
                    Text(url.absoluteString)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            case .text, .html, .audio:
                if !presentation.text.isEmpty {
                    Text(presentation.text)
                        .font(.body)
                        .textSelection(.enabled)
                }
            }
            if stillRunning {
                HStack(spacing: 6) {
                    ProgressView()
                        .scaleEffect(0.7)
                    Text("仍在执行…")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(.tertiarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .contextMenu {
            if !presentation.copyText.isEmpty {
                Button {
                    UIPasteboard.general.string = presentation.copyText
                } label: {
                    Label("复制", systemImage: "doc.on.doc")
                }
            }
        }
    }
}

private struct ImageLightbox: View {
    let url: URL
    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            AsyncImage(url: url) { phase in
                switch phase {
                case .empty:
                    ProgressView()
                        .tint(.white)
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFit()
                        .scaleEffect(scale)
                        .offset(offset)
                        .gesture(pinch)
                        .simultaneousGesture(drag)
                        .onTapGesture(count: 2, perform: toggleZoom)
                case .failure:
                    VStack(spacing: 8) {
                        Text("图片无法加载")
                            .foregroundStyle(.white)
                        Text(url.absoluteString)
                            .font(.caption2)
                            .foregroundStyle(.white.opacity(0.7))
                            .textSelection(.enabled)
                    }
                    .padding()
                @unknown default:
                    EmptyView()
                }
            }
            .ignoresSafeArea()

            VStack {
                HStack {
                    Spacer()
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title)
                            .symbolRenderingMode(.hierarchical)
                            .foregroundStyle(.white)
                    }
                    .accessibilityLabel("关闭")
                    .padding(16)
                }
                Spacer()
            }
        }
        .statusBarHidden(true)
    }

    private var pinch: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                scale = min(4, max(1, lastScale * value))
            }
            .onEnded { _ in
                lastScale = scale
                if scale <= 1.01 {
                    resetZoom()
                }
            }
    }

    private var drag: some Gesture {
        DragGesture()
            .onChanged { value in
                if scale > 1.01 {
                    offset = CGSize(
                        width: lastOffset.width + value.translation.width,
                        height: lastOffset.height + value.translation.height
                    )
                } else {
                    offset = CGSize(width: 0, height: value.translation.height)
                }
            }
            .onEnded { value in
                if scale > 1.01 {
                    lastOffset = offset
                } else if abs(value.translation.height) > 100 {
                    dismiss()
                } else {
                    withAnimation(.easeOut(duration: 0.18)) {
                        offset = .zero
                    }
                }
            }
    }

    private func toggleZoom() {
        withAnimation(.easeInOut(duration: 0.2)) {
            if scale > 1.01 {
                resetZoom()
            } else {
                scale = 2
                lastScale = 2
            }
        }
    }

    private func resetZoom() {
        scale = 1
        lastScale = 1
        offset = .zero
        lastOffset = .zero
    }
}

private struct ChatSettingsSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var copyHint = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Brain") {
                    TextField(AppModel.defaultIntentURL, text: $model.intentServerURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .font(.caption)
                        .disabled(model.inputLocked)
                }
                Section("本机 Participant") {
                    LabeledContent("client_hint", value: model.clientHint)
                        .font(.caption)
                        .textSelection(.enabled)
                    LabeledContent(
                        "participant_id",
                        value: model.participantId.isEmpty ? "（尚未登记）" : model.participantId
                    )
                    .font(.caption)
                    .textSelection(.enabled)
                    Text("Intent Source + Endpoint（屏幕 image/text）。不注册 Runtime。")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Section("最近一次服务器返回") {
                    HStack {
                        Spacer()
                        if !copyHint.isEmpty {
                            Text(copyHint)
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Button("复制") {
                            UIPasteboard.general.string = model.lastResponse
                            copyHint = "已复制"
                            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copyHint = "" }
                        }
                        .disabled(model.lastResponse.isEmpty)
                    }
                    Text(model.lastResponse.isEmpty ? "（暂无）" : model.lastResponse)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                }
            }
            .navigationTitle("设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
            }
            .onDisappear {
                Task { await model.ensureRegistered(serverURL: model.intentServerURL, force: true) }
            }
        }
    }
}
