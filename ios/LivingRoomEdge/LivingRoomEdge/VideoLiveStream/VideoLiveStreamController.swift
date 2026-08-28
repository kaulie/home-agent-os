import CoreMedia
import Foundation
import UIKit

final class LivePushPipeline {
    let transport = MpegTsTcpTransport()
    let muxer = MpegTsMuxer()
    var encoder: H264VideoEncoder?
    var audioEncoder: AacAudioEncoder?
    private let queue = DispatchQueue(label: "homeagent.video.live.mux")
    private var frameIndex: UInt64 = 0
    private var audioPacketIndex: UInt64 = 0
    private let ticksPerFrame: UInt64
    private let audioTicksPerPacket: UInt64 = 1024 * 90_000 / 48_000

    init(fps: Int) {
        let rate = max(1, fps)
        ticksPerFrame = UInt64(90_000 / rate)
    }

    func send(annexB: Data, keyframe: Bool, pts: CMTime) {
        queue.async { [self] in
            let pts90 = frameIndex * ticksPerFrame
            frameIndex += 1
            let ts = muxer.mux(annexB: annexB, pts90k: pts90, keyframe: keyframe)
            transport.send(ts)
        }
    }

    func sendAudio(aacAdts: Data, pts: CMTime) {
        queue.async { [self] in
            let pts90 = audioPacketIndex * audioTicksPerPacket
            audioPacketIndex += 1
            let ts = muxer.muxAudio(aacAdts: aacAdts, pts90k: pts90)
            transport.send(ts)
        }
    }

    func stop() {
        encoder?.stop()
        encoder = nil
        audioEncoder?.stop()
        audioEncoder = nil
        queue.sync {
            transport.close()
            muxer.reset()
            frameIndex = 0
            audioPacketIndex = 0
        }
    }
}

@MainActor
final class VideoLiveStreamController: ObservableObject {
    enum Phase: String {
        case idle
        case starting
        case streaming
        case stopping
        case error
    }

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var streamId = ""
    @Published private(set) var startedAt: Date?
    @Published private(set) var resolution = "1920x1080"
    @Published private(set) var fps = 30
    @Published private(set) var bitrate = 4_000_000
    @Published private(set) var endpoint = ""
    @Published private(set) var errorMessage = ""
    @Published private(set) var streamIncludesAudio = false

    let capture = VideoLiveCapture()
    private var pipeline: LivePushPipeline?
    private var lastIngestBase = ""

    var uiStatus: String {
        switch phase {
        case .idle: return "OFF"
        case .starting: return "STARTING"
        case .streaming: return "LIVE"
        case .stopping: return "STOPPING"
        case .error: return "ERROR"
        }
    }

    var connectedHost: String {
        URL(string: endpoint)?.host ?? endpoint
    }

    func setAudioCaptureEnabled(_ enabled: Bool) {
        guard phase == .idle || phase == .error else { return }
        capture.setAudioEnabled(enabled)
    }

    func startPreview() {
        capture.start()
    }

    func stopPreview() {
        capture.onFrame = nil
        capture.onAudioSample = nil
        if phase == .streaming || phase == .starting {
            Task { await stopStream(keepPreview: false) }
        } else {
            pipeline?.stop()
            pipeline = nil
            capture.stop()
        }
    }

    func startStream(ingestBaseURL: String, includeAudio: Bool) async {
        let base = ingestBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty else {
            phase = .error
            errorMessage = "请先在设置里填写 Mac ingest URL"
            return
        }
        guard capture.authorization == .authorized,
              capture.hasDevice,
              capture.isRunning else {
            phase = .error
            errorMessage = capture.statusMessage.isEmpty ? "相机未就绪" : capture.statusMessage
            return
        }
        if includeAudio {
            guard capture.audioAuthorization == .authorized else {
                phase = .error
                errorMessage = capture.statusMessage.isEmpty ? "麦克风未就绪" : capture.statusMessage
                return
            }
        }
        streamIncludesAudio = includeAudio
        phase = .starting
        errorMessage = ""
        lastIngestBase = base
        do {
            let prepared = try await Self.prepare(baseURL: base)
            streamId = prepared.streamId
            endpoint = prepared.endpoint
            let (host, port) = try Self.parseTcpEndpoint(prepared.endpoint)
            let rate = Int32(max(15, capture.fps))
            let pipe = LivePushPipeline(fps: Int(rate))
            try await pipe.transport.connect(host: host, port: port)
            pipe.muxer.reset()
            pipe.muxer.includesAudio = includeAudio
            let w = Int32(capture.width)
            let h = Int32(capture.height)
            let br: Int32 = (w >= 1920) ? 2_500_000 : 1_500_000
            fps = Int(rate)
            bitrate = Int(br)
            resolution = "\(w)x\(h)"
            let enc = H264VideoEncoder(config: .init(width: w, height: h, fps: rate, bitrate: br, gop: rate))
            try enc.start()
            enc.onAccessUnit = { annexB, keyframe, pts in
                pipe.send(annexB: annexB, keyframe: keyframe, pts: pts)
            }
            pipe.encoder = enc
            if includeAudio {
                let aenc = AacAudioEncoder()
                aenc.onAccessUnit = { adts, pts in
                    pipe.sendAudio(aacAdts: adts, pts: pts)
                }
                pipe.audioEncoder = aenc
            }
            pipeline = pipe
            capture.onFrame = { sample in
                pipe.encoder?.encode(sample: sample)
            }
            if includeAudio {
                capture.onAudioSample = { sample in
                    pipe.audioEncoder?.encode(sample: sample)
                }
            } else {
                capture.onAudioSample = nil
            }
            startedAt = Date()
            phase = .streaming
        } catch {
            capture.onFrame = nil
            capture.onAudioSample = nil
            pipeline?.stop()
            pipeline = nil
            phase = .error
            errorMessage = error.localizedDescription
        }
    }

    func stopStream(keepPreview: Bool = true) async {
        guard phase == .streaming || phase == .starting || pipeline != nil else {
            if phase != .error { phase = .idle }
            return
        }
        phase = .stopping
        capture.onFrame = nil
        capture.onAudioSample = nil
        let sid = streamId
        let base = lastIngestBase
        pipeline?.stop()
        pipeline = nil
        await Self.notifyStop(ingestBaseURL: base, streamId: sid)
        if !keepPreview {
            capture.stop()
        }
        streamId = ""
        endpoint = ""
        startedAt = nil
        streamIncludesAudio = false
        phase = .idle
        errorMessage = ""
    }

    private struct Prepared {
        var streamId: String
        var endpoint: String
    }

    private static func prepare(baseURL: String) async throws -> Prepared {
        let root = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: root + "/api/v1/video-live/prepare") else {
            throw VideoLiveError.message("Mac ingest URL 无效。")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data("{}".utf8)
        req.timeoutInterval = 8
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw VideoLiveError.message("无法连接 Mac ingest（检查 URL / 同一 Wi‑Fi）。")
        }
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        let sid = (obj["stream_id"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let ep = (obj["endpoint"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !sid.isEmpty, !ep.isEmpty else {
            throw VideoLiveError.message("Mac ingest 未返回 stream_id / endpoint。")
        }
        return Prepared(streamId: sid, endpoint: ep)
    }

    private static func notifyStop(ingestBaseURL: String, streamId: String) async {
        let root = ingestBaseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let sid = streamId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !root.isEmpty, !sid.isEmpty,
              let url = URL(string: root + "/api/v1/video-live/stop") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["stream_id": sid])
        req.timeoutInterval = 5
        _ = try? await URLSession.shared.data(for: req)
    }

    private static func parseTcpEndpoint(_ raw: String) throws -> (String, UInt16) {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme == "tcp",
              let host = url.host, !host.isEmpty else {
            throw VideoLiveError.message("Mac 返回的 endpoint 无法解析：\(raw)")
        }
        let port = UInt16(url.port ?? 0)
        guard port > 0 else {
            throw VideoLiveError.message("Mac 返回的 ingest 端口无效。")
        }
        return (host, port)
    }
}
