import Foundation

struct BrainFailure: Error, CustomStringConvertible {
    let message: String
    var description: String { message }
}

enum BrainAPI {
    typealias JSONCompletion = (Result<[String: Any], BrainFailure>) -> Void
    typealias DataCompletion = (Result<Data, BrainFailure>) -> Void

    /// Same as User Console: 5s × 3. Session caps stay high so timeout ≠ DNS.
    static let heartbeatAttemptTimeout: TimeInterval = 5
    static let heartbeatMaxAttempts = 3
    static let heartbeatRetryGapSeconds: TimeInterval = 1

    private static let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 90
        config.timeoutIntervalForResource = 90
        return URLSession(configuration: config)
    }()

    static func register(intentURL: String, completion: @escaping (Result<String, BrainFailure>) -> Void) {
        guard let url = BrainURL.apiURL(fromIntentURL: intentURL, leaf: "edge-register") else {
            completion(.failure(BrainFailure(message: "invalid register URL")))
            return
        }
        DiscoveryDebugLog.shared.log("HTTP POST \(url.absoluteString)", category: "connect")
        let payload = ParticipantStore.registrationBody()
        postJSON(url: url, payload: payload) { result in
            switch result {
            case .failure(let err):
                completion(.failure(err))
            case .success(let obj):
                let pid = (obj["participant_id"] as? String ?? obj["edge_id"] as? String ?? "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                if pid.isEmpty {
                    completion(.failure(BrainFailure(message: "register: no participant_id")))
                } else {
                    ParticipantStore.participantId = pid
                    completion(.success(pid))
                }
            }
        }
    }

    static func heartbeat(
        intentURL: String,
        participantId: String,
        completion: @escaping (Result<HeartbeatResult, BrainFailure>) -> Void
    ) {
        guard let url = BrainURL.apiURL(fromIntentURL: intentURL, leaf: "edge-heartbeat") else {
            completion(.failure(BrainFailure(message: "invalid heartbeat URL")))
            return
        }
        let payload = ParticipantStore.heartbeatBody(participantId: participantId)
        heartbeatAttempt(url: url, payload: payload, attempt: 1, completion: completion)
    }

    private static func heartbeatAttempt(
        url: URL,
        payload: [String: Any],
        attempt: Int,
        completion: @escaping (Result<HeartbeatResult, BrainFailure>) -> Void
    ) {
        postJSON(url: url, payload: payload, timeout: heartbeatAttemptTimeout) { result in
            switch result {
            case .failure(let err):
                if shouldRetryHeartbeat(err.message), attempt < heartbeatMaxAttempts {
                    DispatchQueue.main.asyncAfter(deadline: .now() + heartbeatRetryGapSeconds) {
                        heartbeatAttempt(url: url, payload: payload, attempt: attempt + 1, completion: completion)
                    }
                    return
                }
                ParticipantStore.lastHeartbeatOk = false
                HeartbeatLog.append(ok: false, detail: err.message)
                completion(.failure(err))
            case .success(let obj):
                let ok = (obj["ok"] as? Bool) ?? true
                if ok {
                    ParticipantStore.lastHeartbeatOk = true
                    let detail = heartbeatDetail(from: obj)
                    HeartbeatLog.append(ok: true, detail: detail)
                    completion(.success(HeartbeatResult(ok: true, detail: detail)))
                } else {
                    let err = (obj["error"] as? String ?? "heartbeat rejected")
                    if shouldRetryHeartbeat(err), attempt < heartbeatMaxAttempts {
                        DispatchQueue.main.asyncAfter(deadline: .now() + heartbeatRetryGapSeconds) {
                            heartbeatAttempt(url: url, payload: payload, attempt: attempt + 1, completion: completion)
                        }
                        return
                    }
                    ParticipantStore.lastHeartbeatOk = false
                    HeartbeatLog.append(ok: false, detail: err)
                    completion(.failure(BrainFailure(message: err)))
                }
            }
        }
    }

    private static func shouldRetryHeartbeat(_ message: String) -> Bool {
        let msg = message.lowercased()
        if msg.contains("register first") || msg.contains("unknown edge") || msg.contains("http 401") {
            return false
        }
        return true
    }

    private static func heartbeatDetail(from obj: [String: Any]) -> String {
        var parts: [String] = []
        if let edge = obj["edge"] as? [String: Any] {
            if let skew = edge["clock_skew_ms"] as? Int {
                parts.append("skew \(skew)ms")
            } else if let skew = edge["clock_skew_ms"] as? NSNumber {
                parts.append("skew \(skew.intValue)ms")
            }
            if let eligible = edge["schedule_eligible"] as? Bool {
                parts.append(eligible ? "可调度" : "不可调度")
            }
        } else if let skew = obj["clock_skew_ms"] as? Int {
            parts.append("skew \(skew)ms")
        }
        if let status = obj["online_status"] as? String, !status.isEmpty {
            parts.append(status)
        }
        return parts.joined(separator: " · ")
    }

    static func postIntent(
        intentURL: String,
        text: String,
        participantId: String,
        completion: @escaping (Result<IntentDetailSnapshot, BrainFailure>) -> Void
    ) {
        guard let url = URL(string: BrainURL.normalizeIntentURL(intentURL)) else {
            completion(.failure(BrainFailure(message: "invalid intent URL")))
            return
        }
        let payload: [String: Any] = [
            "text": text,
            "source": "text",
            "participant_id": participantId,
            "client_hint": ParticipantStore.clientHint,
            "edge_id": participantId,
        ]
        postJSON(url: url, payload: payload) { result in
            switch result {
            case .failure(let err):
                completion(.failure(err))
            case .success(let obj):
                if let data = try? JSONSerialization.data(withJSONObject: obj),
                   let snap = IntentDetailSnapshot.parseIntentPost(data: data) {
                    completion(.success(snap))
                    return
                }
                completion(.failure(BrainFailure(message: "intent: no intent_id in response")))
            }
        }
    }

    static func fetchIntentDetail(
        intentURL: String,
        intentId: String,
        completion: @escaping (Result<IntentDetailSnapshot, BrainFailure>) -> Void
    ) {
        guard let url = BrainURL.intentDetailURL(fromIntentURL: intentURL, intentId: intentId) else {
            completion(.failure(BrainFailure(message: "invalid intent_detail URL")))
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        dataTask(request: request) { result in
            switch result {
            case .failure(let err):
                completion(.failure(err))
            case .success(let data):
                if let snap = IntentDetailSnapshot.parse(data: data) {
                    completion(.success(snap))
                } else {
                    completion(.failure(BrainFailure(message: "intent_detail: parse failed")))
                }
            }
        }
    }

    private static func postJSON(url: URL, payload: [String: Any], timeout: TimeInterval = 20, completion: @escaping JSONCompletion) {
        guard JSONSerialization.isValidJSONObject(payload),
              let body = try? JSONSerialization.data(withJSONObject: payload) else {
            completion(.failure(BrainFailure(message: "JSON encode failed")))
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = timeout
        dataTask(request: request) { result in
            switch result {
            case .failure(let err):
                completion(.failure(err))
            case .success(let data):
                guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    let raw = String(data: data, encoding: .utf8) ?? ""
                    completion(.failure(BrainFailure(message: raw.isEmpty ? "invalid JSON" : String(raw.prefix(200)))))
                    return
                }
                completion(.success(obj))
            }
        }
    }

    private static func dataTask(request: URLRequest, completion: @escaping DataCompletion) {
        session.dataTask(with: request) { data, response, error in
            DispatchQueue.main.async {
                if let error = error {
                    let url = request.url ?? URL(string: "http://invalid")!
                    completion(.failure(BrainFailure(message: BrainURL.describeTransportError(error, url: url))))
                    return
                }
                guard let http = response as? HTTPURLResponse else {
                    completion(.failure(BrainFailure(message: "no HTTP response")))
                    return
                }
                let body = data ?? Data()
                guard (200 ..< 300).contains(http.statusCode) else {
                    let raw = String(data: body, encoding: .utf8) ?? ""
                    completion(.failure(BrainFailure(message: "HTTP \(http.statusCode): \(raw.prefix(200))")))
                    return
                }
                completion(.success(body))
            }
        }.resume()
    }

    static func uploadPhoto(
        intentURL: String,
        jpegData: Data,
        uploadIntent: String = "legacy.reading.photo",
        completion: @escaping (Result<String, BrainFailure>) -> Void
    ) {
        guard let url = BrainURL.assetsUploadURL(fromIntentURL: intentURL) else {
            completion(.failure(BrainFailure(message: "invalid assets/upload URL")))
            return
        }
        let pid = ParticipantStore.participantId
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()

        func appendField(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
        }

        appendField("upload_intent", uploadIntent)
        appendField("producer", uploadIntent)
        appendField("type", "image")
        appendField("mime_type", "image/jpeg")
        if !pid.isEmpty {
            appendField("edge_id", pid)
            appendField("participant_id", pid)
            appendField("client_hint", ParticipantStore.clientHint)
        }
        let filename = "reading_\(Int(Date().timeIntervalSince1970)).jpg"
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\nContent-Type: image/jpeg\r\n\r\n"
                .data(using: .utf8)!
        )
        body.append(jpegData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 90

        dataTask(request: request) { result in
            switch result {
            case .failure(let err):
                completion(.failure(err))
            case .success(let data):
                guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                    completion(.failure(BrainFailure(message: "upload: invalid JSON")))
                    return
                }
                let assetId = (obj["asset_id"] as? String)
                    ?? ((obj["asset"] as? [String: Any])?["asset_id"] as? String)
                    ?? ""
                if assetId.isEmpty {
                    let err = (obj["error"] as? String ?? obj["msg"] as? String ?? "upload failed")
                    completion(.failure(BrainFailure(message: err)))
                } else {
                    completion(.success(assetId))
                }
            }
        }
    }

    static func submitDebugReport(
        intentURL: String,
        intentId: String,
        participantId: String,
        clientSnapshot: [String: Any]? = nil,
        userSummary: String = "",
        completion: @escaping (Result<DebugReportResult, BrainFailure>) -> Void
    ) {
        let trimmedId = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let iid = Int(trimmedId), iid > 0 else {
            completion(.failure(BrainFailure(message: "invalid intent_id")))
            return
        }
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else {
            completion(.failure(BrainFailure(message: "participant_id is required")))
            return
        }
        guard let url = BrainURL.debugReportURL(fromIntentURL: intentURL) else {
            completion(.failure(BrainFailure(message: "invalid debug/report URL")))
            return
        }
        var payload: [String: Any] = [
            "intent_id": iid,
            "participant_id": pid,
            "source": "user_console",
        ]
        let summary = userSummary.trimmingCharacters(in: .whitespacesAndNewlines)
        if !summary.isEmpty {
            payload["user_summary"] = summary
        }
        if let clientSnapshot, !clientSnapshot.isEmpty {
            payload["client_snapshot"] = clientSnapshot
        }
        postJSON(url: url, payload: payload) { result in
            switch result {
            case .failure(let err):
                completion(.failure(err))
            case .success(let obj):
                let ok = (obj["ok"] as? Bool) == true
                if ok {
                    let issueId = (obj["issue_id"] as? Int) ?? (obj["issue_id"] as? NSNumber)?.intValue
                    let message = (obj["message"] as? String ?? "已提交反馈，正在分析。")
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    completion(.success(DebugReportResult(ok: true, issueId: issueId, message: message, error: "")))
                } else {
                    let err = (obj["error"] as? String ?? "提交失败")
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    completion(.success(DebugReportResult(ok: false, issueId: nil, message: "", error: err)))
                }
            }
        }
    }
}
