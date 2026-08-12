import Foundation

/// Debug helper: POST selected services to a registration URL.
final class CapabilityRegisterController: DeviceController {
    let controllerId = "capability.register"
    let displayName = "Capability Register"

    /// POST JSON `{ edge_id, services, registered_at }` to `serverURL`.
    func register(
        serverURL: String,
        edgeId: String,
        services: [ServiceDescriptor]
    ) async -> ControllerResult {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), !trimmed.isEmpty else {
            return .failure("invalid server_url")
        }
        guard !services.isEmpty else {
            return .failure("请至少勾选一个 service")
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let payload = RegisterPayload(
            edgeId: edgeId,
            services: services,
            registeredAt: Date().timeIntervalSince1970
        )
        guard let body = try? encoder.encode(payload) else {
            return .failure("encode JSON failed")
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 30

        do {
            let timed = try await TimedHTTP.data(for: request, label: "capability-register")
            guard let http = timed.http else {
                return .failure("invalid response · \(timed.durationLabel)")
            }
            let text = String(data: timed.data, encoding: .utf8) ?? ""
            let withTime: (String) -> String = { "\($0)\n⏱ \(timed.durationLabel)" }
            if (200 ..< 300).contains(http.statusCode) {
                return .success(withTime(text.isEmpty ? "register ok HTTP \(http.statusCode)" : text), data: body)
            }
            return .failure(withTime("register HTTP \(http.statusCode): \(text.prefix(300))"))
        } catch let timed as TimedHTTP.Failure {
            return registerFailure(timed.nsError, duration: timed.durationLabel)
        } catch {
            return registerFailure(error as NSError, duration: nil)
        }
    }

    private struct RegisterPayload: Encodable {
        let edgeId: String
        let services: [ServiceDescriptor]
        let registeredAt: TimeInterval

        enum CodingKeys: String, CodingKey {
            case edgeId = "edge_id"
            case services
            case registeredAt = "registered_at"
        }
    }

    private func registerFailure(_ ns: NSError, duration: String?) -> ControllerResult {
        let suffix = duration.map { "\n⏱ \($0)" } ?? ""
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNetworkConnectionLost {
            return .failure("capability register failed: network connection was lost\(suffix)")
        }
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNotConnectedToInternet {
            return .failure("capability register failed: no internet\(suffix)")
        }
        return .failure("capability register failed: \(ns.localizedDescription)\(suffix)")
    }
}
