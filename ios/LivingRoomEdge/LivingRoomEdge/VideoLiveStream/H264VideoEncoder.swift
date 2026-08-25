import CoreMedia
import Foundation
import VideoToolbox

final class H264VideoEncoder {
    struct Config {
        var width: Int32
        var height: Int32
        var fps: Int32
        var bitrate: Int32
        var gop: Int32
    }

    var onAccessUnit: ((Data, Bool, CMTime) -> Void)?

    private var session: VTCompressionSession?
    private let lock = NSLock()
    private var config: Config
    private var forceKey = true

    init(config: Config) {
        self.config = config
    }

    func start() throws {
        lock.lock()
        defer { lock.unlock() }
        invalidateLocked()
        var sess: VTCompressionSession?
        let status = VTCompressionSessionCreate(
            allocator: kCFAllocatorDefault,
            width: config.width,
            height: config.height,
            codecType: kCMVideoCodecType_H264,
            encoderSpecification: nil,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: encoderCallback,
            refcon: Unmanaged.passUnretained(self).toOpaque(),
            compressionSessionOut: &sess
        )
        guard status == noErr, let sess else {
            throw VideoLiveError.message("编码器初始化失败（\(status)）。")
        }
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_RealTime, value: kCFBooleanTrue)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_ProfileLevel, value: kVTProfileLevel_H264_Main_AutoLevel)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_AverageBitRate, value: config.bitrate as CFNumber)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_ExpectedFrameRate, value: config.fps as CFNumber)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: config.gop as CFNumber)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_MaxKeyFrameIntervalDuration, value: 2 as CFNumber)
        VTSessionSetProperty(sess, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse)
        VTCompressionSessionPrepareToEncodeFrames(sess)
        session = sess
        forceKey = true
    }

    func stop() {
        lock.lock()
        defer { lock.unlock() }
        invalidateLocked()
    }

    func encode(sample: CMSampleBuffer) {
        lock.lock()
        let sess = session
        let key = forceKey
        forceKey = false
        lock.unlock()
        guard let sess, let pixel = CMSampleBufferGetImageBuffer(sample) else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sample)
        let duration = CMTime(value: 1, timescale: CMTimeScale(max(1, config.fps)))
        var flags = VTEncodeInfoFlags()
        var props: CFDictionary?
        if key {
            props = [kVTEncodeFrameOptionKey_ForceKeyFrame: kCFBooleanTrue] as CFDictionary
        }
        VTCompressionSessionEncodeFrame(
            sess,
            imageBuffer: pixel,
            presentationTimeStamp: pts,
            duration: duration,
            frameProperties: props,
            sourceFrameRefcon: nil,
            infoFlagsOut: &flags
        )
    }

    private func invalidateLocked() {
        if let session {
            VTCompressionSessionCompleteFrames(session, untilPresentationTimeStamp: .invalid)
            VTCompressionSessionInvalidate(session)
        }
        session = nil
    }

    fileprivate func handle(sample: CMSampleBuffer) {
        var keyframe = true
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false) as? [[String: Any]],
           let first = attachments.first {
            let notSync = first[kCMSampleAttachmentKey_NotSync as String] as? Bool ?? false
            keyframe = !notSync
        }
        guard let data = Self.annexB(from: sample, includeParameterSets: keyframe) else { return }
        let pts = CMSampleBufferGetPresentationTimeStamp(sample)
        onAccessUnit?(data, keyframe, pts)
    }

    private static func annexB(from sample: CMSampleBuffer, includeParameterSets: Bool) -> Data? {
        guard let block = CMSampleBufferGetDataBuffer(sample) else { return nil }
        var length = 0
        var dataPointer: UnsafeMutablePointer<Int8>?
        guard CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &length, dataPointerOut: &dataPointer) == noErr,
              let dataPointer, length > 4 else { return nil }
        var out = Data([0x00, 0x00, 0x00, 0x01, 0x09, 0xF0])
        var sampleBytes = Data()
        var offset = 0
        let raw = UnsafeRawPointer(dataPointer)
        while offset + 4 <= length {
            let b0 = UInt32(raw.load(fromByteOffset: offset, as: UInt8.self))
            let b1 = UInt32(raw.load(fromByteOffset: offset + 1, as: UInt8.self))
            let b2 = UInt32(raw.load(fromByteOffset: offset + 2, as: UInt8.self))
            let b3 = UInt32(raw.load(fromByteOffset: offset + 3, as: UInt8.self))
            let nalSize = Int((b0 << 24) | (b1 << 16) | (b2 << 8) | b3)
            offset += 4
            guard nalSize > 0, offset + nalSize <= length else { break }
            sampleBytes.append(contentsOf: [0x00, 0x00, 0x00, 0x01])
            sampleBytes.append(raw.advanced(by: offset).assumingMemoryBound(to: UInt8.self), count: nalSize)
            offset += nalSize
        }
        let hasSPS = Self.containsNAL(sampleBytes, type: 7)
        if includeParameterSets, !hasSPS, let format = CMSampleBufferGetFormatDescription(sample) {
            var paramCount = 0
            CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                format,
                parameterSetIndex: 0,
                parameterSetPointerOut: nil,
                parameterSetSizeOut: nil,
                parameterSetCountOut: &paramCount,
                nalUnitHeaderLengthOut: nil
            )
            if paramCount > 0 {
                for i in 0..<paramCount {
                    var ptr: UnsafePointer<UInt8>?
                    var size = 0
                    let st = CMVideoFormatDescriptionGetH264ParameterSetAtIndex(
                        format,
                        parameterSetIndex: i,
                        parameterSetPointerOut: &ptr,
                        parameterSetSizeOut: &size,
                        parameterSetCountOut: nil,
                        nalUnitHeaderLengthOut: nil
                    )
                    if st == noErr, let ptr, size > 0 {
                        out.append(contentsOf: [0x00, 0x00, 0x00, 0x01])
                        out.append(ptr, count: size)
                    }
                }
            }
        }
        out.append(sampleBytes)
        return out.count > 6 ? out : nil
    }

    private static func containsNAL(_ annexB: Data, type: UInt8) -> Bool {
        var i = 0
        let bytes = [UInt8](annexB)
        while i + 4 < bytes.count {
            if bytes[i] == 0, bytes[i + 1] == 0, bytes[i + 2] == 0, bytes[i + 3] == 1 {
                if (bytes[i + 4] & 0x1F) == type { return true }
                i += 4
                continue
            }
            if bytes[i] == 0, bytes[i + 1] == 0, bytes[i + 2] == 1 {
                if (bytes[i + 3] & 0x1F) == type { return true }
                i += 3
                continue
            }
            i += 1
        }
        return false
    }
}

private func encoderCallback(
    outputCallbackRefCon: UnsafeMutableRawPointer?,
    sourceFrameRefCon: UnsafeMutableRawPointer?,
    status: OSStatus,
    infoFlags: VTEncodeInfoFlags,
    sampleBuffer: CMSampleBuffer?
) {
    guard status == noErr, let sampleBuffer, let ref = outputCallbackRefCon else { return }
    let encoder = Unmanaged<H264VideoEncoder>.fromOpaque(ref).takeUnretainedValue()
    encoder.handle(sample: sampleBuffer)
}

enum VideoLiveError: LocalizedError {
    case message(String)
    var errorDescription: String? {
        switch self {
        case .message(let s): return s
        }
    }
}
