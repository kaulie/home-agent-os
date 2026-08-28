import Foundation
import UIKit

enum FeedbackAttachmentKind: String, Codable, Equatable, CaseIterable {
    case image
    case file
    case audio
    case video
    case other

    var label: String {
        switch self {
        case .image: return "图片"
        case .file: return "文件"
        case .audio: return "音频"
        case .video: return "视频"
        case .other: return "附件"
        }
    }
}

/// Uploaded attachment referenced by Brain asset_id.
struct FeedbackAttachment: Equatable, Codable {
    let assetId: String
    let kind: FeedbackAttachmentKind
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
        if !mimeType.isEmpty {
            row["mime_type"] = mimeType
        }
        if !filename.isEmpty {
            row["filename"] = filename
        }
        return row
    }
}

/// Local attachment waiting to upload (currently image-only picker).
struct PendingFeedbackAttachment: Identifiable, Equatable {
    let id = UUID()
    let preview: UIImage
    let kind: FeedbackAttachmentKind
    let mimeType: String
    let filename: String

    static func image(_ image: UIImage, filename: String = "") -> PendingFeedbackAttachment {
        PendingFeedbackAttachment(
            preview: image,
            kind: .image,
            mimeType: "image/jpeg",
            filename: filename
        )
    }
}

enum FeedbackAttachmentUpload {
    static func upload(
        _ pending: PendingFeedbackAttachment,
        intentURL: String,
        intentId: String
    ) async throws -> FeedbackAttachment {
        let uploaded = try await VisualInput.uploadAsset(
            image: pending.preview,
            intentURL: intentURL,
            uploadIntent: VisualInput.uploadIntentFeedbackAttachment,
            intentId: intentId
        )
        return FeedbackAttachment(
            assetId: uploaded.assetId,
            kind: pending.kind,
            mimeType: pending.mimeType.isEmpty ? "image/jpeg" : pending.mimeType,
            filename: pending.filename
        )
    }
}
