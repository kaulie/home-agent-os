import Foundation

enum TvGameLaunch {
    /// Resolve game URL: explicit param → default Mac LAN :8102 on same /24 as Brain.
    static func resolveGameURL(from params: [String: Any], brainURL: String) -> String {
        if let raw = params["game_url"] as? String {
            let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.hasPrefix("http://") || t.hasPrefix("https://") { return t }
        }
        if let host = lanHostHint(from: brainURL) {
            return "http://\(host):8102/"
        }
        return "http://127.0.0.1:8102/"
    }

    static func run(params: [String: Any], brainURL: String) async -> (message: String, outputs: [String: Any]) {
        let gameId = (params["game_id"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            .ifEmpty("coin_catcher") ?? "coin_catcher"
        let url = resolveGameURL(from: params, brainURL: brainURL)
        await MainActor.run {
            GameSession.shared.activate(gameURL: url, gameId: gameId)
            GameInputBridge.shared.configure(baseURL: url)
        }
        NotificationCenter.default.post(name: .gameSessionActivated, object: nil)
        let outputs: [String: Any] = [
            "status": "ready",
            "game_id": gameId,
            "game_url": url,
        ]
        return ("game.launch ok game_id=\(gameId) url=\(url)", outputs)
    }

    private static func lanHostHint(from brainURL: String) -> String? {
        guard let u = URL(string: brainURL), let host = u.host else { return nil }
        if host == "127.0.0.1" || host == "localhost" { return "127.0.0.1" }
        return host
    }
}

extension Notification.Name {
    static let gameSessionActivated = Notification.Name("homeagent.gameSessionActivated")
}

private extension String {
    func ifEmpty(_ fallback: String) -> String {
        trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? fallback : self
    }
}
