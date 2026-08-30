import Foundation

enum AdminSettings {
    static let defaultBrainURL = "http://192.168.3.84:9527"
    static let cloudBrainURL = "http://115.190.153.53:9527"

    private static let brainKey = "homeagent.admin.brainURL"
    private static let tokenKey = "homeagent.admin.token"
    private static let logKey = "homeagent.admin.opLog"
    private static let logLimit = 200

    static var brainURL: String {
        get {
            let saved = UserDefaults.standard.string(forKey: brainKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if saved.isEmpty {
                return defaultBrainURL
            }
            return saved
        }
        set {
            UserDefaults.standard.set(normalize(newValue), forKey: brainKey)
        }
    }

    static var adminToken: String {
        get { UserDefaults.standard.string(forKey: tokenKey) ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: tokenKey) }
    }

    static func normalize(_ raw: String) -> String {
        var value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") {
            value.removeLast()
        }
        return value
    }

    static func loadLogs() -> [AdminLogEntry] {
        guard let data = UserDefaults.standard.data(forKey: logKey) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        return (try? decoder.decode([AdminLogEntry].self, from: data)) ?? []
    }

    static func saveLogs(_ entries: [AdminLogEntry]) {
        let decoderReady = Array(entries.prefix(logLimit))
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .secondsSince1970
        guard let data = try? encoder.encode(decoderReady) else { return }
        UserDefaults.standard.set(data, forKey: logKey)
    }
}
