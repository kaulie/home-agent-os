import Foundation
import UIKit

enum PickupAssetUpload {
    private static let uploadIntent = "feedback.attachment"

    static func assetsUploadURL(from brainURL: String) -> URL? {
        let trimmed = brainURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, var components = URLComponents(string: trimmed) else { return nil }
        var path = components.path
        if path.hasSuffix("/intent") {
            path = String(path.dropLast("intent".count)) + "assets/upload"
        } else if let range = path.range(of: "/api/v1/") {
            path = String(path[..<range.upperBound]) + "assets/upload"
        } else if path.isEmpty || path == "/" {
            path = "/api/v1/assets/upload"
        } else if !path.hasSuffix("assets/upload") {
            path = path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/api/v1/assets/upload"
        }
        components.path = path
        components.query = nil
        return components.url
    }

    static func uploadFeedbackImage(
        _ pending: PendingPickupFeedbackAttachment,
        brainURL: String,
        intentId: String,
        participantId: String
    ) async throws -> PickupFeedbackAttachment {
        guard let data = pending.preview.jpegData(compressionQuality: 0.92) else {
            throw UploadError.message("图片编码失败")
        }
        guard let url = assetsUploadURL(from: brainURL) else {
            throw UploadError.message("上传地址无效")
        }

        let pid = participantId.trimmingCharacters(in: .whitespacesAndNewlines)
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()

        func appendField(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".data(using: .utf8)!)
        }

        appendField("upload_intent", uploadIntent)
        appendField("producer", uploadIntent)
        appendField("type", "image")
        appendField("mime_type", "image/jpeg")
        if !pid.isEmpty {
            appendField("edge_id", pid)
            appendField("participant_id", pid)
        }
        if !iid.isEmpty {
            appendField("intent_id", iid)
        }

        let filename = pending.filename.isEmpty
            ? "feedback_\(Int(Date().timeIntervalSince1970)).jpg"
            : pending.filename
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\nContent-Type: image/jpeg\r\n\r\n"
                .data(using: .utf8)!
        )
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 60

        let (respData, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200 ..< 300).contains(code),
              let obj = try JSONSerialization.jsonObject(with: respData) as? [String: Any] else {
            let text = String(data: respData, encoding: .utf8) ?? ""
            throw UploadError.message("上传失败：HTTP \(code) \(text.prefix(120))")
        }

        let assetId = (obj["asset_id"] as? String)
            ?? ((obj["asset"] as? [String: Any])?["asset_id"] as? String)
            ?? ((obj["asset_ref"] as? [String: Any])?["asset_id"] as? String)
            ?? ""
        let trimmed = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw UploadError.message("上传失败：未返回 asset_id")
        }

        return PickupFeedbackAttachment(
            assetId: trimmed,
            kind: pending.kind,
            mimeType: pending.mimeType.isEmpty ? "image/jpeg" : pending.mimeType,
            filename: filename
        )
    }

    enum UploadError: LocalizedError {
        case message(String)
        var errorDescription: String? {
            switch self {
            case let .message(text): return text
            }
        }
    }
}
