import Foundation

/// Edge plugin that installs ChromecastCastSkill (service chromecast.display / group display).
final class ChromecastDisplayCapabilityPlugin: CapabilityPlugin {
    let capabilityId = ChromecastCastSkill.skillId
    let description = "Cast 照片到 Chromecast"
    let version = "0.2.0"

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func makeSkills() -> [Skill] {
        [ChromecastCastSkill(cast: cast)]
    }
}

/// Plugin entry (manifest `entry.ios`).
final class ChromecastPluginEntry {
    static let skillId = ChromecastCastSkill.skillId

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func makeCapabilityPlugin() -> CapabilityPlugin {
        ChromecastDisplayCapabilityPlugin(cast: cast)
    }

    func castPhoto(urlString: String) async -> ControllerResult {
        await cast.castPhoto(urlString: urlString)
    }
}
