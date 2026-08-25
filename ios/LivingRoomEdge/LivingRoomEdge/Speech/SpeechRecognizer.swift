import AVFoundation
import Foundation
import Speech

/// On-device speech → text (zh-CN). Used by the command-dispatch panel before POST to server.
///
/// Audio / Speech frameworks are created lazily on first mic tap — constructing
/// `AVAudioEngine` / `SFSpeechRecognizer` during first frame has hung the main
/// thread on device (UI appears frozen right after launch).
@MainActor
final class SpeechRecognizer: ObservableObject {
    @Published private(set) var transcript: String = ""
    @Published private(set) var isRecording: Bool = false
    @Published private(set) var statusMessage: String = ""
    @Published private(set) var lastError: String = ""

    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var audioEngine: AVAudioEngine?

    var isAvailable: Bool {
        ensureSpeechRecognizer()?.isAvailable == true
    }

    func requestPermissions() async -> Bool {
        let speechOk = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status == .authorized)
            }
        }
        guard speechOk else {
            lastError = "未授权语音识别（设置 → HomeAgent Console → 语音识别）"
            return false
        }

        let micOk = await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
        guard micOk else {
            lastError = "未授权麦克风（设置 → HomeAgent Console → 麦克风）"
            return false
        }
        return true
    }

    func start() async {
        lastError = ""
        statusMessage = ""
        guard !isRecording else { return }

        let ok = await requestPermissions()
        guard ok else { return }
        guard let recognizer = ensureSpeechRecognizer(), recognizer.isAvailable else {
            lastError = "语音识别不可用（请用真机，并确认中文语音包）"
            return
        }

        do {
            try beginSession(recognizer: recognizer)
            isRecording = true
            statusMessage = "聆听中…"
        } catch {
            lastError = "无法开始录音：\(error.localizedDescription)"
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
        isRecording = false
        if statusMessage == "聆听中…" {
            statusMessage = transcript.isEmpty ? "已停止" : "识别完成"
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
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
        try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
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
                    if result.isFinal {
                        self.statusMessage = "识别完成"
                        self.stop()
                    }
                }
                if let error {
                    let ns = error as NSError
                    // Ignore cancellation after stop()
                    if ns.domain == "kAFAssistantErrorDomain", ns.code == 216 || ns.code == 203 {
                        return
                    }
                    if self.isRecording {
                        self.lastError = error.localizedDescription
                    }
                    self.stop()
                }
            }
        }
    }

    func clearTranscript() {
        transcript = ""
        statusMessage = ""
        lastError = ""
    }
}
