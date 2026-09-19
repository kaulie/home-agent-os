import Foundation

/// Client-side energy gate before HAP1 send: drop silence, keep a short pre-roll,
/// and hold open for a hangover so mid-phrase pauses are not chopped.
///
/// It also *reports* how long the room has been quiet when it closes. The Mac
/// only receives speech (this gate), and its AGC lifts room tone above the fixed
/// energy thresholds, so silence is invisible over there: the segmenter used to
/// wait for `max_speech` (2.8s) before every wake clip, delaying
/// 「面条面条 → 我在呢」by ~1.4s. The quiet report (HAP1 type 5) lets Mac
/// `voice.stream` endpoint on wall clock like the USB mic.
/// See `agent_plans/phone_wake_latency_v1.md`.
final class HomeMicEnergyGate {
    /// Absolute RMS floor (post-AGC, 0…1). Below this never opens.
    private let absoluteFloor: Float = 0.007
    /// Open when rms >= max(absoluteFloor, noiseEMA * openRatio).
    private let openRatio: Float = 2.4
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
    /// Quiet ms measured when the gate last closed; read by the controller, which
    /// turns it into one HAP1 quiet frame. 0 = nothing to report.
    private var pendingQuietMs: Double = 0

    private var maxPreRollBytes: Int {
        Int(sampleRate * (preRollMs / 1000.0) * Double(bytesPerSample))
    }

    init(
        sampleRate: Double = 44_100,
        preRollMs: Double = 280,
        // Must stay ≥ MAC_VOICE_PHONE_WAKE_SILENCE_MS (350) so one quiet frame
        // already endpoints a wake clip on the Mac.
        hangoverMs: Double = 400
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
        pendingQuietMs = 0
    }

    /// Take the quiet window measured at the last close (ms); 0 = none.
    func takeQuietReportMs() -> Double {
        let ms = pendingQuietMs
        pendingQuietMs = 0
        return ms
    }

    /// Returns PCM chunks to send (may include flushed pre-roll). Empty = hold.
    ///
    /// The detector always runs; `enabled == false` only means "also upload the
    /// quiet audio" (debug: bandwidth instead of silence reporting).
    func filter(_ pcm: Data, enabled: Bool) -> [Data] {
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
                var out = enabled ? preRoll : []
                preRoll.removeAll(keepingCapacity: true)
                preRollBytes = 0
                out.append(pcm)
                return out
            }
            guard enabled else { return [pcm] }
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
        // Hand the Mac the missing wall-clock silence (speech has stopped).
        pendingQuietMs = max(pendingQuietMs, quietMs)
        quietMs = 0
        guard enabled else { return [pcm] }
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
