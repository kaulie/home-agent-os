import Foundation

/// Disk cache for finished iPhone recordings (playback only). Keyed by asset_id.
enum AudioPreviewStore {
    private static let folderName = "audio-previews"
    private static let maxFiles = 40

    static func save(assetId: String, data: Data) {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty, !data.isEmpty else { return }
        let dir = directory()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? data.write(to: fileURL(aid), options: .atomic)
        prune()
    }

    static func fileURL(for assetId: String) -> URL? {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty else { return nil }
        let url = fileURL(aid)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return url
    }

    private static func directory() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        return base.appendingPathComponent(folderName, isDirectory: true)
    }

    private static func fileURL(_ assetId: String) -> URL {
        let safe = assetId.replacingOccurrences(of: "/", with: "_")
        return directory().appendingPathComponent("\(safe).m4a")
    }

    private static func prune() {
        let dir = directory()
        guard let files = try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: [.skipsHiddenFiles]
        ) else { return }
        let ranked = files.compactMap { url -> (URL, Date)? in
            let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate)
                ?? .distantPast
            return (url, date)
        }
        .sorted { $0.1 > $1.1 }
        for extra in ranked.dropFirst(maxFiles) {
            try? FileManager.default.removeItem(at: extra.0)
        }
    }
}
