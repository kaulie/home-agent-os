import Foundation

/// HTTP Edge → Brain: register (get edgeId) then heartbeat with that edgeId.
final class HttpEdgeReporter {
    /// Base host, e.g. `http://115.190.153.53:9527`
    var baseURL: String
    var enabled: Bool

    init(baseURL: String, enabled: Bool = true) {
        self.baseURL = baseURL
        self.enabled = enabled
    }

    private var root: String {
        baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    /// Default register path when no full URL override is given.
    var defaultRegisterURL: String { "\(root)/api/v1/edge-register" }
    /// Default heartbeat path when no full URL override is given.
    var defaultHeartbeatURL: String { "\(root)/api/v1/edge-heartbeat" }

    /// `POST /api/v1/edge-register` → Brain returns trusted `edgeId`.
    /// - Returns: decoded response + raw body (for debug UI) + duration label.
    @discardableResult
    func register(
        _ request: EdgeRegisterRequest,
        urlOverride: String? = nil
    ) async throws -> (response: EdgeRegisterResponse, rawBody: String, durationLabel: String) {
        guard enabled else {
            let id = request.clientHint?.trimmingCharacters(in: .whitespacesAndNewlines)
            let response = EdgeRegisterResponse(
                ok: true,
                status: "approved",
                edgeId: (id?.isEmpty == false) ? id! : "local-edge",
                message: "remote reporter disabled"
            )
            let raw =
                "{\"ok\":true,\"ts\":\(Date().timeIntervalSince1970),\"status\":\"approved\",\"edge_id\":\"\(response.edgeId)\",\"message\":\"remote reporter disabled\"}"
            return (response, raw, "0ms")
        }

        let urlString = (urlOverride?.trimmingCharacters(in: .whitespacesAndNewlines)).flatMap {
            $0.isEmpty ? nil : $0
        } ?? defaultRegisterURL
        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        let body = try encoder.encode(request)

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        req.timeoutInterval = 20

        let timed = try await TimedHTTP.data(for: req, label: "edge-register")
        guard let http = timed.http else {
            throw URLError(.badServerResponse)
        }
        let text = String(data: timed.data, encoding: .utf8) ?? ""
        let withTime = text.isEmpty
            ? "HTTP \(http.statusCode)\n⏱ \(timed.durationLabel)"
            : "\(text)\n⏱ \(timed.durationLabel)"
        guard (200 ..< 300).contains(http.statusCode) else {
            throw NSError(
                domain: "HttpEdgeReporter",
                code: http.statusCode,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "edge-register HTTP \(http.statusCode): \(text.prefix(200)) · \(timed.durationLabel)",
                ]
            )
        }
        let response = try JSONDecoder().decode(EdgeRegisterResponse.self, from: timed.data)
        return (response, withTime, timed.durationLabel)
    }

    /// `POST /api/v1/edge-heartbeat` (must include Brain-issued `edgeId`).
    /// - Returns: raw response body for debug UI.
    @discardableResult
    func heartbeat(
        _ info: EdgeNodeInfo,
        urlOverride: String? = nil
    ) async throws -> String {
        guard enabled else { return "(remote disabled)" }
        guard !info.edgeId.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw NSError(
                domain: "HttpEdgeReporter",
                code: 401,
                userInfo: [NSLocalizedDescriptionKey: "heartbeat requires edgeId; register first"]
            )
        }

        let urlString = (urlOverride?.trimmingCharacters(in: .whitespacesAndNewlines)).flatMap {
            $0.isEmpty ? nil : $0
        } ?? defaultHeartbeatURL
        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        let body = try encoder.encode(info)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 15

        let timed = try await TimedHTTP.data(for: request, label: "edge-heartbeat")
        guard let http = timed.http else {
            throw URLError(.badServerResponse)
        }
        let text = String(data: timed.data, encoding: .utf8) ?? ""
        let withTime = text.isEmpty
            ? "HTTP \(http.statusCode)\n⏱ \(timed.durationLabel)"
            : "\(text)\n⏱ \(timed.durationLabel)"
        guard (200 ..< 300).contains(http.statusCode) else {
            throw NSError(
                domain: "HttpEdgeReporter",
                code: http.statusCode,
                userInfo: [
                    NSLocalizedDescriptionKey:
                        "edge-heartbeat HTTP \(http.statusCode): \(text.prefix(200)) · \(timed.durationLabel)",
                ]
            )
        }
        if let obj = try? JSONSerialization.jsonObject(with: timed.data) as? [String: Any] {
            var brainMs: Int64?
            if let v = obj["brain_time_ms"] as? Int64 { brainMs = v }
            else if let v = obj["brain_time_ms"] as? Int { brainMs = Int64(v) }
            else if let v = obj["brain_time_ms"] as? Double { brainMs = Int64(v) }
            else if let edge = obj["edge"] as? [String: Any] {
                if let v = edge["brain_time_ms"] as? Int64 { brainMs = v }
                else if let v = edge["brain_time_ms"] as? Int { brainMs = Int64(v) }
                else if let v = edge["brain_time_ms"] as? Double { brainMs = Int64(v) }
            }
            BrainTimeSync.applyHeartbeat(brainTimeMs: brainMs)
        }
        return withTime
    }
}

/// Local MockBrain (plans / UI) + optional HTTP edge register/heartbeat.
@MainActor
final class CompositeBrainClient: BrainClient {
    let local: MockBrainClient
    let remote: HttpEdgeReporter?

    init(local: MockBrainClient, remote: HttpEdgeReporter? = nil) {
        self.local = local
        self.remote = remote
    }

    func registerEdge(_ request: EdgeRegisterRequest) async throws -> EdgeRegisterResponse {
        if let remote {
            let (response, _, _) = try await remote.register(request)
            _ = try await local.registerEdge(
                EdgeRegisterRequest(
                    clientHint: response.edgeId,
                    displayName: request.displayName,
                    deviceType: request.deviceType,
                    room: request.room,
                    services: request.services,
                    appVersion: request.appVersion
                )
            )
            return response
        }
        return try await local.registerEdge(request)
    }

    func reportEdgeInfo(_ info: EdgeNodeInfo) async throws {
        try await local.reportEdgeInfo(info)
        do {
            _ = try await remote?.heartbeat(info)
        } catch let err as NSError where err.domain == "HttpEdgeReporter" && err.code == 401 {
            throw err
        } catch {
            NSLog("[CompositeBrainClient] remote heartbeat failed: \(error.localizedDescription)")
        }
    }

    func fetchPlans(edgeId: String) async throws -> [Plan] {
        try await local.fetchPlans(edgeId: edgeId)
    }

    func report(_ report: ExecutionReport) async throws {
        try await local.report(report)
    }
}
