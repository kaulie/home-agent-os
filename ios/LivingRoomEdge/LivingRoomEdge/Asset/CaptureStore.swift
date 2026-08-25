import CryptoKit
import Foundation
import Security

/// Runtime-private GoPro inbox. Plugins do not list this directory.
/// `Documents/captures/inbox/{capture_id}.jpg` + `.json` sidecar.
enum CaptureStore {
    struct Ref {
        let captureId: String
        let type: String
        let mimeType: String

        var json: [String: String] {
            [
                "capture_id": captureId,
                "type": type,
                "mime_type": mimeType,
            ]
        }
    }

    enum StoreError: LocalizedError {
        case empty
        case missing(String)
        case invalidId(String)
        case nonePending
        case manyPending

        var errorDescription: String? {
            switch self {
            case .empty:
                return "拍照失败：空图片。"
            case .missing(let id):
                return "本机 inbox 没有 \(id)"
            case .invalidId(let id):
                return "无效 capture_id：\(id)"
            case .nonePending:
                return "本机 inbox 没有待上传的 capture，请带 capture_id"
            case .manyPending:
                return "本机 inbox 有多条待上传，请带 capture_id"
            }
        }
    }

    private static let idRegex = try! NSRegularExpression(pattern: "^cap_[0-9a-f]{24}$")

    static func inboxDirectory() throws -> URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        let dir = docs.appendingPathComponent("captures/inbox", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static func put(jpeg: Data, originalName: String = "", source: String = "gopro") throws -> Ref {
        guard !jpeg.isEmpty else { throw StoreError.empty }
        let cid = "cap_" + randomHex(12)
        let inbox = try inboxDirectory()
        let jpg = inbox.appendingPathComponent("\(cid).jpg")
        try jpeg.write(to: jpg, options: .atomic)
        let digest = SHA256.hash(data: jpeg)
        let sha = digest.map { String(format: "%02x", $0) }.joined()
        let iso = ISO8601DateFormatter().string(from: Date())
        let meta: [String: Any] = [
            "capture_id": cid,
            "created_at": iso,
            "source": source,
            "original_name": originalName,
            "sha256": sha,
            "uploaded_dests": [String](),
        ]
        let sidecar = inbox.appendingPathComponent("\(cid).json")
        try JSONSerialization.data(withJSONObject: meta, options: [.prettyPrinted]).write(to: sidecar, options: .atomic)
        return Ref(captureId: cid, type: "image", mimeType: "image/jpeg")
    }

    static func readBytes(captureId: String) throws -> Data {
        let cid = try requireId(captureId)
        let url = try inboxDirectory().appendingPathComponent("\(cid).jpg")
        guard FileManager.default.fileExists(atPath: url.path),
              let data = try? Data(contentsOf: url),
              !data.isEmpty
        else {
            throw StoreError.missing(cid)
        }
        return data
    }

    static func markUploaded(captureId: String, dest: String) throws {
        let cid = try requireId(captureId)
        let destName = dest.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !destName.isEmpty else { return }
        var meta = loadMeta(cid)
        var dests = meta["uploaded_dests"] as? [String] ?? []
        if !dests.contains(destName) {
            dests.append(destName)
        }
        meta["uploaded_dests"] = dests
        meta["capture_id"] = cid
        let sidecar = try inboxDirectory().appendingPathComponent("\(cid).json")
        try JSONSerialization.data(withJSONObject: meta, options: [.prettyPrinted]).write(to: sidecar, options: .atomic)
    }

    static func uniquePending(dest: String) throws -> String {
        let destName = dest.trimmingCharacters(in: .whitespacesAndNewlines)
        let inbox = try inboxDirectory()
        let files = (try? FileManager.default.contentsOfDirectory(at: inbox, includingPropertiesForKeys: nil)) ?? []
        var pending: [String] = []
        for url in files where url.pathExtension.lowercased() == "json" {
            let cid = url.deletingPathExtension().lastPathComponent
            guard isValidId(cid) else { continue }
            let jpg = inbox.appendingPathComponent("\(cid).jpg")
            guard FileManager.default.fileExists(atPath: jpg.path) else { continue }
            let dests = (loadMeta(cid)["uploaded_dests"] as? [String]) ?? []
            if !destName.isEmpty, dests.contains(destName) { continue }
            pending.append(cid)
        }
        if pending.isEmpty { throw StoreError.nonePending }
        if pending.count > 1 { throw StoreError.manyPending }
        return pending[0]
    }

    static func parseCaptureId(_ raw: Any?) -> String? {
        if let s = raw as? String {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.hasPrefix("$") { return nil }
            if t.hasPrefix("{"),
               let data = t.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                return parseCaptureId(obj)
            }
            return isValidId(t) ? t : nil
        }
        guard let obj = raw as? [String: Any] else { return nil }
        let cid = (obj["capture_id"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return isValidId(cid) ? cid : nil
    }

    private static func requireId(_ raw: String) throws -> String {
        let cid = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard isValidId(cid) else { throw StoreError.invalidId(raw) }
        return cid
    }

    private static func isValidId(_ raw: String) -> Bool {
        let range = NSRange(raw.startIndex..., in: raw)
        return idRegex.firstMatch(in: raw, options: [], range: range) != nil
    }

    private static func loadMeta(_ captureId: String) -> [String: Any] {
        let url = (try? inboxDirectory())?.appendingPathComponent("\(captureId).json")
        guard let url,
              let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return ["capture_id": captureId, "uploaded_dests": [String]()]
        }
        return obj
    }

    private static func randomHex(_ byteCount: Int) -> String {
        var bytes = [UInt8](repeating: 0, count: byteCount)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return bytes.map { String(format: "%02x", $0) }.joined()
    }
}
