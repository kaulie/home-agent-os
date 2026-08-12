import Foundation

/// Base type for digital content managed by the Edge runtime asset manager.
class Asset {
    let type: AssetType
    /// Local file path (or URI) for the content bytes.
    var location: String
    var id: String?

    init(type: AssetType, location: String, id: String? = nil) {
        self.type = type
        self.location = location
        self.id = id
    }

    /// Factory matching `Asset(type:location:)` call style.
    static func make(type: AssetType, location: String, id: String? = nil) -> Asset {
        switch type {
        case .photo:
            return PhotoAsset(location: location, id: id)
        }
    }
}
