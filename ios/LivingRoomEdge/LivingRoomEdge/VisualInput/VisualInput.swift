import AVFoundation
import Foundation
import UIKit
import VisionKit

/// Local Input: system document scan → `POST /api/v1/assets/upload`.
/// Chat entry does not go through Planner / 「扫描一下」 text intent.
enum VisualInput {
    static let uploadIntentDocumentScan = "document.scan"
    static let uploadIntentIPhonePhoto = "iphone.photo"
    static let uploadIntentIPhoneFile = "iphone.file"
    static let uploadIntentIPhoneAudio = "iphone.audio"
    static let uploadIntentFeedbackAttachment = "feedback.attachment"

    struct AssetResult {
        let assetId: String
        let assetRef: [String: Any]
        let localImage: UIImage
    }

    struct FileResult {
        let assetId: String
        let assetRef: [String: Any]
        let filename: String
        let mimeType: String
        let type: String
        let localImage: UIImage?
    }

    enum InputError: LocalizedError {
        case cancelled
        case message(String)

        var errorDescription: String? {
            switch self {
            case .cancelled:
                return "已取消"
            case let .message(s):
                return s
            }
        }

        var isCancelled: Bool {
            if case .cancelled = self { return true }
            return false
        }
    }

    static var isSupported: Bool {
        VNDocumentCameraViewController.isSupported
    }

    /// Open system scanner immediately, then upload+register via assets/upload.
    static func captureAndCreateAsset(
        intentURL: String,
        intentId: String? = nil,
        uploadIntent: String = uploadIntentDocumentScan
    ) async throws -> AssetResult {
        guard isSupported else {
            throw InputError.message("扫描失败：本机不支持系统文档扫描。")
        }
        try await ensureCameraPermission()
        let image = try await presentSystemScanner()
        return try await uploadAsset(
            image: image,
            intentURL: intentURL,
            uploadIntent: uploadIntent,
            intentId: intentId
        )
    }

    /// Runtime `document.scan` / `visual.input` (optional secondary path).
    static func runAsCapability(
        intentId: String,
        params _: [String: Any],
        intentURL: String,
        onPhase: ((String) async -> Void)? = nil
    ) async throws -> (message: String, outputs: [String: Any]) {
        guard isSupported else {
            throw InputError.message("扫描失败：本机不支持系统文档扫描。")
        }
        await onPhase?("waiting")
        let asset: AssetResult
        do {
            asset = try await captureAndCreateAsset(
                intentURL: intentURL,
                intentId: intentId,
                uploadIntent: uploadIntentDocumentScan
            )
        } catch let e as InputError where e.isCancelled {
            throw e
        } catch {
            throw InputError.message(error.localizedDescription)
        }
        await onPhase?("uploading")
        let ref = asset.assetRef
        let outputs: [String: Any] = [
            "status": "completed",
            "page_count": 1,
            "assets": [
                [
                    "asset_id": asset.assetId,
                    "type": "image",
                    "mime_type": "image/jpeg",
                    "page": 1,
                ],
            ],
            "asset_ref": ref,
        ]
        return (
            "document.scan ok asset_id=\(asset.assetId)",
            outputs
        )
    }

    // MARK: - System scanner UI

    @MainActor
    private static func presentSystemScanner() async throws -> UIImage {
        try await withCheckedThrowingContinuation { cont in
            let host = SystemScannerPresenter(continuation: cont)
            host.present()
        }
    }

    private static func ensureCameraPermission() async throws {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            return
        case .notDetermined:
            let ok = await AVCaptureDevice.requestAccess(for: .video)
            if !ok {
                throw InputError.message("扫描失败：需要相机权限（设置 → 相机）。")
            }
        case .denied, .restricted:
            throw InputError.message("扫描失败：相机权限未开（设置 → 相机）。")
        @unknown default:
            throw InputError.message("扫描失败：无法确认相机权限。")
        }
    }

    // MARK: - Unified assets/upload

    static func assetsUploadURL(fromIntentURL intentURL: String) -> URL? {
        IntentClient.assetsUploadURL(fromIntentURL: intentURL)
    }

    static func uploadAsset(
        image: UIImage,
        intentURL: String,
        uploadIntent: String,
        intentId: String?
    ) async throws -> AssetResult {
        guard let data = image.jpegData(compressionQuality: 0.92) else {
            throw InputError.message("上传失败：JPEG 编码失败。")
        }
        guard let url = assetsUploadURL(fromIntentURL: intentURL) else {
            throw InputError.message("上传失败：assets/upload 地址无效。")
        }
        let pid = ParticipantStore.participantId
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()

        func appendField(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append(
                "Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n"
                    .data(using: .utf8)!
            )
        }

        appendField("upload_intent", uploadIntent)
        appendField("producer", uploadIntent)
        appendField("type", "image")
        appendField("mime_type", "image/jpeg")
        if !pid.isEmpty {
            appendField("edge_id", pid)
            appendField("participant_id", pid)
        }
        let iid = (intentId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !iid.isEmpty {
            appendField("intent_id", iid)
        }

        let prefix: String
        switch uploadIntent {
        case uploadIntentIPhonePhoto: prefix = "photo"
        case uploadIntentFeedbackAttachment: prefix = "feedback"
        default: prefix = "scan"
        }
        let filename = "\(prefix)_\(Int(Date().timeIntervalSince1970)).jpg"
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

        let (respData, response): (Data, URLResponse)
        do {
            (respData, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw uploadFailure(error)
        }
        let code = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200 ..< 300).contains(code),
              let obj = try JSONSerialization.jsonObject(with: respData) as? [String: Any]
        else {
            let text = String(data: respData, encoding: .utf8) ?? ""
            throw InputError.message("上传失败：HTTP \(code)：\(text.prefix(200))")
        }
        let aid = (obj["asset_id"] as? String)
            ?? ((obj["asset"] as? [String: Any])?["asset_id"] as? String)
            ?? ((obj["asset_ref"] as? [String: Any])?["asset_id"] as? String)
            ?? ""
        let trimmed = aid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw InputError.message("上传失败：响应未返回 asset_id。")
        }
        let ref: [String: Any]
        if let r = obj["asset_ref"] as? [String: Any], !(r["asset_id"] as? String ?? "").isEmpty {
            ref = r
        } else {
            ref = [
                "asset_id": trimmed,
                "type": "image",
                "mime_type": "image/jpeg",
            ]
        }
        return AssetResult(assetId: trimmed, assetRef: ref, localImage: image)
    }

    /// Files-app pick → `POST /api/v1/assets/upload`. Not JPEG-forced.
    static func uploadFile(
        data: Data,
        filename: String,
        mimeType: String,
        type: String,
        intentURL: String,
        uploadIntent: String = uploadIntentIPhoneFile,
        intentId: String? = nil
    ) async throws -> FileResult {
        guard !data.isEmpty else {
            throw InputError.message("上传失败：文件为空。")
        }
        guard let url = assetsUploadURL(fromIntentURL: intentURL) else {
            throw InputError.message("上传失败：assets/upload 地址无效。")
        }
        let safeName = sanitizedFilename(filename)
        let mime = mimeType.trimmingCharacters(in: .whitespacesAndNewlines)
            .ifEmpty("application/octet-stream")
        let assetType = normalizedAssetType(type, mimeType: mime, filename: safeName)
        let pid = ParticipantStore.participantId
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()

        func appendField(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append(
                "Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n"
                    .data(using: .utf8)!
            )
        }

        appendField("upload_intent", uploadIntent)
        appendField("producer", uploadIntent)
        appendField("type", assetType)
        appendField("mime_type", mime)
        if !pid.isEmpty {
            appendField("edge_id", pid)
            appendField("participant_id", pid)
        }
        let iid = (intentId ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !iid.isEmpty {
            appendField("intent_id", iid)
        }

        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(safeName)\"\r\nContent-Type: \(mime)\r\n\r\n"
                .data(using: .utf8)!
        )
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 120

        let (respData, response): (Data, URLResponse)
        do {
            (respData, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw uploadFailure(error)
        }
        let code = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200 ..< 300).contains(code),
              let obj = try JSONSerialization.jsonObject(with: respData) as? [String: Any]
        else {
            let text = String(data: respData, encoding: .utf8) ?? ""
            throw InputError.message("上传失败：HTTP \(code)：\(text.prefix(200))")
        }
        let aid = (obj["asset_id"] as? String)
            ?? ((obj["asset"] as? [String: Any])?["asset_id"] as? String)
            ?? ((obj["asset_ref"] as? [String: Any])?["asset_id"] as? String)
            ?? ""
        let trimmed = aid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw InputError.message("上传失败：响应未返回 asset_id。")
        }
        let returnedType = ((obj["type"] as? String) ?? "").ifEmpty(assetType)
        let returnedMime = ((obj["mime_type"] as? String) ?? "").ifEmpty(mime)
        let ref: [String: Any]
        if let r = obj["asset_ref"] as? [String: Any], !(r["asset_id"] as? String ?? "").isEmpty {
            ref = r
        } else {
            ref = [
                "asset_id": trimmed,
                "type": returnedType,
                "mime_type": returnedMime,
            ]
        }
        return FileResult(
            assetId: trimmed,
            assetRef: ref,
            filename: safeName,
            mimeType: returnedMime,
            type: returnedType,
            localImage: assetType == "image" ? UIImage(data: data) : nil
        )
    }

    static func inferAssetType(mimeType: String, filename: String) -> String {
        normalizedAssetType("", mimeType: mimeType, filename: filename)
    }

    static func sanitizedFilename(_ raw: String) -> String {
        let last = (raw as NSString).lastPathComponent
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\\", with: "_")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let ns = last as NSString
        let ext = ns.pathExtension.lowercased()
        let stem = ext.isEmpty ? last : ns.deletingPathExtension
        let ascii = CharacterSet(charactersIn: "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")
        func allowed(_ ch: Unicode.Scalar) -> Bool {
            if ascii.contains(ch) { return true }
            return ch.value >= 0x4E00 && ch.value <= 0x9FFF
        }
        var slug = ""
        var prevUnderscore = false
        for ch in stem.unicodeScalars {
            if allowed(ch) {
                slug.append(Character(ch))
                prevUnderscore = false
            } else if !prevUnderscore {
                slug.append("_")
                prevUnderscore = true
            }
        }
        while slug.hasPrefix("_") || slug.hasPrefix(".") { slug.removeFirst() }
        while slug.hasSuffix("_") || slug.hasSuffix(".") { slug.removeLast() }
        if slug.isEmpty { slug = "file" }
        if slug.count > 48 { slug = String(slug.prefix(48)) }
        let safeExt = ext.range(of: "^[a-z0-9]{1,8}$", options: .regularExpression) != nil ? ext : "bin"
        return "\(slug).\(safeExt)"
    }

    private static func normalizedAssetType(_ explicit: String, mimeType: String, filename: String) -> String {
        let raw = explicit.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if raw == "image" || raw == "audio" || raw == "video" || raw == "document" {
            return raw
        }
        let mime = mimeType.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if mime.hasPrefix("image/") { return "image" }
        if mime.hasPrefix("audio/") { return "audio" }
        if mime.hasPrefix("video/") { return "video" }
        let name = filename.lowercased()
        if name.hasSuffix(".jpg") || name.hasSuffix(".jpeg") || name.hasSuffix(".png")
            || name.hasSuffix(".gif") || name.hasSuffix(".webp") || name.hasSuffix(".heic")
            || name.hasSuffix(".bmp") {
            return "image"
        }
        if name.hasSuffix(".mp3") || name.hasSuffix(".wav") || name.hasSuffix(".m4a")
            || name.hasSuffix(".aac") || name.hasSuffix(".ogg") || name.hasSuffix(".flac") {
            return "audio"
        }
        if name.hasSuffix(".mp4") || name.hasSuffix(".mov") || name.hasSuffix(".m4v")
            || name.hasSuffix(".webm") || name.hasSuffix(".mkv") {
            return "video"
        }
        return "document"
    }

    /// Upload-step network errors → readable Chinese, always attributed to the
    /// upload (never misreported as a capture failure).
    static func uploadFailure(_ error: Error) -> InputError {
        if let e = error as? InputError { return e }
        let ns = error as NSError
        if ns.domain == NSURLErrorDomain {
            switch ns.code {
            case NSURLErrorNotConnectedToInternet, NSURLErrorDataNotAllowed:
                return .message("上传失败：本机网络不可用。")
            case NSURLErrorTimedOut:
                return .message("上传失败：连接超时。")
            case NSURLErrorCannotConnectToHost, NSURLErrorCannotFindHost:
                return .message("上传失败：连不上 Brain 服务。")
            case NSURLErrorNetworkConnectionLost:
                return .message("上传失败：网络连接中断。")
            case NSURLErrorCancelled:
                return .message("上传失败：上传被取消。")
            default:
                break
            }
        }
        return .message("上传失败：\(error.localizedDescription)")
    }
}

private extension String {
    func ifEmpty(_ fallback: String) -> String {
        trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? fallback : self
    }
}

@MainActor
private final class SystemScannerPresenter: NSObject, VNDocumentCameraViewControllerDelegate {
    private static var retained: [ObjectIdentifier: SystemScannerPresenter] = [:]
    private var continuation: CheckedContinuation<UIImage, Error>?

    init(continuation: CheckedContinuation<UIImage, Error>) {
        self.continuation = continuation
    }

    func present() {
        guard let root = topViewController() else {
            finish(.failure(VisualInput.InputError.message("扫描失败：找不到可呈现的界面。")))
            return
        }
        Self.retained[ObjectIdentifier(self)] = self
        let scanner = VNDocumentCameraViewController()
        scanner.delegate = self
        root.present(scanner, animated: true)
    }

    func documentCameraViewController(
        _ controller: VNDocumentCameraViewController,
        didFinishWith scan: VNDocumentCameraScan
    ) {
        let image: UIImage? = scan.pageCount > 0 ? scan.imageOfPage(at: 0) : nil
        controller.dismiss(animated: true) { [weak self] in
            guard let self else { return }
            if let image {
                self.finish(.success(image))
            } else {
                self.finish(.failure(VisualInput.InputError.message("扫描失败：没有扫描页。")))
            }
        }
    }

    func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
        controller.dismiss(animated: true) { [weak self] in
            self?.finish(.failure(VisualInput.InputError.cancelled))
        }
    }

    func documentCameraViewController(
        _ controller: VNDocumentCameraViewController,
        didFailWithError error: Error
    ) {
        controller.dismiss(animated: true) { [weak self] in
            self?.finish(.failure(VisualInput.InputError.message("扫描失败：\(error.localizedDescription)")))
        }
    }

    private func finish(_ result: Result<UIImage, Error>) {
        defer { Self.retained.removeValue(forKey: ObjectIdentifier(self)) }
        guard let cont = continuation else { return }
        continuation = nil
        cont.resume(with: result)
    }

    private func topViewController() -> UIViewController? {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let window = scenes.flatMap(\.windows).first(where: \.isKeyWindow)
            ?? scenes.flatMap(\.windows).first
        var top = window?.rootViewController
        while let presented = top?.presentedViewController {
            top = presented
        }
        return top
    }
}
