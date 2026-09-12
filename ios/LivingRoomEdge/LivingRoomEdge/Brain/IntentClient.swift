import Foundation
import UIKit

/// One click「对时」snapshot: local + LAN Brain + Cloud Brain, same timestamp format.
struct ClockSyncSample: Equatable {
    var localAt: Date
    var lanURL: String = ""
    var cloudURL: String = ""
    var lanServerAt: Date?
    var cloudServerAt: Date?
    /// Brain `skew_ms` = server − local. Positive = server ahead of this device.
    var lanSkewMs: Int?
    var cloudSkewMs: Int?
    var lanError: String = ""
    var cloudError: String = ""
}

/// Phone-side Brain client: POST an intent, then GET `intent_detail` while it runs.
final class IntentClient {
    static let defaultIntentURL = BrainEndpoint.defaultLanIntentURL
    static let defaultCloudIntentURL = BrainEndpoint.defaultCloudIntentURL

    var lastServerURL: String = IntentClient.defaultIntentURL

    struct DispatchResult {
        let ok: Bool
        let message: String
        let snapshot: IntentJobSnapshot?
    }

    func dispatch(
        text: String,
        source: String,
        serverURL: String,
        assetRef: [String: Any]? = nil,
        context: [String: Any]? = nil,
        capability: String? = nil,
        params: [String: Any]? = nil
    ) async -> DispatchResult {
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedCapability = (capability ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        // 直派（capability 非空）时 text 仅作展示/留痕，允许为空
        guard !trimmedText.isEmpty || !trimmedCapability.isEmpty else {
            return DispatchResult(ok: false, message: "text is empty", snapshot: nil)
        }
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let refuse = BrainEndpoint.refuseBonjourHTTP(trimmedURL) {
            return DispatchResult(ok: false, message: refuse, snapshot: nil)
        }
        guard let url = URL(string: trimmedURL), !trimmedURL.isEmpty else {
            return DispatchResult(ok: false, message: "invalid server_url", snapshot: nil)
        }

        let src: String
        if source == "voice" {
            src = "voice"
        } else if source == "visual" || assetRef != nil {
            src = "visual"
        } else {
            src = "text"
        }
        var payload: [String: Any] = [
            "text": trimmedText.isEmpty ? "直派 \(trimmedCapability)" : trimmedText,
            "source": src,
            "client_hint": ParticipantStore.clientHint,
        ]
        if !trimmedCapability.isEmpty {
            payload["capability"] = trimmedCapability
            payload["params"] = params ?? [:]
        }
        if let assetRef {
            payload["asset_ref"] = assetRef
            payload["context"] = ["asset_ref": assetRef]
        }
        // Named context inputs (e.g. pronunciation.assess reference_audio +
        // student_audio AssetRefs) are merged into payload["context"] so the
        // Brain planner can wire them into the assess step's input_constrict.
        if let context, !context.isEmpty {
            if var existing = payload["context"] as? [String: Any] {
                existing.merge(context) { _, new in new }
                payload["context"] = existing
            } else {
                payload["context"] = context
            }
        }
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

    /// Register as Intent Source + Endpoint. Returns participant_id and optional server time.
    /// Heartbeat-path self-heal should pass `timeout: 3` so one attempt cannot hang on register.
    func registerParticipant(serverURL: String, timeout: TimeInterval = 6) async -> (id: String, ts: Date?)? {
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if BrainEndpoint.refuseBonjourHTTP(trimmedURL) != nil {
            return nil
        }
        guard let url = Self.edgeRegisterURL(fromIntentURL: trimmedURL) else {
            return nil
        }
        var payload = ParticipantStore.registrationBody()
        await ParticipantStore.applyAvailability(to: &payload)
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return nil
        }
        let cap = max(0.5, timeout)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = cap
        do {
            let timed = try await TimedHTTP.data(for: request, label: "edge-register", hardTimeout: cap)
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
                  let obj = try JSONSerialization.jsonObject(with: timed.data) as? [String: Any] else {
                return nil
            }
            let pid = (obj["participant_id"] as? String)
                ?? (obj["edge_id"] as? String)
                ?? ""
            let trimmed = pid.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            let ts = Self.dateFromWire(obj["ts"] ?? obj["created_at"] ?? obj["registered_at"])
            return (trimmed, ts)
        } catch {
            NSLog("[IntentClient] registerParticipant failed: %@", error.localizedDescription)
            return nil
        }
    }

    enum HeartbeatSend {
        case ok(at: Date, roles: [String])
        case failed(String)
    }

    /// Build heartbeat JSON once (availability probe included) so retries reuse the same body.
    func prepareHeartbeatBody(participantId: String) async -> (data: Data?, error: String?) {
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else { return (nil, "participant_id 为空") }
        var payload = ParticipantStore.heartbeatBody()
        payload["edge_id"] = pid
        payload["participant_id"] = pid
        await ParticipantStore.applyAvailability(to: &payload)
        guard JSONSerialization.isValidJSONObject(payload),
              let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return (nil, "心跳 JSON 无法序列化")
        }
        return (body, nil)
    }

    func sendHeartbeat(
        serverURL: String,
        participantId: String,
        body: Data? = nil,
        hardTimeout: TimeInterval = 5
    ) async -> HeartbeatSend {
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !pid.isEmpty else { return .failed("participant_id 为空") }
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let refuse = BrainEndpoint.refuseBonjourHTTP(trimmedURL) {
            return .failed(refuse)
        }
        guard let url = Self.edgeHeartbeatURL(fromIntentURL: trimmedURL) else {
            return .failed("无法从 \(trimmedURL) 拼出 edge-heartbeat URL")
        }
        let wire: Data
        if let body {
            wire = body
        } else {
            let prepared = await prepareHeartbeatBody(participantId: pid)
            if let data = prepared.data {
                wire = data
            } else {
                return .failed(prepared.error ?? "心跳 JSON 无法序列化")
            }
        }
        let sentRoles = Self.rolesFromHeartbeatWire(wire)
        let cap = max(0.5, hardTimeout)
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = wire
        request.timeoutInterval = cap
        do {
            let timed = try await TimedHTTP.data(for: request, label: "edge-heartbeat", hardTimeout: cap)
            guard let http = timed.http else {
                return .failed("心跳无 HTTP 响应 · \(url.absoluteString) · \(timed.durationLabel)")
            }
            guard (200 ..< 300).contains(http.statusCode) else {
                let text = String(data: timed.data, encoding: .utf8) ?? ""
                let snippet = text.trimmingCharacters(in: .whitespacesAndNewlines)
                let clipped = snippet.isEmpty ? "(empty body)" : String(snippet.prefix(400))
                return .failed(
                    "心跳 HTTP \(http.statusCode) · \(url.absoluteString) · \(timed.durationLabel)\n\(clipped)"
                )
            }
            lastServerURL = trimmedURL
            let at = Self.dateFromHeartbeat(timed.data) ?? Date()
            return .ok(at: at, roles: sentRoles)
        } catch let timed as TimedHTTP.Failure {
            return .failed(
                BrainEndpoint.describeTransportError(timed.underlying, url: url, elapsed: timed.durationLabel)
            )
        } catch {
            return .failed(
                BrainEndpoint.describeTransportError(error, url: url, elapsed: "")
            )
        }
    }

    /// `roles` as actually serialized on the heartbeat request.
    private static func rolesFromHeartbeatWire(_ body: Data) -> [String] {
        guard let obj = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else {
            return []
        }
        let names: [String]
        if let arr = obj["roles"] as? [String] {
            names = arr
        } else if let arr = obj["roles"] as? [Any] {
            names = arr.compactMap { $0 as? String }
        } else {
            names = []
        }
        return ParticipantStore.allRoles.filter { names.contains($0) }
    }

    private static func dateFromHeartbeat(_ data: Data) -> Date? {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let raw = obj["server_received_at"]
            ?? (obj["edge"] as? [String: Any])?["server_received_at"]
        return dateFromWire(raw)
    }

    private static func dateFromWire(_ raw: Any?) -> Date? {
        if let s = raw as? String {
            let trimmed = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if let d = Double(trimmed), d > 0 {
                return dateFromEpoch(d)
            }
            let iso = ISO8601DateFormatter()
            iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let d = iso.date(from: trimmed) { return d }
            iso.formatOptions = [.withInternetDateTime]
            if let d = iso.date(from: trimmed) { return d }
            let f = DateFormatter()
            f.locale = Locale(identifier: "en_US_POSIX")
            f.timeZone = TimeZone(secondsFromGMT: 0)
            f.dateFormat = "yyyy-MM-dd HH:mm:ss"
            if let d = f.date(from: trimmed) { return d }
            return nil
        }
        let n: Double? = {
            if let d = raw as? Double { return d }
            if let i = raw as? Int { return Double(i) }
            if let num = raw as? NSNumber { return num.doubleValue }
            return nil
        }()
        guard let n, n > 0 else { return nil }
        return dateFromEpoch(n)
    }

    private static func dateFromEpoch(_ n: Double) -> Date {
        if n >= 1_000_000_000_000 { return Date(timeIntervalSince1970: n / 1000.0) }
        return Date(timeIntervalSince1970: n)
    }

    private static func jsonInt64(_ raw: Any?) -> Int64? {
        if let n = raw as? Int64 { return n }
        if let n = raw as? Int { return Int64(n) }
        if let n = raw as? Double { return Int64(n.rounded()) }
        if let n = raw as? NSNumber { return n.int64Value }
        if let s = raw as? String, let n = Int64(s.trimmingCharacters(in: .whitespacesAndNewlines)) {
            return n
        }
        return nil
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
            IntentDetailCache.save(intentId: intentId, data: timed.data)
            return IntentJobSnapshot.parse(data: timed.data)
        } catch {
            NSLog("[IntentClient] fetchIntentDetail failed: %@", error.localizedDescription)
            return nil
        }
    }

    /// Endpoint bytes via Brain: `GET /api/v1/assets/{id}/content?intent_id=&representation=`.
    /// Chat display defaults to `preview`; pass `original` for full resolution.
    func fetchAssetImageData(
        assetId: String,
        intentId: String,
        intentURL: String? = nil,
        representation: String = "preview"
    ) async -> Data? {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty, !iid.isEmpty else { return nil }
        let base = (intentURL ?? lastServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        let reps = representationCandidates(representation)
        for attempt in 0 ..< 4 {
            for rep in reps {
                guard let content = Self.assetContentURL(
                    fromIntentURL: base,
                    assetId: aid,
                    intentId: iid,
                    representation: rep
                ),
                let bytes = await getOKData(content),
                Self.decodesAsUIImage(bytes) else {
                    continue
                }
                return bytes
            }
            if attempt < 3 {
                try? await Task.sleep(nanoseconds: 1_500_000_000)
            }
        }
        return nil
    }

    /// Raw asset bytes via Brain content endpoint (audio / video / document…).
    /// Chat audio playback fetches the original so the console can play it locally.
    func fetchAssetData(
        assetId: String,
        intentId: String,
        intentURL: String? = nil,
        representation: String = "original"
    ) async -> Data? {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty, !iid.isEmpty else { return nil }
        let base = (intentURL ?? lastServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        let reps = representationCandidates(representation)
        for attempt in 0 ..< 4 {
            for rep in reps {
                guard let content = Self.assetContentURL(
                    fromIntentURL: base,
                    assetId: aid,
                    intentId: iid,
                    representation: rep
                ),
                let bytes = await getOKData(content),
                !bytes.isEmpty else {
                    continue
                }
                return bytes
            }
            if attempt < 3 {
                try? await Task.sleep(nanoseconds: 1_500_000_000)
            }
        }
        return nil
    }

    private func representationCandidates(_ preferred: String) -> [String] {
        let p = preferred.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if p.isEmpty || p == "preview" || p == "thumbnail" {
            return ["preview", "original"]
        }
        if p == "original" {
            return ["original", "preview"]
        }
        return [p, "original"]
    }

    private func getOKData(_ url: URL) async -> Data? {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 45
        do {
            let timed = try await TimedHTTP.data(for: request, label: "asset-bytes")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode) else {
                return nil
            }
            return timed.data
        } catch {
            NSLog("[IntentClient] asset GET failed: %@", error.localizedDescription)
            return nil
        }
    }

    private static func decodesAsUIImage(_ data: Data) -> Bool {
        UIImage(data: data) != nil
    }

    private static func looksLikeImage(_ data: Data) -> Bool {
        guard data.count >= 12 else { return false }
        let bytes = [UInt8](data.prefix(12))
        if bytes[0] == 0xFF, bytes[1] == 0xD8 { return true }
        if bytes[0] == 0x89, bytes[1] == 0x50, bytes[2] == 0x4E, bytes[3] == 0x47 { return true }
        if bytes[0] == 0x47, bytes[1] == 0x49, bytes[2] == 0x46 { return true }
        if bytes[0] == 0x52, bytes[1] == 0x49, bytes[2] == 0x46, bytes[3] == 0x46 { return true }
        return false
    }

    /// `…/api/v1/intent` → `…/api/v1/assets/{id}/content?intent_id=&representation=`
    static func assetContentURL(
        fromIntentURL intentURL: String,
        assetId: String,
        intentId: String,
        representation: String? = nil
    ) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "assets/\(assetId)/content"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "assets/\(assetId)/content"
        } else {
            path = "/api/v1/assets/\(assetId)/content"
        }
        components.path = path
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        var query: [URLQueryItem] = []
        if !iid.isEmpty {
            query.append(URLQueryItem(name: "intent_id", value: iid))
        }
        let rep = (representation ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !rep.isEmpty, rep != "original" {
            query.append(URLQueryItem(name: "representation", value: rep))
        }
        components.queryItems = query.isEmpty ? nil : query
        return components.url
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

    /// `…/api/v1/intent` → `…/api/v1/edge-heartbeat`
    static func edgeHeartbeatURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "edge-heartbeat"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "edge-heartbeat"
        } else {
            path = "/api/v1/edge-heartbeat"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    /// `…/api/v1/intent` → `…/api/v1/ping?client_time_ms=`
    static func pingURL(fromIntentURL intentURL: String, clientTimeMs: Int64) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "ping"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "ping"
        } else {
            path = "/api/v1/ping"
        }
        components.path = path
        components.queryItems = [
            URLQueryItem(name: "client_time_ms", value: String(clientTimeMs)),
        ]
        return components.url
    }

    enum ClockPing {
        case ok(serverAt: Date, skewMs: Int)
        case failed(String)
    }

    /// GET `/api/v1/ping` with `client_time_ms` derived from `clientSentAt`.
    func ping(serverURL: String, clientSentAt: Date, timeout: TimeInterval = 10) async -> ClockPing {
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        if let refuse = BrainEndpoint.refuseBonjourHTTP(trimmedURL) {
            return .failed(refuse)
        }
        let clientTimeMs = Int64((clientSentAt.timeIntervalSince1970 * 1000.0).rounded())
        guard let url = Self.pingURL(fromIntentURL: trimmedURL, clientTimeMs: clientTimeMs) else {
            return .failed("无法从 \(trimmedURL) 拼出 ping URL")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = timeout
        do {
            let timed = try await TimedHTTP.data(for: request, label: "ping", hardTimeout: timeout)
            guard let http = timed.http else {
                return .failed("对时无 HTTP 响应 · \(timed.durationLabel)")
            }
            guard (200 ..< 300).contains(http.statusCode) else {
                let text = String(data: timed.data, encoding: .utf8) ?? ""
                return .failed("对时 HTTP \(http.statusCode) · \(timed.durationLabel)\n\(text.prefix(200))")
            }
            guard let obj = try JSONSerialization.jsonObject(with: timed.data) as? [String: Any],
                  (obj["ok"] as? Bool) == true || (obj["ok"] as? NSNumber)?.boolValue == true else {
                return .failed("对时响应无效 · \(timed.durationLabel)")
            }
            guard let serverMs = Self.jsonInt64(obj["server_time_ms"])
                    ?? Self.jsonInt64(obj["server_time"]).map({ $0 * 1000 }) else {
                return .failed("对时响应缺少 server_time_ms")
            }
            let skew: Int
            if let n = Self.jsonInt64(obj["skew_ms"]) {
                skew = Int(n)
            } else {
                skew = Int(serverMs - clientTimeMs)
            }
            return .ok(
                serverAt: Date(timeIntervalSince1970: TimeInterval(serverMs) / 1000.0),
                skewMs: skew
            )
        } catch let timed as TimedHTTP.Failure {
            return .failed(
                BrainEndpoint.describeTransportError(timed.underlying, url: url, elapsed: timed.durationLabel)
            )
        } catch {
            return .failed(BrainEndpoint.describeTransportError(error, url: url, elapsed: ""))
        }
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

    private static let runtimeCapabilities: Set<String> = [
        "camera.capture",
        "camera.capture_and_upload",
        "asset.upload",
        "light.set",
        "climate.set",
        "document.scan",
        "visual.input",
        "video.live_stream",
    ]

    func pullRuntimeIntents(edgeId: String, intentURL: String) async -> [RuntimeStepJob] {
        let eid = edgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        var jobs: [RuntimeStepJob] = []
        for item in await peekLivingRoomIntents(edgeId: eid, intentURL: intentURL) {
            let iid = stringId(item["intent_id"] ?? item["id"])
            guard !iid.isEmpty else { continue }
            let wire = (item["status"] as? String ?? item["intent_status"] as? String ?? "")
                .lowercased()
            if wire == "succeeded" || wire == "failed" { continue }
            let plan = item["execution_plan"] as? [[String: Any]] ?? []
            for step in plan {
                let cap = (step["capability"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard Self.runtimeCapabilities.contains(cap) else { continue }
                let assigned = (step["assigned_edge_id"] as? String ?? "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                guard assigned == eid else {
                    NSLog(
                        "[IntentClient] skip %@ step=%@ assigned=%@ self=%@",
                        cap,
                        stringId(step["step"]),
                        assigned.isEmpty ? "(empty)" : assigned,
                        eid
                    )
                    continue
                }
                let st = intStatus(step["status"])
                if st == 2 || st == 3 { continue }
                let num = intStatus(step["step"])
                guard num > 0 else { continue }
                guard predecessorsAllSucceeded(plan, stepNum: num) else {
                    NSLog(
                        "[IntentClient] skip %@ step=%d waiting for predecessors",
                        cap,
                        num
                    )
                    continue
                }
                jobs.append(
                    RuntimeStepJob(
                        intentId: iid,
                        step: num,
                        capability: cap,
                        params: Self.hydrateParams(
                            Self.stepParams(step),
                            intent: item,
                            step: num
                        )
                    )
                )
            }
        }
        return jobs
    }

    private static func stepParams(_ step: [String: Any]) -> [String: Any] {
        var out: [String: Any] = [:]
        if let params = step["params"] as? [String: Any] {
            out.merge(params) { _, new in new }
        }
        if let constrict = step["input_constrict"] as? [String: Any] {
            for (k, v) in constrict {
                out[k] = unwrapConstrictValue(v)
            }
        }
        return out
    }

    private static func unwrapConstrictValue(_ v: Any) -> Any {
        if let d = v as? [String: Any], d["value"] != nil {
            return d["value"] as Any
        }
        return v
    }

    /// True iff every plan step < N has Brain `status=2`. Same gate as Mac / Android.
    private func predecessorsAllSucceeded(_ plan: [[String: Any]], stepNum: Int) -> Bool {
        for step in plan {
            let n = intStatus(step["step"])
            if n <= 0 || n >= stepNum { continue }
            if intStatus(step["status"]) != 2 { return false }
        }
        return true
    }

    /// Replace `$name` / `${name}` from `ctx_param` and predecessor `step_outputs`.
    static func hydrateParams(
        _ params: [String: Any],
        intent: [String: Any],
        step: Int
    ) -> [String: Any] {
        var ctx: [String: String] = [:]
        mergeContext(&ctx, intent["ctx_param"])
        if let bags = intent["step_outputs"] as? [String: Any] {
            for (key, bag) in bags {
                let n = Int(key.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
                guard n > 0, n < step else { continue }
                mergeContext(&ctx, bag)
            }
        }
        if let plan = intent["execution_plan"] as? [[String: Any]] {
            for row in plan {
                let n: Int = {
                    if let i = row["step"] as? Int { return i }
                    if let num = row["step"] as? NSNumber { return num.intValue }
                    if let s = row["step"] as? String { return Int(s) ?? 0 }
                    return 0
                }()
                guard n > 0, n < step else { continue }
                let st: Int = {
                    if let i = row["status"] as? Int { return i }
                    if let num = row["status"] as? NSNumber { return num.intValue }
                    if let s = row["status"] as? String { return Int(s) ?? 0 }
                    return 0
                }()
                guard st == 2 else { continue }
                mergeContext(&ctx, row["outputs"])
            }
        }
        return resolveParams(params, context: ctx)
    }

    static func hydrateParams(
        _ params: [String: Any],
        snapshot: IntentJobSnapshot,
        step: Int
    ) -> [String: Any] {
        var ctx: [String: String] = [:]
        for row in snapshot.planSteps where row.step < step && row.runStatus == .succeeded {
            for (k, v) in row.realizedOutputs where !v.hasPrefix("$") {
                ctx[k] = v
            }
        }
        return resolveParams(params, context: ctx)
    }

    static func hasUnresolvedVars(_ params: [String: Any]) -> Bool {
        params.values.contains { value in
            unresolvedVarName(in: contextText(value) ?? "") != nil
        }
    }

    private static func mergeContext(_ ctx: inout [String: String], _ raw: Any?) {
        guard let dict = raw as? [String: Any] else { return }
        for (k, v) in dict {
            let key = k.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !key.isEmpty, let text = contextText(v), !text.hasPrefix("$") else { continue }
            ctx[key] = text
        }
    }

    private static func contextText(_ raw: Any?) -> String? {
        guard let raw else { return nil }
        if let s = raw as? String {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        if JSONSerialization.isValidJSONObject(raw),
           let data = try? JSONSerialization.data(withJSONObject: raw),
           let s = String(data: data, encoding: .utf8) {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty ? nil : t
        }
        let t = String(describing: raw).trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    private static let inlineVarRegex: NSRegularExpression = {
        try! NSRegularExpression(
            pattern: #"\$\{([A-Za-z_][A-Za-z0-9_.]*)\}|\$([A-Za-z_][A-Za-z0-9_.]*)"#
        )
    }()

    private static func resolveParams(
        _ params: [String: Any],
        context: [String: String]
    ) -> [String: Any] {
        guard !context.isEmpty else { return params }
        var out: [String: Any] = [:]
        for (k, v) in params {
            if let s = v as? String {
                out[k] = resolveString(s, context: context)
            } else {
                out[k] = v
            }
        }
        return out
    }

    private static func resolveString(_ raw: String, context: [String: String]) -> String {
        let ns = raw as NSString
        let full = NSRange(location: 0, length: ns.length)
        var result = ""
        var last = 0
        inlineVarRegex.enumerateMatches(in: raw, options: [], range: full) { match, _, _ in
            guard let match else { return }
            result += ns.substring(
                with: NSRange(location: last, length: match.range.location - last)
            )
            let nameRange = match.range(at: 1).location != NSNotFound
                ? match.range(at: 1)
                : match.range(at: 2)
            let name = ns.substring(with: nameRange)
            if let resolved = lookupContext(name, context: context) {
                result += resolved
            } else {
                result += ns.substring(with: match.range)
            }
            last = match.range.location + match.range.length
        }
        result += ns.substring(from: last)
        return result
    }

    private static func lookupContext(_ name: String, context: [String: String]) -> String? {
        let key = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if let exact = context[key], !exact.isEmpty { return exact }
        guard let dot = key.firstIndex(of: ".") else { return nil }
        let root = String(key[..<dot])
        let rest = String(key[key.index(after: dot)...]).split(separator: ".").map(String.init)
        guard let rootText = context[root],
              let data = rootText.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data)
        else { return nil }
        var cur: Any = obj
        for part in rest {
            if let dict = cur as? [String: Any] {
                if let next = dict[part] {
                    cur = next
                } else {
                    return nil
                }
            } else if let arr = cur as? [Any], let idx = Int(part), idx >= 0, idx < arr.count {
                cur = arr[idx]
            } else {
                return nil
            }
        }
        return contextText(cur)
    }

    private static func unresolvedVarName(in value: String) -> String? {
        let ns = value as NSString
        let full = NSRange(location: 0, length: ns.length)
        guard let match = inlineVarRegex.firstMatch(in: value, options: [], range: full) else {
            return nil
        }
        let nameRange = match.range(at: 1).location != NSNotFound
            ? match.range(at: 1)
            : match.range(at: 2)
        let name = ns.substring(with: nameRange)
        return name.isEmpty ? nil : name
    }

    /// Peek queue rows for this edge (non-terminal jobs included).
    func peekLivingRoomIntents(edgeId: String, intentURL: String) async -> [[String: Any]] {
        let eid = edgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !eid.isEmpty, let url = Self.runtimeIntentsURL(fromIntentURL: intentURL, edgeId: eid) else {
            return []
        }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20
        do {
            let timed = try await TimedHTTP.data(for: request, label: "runtime-intents")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
                  let obj = try JSONSerialization.jsonObject(with: timed.data) as? [String: Any]
            else { return [] }
            return (obj["intents"] as? [[String: Any]])
                ?? (obj["commands"] as? [[String: Any]])
                ?? []
        } catch {
            NSLog("[IntentClient] peekLivingRoomIntents failed: %@", error.localizedDescription)
            return []
        }
    }

    func postStepStatus(
        intentId: String,
        step: Int,
        status: Int,
        edgeId: String,
        outputs: [String: Any]?,
        msg: String?,
        intentURL: String
    ) async -> Bool {
        guard let url = Self.stepStatusURL(fromIntentURL: intentURL, intentId: intentId, step: step) else {
            return false
        }
        var body: [String: Any] = [
            "step_status": String(status),
            "status": String(status),
            "edge_node_id": edgeId,
            "ts": Int64(Date().timeIntervalSince1970 * 1000),
        ]
        if let outputs { body["outputs"] = outputs }
        if let msg, !msg.isEmpty { body["msg"] = msg }
        return await postJSON(url, body: body, label: "step-status")
    }

    func postIntentStatus(
        intentId: String,
        status: String,
        edgeId: String,
        message: String,
        intentURL: String
    ) async -> Bool {
        guard let url = Self.intentStatusURL(fromIntentURL: intentURL, intentId: intentId) else {
            return false
        }
        var body: [String: Any] = [
            "intent_id": intentId,
            "intent_status": status,
            "status": status,
            "edge_node_id": edgeId,
        ]
        if !message.isEmpty {
            body["message"] = message
            body["msg"] = message
        }
        return await postJSON(url, body: body, label: "intent-status")
    }

    func registerAsset(
        intentURL: String,
        intentId: String,
        key: String,
        publicBase: String
    ) async throws -> String {
        guard let url = Self.assetsURL(fromIntentURL: intentURL) else {
            throw NSError(domain: "IntentClient", code: 1, userInfo: [NSLocalizedDescriptionKey: "assets URL invalid"])
        }
        let pid = ParticipantStore.participantId
        let body: [String: Any] = [
            "type": "image",
            "mime_type": "image/jpeg",
            "intent_id": intentId,
            "execution_id": intentId,
            "producer": "camera.capture",
            "edge_id": pid,
            "storage": [
                "backend": "img_server",
                "key": key,
                "public_base": publicBase,
                "edge_id": pid,
            ],
        ]
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 20
        let timed = try await TimedHTTP.data(for: request, label: "asset-register")
        guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
              let obj = try JSONSerialization.jsonObject(with: timed.data) as? [String: Any]
        else {
            throw NSError(domain: "IntentClient", code: 2, userInfo: [NSLocalizedDescriptionKey: "register asset failed"])
        }
        let aid = (obj["asset_id"] as? String)
            ?? ((obj["asset"] as? [String: Any])?["asset_id"] as? String)
            ?? ""
        let trimmed = aid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw NSError(domain: "IntentClient", code: 3, userInfo: [NSLocalizedDescriptionKey: "register asset missing asset_id"])
        }
        return trimmed
    }

    private func postJSON(_ url: URL, body: [String: Any], label: String) async -> Bool {
        guard let data = try? JSONSerialization.data(withJSONObject: body) else { return false }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = data
        request.timeoutInterval = 20
        do {
            let timed = try await TimedHTTP.data(for: request, label: label)
            return timed.http.map { (200 ..< 300).contains($0.statusCode) } ?? false
        } catch {
            NSLog("[IntentClient] %@ failed: %@", label, error.localizedDescription)
            return false
        }
    }

    private func stringId(_ raw: Any?) -> String {
        if let s = raw as? String { return s.trimmingCharacters(in: .whitespacesAndNewlines) }
        if let i = raw as? Int { return String(i) }
        if let n = raw as? NSNumber { return n.stringValue }
        return ""
    }

    private func intStatus(_ raw: Any?) -> Int {
        if let i = raw as? Int { return i }
        if let n = raw as? NSNumber { return n.intValue }
        if let s = raw as? String { return Int(s.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0 }
        return 0
    }

    static func runtimeIntentsURL(fromIntentURL intentURL: String, edgeId: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "devices/living-room/intents"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "devices/living-room/intents"
        } else {
            path = "/api/v1/devices/living-room/intents"
        }
        components.path = path
        components.queryItems = [
            URLQueryItem(name: "edge_id", value: edgeId),
            URLQueryItem(name: "peek", value: "1"),
        ]
        return components.url
    }

    static func stepStatusURL(fromIntentURL intentURL: String, intentId: String, step: Int) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        let suffix = "intent/\(intentId)/step/\(step)/status"
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + suffix
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + suffix
        } else {
            path = "/api/v1/\(suffix)"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func intentStatusURL(fromIntentURL intentURL: String, intentId: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        let suffix = "intent/\(intentId)/status"
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + suffix
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + suffix
        } else {
            path = "/api/v1/\(suffix)"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func assetsURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "assets"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "assets"
        } else {
            path = "/api/v1/assets"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    /// `…/api/v1/intent` → `…/api/v1/assets/upload` (multipart + upload_intent).
    static func assetsUploadURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "assets/upload"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "assets/upload"
        } else {
            path = "/api/v1/assets/upload"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    /// `…/api/v1/intent` → `…/api/v1/assets/register` (JSON, url 资产注册)
    static func assetsRegisterURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "assets/register"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "assets/register"
        } else {
            path = "/api/v1/assets/register"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func feedbackURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "intent_feedback"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "intent_feedback"
        } else {
            path = "/api/v1/intent_feedback"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func debugReportURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "debug/report"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "debug/report"
        } else {
            path = "/api/v1/debug/report"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    struct DebugReportResult {
        let ok: Bool
        let issueId: Int?
        let message: String
        let error: String
    }

    func submitDebugReport(
        intentId: String,
        participantId: String,
        intentURL: String,
        clientSnapshot: [String: Any]? = nil,
        userSummary: String = "",
        problemType: String = "",
        attachmentAssetIds: [String] = [],
        attachments: [FeedbackAttachment] = []
    ) async -> DebugReportResult {
        let iid = Int(intentId.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard iid > 0 else {
            return DebugReportResult(ok: false, issueId: nil, message: "", error: "invalid intent_id")
        }
        guard !pid.isEmpty else {
            return DebugReportResult(ok: false, issueId: nil, message: "", error: "participant_id is required")
        }
        guard let url = Self.debugReportURL(fromIntentURL: intentURL) else {
            return DebugReportResult(ok: false, issueId: nil, message: "", error: "无法拼出 debug/report URL")
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
        let ptype = problemType.trimmingCharacters(in: .whitespacesAndNewlines)
        if !ptype.isEmpty {
            payload["problem_type"] = ptype
        }
        if let clientSnapshot, !clientSnapshot.isEmpty {
            payload["client_snapshot"] = clientSnapshot
        }
        if !attachments.isEmpty {
            payload["attachments"] = attachments.map { $0.apiPayload() }
        } else {
            let legacyIds = attachmentAssetIds
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
            if !legacyIds.isEmpty {
                payload["attachments"] = legacyIds.map {
                    FeedbackAttachment(assetId: $0, kind: .image, mimeType: "image/jpeg", filename: "").apiPayload()
                }
            }
        }
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return DebugReportResult(ok: false, issueId: nil, message: "", error: "encode JSON failed")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 20
        do {
            let timed = try await TimedHTTP.data(for: request, label: "debug_report")
            guard let http = timed.http else {
                return DebugReportResult(ok: false, issueId: nil, message: "", error: "无 HTTP 响应")
            }
            let raw = String(data: timed.data, encoding: .utf8) ?? ""
            guard let obj = try? JSONSerialization.jsonObject(with: timed.data) as? [String: Any] else {
                return DebugReportResult(
                    ok: false,
                    issueId: nil,
                    message: "",
                    error: raw.isEmpty ? "返回格式不对" : String(raw.prefix(200))
                )
            }
            if !(200 ..< 300).contains(http.statusCode) || obj["ok"] as? Bool != true {
                let err = (obj["error"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
                return DebugReportResult(
                    ok: false,
                    issueId: nil,
                    message: "",
                    error: err?.isEmpty == false ? err! : String(raw.prefix(200))
                )
            }
            let issueId = obj["issue_id"] as? Int
            let message = (obj["message"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            return DebugReportResult(
                ok: true,
                issueId: issueId,
                message: message?.isEmpty == false ? message! : "已提交反馈，正在分析。",
                error: ""
            )
        } catch {
            return DebugReportResult(ok: false, issueId: nil, message: "", error: error.localizedDescription)
        }
    }

    func fetchIntentFeedback(
        intentId: String,
        participantId: String,
        intentURL: String
    ) async -> IntentUserFeedback? {
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !iid.isEmpty, !pid.isEmpty,
              let base = Self.feedbackURL(fromIntentURL: intentURL),
              var components = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            return nil
        }
        components.queryItems = [
            URLQueryItem(name: "intent_id", value: iid),
            URLQueryItem(name: "participant_id", value: pid),
        ]
        guard let url = components.url else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent_feedback_get")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
                  let obj = try? JSONSerialization.jsonObject(with: timed.data) as? [String: Any],
                  obj["ok"] as? Bool == true else {
                return nil
            }
            guard let row = obj["feedback"] as? [String: Any] else {
                return IntentUserFeedback()
            }
            return Self.parseFeedbackRow(row)
        } catch {
            return nil
        }
    }

    func submitIntentFeedback(
        intentId: String,
        participantId: String,
        understanding: IntentUnderstandingFeedback,
        responseSpeed: IntentSpeedFeedback,
        intentURL: String
    ) async -> Bool {
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !iid.isEmpty, !pid.isEmpty,
              let url = Self.feedbackURL(fromIntentURL: intentURL) else {
            return false
        }
        let payload: [String: Any] = [
            "intent_id": iid,
            "participant_id": pid,
            "edge_id": pid,
            "understanding": understanding.rawValue,
            "response_speed": responseSpeed.rawValue,
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return false }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 15
        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent_feedback_post")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode),
                  let obj = try? JSONSerialization.jsonObject(with: timed.data) as? [String: Any],
                  obj["ok"] as? Bool == true else {
                return false
            }
            return true
        } catch {
            return false
        }
    }

    private static func parseFeedbackRow(_ row: [String: Any]) -> IntentUserFeedback {
        var fb = IntentUserFeedback()
        if let raw = row["understanding"] as? String,
           let val = IntentUnderstandingFeedback(rawValue: raw) {
            fb.understanding = val
        }
        if let raw = row["response_speed"] as? String,
           let val = IntentSpeedFeedback(rawValue: raw) {
            fb.responseSpeed = val
        }
        return fb
    }
}
