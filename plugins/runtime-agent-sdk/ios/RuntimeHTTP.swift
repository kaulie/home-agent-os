import Foundation

/// SDK-local timed HTTP. Independent of App TimedHTTP / GoProHTTP.
enum RuntimeHTTP {
    /// Prefer cellular/multipath when associated Wi‑Fi has no internet (e.g. GoPro AP).
    private static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.allowsCellularAccess = true
        config.waitsForConnectivity = true
        config.multipathServiceType = .handover
        return URLSession(configuration: config)
    }()

    struct Result {
        let data: Data
        let response: URLResponse
        let elapsedMs: Double

        var durationLabel: String { RuntimeHTTP.formatDuration(elapsedMs) }
        var http: HTTPURLResponse? { response as? HTTPURLResponse }
        var statusCode: Int { http?.statusCode ?? -1 }
    }

    struct Failure: Error, LocalizedError {
        let underlying: Error
        let elapsedMs: Double

        var durationLabel: String { RuntimeHTTP.formatDuration(elapsedMs) }

        var errorDescription: String? {
            "\(underlying.localizedDescription) · \(durationLabel)"
        }

        var nsError: NSError { underlying as NSError }
    }

    static func data(for request: URLRequest, label: String) async throws -> Result {
        let method = request.httpMethod ?? "GET"
        let url = request.url?.absoluteString ?? "(nil)"
        var req = request
        req.allowsCellularAccess = true
        let started = CFAbsoluteTimeGetCurrent()
        do {
            let (data, response) = try await session.data(for: req)
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            print("[RuntimeHTTP] \(label) \(method) \(url) → HTTP \(code) · \(formatDuration(ms)) · \(data.count) bytes")
            return Result(data: data, response: response, elapsedMs: ms)
        } catch {
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            print("[RuntimeHTTP] \(label) \(method) \(url) → FAIL · \(formatDuration(ms)) · \(error.localizedDescription)")
            throw Failure(underlying: error, elapsedMs: ms)
        }
    }

    static func formatDuration(_ ms: Double) -> String {
        if ms >= 1000 {
            return String(format: "%.2fs", ms / 1000)
        }
        return String(format: "%.0fms", ms)
    }
}
