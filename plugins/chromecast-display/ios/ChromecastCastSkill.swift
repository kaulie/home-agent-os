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
                    description: "能：把本步 image_ref（AssetRef）经 Cast 投到 Chromecast。仅用户明确要投电视时用。不能：拍照、自己捡图、收 photo_url、TTS。",
                    inputSchema: [
                        "image_ref": SchemaField(
                            type: "string",
                            required: true,
                            description: "AssetRef JSON {asset_id, type}。禁止 photo_url。"
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
                return .ok(result.message)
            }
            return .error(result.message)
        default:
            return .error("unsupported capability: \(capabilityId)")
        }
    }
}
