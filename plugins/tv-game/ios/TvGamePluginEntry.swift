import Foundation

final class TvGameCapabilityPlugin: CapabilityPlugin {
    let capabilityId = TvGameCastSkill.skillId
    let description = "TV Game Cast"
    let version = "0.1.0"

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func makeSkills() -> [Skill] {
        [TvGameCastSkill(cast: cast)]
    }
}

final class TvGamePluginEntry {
    static let skillId = TvGameCastSkill.skillId

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func makeCapabilityPlugin() -> CapabilityPlugin {
        TvGameCapabilityPlugin(cast: cast)
    }

    func launchGame(gameURL: String, gameId: String = "coin_catcher") async -> ControllerResult {
        await cast.launchGame(gameURL: gameURL, gameId: gameId)
    }

    func sendGameCommand(type: String, source: String = "GESTURE") async -> ControllerResult {
        await cast.sendGameCommand(type: type, source: source)
    }
}
