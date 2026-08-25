import Foundation
import Security
import UIKit

/// Durable on-device copy of iPhone photo-workspace captures awaiting upload.
/// `Documents/local-photos/{local_id}.jpg`; deleted only after a successful upload.
/// Display thumbnails live in `ScanPreviewStore` (pruned); this store is never pruned,
/// so an upload failure never loses the photo.
enum LocalPhotoStore {
    static let idPrefix = "ph_"
    private static let idRegex = try! NSRegularExpression(pattern: "^ph_[0-9a-f]{24}$")

    enum StoreError: LocalizedError {
        case encode
        case missing(String)

        var errorDescription: String? {
            switch self {
            case .encode:
                return "照片 JPEG 编码失败"
            case .missing(let id):
                return "本机没有找到照片 \(id)"
            }
        }
    }

    static func makeId() -> String {
        idPrefix + randomHex(12)
    }

    static func isLocalId(_ raw: String) -> Bool {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        let range = NSRange(trimmed.startIndex..., in: trimmed)
        return idRegex.firstMatch(in: trimmed, options: [], range: range) != nil
    }

    static func save(image: UIImage, localId: String) throws {
        guard let data = image.jpegData(compressionQuality: 0.92), !data.isEmpty else {
            throw StoreError.encode
        }
        try data.write(to: fileURL(localId), options: .atomic)
    }

    static func read(localId: String) throws -> Data {
        let url = try fileURL(localId)
        guard let data = try? Data(contentsOf: url), !data.isEmpty else {
            throw StoreError.missing(localId)
        }
        return data
    }

    static func remove(localId: String) {
        guard let url = try? fileURL(localId) else { return }
        try? FileManager.default.removeItem(at: url)
    }

    private static func directory() throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let dir = docs.appendingPathComponent("local-photos", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    private static func fileURL(_ localId: String) throws -> URL {
        let safe = localId.replacingOccurrences(of: "/", with: "_")
        return try directory().appendingPathComponent("\(safe).jpg")
    }

    private static func randomHex(_ byteCount: Int) -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return bytes.map { String(format: "%02x", $0) }.joined()
    }
}
