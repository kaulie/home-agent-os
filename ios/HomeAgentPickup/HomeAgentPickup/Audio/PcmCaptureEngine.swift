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

/// Captures microphone as mono s16le 44.1kHz PCM with far-field boost (AGC).
final class PcmCaptureEngine {
    /// Soft AGC keeps quiet / slightly-distant speech audible without hard clipping.
    private static let agcTargetRMS: Float = 0.14
    private static let agcMinGain: Float = 2.0
    private static let agcMaxGain: Float = 12.0
    private static let fixedPreamp: Float = 1.8

    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var targetFormat: AVAudioFormat?
    private var onPCM: ((Data) -> Void)?
    private var onLevel: ((Float) -> Void)?
    private var interruptionObserver: NSObjectProtocol?
    private var routeObserver: NSObjectProtocol?
    private var levelEMA: Float = 0
    private var agcGain: Float = 4.0
    private let levelQueue = DispatchQueue(label: "homeagent.pickup.level")

    var isRunning: Bool { engine.isRunning }

    func start(onPCM: @escaping (Data) -> Void, onLevel: ((Float) -> Void)? = nil) throws {
        stop()
        self.onPCM = onPCM
        self.onLevel = onLevel
        levelEMA = 0
        agcGain = 4.0

        let session = AVAudioSession.sharedInstance()
        // .videoRecording keeps capture quality high without two-way AEC that can
        // suppress quiet far speech (unlike .voiceChat).
        try session.setCategory(.record, mode: .videoRecording, options: [])
        try session.setPreferredSampleRate(44_100)
        try session.setPreferredIOBufferDuration(0.02)
        try session.setActive(true, options: [])
        configureBuiltInMic(session)

        guard
            let target = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: 44_100,
                channels: 1,
                interleaved: true
            )
        else {
            throw PcmCaptureError.engineFailed("无法创建 PCM 格式")
        }
        targetFormat = target

        engine.reset()
        let input = engine.inputNode
        let hwFormat = input.outputFormat(forBus: 0)
        guard hwFormat.sampleRate > 0, hwFormat.channelCount > 0 else {
            throw PcmCaptureError.engineFailed(
                "麦克风硬件格式无效（\(hwFormat.sampleRate) Hz / \(hwFormat.channelCount) ch）"
            )
        }

        converter = AVAudioConverter(from: hwFormat, to: target)
        guard converter != nil else {
            throw PcmCaptureError.engineFailed("无法创建音频转换器")
        }

        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: hwFormat) { [weak self] buffer, _ in
            self?.handle(buffer: buffer)
        }

        observeInterruption()
        observeRouteChange()
        engine.prepare()
        try engine.start()
    }

    func stop() {
        if engine.isRunning {
            engine.stop()
        }
        engine.inputNode.removeTap(onBus: 0)
        converter = nil
        targetFormat = nil
        onPCM = nil
        onLevel = nil
        levelEMA = 0
        if let interruptionObserver {
            NotificationCenter.default.removeObserver(interruptionObserver)
            self.interruptionObserver = nil
        }
        if let routeObserver {
            NotificationCenter.default.removeObserver(routeObserver)
            self.routeObserver = nil
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    /// Prefer built-in mic + omnidirectional pattern + max hardware gain.
    private func configureBuiltInMic(_ session: AVAudioSession) {
        if let builtin = session.availableInputs?.first(where: { $0.portType == .builtInMic }) {
            try? session.setPreferredInput(builtin)
            if let dataSources = builtin.dataSources, !dataSources.isEmpty {
                let preferred =
                    dataSources.first(where: {
                        $0.supportedPolarPatterns?.contains(.omnidirectional) == true
                    })
                    ?? dataSources.first(where: {
                        ($0.dataSourceName ?? "").localizedCaseInsensitiveContains("bottom")
                            || ($0.dataSourceName ?? "").localizedCaseInsensitiveContains("下")
                    })
                    ?? dataSources.first
                if let preferred {
                    try? preferred.setPreferredPolarPattern(.omnidirectional)
                    try? session.setInputDataSource(preferred)
                }
            }
        }
        if session.isInputGainSettable {
            try? session.setInputGain(1.0)
        }
    }

    private func handle(buffer: AVAudioPCMBuffer) {
        guard let targetFormat, let converter, let onPCM else {
            meterPCMBuffer(buffer)
            return
        }
        let ratio = targetFormat.sampleRate / max(buffer.format.sampleRate, 1)
        let frameCapacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 32
        guard frameCapacity > 0,
              let out = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: frameCapacity)
        else {
            meterPCMBuffer(buffer)
            return
        }

        var consumed = false
        var error: NSError?
        let inputBlock: AVAudioConverterInputBlock = { _, outStatus in
            if consumed {
                outStatus.pointee = .noDataNow
                return nil
            }
            consumed = true
            outStatus.pointee = .haveData
            return buffer
        }
        let status = converter.convert(to: out, error: &error, withInputFrom: inputBlock)
        guard error == nil, status != .error, out.frameLength > 0,
              let channel = out.int16ChannelData?.pointee
        else {
            meterPCMBuffer(buffer)
            return
        }

        let frames = Int(out.frameLength)
        applyFarFieldBoost(channel, frames: frames)
        meterInt16(channel, frames: frames)

        let byteCount = frames * MemoryLayout<Int16>.size
        onPCM(Data(bytes: channel, count: byteCount))
    }

    /// Adaptive gain toward target RMS, with soft knee limiter.
    private func applyFarFieldBoost(_ samples: UnsafeMutablePointer<Int16>, frames: Int) {
        guard frames > 0 else { return }

        var sumSquares: Float = 0
        var peak: Float = 0
        for i in 0 ..< frames {
            let n = Float(samples[i]) / Float(Int16.max)
            sumSquares += n * n
            let a = abs(n)
            if a > peak { peak = a }
        }
        let rms = sqrt(sumSquares / Float(frames))

        // Only chase gain when there is some signal (avoid pumping noise in silence).
        if rms > 0.002 {
            let desired = Self.agcTargetRMS / max(rms, 0.002)
            let clamped = min(Self.agcMaxGain, max(Self.agcMinGain, desired))
            // Slow attack / release so gain doesn't pump per buffer.
            let alpha: Float = clamped > agcGain ? 0.08 : 0.03
            agcGain = agcGain * (1 - alpha) + clamped * alpha
        } else {
            // Drift gently back toward a mid far-field boost while silent.
            agcGain = agcGain * 0.995 + 4.0 * 0.005
        }

        let gain = agcGain * Self.fixedPreamp
        for i in 0 ..< frames {
            let raw = Float(samples[i]) * gain
            // Soft clip tanh around ±28000 to keep headroom without harsh digital clip.
            let limited = tanhf(raw / 28_000) * 28_000
            let clipped = max(Float(Int16.min), min(Float(Int16.max), limited))
            samples[i] = Int16(clipped)
        }
    }

    private func meterPCMBuffer(_ buffer: AVAudioPCMBuffer) {
        let frames = Int(buffer.frameLength)
        guard frames > 0 else { return }

        var peak: Float = 0
        var sumSquares: Float = 0
        var counted = 0

        if let floats = buffer.floatChannelData {
            let chCount = max(Int(buffer.format.channelCount), 1)
            for ch in 0 ..< chCount {
                let samples = floats[ch]
                for i in 0 ..< frames {
                    let s = abs(samples[i])
                    if s > peak { peak = s }
                    sumSquares += samples[i] * samples[i]
                }
                counted += frames
            }
        } else if let ints = buffer.int16ChannelData {
            let chCount = max(Int(buffer.format.channelCount), 1)
            for ch in 0 ..< chCount {
                let samples = ints[ch]
                for i in 0 ..< frames {
                    let normalized = Float(samples[i]) / Float(Int16.max)
                    let s = abs(normalized)
                    if s > peak { peak = s }
                    sumSquares += normalized * normalized
                }
                counted += frames
            }
        } else {
            return
        }

        guard counted > 0 else { return }
        let rms = sqrt(sumSquares / Float(counted))
        publishLevel(max(rms * 2.2, peak * 1.35))
    }

    private func meterInt16(_ samples: UnsafePointer<Int16>, frames: Int) {
        guard frames > 0 else { return }
        var peak: Float = 0
        var sumSquares: Float = 0
        for i in 0 ..< frames {
            let n = Float(samples[i]) / Float(Int16.max)
            sumSquares += n * n
            let a = abs(n)
            if a > peak { peak = a }
        }
        let rms = sqrt(sumSquares / Float(frames))
        publishLevel(max(rms * 2.0, peak * 1.2))
    }

    private func publishLevel(_ instantRaw: Float) {
        guard let onLevel else { return }
        let instant = min(1, max(0, instantRaw))
        levelQueue.async { [weak self] in
            guard let self else { return }
            self.levelEMA = self.levelEMA * 0.35 + instant * 0.65
            let value = self.levelEMA
            DispatchQueue.main.async {
                onLevel(value)
            }
        }
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
                try? AVAudioSession.sharedInstance().setActive(true)
                try? self.engine.start()
            }
        }
    }

    private func observeRouteChange() {
        routeObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.routeChangeNotification,
            object: AVAudioSession.sharedInstance(),
            queue: .main
        ) { [weak self] _ in
            guard let self, self.onPCM != nil else { return }
            let session = AVAudioSession.sharedInstance()
            self.configureBuiltInMic(session)
            if !self.engine.isRunning {
                try? session.setActive(true)
                try? self.engine.start()
            }
        }
    }
}
