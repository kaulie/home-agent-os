import AVFoundation
import Foundation
import Speech

@MainActor
final class DevChatSpeechRecognizer: ObservableObject {
    @Published private(set) var isListening = false
    @Published private(set) var statusMessage = ""
    @Published private(set) var partialText = ""

    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    func toggle() {
        if isListening {
            stopListening()
        } else {
            startListening()
        }
    }

    func stopListening() {
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        recognitionRequest?.endAudio()
        recognitionRequest = nil
        recognitionTask?.cancel()
        recognitionTask = nil
        isListening = false
        statusMessage = ""
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func startListening() {
        partialText = ""
        statusMessage = "准备麦克风…"
        requestPermissions { [weak self] ok, message in
            guard let self else { return }
            guard ok else {
                self.statusMessage = message
                return
            }
            self.beginCapture()
        }
    }

    private func requestPermissions(completion: @escaping (Bool, String) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            Task { @MainActor in
                guard status == .authorized else {
                    completion(false, "需要语音识别权限")
                    return
                }
                AVAudioSession.sharedInstance().requestRecordPermission { granted in
                    Task { @MainActor in
                        completion(granted, granted ? "" : "需要麦克风权限")
                    }
                }
            }
        }
    }

    private func beginCapture() {
        stopListening()
        guard let recognizer = speechRecognizer ?? SFSpeechRecognizer(locale: Locale(identifier: "zh-CN")) else {
            statusMessage = "语音识别不可用"
            return
        }
        speechRecognizer = recognizer
        guard recognizer.isAvailable else {
            statusMessage = "语音识别暂不可用"
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            recognitionRequest = request
            let input = audioEngine.inputNode
            let format = input.outputFormat(forBus: 0)
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
                self?.recognitionRequest?.append(buffer)
            }
            audioEngine.prepare()
            try audioEngine.start()
            isListening = true
            statusMessage = "正在听…"
            recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                Task { @MainActor in
                    guard let self else { return }
                    if let result {
                        let text = result.bestTranscription.formattedString
                        self.partialText = text
                        if result.isFinal {
                            self.partialText = text.trimmingCharacters(in: .whitespacesAndNewlines)
                            self.stopListening()
                        }
                    }
                    if let error {
                        let ns = error as NSError
                        if ns.domain == "kAFAssistantErrorDomain", ns.code == 216 || ns.code == 203 {
                            return
                        }
                        if self.isListening {
                            self.statusMessage = error.localizedDescription
                        }
                        self.stopListening()
                    }
                }
            }
        } catch {
            statusMessage = error.localizedDescription
            stopListening()
        }
    }
}
