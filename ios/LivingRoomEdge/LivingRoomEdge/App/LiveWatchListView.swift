import SwiftUI

/// 轮询 Mac Edge `/api/v1/video-live/status`（约 3s 一次），筛选有数据的会话。
@MainActor
final class LiveWatchStatusPoller: ObservableObject {
    @Published private(set) var status: VideoLiveStatus?
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var lastRefresh = Date()

    private(set) var ingestURL = ""
    private var task: Task<Void, Never>?
    private let intervalNanoseconds: UInt64 = 3_000_000_000

    var hasConfiguredURL: Bool {
        !ingestURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var watchable: [VideoLiveSession] {
        (status?.streams ?? []).filter(\.isListed)
    }

    var replays: [VideoLiveReplay] {
        status?.replays ?? []
    }

    func start(ingestURL: String) {
        self.ingestURL = ingestURL.trimmingCharacters(in: .whitespacesAndNewlines)
        task?.cancel()
        task = Task { [weak self] in
            while let self, !Task.isCancelled {
                await self.refreshNow()
                try? await Task.sleep(nanoseconds: self.intervalNanoseconds)
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    func refreshNow() async {
        guard hasConfiguredURL else {
            status = nil
            errorMessage = nil
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let result = try await VideoLiveStatusClient.fetchStatus(macIngestURL: ingestURL)
            status = result
            errorMessage = nil
            lastRefresh = Date()
        } catch {
            if !Task.isCancelled {
                errorMessage = "无法连接 Mac Edge：\(error.localizedDescription)"
            }
        }
    }
}

/// 观看段：轮询 status，列出进行中的直播会话，点击进播放器。
struct LiveWatchListView: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSettings: Bool
    @Binding var settingsFocus: SettingsFocus

    @StateObject private var poller = LiveWatchStatusPoller()

    var body: some View {
        VStack(spacing: 0) {
            header
            if !poller.hasConfiguredURL {
                configureHint
            } else if let err = poller.errorMessage {
                errorBanner(err)
            }
            content
        }
        .onAppear {
            poller.start(ingestURL: model.macIngestURL)
        }
        .onDisappear {
            poller.stop()
        }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("同 Wi-Fi 观看直播")
                    .font(.system(size: 17, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.92))
                Text("刷新于 " + Self.timeText(poller.lastRefresh))
                    .font(.caption2)
                    .foregroundStyle(EdgeTheme.dim)
            }
            Spacer()
            Button {
                Task { await poller.refreshNow() }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(EdgeTheme.sand)
                    .frame(width: 36, height: 36)
            }
            .disabled(poller.isLoading)
            .accessibilityLabel("立即刷新")
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
    }

    private var configureHint: some View {
        HStack(spacing: 10) {
            Image(systemName: "wifi.slash")
            Text("未配置 Mac ingest URL，无法查看进行中的直播")
            Spacer()
            Button("去设置") {
                settingsFocus = .macIngest
                showSettings = true
            }
            .font(.system(size: 13, weight: .semibold, design: .rounded))
            .foregroundStyle(EdgeTheme.sand)
        }
        .font(.system(size: 13, weight: .medium, design: .rounded))
        .foregroundStyle(Color.orange.opacity(0.95))
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(EdgeTheme.panel.opacity(0.6))
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle")
            Text(message)
            Spacer()
        }
        .font(.system(size: 13, weight: .medium, design: .rounded))
        .foregroundStyle(Color.orange.opacity(0.95))
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(EdgeTheme.panel.opacity(0.6))
    }


    @ViewBuilder
    private var content: some View {
        let sessions = poller.watchable
        let replays = poller.replays
        if sessions.isEmpty && replays.isEmpty {
            emptyState
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .refreshable { await poller.refreshNow() }
        } else {
            List {
                if !sessions.isEmpty {
                    Section {
                        ForEach(sessions) { session in
                            NavigationLink {
                                LiveWatchPlayerView(
                                    item: LiveWatchPlaybackItem(
                                        streamId: session.streamId,
                                        playbackURL: session.playbackURL,
                                        mode: .live
                                    ),
                                    ingestURL: poller.ingestURL
                                )
                            } label: {
                                LiveWatchRowView(session: session)
                            }
                        }
                    } header: {
                        Text("直播中")
                    }
                }
                if !replays.isEmpty {
                    Section {
                        ForEach(replays) { replay in
                            NavigationLink {
                                LiveWatchPlayerView(
                                    item: LiveWatchPlaybackItem(
                                        streamId: replay.streamId,
                                        playbackURL: replay.playbackURL,
                                        mode: .replay
                                    ),
                                    ingestURL: poller.ingestURL
                                )
                            } label: {
                                LiveWatchReplayRowView(replay: replay)
                            }
                        }
                    } header: {
                        Text("回放")
                    } footer: {
                        Text("约 \(sessions.count) 路直播 · \(replays.count) 场回放 · 每 3 秒自动刷新")
                    }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .background(EdgeTheme.canvas)
            .refreshable { await poller.refreshNow() }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "video.badge.waveform")
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(EdgeTheme.dim)
            Text("暂无进行中的直播")
                .font(.system(size: 16, weight: .semibold, design: .rounded))
                .foregroundStyle(EdgeTheme.mist)
            Text("让另一台手机在「自己直播」里 Start Stream，这里 3 秒内会出现。")
                .font(.system(size: 13, weight: .regular, design: .rounded))
                .foregroundStyle(EdgeTheme.dim)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private static func timeText(_ date: Date) -> String {
        let fmt = DateFormatter()
        fmt.locale = Locale(identifier: "zh_CN")
        fmt.dateFormat = "HH:mm:ss"
        return fmt.string(from: date)
    }
}

struct LiveWatchRowView: View {
    let session: VideoLiveSession

    var body: some View {
        HStack(spacing: 12) {
            Circle()
                .fill(session.status == "streaming" ? Color.red : Color.orange)
                .frame(width: 10, height: 10)
            VStack(alignment: .leading, spacing: 3) {
                Text(session.shortStreamId)
                    .font(.system(size: 14, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.92))
                Text("\(session.sourceLabel) · \(session.bytesText)")
                    .font(.caption2)
                    .foregroundStyle(EdgeTheme.dim)
            }
            Spacer()
            Text(session.startedAtLocal ?? "")
                .font(.caption2)
                .foregroundStyle(EdgeTheme.dim)
        }
        .padding(.vertical, 6)
    }
}

struct LiveWatchReplayRowView: View {
    let replay: VideoLiveReplay

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "play.rectangle")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(EdgeTheme.sand)
                .frame(width: 14)
            VStack(alignment: .leading, spacing: 3) {
                Text(replay.shortStreamId)
                    .font(.system(size: 14, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.92))
                Text("\(replay.sourceLabel) · 时长 \(replay.durationText) · \(replay.segmentsText)")
                    .font(.caption2)
                    .foregroundStyle(EdgeTheme.dim)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 2) {
                if let start = replay.startedAtLocal {
                    Text("开播 \(start)")
                        .font(.caption2)
                        .foregroundStyle(EdgeTheme.dim)
                }
                if let end = replay.endedAtLocal {
                    Text("结束 \(end)")
                        .font(.caption2)
                        .foregroundStyle(EdgeTheme.dim)
                }
            }
        }
        .padding(.vertical, 6)
    }
}


