import AVFoundation
import CoreMedia
import Foundation

/// PCM (from AVCapture) → AAC-LC ADTS for MPEG-TS (PID 0x0101).
final class AacAudioEncoder {
    struct Config {
        var channels: AVAudioChannelCount = 1
        var bitrate: Int = 64_000
    }

    var onAccessUnit: ((Data, CMTime) -> Void)?

    private let config: Config
    private var pcmConverter: AVAudioConverter?
    private var aacConverter: AVAudioConverter?
    private var pcmFormat: AVAudioFormat?
    private var aacFormat: AVAudioFormat?
    private var sampleRate: Double = 48_000
    private var pendingPCM: AVAudioPCMBuffer?
    private var nextPts: CMTime?
    private let framesPerPacket: AVAudioFrameCount = 1024

    init(config: Config = Config()) {
        self.config = config
    }

    func stop() {
        pcmConverter = nil
        aacConverter = nil
        pcmFormat = nil
        aacFormat = nil
        pendingPCM = nil
        nextPts = nil
    }

    func encode(sample: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sample),
              let formatDesc = CMSampleBufferGetFormatDescription(sample) else { return }
        if aacConverter == nil, !setupConverter(formatDescription: formatDesc) {
            return
        }
        guard let pcmFormat else { return }

        let frameCount = AVAudioFrameCount(CMSampleBufferGetNumSamples(sample))
        guard frameCount > 0,
              let captureFormat = captureFormat(from: formatDesc),
              let chunk = AVAudioPCMBuffer(pcmFormat: captureFormat, frameCapacity: frameCount) else { return }
        chunk.frameLength = frameCount
        let copyStatus = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sample,
            at: 0,
            frameCount: Int32(frameCount),
            into: chunk.mutableAudioBufferList
        )
        guard copyStatus == noErr else { return }

        let monoChunk: AVAudioPCMBuffer
        if let pcmConverter {
            guard let converted = convertToMono(chunk, converter: pcmConverter, format: pcmFormat) else { return }
            monoChunk = converted
        } else {
            monoChunk = chunk
        }

        let pts = CMSampleBufferGetPresentationTimeStamp(sample)
        if nextPts == nil { nextPts = pts }
        appendAndEncode(monoChunk, basePts: pts)
    }

    private var cachedCaptureFormat: AVAudioFormat?

    private func captureFormat(from formatDesc: CMFormatDescription) -> AVAudioFormat? {
        if let cachedCaptureFormat { return cachedCaptureFormat }
        guard var asbd = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc)?.pointee else { return nil }
        cachedCaptureFormat = AVAudioFormat(streamDescription: &asbd)
        return cachedCaptureFormat
    }

    private func convertToMono(
        _ input: AVAudioPCMBuffer,
        converter: AVAudioConverter,
        format: AVAudioFormat
    ) -> AVAudioPCMBuffer? {
        guard let output = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: input.frameLength) else { return nil }
        var error: NSError?
        var supplied = false
        let status = converter.convert(to: output, error: &error) { _, outStatus in
            if supplied {
                outStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            outStatus.pointee = .haveData
            return input
        }
        guard status != .error, output.frameLength > 0 else { return nil }
        return output
    }

    private func appendAndEncode(_ buffer: AVAudioPCMBuffer, basePts: CMTime) {
        guard let pcmFormat, let aacConverter, let aacFormat else { return }
        if pendingPCM == nil {
            pendingPCM = AVAudioPCMBuffer(pcmFormat: pcmFormat, frameCapacity: framesPerPacket)
        }
        guard let pending = pendingPCM else { return }

        var sourceOffset: AVAudioFrameCount = 0
        while sourceOffset < buffer.frameLength {
            let pendingSpace = framesPerPacket - pending.frameLength
            if pendingSpace == 0 {
                flushPending(converter: aacConverter, outputFormat: aacFormat, pts: nextPts ?? basePts)
                continue
            }
            let toCopy = min(pendingSpace, buffer.frameLength - sourceOffset)
            copyPCMFrames(from: buffer, sourceOffset: sourceOffset, to: pending, destOffset: pending.frameLength, count: toCopy)
            pending.frameLength += toCopy
            sourceOffset += toCopy
            if pending.frameLength == framesPerPacket {
                flushPending(converter: aacConverter, outputFormat: aacFormat, pts: nextPts ?? basePts)
            }
        }
    }

    private func flushPending(converter: AVAudioConverter, outputFormat: AVAudioFormat, pts: CMTime) {
        guard let pending = pendingPCM,
              pending.frameLength == framesPerPacket,
              let encoded = encodePCM(pending, converter: converter, outputFormat: outputFormat) else {
            return
        }
        let adts = Self.wrapADTS(
            aacPayload: encoded,
            sampleRate: sampleRate,
            channels: UInt32(config.channels)
        )
        onAccessUnit?(adts, nextPts ?? pts)
        let frameDuration = CMTime(
            value: CMTimeValue(framesPerPacket),
            timescale: CMTimeScale(sampleRate.rounded())
        )
        nextPts = CMTimeAdd(nextPts ?? pts, frameDuration)
        pending.frameLength = 0
    }

    private func encodePCM(
        _ input: AVAudioPCMBuffer,
        converter: AVAudioConverter,
        outputFormat: AVAudioFormat
    ) -> Data? {
        let maxPacketSize = converter.maximumOutputPacketSize
        let output = AVAudioCompressedBuffer(
            format: outputFormat,
            packetCapacity: 1,
            maximumPacketSize: maxPacketSize
        )

        var supplied = false
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, outStatus in
            if supplied {
                outStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            outStatus.pointee = .haveData
            return input
        }
        guard status != .error, output.byteLength > 0 else { return nil }
        return Data(bytes: output.data, count: Int(output.byteLength))
    }

    private func copyPCMFrames(
        from source: AVAudioPCMBuffer,
        sourceOffset: AVAudioFrameCount,
        to dest: AVAudioPCMBuffer,
        destOffset: AVAudioFrameCount,
        count: AVAudioFrameCount
    ) {
        guard let pcmFormat else { return }
        let channels = Int(pcmFormat.channelCount)
        if pcmFormat.commonFormat == .pcmFormatFloat32 {
            guard let src = source.floatChannelData, let dst = dest.floatChannelData else { return }
            for ch in 0..<channels {
                memcpy(
                    dst[ch].advanced(by: Int(destOffset)),
                    src[ch].advanced(by: Int(sourceOffset)),
                    Int(count) * MemoryLayout<Float>.size
                )
            }
        } else if pcmFormat.commonFormat == .pcmFormatInt16 {
            guard let src = source.int16ChannelData, let dst = dest.int16ChannelData else { return }
            for ch in 0..<channels {
                memcpy(
                    dst[ch].advanced(by: Int(destOffset)),
                    src[ch].advanced(by: Int(sourceOffset)),
                    Int(count) * MemoryLayout<Int16>.size
                )
            }
        }
    }

    private func setupConverter(formatDescription: CMFormatDescription) -> Bool {
        guard var captureASBD = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription)?.pointee,
              let captureFormat = AVAudioFormat(streamDescription: &captureASBD) else {
            return false
        }
        cachedCaptureFormat = captureFormat
        sampleRate = captureFormat.sampleRate

        guard let monoPCM = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: sampleRate,
            channels: config.channels,
            interleaved: false
        ) else { return false }

        var outASBD = AudioStreamBasicDescription(
            mSampleRate: sampleRate,
            mFormatID: kAudioFormatMPEG4AAC,
            mFormatFlags: UInt32(MPEG4ObjectID.AAC_LC.rawValue) << 2,
            mBytesPerPacket: 0,
            mFramesPerPacket: 1024,
            mBytesPerFrame: 0,
            mChannelsPerFrame: config.channels,
            mBitsPerChannel: 0,
            mReserved: 0
        )
        guard let aacFmt = AVAudioFormat(streamDescription: &outASBD) else { return false }
        guard let aacConv = AVAudioConverter(from: monoPCM, to: aacFmt) else { return false }
        aacConv.bitRate = config.bitrate

        if captureFormat == monoPCM {
            pcmConverter = nil
            pcmFormat = monoPCM
        } else {
            guard let pcmConv = AVAudioConverter(from: captureFormat, to: monoPCM) else { return false }
            pcmConverter = pcmConv
            pcmFormat = monoPCM
        }

        aacConverter = aacConv
        aacFormat = aacFmt
        pendingPCM = AVAudioPCMBuffer(pcmFormat: monoPCM, frameCapacity: framesPerPacket)
        return true
    }

    private static func wrapADTS(aacPayload: Data, sampleRate: Double, channels: UInt32) -> Data {
        let profile: UInt8 = 2
        let freqIdx = sampleRateIndex(sampleRate)
        let chanCfg = UInt8(min(channels, 7))
        let fullLen = aacPayload.count + 7
        var hdr = Data(count: 7)
        hdr[0] = 0xFF
        hdr[1] = 0xF1
        hdr[2] = (profile << 6) | (freqIdx << 2) | (chanCfg >> 2)
        hdr[3] = ((chanCfg & 0x03) << 6) | UInt8((fullLen >> 11) & 0x03)
        hdr[4] = UInt8((fullLen >> 3) & 0xFF)
        hdr[5] = UInt8(((fullLen & 0x07) << 5) | 0x1F)
        hdr[6] = 0xFC
        var out = hdr
        out.append(aacPayload)
        return out
    }

    private static func sampleRateIndex(_ rate: Double) -> UInt8 {
        let table: [Double] = [
            96_000, 88_200, 64_000, 48_000, 44_100, 32_000, 24_000, 22_050,
            16_000, 12_000, 11_025, 8_000, 7_350,
        ]
        for (i, r) in table.enumerated() where abs(r - rate) < 1 {
            return UInt8(i)
        }
        return 3
    }
}
