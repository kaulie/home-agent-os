import Foundation

/// Send GameCommand via HTTP (Mac serve.py) — Cast path uses plugins when GoogleCast linked.
@MainActor
final class GameInputBridge: ObservableObject {
    static let shared = GameInputBridge()

    @Published private(set) var transportLabel = "未连接"
    @Published private(set) var lastError = ""

    private var baseURL: String = ""
    private var lastSentAt: [GameCommandType: Date] = [:]

    private init() {}

    func configure(baseURL: String) {
        let trimmed = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        self.baseURL = trimmed
        transportLabel = trimmed.isEmpty ? "未连接" : "HTTP · \(trimmed)"
    }

    func send(_ command: GameCommand) async {
        let now = Date()
        if let prev = lastSentAt[command.type], now.timeIntervalSince(prev) < 0.08 { return }
        lastSentAt[command.type] = now
        lastError = ""
        guard !baseURL.isEmpty, let url = URL(string: "\(baseURL)/command") else {
            lastError = "game host URL 未设置"
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONSerialization.data(withJSONObject: command.body)
        request.timeoutInterval = 3
        do {
            let (_, resp) = try await URLSession.shared.data(for: request)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
            guard (200 ..< 300).contains(code) else {
                lastError = "HTTP \(code)"
                return
            }
            transportLabel = "HTTP · \(baseURL)"
        } catch {
            lastError = error.localizedDescription
        }
    }
}
