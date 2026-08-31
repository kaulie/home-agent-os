import Foundation

/// Shared formatting helpers for the video-live watch/replay views.
func videoLiveShortId(_ streamId: String) -> String {
    let prefix = "video_stream_"
    guard streamId.hasPrefix(prefix) else {
        return String(streamId.prefix(12))
    }
    return prefix + streamId.dropFirst(prefix.count).prefix(4)
}

func videoLiveISO(_ raw: String) -> Date? {
    ISO8601DateFormatter().date(from: raw)
}

func videoLiveTimeText(_ date: Date) -> String {
    let fmt = DateFormatter()
    fmt.locale = Locale(identifier: "zh_CN")
    fmt.dateFormat = "HH:mm:ss"
    return fmt.string(from: date)
}

func videoLiveByteText(_ bytes: Int) -> String {
    let value = Double(bytes)
    if value >= 1_000_000 {
        return String(format: "%.1f MB", value / 1_000_000)
    }
    if value >= 1_000 {
        return String(format: "%.0f KB", value / 1_000)
    }
    return "\(bytes) B"
}

/// One live session as reported by `GET /api/v1/video-live/status` on Mac Edge.
struct VideoLiveSession: Identifiable, Equatable {
    let streamId: String
    let source: String
    let status: String
    let startedAt: String
    let endpoint: String
    let bytesReceived: Int
    let playbackURL: String?
    let error: String?

    var id: String { streamId }

    /// Show in the watch list only when the session is actually producing data:
    /// status ∈ {starting, listening, streaming} AND (bytes_received > 0 OR streaming).
    var isListed: Bool {
        ["starting", "listening", "streaming"].contains(status)
            && (bytesReceived > 0 || status == "streaming")
    }

    var shortStreamId: String { videoLiveShortId(streamId) }

    var sourceLabel: String {
        source == "larix" ? "Larix" : "Console"
    }

    var startedAtLocal: String? {
        videoLiveISO(startedAt).map(videoLiveTimeText)
    }

    var bytesText: String {
        videoLiveByteText(bytesReceived)
    }
}

/// A completed session kept on disk for replay (`status.replays[]`).
struct VideoLiveReplay: Identifiable, Equatable {
    let streamId: String
    let source: String
    let startedAt: String
    let endedAt: String
    let bytesReceived: Int
    let segments: Int
    let playbackURL: String?

    var id: String { streamId }
    var shortStreamId: String { videoLiveShortId(streamId) }
    var sourceLabel: String { source == "larix" ? "Larix" : "Console" }
    var startedAtLocal: String? { videoLiveISO(startedAt).map(videoLiveTimeText) }
    var endedAtLocal: String? { videoLiveISO(endedAt).map(videoLiveTimeText) }
    var bytesText: String { videoLiveByteText(bytesReceived) }
    var segmentsText: String { "\(segments) 段" }

    var durationSeconds: TimeInterval {
        guard let start = videoLiveISO(startedAt), let end = videoLiveISO(endedAt) else { return 0 }
        return max(0, end.timeIntervalSince(start))
    }

    var durationText: String {
        let sec = Int(durationSeconds)
        let h = sec / 3600
        let m = (sec % 3600) / 60
        let s = sec % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%02d:%02d", m, s)
    }
}

/// What the player should do on open: live tracks the edge, replay plays the
/// whole archived session from the start.
enum LiveWatchPlayMode {
    case live
    case replay
}

/// Minimal description handed to the player (works for both live + replay rows).
struct LiveWatchPlaybackItem {
    let streamId: String
    let playbackURL: String?
    let mode: LiveWatchPlayMode

    var shortStreamId: String { videoLiveShortId(streamId) }
}

/// Whole `/api/v1/video-live/status` response.
struct VideoLiveStatus: Equatable {
    let overall: String
    let streams: [VideoLiveSession]
    let replays: [VideoLiveReplay]
}

enum VideoLiveStatusError: LocalizedError {
    case missingURL
    case invalidResponse
    case bonjourHost(String)

    var errorDescription: String? {
        switch self {
        case .missingURL: return "未配置 Mac ingest URL"
        case .invalidResponse: return "Mac Edge 返回内容无法解析"
        case let .bonjourHost(url): return "拒绝用 mDNS 名访问 Mac（\(url)）。请先自动发现 IPv4。"
        }
    }
}

/// Thin client for the Mac Edge video-live control HTTP.
struct VideoLiveStatusClient {
    /// Full status (all sessions in `streams`).
    static func fetchStatus(macIngestURL: String) async throws -> VideoLiveStatus {
        let root = macIngestURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if BrainEndpoint.isBonjourHost(root) {
            throw VideoLiveStatusError.bonjourHost(root)
        }
        guard !root.isEmpty, let url = URL(string: root + "/api/v1/video-live/status") else {
            throw VideoLiveStatusError.missingURL
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 5
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw VideoLiveStatusError.invalidResponse
        }
        guard let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
            throw VideoLiveStatusError.invalidResponse
        }
        let overall = obj["status"] as? String ?? "idle"
        let rawStreams = obj["streams"] as? [[String: Any]] ?? []
        let rawReplays = obj["replays"] as? [[String: Any]] ?? []
        return VideoLiveStatus(
            overall: overall,
            streams: rawStreams.map(VideoLiveSession.init(json:)),
            replays: rawReplays.map(VideoLiveReplay.init(json:))
        )
    }

    /// Single session (`status?stream_id=...`); nil when the stream is gone.
    static func fetchSession(macIngestURL: String, streamId: String) async throws -> VideoLiveSession? {
        let root = macIngestURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if BrainEndpoint.isBonjourHost(root) {
            throw VideoLiveStatusError.bonjourHost(root)
        }
        guard !root.isEmpty,
              let url = URL(string: root + "/api/v1/video-live/status?stream_id=" + streamId) else {
            throw VideoLiveStatusError.missingURL
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 5
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw VideoLiveStatusError.invalidResponse
        }
        guard let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              obj["stream_id"] != nil else {
            return nil
        }
        return VideoLiveSession(json: obj)
    }
}

extension VideoLiveSession {
    init(json: [String: Any]) {
        streamId = json["stream_id"] as? String ?? ""
        source = json["source"] as? String ?? ""
        status = json["status"] as? String ?? ""
        startedAt = json["started_at"] as? String ?? ""
        endpoint = json["endpoint"] as? String ?? ""
        bytesReceived = (json["bytes_received"] as? NSNumber)?.intValue ?? 0
        playbackURL = json["playback_url"] as? String
        error = json["error"] as? String
    }
}

extension VideoLiveReplay {
    init(json: [String: Any]) {
        streamId = json["stream_id"] as? String ?? ""
        source = json["source"] as? String ?? ""
        startedAt = json["started_at"] as? String ?? ""
        endedAt = json["ended_at"] as? String ?? ""
        bytesReceived = (json["bytes_received"] as? NSNumber)?.intValue ?? 0
        segments = (json["segments"] as? NSNumber)?.intValue ?? 0
        playbackURL = json["playback_url"] as? String
    }
}
