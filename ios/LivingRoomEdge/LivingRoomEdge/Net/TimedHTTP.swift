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

    /// Edge control-plane calls (ping / heartbeat / register). Must not wait for
    /// connectivity: on GoPro Wi‑Fi the LAN Brain is unroutable and TCP SYN
    /// would otherwise sit far past `URLRequest.timeoutInterval`.
    private static let controlSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.waitsForConnectivity = false
        config.timeoutIntervalForRequest = 5
        config.timeoutIntervalForResource = 8
        return URLSession(configuration: config)
    }()

    /// Perform HTTP and log elapsed time.
    /// - Parameter hardTimeout: wall-clock cap. Cancels the transfer (needed when
    ///   the destination is on another subnet and TCP connect ignores request timeout).
    static func data(
        for request: URLRequest,
        label: String,
        hardTimeout: TimeInterval? = nil
    ) async throws -> Result {
        var req = request
        let session: URLSession
        if let hardTimeout {
            req.timeoutInterval = min(max(0.5, hardTimeout), req.timeoutInterval)
            session = controlSession
            return try await withHardTimeout(hardTimeout) {
                try await perform(req, label: label, session: session)
            }
        }
        session = .shared
        return try await perform(req, label: label, session: session)
    }

    private static func withHardTimeout(
        _ seconds: TimeInterval,
        _ work: @escaping () async throws -> Result
    ) async throws -> Result {
        try await withThrowingTaskGroup(of: Result.self) { group in
            group.addTask { try await work() }
            group.addTask {
                let ns = UInt64(max(0.5, seconds) * 1_000_000_000)
                try await Task.sleep(nanoseconds: ns)
                throw Failure(
                    underlying: URLError(.timedOut),
                    elapsedMs: seconds * 1000
                )
            }
            defer { group.cancelAll() }
            guard let first = try await group.next() else {
                throw Failure(underlying: URLError(.timedOut), elapsedMs: seconds * 1000)
            }
            return first
        }
    }

    private static func perform(
        _ request: URLRequest,
        label: String,
        session: URLSession
    ) async throws -> Result {
        let method = request.httpMethod ?? "GET"
        let url = request.url?.absoluteString ?? "(nil)"
        let started = CFAbsoluteTimeGetCurrent()
        do {
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
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
