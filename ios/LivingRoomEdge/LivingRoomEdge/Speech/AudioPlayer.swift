import AVFoundation
import Foundation

/// Local playback for finished recordings. Pause here is play-pause, not record-pause.
@MainActor
final class AudioPlayer: NSObject, ObservableObject {
    @Published private(set) var playingAssetId: String = ""
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var isPaused: Bool = false
    @Published private(set) var lastError: String = ""

    var isPlaying: Bool {
        !playingAssetId.isEmpty && !isPaused && (player?.isPlaying == true)
    }

    var isActive: Bool { !playingAssetId.isEmpty }

    private var player: AVAudioPlayer?
    private var tick: Timer?

    func play(assetId: String) -> Bool {
        lastError = ""
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty else {
            lastError = "本机没有可播放的录音。"
            return false
        }
        if playingAssetId == aid {
            if isPaused {
                return resume()
            }
            pause()
            return true
        }
        stop(deactivate: false)
        guard let url = AudioPreviewStore.fileURL(for: aid) else {
            lastError = "本机没有可播放的录音。"
            return false
        }
        do {
            try activateSession()
            let next = try AVAudioPlayer(contentsOf: url)
            next.delegate = self
            next.prepareToPlay()
            guard next.play() else {
                lastError = "无法播放录音。"
                return false
            }
            player = next
            playingAssetId = aid
            duration = next.duration
            elapsed = 0
            isPaused = false
            startTick()
            return true
        } catch {
            lastError = "无法播放录音：\(error.localizedDescription)"
            stop(deactivate: true)
            return false
        }
    }

    func pause() {
        guard isPlaying, let player else { return }
        player.pause()
        isPaused = true
        elapsed = player.currentTime
        tick?.invalidate()
        tick = nil
    }

    @discardableResult
    func resume() -> Bool {
        guard isPaused, let player, !playingAssetId.isEmpty else { return false }
        do {
            try activateSession()
            guard player.play() else {
                lastError = "无法继续播放。"
                return false
            }
            isPaused = false
            startTick()
            return true
        } catch {
            lastError = "无法继续播放：\(error.localizedDescription)"
            return false
        }
    }

    func seek(_ seconds: TimeInterval) {
        guard let player, !playingAssetId.isEmpty else { return }
        let clamped = min(max(0, seconds), player.duration)
        player.currentTime = clamped
        elapsed = clamped
    }

    func stop(deactivate: Bool) {
        tick?.invalidate()
        tick = nil
        player?.delegate = nil
        player?.stop()
        player = nil
        playingAssetId = ""
        elapsed = 0
        duration = 0
        isPaused = false
        if deactivate {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }

    private func activateSession() throws {
        let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
            try? session.overrideOutputAudioPort(.speaker)
    }

    private func startTick() {
        tick?.invalidate()
        let timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.tickElapsed()
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        tick = timer
    }

    private func tickElapsed() {
        guard let player, !isPaused else { return }
        elapsed = player.currentTime
        duration = player.duration
    }
}

extension AudioPlayer: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            stop(deactivate: true)
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in
            lastError = "播放失败：\(error?.localizedDescription ?? "解码错误")"
            stop(deactivate: true)
        }
    }
}
