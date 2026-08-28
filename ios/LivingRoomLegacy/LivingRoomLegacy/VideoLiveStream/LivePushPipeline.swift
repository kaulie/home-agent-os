import CoreMedia
import Foundation

final class LivePushPipeline {
    let transport = MpegTsTcpTransport()
    let muxer = MpegTsMuxer()
    var encoder: H264VideoEncoder?

    private let queue = DispatchQueue(label: "legacy.video.live.mux")
    private var frameIndex: UInt64 = 0
    private let ticksPerFrame: UInt64

    init(fps: Int = VideoLiveCapture.fps) {
        let rate = max(1, fps)
        ticksPerFrame = UInt64(90_000 / rate)
        muxer.includesAudio = false
    }

    func send(annexB: Data, keyframe: Bool, pts: CMTime) {
        queue.async { [self] in
            let pts90 = frameIndex * ticksPerFrame
            frameIndex += 1
            let ts = muxer.mux(annexB: annexB, pts90k: pts90, keyframe: keyframe)
            transport.send(ts)
        }
    }

    func stop() {
        encoder?.stop()
        encoder = nil
        queue.sync {
            transport.close()
            muxer.reset()
            frameIndex = 0
        }
    }
}
