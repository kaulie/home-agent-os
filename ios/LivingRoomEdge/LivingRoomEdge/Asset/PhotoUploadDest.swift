import Foundation

/// Shared photo dest endpoints. img-server is infrastructure, not a capability.
/// LAN identity is `img-server.local`; HTTP uses a discovered IPv4 only.
enum PhotoUploadDest {
    static let lanIdentityPublic = "http://img-server.local:8080"
    static let cloudUpload = "http://115.190.153.53:9527/api/v1/photos/upload"
    static let cloudPublic = "http://115.190.153.53:8080"

    private static let resolvedKey = "livingroom.img.lanResolvedBase"

    /// Discovered IPv4 img-server base (`http://x.x.x.x:8080`). Empty until mDNS.
    static var lanPublic: String {
        get {
            let saved = UserDefaults.standard.string(forKey: resolvedKey)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            if let ip = ipv4PublicBase(from: saved) { return ip }
            return ""
        }
        set {
            if let ip = ipv4PublicBase(from: newValue) {
                UserDefaults.standard.set(ip, forKey: resolvedKey)
            } else {
                UserDefaults.standard.removeObject(forKey: resolvedKey)
            }
        }
    }

    static var lanUpload: String {
        let base = lanPublic
        return base.isEmpty ? "" : base + "/api/v1/photos/upload"
    }

    static func applyDiscovered(host: String, port: Int) {
        guard MdnsDiscovery.isUsableLanIPv4(host), port > 0 else { return }
        lanPublic = "http://\(host):\(port)"
    }

    static func parse(_ params: [String: Any]) -> String {
        let raw = (
            (params["dest"] as? String)
                ?? (params["upload_dest"] as? String)
                ?? (params["uploadDest"] as? String)
                ?? "img_server"
        )
        .trimmingCharacters(in: .whitespacesAndNewlines)
        .lowercased()
        if raw == "cloud" { return "cloud" }
        if raw == "gdrive" || raw == "google_drive" || raw == "googledrive" {
            return "gdrive"
        }
        if raw == "dropbox" {
            return "dropbox"
        }
        return "img_server"
    }

    static func displayName(_ dest: String) -> String {
        let d = dest.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if d == "lan" || d == "local" || d == "home" || d.isEmpty { return "img_server" }
        return d
    }

    /// dest for capability output: LAN Brain → img_server, Cloud Brain → cloud.
    static func wireDest(forIntentURL intentURL: String) -> String {
        let given = BrainEndpoint.displayBase(from: intentURL)
        let cloud = BrainEndpoint.displayBase(from: BrainEndpoint.cloudBaseURL)
        if hostsMatch(given, cloud) {
            return "cloud"
        }
        return "img_server"
    }

    /// Img-server endpoints for a dest. LAN uses discovered IPv4, never `.local`.
    static func endpoints(
        _ dest: String,
        primaryIntentURL: String? = nil
    ) throws -> (upload: String, publicBase: String, probe: String) {
        switch dest {
        case "gdrive":
            throw destError("dest=gdrive is not implemented yet (Google Drive is a plugin slot only)")
        case "dropbox":
            throw destError("dest=dropbox is not implemented yet (Dropbox is a plugin slot only)")
        default:
            break
        }
        let useCloud = dest == "cloud"
            || (primaryIntentURL.map { wireDest(forIntentURL: $0) == "cloud" } ?? false)
        if useCloud {
            return (cloudUpload, cloudPublic, "http://115.190.153.53:9527/")
        }
        let publicBase = lanPublic
        guard !publicBase.isEmpty else {
            throw destError("尚未发现局域网 img-server（img-server.local）。先自动发现再上传。")
        }
        return (publicBase + "/api/v1/photos/upload", publicBase, publicBase + "/health")
    }

    private static func ipv4PublicBase(from raw: String) -> String? {
        let trimmed = BrainEndpoint.normalizeBase(raw)
        guard let host = BrainEndpoint.ipv4Host(from: trimmed) else { return nil }
        let port: Int
        if let url = URL(string: trimmed), let urlPort = url.port {
            port = urlPort
        } else {
            port = 8080
        }
        return "http://\(host):\(port)"
    }

    private static func hostsMatch(_ a: String, _ b: String) -> Bool {
        if a.compare(b, options: [.caseInsensitive, .diacriticInsensitive]) == .orderedSame {
            return true
        }
        let ha = URL(string: a)?.host?.lowercased() ?? ""
        let hb = URL(string: b)?.host?.lowercased() ?? ""
        return !ha.isEmpty && ha == hb
    }

    private static func destError(_ message: String) -> NSError {
        NSError(domain: "PhotoUploadDest", code: 1, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
