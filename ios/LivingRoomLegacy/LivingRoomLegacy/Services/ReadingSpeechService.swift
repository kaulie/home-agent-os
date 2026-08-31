import AVFoundation
import Foundation
import Speech

protocol ReadingSpeechServiceDelegate: AnyObject {
    func speechService(_ service: ReadingSpeechService, didUpdatePartial text: String)
    func speechService(_ service: ReadingSpeechService, didFinalize text: String)
    func speechService(_ service: ReadingSpeechService, didUpdateStatus text: String)
    func speechService(_ service: ReadingSpeechService, didFail message: String)
    func speechService(_ service: ReadingSpeechService, didUpdateLevel level: Float)
}

final class ReadingSpeechService {
    weak var delegate: ReadingSpeechServiceDelegate?

    static var isSupported: Bool {
        SFSpeechRecognizer(locale: Locale(identifier: "zh-CN")) != nil
            || SFSpeechRecognizer() != nil
    }

    private(set) var isListening = false
    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var audioEngine: AVAudioEngine?

    private func ensureAudioEngine() -> AVAudioEngine {
        if let existing = audioEngine { return existing }
        let engine = AVAudioEngine()
        audioEngine = engine
        return engine
    }

    func start() {
        guard Self.isSupported else {
            delegate?.speechService(self, didFail: "本机不支持语音")
            return
        }
        requestPermissions { [weak self] ok, message in
            guard let self = self else { return }
            guard ok else {
                self.delegate?.speechService(self, didFail: message)
                return
            }
            self.beginListening()
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
        delegate?.speechService(self, didUpdateLevel: 0)
    }

    private func requestPermissions(completion: @escaping (Bool, String) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            guard status == .authorized else {
                DispatchQueue.main.async { completion(false, "需要语音识别权限") }
                return
            }
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async {
                    completion(granted, granted ? "" : "需要麦克风权限")
                }
            }
        }
    }

    private func beginListening() {
        stop()
        guard let recognizer = speechRecognizer ?? SFSpeechRecognizer(locale: Locale(identifier: "zh-CN")) else {
            delegate?.speechService(self, didFail: "语音识别不可用")
            return
        }
        speechRecognizer = recognizer
        guard recognizer.isAvailable else {
            delegate?.speechService(self, didFail: "语音识别暂不可用")
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let request = SFSpeechAudioBufferRecognitionRequest()
            request.shouldReportPartialResults = true
            recognitionRequest = request
            let engine = ensureAudioEngine()
            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                delegate?.speechService(self, didFail: "本机不支持语音")
                return
            }
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
                self?.recognitionRequest?.append(buffer)
                self?.reportLevel(from: buffer)
            }
            engine.prepare()
            try engine.start()
            isListening = true
            delegate?.speechService(self, didUpdateStatus: "可以直接说话")
            recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
                guard let self = self else { return }
                DispatchQueue.main.async {
                    if let result = result {
                        let text = result.bestTranscription.formattedString
                        if result.isFinal {
                            self.delegate?.speechService(self, didFinalize: text)
                        } else {
                            self.delegate?.speechService(self, didUpdatePartial: text)
                        }
                    }
                    if let error = error {
                        let ns = error as NSError
                        if ns.domain == "kAFAssistantErrorDomain", ns.code == 216 || ns.code == 203 {
                            return
                        }
                        if self.isListening {
                            self.delegate?.speechService(self, didFail: error.localizedDescription)
                        }
                        self.stop()
                    }
                }
            }
        } catch {
            delegate?.speechService(self, didFail: error.localizedDescription)
            stop()
        }
    }

    private func reportLevel(from buffer: AVAudioPCMBuffer) {
        guard let channel = buffer.floatChannelData?[0] else { return }
        let count = Int(buffer.frameLength)
        guard count > 0 else { return }
        var sum: Float = 0
        for i in 0 ..< count {
            sum += abs(channel[i])
        }
        let level = min(1, sum / Float(count) * 8)
        DispatchQueue.main.async { [weak self] in
            guard let self = self, self.isListening else { return }
            self.delegate?.speechService(self, didUpdateLevel: level)
        }
    }
}
