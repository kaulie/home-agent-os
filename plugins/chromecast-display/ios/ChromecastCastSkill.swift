import Foundation

/// Wire service chromecast.display — iPhone Cast Sender for display.photo.
final class ChromecastCastSkill: Skill {
    static let skillId = "chromecast.display"

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.2.0",
            displayName: "Chromecast Cast",
            group: "display",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: Capabilities.displayPhoto,
                    description: "将 photo_url 经 Cast 投到 Chromecast",
                    inputSchema: [
                        "photo_url": SchemaField(
                            type: "string",
                            required: true,
                            description: "服务器图片下载地址（Chromecast 可访问）"
                        ),
                    ]
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        switch capabilityId {
        case Capabilities.displayPhoto:
            let url = params["photo_url"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !url.isEmpty else {
                return .error("display.photo requires photo_url")
            }
            // CastSessionController is @MainActor; await hops here even from Task.detached.
            let result = await cast.castPhoto(urlString: url)
            if result.ok {
                return .ok(result.message, outputs: ["photo_url": url])
            }
            return .error(result.message)
        default:
            return .error("unsupported capability: \(capabilityId)")
        }
    }
}
