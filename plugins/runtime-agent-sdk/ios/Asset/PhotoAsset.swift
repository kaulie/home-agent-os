import Foundation

final class PhotoAsset: Asset {
    init(location: String, id: String? = nil) {
        super.init(type: .photo, location: location, id: id)
    }
}
