import Foundation

enum AssetTransportError: LocalizedError {
    case invalidURL(String)
    case emptyData
    case emptyLocation
    case unsupportedType(AssetType)
    case httpStatus(Int, String)
    case network(String)

    var errorDescription: String? {
        switch self {
        case let .invalidURL(s):
            return "invalid asset URL: \(s)"
        case .emptyData:
            return "empty asset data"
        case .emptyLocation:
            return "asset location is empty"
        case let .unsupportedType(t):
            return "unsupported asset type: \(t.rawValue)"
        case let .httpStatus(code, body):
            return "asset HTTP \(code): \(body)"
        case let .network(msg):
            return msg
        }
    }
}

/// Owns business-server HTTP details for digital assets (SDK-internal).
enum AssetHTTPTransport {
    /// LAN img-server base, refreshable via mDNS (`_ha-img-server._tcp`) so the
    /// SDK does not depend on a fixed LAN IP. Fallback keeps the old default.
    private static var lanBase = "http://192.168.3.73:8080"

    static var uploadURL: String { lanBase + "/api/v1/photos/upload" }
    static var downloadLatestURL: String { lanBase + "/api/v1/photos/download_latest" }
    /// Public static host for Cast / download.
    static var publicPhotoBaseURL: String { lanBase }

    /// Resolve the LAN img-server via mDNS and refresh `lanBase`.
    static func refreshLanBaseFromMdns() async {
        guard let endpoint = await MdnsDiscovery.resolve(MdnsDiscovery.imgServerType) else { return }
        lanBase = endpoint.baseURL
    }

    struct UploadResult {
        let message: String
        let durationLabel: String
        let url: String?
        let savedAs: String?
    }

    struct DownloadResult {
        let data: Data
        let suggestedFilename: String
        let durationLabel: String
        let message: String
    }

    static func uploadPhoto(fileURL: URL) async throws -> UploadResult {
        let data = try Data(contentsOf: fileURL)
        return try await uploadPhoto(data: data, filename: fileURL.lastPathComponent)
    }

    static func uploadPhoto(data: Data, filename: String) async throws -> UploadResult {
        let trimmed = uploadURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), !trimmed.isEmpty else {
            throw AssetTransportError.invalidURL(trimmed)
        }
        guard !data.isEmpty else {
            throw AssetTransportError.emptyData
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(
            Data(
                "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n"
                    .utf8
            )
        )
        body.append(Data("Content-Type: image/jpeg\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = 60

        do {
            let timed = try await RuntimeHTTP.data(for: request, label: "upload")
            guard let http = timed.http else {
                throw AssetTransportError.network("invalid upload response · \(timed.durationLabel)")
            }
            let text = String(data: timed.data, encoding: .utf8) ?? ""
            if (200 ..< 300).contains(http.statusCode) {
                let parsed = parseUploadJSON(timed.data)
                let publicURL = publicPhotoURL(savedAs: parsed.savedAs) ?? parsed.url
                let msg = text.isEmpty ? "upload ok HTTP \(http.statusCode)" : text
                return UploadResult(
                    message: "\(msg)\n⏱ \(timed.durationLabel)",
                    durationLabel: timed.durationLabel,
                    url: publicURL,
                    savedAs: parsed.savedAs
                )
            }
            throw AssetTransportError.httpStatus(
                http.statusCode,
                "\(String(text.prefix(200)))\n⏱ \(timed.durationLabel)"
            )
        } catch let timed as RuntimeHTTP.Failure {
            throw AssetTransportError.network(mapNetworkFailure(timed.nsError, kind: "upload", duration: timed.durationLabel))
        }
    }

    static func downloadLatestPhoto() async throws -> DownloadResult {
        let trimmed = downloadLatestURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard var components = URLComponents(string: trimmed), components.url != nil, !trimmed.isEmpty else {
            throw AssetTransportError.invalidURL(trimmed)
        }
        // Bust URLSession / CDN caches — this URL is stable while file content changes.
        var items = components.queryItems ?? []
        items.removeAll { $0.name == "_ts" }
        items.append(URLQueryItem(name: "_ts", value: String(Int(Date().timeIntervalSince1970 * 1000))))
        components.queryItems = items
        guard let url = components.url else {
            throw AssetTransportError.invalidURL(trimmed)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 60
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        request.setValue("no-cache", forHTTPHeaderField: "Pragma")

        do {
            let timed = try await RuntimeHTTP.data(for: request, label: "server-download")
            guard let http = timed.http else {
                throw AssetTransportError.network("invalid download response · \(timed.durationLabel)")
            }
            if !(200 ..< 300).contains(http.statusCode) {
                let text = String(data: timed.data, encoding: .utf8) ?? ""
                throw AssetTransportError.httpStatus(
                    http.statusCode,
                    "\(String(text.prefix(200)))\n⏱ \(timed.durationLabel)"
                )
            }
            guard !timed.data.isEmpty else {
                throw AssetTransportError.network("download empty body\n⏱ \(timed.durationLabel)")
            }
            let remoteName = filenameFromDownloadResponse(http) ?? "server_latest.jpg"
            // Unique local name so UI path changes and ImageView reloads.
            let localName = "latest_\(Int(Date().timeIntervalSince1970))_\(remoteName)"
            return DownloadResult(
                data: timed.data,
                suggestedFilename: localName,
                durationLabel: timed.durationLabel,
                message: "downloaded from server · \(remoteName) · \(timed.data.count) bytes\n⏱ \(timed.durationLabel)"
            )
        } catch let timed as RuntimeHTTP.Failure {
            throw AssetTransportError.network(
                mapNetworkFailure(timed.nsError, kind: "download", duration: timed.durationLabel)
            )
        }
    }

    private static func parseUploadJSON(_ data: Data) -> (url: String?, savedAs: String?) {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return (nil, nil)
        }
        let url = (obj["url"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        let savedAs = (obj["saved_as"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return (
            (url?.isEmpty == false) ? url : nil,
            (savedAs?.isEmpty == false) ? savedAs : nil
        )
    }

    /// Public photo URL: `http://115.190.153.53:8080/{saved_as}`.
    static func publicPhotoURL(savedAs: String?) -> String? {
        guard let name = savedAs?.trimmingCharacters(in: .whitespacesAndNewlines), !name.isEmpty else {
            return nil
        }
        let safe = (name as NSString).lastPathComponent
        guard !safe.isEmpty, !safe.hasPrefix(".") else { return nil }
        let base = publicPhotoBaseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return "\(base)/\(safe)"
    }

    private static func filenameFromDownloadResponse(_ http: HTTPURLResponse) -> String? {
        guard let raw = http.value(forHTTPHeaderField: "Content-Disposition") else { return nil }
        if let r = try? NSRegularExpression(pattern: #"filename\*?=(?:UTF-8''|")?([^";]+)"#, options: .caseInsensitive),
           let m = r.firstMatch(in: raw, range: NSRange(raw.startIndex..., in: raw)),
           let range = Range(m.range(at: 1), in: raw) {
            let name = String(raw[range]).trimmingCharacters(in: CharacterSet(charactersIn: "\""))
            let decoded = name.removingPercentEncoding ?? name
            let safe = (decoded as NSString).lastPathComponent
            return safe.isEmpty ? nil : safe
        }
        return nil
    }

    private static func mapNetworkFailure(_ ns: NSError, kind: String, duration: String) -> String {
        let suffix = "\n⏱ \(duration)"
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNetworkConnectionLost {
            return "\(kind) failed: network connection was lost — 确认蜂窝数据已开（可仍连着 GoPro 热点）\(suffix)"
        }
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorNotConnectedToInternet {
            return "\(kind) failed: no internet — 确认蜂窝数据已开（可在 GoPro 网上经蜂窝上云）\(suffix)"
        }
        if ns.domain == NSURLErrorDomain, ns.code == NSURLErrorTimedOut {
            return "\(kind) failed: timed out\(suffix)"
        }
        return "\(kind) failed: \(ns.localizedDescription)\(suffix)"
    }
}
