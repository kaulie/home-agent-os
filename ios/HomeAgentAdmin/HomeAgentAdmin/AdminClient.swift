import Foundation

enum AdminClientError: LocalizedError {
    case invalidURL
    case http(Int, String)
    case decode
    case server(String)
    case missingLogs

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Brain 地址无效"
        case .http(401, _):
            return "管理员令牌不对"
        case .http(let code, let body):
            let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.isEmpty { return "HTTP \(code)" }
            return trimmed
        case .decode:
            return "返回格式不对"
        case .server(let message):
            return message
        case .missingLogs:
            return "Brain 还没有操作日志接口"
        }
    }
}

enum AdminClient {
    static func fetchNodes(brainURL: String, token: String) async throws -> [AdminNode] {
        let url = try endpoint(brainURL, path: "/api/v1/admin/nodes")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed: AdminNodesResponse
        do {
            parsed = try JSONDecoder().decode(AdminNodesResponse.self, from: data)
        } catch {
            throw AdminClientError.decode
        }
        if parsed.ok == false {
            throw AdminClientError.server(parsed.error ?? "加载失败")
        }
        return parsed.nodes
    }

    static func setPolicy(
        brainURL: String,
        token: String,
        participantId: String,
        kind: PolicyTargetKind,
        targetId: String,
        enabled: Bool
    ) async throws {
        let url = try endpoint(brainURL, path: "/api/v1/admin/policy")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let body: [String: Any] = [
            "participant_id": participantId,
            "target_kind": kind.rawValue,
            "target_id": targetId,
            "enabled": enabled,
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try? JSONDecoder().decode(AdminPolicyResponse.self, from: data)
        if parsed?.ok == false {
            throw AdminClientError.server(parsed?.error ?? "保存失败")
        }
    }

    static func fetchLogs(brainURL: String, token: String, limit: Int = 100) async throws -> [AdminLogEntry] {
        let url = try endpoint(brainURL, path: "/api/v1/admin/logs?limit=\(limit)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        if let http = response as? HTTPURLResponse, http.statusCode == 404 || http.statusCode == 501 {
            throw AdminClientError.missingLogs
        }
        try throwIfNeeded(data: data, response: response)
        let parsed: AdminLogsResponse
        do {
            parsed = try JSONDecoder().decode(AdminLogsResponse.self, from: data)
        } catch {
            throw AdminClientError.decode
        }
        if parsed.ok == false {
            let message = parsed.error ?? "加载失败"
            if message.contains("admin_op_log") {
                throw AdminClientError.missingLogs
            }
            throw AdminClientError.server(message)
        }
        return parsed.logs.map { $0.asEntry() }
    }

    static func fetchIntents(
        brainURL: String,
        token: String,
        limit: Int = 50,
        beforeId: Int? = nil
    ) async throws -> AdminIntentsResponse {
        var path = "/api/v1/admin/intents?limit=\(limit)"
        if let beforeId {
            path += "&before_id=\(beforeId)"
        }
        let url = try endpoint(brainURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed: AdminIntentsResponse
        do {
            parsed = try JSONDecoder().decode(AdminIntentsResponse.self, from: data)
        } catch {
            throw AdminClientError.decode
        }
        if parsed.ok == false {
            throw AdminClientError.server(parsed.error ?? "加载失败")
        }
        return parsed
    }

    static func fetchDevTasks(
        brainURL: String,
        token: String,
        limit: Int = 30,
        beforeId: Int? = nil
    ) async throws -> AdminDevTasksResponse {
        var path = "/api/v1/admin/dev_tasks?limit=\(limit)"
        if let beforeId {
            path += "&before_id=\(beforeId)"
        }
        let url = try endpoint(brainURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed: AdminDevTasksResponse
        do {
            parsed = try JSONDecoder().decode(AdminDevTasksResponse.self, from: data)
        } catch {
            throw AdminClientError.decode
        }
        if parsed.ok == false {
            throw AdminClientError.server(parsed.error ?? "加载失败")
        }
        return parsed
    }

    static func submitDevTask(
        brainURL: String,
        token: String,
        text: String
    ) async throws -> AdminDevTask {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        applyAuth(&request, token: token)
        let body: [String: Any] = ["text": text]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let task: AdminDevTask
        do {
            task = try JSONDecoder().decode(AdminDevTask.self, from: data)
        } catch {
            throw AdminClientError.decode
        }
        if task.intentId <= 0 {
            throw AdminClientError.server("未返回 intent_id")
        }
        return task
    }

    static func fetchDevTask(
        brainURL: String,
        token: String,
        intentId: Int
    ) async throws -> AdminDevTask {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task/\(intentId)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let task: AdminDevTask
        do {
            task = try JSONDecoder().decode(AdminDevTask.self, from: data)
        } catch {
            throw AdminClientError.decode
        }
        if task.intentId <= 0 {
            throw AdminClientError.server("dev task not found")
        }
        return task
    }

    private static func endpoint(_ brainURL: String, path: String) throws -> URL {
        let base = AdminSettings.normalize(brainURL)
        guard let url = URL(string: base + path) else {
            throw AdminClientError.invalidURL
        }
        return url
    }

    private static func applyAuth(_ request: inout URLRequest, token: String) {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty {
            request.setValue(trimmed, forHTTPHeaderField: "X-Admin-Token")
        }
    }

    private static func throwIfNeeded(data: Data, response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw AdminClientError.http(-1, "无效响应")
        }
        let body = String(data: data, encoding: .utf8) ?? ""
        guard (200 ..< 300).contains(http.statusCode) else {
            if let parsed = try? JSONDecoder().decode(AdminPolicyResponse.self, from: data),
               let err = parsed.error, !err.isEmpty {
                throw AdminClientError.http(http.statusCode, err)
            }
            throw AdminClientError.http(http.statusCode, String(body.prefix(200)))
        }
    }
}
