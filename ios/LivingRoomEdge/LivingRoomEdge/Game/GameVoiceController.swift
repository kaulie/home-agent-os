import AVFoundation
import Foundation
import Speech

/// Continuous on-device ASR → GameCommand keywords (no Brain /intent).
@MainActor
final class GameVoiceController: ObservableObject {
    @Published private(set) var transcript: String = ""
    @Published private(set) var isListening = false
    @Published private(set) var lastError: String = ""

    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var audioEngine: AVAudioEngine?
    private var lastFiredAt: [GameCommandType: Date] = [:]
    var onCommand: ((GameCommand) -> Void)?

    func start() async {
        lastError = ""
        guard !isListening else { return }
        let ok = await requestPermissions()
        guard ok else { return }
        guard let recognizer = ensureSpeechRecognizer(), recognizer.isAvailable else {
            lastError = "语音识别不可用"
            return
        }
        do {
            try beginSession(recognizer: recognizer)
            isListening = true
        } catch {
            lastError = error.localizedDescription
            stop()
        }
    }

    func stop() {
        if let engine = audioEngine, engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        isListening = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func requestPermissions() async -> Bool {
        let speechOk = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status == .authorized)
            }
        }
        guard speechOk else {
            lastError = "未授权语音识别"
            return false
        }
        let micOk = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
        guard micOk else {
            lastError = "未授权麦克风"
            return false
        }
        return true
    }

    private func ensureSpeechRecognizer() -> SFSpeechRecognizer? {
        if let speechRecognizer { return speechRecognizer }
        let next = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
        speechRecognizer = next
        return next
    }

    private func ensureAudioEngine() -> AVAudioEngine {
        if let audioEngine { return audioEngine }
        let next = AVAudioEngine()
        audioEngine = next
        return next
    }

    private func beginSession(recognizer: SFSpeechRecognizer) throws {
        recognitionTask?.cancel()
        recognitionTask = nil
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        recognitionRequest = request
        let engine = ensureAudioEngine()
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.recognitionRequest?.append(buffer)
        }
        engine.prepare()
        try engine.start()
        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                guard let self else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    self.tryFire(from: self.transcript)
                }
                if let error {
                    let ns = error as NSError
                    if ns.domain == "kAFAssistantErrorDomain", ns.code == 216 || ns.code == 203 { return }
                    if self.isListening { self.lastError = error.localizedDescription }
                    self.stop()
                }
            }
        }
    }

    private func tryFire(from text: String) {
        guard let type = GameVoiceMapper.match(text) else { return }
        let now = Date()
        if let prev = lastFiredAt[type], now.timeIntervalSince(prev) < 0.35 { return }
        lastFiredAt[type] = now
        let cmd = GameCommand(type: type, source: .voice)
        onCommand?(cmd)
        GameSession.shared.noteCommand(type, source: .voice)
    }
}
