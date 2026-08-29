import Foundation

enum PickupFeedbackProblemType: CaseIterable, Identifiable {
    case connection
    case capture
    case audioQuality
    case other

    var id: String { label }

    var label: String {
        switch self {
        case .connection: return "连接异常"
        case .capture: return "采集异常"
        case .audioQuality: return "音质问题"
        case .other: return "其他"
        }
    }

    var problemTypeKey: String {
        switch self {
        case .connection, .capture: return "execution_error"
        case .audioQuality, .other: return "other"
        }
    }
}

struct PickupFeedbackResult {
    let ok: Bool
    let issueId: Int?
    let message: String
    let error: String
}

enum PickupFeedbackClient {
    static func debugReportURL(from brainURL: String) -> URL? {
        let trimmed = brainURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, var components = URLComponents(string: trimmed) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "debug/report"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "debug/report"
        } else if path.isEmpty || path == "/" {
            path = "/api/v1/debug/report"
        } else if !path.hasSuffix("debug/report") {
            path = path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/v1/debug/report"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func submit(
        brainURL: String,
        intentId: Int,
        participantId: String,
        problemType: PickupFeedbackProblemType,
        userSummary: String,
        clientSnapshot: [String: Any]
    ) async -> PickupFeedbackResult {
        guard intentId > 0 else {
            return PickupFeedbackResult(ok: false, issueId: nil, message: "", error: "请填写有效的 Intent 编号")
        }
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            return PickupFeedbackResult(ok: false, issueId: nil, message: "", error: "请先在反馈配置里填写 participant_id")
        }
        guard let url = debugReportURL(from: brainURL) else {
            return PickupFeedbackResult(ok: false, issueId: nil, message: "", error: "Brain URL 无效")
        }

        var payload: [String: Any] = [
            "intent_id": intentId,
            "participant_id": pid,
            "source": "pickup_terminal",
            "problem_type": problemType.problemTypeKey,
            "client_snapshot": clientSnapshot,
        ]
        let summary = userSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        if !summary.isEmpty {
            payload["user_summary"] = summary
        } else {
            payload["user_summary"] = "[拾音终端] \(problemType.label)"
        }

        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return PickupFeedbackResult(ok: false, issueId: nil, message: "", error: "JSON 编码失败")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 20

        do {
            let (data, resp) = try await URLSession.shared.data(for: request)
            guard let http = resp as? HTTPURLResponse else {
                return PickupFeedbackResult(ok: false, issueId: nil, message: "", error: "无 HTTP 响应")
            }
            let raw = String(data: data, encoding: .utf8) ?? ""
            guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return PickupFeedbackResult(
                    ok: false,
                    issueId: nil,
                    message: "",
                    error: raw.isEmpty ? "返回格式不对" : String(raw.prefix(200))
                )
            }
            if !(200 ..< 300).contains(http.statusCode) || obj["ok"] as? Bool != true {
                let err = (obj["error"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
                return PickupFeedbackResult(
                    ok: false,
                    issueId: nil,
                    message: "",
                    error: err?.isEmpty == false ? err! : String(raw.prefix(200))
                )
            }
            let issueId = obj["issue_id"] as? Int
            let message = (obj["message"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            return PickupFeedbackResult(
                ok: true,
                issueId: issueId,
                message: message?.isEmpty == false ? message! : "已提交反馈",
                error: ""
            )
        } catch {
            return PickupFeedbackResult(ok: false, issueId: nil, message: "", error: error.localizedDescription)
        }
    }
}
