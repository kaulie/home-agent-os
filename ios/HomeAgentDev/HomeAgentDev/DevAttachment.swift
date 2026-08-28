import PhotosUI
import SwiftUI
import UIKit

enum DevAttachmentKind: String, Codable, Equatable, CaseIterable {
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

/// Local attachment selected in the composer, waiting to upload.
struct PendingDevAttachment: Identifiable, Equatable {
    let id = UUID()
    let preview: UIImage?
    let kind: DevAttachmentKind
    let mimeType: String
    let filename: String
    let imageData: Data?

    static func image(_ image: UIImage, filename: String = "") -> PendingDevAttachment {
        PendingDevAttachment(
            preview: image,
            kind: .image,
            mimeType: "image/jpeg",
            filename: filename,
            imageData: image.jpegData(compressionQuality: 0.9)
        )
    }
}

extension DebugAttachment {
    func apiPayload() -> [String: String] {
        var row: [String: String] = [
            "asset_id": assetId,
            "kind": kind.isEmpty ? "other" : kind,
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

/// Reusable attachment picker + thumbnail strip for Dev Task composers.
struct DevAttachmentComposer: View {
    @Binding var pending: [PendingDevAttachment]
    @State private var pickerItems: [PhotosPickerItem] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !pending.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(pending) { item in
                            ZStack(alignment: .topTrailing) {
                                if let preview = item.preview {
                                    Image(uiImage: preview)
                                        .resizable()
                                        .scaledToFill()
                                        .frame(width: 72, height: 72)
                                        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                                } else {
                                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                                        .fill(DevTheme.chip)
                                        .frame(width: 72, height: 72)
                                        .overlay {
                                            Image(systemName: "paperclip")
                                                .foregroundStyle(DevTheme.dim)
                                        }
                                }
                                Button {
                                    pending.removeAll { $0.id == item.id }
                                } label: {
                                    Image(systemName: "xmark.circle.fill")
                                        .font(.system(size: 18))
                                        .symbolRenderingMode(.palette)
                                        .foregroundStyle(Color.white, Color.black.opacity(0.55))
                                }
                                .offset(x: 6, y: -6)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                }
            }

            PhotosPicker(
                selection: $pickerItems,
                maxSelectionCount: 8,
                matching: .images
            ) {
                Label("添加附件", systemImage: "paperclip")
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .foregroundStyle(DevTheme.sand)
            }
            .onChange(of: pickerItems) { items in
                guard !items.isEmpty else { return }
                Task { await importPickerItems(items) }
            }
        }
    }

    @MainActor
    private func importPickerItems(_ items: [PhotosPickerItem]) async {
        var imported: [PendingDevAttachment] = []
        for item in items {
            guard let data = try? await item.loadTransferable(type: Data.self),
                  let image = UIImage(data: data) else {
                continue
            }
            imported.append(.image(image))
        }
        if !imported.isEmpty {
            pending.append(contentsOf: imported)
        }
        pickerItems = []
    }
}

struct DevAttachmentGallery: View {
    let attachments: [DebugAttachment]
    let scopeId: String
    let brainURL: String

    var body: some View {
        if !attachments.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(attachments) { attachment in
                        DevAttachmentThumbnail(
                            attachment: attachment,
                            scopeId: scopeId,
                            brainURL: brainURL
                        )
                    }
                }
            }
        }
    }
}

private struct DevAttachmentThumbnail: View {
    let attachment: DebugAttachment
    let scopeId: String
    let brainURL: String

    @State private var image: UIImage?

    var body: some View {
        Group {
            if attachment.isImage, let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else if attachment.isImage {
                ProgressView()
            } else {
                VStack(spacing: 4) {
                    Image(systemName: "doc")
                    Text(attachment.displayLabel)
                        .font(.system(size: 9, design: .rounded))
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                }
                .foregroundStyle(DevTheme.dim)
            }
        }
        .frame(width: 88, height: 88)
        .background(DevTheme.chip)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .task(id: "\(attachment.assetId)|\(scopeId)|\(brainURL)") {
            guard attachment.isImage else { return }
            do {
                let data = try await DevClient.fetchDevTaskAttachmentData(
                    brainURL: brainURL,
                    assetId: attachment.assetId,
                    scopeId: scopeId
                )
                if let loaded = UIImage(data: data) {
                    image = loaded
                }
            } catch {
                image = nil
            }
        }
    }
}

enum DevAttachmentUpload {
    static func upload(
        _ pending: PendingDevAttachment,
        brainURL: String,
        token: String
    ) async throws -> DebugAttachment {
        guard let data = pending.imageData, !data.isEmpty else {
            throw DevClientError.server("附件数据为空")
        }
        let filename = pending.filename.isEmpty
            ? "dev_task_\(Int(Date().timeIntervalSince1970)).jpg"
            : pending.filename
        return try await DevClient.uploadDevTaskAttachment(
            brainURL: brainURL,
            token: token,
            fileData: data,
            filename: filename,
            mimeType: pending.mimeType,
            kind: pending.kind.rawValue
        )
    }
}
