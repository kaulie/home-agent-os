import Foundation

@MainActor
final class GameSession: ObservableObject {
    static let shared = GameSession()

    @Published var gameURL: String = ""
    @Published var gameId: String = "coin_catcher"
    @Published var isActive: Bool = false
    @Published var lastCommandLabel: String = ""

    private init() {}

    func activate(gameURL: String, gameId: String = "coin_catcher") {
        self.gameURL = gameURL.trimmingCharacters(in: .whitespacesAndNewlines)
        self.gameId = gameId
        isActive = true
    }

    func deactivate() {
        isActive = false
    }

    func noteCommand(_ type: GameCommandType, source: GameCommandSource) {
        lastCommandLabel = "\(source.rawValue) · \(type.rawValue)"
    }
}
