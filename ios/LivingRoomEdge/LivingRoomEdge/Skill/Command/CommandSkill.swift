import Foundation

final class CommandSkill: Skill {
    static let skillId = "commands.pull"

    private let controller: CommandController

    init(controller: CommandController) {
        self.controller = controller
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.1.0",
            displayName: "Command Pull",
            group: "system",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: Capabilities.commandsPull,
                    description: Capabilities.describe(Capabilities.commandsPull),
                    inputSchema: [
                        "server_url": SchemaField(
                            type: "string",
                            required: true,
                            description: "Commands pull URL"
                        ),
                    ]
                ),
                CapabilityDescriptor(
                    capabilityId: Capabilities.commandsExecute,
                    description: Capabilities.describe(Capabilities.commandsExecute),
                    inputSchema: [
                        "commands_json": SchemaField(
                            type: "string",
                            required: true,
                            description: "Pulled commands JSON"
                        ),
                    ]
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        switch capabilityId {
        case Capabilities.commandsPull, "pull":
            let server = params["server_url"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !server.isEmpty else {
                return .error("server_url is required")
            }
            let result = await controller.pullCommands(serverURL: server)
            return result.ok ? .ok(result.message) : .error(result.message)
        case Capabilities.commandsExecute, "execute":
            let json = params["commands_json"] ?? ""
            let result = await controller.executeCommands(jsonText: json)
            return result.ok ? .ok(result.message) : .error(result.message)
        default:
            return .error("unsupported capability: \(capabilityId)")
        }
    }
}
