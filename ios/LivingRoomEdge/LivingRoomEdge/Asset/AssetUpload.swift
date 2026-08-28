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

/// iPhone `asset.upload`: copy a Runtime inbox capture or existing Asset to the
/// **active routing Brain** (`intentURL` / `AppModel.intentServerURL`).
/// One POST `/api/v1/assets/upload` — not LAN img-server then cloud.
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
        if dest == "gdrive" || dest == "dropbox" {
            _ = try PhotoUploadDest.endpoints(dest, primaryIntentURL: intentURL)
        }
        let wireDest = PhotoUploadDest.wireDest(forIntentURL: intentURL)

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
            let newId = try await postToActiveBrain(
                data: bytes,
                filename: "\(captureId).jpg",
                intentURL: intentURL,
                intentId: intentId
            )
            try? CaptureStore.markUploaded(captureId: captureId, dest: wireDest)
            return makeResult(assetId: newId, dest: wireDest)
        }

        guard let ref = existingAsset else {
            throw PhotoImgUpload.uploadError("asset.upload 失败：缺少 capture_ref 或 asset_ref。")
        }
        let bytes = try await loadBytes(
            assetId: ref,
            intentId: intentId,
            intentURL: intentURL
        )
        let newId = try await postToActiveBrain(
            data: bytes,
            filename: "\(ref).jpg",
            intentURL: intentURL,
            intentId: intentId
        )
        return makeResult(assetId: newId, dest: wireDest)
    }

    private static func makeResult(assetId: String, dest: String) -> Result {
        Result(
            message: "asset.upload dest=\(dest)\nasset_id: \(assetId)",
            outputs: [
                "asset_ref": [
                    "asset_id": assetId,
                    "type": "image",
                    "mime_type": "image/jpeg",
                ],
                "dest": dest,
            ]
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

    /// Single hop: POST multipart to the Brain `intentURL` is already routed to.
    private static func postToActiveBrain(
        data: Data,
        filename: String,
        intentURL: String,
        intentId: String
    ) async throws -> String {
        guard !data.isEmpty else {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：文件为空。")
        }
        guard let url = IntentClient.assetsUploadURL(fromIntentURL: intentURL) else {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：assets/upload 地址无效。")
        }
        NSLog("[AssetUpload] POST %@ dest=%@", url.absoluteString, PhotoUploadDest.wireDest(forIntentURL: intentURL))
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

        appendField("upload_intent", "asset.upload")
        appendField("producer", "asset.upload")
        appendField("type", "image")
        appendField("mime_type", "image/jpeg")
        if !pid.isEmpty {
            appendField("edge_id", pid)
            appendField("participant_id", pid)
        }
        let iid = intentId.trimmingCharacters(in: .whitespacesAndNewlines)
        if !iid.isEmpty {
            appendField("intent_id", iid)
        }

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
        request.timeoutInterval = PhotoImgUpload.hardTimeoutSec

        let (respData, response): (Data, URLResponse)
        do {
            (respData, response) = try await PhotoImgUpload.session.data(for: request)
        } catch {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：\(error.localizedDescription)")
        }
        let code = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200 ..< 300).contains(code),
              let obj = try? JSONSerialization.jsonObject(with: respData) as? [String: Any]
        else {
            let text = String(data: respData, encoding: .utf8) ?? ""
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：HTTP \(code) \(text.prefix(160))")
        }
        let aid = (obj["asset_id"] as? String)
            ?? ((obj["asset"] as? [String: Any])?["asset_id"] as? String)
            ?? ((obj["asset_ref"] as? [String: Any])?["asset_id"] as? String)
            ?? ""
        let trimmed = aid.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw PhotoImgUpload.uploadError("卡在上传（asset.upload）：登记 asset_ref 未返回 asset_id。")
        }
        return trimmed
    }
}
