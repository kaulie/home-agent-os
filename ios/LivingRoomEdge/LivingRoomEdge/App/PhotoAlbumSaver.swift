import Foundation
import Photos
import UIKit

/// Save a local image file into the system Photo Library (add-only permission).
enum PhotoAlbumSaver {
    enum SaveError: LocalizedError {
        case missingFile
        case invalidImage
        case denied
        case system(String)

        var errorDescription: String? {
            switch self {
            case .missingFile: return "文件不存在"
            case .invalidImage: return "无法读取图片"
            case .denied: return "未授权写入相册（设置 → 客厅 Edge iPhone → 照片）"
            case let .system(s): return s
            }
        }
    }

    static func save(filePath: String) async throws {
        let path = filePath.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !path.isEmpty, FileManager.default.fileExists(atPath: path) else {
            throw SaveError.missingFile
        }
        guard let image = UIImage(contentsOfFile: path) else {
            throw SaveError.invalidImage
        }
        try await save(image: image)
    }

    static func save(image: UIImage) async throws {
        let status = await requestAddOnlyAccess()
        guard status == .authorized || status == .limited else {
            throw SaveError.denied
        }

        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            PHPhotoLibrary.shared().performChanges({
                PHAssetChangeRequest.creationRequestForAsset(from: image)
            }, completionHandler: { ok, error in
                if ok {
                    cont.resume()
                } else {
                    cont.resume(
                        throwing: SaveError.system(error?.localizedDescription ?? "保存失败")
                    )
                }
            })
        }
    }

    private static func requestAddOnlyAccess() async -> PHAuthorizationStatus {
        let current = PHPhotoLibrary.authorizationStatus(for: .addOnly)
        if current != .notDetermined {
            return current
        }
        return await PHPhotoLibrary.requestAuthorization(for: .addOnly)
    }
}
