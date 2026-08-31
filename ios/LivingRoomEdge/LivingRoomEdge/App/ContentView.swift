import SwiftUI
import UIKit

struct ContentView: View {
    private enum ChatPane: String, Hashable {
        case chat
        case scan
        case photo
        case file
        case audio
        case live
    }

    @EnvironmentObject private var model: AppModel
    @StateObject private var speech = SpeechRecognizer()
    @StateObject private var clicks = ClickGuard()

    @State private var pane: ChatPane = .chat
    @State private var draft = ""
    @State private var intentSource = "text"
    @State private var hint = ""
    @State private var acceptTranscript = true
    @State private var showSettings = false
    @State private var settingsFocus: SettingsFocus = .none
    @State private var progressTurnId: UUID?
    @State private var showBrainSwitcher = false
    @FocusState private var isComposerFocused: Bool

    var body: some View {
        NavigationStack {
            ZStack {
                if pane == .chat {
                    ZStack {
                        VStack(spacing: 0) {
                            BrainEnvironmentStrip {
                                showBrainSwitcher = true
                            }
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
                } else if pane == .scan {
                    ScanWorkspaceView(showSettings: $showSettings)
                } else if pane == .file {
                    FileWorkspaceView(showSettings: $showSettings)
                } else if pane == .audio {
                    AudioWorkspaceView(showSettings: $showSettings)
                } else if pane == .photo {
                    PhotoWorkspaceView(showSettings: $showSettings) {
                        pane = .chat
                    }
                } else {
                    LiveStreamHubView(showSettings: $showSettings, settingsFocus: $settingsFocus) {
                        pane = .chat
                    }
                }
            }
            .animation(.easeOut(duration: 0.18), value: progressTurnId)
            .animation(.easeOut(duration: 0.18), value: pane)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar(pane == .photo || pane == .live ? .hidden : .visible, for: .navigationBar)
            .toolbar(pane == .photo || pane == .live ? .hidden : .visible, for: .tabBar)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Picker("页面", selection: $pane) {
                        Text("对话").tag(ChatPane.chat)
                        Text("扫描").tag(ChatPane.scan)
                        Text("拍照").tag(ChatPane.photo)
                        Text("文件").tag(ChatPane.file)
                        Text("录音").tag(ChatPane.audio)
                        Text("直播").tag(ChatPane.live)
                    }
                    .pickerStyle(.segmented)
                    .frame(minWidth: 348, maxWidth: 420)
                    .tint(pane == .chat ? Color.accentColor : EdgeTheme.sand)
                    .accessibilityLabel("对话、扫描、拍照、文件、录音或直播")
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        dismissComposerKeyboard()
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                            .foregroundStyle(pane == .chat ? Color.primary : EdgeTheme.sand)
                    }
                    .accessibilityLabel("设置")
                }
            }
            .toolbarBackground(pane == .chat ? Color(.systemBackground) : EdgeTheme.ink, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
            .sheet(isPresented: $showSettings, onDismiss: { settingsFocus = .none }) {
                ChatSettingsSheet(focus: settingsFocus)
                    .environmentObject(model)
            }
            .sheet(isPresented: $showBrainSwitcher) {
                BrainRoutingSwitcherSheet()
                    .environmentObject(model)
            }
            .onChange(of: pane) { _, newValue in
                if newValue != .chat {
                    dismissComposerKeyboard()
                    if speech.isRecording { speech.stop() }
                }
            }
            .onDisappear {
                if speech.isRecording { speech.stop() }
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
                        if model.conversationTurns.isEmpty {
                            emptyState
                                .padding(.top, 48)
                        }
                        ForEach(model.conversationTurns) { turn in
                            ChatTurnView(
                                turn: turn,
                                onOpenProgress: {
                                    dismissComposerKeyboard()
                                    Task {
                                        await model.refreshTurnProgress(turnId: turn.id)
                                        await MainActor.run {
                                            withAnimation(.easeOut(duration: 0.18)) {
                                                progressTurnId = turn.id
                                            }
                                        }
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
                .onChange(of: model.conversationTurns.count) { _, _ in
                    if model.consumeSkipScrollToLatest() { return }
                    scrollToLatest(proxy)
                }
                .onChange(of: model.conversationTurns.last?.journey.presentation?.copyText) { _, _ in
                    scrollToLatest(proxy)
                }
                .onChange(of: model.conversationTurns.last?.assistantText) { _, _ in
                    scrollToLatest(proxy)
                }
                .onChange(of: model.conversationTurns.last?.awaitingTerminal) { _, _ in
                    scrollToLatest(proxy)
                }
            }
        }
        .clipped()
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.largeTitle)
                .foregroundStyle(.secondary)
            Text("对客厅说一句话")
                .font(.headline)
            Text("文本或语音发出意图。可连续发多条，不必等上一单结束。下拉加载本机历史。")
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
                    .onChange(of: draft) { _, newValue in
                        if !speech.isRecording,
                           intentSource == "voice",
                           !speech.transcript.isEmpty,
                           newValue != speech.transcript,
                           !newValue.hasPrefix(speech.transcript) {
                            intentSource = "text"
                        }
                    }
                    .onChange(of: speech.transcript) { _, newValue in
                        guard acceptTranscript else { return }
                        if speech.isRecording || !newValue.isEmpty {
                            draft = newValue
                            if speech.isRecording {
                                intentSource = "voice"
                            }
                        }
                    }
                    .onSubmit { beginSend() }

                Button {
                    guard clicks.tryTap() else { return }
                    beginSend()
                } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .font(.system(size: 36))
                }
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .accessibilityLabel("发出")
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .background(Color(.secondarySystemBackground))
    }

    private func scrollToLatest(_ proxy: ScrollViewProxy) {
        guard let last = model.conversationTurns.last else { return }
        DispatchQueue.main.async {
            withAnimation(.easeOut(duration: 0.2)) {
                proxy.scrollTo(last.id, anchor: .bottom)
            }
        }
    }

    private func toggleSpeech() async {
        if speech.isRecording {
            speech.stop()
            intentSource = "voice"
            if !speech.transcript.isEmpty {
                draft = speech.transcript
            }
            hint = speech.transcript.isEmpty ? "未识别到内容" : ""
            return
        }
        if model.audioRecorder.isActive {
            hint = "请先结束录音页的录制（暂停中请回到录音页继续或停止）"
            return
        }
        if model.audioPlayer.isActive {
            model.audioPlayer.stop(deactivate: true)
        }
        acceptTranscript = true
        speech.clearTranscript()
        intentSource = "voice"
        hint = ""
        await speech.start()
    }

    private func beginSend() {
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
            hint = "请先在设置里填写 LAN / Cloud Brain 地址"
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
                    if let aid = turn.inputAssetId, !aid.isEmpty {
                        Text("asset \(aid)")
                            .font(.caption2.monospaced())
                            .foregroundStyle(.secondary)
                    }

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

            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 0) {
                    assistantBubble
                    if canRateFeedback {
                        DebugBugReportStrip(turn: turn)
                    }
                }
                Spacer(minLength: 56)
            }
        }
    }

    private var canRateFeedback: Bool {
        ChatTurn.isBrainIntentId(turn.intentId)
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
        let client: TimeInterval? = {
            if let seconds = turn.journey.clientElapsedSeconds(now: now) {
                return seconds
            }
            if turn.awaitingTerminal {
                let t0 = turn.journey.clientStartedAt ?? turn.createdAt
                return max(0, now.timeIntervalSince(t0))
            }
            return nil
        }()
        let dual = IntentJourney.formatDualElapsed(
            client: client,
            server: turn.journey.serverElapsedSeconds()
        )
        return dual.isEmpty ? "—" : dual
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
            PresentationBubble(
                presentation: pres,
                intentId: turn.intentId,
                stillRunning: turn.awaitingTerminal
            )
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
    var intentId: String = ""
    var stillRunning: Bool = false
    @State private var showFullImage = false
    @State private var imageData: Data?
    @State private var fullImageData: Data?
    @State private var assetFailed = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            switch presentation.type {
            case .image:
                if let data = imageData, let ui = UIImage(data: data) {
                    chatImage(ui)
                } else if assetFailed {
                    Text("无法用 asset_ref 取到图")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else if !presentation.assetId.isEmpty {
                    VStack(alignment: .leading, spacing: 6) {
                        ProgressView()
                            .frame(maxWidth: .infinity, minHeight: 140)
                        Text("正在经 Brain 拉取缩略图…")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    .task(id: "\(presentation.assetId)|\(intentId)") {
                        let client = AppModel.shared.intentClient
                        let url = AppModel.shared.intentServerURL
                        let preview = await client.fetchAssetImageData(
                            assetId: presentation.assetId,
                            intentId: intentId,
                            intentURL: url,
                            representation: "preview"
                        )
                        if let preview {
                            imageData = preview
                            assetFailed = false
                        } else {
                            assetFailed = true
                        }
                    }
                } else {
                    Text("缺少 asset_ref")
                        .font(.caption)
                        .foregroundStyle(.secondary)
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

    @ViewBuilder
    private func chatImage(_ image: UIImage) -> some View {
        Button {
            showFullImage = true
        } label: {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 280, maxHeight: 320)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("查看大图")
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .fullScreenCover(isPresented: $showFullImage) {
            if let full = fullImageData ?? imageData, let ui = UIImage(data: full) {
                ImageLightbox(image: ui)
            }
        }
        .onChange(of: showFullImage) { _, open in
            guard open, fullImageData == nil, !presentation.assetId.isEmpty else { return }
            Task {
                let original = await AppModel.shared.intentClient.fetchAssetImageData(
                    assetId: presentation.assetId,
                    intentId: intentId,
                    intentURL: AppModel.shared.intentServerURL,
                    representation: "original"
                )
                if let original, UIImage(data: original) != nil {
                    fullImageData = original
                }
            }
        }
    }
}

struct ImageLightbox: View {
    let image: UIImage
    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .scaleEffect(scale)
                .offset(offset)
                .gesture(pinch)
                .simultaneousGesture(drag)
                .onTapGesture(count: 2, perform: toggleZoom)
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

enum SettingsFocus: Equatable {
    case none
    case macIngest
}

struct ChatSettingsSheet: View {
    var focus: SettingsFocus = .none
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var copyHint = ""
    @State private var hisenseBindHint = ""
    @State private var hisenseBindBusy = false
    @State private var hisenseConfigured = HisenseCredentials.configured
    @State private var hisenseBoundTick = 0
    @FocusState private var macIngestFocused: Bool
    @State private var discovering = false
    @State private var showDiscoverAlert = false
    @State private var discoverAlertMessage = ""

    private var lanResolvedLabel: String {
        let resolved = model.lanResolvedBase.trimmingCharacters(in: .whitespacesAndNewlines)
        if resolved.isEmpty {
            return "实际 IP：尚未发现（点「自动发现」或等探测）"
        }
        return "实际 IP：\(resolved)"
    }

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                Form {
                    if focus == .macIngest {
                        macIngestSection
                        brainSection
                    } else {
                        brainSection
                        macIngestSection
                    }
                    discoveryLogSection
                    participantSection
                    runtimeSection
                    Section("文档扫描") {
                        Text("入口在顶部「扫描」。点「开始扫描」打开系统文档扫描仪，完成后 POST /api/v1/assets/upload（upload_intent=document.scan）。不经 Planner。")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                        if !VisualInput.isSupported {
                            Text("本机不支持系统文档扫描。")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }
                    }
                    Section("本机拍照") {
                        Text("入口在顶部「拍照」。切过去即后置取景，点快门后 POST /api/v1/assets/upload（upload_intent=iphone.photo）。不经 Planner，也不是 GoPro camera.capture。")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Section("本机文件") {
                        Text("入口在顶部「文件」。可从相册选图，或从「文件」App / iCloud 选取；POST /api/v1/assets/upload（upload_intent=iphone.file）。不经 Planner。")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    Section("本机录音") {
                        Text("入口在顶部「录音」。点开始后可暂停（暂停不上传）；点「停止并上传」才 POST /api/v1/assets/upload（upload_intent=iphone.audio）。不经 Planner。最近列表显示 asset_id，三点菜单可重命名，播放本机缓存。")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                    hisenseSection
                    lastResponseSection
                }
                .onAppear {
                    DiscoveryDebugLog.shared.log(
                        "settings opened routing=\(model.brainRouting) intentURL=\(model.intentServerURL)",
                        category: "connect"
                    )
                    guard focus == .macIngest else { return }
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                        proxy.scrollTo("macIngestField", anchor: .center)
                        macIngestFocused = true
                    }
                }
            }
            .navigationTitle(focus == .macIngest ? "填直播地址" : "设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
            }
            .onDisappear {
                Task { await model.applyPinnedBrainURLs() }
            }
            .alert("自动发现", isPresented: $showDiscoverAlert) {
                Button("好", role: .cancel) {}
            } message: {
                Text(discoverAlertMessage)
            }
        }
    }

    private var brainSection: some View {
        Section {
            BrainEnvironmentCard(chrome: .form)
            VStack(alignment: .leading, spacing: 6) {
                Text("局域网地址")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                Text(BrainEndpoint.defaultLanBase)
                    .font(.caption.monospaced())
                    .textSelection(.enabled)
                Text(lanResolvedLabel)
                    .font(.caption2)
                    .foregroundStyle(model.lanResolvedBase.isEmpty ? .orange : .secondary)
                    .textSelection(.enabled)
            }
            VStack(alignment: .leading, spacing: 6) {
                Text("云端地址")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                TextField(AppModel.defaultCloudBrainURL, text: $model.cloudBrainURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.caption)
                    .textContentType(.URL)
                    .keyboardType(.URL)
            }
            Button {
                guard !discovering else { return }
                discovering = true
                discoverAlertMessage = ""
                DiscoveryDebugLog.shared.log("auto-discover button tapped (force=true)", category: "connect")
                Task { @MainActor in
                    defer { discovering = false }
                    let outcome = await model.refreshMdnsEndpoints(force: true)
                    if outcome.brainFound || outcome.gatewayFound {
                        var parts: [String] = []
                        if outcome.brainFound {
                            parts.append("\(MdnsDiscovery.brainMdnsHost) → \(outcome.brainURL)")
                        }
                        if outcome.gatewayFound {
                            parts.append("\(MdnsDiscovery.gatewayMdnsHost) → \(outcome.gatewayURL)")
                        }
                        discoverAlertMessage = "已用 mDNS 找到：\n\(parts.joined(separator: "\n"))"
                    } else {
                        discoverAlertMessage = "没找到 Brain / Mac。请确认：\n① iPhone 和 Mac 在同一 WiFi\n② Mac 上 Brain 已运行（Mac 终端 dns-sd -L \"Home Agent Brain\" _ha-brain._tcp . 有输出）\n③ 设置里已允许本 App 的「本地网络」\n④ 若路由器开了「AP 隔离」，请关闭或改用手机热点测试"
                    }
                    showDiscoverAlert = true
                    Task { await model.applyPinnedBrainURLs() }
                }
            } label: {
                HStack(spacing: 8) {
                    if discovering {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Text(discovering ? "自动发现中…" : "自动发现")
                }
            }
            .disabled(discovering)
            Button {
                Task { await model.applyPinnedBrainURLs() }
            } label: {
                HStack(spacing: 8) {
                    if model.brainResolveBusy {
                        ProgressView()
                            .controlSize(.small)
                    }
                    Text(model.brainResolveBusy ? "保存中…" : "保存地址")
                }
            }
            .disabled(model.brainResolveBusy || discovering)
        } header: {
            Text("Brain 环境")
        } footer: {
            Text("顶栏始终显示当前实际连接的是局域网还是云端。局域网身份是 brain.local，连接走探测到的 IP。云端仍用固定 IP。改连接方式要进确认页。直播地址不要填到这里。")
        }
    }

    private var discoveryLogSection: some View {
        Section {
            DiscoveryDebugLogView {
                _ = await model.refreshMdnsEndpoints(force: true)
                await model.applyPinnedBrainURLs()
            }
        } header: {
            Text("局域网探测日志")
        } footer: {
            Text("默认关闭。打开「记录探测日志」后才会写入 browse / A 记录 / 扫描 / ping。最新在底部，可复制。")
        }
    }

    private var macIngestSection: some View {
        let ingest = model.macIngestURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return Section {
            Text("只填下面这一栏。把 iPhone 画面推到客厅那台跑 mac_edge 的电脑。")
                .font(.caption)
                .foregroundStyle(focus == .macIngest ? Color.primary : .secondary)
            if ingest.isEmpty {
                Text("当前：未填写（灰色字只是格式提示，还没保存）")
                    .font(.caption)
                    .foregroundStyle(.orange)
            } else {
                Text("当前已保存：\(ingest)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            TextField("", text: $model.macIngestURL, prompt: Text("还没填，点这里输入"))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .keyboardType(.URL)
                .font(.body.monospaced())
                .focused($macIngestFocused)
                .id("macIngestField")
            Text("要填的内容示例（也可以点「Brain 环境」里的「自动发现」自动填入）：")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text("http://gateway.local:8790")
                .font(.caption.monospaced())
                .textSelection(.enabled)
            Text("默认 mDNS 名是 gateway.local。点「自动发现」后下面会填入实际 IP；HTTP 走 IP，不要填 brain.local。")
                .font(.caption2)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
        } header: {
            Text("直播 · 填这里")
        } footer: {
            Text("端口必须是 8790。手机和电脑同一 Wi‑Fi。不要和上面的 LAN / Cloud Brain 填混：那是规划服务，这一栏是客厅电脑直播。电脑需先运行 mac_edge。")
        }
    }

    private var participantSection: some View {
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
            LabeledContent("心跳", value: model.lastHeartbeatOk ? "正常" : "失败或尚未成功")
                .font(.caption)
            ForEach(ParticipantStore.allRoles, id: \.self) { role in
                Toggle(role, isOn: Binding(
                    get: { model.enabledRoles.contains(role) },
                    set: { model.setRole(role, enabled: $0) }
                ))
                .font(.caption)
            }
            Text("开关只改下次心跳组包时的 roles。顶栏「上报 role」是上一次心跳请求实际发出的列表。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var runtimeSection: some View {
        Section("Runtime") {
            Text("预装 camera.capture、light.set、visual.input；配置海信爱家后广告 climate.set。打开 runtime 后心跳上报。")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(
                model.lastReportedRoles.contains("runtime")
                ? "本机 runtime 已上报（可拉单）"
                : "本机 runtime 未上报：请打开 runtime 并等心跳成功"
            )
            .font(.caption2)
            .foregroundStyle(model.lastReportedRoles.contains("runtime") ? .green : .orange)
            ForEach(LivingRoomLight.clipStatusLines(), id: \.self) { line in
                Text(line)
                    .font(.caption2.monospaced())
                    .foregroundStyle(line.contains("缺失") ? .orange : .secondary)
            }
            Text("若 Mac 也广告同一能力，Brain 可能派给另一边；进度里看 assigned_edge。")
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var hisenseSection: some View {
        Section("海信空调") {
            Text("账号只存本机 UserDefaults，不上报 Brain。点「验证并绑定」会立刻心跳广告 climate.set。")
                .font(.caption2)
                .foregroundStyle(.secondary)
            TextField("爱家用户名（手机号）", text: Binding(
                get: { HisenseCredentials.username },
                set: {
                    HisenseCredentials.username = $0
                    hisenseConfigured = HisenseCredentials.configured
                }
            ))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            SecureField("爱家密码", text: Binding(
                get: { HisenseCredentials.password },
                set: {
                    HisenseCredentials.password = $0
                    hisenseConfigured = HisenseCredentials.configured
                }
            ))
            TextField("homeId（多家庭时必填）", text: Binding(
                get: { HisenseCredentials.homeId },
                set: { HisenseCredentials.homeId = $0 }
            ))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            TextField("下一台 deviceId（多空调时填要追加的那台；点绑定写入列表）", text: Binding(
                get: { HisenseCredentials.deviceId },
                set: { HisenseCredentials.deviceId = $0 }
            ))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            if !HisenseCredentials.boundDevices.isEmpty {
                ForEach(HisenseCredentials.boundDevices) { unit in
                    // hisenseBoundTick forces refresh after add/unbind
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(unit.label.isEmpty ? unit.deviceId : unit.label)
                                .font(.caption)
                            Text("deviceId=\(unit.deviceId)")
                                .font(.caption2)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("解除绑定") {
                            HisenseCredentials.removeBoundDevice(deviceId: unit.deviceId)
                            hisenseBoundTick += 1
                            Task { _ = await model.heartbeatNow(serverURL: model.intentServerURL) }
                        }
                        .font(.caption2)
                    }
                }
            }
            Text(
                hisenseConfigured
                ? "已填账号 · 点下方绑定会追加一台，不会冲掉已绑定的另一台"
                : "未配置 · 暂不广告 climate.set"
            )
            .font(.caption2)
            .foregroundStyle(hisenseConfigured ? .green : .orange)
            Button {
                Task { await bindHisenseClimate() }
            } label: {
                if hisenseBindBusy {
                    ProgressView()
                } else {
                    Text("验证并绑定到本机（可绑第二台）")
                }
            }
            .disabled(hisenseBindBusy || !hisenseConfigured)
            if !hisenseBindHint.isEmpty {
                Text(hisenseBindHint)
                    .font(.caption2)
                    .foregroundStyle(
                        hisenseBindHint.contains("失败") || hisenseBindHint.hasPrefix("绑定失败")
                        ? .orange : .secondary
                    )
            }
        }
    }

    private var lastResponseSection: some View {
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

    @MainActor
    private func bindHisenseClimate() async {
        hisenseBindBusy = true
        hisenseBindHint = ""
        defer { hisenseBindBusy = false }
        if !model.enabledRoles.contains("runtime") {
            model.setRole("runtime", enabled: true)
        }
        do {
            let found = try await HisenseClimate.probeBind()
            hisenseBoundTick += 1
            let ok = await model.heartbeatNow(serverURL: model.intentServerURL)
            if ok {
                hisenseBindHint = "\(found)。已心跳上报 climate.set。"
            } else {
                let err = model.lastHeartbeatError.isEmpty ? "未知原因" : model.lastHeartbeatError
                hisenseBindHint = "\(found)。账号可用，但心跳失败：\(err)"
            }
        } catch {
            hisenseBindHint = "绑定失败：\(error.localizedDescription)"
        }
    }
}
