import Foundation
import UIKit

enum PickupFeedbackAttachmentKind: String, Codable, Equatable {
    case image

    var label: String { "图片" }
}

struct PickupFeedbackAttachment: Equatable, Codable {
    let assetId: String
    let kind: PickupFeedbackAttachmentKind
    let mimeType: String
    let filename: String

    enum CodingKeys: String, CodingKey {
        case assetId = "asset_id"
        case kind
        case mimeType = "mime_type"
        case filename
    }

    func apiPayload() -> [String: String] {
        var row: [String: String] = [
            "asset_id": assetId,
            "kind": kind.rawValue,
        ]
        if !mimeType.isEmpty { row["mime_type"] = mimeType }
        if !filename.isEmpty { row["filename"] = filename }
        return row
    }
}

struct PendingPickupFeedbackAttachment: Identifiable, Equatable {
    let id = UUID()
    let preview: UIImage
    let kind: PickupFeedbackAttachmentKind
    let mimeType: String
    let filename: String

    static func image(_ image: UIImage, filename: String = "") -> PendingPickupFeedbackAttachment {
        PendingPickupFeedbackAttachment(
            preview: image,
            kind: .image,
            mimeType: "image/jpeg",
            filename: filename
        )
    }
}
