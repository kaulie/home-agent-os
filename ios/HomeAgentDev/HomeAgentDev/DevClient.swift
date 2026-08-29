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
        targetHandle: String? = nil,
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
        if let targetHandle, !targetHandle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            body["target_handle"] = targetHandle.trimmingCharacters(in: .whitespacesAndNewlines)
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

    static func fetchFleet(
        brainURL: String,
        token: String
    ) async throws -> FleetSnapshot {
        let url = try endpoint(brainURL, path: "/api/v1/admin/agent_fleet")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(FleetSnapshot.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载 Fleet 失败")
        }
        return parsed
    }

    static func wakeFleetAgent(
        brainURL: String,
        token: String,
        handle: String,
        text: String = ""
    ) async throws -> FleetWakeResponse {
        let encoded = handle.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? handle
        let url = try endpoint(brainURL, path: "/api/v1/admin/agent_fleet/\(encoded)/wake")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["text": text])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(FleetWakeResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "唤醒失败")
        }
        return parsed
    }

    static func fetchReleases(
        brainURL: String,
        token: String
    ) async throws -> DeploySnapshot {
        let url = try endpoint(brainURL, path: "/api/v1/admin/releases")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 25
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DeploySnapshot.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载 Deploy 失败")
        }
        return parsed
    }

    static func fetchRelease(
        brainURL: String,
        token: String,
        releaseId: Int
    ) async throws -> DeployRelease {
        let url = try endpoint(brainURL, path: "/api/v1/admin/releases/\(releaseId)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 25
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DeployReleaseDetailResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载流水线详情失败")
        }
        guard let release = parsed.release else {
            throw DevClientError.server("release not found")
        }
        return release
    }

    static func approveRelease(
        brainURL: String,
        token: String,
        releaseId: Int,
        note: String = ""
    ) async throws -> DeployActionResponse {
        let url = try endpoint(brainURL, path: "/api/v1/admin/releases/\(releaseId)/approve")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 45
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["note": note])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DeployActionResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "批准失败")
        }
        return parsed
    }

    static func rejectRelease(
        brainURL: String,
        token: String,
        releaseId: Int,
        note: String = ""
    ) async throws -> DeployActionResponse {
        let url = try endpoint(brainURL, path: "/api/v1/admin/releases/\(releaseId)/reject")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 30
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["note": note])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DeployActionResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "拒绝失败")
        }
        return parsed
    }

    static func fetchAgentChat(
        brainURL: String,
        token: String,
        sinceId: Int = 0,
        sinceAckAt: Double = 0
    ) async throws -> AgentChatSnapshot {
        var path = "/api/v1/admin/agent_chat?since_id=\(max(0, sinceId))"
        if sinceAckAt > 0 {
            path += "&since_ack_at=\(sinceAckAt)"
        }
        let url = try endpoint(brainURL, path: path)
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(AgentChatSnapshot.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载 Chat 失败")
        }
        return parsed
    }

    static func sendAgentChatMessage(
        brainURL: String,
        token: String,
        body: String
    ) async throws -> AgentChatMessage {
        let url = try endpoint(brainURL, path: "/api/v1/admin/agent_chat/send")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["body": body])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        return try decodeAgentChatMessage(from: data)
    }

    static func ackAgentChatMessage(
        brainURL: String,
        token: String,
        messageId: Int,
        ackType: String = "ok"
    ) async throws -> AgentChatMessage {
        let url = try endpoint(brainURL, path: "/api/v1/admin/agent_chat/ack")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "message_id": messageId,
            "ack_type": ackType,
        ])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        return try decodeAgentChatMessage(from: data)
    }

    static func unackAgentChatMessage(
        brainURL: String,
        token: String,
        messageId: Int
    ) async throws -> AgentChatMessage {
        let url = try endpoint(brainURL, path: "/api/v1/admin/agent_chat/unack")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "message_id": messageId,
        ])
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        return try decodeAgentChatMessage(from: data)
    }

    static func promoteAgentChat(
        brainURL: String,
        token: String,
        text: String,
        targetHandle: String,
        category: String,
        anchorMessageId: Int?,
        backgroundMessageIds: [Int]
    ) async throws -> AgentChatPromoteResponse {
        let url = try endpoint(brainURL, path: "/api/v1/admin/agent_chat/promote")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 45
        applyAuth(&request, token: token)
        var payload: [String: Any] = [
            "text": text,
            "target_handle": targetHandle,
            "category": category,
            "background_message_ids": backgroundMessageIds,
        ]
        if let anchorMessageId {
            payload["anchor_message_id"] = anchorMessageId
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(AgentChatPromoteResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "转为 Dev Task 失败")
        }
        return parsed
    }

    private static func decodeAgentChatMessage(from data: Data) throws -> AgentChatMessage {
        if let wrapped = try? JSONDecoder().decode(AgentChatSendResponse.self, from: data),
           let message = wrapped.message {
            if wrapped.ok == false {
                throw DevClientError.server(wrapped.error ?? "Chat 操作失败")
            }
            return message
        }
        if let message = try? JSONDecoder().decode(AgentChatMessage.self, from: data), message.id > 0 {
            return message
        }
        throw DevClientError.decode
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

    static func fetchDocsIndex(
        brainURL: String,
        token: String
    ) async throws -> DevDocsIndexResponse {
        let url = try endpoint(brainURL, path: "/api/v1/admin/docs")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DevDocsIndexResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载文档列表失败")
        }
        return parsed
    }

    static func fetchDoc(
        brainURL: String,
        token: String,
        path: String
    ) async throws -> DevDocContent {
        let encoded = path.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? path
        let url = try endpoint(brainURL, path: "/api/v1/admin/docs/\(encoded)")
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        applyAuth(&request, token: token)
        let (data, response) = try await URLSession.shared.data(for: request)
        try throwIfNeeded(data: data, response: response)
        let parsed = try JSONDecoder().decode(DevDocContentResponse.self, from: data)
        if parsed.ok == false {
            throw DevClientError.server(parsed.error ?? "加载文档失败")
        }
        guard let doc = parsed.doc else {
            throw DevClientError.server("文档不存在")
        }
        return doc
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
            let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed.lowercased().contains("<html") || trimmed.lowercased().contains("<!doctype") {
                if http.statusCode == 404 {
                    throw DevClientError.http(
                        404,
                        "接口不存在（404）。本机 Brain 可能未重启，Deploy/Chat 新路由未加载。"
                    )
                }
                throw DevClientError.http(http.statusCode, "服务器返回了 HTML 错误页（HTTP \(http.statusCode)）")
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
