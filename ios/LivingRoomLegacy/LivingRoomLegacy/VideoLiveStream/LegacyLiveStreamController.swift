import CoreMedia
import Foundation

/// UIKit-friendly live stream controller (no async/await).
final class LegacyLiveStreamController {
    enum Phase: String {
        case idle
        case starting
        case streaming
        case stopping
        case error
    }

    private(set) var phase: Phase = .idle {
        didSet {
            let current = phase
            DispatchQueue.main.async { [weak self] in
                self?.onPhaseChanged?(current)
            }
        }
    }

    var onPhaseChanged: ((Phase) -> Void)?
    private(set) var streamId = ""
    private(set) var endpoint = ""
    private(set) var errorMessage = ""

    let capture = VideoLiveCapture()
    private var pipeline: LivePushPipeline?
    private var lastIngestBase = ""

    var connectedHost: String {
        guard let url = URL(string: endpoint), let host = url.host, !host.isEmpty else {
            return endpoint
        }
        return host
    }

    func startPreview(completion: @escaping (Bool, String) -> Void) {
        capture.start(completion: completion)
    }

    func stopPreview() {
        capture.onFrame = nil
        if phase == .streaming || phase == .starting {
            stopStream(keepPreview: false, completion: nil)
        } else {
            pipeline?.stop()
            pipeline = nil
            capture.stop()
        }
    }

    func startStream(ingestBaseURL: String, includeAudio: Bool, completion: @escaping (Error?) -> Void) {
        let base = ingestBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !base.isEmpty else {
            phase = .error
            errorMessage = "请先在家长页填写 Mac ingest URL"
            completion(VideoLiveError.message(errorMessage))
            return
        }
        if includeAudio {
            phase = .error
            errorMessage = "P1 仅视频，音频后续版本支持"
            completion(VideoLiveError.message(errorMessage))
            return
        }
        guard capture.isRunning, capture.hasDevice else {
            phase = .error
            errorMessage = capture.statusMessage.isEmpty ? "相机未就绪" : capture.statusMessage
            completion(VideoLiveError.message(errorMessage))
            return
        }

        phase = .starting
        errorMessage = ""
        lastIngestBase = base

        prepare(baseURL: base) { [weak self] result in
            guard let self else { return }
            switch result {
            case .failure(let err):
                self.phase = .error
                self.errorMessage = err.localizedDescription
                completion(err)
            case .success(let prepared):
                self.beginStreaming(prepared: prepared, completion: completion)
            }
        }
    }

    func stopStream(keepPreview: Bool, completion: (() -> Void)?) {
        guard phase == .streaming || phase == .starting || pipeline != nil else {
            if phase != .error { phase = .idle }
            completion?()
            return
        }
        phase = .stopping
        capture.onFrame = nil
        let sid = streamId
        let base = lastIngestBase
        pipeline?.stop()
        pipeline = nil
        notifyStop(ingestBaseURL: base, streamId: sid) { [weak self] in
            guard let self else { return }
            if !keepPreview {
                self.capture.stop()
            }
            self.streamId = ""
            self.endpoint = ""
            self.phase = .idle
            self.errorMessage = ""
            completion?()
        }
    }

    private struct Prepared {
        var streamId: String
        var endpoint: String
    }

    private func beginStreaming(prepared: Prepared, completion: @escaping (Error?) -> Void) {
        streamId = prepared.streamId
        endpoint = prepared.endpoint

        guard let parsed = parseTcpEndpoint(prepared.endpoint) else {
            phase = .error
            errorMessage = "Mac 返回的 endpoint 无法解析"
            completion(VideoLiveError.message(errorMessage))
            return
        }

        let pipe = LivePushPipeline()
        pipe.transport.connect(host: parsed.host, port: parsed.port) { [weak self] err in
            guard let self else { return }
            if let err {
                self.phase = .error
                self.errorMessage = err.localizedDescription
                completion(err)
                return
            }

            pipe.muxer.reset()
            let enc: H264VideoEncoder
            do {
                enc = H264VideoEncoder(config: .init(
                    width: Int32(VideoLiveCapture.width),
                    height: Int32(VideoLiveCapture.height),
                    fps: Int32(VideoLiveCapture.fps),
                    bitrate: 800_000,
                    gop: Int32(VideoLiveCapture.fps)
                ))
                try enc.start()
            } catch {
                self.phase = .error
                self.errorMessage = error.localizedDescription
                completion(error)
                return
            }

            enc.onAccessUnit = { annexB, keyframe, pts in
                pipe.send(annexB: annexB, keyframe: keyframe, pts: pts)
            }
            pipe.encoder = enc
            self.pipeline = pipe
            self.capture.onFrame = { sample in
                pipe.encoder?.encode(sample: sample)
            }
            self.phase = .streaming
            completion(nil)
        }
    }

    private func prepare(baseURL: String, completion: @escaping (Result<Prepared, Error>) -> Void) {
        let root = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: root + "/api/v1/video-live/prepare") else {
            completion(.failure(VideoLiveError.message("Mac ingest URL 无效。")))
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = Data("{}".utf8)
        req.timeoutInterval = 8
        URLSession.shared.dataTask(with: req) { data, resp, err in
            if let err {
                DispatchQueue.main.async {
                    completion(.failure(VideoLiveError.message("无法连接 Mac ingest：\(err.localizedDescription)")))
                }
                return
            }
            guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode), let data else {
                DispatchQueue.main.async {
                    completion(.failure(VideoLiveError.message("无法连接 Mac ingest（检查 URL / 同一 Wi‑Fi）。")))
                }
                return
            }
            let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
            let sid = (obj["stream_id"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let ep = (obj["endpoint"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !sid.isEmpty, !ep.isEmpty else {
                DispatchQueue.main.async {
                    completion(.failure(VideoLiveError.message("Mac ingest 未返回 stream_id / endpoint。")))
                }
                return
            }
            DispatchQueue.main.async {
                completion(.success(Prepared(streamId: sid, endpoint: ep)))
            }
        }.resume()
    }

    private func notifyStop(ingestBaseURL: String, streamId: String, completion: @escaping () -> Void) {
        let root = ingestBaseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let sid = streamId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !root.isEmpty, !sid.isEmpty,
              let url = URL(string: root + "/api/v1/video-live/stop") else {
            completion()
            return
        }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["stream_id": sid])
        req.timeoutInterval = 5
        URLSession.shared.dataTask(with: req) { _, _, _ in
            DispatchQueue.main.async { completion() }
        }.resume()
    }

    private func parseTcpEndpoint(_ raw: String) -> (host: String, port: UInt16)? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme == "tcp",
              let host = url.host, !host.isEmpty else { return nil }
        let port = UInt16(url.port ?? 0)
        guard port > 0 else { return nil }
        return (host, port)
    }
}
