import AudioToolbox
import AVFoundation
import CoreMedia
import Foundation

private struct AacEncodeInputContext {
    var bytes: UnsafePointer<UInt8>?
    var byteCount: Int = 0
    var consumed = false
}

private func aacInputDataProc(
    _ converter: AudioConverterRef,
    _ ioNumberDataPackets: UnsafeMutablePointer<UInt32>,
    _ ioData: UnsafeMutablePointer<AudioBufferList>,
    _ outDataPacketDescription: UnsafeMutablePointer<UnsafeMutablePointer<AudioStreamPacketDescription>?>?,
    _ inUserData: UnsafeMutableRawPointer?
) -> OSStatus {
    guard let inUserData else {
        ioNumberDataPackets.pointee = 0
        return -1
    }
    let ctx = inUserData.assumingMemoryBound(to: AacEncodeInputContext.self)
    guard !ctx.pointee.consumed,
          let bytes = ctx.pointee.bytes,
          ctx.pointee.byteCount > 0 else {
        ioNumberDataPackets.pointee = 0
        return noErr
    }
    ioData.pointee.mNumberBuffers = 1
    ioData.pointee.mBuffers.mNumberChannels = 1
    ioData.pointee.mBuffers.mDataByteSize = UInt32(ctx.pointee.byteCount)
    ioData.pointee.mBuffers.mData = UnsafeMutableRawPointer(mutating: bytes)
    ioNumberDataPackets.pointee = 1024
    ctx.pointee.consumed = true
    return noErr
}

/// PCM (from AVCapture) → AAC-LC ADTS for MPEG-TS (PID 0x0101).
final class AacAudioEncoder {
    struct Config {
        var channels: UInt32 = 1
        var bitrate: UInt32 = 64_000
    }

    var onAccessUnit: ((Data, CMTime) -> Void)?

    private let config: Config
    private var converter: AudioConverterRef?
    private var sampleRate: Double = 48_000
    private var pcmFifo = Data()
    private var nextPts: CMTime?
    private let framesPerPacket: UInt32 = 1024
    private let bytesPerChunk: Int

    init(config: Config = Config()) {
        self.config = config
        bytesPerChunk = Int(framesPerPacket) * Int(config.channels) * MemoryLayout<Int16>.size
    }

    deinit {
        stop()
    }

    func stop() {
        if let converter {
            AudioConverterDispose(converter)
        }
        converter = nil
        pcmFifo.removeAll(keepingCapacity: false)
        nextPts = nil
    }

    func encode(sample: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sample),
              let formatDesc = CMSampleBufferGetFormatDescription(sample) else { return }
        if converter == nil, !setupConverter(formatDescription: formatDesc) {
            return
        }
        guard let converter else { return }

        guard let pcm = extractMonoInt16PCM(sample) else { return }
        pcmFifo.append(pcm)

        let pts = CMSampleBufferGetPresentationTimeStamp(sample)
        if nextPts == nil {
            nextPts = pts
        }

        while pcmFifo.count >= bytesPerChunk {
            let chunk = Data(pcmFifo.prefix(bytesPerChunk))
            pcmFifo.removeFirst(bytesPerChunk)
            let framePts = nextPts ?? pts
            if let adts = encodeChunk(chunk, converter: converter) {
                onAccessUnit?(adts, framePts)
            }
            let frameDuration = CMTime(
                value: CMTimeValue(framesPerPacket),
                timescale: CMTimeScale(sampleRate.rounded())
            )
            nextPts = CMTimeAdd(framePts, frameDuration)
        }
    }

    private func encodeChunk(_ pcm: Data, converter: AudioConverterRef) -> Data? {
        let outCapacity = 768
        let outPtr = UnsafeMutablePointer<UInt8>.allocate(capacity: outCapacity)
        defer { outPtr.deallocate() }

        return pcm.withUnsafeBytes { raw -> Data? in
            guard let base = raw.baseAddress?.assumingMemoryBound(to: UInt8.self) else { return nil }
            var inputCtx = AacEncodeInputContext(bytes: base, byteCount: pcm.count, consumed: false)
            var outPackets: UInt32 = 1
            var packetDesc = AudioStreamPacketDescription()
            var outABL = AudioBufferList(
                mNumberBuffers: 1,
                mBuffers: AudioBuffer(
                    mNumberChannels: config.channels,
                    mDataByteSize: UInt32(outCapacity),
                    mData: outPtr
                )
            )
            let encSt = withUnsafeMutablePointer(to: &inputCtx) { ctxPtr in
                AudioConverterFillComplexBuffer(
                    converter,
                    aacInputDataProc,
                    ctxPtr,
                    &outPackets,
                    &outABL,
                    &packetDesc
                )
            }
            guard encSt == noErr, outPackets > 0 else { return nil }
            let aacLen = Int(packetDesc.mDataByteSize > 0 ? packetDesc.mDataByteSize : outABL.mBuffers.mDataByteSize)
            guard aacLen > 0, aacLen <= outCapacity else { return nil }
            let rawAAC = Data(bytes: outPtr, count: aacLen)
            return Self.wrapADTS(
                aacPayload: rawAAC,
                sampleRate: sampleRate,
                channels: config.channels
            )
        }
    }

    private func setupConverter(formatDescription: CMFormatDescription) -> Bool {
        guard let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription) else {
            return false
        }
        let inputASBD = asbdPtr.pointee
        sampleRate = inputASBD.mSampleRate > 0 ? inputASBD.mSampleRate : 48_000

        var inFmt = AudioStreamBasicDescription()
        inFmt.mSampleRate = sampleRate
        inFmt.mFormatID = kAudioFormatLinearPCM
        inFmt.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked
        inFmt.mBytesPerPacket = 2 * config.channels
        inFmt.mFramesPerPacket = 1
        inFmt.mBytesPerFrame = 2 * config.channels
        inFmt.mChannelsPerFrame = config.channels
        inFmt.mBitsPerChannel = 16
        inFmt.mReserved = 0

        var out = AudioStreamBasicDescription()
        out.mSampleRate = sampleRate
        out.mFormatID = kAudioFormatMPEG4AAC
        out.mFormatFlags = UInt32(MPEG4ObjectID.AAC_LC.rawValue) << 2
        out.mBytesPerPacket = 0
        out.mFramesPerPacket = framesPerPacket
        out.mBytesPerFrame = 0
        out.mChannelsPerFrame = config.channels
        out.mBitsPerChannel = 0
        out.mReserved = 0

        var conv: AudioConverterRef?
        var st = AudioConverterNew(&inFmt, &out, &conv)
        guard st == noErr, let conv else { return false }
        var bitrate = config.bitrate
        st = AudioConverterSetProperty(
            conv,
            kAudioConverterEncodeBitRate,
            UInt32(MemoryLayout.size(ofValue: bitrate)),
            &bitrate
        )
        if st != noErr {
            AudioConverterDispose(conv)
            return false
        }
        converter = conv
        return true
    }

    private func extractMonoInt16PCM(_ sample: CMSampleBuffer) -> Data? {
        guard let formatDesc = CMSampleBufferGetFormatDescription(sample),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else {
            return nil
        }
        let asbd = asbdPtr.pointee
        let frames = Int(CMSampleBufferGetNumSamples(sample))
        guard frames > 0 else { return nil }

        var needed = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sample,
            bufferListSizeNeededOut: &needed,
            bufferListOut: nil,
            bufferListSize: 0,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: nil
        )
        guard needed > 0 else { return nil }

        let ablRaw = UnsafeMutableRawPointer.allocate(byteCount: needed, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { ablRaw.deallocate() }
        let abl = ablRaw.assumingMemoryBound(to: AudioBufferList.self)
        var blockBuffer: CMBlockBuffer?
        let listSt = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sample,
            bufferListSizeNeededOut: nil,
            bufferListOut: abl,
            bufferListSize: needed,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBuffer
        )
        guard listSt == noErr else { return nil }

        let buffers = UnsafeMutableAudioBufferListPointer(abl)
        guard !buffers.isEmpty else { return nil }

        let isFloat = asbd.mFormatFlags & kAudioFormatFlagIsFloat != 0
        let isNonInterleaved = asbd.mFormatFlags & kAudioFormatFlagIsNonInterleaved != 0
        let channels = max(1, Int(asbd.mChannelsPerFrame))
        var mono = [Int16](repeating: 0, count: frames)

        if isFloat {
            if isNonInterleaved {
                let channelCount = min(buffers.count, channels)
                for i in 0..<frames {
                    var sum: Float = 0
                    for ch in 0..<channelCount {
                        guard let data = buffers[ch].mData else { continue }
                        let ptr = data.assumingMemoryBound(to: Float.self)
                        sum += ptr[i]
                    }
                    mono[i] = Self.floatToInt16(sum / Float(channelCount))
                }
            } else {
                guard let data = buffers[0].mData else { return nil }
                let ptr = data.assumingMemoryBound(to: Float.self)
                for i in 0..<frames {
                    var sum: Float = 0
                    for ch in 0..<channels {
                        sum += ptr[i * channels + ch]
                    }
                    mono[i] = Self.floatToInt16(sum / Float(channels))
                }
            }
        } else {
            let bits = Int(asbd.mBitsPerChannel)
            if bits == 16 {
                if isNonInterleaved {
                    let channelCount = min(buffers.count, channels)
                    for i in 0..<frames {
                        var sum = 0
                        for ch in 0..<channelCount {
                            guard let data = buffers[ch].mData else { continue }
                            let ptr = data.assumingMemoryBound(to: Int16.self)
                            sum += Int(ptr[i])
                        }
                        mono[i] = Int16(clamping: sum / channelCount)
                    }
                } else {
                    guard let data = buffers[0].mData else { return nil }
                    let ptr = data.assumingMemoryBound(to: Int16.self)
                    for i in 0..<frames {
                        var sum = 0
                        for ch in 0..<channels {
                            sum += Int(ptr[i * channels + ch])
                        }
                        mono[i] = Int16(clamping: sum / channels)
                    }
                }
            }
        }

        return mono.withUnsafeBufferPointer { Data(buffer: $0) }
    }

    private static func floatToInt16(_ sample: Float) -> Int16 {
        let clipped = max(-1, min(1, sample))
        return Int16(clipped * 32767)
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
