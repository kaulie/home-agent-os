import Foundation

/// Shared HTTP helper: measures wall-clock latency for every request.
/// Logs to console + in-app event log; callers should also show `durationLabel` in panel responses.
enum TimedHTTP {
    static let logNotification = Notification.Name("LivingRoomEdge.TimedHTTPLog")

    struct Result {
        let data: Data
        let response: URLResponse
        let elapsedMs: Double

        var durationLabel: String { TimedHTTP.formatDuration(elapsedMs) }

        var http: HTTPURLResponse? { response as? HTTPURLResponse }

        var statusCode: Int { http?.statusCode ?? -1 }
    }

    struct Failure: Error, LocalizedError {
        let underlying: Error
        let elapsedMs: Double

        var durationLabel: String { TimedHTTP.formatDuration(elapsedMs) }

        var errorDescription: String? {
            "\(underlying.localizedDescription) · \(durationLabel)"
        }

        var nsError: NSError { underlying as NSError }
    }

    /// Perform `URLSession.shared.data(for:)` and log elapsed time.
    /// - Parameter label: short tag, e.g. `gopro`, `upload`, `server-download`, `intent`
    static func data(for request: URLRequest, label: String) async throws -> Result {
        let method = request.httpMethod ?? "GET"
        let url = request.url?.absoluteString ?? "(nil)"
        let started = CFAbsoluteTimeGetCurrent()
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            emit(
                "\(label) \(method) \(url) → HTTP \(code) · \(formatDuration(ms)) · \(data.count) bytes"
            )
            return Result(data: data, response: response, elapsedMs: ms)
        } catch {
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            emit(
                "\(label) \(method) \(url) → FAIL · \(formatDuration(ms)) · \(error.localizedDescription)"
            )
            throw Failure(underlying: error, elapsedMs: ms)
        }
    }

    static func formatDuration(_ ms: Double) -> String {
        if ms >= 1000 {
            return String(format: "%.2fs", ms / 1000)
        }
        return String(format: "%.0fms", ms)
    }

    private static func emit(_ line: String) {
        print("[HTTP] \(line)")
        NotificationCenter.default.post(
            name: logNotification,
            object: nil,
            userInfo: ["line": line]
        )
    }
}
