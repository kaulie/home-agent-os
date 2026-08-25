import AVFoundation
import CoreMedia
import SwiftUI

/// Dedicated audio workspace: record / pause / stop-and-upload, then play locally.
struct AudioWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    @StateObject private var clicks = ClickGuard()
    @State private var renameTurn: ChatTurn?
    @State private var renameDraft = ""
    @State private var pulse = false

    var body: some View {
        ZStack {
            EdgeTheme.canvas
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    VStack(alignment: .leading, spacing: 8) {
                        EdgeTheme.heroTitle("录音")
                        EdgeTheme.heroSubtitle("对着话筒说完再停。暂停不上传；停止后才自动上传并登记 Asset。可改录音名字。不经意图理解。")
                    }
                    .padding(.top, 8)

                    ctaCard

                    if !model.audioHint.isEmpty {
                        Text(model.audioHint)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(Color.orange.opacity(0.95))
                            .fixedSize(horizontal: false, vertical: true)
                    } else if !model.audioRecorder.lastError.isEmpty, !model.audioRecorder.isActive {
                        Text(model.audioRecorder.lastError)
                            .font(.system(size: 13, weight: .medium, design: .rounded))
                            .foregroundStyle(Color.orange.opacity(0.95))
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    recentSection
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 36)
            }
        }
        .onAppear {
            pulse = model.audioRecorder.isRecording
        }
        .onDisappear {
            model.handleAudioPaneDisappear()
        }
        .onChange(of: model.audioRecorder.isRecording) { recording in
            pulse = recording
        }
        .alert("重命名", isPresented: renamePresented) {
            TextField("名字", text: $renameDraft)
            Button("取消", role: .cancel) {
                renameTurn = nil
            }
            Button("保存") {
                if let turn = renameTurn {
                    model.renameLocalAudio(turnId: turn.id, name: renameDraft)
                }
                renameTurn = nil
            }
        } message: {
            Text("只改本机显示名，不会重新上传。")
        }
    }

    private var renamePresented: Binding<Bool> {
        Binding(
            get: { renameTurn != nil },
            set: { if !$0 { renameTurn = nil } }
        )
    }

    @ViewBuilder
    private var ctaCard: some View {
        let recording = model.audioRecorder.isRecording
        let paused = model.audioRecorder.isPaused
        let busy = model.audioBusy
        let active = model.audioRecorder.isActive

        VStack(spacing: 16) {
            if busy {
                ProgressView()
                    .tint(EdgeTheme.sand)
                    .scaleEffect(1.15)
                Text("正在上传…")
                    .font(.system(size: 20, weight: .semibold, design: .rounded))
                Text(uploadCaption)
                    .font(.system(size: 13, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.mist)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
            } else if !active {
                Button {
                    beginRecord()
                } label: {
                    VStack(spacing: 12) {
                        Image(systemName: "mic")
                            .font(.system(size: 44, weight: .light))
                        Text("开始录音")
                            .font(.system(size: 20, weight: .semibold, design: .rounded))
                        Text("可暂停（暂停不上传）")
                            .font(.system(size: 13, weight: .regular, design: .rounded))
                            .foregroundStyle(EdgeTheme.mist)
                    }
                    .foregroundStyle(EdgeTheme.sand)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("开始录音")
            } else {
                Text(paused ? "已暂停  \(model.audioRecorder.formattedElapsed())" : model.audioRecorder.formattedElapsed())
                    .font(.system(size: 28, weight: .medium, design: .monospaced))
                    .foregroundStyle(Color.white.opacity(0.94))
                    .accessibilityLabel(paused ? "已暂停" : "正在录音")

                TextField("录音名称", text: $model.audioTitle)
                    .font(.system(size: 16, weight: .regular, design: .rounded))
                    .foregroundStyle(Color.white.opacity(0.92))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .background(
                        RoundedRectangle(cornerRadius: 12, style: .continuous)
                            .fill(EdgeTheme.ink.opacity(0.55))
                    )
                    .accessibilityLabel("录音名称")

                Button {
                    if recording {
                        model.pauseLocalAudio()
                    } else {
                        model.resumeLocalAudio()
                    }
                } label: {
                    VStack(spacing: 8) {
                        Image(systemName: recording ? "pause.fill" : "mic.circle")
                            .font(.system(size: 36, weight: .light))
                        Text(recording ? "暂停" : "继续录音")
                            .font(.system(size: 18, weight: .semibold, design: .rounded))
                    }
                    .foregroundStyle(EdgeTheme.sand)
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(recording ? "暂停" : "继续录音")

                Button {
                    stopAndUpload()
                } label: {
                    Text("停止并上传")
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(Color.red.opacity(0.92))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .overlay(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .stroke(Color.red.opacity(0.55), lineWidth: 1)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityLabel("停止并上传")

                Text("最长 10 分钟")
                    .font(.system(size: 12, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
            }
        }
        .foregroundStyle(EdgeTheme.sand)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 28)
        .padding(.horizontal, 16)
        .background(
            RoundedRectangle(cornerRadius: 24, style: .continuous)
                .fill(EdgeTheme.panel)
                .overlay(
                    RoundedRectangle(cornerRadius: 24, style: .continuous)
                        .stroke(ctaStroke, lineWidth: recording ? 1.4 : 1)
                )
        )
        .opacity(recording ? (pulse ? 1 : 0.86) : 1)
        .animation(
            recording ? .easeInOut(duration: 0.9).repeatForever(autoreverses: true) : .default,
            value: pulse
        )
        .disabled(busy)
    }

    private var ctaStroke: Color {
        if model.audioBusy {
            return EdgeTheme.sand.opacity(0.22)
        }
        if model.audioRecorder.isRecording {
            return Color.red.opacity(0.7)
        }
        if model.audioRecorder.isPaused {
            return EdgeTheme.sand.opacity(0.55)
        }
        return EdgeTheme.sand.opacity(0.35)
    }

    private var uploadCaption: String {
        let name = model.audioTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        if name.isEmpty {
            return "登记 Asset 中"
        }
        return "\(name) · 登记 Asset 中"
    }

    @ViewBuilder
    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            EdgeTheme.sectionLabel("最近录音")
            if model.audioTurns.isEmpty {
                Text("还没有录音。点上方按钮开始，停录后会自动上传。")
                    .font(.system(size: 14, weight: .regular, design: .rounded))
                    .foregroundStyle(EdgeTheme.dim)
            } else {
                LazyVStack(alignment: .leading, spacing: 8) {
                    ForEach(model.audioTurns) { turn in
                        AudioInboxRow(
                            turn: turn,
                            recordingNow: model.audioRecorder.isRecording,
                            playingAssetId: model.audioPlayer.playingAssetId,
                            isPaused: model.audioPlayer.isPaused,
                            elapsed: model.audioPlayer.elapsed,
                            duration: model.audioPlayer.duration,
                            onPlay: { play(turn) },
                            onPause: { model.pauseLocalAudioPlayback() },
                            onSeek: { model.seekLocalAudioPlayback($0) },
                            onRename: { beginRename(turn) }
                        )
                    }
                }
            }
        }
    }

    private func beginRecord() {
        guard clicks.tryTap(cooldown: 0.8) else { return }
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            model.setAudioHint("请先在设置里填写 Brain URL")
            showSettings = true
            return
        }
        model.setAudioHint("")
        Task { await model.startLocalAudio() }
    }

    private func stopAndUpload() {
        guard clicks.tryTap(cooldown: 0.8) else { return }
        let server = model.intentServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !server.isEmpty else {
            model.setAudioHint("请先在设置里填写 Brain URL")
            showSettings = true
            return
        }
        Task { await model.stopAndUploadLocalAudio(serverURL: server) }
    }

    private func play(_ turn: ChatTurn) {
        guard !model.audioRecorder.isRecording else { return }
        let aid = (turn.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty else {
            model.setAudioHint("已登记，但没有 asset_id。")
            return
        }
        model.playLocalAudio(assetId: aid)
    }

    private func beginRename(_ turn: ChatTurn) {
        renameDraft = turn.userText
        renameTurn = turn
    }
}

private struct AudioInboxRow: View {
    let turn: ChatTurn
    var recordingNow: Bool
    var playingAssetId: String
    var isPaused: Bool
    var elapsed: TimeInterval
    var duration: TimeInterval
    var onPlay: () -> Void
    var onPause: () -> Void
    var onSeek: (TimeInterval) -> Void
    var onRename: () -> Void

    @State private var clipDuration: TimeInterval = 0

    private var assetId: String {
        (turn.inputAssetId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var isThisClip: Bool {
        !assetId.isEmpty && playingAssetId == assetId
    }

    private var isThisPlaying: Bool {
        isThisClip && !isPaused
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Button {
                    if recordingNow { return }
                    if isThisPlaying {
                        onPause()
                    } else {
                        onPlay()
                    }
                } label: {
                    ZStack {
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(EdgeTheme.ink.opacity(0.55))
                        Image(systemName: isThisPlaying ? "pause.fill" : "play.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(recordingNow ? EdgeTheme.dim : EdgeTheme.sand)
                    }
                    .frame(width: 44, height: 44)
                }
                .buttonStyle(.plain)
                .disabled(recordingNow)
                .accessibilityLabel(isThisPlaying ? "暂停播放" : "播放")

                VStack(alignment: .leading, spacing: 3) {
                    Text(turn.userText)
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(Color.white.opacity(0.92))
                        .lineLimit(1)
                    Text("音频 · \(Self.timeLabel(turn.createdAt))")
                        .font(.system(size: 12, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                    if !assetId.isEmpty {
                        Text(assetId)
                            .font(.system(size: 11, weight: .regular, design: .monospaced))
                            .foregroundStyle(EdgeTheme.dim)
                            .lineLimit(1)
                            .truncationMode(.middle)
                            .textSelection(.enabled)
                            .accessibilityLabel("asset_id \(assetId)")
                    }
                }
                Spacer(minLength: 8)
                Text(AudioRecorder.formatTime(displayDuration))
                    .font(.system(size: 13, weight: .medium, design: .monospaced))
                    .foregroundStyle(EdgeTheme.mist)
                Menu {
                    Button("重命名") {
                        onRename()
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(EdgeTheme.sand)
                        .frame(width: 36, height: 36)
                        .contentShape(Rectangle())
                }
                .accessibilityLabel("更多")
            }

            if isThisClip {
                HStack(spacing: 8) {
                    Text(AudioRecorder.formatTime(elapsed))
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(EdgeTheme.dim)
                    Slider(
                        value: Binding(
                            get: { elapsed },
                            set: { onSeek($0) }
                        ),
                        in: 0 ... max(displayDuration, 0.01)
                    )
                    .tint(EdgeTheme.sand)
                    Text(AudioRecorder.formatTime(displayDuration))
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(EdgeTheme.panel)
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(EdgeTheme.panelStroke, lineWidth: 1)
                )
        )
        .task(id: assetId) {
            guard let url = AudioPreviewStore.fileURL(for: assetId) else { return }
            let asset = AVURLAsset(url: url)
            let seconds = CMTimeGetSeconds(asset.duration)
            if seconds.isFinite, seconds > 0 {
                clipDuration = seconds
            }
        }
    }

    private var displayDuration: TimeInterval {
        if isThisClip, duration > 0 { return duration }
        return clipDuration
    }

    private static let todayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MM/dd HH:mm"
        return f
    }()

    private static func timeLabel(_ date: Date) -> String {
        if Calendar.current.isDateInToday(date) {
            return todayFormatter.string(from: date)
        }
        return dayFormatter.string(from: date)
    }
}
