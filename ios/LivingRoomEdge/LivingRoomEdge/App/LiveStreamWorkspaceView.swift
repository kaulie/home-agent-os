import SwiftUI
import UIKit

private enum LiveStreamMediaMode: String, CaseIterable, Identifiable {
    case videoOnly
    case videoAndAudio

    var id: String { rawValue }

    var label: String {
        switch self {
        case .videoOnly: return "仅视频"
        case .videoAndAudio: return "视频+音频"
        }
    }

    var includesAudio: Bool { self == .videoAndAudio }
}

/// Local Input: iPhone camera → MPEG-TS over TCP to Mac Edge (not Planner).
struct LiveStreamWorkspaceView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    @Binding var settingsFocus: SettingsFocus
    var onClose: () -> Void
    @StateObject private var live = VideoLiveStreamController()
    @StateObject private var clicks = ClickGuard()
    @State private var mediaMode: LiveStreamMediaMode = .videoAndAudio

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.black.ignoresSafeArea()
            VStack(spacing: 0) {
                previewBlock
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                controlBar
            }
            HStack {
                Button {
                    Task {
                        await live.stopStream(keepPreview: false)
                        onClose()
                    }
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("关闭直播")
                Spacer()
                Button {
                    openMacIngestSettings()
                } label: {
                    Image(systemName: "gearshape")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("设置")
            }
            .padding(.top, 54)
            .padding(.horizontal, 12)
            if live.phase == .streaming {
                liveOverlay
                    .padding(.top, 54)
                    .padding(.horizontal, 56)
            }
        }
        .ignoresSafeArea()
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .onAppear {
            live.setAudioCaptureEnabled(mediaMode.includesAudio)
            live.startPreview()
        }
        .onDisappear {
            live.stopPreview()
        }
    }

    private var previewReady: Bool {
        guard live.capture.authorization == .authorized, live.capture.hasDevice else { return false }
        if mediaMode.includesAudio {
            return live.capture.audioAuthorization == .authorized
        }
        return true
    }

    private var previewBlock: some View {
        ZStack {
            Color.black
            if previewReady {
                LiveCameraPreviewView(session: live.capture.session)
            } else {
                VStack(spacing: 10) {
                    Image(systemName: mediaMode.includesAudio ? "video.badge.waveform" : "video")
                        .font(.system(size: 36, weight: .light))
                        .foregroundStyle(EdgeTheme.sand)
                    Text(live.capture.authorization != .authorized ? "需要相机权限"
                        : mediaMode.includesAudio && live.capture.audioAuthorization != .authorized ? "需要麦克风权限"
                        : "本机没有可用摄像头")
                        .font(.system(size: 16, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.mist)
                    Text(live.capture.authorization != .authorized ? "授权后即可取景推流。"
                        : mediaMode.includesAudio && live.capture.audioAuthorization != .authorized ? "「视频+音频」会采集环境音，请允许麦克风。"
                        : "模拟器无法预览，请用真机。")
                        .font(.system(size: 13, weight: .regular, design: .rounded))
                        .foregroundStyle(EdgeTheme.dim)
                    if live.capture.authorization == .denied || live.capture.authorization == .restricted
                        || (mediaMode.includesAudio && (live.capture.audioAuthorization == .denied || live.capture.audioAuthorization == .restricted)) {
                        Button("去设置") {
                            if let url = URL(string: UIApplication.openSettingsURLString) {
                                UIApplication.shared.open(url)
                            }
                        }
                        .font(.system(size: 13, weight: .semibold, design: .rounded))
                        .foregroundStyle(EdgeTheme.sand)
                    }
                }
                .padding(.horizontal, 24)
            }
        }
        .clipped()
    }

    private var liveOverlay: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 8) {
                Circle()
                    .fill(Color.red)
                    .frame(width: 8, height: 8)
                Text("LIVE")
                    .font(.system(size: 13, weight: .bold, design: .rounded))
            }
            Text(live.streamId)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
            Text("\(live.resolution) · \(live.fps)fps · \(bitrateLabel)\(live.streamIncludesAudio ? " · 音" : "")")
                .font(.system(size: 12, weight: .medium, design: .rounded))
            HStack(spacing: 8) {
                Text(live.connectedHost.isEmpty ? "—" : live.connectedHost)
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    Text(durationText(now: context.date))
                }
            }
            .font(.system(size: 12, weight: .medium, design: .rounded))
        }
        .foregroundStyle(.white)
        .padding(10)
        .background(Color.black.opacity(0.45), in: RoundedRectangle(cornerRadius: 10))
        .frame(maxWidth: .infinity, alignment: .leading)
        .allowsHitTesting(false)
    }

    private var controlBar: some View {
        ZStack {
            Color.black
            VStack(spacing: 8) {
                statusLine
                if live.phase == .idle || live.phase == .error {
                    mediaModePicker
                }
                if live.phase == .streaming || live.phase == .starting || live.phase == .stopping {
                    stopButton
                } else {
                    startButton
                }
            }
        }
        .frame(height: live.phase == .idle || live.phase == .error ? 158 : 118)
        .padding(.bottom, 28)
        .frame(maxWidth: .infinity)
        .background(Color.black)
    }

    private var statusLine: some View {
        Group {
            if live.phase == .starting {
                Text("正在连接 Mac…")
            } else if live.phase == .stopping {
                Text("正在停止…")
            } else if live.phase == .error, !live.errorMessage.isEmpty {
                Text(live.errorMessage)
                    .foregroundStyle(Color.orange.opacity(0.95))
                    .multilineTextAlignment(.center)
            } else if live.phase == .idle {
                if model.macIngestURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    Button {
                        openMacIngestSettings()
                    } label: {
                        Text("未填 Mac ingest URL，去设置")
                            .underline()
                    }
                    .foregroundStyle(Color.orange.opacity(0.95))
                    .buttonStyle(.plain)
                } else {
                    Text("○ OFF")
                }
            } else {
                EmptyView()
            }
        }
        .font(.system(size: 13, weight: .medium, design: .rounded))
        .foregroundStyle(.white.opacity(0.9))
        .padding(.horizontal, 20)
    }

    private var mediaModePicker: some View {
        Picker("推流内容", selection: $mediaMode) {
            ForEach(LiveStreamMediaMode.allCases) { mode in
                Text(mode.label).tag(mode)
            }
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, 24)
        .disabled(live.phase == .starting)
        .onChange(of: mediaMode) { mode in
            live.setAudioCaptureEnabled(mode.includesAudio)
        }
        .accessibilityLabel("推流内容")
    }

    private var startButton: some View {
        let ingest = model.macIngestURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return Button {
            guard clicks.tryTap(cooldown: 0.8) else { return }
            if ingest.isEmpty {
                openMacIngestSettings()
                return
            }
            Task { await live.startStream(ingestBaseURL: ingest, includeAudio: mediaMode.includesAudio) }
        } label: {
            Text("Start Stream")
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(.black)
                .frame(width: 180, height: 48)
                .background(Color.white, in: Capsule())
        }
        .disabled(live.phase == .starting || (!ingest.isEmpty && !canStartStream))
        .opacity(ingest.isEmpty || !canStartStream ? 0.4 : 1)
        .accessibilityLabel("开始推流")
    }

    private var canStartStream: Bool {
        guard live.capture.isRunning else { return false }
        if mediaMode.includesAudio {
            return live.capture.audioAuthorization == .authorized
        }
        return true
    }

    private var stopButton: some View {
        Button {
            guard clicks.tryTap(cooldown: 0.4) else { return }
            Task { await live.stopStream(keepPreview: true) }
        } label: {
            Text("Stop Stream")
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(.white)
                .frame(width: 180, height: 48)
                .background(Color.red.opacity(0.9), in: Capsule())
        }
        .disabled(live.phase == .stopping)
        .accessibilityLabel("停止推流")
    }

    private var bitrateLabel: String {
        let mbps = Double(live.bitrate) / 1_000_000.0
        if mbps >= 1 {
            return String(format: "%.0f Mbps", mbps)
        }
        return "\(live.bitrate / 1000) kbps"
    }

    private func durationText(now: Date) -> String {
        guard let started = live.startedAt else { return "00:00:00" }
        let sec = max(0, Int(now.timeIntervalSince(started)))
        let h = sec / 3600
        let m = (sec % 3600) / 60
        let s = sec % 60
        return String(format: "%02d:%02d:%02d", h, m, s)
    }

    private func openMacIngestSettings() {
        settingsFocus = .macIngest
        showSettings = true
    }
}
