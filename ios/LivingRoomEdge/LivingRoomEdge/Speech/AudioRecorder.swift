import AVFoundation
import Foundation

/// Local AAC/M4A capture for the 录音 workspace. Pause never finalizes or uploads.
@MainActor
final class AudioRecorder: NSObject, ObservableObject {
    enum Phase: Equatable {
        case idle
        case recording
        case paused
    }

    static let maxDuration: TimeInterval = 600

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var lastError: String = ""

    var isRecording: Bool { phase == .recording }
    var isPaused: Bool { phase == .paused }
    var isActive: Bool { phase == .recording || phase == .paused }

    private var recorder: AVAudioRecorder?
    private var tick: Timer?
    private var fileURL: URL?
    private var onMaxDuration: (() -> Void)?

    func requestPermission() async -> Bool {
        lastError = ""
        let granted = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            AVAudioSession.sharedInstance().requestRecordPermission { ok in
                cont.resume(returning: ok)
            }
        }
        if !granted {
            lastError = "需要麦克风权限（设置 → HomeAgent Console → 麦克风）"
        }
        return granted
    }

    func start(onMaxDuration: @escaping () -> Void) async -> Bool {
        lastError = ""
        guard phase == .idle else { return phase != .idle }
        let ok = await requestPermission()
        guard ok else { return false }
        self.onMaxDuration = onMaxDuration
        do {
            try activateSession()
            let url = try makeFileURL()
            let settings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
                AVSampleRateKey: 44_100,
                AVNumberOfChannelsKey: 1,
                AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
            ]
            let rec = try AVAudioRecorder(url: url, settings: settings)
            rec.delegate = self
            guard rec.prepareToRecord(), rec.record() else {
                lastError = "无法开始录音。"
                teardown(deactivate: true)
                return false
            }
            recorder = rec
            fileURL = url
            elapsed = 0
            phase = .recording
            startTick()
            return true
        } catch {
            lastError = "无法开始录音：\(error.localizedDescription)"
            teardown(deactivate: true)
            return false
        }
    }

    func pause() {
        guard phase == .recording, let recorder else { return }
        recorder.pause()
        phase = .paused
        elapsed = recorder.currentTime
        // Keep session; pause must not upload or finalize.
    }

    func resume() {
        guard phase == .paused, let recorder else { return }
        lastError = ""
        do {
            try activateSession()
            guard recorder.record() else {
                lastError = "无法继续录音。"
                return
            }
            phase = .recording
            startTick()
        } catch {
            lastError = "无法继续录音：\(error.localizedDescription)"
        }
    }

    /// Finalize the m4a. Does not upload. Returns nil if nothing was captured.
    func stop(deactivateSession: Bool) -> URL? {
        guard isActive, let recorder else {
            teardown(deactivate: deactivateSession)
            return nil
        }
        recorder.stop()
        let url = fileURL
        let seconds = recorder.currentTime
        teardown(deactivate: deactivateSession)
        elapsed = max(seconds, elapsed)
        guard let url, FileManager.default.fileExists(atPath: url.path) else {
            lastError = lastError.isEmpty ? "录音失败：没有文件。" : lastError
            return nil
        }
        let size = (try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? NSNumber)?.intValue ?? 0
        if size <= 0 {
            lastError = "录音失败：文件为空。"
            try? FileManager.default.removeItem(at: url)
            return nil
        }
        return url
    }

    func formattedElapsed() -> String {
        Self.formatTime(elapsed)
    }

    static func formatTime(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded(.down)))
        let m = total / 60
        let s = total % 60
        return String(format: "%d:%02d", m, s)
    }

    static func defaultTitle(at date: Date = Date()) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "zh_CN")
        f.dateFormat = "HHmm"
        return "录音_\(f.string(from: date))"
    }

    private func activateSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker, .allowBluetooth])
        try session.setActive(true)
    }

    private func makeFileURL() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("iphone-audio", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("rec_\(Int(Date().timeIntervalSince1970)).m4a")
    }

    private func startTick() {
        tick?.invalidate()
        let timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.tickElapsed()
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        tick = timer
    }

    private func tickElapsed() {
        guard phase == .recording, let recorder else { return }
        elapsed = recorder.currentTime
        if elapsed >= Self.maxDuration {
            let fire = onMaxDuration
            onMaxDuration = nil
            fire?()
        }
    }

    private func teardown(deactivate: Bool) {
        tick?.invalidate()
        tick = nil
        recorder?.delegate = nil
        recorder = nil
        fileURL = nil
        onMaxDuration = nil
        phase = .idle
        if deactivate {
            try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        }
    }
}

extension AudioRecorder: AVAudioRecorderDelegate {
    nonisolated func audioRecorderEncodeErrorDidOccur(_ recorder: AVAudioRecorder, error: Error?) {
        Task { @MainActor in
            lastError = "录音失败：\(error?.localizedDescription ?? "编码错误")"
            _ = stop(deactivateSession: true)
        }
    }
}
