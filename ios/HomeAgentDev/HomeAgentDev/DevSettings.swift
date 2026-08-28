import Foundation

enum DevSettings {
    private static let tokenKey = "homeagent.dev.token"

    static var adminToken: String {
        get { UserDefaults.standard.string(forKey: tokenKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: tokenKey) }
    }

    /// Resolved active Brain base (LAN or Cloud). Prefer `DevStore.activeBrainURL`.
    static var brainURL: String {
        DevBrainEndpoint.lanBaseURL
    }

    static func normalize(_ raw: String) -> String {
        DevBrainEndpoint.normalizeBase(raw)
    }
}
