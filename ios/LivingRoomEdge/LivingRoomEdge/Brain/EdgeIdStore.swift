import Foundation

/// Persists Brain-issued `edge_id` to a local file so relaunches reuse the same id
/// and skip `/api/v1/edge-register`.
enum EdgeIdStore {
    private static let fileName = "assigned_edge_id.txt"

    private static var fileURL: URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let dir = root.appendingPathComponent("LivingRoomEdge", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent(fileName)
    }

    /// Also migrate from legacy UserDefaults key if present.
    private static let legacyUserDefaultsKey = "livingroom.edge.assignedEdgeId"

    static func load() -> String? {
        let url = fileURL
        if let data = try? Data(contentsOf: url),
           let text = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !text.isEmpty {
            return text
        }
        // One-time migrate from UserDefaults → file
        if let legacy = UserDefaults.standard.string(forKey: legacyUserDefaultsKey)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !legacy.isEmpty {
            save(legacy)
            UserDefaults.standard.removeObject(forKey: legacyUserDefaultsKey)
            return legacy
        }
        return nil
    }

    static func save(_ edgeId: String) {
        let trimmed = edgeId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            clear()
            return
        }
        try? trimmed.data(using: .utf8)?.write(to: fileURL, options: [.atomic])
        // Keep UserDefaults cleared so file is the single source of truth.
        UserDefaults.standard.removeObject(forKey: legacyUserDefaultsKey)
    }

    static func clear() {
        try? FileManager.default.removeItem(at: fileURL)
        UserDefaults.standard.removeObject(forKey: legacyUserDefaultsKey)
    }

    static var storagePathDescription: String {
        fileURL.path
    }
}
