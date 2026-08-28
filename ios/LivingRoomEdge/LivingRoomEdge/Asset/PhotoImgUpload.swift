import Foundation
import Network

/// Shared img-server upload (Mac `img_upload.py` counterpart).
/// Used by `asset.upload`. Probe first; hard 10 min timeout.
enum PhotoImgUpload {
    static let hardTimeoutSec: TimeInterval = 600
    static let probeTCPTimeoutSec: TimeInterval = 1.5
    static let probeHTTPTimeoutSec: TimeInterval = 2.0

    struct Result: Sendable {
        let savedAs: String
        let publicBase: String
        let dest: String
    }

    static func requireReachable(
        dest: String,
        phase: String,
        primaryIntentURL: String? = nil
    ) async throws {
        let endpoints = try PhotoUploadDest.endpoints(dest, primaryIntentURL: primaryIntentURL)
        let ok = await probe(dest: dest, primaryIntentURL: primaryIntentURL)
        if ok { return }
        throw uploadError(
            "卡在上传（\(phase)）：图床不通 \(endpoints.probe)。先确认图片服务器在线再拍。"
        )
    }

    /// TCP then optional GET. Any HTTP response (including 404) means the host is up.
    static func probe(dest: String, primaryIntentURL: String? = nil) async -> Bool {
        guard let endpoints = try? PhotoUploadDest.endpoints(dest, primaryIntentURL: primaryIntentURL) else { return false }
        let probeURL = endpoints.probe
        guard let hostPort = hostPort(from: probeURL) ?? hostPort(from: endpoints.upload) else {
            return false
        }
        let tcpOk = await tcpConnect(host: hostPort.host, port: hostPort.port)
        if !tcpOk { return false }
        return await httpReachable(probeURL)
    }

    static func uploadFile(
        path: URL,
        dest: String,
        phase: String,
        skipProbe: Bool = false,
        primaryIntentURL: String? = nil
    ) async throws -> Result {
        let data = try Data(contentsOf: path)
        return try await uploadData(
            data: data,
            filename: path.lastPathComponent,
            dest: dest,
            phase: phase,
            skipProbe: skipProbe,
            primaryIntentURL: primaryIntentURL
        )
    }

    static func uploadData(
        data: Data,
        filename: String,
        dest: String,
        phase: String,
        skipProbe: Bool = false,
        primaryIntentURL: String? = nil
    ) async throws -> Result {
        if !skipProbe {
            try await requireReachable(dest: dest, phase: phase, primaryIntentURL: primaryIntentURL)
        }
        let endpoints = try PhotoUploadDest.endpoints(dest, primaryIntentURL: primaryIntentURL)
        guard !data.isEmpty else {
            throw uploadError("卡在上传（\(phase)）：文件为空。")
        }
        guard let url = URL(string: endpoints.upload) else {
            throw uploadError("卡在上传（\(phase)）：上传地址无效。")
        }
        do {
            return try await withHardTimeout(hardTimeoutSec, phase: phase) {
                try await multipartPost(
                    data: data,
                    filename: filename,
                    uploadURL: url,
                    publicBase: endpoints.publicBase,
                    dest: dest,
                    phase: phase
                )
            }
        } catch let err as NSError where err.domain == "PhotoImgUpload" {
            throw err
        } catch is CancellationError {
            throw uploadError("卡在上传（\(phase)）：超过 10 分钟仍未完成。")
        } catch {
            throw uploadError("卡在上传（\(phase)）：\(error.localizedDescription)")
        }
    }

    private static func multipartPost(
        data: Data,
        filename: String,
        uploadURL: URL,
        publicBase: String,
        dest: String,
        phase: String
    ) async throws -> Result {
        let boundary = "Boundary-\(UUID().uuidString)"
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\nContent-Type: image/jpeg\r\n\r\n"
                .data(using: .utf8)!
        )
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        var request = URLRequest(url: uploadURL)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body
        request.timeoutInterval = hardTimeoutSec
        let (respData, response) = try await session.data(for: request)
        let code = (response as? HTTPURLResponse)?.statusCode ?? -1
        guard (200 ..< 300).contains(code) else {
            let text = String(data: respData, encoding: .utf8) ?? ""
            throw uploadError("卡在上传（\(phase)）：HTTP \(code) \(text.prefix(160))")
        }
        let obj = (try? JSONSerialization.jsonObject(with: respData) as? [String: Any]) ?? [:]
        let saved = (obj["saved_as"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let base = publicBase.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !saved.isEmpty else {
            throw uploadError("卡在上传（\(phase)）：服务器未返回 saved_as")
        }
        return Result(savedAs: saved, publicBase: base, dest: dest)
    }

    private static func withHardTimeout<T: Sendable>(
        _ seconds: TimeInterval,
        phase: String,
        work: @escaping @Sendable () async throws -> T
    ) async throws -> T {
        try await withThrowingTaskGroup(of: T.self) { group in
            group.addTask { try await work() }
            group.addTask {
                try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                throw uploadError("卡在上传（\(phase)）：超过 10 分钟仍未完成。")
            }
            let first = try await group.next()!
            group.cancelAll()
            return first
        }
    }

    private static func tcpConnect(host: String, port: Int) async -> Bool {
        await withCheckedContinuation { cont in
            let endpoint = NWEndpoint.hostPort(
                host: NWEndpoint.Host(host),
                port: NWEndpoint.Port(rawValue: UInt16(port)) ?? .http
            )
            let conn = NWConnection(to: endpoint, using: .tcp)
            let lock = NSLock()
            var resumed = false
            let finish: (Bool) -> Void = { ok in
                lock.lock()
                defer { lock.unlock() }
                guard !resumed else { return }
                resumed = true
                conn.cancel()
                cont.resume(returning: ok)
            }
            conn.stateUpdateHandler = { state in
                switch state {
                case .ready:
                    finish(true)
                case .failed, .cancelled:
                    finish(false)
                default:
                    break
                }
            }
            conn.start(queue: .global(qos: .userInitiated))
            DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + probeTCPTimeoutSec) {
                finish(false)
            }
        }
    }

    private static func httpReachable(_ raw: String) async -> Bool {
        guard let url = URL(string: raw), !raw.isEmpty else { return true }
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = probeHTTPTimeoutSec
        do {
            _ = try await session.data(for: request)
            return true
        } catch {
            return false
        }
    }

    private static func hostPort(from raw: String) -> (host: String, port: Int)? {
        guard let url = URL(string: raw), let host = url.host, !host.isEmpty else { return nil }
        let port = url.port ?? (url.scheme == "https" ? 443 : 80)
        return (host, port)
    }

    /// Never wait forever for a route (1417 hung on waitsForConnectivity).
    static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.waitsForConnectivity = false
        config.allowsExpensiveNetworkAccess = true
        config.allowsConstrainedNetworkAccess = true
        config.timeoutIntervalForRequest = hardTimeoutSec
        config.timeoutIntervalForResource = hardTimeoutSec
        return URLSession(configuration: config)
    }()

    static let shortSession: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.waitsForConnectivity = false
        config.allowsExpensiveNetworkAccess = true
        config.allowsConstrainedNetworkAccess = true
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 30
        return URLSession(configuration: config)
    }()

    static func uploadError(_ message: String) -> NSError {
        NSError(domain: "PhotoImgUpload", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
