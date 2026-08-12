import Foundation

/// Plugin-local timed HTTP (camera only). Independent of App TimedHTTP / RuntimeHTTP.
enum GoProHTTP {
    struct Result {
        let data: Data
        let response: URLResponse
        let elapsedMs: Double

        var durationLabel: String { GoProHTTP.formatDuration(elapsedMs) }
        var http: HTTPURLResponse? { response as? HTTPURLResponse }
        var statusCode: Int { http?.statusCode ?? -1 }
    }

    struct Failure: Error, LocalizedError {
        let underlying: Error
        let elapsedMs: Double

        var durationLabel: String { GoProHTTP.formatDuration(elapsedMs) }

        var errorDescription: String? {
            "\(underlying.localizedDescription) · \(durationLabel)"
        }

        var nsError: NSError { underlying as NSError }
    }

    static func data(for request: URLRequest, label: String) async throws -> Result {
        let method = request.httpMethod ?? "GET"
        let url = request.url?.absoluteString ?? "(nil)"
        let started = CFAbsoluteTimeGetCurrent()
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            let code = (response as? HTTPURLResponse)?.statusCode ?? -1
            print("[GoProHTTP] \(label) \(method) \(url) → HTTP \(code) · \(formatDuration(ms)) · \(data.count) bytes")
            return Result(data: data, response: response, elapsedMs: ms)
        } catch {
            let ms = (CFAbsoluteTimeGetCurrent() - started) * 1000
            print("[GoProHTTP] \(label) \(method) \(url) → FAIL · \(formatDuration(ms)) · \(error.localizedDescription)")
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
