import Foundation

/// Manages digital content publish / fetch against the Edge business plane.
final class AssetManager {
    /// Last human-readable status from publish / fetch (for Controllers that surface messages).
    private(set) var lastMessage: String = ""
    /// Absolute download URL from the last successful photo publish (server `url` field).
    private(set) var lastPublishUrl: String?
    /// Server filename (`saved_as`) from the last successful photo publish.
    private(set) var lastPublishSavedAs: String?

    /// Publish local asset bytes to the business server.
    @discardableResult
    func publish(_ asset: Asset) async throws -> Asset {
        switch asset.type {
        case .photo:
            return try await publishPhoto(asset)
        }
    }

    /// Fetch the latest asset of a given type from the business server; writes locally and returns it.
    func fetchLatest(type: AssetType) async throws -> Asset {
        switch type {
        case .photo:
            return try await fetchLatestPhoto()
        }
    }

    private func publishPhoto(_ asset: Asset) async throws -> Asset {
        let path = asset.location.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty else {
            throw AssetTransportError.emptyLocation
        }
        let fileURL = URL(fileURLWithPath: path)
        let result = try await AssetHTTPTransport.uploadPhoto(fileURL: fileURL)
        lastMessage = result.message
        lastPublishUrl = result.url
        lastPublishSavedAs = result.savedAs
        // id = cloud public URL only (never leave local filesystem path as id).
        if let url = result.url?.trimmingCharacters(in: .whitespacesAndNewlines),
           url.lowercased().hasPrefix("http://") || url.lowercased().hasPrefix("https://") {
            asset.id = url
            lastPublishUrl = url
        } else {
            asset.id = nil
            lastPublishUrl = nil
        }
        return asset
    }

    private func fetchLatestPhoto() async throws -> PhotoAsset {
        let downloaded = try await AssetHTTPTransport.downloadLatestPhoto()
        let saved = try Self.saveLocally(
            data: downloaded.data,
            suggestedName: downloaded.suggestedFilename
        )
        lastMessage =
            "downloaded from server → \(saved.path) · \(downloaded.suggestedFilename) · \(downloaded.data.count) bytes\n⏱ \(downloaded.durationLabel)"
        return PhotoAsset(location: saved.path)
    }

    private static func saveLocally(data: Data, suggestedName: String) throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let dir = docs.appendingPathComponent("RuntimeAssets", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let safe = suggestedName.replacingOccurrences(of: "/", with: "_")
        let url = dir.appendingPathComponent(safe)
        try data.write(to: url, options: .atomic)
        return url
    }
}
