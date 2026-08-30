import Foundation

/// Client-side energy gate before HAP1 send: drop silence, keep a short pre-roll,
/// and hold open for a hangover so mid-phrase pauses are not chopped.
final class HomeMicEnergyGate {
    /// Absolute RMS floor (post-AGC, 0…1). Below this never opens.
    private let absoluteFloor: Float = 0.007
    /// Open when rms >= max(absoluteFloor, noiseEMA * openRatio).
    private let openRatio: Float = 3.0
    /// Stay open while rms >= max(absoluteFloor * 0.7, noiseEMA * holdRatio).
    private let holdRatio: Float = 1.8
    private let noiseAlpha: Float = 0.04
    private let sampleRate: Double
    private let bytesPerSample = 2 // s16le mono

    private let preRollMs: Double
    private let hangoverMs: Double

    private var noiseEMA: Float = 0.006
    private var open = false
    private var quietMs: Double = 0
    private var preRoll: [Data] = []
    private var preRollBytes = 0

    private var maxPreRollBytes: Int {
        Int(sampleRate * (preRollMs / 1000.0) * Double(bytesPerSample))
    }

    init(
        sampleRate: Double = 44_100,
        preRollMs: Double = 220,
        hangoverMs: Double = 1100
    ) {
        self.sampleRate = sampleRate
        self.preRollMs = preRollMs
        self.hangoverMs = hangoverMs
    }

    func reset() {
        noiseEMA = 0.006
        open = false
        quietMs = 0
        preRoll.removeAll(keepingCapacity: true)
        preRollBytes = 0
    }

    /// Returns PCM chunks to send (may include flushed pre-roll). Empty = hold.
    func filter(_ pcm: Data, enabled: Bool) -> [Data] {
        guard enabled else {
            reset()
            return pcm.isEmpty ? [] : [pcm]
        }
        guard !pcm.isEmpty, pcm.count % bytesPerSample == 0 else { return [] }

        let frames = pcm.count / bytesPerSample
        let durationMs = Double(frames) / sampleRate * 1000.0
        let rms = Self.rmsS16le(pcm)

        if !open {
            if rms < absoluteFloor {
                // Track quiet baseline only when clearly not speech.
                noiseEMA = noiseEMA * (1 - noiseAlpha) + rms * noiseAlpha
            } else if rms < noiseEMA * openRatio {
                noiseEMA = noiseEMA * (1 - noiseAlpha * 0.5) + rms * noiseAlpha * 0.5
            }

            let openTh = max(absoluteFloor, noiseEMA * openRatio)
            if rms >= openTh {
                open = true
                quietMs = 0
                var out = preRoll
                preRoll.removeAll(keepingCapacity: true)
                preRollBytes = 0
                out.append(pcm)
                return out
            }
            pushPreRoll(pcm)
            return []
        }

        // Open: hysteresis + hangover.
        let holdTh = max(absoluteFloor * 0.7, noiseEMA * holdRatio)
        if rms >= holdTh {
            quietMs = 0
            if rms < absoluteFloor * 1.5 {
                noiseEMA = noiseEMA * (1 - noiseAlpha * 0.3) + rms * noiseAlpha * 0.3
            }
            return [pcm]
        }

        quietMs += durationMs
        if quietMs < hangoverMs {
            // Still in hangover — keep streaming so Mac segmenter sees the trail.
            return [pcm]
        }

        open = false
        quietMs = 0
        pushPreRoll(pcm)
        return []
    }

    private func pushPreRoll(_ pcm: Data) {
        preRoll.append(pcm)
        preRollBytes += pcm.count
        let cap = maxPreRollBytes
        while preRollBytes > cap, let first = preRoll.first {
            preRollBytes -= first.count
            preRoll.removeFirst()
        }
    }

    private static func rmsS16le(_ data: Data) -> Float {
        let count = data.count / 2
        guard count > 0 else { return 0 }
        var sum: Float = 0
        data.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for i in 0 ..< count {
                let n = Float(samples[i]) / Float(Int16.max)
                sum += n * n
            }
        }
        return sqrt(sum / Float(count))
    }
}
