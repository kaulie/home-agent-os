import Foundation

/// Wire service chromecast.game — launch interactive games on Cast Receiver.
final class TvGameCastSkill: Skill {
    static let skillId = "chromecast.game"

    private let cast: CastSessionController

    init(cast: CastSessionController = .shared) {
        self.cast = cast
    }

    func service() -> ServiceDescriptor {
        ServiceDescriptor(
            serviceId: Self.skillId,
            version: "0.1.0",
            displayName: "TV Game Cast",
            group: "game",
            capabilities: [
                CapabilityDescriptor(
                    capabilityId: "game.launch",
                    description: "能：Cast launch_game 加载 LAN 互动游戏（必填 game_id）。不能：实时帧控制、MOVE/PAUSE plan 步。",
                    inputSchema: [
                        "game_id": SchemaField(
                            type: "string",
                            required: true,
                            description: "游戏 id，如 coin_catcher"
                        ),
                        "game_url": SchemaField(
                            type: "string",
                            required: false,
                            description: "LAN 游戏页 URL；缺省由 Mac game host 或默认端口解析"
                        ),
                    ]
                ),
            ]
        )
    }

    func execute(capabilityId: String, params: [String: String], context: SkillContext) async -> SkillResult {
        guard capabilityId == "game.launch" else {
            return .error("unsupported capability: \(capabilityId)")
        }
        let gameId = (params["game_id"] ?? "coin_catcher").trimmingCharacters(in: .whitespacesAndNewlines)
        let gameURL = (params["game_url"] ?? params["photo_url"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !gameURL.isEmpty else {
            return .error("game.launch requires resolved game_url")
        }
        let result = await cast.launchGame(gameURL: gameURL, gameId: gameId)
        if result.ok {
            return .ok(result.message)
        }
        return .error(result.message)
    }
}
