import Foundation

/// Phone-side Brain client: POST an intent, then GET `intent_detail` while it runs.
final class IntentClient {
    static let defaultIntentURL = "http://115.190.153.53:9527/api/v1/intent"

    var lastServerURL: String = IntentClient.defaultIntentURL

    struct DispatchResult {
        let ok: Bool
        let message: String
        let snapshot: IntentJobSnapshot?
    }

    func dispatch(text: String, source: String, serverURL: String) async -> DispatchResult {
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedText.isEmpty else {
            return DispatchResult(ok: false, message: "text is empty", snapshot: nil)
        }
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmedURL), !trimmedURL.isEmpty else {
            return DispatchResult(ok: false, message: "invalid server_url", snapshot: nil)
        }

        let src = (source == "voice") ? "voice" : "text"
        var payload: [String: Any] = [
            "text": trimmedText,
            "source": src,
            "client_hint": ParticipantStore.clientHint,
        ]
        let pid = ParticipantStore.participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        if !pid.isEmpty {
            payload["participant_id"] = pid
            payload["edge_id"] = pid
        }
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return DispatchResult(ok: false, message: "encode JSON failed", snapshot: nil)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 60

        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent")
            guard let http = timed.http else {
                return DispatchResult(
                    ok: false,
                    message: "invalid intent response · \(timed.durationLabel)",
                    snapshot: nil
                )
            }
            let textBody = String(data: timed.data, encoding: .utf8) ?? ""
            let withTime = { (msg: String) in "\(msg)\n⏱ \(timed.durationLabel)" }
            if (200 ..< 300).contains(http.statusCode) {
                lastServerURL = trimmedURL
                let snapshot = IntentJobSnapshot.parse(data: timed.data)
                if snapshot == nil, IntentJobSnapshot.isSuccessWithoutIntentId(textBody) {
                    return DispatchResult(
                        ok: false,
                        message: withTime("服务端未返回 intent_id。"),
                        snapshot: nil
                    )
                }
                return DispatchResult(
                    ok: snapshot != nil,
                    message: withTime(textBody.isEmpty ? "intent ok HTTP \(http.statusCode)" : textBody),
                    snapshot: snapshot
                )
            }
            return DispatchResult(
                ok: false,
                message: withTime("intent HTTP \(http.statusCode): \(textBody.prefix(200))"),
                snapshot: nil
            )
        } catch let timed as TimedHTTP.Failure {
            return DispatchResult(ok: false, message: intentFailure(timed.nsError, duration: timed.durationLabel), snapshot: nil)
        } catch {
            return DispatchResult(ok: false, message: intentFailure(error as NSError, duration: nil), snapshot: nil)
        }
    }

    /// Register as Intent Source + Endpoint. Returns participant_id when Brain answers.
    func registerParticipant(serverURL: String) async -> String? {
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = Self.edgeRegisterURL(fromIntentURL: trimmedURL) else {
            return nil
        }
        let payload = ParticipantStore.registrationBody()
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return nil
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 20
        do {
            let timed = try await TimedHTTP.data(for: request, label: "edge-register")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
                  let obj = try JSONSerialization.jsonObject(with: timed.data) as? [String: Any] else {
                return nil
            }
            let pid = (obj["participant_id"] as? String)
                ?? (obj["edge_id"] as? String)
                ?? ""
            let trimmed = pid.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed.isEmpty ? nil : trimmed
        } catch {
            NSLog("[IntentClient] registerParticipant failed: %@", error.localizedDescription)
            return nil
        }
    }

    func fetchIntentDetail(intentId: String, intentURL: String? = nil) async -> IntentJobSnapshot? {
        let base = (intentURL ?? lastServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = Self.intentDetailURL(fromIntentURL: base, intentId: intentId) else {
            return nil
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 30
        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent-detail")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode) else {
                return nil
            }
            return IntentJobSnapshot.parse(data: timed.data)
        } catch {
            NSLog("[IntentClient] fetchIntentDetail failed: %@", error.localizedDescription)
            return nil
        }
    }

    struct HistoryPage {
        let snapshots: [IntentJobSnapshot]
        /// Exclusive cursor for the next page (`before_id`). Nil when exhausted.
        let nextBeforeId: Int?
        let exhausted: Bool
    }

    static let historyPageLimit = 5

    /// Older intents issued by this participant via `GET /api/v1/intents`.
    /// `beforeId` is exclusive. Omit it to get the newest page.
    func fetchIssuerHistory(
        participantId: String,
        beforeId: Int?,
        intentURL: String,
        limit: Int = IntentClient.historyPageLimit
    ) async -> HistoryPage {
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        let pageLimit = min(max(1, limit), IntentClient.historyPageLimit)
        guard !pid.isEmpty else {
            return HistoryPage(snapshots: [], nextBeforeId: nil, exhausted: true)
        }
        guard let url = Self.intentsListURL(
            fromIntentURL: intentURL,
            participantId: pid,
            beforeId: beforeId,
            limit: pageLimit
        ) else {
            return HistoryPage(snapshots: [], nextBeforeId: nil, exhausted: true)
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        do {
            let timed = try await TimedHTTP.data(for: request, label: "intents-list")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
                  let obj = try JSONSerialization.jsonObject(with: timed.data) as? [String: Any] else {
                return HistoryPage(snapshots: [], nextBeforeId: nil, exhausted: false)
            }
            let rows = obj["intents"] as? [Any] ?? []
            var snapshots: [IntentJobSnapshot] = []
            snapshots.reserveCapacity(min(rows.count, pageLimit))
            for row in rows {
                guard let json = row as? [String: Any],
                      let snap = IntentJobSnapshot.parse(json: json) else { continue }
                snapshots.append(snap)
            }
            let nextBefore: Int?
            if let n = obj["next_before_id"] as? Int {
                nextBefore = n
            } else if let n = obj["next_before_id"] as? NSNumber {
                nextBefore = n.intValue
            } else {
                nextBefore = snapshots.compactMap { Int($0.jobId) }.min()
            }
            let exhausted = (obj["exhausted"] as? Bool)
                ?? (obj["exhausted"] as? NSNumber)?.boolValue
                ?? (snapshots.count < pageLimit)
            return HistoryPage(
                snapshots: snapshots,
                nextBeforeId: exhausted ? nil : nextBefore,
                exhausted: exhausted
            )
        } catch {
            NSLog("[IntentClient] fetchIssuerHistory failed: %@", error.localizedDescription)
            return HistoryPage(snapshots: [], nextBeforeId: nil, exhausted: false)
        }
    }

    /// `…/api/v1/intent` → `…/api/v1/intents?participant_id=&before_id=&limit=`
    static func intentsListURL(
        fromIntentURL intentURL: String,
        participantId: String,
        beforeId: Int?,
        limit: Int
    ) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "intents"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "intents"
        } else {
            path = "/api/v1/intents"
        }
        components.path = path
        var items: [URLQueryItem] = [
            URLQueryItem(name: "participant_id", value: participantId),
            URLQueryItem(name: "limit", value: String(min(max(1, limit), historyPageLimit))),
        ]
        if let beforeId, beforeId >= 1 {
            items.append(URLQueryItem(name: "before_id", value: String(beforeId)))
        }
        components.queryItems = items
        return components.url
    }

    /// `…/api/v1/intent` → `…/api/v1/edge-register`
    static func edgeRegisterURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "edge-register"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "edge-register"
        } else {
            path = "/api/v1/edge-register"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    /// `…/api/v1/intent` → `…/api/v1/intent_detail?intent_id=`
    static func intentDetailURL(fromIntentURL intentURL: String, intentId: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "intent_detail"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "intent_detail"
        } else {
            path = "/api/v1/intent_detail"
        }
        components.path = path
        components.queryItems = [URLQueryItem(name: "intent_id", value: intentId)]
        return components.url
    }

    private func intentFailure(_ ns: NSError, duration: String?) -> String {
        let suffix = duration.map { "\n⏱ \($0)" } ?? ""
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNotConnectedToInternet {
            return "intent failed: no internet\(suffix)"
        }
        return "intent failed: \(ns.localizedDescription)\(suffix)"
    }
}
