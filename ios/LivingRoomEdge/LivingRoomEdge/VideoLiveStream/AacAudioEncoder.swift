import AudioToolbox
import AVFoundation
import CoreMedia
import Foundation

private struct AacEncodeInputContext {
    var bufferList: UnsafeMutablePointer<AudioBufferList>?
    var framesRemaining: UInt32 = 0
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
          let list = ctx.pointee.bufferList,
          ctx.pointee.framesRemaining > 0 else {
        ioNumberDataPackets.pointee = 0
        return noErr
    }
    ioData.pointee.mNumberBuffers = 1
    ioData.pointee.mBuffers = list.pointee.mBuffers
    ioNumberDataPackets.pointee = ctx.pointee.framesRemaining
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
    private var inputFormat = AudioStreamBasicDescription()
    private var outputSampleRate: Double = 48_000
    private var framesPerPacket: UInt32 = 1024
    private var bytesPerFrame: UInt32 = 0
    private var pcmRemainder = Data()
    private var nextPts: CMTime?

    init(config: Config = Config()) {
        self.config = config
    }

    deinit {
        stop()
    }

    func stop() {
        if let converter {
            AudioConverterDispose(converter)
        }
        converter = nil
        pcmRemainder.removeAll(keepingCapacity: false)
        nextPts = nil
    }

    func encode(sample: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sample),
              let formatDesc = CMSampleBufferGetFormatDescription(sample) else { return }
        if converter == nil, !setupConverter(formatDescription: formatDesc) {
            return
        }
        guard let converter, bytesPerFrame > 0 else { return }

        var blockBuffer: CMBlockBuffer?
        let ablSize = MemoryLayout<AudioBufferList>.size + MemoryLayout<AudioBuffer>.size * 8
        let ablRaw = UnsafeMutableRawPointer.allocate(byteCount: ablSize, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { ablRaw.deallocate() }
        let ablPtr = ablRaw.assumingMemoryBound(to: AudioBufferList.self)
        var needed = 0
        let listSt = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sample,
            bufferListSizeNeededOut: &needed,
            bufferListOut: ablPtr,
            bufferListSize: ablSize,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBuffer
        )
        guard listSt == noErr else { return }

        let buffer = ablPtr.pointee.mBuffers
        guard let data = buffer.mData, buffer.mDataByteSize > 0 else { return }
        pcmRemainder.append(data.assumingMemoryBound(to: UInt8.self), count: Int(buffer.mDataByteSize))

        let pts = CMSampleBufferGetPresentationTimeStamp(sample)
        if nextPts == nil {
            nextPts = pts
        }

        let chunkBytes = Int(framesPerPacket * bytesPerFrame)
        while pcmRemainder.count >= chunkBytes {
            let chunk = pcmRemainder.prefix(chunkBytes)
            pcmRemainder.removeFirst(chunkBytes)
            let framePts = nextPts ?? pts
            if let encoded = encodeChunk(Data(chunk), converter: converter) {
                onAccessUnit?(encoded, framePts)
            }
            let frameDuration = CMTime(
                value: CMTimeValue(framesPerPacket),
                timescale: CMTimeScale(outputSampleRate.rounded())
            )
            nextPts = CMTimeAdd(framePts, frameDuration)
        }
    }

    private func encodeChunk(_ pcm: Data, converter: AudioConverterRef) -> Data? {
        let outCapacity = 768
        let outPtr = UnsafeMutablePointer<UInt8>.allocate(capacity: outCapacity)
        defer { outPtr.deallocate() }

        return pcm.withUnsafeBytes { raw -> Data? in
            guard let base = raw.baseAddress else { return nil }
            var abl = AudioBufferList(
                mNumberBuffers: 1,
                mBuffers: AudioBuffer(
                    mNumberChannels: config.channels,
                    mDataByteSize: UInt32(pcm.count),
                    mData: UnsafeMutableRawPointer(mutating: base)
                )
            )
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
            return withUnsafeMutablePointer(to: &abl) { ablPtr in
                var inputCtx = AacEncodeInputContext(
                    bufferList: ablPtr,
                    framesRemaining: framesPerPacket,
                    consumed: false
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
                    sampleRate: outputSampleRate,
                    channels: config.channels
                )
            }
        }
    }

    private func setupConverter(formatDescription: CMFormatDescription) -> Bool {
        guard let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription) else {
            return false
        }
        inputFormat = asbdPtr.pointee
        outputSampleRate = inputFormat.mSampleRate > 0 ? inputFormat.mSampleRate : 48_000
        bytesPerFrame = inputFormat.mBytesPerFrame > 0
            ? inputFormat.mBytesPerFrame
            : (inputFormat.mBitsPerChannel / 8) * max(1, inputFormat.mChannelsPerFrame)

        var out = AudioStreamBasicDescription()
        out.mSampleRate = outputSampleRate
        out.mFormatID = kAudioFormatMPEG4AAC
        out.mFormatFlags = UInt32(MPEG4ObjectID.AAC_LC.rawValue) << 2
        out.mBytesPerPacket = 0
        out.mFramesPerPacket = 1024
        out.mBytesPerFrame = 0
        out.mChannelsPerFrame = config.channels
        out.mBitsPerChannel = 0
        out.mReserved = 0
        framesPerPacket = out.mFramesPerPacket

        var conv: AudioConverterRef?
        var st = AudioConverterNew(&inputFormat, &out, &conv)
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
