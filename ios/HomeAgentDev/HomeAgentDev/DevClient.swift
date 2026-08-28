import Foundation

enum DevClientError: LocalizedError {
    case invalidURL
    case http(Int, String)
    case decode
    case server(String)

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
        }
    }
}

enum DevClient {
    static func fetchIssues(
        brainURL: String,
        token: String,
        limit: Int = 30,
        beforeId: Int? = nil
    ) async throws -> DevIssuesResponse {
        var path = "/api/v1/admin/debug/issues?limit=\(limit)"
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
        let parsed = try JSONDecoder().decode(DevIssuesResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载失败")
        }
        return parsed
    }

    static func fetchIssue(
        brainURL: String,
        token: String,
        issueId: Int
    ) async throws -> DebugIssue {
        let url = try endpoint(brainURL, path: "/api/v1/admin/debug/issue/\(issueId)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DebugIssueResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载失败")
        }
        guard let issue = parsed.issue else {
            throw DevClientError.server("issue not found")
        }
        return issue
    }

    static func fetchDevTasks(
        brainURL: String,
        token: String,
        limit: Int = 30,
        beforeId: Int? = nil,
        category: String? = nil
    ) async throws -> DevDevTasksResponse {
        var path = "/api/v1/admin/dev_tasks?limit=\(limit)"
        if let beforeId {
            path += "&before_id=\(beforeId)"
        }
        if let category, !category.isEmpty {
            path += "&category=\(category)"
        }
        let url = try endpoint(brainURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DevDevTasksResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载失败")
        }
        return parsed
    }

    static func submitDevTask(
        brainURL: String,
        token: String,
        text: String,
        continueTaskId: Int? = nil,
        threadId: Int? = nil,
        category: String? = nil,
        attachments: [DebugAttachment] = []
    ) async throws -> DevTask {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60
        applyAuth(&request, token: token)
        var body: [String: Any] = ["text": text]
        if let continueTaskId {
            body["continue_task_id"] = continueTaskId
        }
        if let threadId {
            body["thread_id"] = threadId
        }
        if let category, !category.isEmpty {
            body["category"] = category
        }
        if !attachments.isEmpty {
            body["attachments"] = attachments.map { $0.apiPayload() }
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let task = try JSONDecoder().decode(DevTask.self, from: data)
        if task.taskId <= 0 {
            throw DevClientError.server("未返回 task_id")
        }
        return task
    }

    static func uploadDevTaskAttachment(
        brainURL: String,
        token: String,
        fileData: Data,
        filename: String,
        mimeType: String,
        kind: String
    ) async throws -> DebugAttachment {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task/attachment/upload")
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()

        func appendField(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append(
                "Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n"
                    .data(using: .utf8)!
            )
        }

        appendField("kind", kind)
        appendField("mime_type", mimeType)
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\nContent-Type: \(mimeType)\r\n\r\n"
                .data(using: .utf8)!
        )
        body.append(fileData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 90
        applyAuth(&request, token: token)
        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        struct UploadResponse: Decodable {
            let ok: Bool?
            let error: String?
            let attachment: DebugAttachment?
        }
        let parsed = try JSONDecoder().decode(UploadResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "上传失败")
        }
        guard let attachment = parsed.attachment else {
            throw DevClientError.server("上传失败：未返回 attachment")
        }
        return attachment
    }

    static func devTaskAttachmentURL(
        brainURL: String,
        assetId: String,
        scopeId: String
    ) throws -> URL {
        let encoded = assetId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? assetId
        let scope = scopeId.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? scopeId
        return try endpoint(
            brainURL,
            path: "/api/v1/assets/\(encoded)/content?intent_id=\(scope)&representation=preview"
        )
    }

    static func fetchDevTaskAttachmentData(
        brainURL: String,
        assetId: String,
        scopeId: String,
        token: String = DevSettings.adminToken
    ) async throws -> Data {
        let url = try devTaskAttachmentURL(brainURL: brainURL, assetId: assetId, scopeId: scopeId)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 45
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        return data
    }

    static func patchDevTaskCategory(
        brainURL: String,
        token: String,
        taskId: Int,
        category: String
    ) async throws -> DevTask {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task/\(taskId)/category")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["category": category])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let task = try JSONDecoder().decode(DevTask.self, from: data)
        if task.taskId <= 0 {
            throw DevClientError.server("未返回 task_id")
        }
        return task
    }

    static func fetchDevTask(
        brainURL: String,
        token: String,
        taskId: Int
    ) async throws -> DevTask {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task/\(taskId)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let task = try JSONDecoder().decode(DevTask.self, from: data)
        if task.taskId <= 0 {
            throw DevClientError.server("dev task not found")
        }
        return task
    }

    static func cancelDevTask(
        brainURL: String,
        token: String,
        taskId: Int
    ) async throws -> DevTask {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task/\(taskId)/cancel")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let task = try JSONDecoder().decode(DevTask.self, from: data)
        if task.taskId <= 0 {
            throw DevClientError.server("dev task not found")
        }
        return task
    }

    static func fetchDevTaskUsage(
        brainURL: String,
        token: String,
        period: String = "week"
    ) async throws -> DevTokenUsageStats {
        let url = try endpoint(brainURL, path: "/api/v1/admin/dev_task/usage?period=\(period)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DevTokenUsageResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载 token 统计失败")
        }
        return parsed.usage ?? DevTokenUsageStats(
            periodKey: period,
            periodLabel: nil,
            period: .empty,
            allTime: .empty,
            recentTasks: []
        )
    }

    private static func endpoint(_ brainURL: String, path: String) throws -> URL {
        let base = DevSettings.normalize(brainURL)
        guard let url = URL(string: base + path) else {
            throw DevClientError.invalidURL
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
            throw DevClientError.http(-1, "无效响应")
        }
        let body = String(data: data, encoding: .utf8) ?? ""
        guard (200 ..< 300).contains(http.statusCode) else {
            if let parsed = try? JSONDecoder().decode(DevPolicyResponse.self, from: data),
               let err = parsed.error, !err.isEmpty {
                throw DevClientError.http(http.statusCode, err)
            }
            throw DevClientError.http(http.statusCode, String(body.prefix(200)))
        }
    }

    static func issueAttachmentURL(
        brainURL: String,
        assetId: String,
        intentId: Int
    ) throws -> URL {
        let encoded = assetId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? assetId
        return try endpoint(
            brainURL,
            path: "/api/v1/assets/\(encoded)/content?intent_id=\(intentId)&representation=preview"
        )
    }

    static func fetchIssueAttachmentData(
        brainURL: String,
        assetId: String,
        intentId: Int
    ) async throws -> Data {
        let url = try issueAttachmentURL(brainURL: brainURL, assetId: assetId, intentId: intentId)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        return data
    }
}
