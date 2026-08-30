import AVFoundation
import AVKit
import SwiftUI
import UIKit

/// AVPlayerViewController wrapper — native transport controls for HLS playback.
struct AVPlayerViewControllerRepresentable: UIViewControllerRepresentable {
    let player: AVPlayer

    func makeUIViewController(context: Context) -> AVPlayerViewController {
        let controller = AVPlayerViewController()
        controller.player = player
        controller.showsPlaybackControls = true
        controller.videoGravity = .resizeAspect
        return controller
    }

    func updateUIViewController(_ uiViewController: AVPlayerViewController, context: Context) {
        uiViewController.player = player
    }
}

/// 全屏 HLS 播放器。
/// - live 模式：默认 seek 到最新画面（跟随直播），提供「从头看」按钮；
///   原生 scrubber 覆盖整场，可拖回任意时间点。
/// - replay 模式：VOD 默认从开头播整场，scrubber 可拖任意点。
struct LiveWatchPlayerView: View {
    let item: LiveWatchPlaybackItem
    let ingestURL: String

    @Environment(\.dismiss) private var dismiss

    @State private var player: AVPlayer?
    @State private var notReadyMessage = "流尚未就绪，等待推流方送出画面…"
    @State private var errorText: String?
    @State private var pollTask: Task<Void, Never>?
    @State private var liveSeekTask: Task<Void, Never>?

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color.black.ignoresSafeArea()
            if let player {
                AVPlayerViewControllerRepresentable(player: player)
                    .ignoresSafeArea()
            } else {
                notReadyView
            }
            HStack {
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel("关闭观看")
                Spacer()
                if item.mode == .live {
                    seekStartButton
                }
            }
            .padding(.top, 54)
            .padding(.horizontal, 12)
        }
        .toolbar(.hidden, for: .navigationBar)
        .toolbar(.hidden, for: .tabBar)
        .onAppear(perform: start)
        .onDisappear(perform: teardown)
    }

    /// 「从头看」：跳回开播时间点（Event 流里 .zero 即 seg_00000）。
    private var seekStartButton: some View {
        Button {
            player?.seek(to: .zero, toleranceBefore: .zero, toleranceAfter: .zero) { _ in }
        } label: {
            Text("从头看")
                .font(.system(size: 13, weight: .semibold, design: .rounded))
                .foregroundStyle(.white)
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color.white.opacity(0.16), in: Capsule())
        }
        .accessibilityLabel("从头开始看")
    }

    private var notReadyView: some View {
        VStack(spacing: 14) {
            ProgressView()
                .tint(EdgeTheme.sand)
            Text(notReadyMessage)
                .font(.system(size: 14, weight: .medium, design: .rounded))
                .foregroundStyle(EdgeTheme.mist)
                .multilineTextAlignment(.center)
            Text(item.shortStreamId)
                .font(.system(size: 12, weight: .medium, design: .monospaced))
                .foregroundStyle(EdgeTheme.dim)
            if let errorText {
                Text(errorText)
                    .font(.caption2)
                    .foregroundStyle(Color.orange.opacity(0.95))
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal, 32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func start() {
        if let urlStr = item.playbackURL, let url = URL(string: urlStr) {
            startPlayback(url: url)
            return
        }
        notReadyMessage = item.mode == .replay ? "回放尚未就绪" : "流尚未就绪，等待推流方送出画面…"
        guard item.mode == .live else { return }
        pollTask = Task {
            while !Task.isCancelled {
                await pollOnce()
                try? await Task.sleep(nanoseconds: 2_500_000_000)
            }
        }
    }

    @MainActor
    private func pollOnce() async {
        do {
            if let fresh = try await VideoLiveStatusClient.fetchSession(macIngestURL: ingestURL, streamId: item.streamId),
               let urlStr = fresh.playbackURL,
               let url = URL(string: urlStr) {
                pollTask?.cancel()
                pollTask = nil
                startPlayback(url: url)
            }
        } catch {
            if !Task.isCancelled {
                errorText = "连接 Mac Edge 失败：\(error.localizedDescription)"
            }
        }
    }

    @MainActor
    private func startPlayback(url: URL) {
        let newPlayerItem = AVPlayerItem(url: url)
        let newPlayer = AVPlayer(playerItem: newPlayerItem)
        player = newPlayer
        if item.mode == .live {
            jumpToLiveEdge(item: newPlayerItem, player: newPlayer)
        }
        newPlayer.play()
        errorText = nil
    }

    /// 等 live playlist 加载出 seekable 范围后，跳到最新时刻（live edge），
    /// 这样打开播放器就是「跟随最新画面」而不是从窗口起点起播。
    private func jumpToLiveEdge(item: AVPlayerItem, player: AVPlayer) {
        liveSeekTask?.cancel()
        liveSeekTask = Task {
            while !Task.isCancelled {
                if let end = item.seekableTimeRanges.last?.timeRangeValue.end,
                   end.isNumeric, end > .zero {
                    player.seek(to: end, toleranceBefore: .zero, toleranceAfter: .zero) { _ in }
                    return
                }
                try? await Task.sleep(nanoseconds: 200_000_000)
            }
        }
    }

    private func teardown() {
        pollTask?.cancel()
        pollTask = nil
        liveSeekTask?.cancel()
        liveSeekTask = nil
        player?.pause()
        player = nil
    }
}

