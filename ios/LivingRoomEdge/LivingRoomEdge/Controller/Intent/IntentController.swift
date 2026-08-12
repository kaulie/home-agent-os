import Foundation

/// Intent API client (production contract):
/// - POST `/api/v1/intent` → `{ intent_id, intent_status, … }`
/// - GET  `/api/v1/intent_detail?intent_id=` → `{ id, status, execution_plan }`
/// - POST status updates use `intent_id` + `intent_status`
final class IntentController: DeviceController {
    let controllerId = "intent"
    let displayName = "Intent Dispatch"

    /// POST `/api/v1/intent` base (also used to derive `intent_detail` URL).
    var lastServerURL: String = AppModel.defaultIntentURL

    weak var journeyStore: IntentJourneyStore?

    func dispatch(
        text: String,
        source: String,
        serverURL: String,
        edgeId: String
    ) async -> ControllerResult {
        let trimmedText = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedText.isEmpty else {
            return .failure("text is empty")
        }
        let trimmedURL = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmedURL), !trimmedURL.isEmpty else {
            return .failure("invalid server_url")
        }

        let src = (source == "voice") ? "voice" : "text"
        let payload: [String: String] = [
            "text": trimmedText,
            "source": src,
            "edge_id": edgeId,
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else {
            return .failure("encode JSON failed")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 60

        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent")
            guard let http = timed.http else {
                return .failure("invalid intent response · \(timed.durationLabel)")
            }
            let textBody = String(data: timed.data, encoding: .utf8) ?? ""
            let withTime: (String) -> String = { "\($0)\n⏱ \(timed.durationLabel)" }
            if (200 ..< 300).contains(http.statusCode) {
                lastServerURL = trimmedURL
                if let snapshot = IntentJobSnapshot.parse(data: timed.data) {
                    let store = journeyStore
                    await MainActor.run {
                        let target = store ?? AppModel.shared.intentJourney
                        target.startFromPost(snapshot)
                        target.startPolling(jobId: snapshot.jobId) { [weak self] jobId in
                            guard let self else { return nil }
                            return await self.fetchIntentDetail(intentId: jobId, intentURL: trimmedURL)
                        }
                    }
                } else if IntentJobSnapshot.isSuccessWithoutIntentId(textBody) {
                    await MainActor.run {
                        let target = journeyStore ?? AppModel.shared.intentJourney
                        target.markLegacyServerMissingJob(detail: "服务端未返回 intent_id。")
                    }
                }
                return .success(withTime(textBody.isEmpty ? "intent ok HTTP \(http.statusCode)" : textBody))
            }
            return .failure(withTime("intent HTTP \(http.statusCode): \(textBody.prefix(200))"))
        } catch let timed as TimedHTTP.Failure {
            return intentFailure(timed.nsError, duration: timed.durationLabel)
        } catch {
            return intentFailure(error as NSError, duration: nil)
        }
    }

    /// GET `/api/v1/intent_detail?intent_id=`
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
            NSLog("[IntentController] fetchIntentDetail failed: %@", error.localizedDescription)
            return nil
        }
    }

    /// Compatibility alias used by AppModel / journey polling.
    func fetchJob(jobId: String, intentURL: String? = nil) async -> IntentJobSnapshot? {
        await fetchIntentDetail(intentId: jobId, intentURL: intentURL)
    }

    /// Report pipeline status with `{ intent_id, intent_status, … }`.
    /// On HTTP success, always refresh UI from `intent_detail` (backend is source of truth).
    @discardableResult
    func reportJobStatus(
        jobId: String,
        status: String,
        edgeNodeId: String? = nil,
        message: String? = nil,
        outputs: [String: String]? = nil,
        intentURL: String? = nil
    ) async -> Bool {
        let trimmedId = jobId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedId.isEmpty else { return false }
        let base = (intentURL ?? lastServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        let wireStatus = IntentPhase.fromWire(status)?.wireValue ?? status

        var payload: [String: Any] = [
            "intent_status": wireStatus,
            "status": wireStatus,
        ]
        if let asInt = Int(trimmedId) {
            payload["intent_id"] = asInt
        } else {
            payload["intent_id"] = trimmedId
        }
        if let edgeNodeId, !edgeNodeId.isEmpty {
            payload["edge_node_id"] = edgeNodeId
        }
        if let message, !message.isEmpty {
            payload["message"] = message
        }
        if let outputs, !outputs.isEmpty {
            payload["outputs"] = outputs
            payload["ctx_param"] = outputs
        }
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return false }

        guard let url = Self.statusPOSTCandidates(intentURL: base, intentId: trimmedId).first else {
            return false
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 30
        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent-status")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode) else {
                NSLog("[IntentController] reportJobStatus failed intent_id=%@ status=%@", trimmedId, wireStatus)
                return false
            }
            await refreshJourneyFromDetail(intentId: trimmedId, intentURL: base)
            return true
        } catch {
            NSLog("[IntentController] reportJobStatus failed intent_id=%@ status=%@", trimmedId, wireStatus)
            return false
        }
    }

    /// POST status then refresh from detail (Handler/Runtime entry).
    @discardableResult
    func reportAndRefresh(
        intentId: String,
        status: String,
        edgeNodeId: String? = nil,
        message: String? = nil,
        outputs: [String: String]? = nil,
        intentURL: String? = nil
    ) async -> Bool {
        await reportJobStatus(
            jobId: intentId,
            status: status,
            edgeNodeId: edgeNodeId,
            message: message,
            outputs: outputs,
            intentURL: intentURL
        )
    }

    /// POST `/api/v1/intent/<id>/step/<step>/status` with `{ step_status, edge_node_id, ts [, outputs] }`.
    @discardableResult
    func reportStepStatus(
        intentId: String,
        stepId: Int,
        stepStatus: Int,
        edgeNodeId: String,
        intentURL: String? = nil,
        tsMs: Int64? = nil,
        outputs: [String: String]? = nil
    ) async -> Bool {
        let trimmedId = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        let eid = edgeNodeId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedId.isEmpty, stepId > 0, !eid.isEmpty else { return false }
        let base = (intentURL ?? lastServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = Self.stepStatusURL(fromIntentURL: base, intentId: trimmedId, stepId: stepId) else {
            return false
        }
        let ts = tsMs ?? Int64(Date().timeIntervalSince1970 * 1000)
        var payload: [String: Any] = [
            "step_status": stepStatus,
            "edge_node_id": eid,
            "ts": ts,
        ]
        if let outputs, !outputs.isEmpty {
            // Skill outputs only — Brain registers into ctx_param via output_constrict.
            payload["outputs"] = outputs
        }
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return false }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 30
        do {
            let timed = try await TimedHTTP.data(for: request, label: "step-status")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode) else {
                let text = String(data: timed.data, encoding: .utf8) ?? ""
                NSLog(
                    "[IntentController] reportStepStatus failed intent=%@ step=%d status=%d http=%@ body=%@",
                    trimmedId,
                    stepId,
                    stepStatus,
                    String(timed.http?.statusCode ?? -1),
                    String(text.prefix(160))
                )
                return false
            }
            await refreshJourneyFromDetail(intentId: trimmedId, intentURL: base)
            return true
        } catch {
            NSLog(
                "[IntentController] reportStepStatus error intent=%@ step=%d: %@",
                trimmedId,
                stepId,
                error.localizedDescription
            )
            return false
        }
    }

    /// Re-POST the intent onto the living-room pull queue so the next Edge (e.g. Mac)
    /// can peek it after a prior consume emptied the queue. Best-effort; Brain upserts by id.
    @discardableResult
    func requeueIntentForPull(
        intentId: String,
        status: String,
        executionPlan: [[String: Any]],
        ctxParam: [String: String]? = nil,
        schedulerNode: String? = nil,
        intentURL: String? = nil
    ) async -> Bool {
        let trimmedId = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedId.isEmpty, !executionPlan.isEmpty else { return false }
        let base = (intentURL ?? lastServerURL).trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = Self.livingRoomIntentsURL(fromIntentURL: base) else { return false }
        var payload: [String: Any] = [
            "id": Int(trimmedId) ?? trimmedId,
            "status": status,
            "intent_status": status,
            "execution_plan": executionPlan,
            "skip_routing": true,
        ]
        if let schedulerNode, !schedulerNode.isEmpty {
            payload["scheduler_node"] = schedulerNode
        }
        if let ctxParam, !ctxParam.isEmpty {
            payload["ctx_param"] = ctxParam
        }
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return false }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 30
        do {
            let timed = try await TimedHTTP.data(for: request, label: "intent-requeue")
            guard let http = timed.http, (200 ..< 300).contains(http.statusCode) else {
                let text = String(data: timed.data, encoding: .utf8) ?? ""
                NSLog(
                    "[IntentController] requeueIntentForPull failed intent=%@ http=%@ body=%@",
                    trimmedId,
                    String(timed.http?.statusCode ?? -1),
                    String(text.prefix(160))
                )
                return false
            }
            NSLog("[IntentController] requeueIntentForPull ok intent=%@", trimmedId)
            return true
        } catch {
            NSLog(
                "[IntentController] requeueIntentForPull error intent=%@: %@",
                trimmedId,
                error.localizedDescription
            )
            return false
        }
    }

    /// `…/api/v1/intent` → `…/api/v1/devices/living-room/intents`
    static func livingRoomIntentsURL(fromIntentURL intentURL: String) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "devices/living-room/intents"
        } else {
            path = "/api/v1/devices/living-room/intents"
        }
        components.path = path
        components.queryItems = nil
        return components.url
    }

    /// `…/api/v1/intent` → `…/api/v1/intent/<id>/step/<step>/status`
    static func stepStatusURL(fromIntentURL intentURL: String, intentId: String, stepId: Int) -> URL? {
        guard var components = URLComponents(string: intentURL) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "intent/\(intentId)/step/\(stepId)/status"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "intent/\(intentId)/step/\(stepId)/status"
        } else {
            path = "/api/v1/intent/\(intentId)/step/\(stepId)/status"
        }
        components.path = path
        components.queryItems = nil
        return components.url
    }

    private func refreshJourneyFromDetail(intentId: String, intentURL: String) async {
        guard let snap = await fetchIntentDetail(intentId: intentId, intentURL: intentURL) else {
            NSLog("[IntentController] detail refresh failed after status report intent_id=%@", intentId)
            return
        }
        await MainActor.run {
            (journeyStore ?? AppModel.shared.intentJourney).applyServerJob(snap)
        }
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

    static func statusPOSTCandidates(intentURL: String, intentId: String) -> [URL] {
        let root = intentURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return [
            URL(string: "\(root)/\(intentId)/status"),
        ].compactMap { $0 }
    }

    private func intentFailure(_ ns: NSError, duration: String?) -> ControllerResult {
        let suffix = duration.map { "\n⏱ \($0)" } ?? ""
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNetworkConnectionLost {
            return .failure("intent failed: network connection was lost — 确认已离开 GoPro Wi‑Fi\(suffix)")
        }
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNotConnectedToInternet {
            return .failure("intent failed: no internet\(suffix)")
        }
        return .failure("intent failed: \(ns.localizedDescription)\(suffix)")
    }
}
