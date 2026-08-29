import AVFoundation
import Foundation

enum PcmCaptureError: LocalizedError {
    case engineFailed(String)

    var errorDescription: String? {
        switch self {
        case .engineFailed(let msg): return msg
        }
    }
}

/// Captures microphone as mono s16le 44.1kHz PCM. No playback path (.record only).
final class PcmCaptureEngine {
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var targetFormat: AVAudioFormat?
    private var onPCM: ((Data) -> Void)?
    private var interruptionObserver: NSObjectProtocol?

    var isRunning: Bool { engine.isRunning }

    func start(onPCM: @escaping (Data) -> Void) throws {
        self.onPCM = onPCM
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .voiceChat, options: [])
        try session.setPreferredSampleRate(44_100)
        try session.setActive(true, options: .notifyOthersOnDeactivation)

        guard
            let format = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: 44_100,
                channels: 1,
                interleaved: true
            )
        else {
            throw PcmCaptureError.engineFailed("无法创建 PCM 格式")
        }
        targetFormat = format

        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: inputFormat, to: format)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: inputFormat) { [weak self] buffer, _ in
            self?.handle(buffer: buffer)
        }

        observeInterruption()
        engine.prepare()
        try engine.start()
    }

    func stop() {
        if engine.isRunning {
            engine.stop()
        }
        engine.inputNode.removeTap(onBus: 0)
        converter = nil
        onPCM = nil
        if let interruptionObserver {
            NotificationCenter.default.removeObserver(interruptionObserver)
            self.interruptionObserver = nil
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func handle(buffer: AVAudioPCMBuffer) {
        guard let targetFormat, let converter, let onPCM else { return }
        let frameCapacity = AVAudioFrameCount(
            Double(buffer.frameLength) * targetFormat.sampleRate / buffer.format.sampleRate
        ) + 32
        guard let out = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: frameCapacity) else { return }
        var error: NSError?
        let inputBlock: AVAudioConverterInputBlock = { _, outStatus in
            outStatus.pointee = .haveData
            return buffer
        }
        converter.convert(to: out, error: &error, withInputFrom: inputBlock)
        if error != nil { return }
        guard let channel = out.int16ChannelData?.pointee else { return }
        let byteCount = Int(out.frameLength) * MemoryLayout<Int16>.size
        let data = Data(bytes: channel, count: byteCount)
        onPCM(data)
    }

    private func observeInterruption() {
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] note in
            guard let self else { return }
            guard
                let info = note.userInfo,
                let typeValue = info[AVAudioSessionInterruptionTypeKey] as? UInt,
                let type = AVAudioSession.InterruptionType(rawValue: typeValue)
            else { return }
            if type == .ended {
                try? self.engine.start()
            }
        }
    }
}
