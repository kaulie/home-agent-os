import Foundation

final class IntentSkill: Skill {
    static let skillId = "intent.dispatch"

    private let controller: IntentController

    init(controller: IntentController) {
        self.controller = controller
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.1.0",
            displayName: "Intent Dispatch",
            group: "system",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: Capabilities.intentDispatch,
                    description: Capabilities.describe(Capabilities.intentDispatch),
                    inputSchema: [
                        "text": SchemaField(type: "string", required: true, description: "Command text"),
                        "source": SchemaField(type: "string", required: false, description: "Source (text|voice)"),
                        "server_url": SchemaField(type: "string", required: true, description: "Intent server URL"),
                    ]
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        switch capabilityId {
        case Capabilities.intentDispatch, "dispatch":
            let text = params["text"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !text.isEmpty else {
                return .error("text is required")
            }
            let server = params["server_url"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !server.isEmpty else {
                return .error("server_url is required")
            }
            let source = params["source"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "text"
            let result = await controller.dispatch(
                text: text,
                source: source,
                serverURL: server,
                edgeId: context.edgeId
            )
            return result.ok ? .ok(result.message) : .error(result.message)
        default:
            return .error("unsupported capability: \(capabilityId)")
        }
    }
}
