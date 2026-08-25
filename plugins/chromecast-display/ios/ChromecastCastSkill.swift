import Foundation

/// Wire service chromecast.display — iPhone Cast Sender for display.photo / slideshow.
/// Cast Presentation Protocol V1: docs/chromecast-cast-protocol.md
final class ChromecastCastSkill: Skill {
    static let skillId = "chromecast.display"

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.5.0",
            displayName: "Chromecast Cast",
            group: "display",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: "display.photo",
                    description: "能：把本步 asset_ref（AssetRef）经 Cast Presentation Command 投到 Chromecast（F7649303）。仅用户明确要投电视时用。不能：拍照、自己捡图、收永久 URL、TTS。accepted≠已显示；等 Receiver presentation.started。",
                    inputSchema: [
                        "asset_ref": SchemaField(
                            type: "string",
                            required: true,
                            description: "AssetRef JSON {asset_id, type}。禁止 photo_url 作为 identity。"
                        ),
                    ]
                ),
                CapabilityDescriptor(
                    capabilityId: "display.slideshow",
                    description: "能：把本步必填 asset_refs 轮播投到电视（多次 present）。不能：从前序自己拼列表、空数组。",
                    inputSchema: [
                        "asset_refs": SchemaField(
                            type: "string",
                            required: true,
                            description: "AssetRef JSON 数组。"
                        ),
                        "interval_sec": SchemaField(
                            type: "string",
                            required: false,
                            description: "帧间隔秒，默认 5。"
                        ),
                    ]
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        switch capabilityId {
        case "display.photo", Capabilities.displayPhoto:
            // Runtime may hydrate temporary LAN URL into photo_url for Cast transport.
            let url = params["photo_url"]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !url.isEmpty else {
                return .error("display.photo requires resolved photo_url (from asset_ref)")
            }
            let assetId = Self.assetId(from: params["asset_ref"])
            let result = await cast.castPhoto(urlString: url, assetId: assetId)
            if result.ok {
                return .ok(result.message)
            }
            return .error(result.message)
        case "display.slideshow":
            let urls = Self.photoURLs(from: params)
            guard !urls.isEmpty else {
                return .error("display.slideshow requires resolved photo URLs from asset_refs")
            }
            let interval = Double(params["interval_sec"] ?? "") ?? 5
            let result = await cast.castSlideshow(urlStrings: urls, intervalSec: interval)
            if result.ok {
                return .ok(result.message)
            }
            return .error(result.message)
        default:
            return .error("unsupported capability: \(capabilityId)")
        }
    }

    private static func assetId(from raw: String?) -> String? {
        guard let raw = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !raw.isEmpty,
              let data = raw.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let id = obj["asset_id"] as? String,
              !id.isEmpty else {
            return nil
        }
        return id
    }

    private static func photoURLs(from params: [String: String]) -> [String] {
        if let raw = params["photo_urls"]?.trimmingCharacters(in: .whitespacesAndNewlines),
           let data = raw.data(using: .utf8),
           let arr = try? JSONSerialization.jsonObject(with: data) as? [Any] {
            return arr.compactMap { ($0 as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
        }
        if let single = params["photo_url"]?.trimmingCharacters(in: .whitespacesAndNewlines), !single.isEmpty {
            return [single]
        }
        return []
    }
}
