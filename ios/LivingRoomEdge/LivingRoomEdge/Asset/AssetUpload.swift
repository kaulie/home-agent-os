import Foundation

/// Local files produced by `camera.capture` on this device. `asset.upload`
/// reads bytes here for already-registered Assets; inbox captures go through
/// `CaptureStore`.
enum LocalCaptureAssets {
    private static let lock = NSLock()
    private static var files: [String: URL] = [:]

    static func remember(assetId: String, fileURL: URL) {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !aid.isEmpty else { return }
        lock.lock()
        files[aid] = fileURL
        lock.unlock()
    }

    static func data(for assetId: String) -> Data? {
        let aid = assetId.trimmingCharacters(in: .whitespacesAndNewlines)
        lock.lock()
        let url = files[aid]
        lock.unlock()
        guard let url, FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try? Data(contentsOf: url)
    }
}

/// iPhone `asset.upload`: copy a Runtime inbox capture or existing Asset to dest.
/// Upload bytes go through `PhotoImgUpload` (probe + 10 min hard timeout).
enum AssetUpload {
    struct Result {
        let message: String
        let outputs: [String: Any]
    }

    static func run(
        intentId: String,
        params: [String: Any],
        intentURL: String
    ) async throws -> Result {
        let dest = PhotoUploadDest.parse(params)
        let wireDest = PhotoUploadDest.displayName(dest)

        var captureId = CaptureStore.parseCaptureId(params["capture_ref"])
        let existingAsset = parseRef(params["asset_ref"])
        if captureId == nil, existingAsset == nil {
            do {
                captureId = try CaptureStore.uniquePending(dest: wireDest)
            } catch {
                throw PhotoImgUpload.uploadError(error.localizedDescription)
            }
        }

        if let captureId {
            let bytes: Data
            do {
                bytes = try CaptureStore.readBytes(captureId: captureId)
            } catch {
                throw PhotoImgUpload.uploadError(error.localizedDescription)
            }
            let uploaded = try await PhotoImgUpload.uploadData(
                data: bytes,
                filename: "\(captureId).jpg",
                dest: dest,
                phase: "asset.upload"
            )
            let newId = try await registerAsset(
                intentURL: intentURL,
                intentId: intentId,
                savedAs: uploaded.savedAs,
                publicBase: uploaded.publicBase
            )
            try? CaptureStore.markUploaded(captureId: captureId, dest: wireDest)
            let outputs: [String: Any] = [
                "asset_ref": [
                    "asset_id": newId,
                    "type": "image",
                    "mime_type": "image/jpeg",
                ],
                "dest": wireDest,
            ]
            return Result(
                message: "asset.upload dest=\(wireDest)\nasset_id: \(newId)",
                outputs: outputs
            )
        }

        guard let ref = existingAsset else {
            throw PhotoImgUpload.uploadError("asset.upload 失败：缺少 capture_ref 或 asset_ref。")
        }
        let bytes = try await loadBytes(
            assetId: ref,
            intentId: intentId,
            intentURL: intentURL
        )
        let uploaded = try await PhotoImgUpload.uploadData(
            data: bytes,
            filename: "\(ref).jpg",
            dest: dest,
            phase: "asset.upload"
        )
        let newId = try await registerAsset(
            intentURL: intentURL,
            intentId: intentId,
            savedAs: uploaded.savedAs,
            publicBase: uploaded.publicBase
        )
        let outputs: [String: Any] = [
            "asset_ref": [
                "asset_id": newId,
                "type": "image",
                "mime_type": "image/jpeg",
            ],
            "dest": wireDest,
        ]
        return Result(
            message: "asset.upload dest=\(wireDest)\nasset_id: \(newId)",
            outputs: outputs
        )
    }

    private static func parseRef(_ raw: Any?) -> String? {
        if let s = raw as? String {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.hasPrefix("$") { return nil }
            if t.hasPrefix("{"),
               let data = t.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                return parseRef(obj)
            }
            return t.isEmpty ? nil : t
        }
        guard let obj = raw as? [String: Any] else { return nil }
        let aid = (obj["asset_id"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return aid.isEmpty ? nil : aid
    }

    private static func loadBytes(assetId: String, intentId: String, intentURL: String) async throws -> Data {
        if let local = LocalCaptureAssets.data(for: assetId), !local.isEmpty {
            return local
        }
        if let path = await fetchLocalStoragePath(
            assetId: assetId,
            intentId: intentId,
            intentURL: intentURL
        ), FileManager.default.fileExists(atPath: path) {
            if let data = try? Data(contentsOf: URL(fileURLWithPath: path)), !data.isEmpty {
                return data
            }
        }
        let client = await AppModel.shared.intentClient
        if let data = await client.fetchAssetImageData(
            assetId: assetId,
            intentId: intentId,
            intentURL: intentURL,
            representation: "original"
        ), !data.isEmpty {
            return data
        }
        throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：无法从本机或 Brain 读取 asset \(assetId) 的内容。")
    }

    private static func fetchLocalStoragePath(
        assetId: String,
        intentId: String,
        intentURL: String
    ) async -> String? {
        guard let base = IntentClient.assetsURL(fromIntentURL: intentURL) else { return nil }
        var components = URLComponents(url: base.appendingPathComponent(assetId), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "intent_id", value: intentId),
            URLQueryItem(name: "edge_id", value: ParticipantStore.participantId),
        ]
        guard let url = components?.url else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 15
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              let http = response as? HTTPURLResponse,
              (200 ..< 300).contains(http.statusCode),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return nil
        }
        let asset = (obj["asset"] as? [String: Any]) ?? obj
        let storage = asset["storage"] as? [String: Any]
        let backend = (storage?["backend"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard backend == "local" else { return nil }
        let key = (storage?["key"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return key.isEmpty ? nil : key
    }

    private static func registerAsset(
        intentURL: String,
        intentId: String,
        savedAs: String,
        publicBase: String
    ) async throws -> String {
        guard let url = IntentClient.assetsURL(fromIntentURL: intentURL) else {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：assets 地址无效。")
        }
        let pid = ParticipantStore.participantId
        let base = publicBase.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let storage: [String: Any] = [
            "backend": "img_server",
            "key": savedAs,
            "public_base": base,
            "edge_id": pid,
        ]
        let body: [String: Any] = [
            "type": "image",
            "mime_type": "image/jpeg",
            "intent_id": intentId,
            "execution_id": intentId,
            "producer": "asset.upload",
            "edge_id": pid,
            "storage": storage,
        ]
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        request.timeoutInterval = 30
        let (data, response) = try await URLSession.shared.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200 ..< 300).contains(code),
              let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：登记 asset_ref 失败。")
        }
        let returned: String = {
            if let direct = obj["asset_id"] as? String { return direct }
            if let nested = (obj["asset"] as? [String: Any])?["asset_id"] as? String { return nested }
            return ""
        }()
        let trimmed = returned.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：登记 asset_ref 未返回 asset_id。")
        }
        return trimmed
    }
}
