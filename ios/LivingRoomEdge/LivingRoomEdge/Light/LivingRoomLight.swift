import AVFoundation
import Foundation

/// iPhone `light.set`: same voice protocol as Mac home-server.
/// Prefers bundled / Documents clips (`wake`, `on`, `off`); falls back to TTS.
enum LivingRoomLight {
    static let wakePhrase = "小书小书"
    static let waitAfterWakeNs: UInt64 = 2_000_000_000
    static let commandOn = "开灯"
    static let commandOff = "关灯"

    private static let clipExts = ["m4a", "wav", "mp3", "caf", "aiff"]

    struct Result {
        let message: String
        let outputs: [String: Any]
    }

    enum Clip: String, CaseIterable {
        case wake
        case on
        case off
    }

    @MainActor
    static func run(params: [String: Any]) async throws -> Result {
        let state = try normalizeState(params["state"])
        let clipsBefore = clipStatusSummary()
        NSLog("[LivingRoomLight] run state=%@ clips=%@", state, clipsBefore)
        do {
            try await playClip(.wake, fallback: wakePhrase)
            try await Task.sleep(nanoseconds: waitAfterWakeNs)
            let cmd: Clip = state == "on" ? .on : .off
            try await playClip(cmd, fallback: state == "on" ? commandOn : commandOff)
        } catch let e as LivingRoomLightError {
            throw e
        } catch {
            throw LivingRoomLightError.voice("灯控失败：本机语音没发出去（\(error.localizedDescription)）")
        }
        let command = state == "on" ? commandOn : commandOff
        let voiceMode = voiceModeLabel()
        return Result(
            message: "light.set \(command) (\(voiceMode))",
            outputs: [
                "state": state,
                "voice_mode": voiceMode,
                "clips": clipsBefore,
            ]
        )
    }

    /// Settings / diagnostics: which bundled or Documents clips exist.
    static func clipStatusLines() -> [String] {
        Clip.allCases.map { clip in
            if let url = clipURL(clip) {
                return "\(clip.rawValue): \(url.lastPathComponent)"
            }
            return "\(clip.rawValue): 缺失（将用 TTS）"
        }
    }

    private static func clipStatusSummary() -> String {
        clipStatusLines().joined(separator: ", ")
    }

    /// `clip` when wake/on/off are all present; otherwise `tts`.
    static func voiceModeLabel() -> String {
        Clip.allCases.allSatisfy { clipURL($0) != nil } ? "clip" : "tts"
    }

    @MainActor
    private static func playClip(_ clip: Clip, fallback: String) async throws {
        if let url = clipURL(clip) {
            NSLog("[LivingRoomLight] play clip %@ → %@", clip.rawValue, url.path)
        } else {
            NSLog("[LivingRoomLight] play tts %@ (no clip)", clip.rawValue)
        }
        try await DeviceVoice.shared.play(clip, fallback: fallback)
    }

    static func normalizeState(_ raw: Any?) throws -> String {
        let text = scalarString(raw)
        let folded = text.lowercased().replacingOccurrences(of: " ", with: "")
        if folded.isEmpty {
            throw LivingRoomLightError.missingState
        }
        if ["on", "开", "开灯", "true", "1"].contains(folded) {
            return "on"
        }
        if ["off", "关", "关灯", "false", "0"].contains(folded) {
            return "off"
        }
        throw LivingRoomLightError.invalidState(text)
    }

    static func clipURL(_ clip: Clip) -> URL? {
        let subdirs = ["Audio", "Light/Audio"]
        for sub in subdirs {
            for ext in clipExts {
                if let url = Bundle.main.url(
                    forResource: clip.rawValue,
                    withExtension: ext,
                    subdirectory: sub
                ) {
                    return url
                }
            }
        }
        for ext in clipExts {
            if let url = Bundle.main.url(forResource: clip.rawValue, withExtension: ext) {
                return url
            }
        }
        guard let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            return nil
        }
        let dir = docs.appendingPathComponent("LightAudio", isDirectory: true)
        for ext in clipExts {
            let url = dir.appendingPathComponent("\(clip.rawValue).\(ext)")
            guard FileManager.default.fileExists(atPath: url.path) else { continue }
            let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            if size > 0 { return url }
        }
        return nil
    }

    private static func scalarString(_ raw: Any?) -> String {
        if let d = raw as? [String: Any] {
            if d["value"] != nil {
                return scalarString(d["value"])
            }
        }
        switch raw {
        case let s as String:
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.hasPrefix("{"),
               let data = t.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               obj["value"] != nil {
                return scalarString(obj["value"])
            }
            return t
        case let n as NSNumber:
            return n.stringValue
        case let i as Int:
            return String(i)
        default:
            return ""
        }
    }
}

/// Switch off any leftover `.record` session (speech UI / background) then
/// take `.playback`. `Session activation failed` is common when the App is
/// inactive or another category is still exclusive — retry a few mixes.
enum DevicePlaybackSession {
    static func activate() throws {
        let session = AVAudioSession.sharedInstance()
        try? session.setActive(false, options: .notifyOthersOnDeactivation)
        let attempts: [(AVAudioSession.Mode, AVAudioSession.CategoryOptions)] = [
            (.spokenAudio, [.duckOthers]),
            (.default, [.duckOthers]),
            (.default, [.mixWithOthers]),
            (.default, []),
        ]
        var lastError: Error?
        for (mode, options) in attempts {
            do {
                try session.setCategory(.playback, mode: mode, options: options)
                try session.setActive(true)
                return
            } catch {
                lastError = error
            }
        }
        let detail = lastError?.localizedDescription ?? "Session activation failed"
        throw LivingRoomLightError.voice("灯控失败：本机语音没发出去（\(detail)）")
    }
}

enum LivingRoomLightError: LocalizedError {
    case missingState
    case invalidState(String)
    case voice(String)

    var errorDescription: String? {
        switch self {
        case .missingState:
            return "灯控失败：缺少必填入参 state（on 或 off）。"
        case let .invalidState(raw):
            return "灯控失败：无法识别 state「\(raw)」。请用 on 或 off。"
        case let .voice(msg):
            return msg
        }
    }
}

@MainActor
final class DeviceVoice: NSObject, AVAudioPlayerDelegate {
    static let shared = DeviceVoice()

    private let tts = DeviceTTS()
    private var player: AVAudioPlayer?
    private var pending: CheckedContinuation<Void, Error>?

    private override init() {
        super.init()
    }

    func play(_ clip: LivingRoomLight.Clip, fallback: String) async throws {
        if let url = LivingRoomLight.clipURL(clip) {
            try await playFile(url)
            return
        }
        try await tts.speak(fallback)
    }

    private func playFile(_ url: URL) async throws {
        try activateSession()
        let audio = try AVAudioPlayer(contentsOf: url)
        audio.volume = 1.0
        audio.prepareToPlay()
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            if pending != nil {
                cont.resume(throwing: LivingRoomLightError.voice("灯控失败：本机语音忙。"))
                return
            }
            pending = cont
            player = audio
            audio.delegate = self
            if !audio.play() {
                pending = nil
                player = nil
                cont.resume(throwing: LivingRoomLightError.voice("灯控失败：预录音频播放失败。"))
            }
        }
    }

    private func activateSession() throws {
        try DevicePlaybackSession.activate()
    }

    private func finish(_ error: Error?) {
        guard let pending else { return }
        self.pending = nil
        player = nil
        if let error {
            pending.resume(throwing: error)
        } else {
            pending.resume()
        }
    }
}

extension DeviceVoice {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            if flag {
                self.finish(nil)
            } else {
                self.finish(LivingRoomLightError.voice("灯控失败：预录音频播放失败。"))
            }
        }
    }

    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor in
            let msg = error?.localizedDescription ?? "decode error"
            self.finish(LivingRoomLightError.voice("灯控失败：预录音频播放失败（\(msg)）。"))
        }
    }
}

@MainActor
final class DeviceTTS: NSObject, AVSpeechSynthesizerDelegate {
    private let synth = AVSpeechSynthesizer()
    private var pending: CheckedContinuation<Void, Error>?

    override init() {
        super.init()
        synth.delegate = self
    }

    func speak(_ text: String) async throws {
        let body = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty else { return }
        try DevicePlaybackSession.activate()
        let utt = AVSpeechUtterance(string: body)
        utt.voice = AVSpeechSynthesisVoice(language: "zh-CN")
            ?? AVSpeechSynthesisVoice(language: "zh-Hans")
        utt.rate = AVSpeechUtteranceDefaultSpeechRate
        utt.volume = 1.0
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            if pending != nil {
                cont.resume(throwing: LivingRoomLightError.voice("灯控失败：本机语音忙。"))
                return
            }
            pending = cont
            synth.speak(utt)
        }
    }

    private func finish(_ error: Error?) {
        guard let pending else { return }
        self.pending = nil
        if let error {
            pending.resume(throwing: error)
        } else {
            pending.resume()
        }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in self.finish(nil) }
    }

    nonisolated func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        Task { @MainActor in
            self.finish(LivingRoomLightError.voice("灯控失败：本机语音被取消。"))
        }
    }
}
